# Schedule Lifecycle, Locking, and Auditing

**Repository:** `github.com/croadfeldt/frc-scheduler-server`
**Document type:** Specification
**Status:** Draft for implementation
**Companion docs:**
- `AUTH_DESIGN.md` — authentication and identity
- `ARCHITECTURE.md` — overall system design
- `V2_SPEC.md` — day_config V2 model that schedules carry as input
- `HANDOFF.md` — current operational state, including live-event change-freeze

---

## Overview

Schedules and events have lifecycle states that govern who can change
what, when. This document specifies the data model, API behavior,
and audit-trail requirements for three layered concerns:

1. **Schedule lifecycle.** Draft → Lockable → Official (immutable).
2. **Working lock.** Time-boxed soft ownership for in-progress edits.
3. **Event freeze.** Administrative hold on an entire event.

Plus a cross-cutting requirement that informs all of the above:

4. **Authentication and audit trail.** Every mutation is performed
   by an authenticated user, recorded with their identity, and
   preserved permanently.

The schema groundwork for items 1–3 already exists in `app/db.py`
and partial enforcement is wired into `app/main.py`. This spec
formalizes the contract, fills the remaining gaps, and pairs the
work with the authentication-mandatory rollout (#4) so that audit
records are never anonymous from this point forward.

---

## Part 1 — Concepts and layering

The three lifecycle concepts are layered. They share a "no changes
permitted" surface but answer different questions and combine
multiplicatively. Understanding the layering matters before any of
the rules below make sense.

### Schedule lifecycle (per-schedule)

A schedule moves through three states:

- **Draft** — freshly created or in-progress. Any authenticated user
  with access to the event can read it. PATCH and DELETE permitted.
  No restrictions on structural fields (slot_map, day_config,
  practice_matches, name).

- **Locked** — an authenticated user has taken a working lock to
  prevent collisions while editing. Only the lock holder can mutate
  structural fields. Other users see "Locked by Alice" and can read
  but not write. Lock auto-expires after a TTL of inactivity (see
  Part 3).

- **Official** — `is_official=true`. **Permanently immutable in
  structure.** Once a schedule has ever been marked official, its
  structural fields are frozen forever. Mutations attempted against
  the structural fields return 409 Conflict with a "fork instead"
  hint. Non-structural fields (operational data — see Part 2) keep
  flowing as the event runs. Demoting an official schedule
  (unmark-official) is permitted but does NOT restore mutability —
  the schedule remains structurally frozen for its lifetime.

The transitions between states:

```
   ┌─────────┐  user takes lock   ┌──────────┐
   │  Draft  │ ─────────────────► │  Locked  │
   │         │ ◄───────────────── │          │
   └─────────┘  unlock or expire  └──────────┘
        │                              │
        │ mark-official                │ mark-official
        ▼                              ▼ (auto-locks)
                  ┌──────────────┐
                  │   Official   │  ← immutable structure forever,
                  │              │     even after unmark-official
                  └──────────────┘
                         │
                         │ unmark-official (admin action)
                         ▼
                  ┌──────────────┐
                  │ Was-Official │  ← structurally frozen, but no
                  │              │     longer the event's "the" one
                  └──────────────┘
```

Two important properties:

1. **Official is one-way at the structural level.** A schedule that
   has ever been official cannot have its slot_map, day_config, or
   practice_matches changed. This is the strongest guarantee in the
   system because it makes "did we accidentally change the schedule
   the event is using" structurally impossible.

2. **Editing an official schedule's structure auto-forks.** Rather
   than rejecting outright, the API can optionally fork: the
   official remains immutable; a new draft is created with
   `forked_from_id` pointing at the official; the user's edits land
   on the new draft. (See Part 5 for the fork model. Initial
   implementation may instead reject with 409; the fork-on-mutation
   behavior is a future enhancement once the lineage UI exists.)

### Working lock (per-schedule, transient)

Independent of lifecycle. Coordination mechanism, not a correctness
mechanism. The point of the working lock is to prevent two people
from independently editing the same draft and stomping each other's
work — not to prevent concurrent edits at the database level
(last-write-wins handles that).

Properties:

- Time-boxed (default 30 min TTL).
- Refreshed by heartbeat from the editor UI while the user is
  active.
- Force-takeable by anyone (including the locker themselves from
  another browser). Force-take generates an audit log entry and a
  notification to the displaced locker.
- Scoped to user, not session: the locker can edit from any tab or
  device using their identity, not the original session.
- Automatically expired by a background sweep after the TTL passes
  with no heartbeat. Expired locks are released silently with a
  `lock_event` row recording the expiration.

A working lock on an official schedule is meaningless and should be
rejected — official schedules are already immutable. Locks are only
acquired on draft schedules.

### Event freeze (per-event)

Administrative hold. When `events.locked_at` is set, the entire
event is in admin-only mode: no metadata changes, no schedule
mutations, no new schedules, no schedule deletions, no team-roster
changes. Independent of per-schedule lifecycle — an event can be
frozen with no official schedule yet, or with multiple drafts
underneath.

Without RBAC, "admin" is implemented as a single boolean flag on
the user record: `users.is_admin`. The mechanism for setting that
flag is out-of-band (database update, environment-variable
allow-list of email addresses, or similar). Only an admin can
freeze an event, and only an admin can unfreeze it.

When an event is frozen:
- All schedule mutations under it return 423 Locked
- All event metadata mutations return 423 Locked
- Read paths are unaffected
- Live result imports (TBA, Nexus) continue — see Part 2

### How the layers stack

A request to mutate a schedule is permitted only if all three
checks pass:

```
              authenticated?  ──┐
                                │
   schedule.is_official?  ──────┼──► all must allow ──► permit
                                │
   schedule.locked_by?  ────────┤
                                │
   event.locked_at?  ───────────┘
```

The order doesn't matter for the answer (any failure rejects), but
it does matter for the error message. The most specific layer wins:
event freeze > official immutability > working lock > authentication.
A user trying to edit a structurally-frozen, working-locked schedule
in a frozen event should hear about the event freeze first; if they
unfreeze the event, then about the official mark; etc. This keeps
the diagnostic conversation short.

---

## Part 2 — Mutable vs. immutable fields

Fields on a schedule fall into two classes:

**Structural fields** — what the schedule IS:

- `slot_map`
- `day_config`
- `practice_matches`
- `name`
- `assign_seed`

**Operational fields** — what's HAPPENING with it:

- `is_active` (which schedule is the event currently using)
- `is_official` (immutability flag itself)
- `locked_at`, `locked_by_user_id`, `locked_by_name`
- `official_at`, `official_by_user_id`, `official_by_name`
- Live data tables keyed by schedule_id but stored separately:
  `match_results`, `team_rankings`, `queue_status`,
  `event_live_sync` etc.
- `updated_at`

The lifecycle rules apply only to structural fields. Operational
fields update freely as the event runs — TBA results stream in,
Nexus queue state updates, the active-flag toggles when promoting
a different schedule. An official schedule's structure is frozen,
but match_results for that schedule keep arriving as matches are
played.

**Important consequence for the API contract:** the existing PATCH
endpoint must split its accepted fields into the two classes.
Structural-field PATCHes go through the lifecycle gates; operational
PATCHes (e.g., setting `is_active`) follow different rules
(documented per-endpoint).

---

## Part 3 — Working lock semantics

### Acquiring a lock

`POST /api/assigned-schedules/{id}/lock`

- 200: lock acquired or refreshed by current user; returns
  `{locked_at, locked_by_user_id, expires_at}`
- 401: caller not authenticated
- 423: schedule is already locked by a different user; response
  body includes `{locked_by_name, locked_at, expires_at,
  can_force: bool}`

Acquiring a lock the caller already holds simply refreshes
`locked_at` (heartbeat semantics on the same endpoint).

Acquiring a lock on an official schedule returns 409 with a clear
error: "Cannot lock an official schedule (already structurally
immutable)."

### Releasing a lock

`POST /api/assigned-schedules/{id}/unlock`

- 200: lock released; lock_event row written with action='unlock'
- 401: caller not authenticated
- 409: schedule is not locked
- 423: schedule is locked by a different user AND caller is not
  admin AND `force=false`. Pass `?force=true` to take the lock
  (writes a force-unlock audit row).

### Heartbeat

Optional dedicated endpoint: `POST /api/assigned-schedules/{id}/lock/heartbeat`
that updates `locked_at` to NOW() if the caller is the holder. The
acquire endpoint can serve double duty (calling acquire while
already holder = heartbeat), so a separate endpoint is not strictly
required. Implementation choice — pick one.

### TTL and expiration

- Default TTL: 30 minutes.
- The heartbeat moves `locked_at` forward, not a separate
  `last_heartbeat_at` field. A lock is "active" if `locked_at >
  NOW() - TTL`.
- A background sweep is unnecessary in v1: the lock is checked at
  request time, and an expired lock is treated as released. The
  lock_event audit row for expiration is written lazily on the
  first request that observes the expiry. (A scheduled sweep is a
  future enhancement if dashboard-level lock-status reporting needs
  to be eager.)

### Force-unlock

When a lock is force-released (by another user or by an admin), an
audit row is written with action='force-unlock' and actor_user_id
set to the *forcer*, plus a `forced_from_user_id` and
`forced_from_name` capturing whose lock was taken. The original
locker's editor UI should detect they no longer hold the lock on
their next heartbeat or save attempt and show a "Your lock was
taken by Bob" message.

### Lock UI hints

Endpoints that read schedules return a `lock_status` block alongside
the data:

```json
{
  "is_locked": true,
  "locked_by_name": "Alice",
  "locked_by_user_id": 12,
  "locked_at": "2026-05-08T15:30:00Z",
  "expires_at": "2026-05-08T16:00:00Z",
  "is_held_by_me": false,
  "can_force": true
}
```

This drives banner rendering on the editor without requiring a
separate fetch.

---

## Part 4 — Schedule lifecycle semantics

### Marking a schedule official

`POST /api/assigned-schedules/{id}/mark-official`

- Requires authentication.
- Requires NOT already official (idempotent — return 200 with
  current state if already official by same user; 409 if already
  official by different user, with `unmark-first` hint).
- Per-event uniqueness is enforced by a partial unique index on
  `(event_id) WHERE is_official = true`. Promoting a different
  schedule official requires the previous one be unmarked first;
  there is no atomic swap. (This is intentional — the explicit
  unmark step forces the user to confirm what they're undoing.)
- Sets `is_official=true`, `official_at=NOW()`,
  `official_by_user_id`, `official_by_name`.
- Acquires a lock on the schedule held by the marker. (The lock is
  largely informational at this point — official is itself stronger
  than a lock — but it preserves the "this user committed to this
  schedule" claim in the lock_events audit table.)
- Writes a history snapshot with action='mark-official'.

### Unmarking official

`POST /api/assigned-schedules/{id}/unmark-official`

- Requires authentication AND admin (since this reverses a
  meaningful commitment).
- 200: cleared. Schedule structure remains frozen — see "structural
  immutability is permanent" below.
- Releases the lock that was acquired at mark time (if still held).
- Writes a history snapshot with action='unmark-official'.

### Structural immutability is permanent

Once a schedule has been marked official, its structural fields
are frozen *forever*, even after unmark-official. The
implementation: when checking whether to permit a structural
PATCH, check `EXISTS(SELECT 1 FROM assigned_schedule_history WHERE
assigned_schedule_id = ? AND action = 'mark-official')` rather
than checking the current `is_official` flag.

This is the strongest property in the system. It means:

- An admin who unmarks a schedule cannot then "fix" something on
  it — they must fork.
- The historical record of what schedules have ever been official
  is preserved by the history table itself.
- Reasoning about "is this safe to edit" reduces to one question:
  was this schedule ever official?

Forking from an unmark-official schedule remains permitted (see
Part 5), so the user has a clear path forward — fork, edit the
fork, mark the fork official.

### Promoting active

`PATCH /api/assigned-schedules/{id}` with `{is_active: true}`

- Requires authentication.
- Sets `is_active=true` on the requested schedule and
  `is_active=false` on all other schedules in the same event in a
  single transaction.
- Writes an event-level audit row (Part 6) capturing which schedule
  was promoted, by whom, and which one was demoted.
- **Does not auto-mark official.** Active and official are
  independent concerns. A user can promote a draft to active for
  testing, then mark it official when they're confident.

### Deletion

`DELETE /api/assigned-schedules/{id}`

- Requires authentication.
- Forbidden when:
  - `is_official=true`
  - schedule has ever been official (per the historical check
    above) — keeping the row preserves the audit trail
  - schedule is currently active (`is_active=true`)
  - event is frozen
- 200: schedule deleted (cascade deletes match_rows; preserves
  history rows by FK ON DELETE SET NULL — wait, that's wrong, see
  schema notes)

Deletion semantics need a small schema review: today
`AssignedScheduleHistory` and `AssignedScheduleLockEvent` cascade
DELETE with the parent. That's fine for non-official drafts but
loses audit trail for ex-official schedules. Since deletion is
forbidden for ever-official schedules anyway, the cascade is
acceptable.

---

## Part 5 — Forks and lineage

When a user wants to change a schedule that is structurally
immutable (currently or ever-official), the API can offer a fork:

`POST /api/assigned-schedules/{id}/fork`

- Requires authentication.
- Permitted on any schedule (official or not) regardless of
  freeze/lock state — forking is a read operation against the
  source plus a write to a new row.
- Creates a new `AssignedSchedule` row with:
  - `id` newly generated
  - `event_id` same as source
  - `name` = source.name + " (fork)" or user-supplied
  - All structural fields copied from source
  - `forked_from_id` set to the source's id
  - `is_active=false`, `is_official=false`
  - Lock fields all NULL
  - `created_by` = current user
- Returns the new schedule's id. The frontend redirects the editor
  to the new schedule.

Schema addition:

```sql
ALTER TABLE assigned_schedules
  ADD COLUMN forked_from_id BIGINT REFERENCES assigned_schedules(id) ON DELETE SET NULL;
CREATE INDEX assigned_schedules_forked_from_idx ON assigned_schedules(forked_from_id);
```

The `ON DELETE SET NULL` is intentional — if the parent schedule
is somehow deleted, the fork survives as an orphan. (Normal flow
prevents this since you can't delete a parent that's been forked
from, but the FK should be defensive.)

A future UI affordance can render fork lineage as a tree:
"Schedule A (official) → Schedule A.1 (fork) → Schedule A.2 (fork
of A.1)". For v1, the `forked_from_id` is captured but the UI
treatment is minimal.

---

## Part 6 — Authentication mandatory

Effective with this spec's implementation, **every write-side API
endpoint requires an authenticated user**. The mixed
`get_current_user` / `require_auth` pattern in `app/main.py` is
unified to `require_auth` for all mutations.

### Scope

Endpoints requiring auth (anything that creates, modifies, or
deletes data):

- `POST /api/events`, `PATCH /api/events/{id}`, `DELETE /api/events/{id}`
- `POST /api/events/{id}/freeze`, `POST /api/events/{id}/unfreeze` (admin-only — see Part 7)
- `POST /api/events/{id}/teams`, `DELETE /api/events/{id}/teams/{n}`
- `POST /api/abstract-schedules`, `PATCH /api/abstract-schedules/{id}`, `DELETE /api/abstract-schedules/{id}`
- `POST /api/assigned-schedules`, `PATCH /api/assigned-schedules/{id}`, `DELETE /api/assigned-schedules/{id}`
- `POST /api/assigned-schedules/{id}/restore/{history_id}`
- `POST /api/assigned-schedules/{id}/lock`, `POST /api/assigned-schedules/{id}/unlock`
- `POST /api/assigned-schedules/{id}/mark-official`, `POST /api/assigned-schedules/{id}/unmark-official`
- `POST /api/assigned-schedules/{id}/fork`
- All TBA / Nexus / branding upload / PDF import endpoints that
  produce side effects

Endpoints remaining auth-optional (read-only public surfaces):

- `GET /api/events`, `GET /api/events/{id}`, `GET /api/events/by-key/{key}/view-payload`
- `GET /api/assigned-schedules/{id}` (the view page reads here)
- `GET /api/abstract-schedules/{id}`
- All `/auth/*` endpoints
- Static asset serving

### Migration consideration

Auth-optional endpoints that previously accepted anonymous writes
become 401. This is a breaking change for any external scripts or
saved-curl-commands that wrote data without a token. Worth
broadcasting in a deploy note. The frontend already handles auth
through the existing OAuth flow; no UI changes required for the
authenticated paths.

### Identity in audit records

Every audit row captures both `actor_user_id` (FK to users.id) and
`actor_name` (denormalized from `users.name` at action time). The
denormalization is deliberate: if a user later changes their
display name, audit rows show what their name was when they
acted.

---

## Part 7 — Admin role (interim, pre-RBAC)

A single `is_admin` boolean column on the users table:

```sql
ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX users_admin_idx ON users(is_admin) WHERE is_admin = TRUE;
```

Setting the flag is out-of-band: a database update or an
environment-variable allow-list that the user upsert path checks
against.

A preferred approach for the env-var path: `ADMIN_EMAILS=alice@example.com,bob@example.com`
read at app startup. When `upsert_user()` runs (login flow) and the
user's email matches the allow-list, set `is_admin=true`. Removing
an email from the env-var does not auto-revoke admin status — that
requires a database update. (Removing privileges in a hurry is rare
enough that the manual step is acceptable; auto-revoke would risk
locking out an admin during a config typo.)

Capabilities gated to `is_admin`:

- `POST /api/events/{id}/freeze`, `POST /api/events/{id}/unfreeze`
- `POST /api/assigned-schedules/{id}/unmark-official`
- `POST /api/assigned-schedules/{id}/unlock?force=true` against
  another user's lock
- `DELETE /api/events/{id}` when frozen

When RBAC arrives, `is_admin=true` becomes membership in an
"admins" role; the gate functions stay the same shape, the
implementation under them changes.

---

## Part 8 — Audit trail

Two existing tables already capture per-schedule history:

- `assigned_schedule_history` — content snapshots, one per mutation
- `assigned_schedule_lock_events` — lock/unlock/force-unlock events

This spec adds one more table for event-level and cross-cutting
events that don't fit the per-schedule shape:

```sql
CREATE TABLE event_audit_events (
  id              BIGSERIAL PRIMARY KEY,
  event_id        BIGINT NOT NULL REFERENCES events(id) ON DELETE CASCADE,

  -- 'freeze' | 'unfreeze' | 'create' | 'patch' | 'delete' |
  -- 'team-add' | 'team-remove' |
  -- 'schedule-create' | 'schedule-promote-active' | 'schedule-demote-active' |
  -- 'schedule-mark-official' | 'schedule-unmark-official' | 'schedule-fork' |
  -- 'schedule-delete'
  action          VARCHAR(64) NOT NULL,

  -- Optional pointer to the affected schedule (for schedule-* actions)
  assigned_schedule_id BIGINT REFERENCES assigned_schedules(id) ON DELETE SET NULL,

  -- Free-form JSON payload — action-specific details
  -- e.g., for schedule-promote-active: {"new_active_id": 5, "previous_active_id": 3}
  -- for team-remove:                   {"team_number": 2530}
  -- for patch:                         {"changed_fields": ["name", "start_date"]}
  details         JSONB,

  actor_user_id   BIGINT REFERENCES users(id) ON DELETE SET NULL,
  actor_name      VARCHAR(256),
  occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX event_audit_events_event_id_idx        ON event_audit_events(event_id, occurred_at DESC);
CREATE INDEX event_audit_events_assigned_id_idx     ON event_audit_events(assigned_schedule_id, occurred_at DESC) WHERE assigned_schedule_id IS NOT NULL;
CREATE INDEX event_audit_events_actor_idx           ON event_audit_events(actor_user_id, occurred_at DESC) WHERE actor_user_id IS NOT NULL;
```

### What gets logged where

| Event                                   | Table                              | Notes                                                        |
|-----------------------------------------|------------------------------------|--------------------------------------------------------------|
| Schedule created                        | `assigned_schedule_history` (action='create') + `event_audit_events` (action='schedule-create') | Both — content snapshot AND event-level cross-reference |
| Schedule patched (structural)           | `assigned_schedule_history` (action='patch') | Snapshot taken BEFORE applying the patch                     |
| Schedule renamed                        | `assigned_schedule_history` (action='rename') | Lightweight; only `name` changes                             |
| Schedule restored from history          | `assigned_schedule_history` (action='restore') | Snapshot of current state taken first                        |
| Schedule deleted                        | `event_audit_events` (action='schedule-delete') | History rows already exist; just need cross-reference        |
| Schedule promoted active                | `event_audit_events` (action='schedule-promote-active') | Includes previous active id in details                       |
| Schedule marked official                | `assigned_schedule_history` (action='mark-official') + `event_audit_events` | Both; the history row preserves "official-ness" forever      |
| Schedule unmarked official              | `assigned_schedule_history` (action='unmark-official') + `event_audit_events` | Both                                                          |
| Schedule forked                         | `event_audit_events` (action='schedule-fork') | Details include `forked_from_id` and new `assigned_schedule_id` |
| Lock acquired                           | `assigned_schedule_lock_events` (action='lock') | Existing                                                      |
| Lock released                           | `assigned_schedule_lock_events` (action='unlock') | Existing                                                      |
| Lock force-released                     | `assigned_schedule_lock_events` (action='force-unlock') | New action value; details include displaced user             |
| Lock expired                            | `assigned_schedule_lock_events` (action='expire') | Lazy — written when first observed                            |
| Event created                           | `event_audit_events` (action='create')             |                                                              |
| Event patched                           | `event_audit_events` (action='patch')              | `details.changed_fields` lists what changed                  |
| Event deleted                           | `event_audit_events` (action='delete')             | Cascades to schedules; the cascade itself is implicit         |
| Event frozen                            | `event_audit_events` (action='freeze')             | Admin action                                                  |
| Event unfrozen                          | `event_audit_events` (action='unfreeze')           | Admin action                                                  |
| Team added to event                     | `event_audit_events` (action='team-add')           |                                                              |
| Team removed from event                 | `event_audit_events` (action='team-remove')        |                                                              |

### Audit query patterns

The schema is designed to answer:

- "Who made this schedule what it is now?" → join history rows by
  schedule_id, ordered by occurred_at
- "When was this event frozen?" → event_audit_events filtered by
  action='freeze'
- "Show me everything Alice did this week" → event_audit_events +
  history rows + lock_events all filtered by actor_user_id (a
  unified view query that UNIONs the three is reasonable to add
  later as a materialized view if dashboards need it)
- "Was this schedule ever official?" → EXISTS query on history
  rows (the per-schedule structural-immutability check)

### Retention

No retention policy. Audit rows are kept indefinitely. They're
small, infrequent, and irreplaceable. If the table becomes
unwieldy in the far future, partition by year — but that's a
future-decade concern.

---

## Part 9 — API contract additions

This summarizes the new and changed endpoints. Existing endpoints
covered by Part 1 don't repeat their full spec here; only the new
shape is described.

### New endpoints

```
POST   /api/events/{id}/freeze              admin-only; sets locked_at
POST   /api/events/{id}/unfreeze            admin-only; clears locked_at

POST   /api/assigned-schedules/{id}/lock                        acquire or refresh
POST   /api/assigned-schedules/{id}/unlock?force=bool           release
POST   /api/assigned-schedules/{id}/lock/heartbeat              optional; refresh-only

POST   /api/assigned-schedules/{id}/mark-official                lifecycle
POST   /api/assigned-schedules/{id}/unmark-official              admin-only

POST   /api/assigned-schedules/{id}/fork                         lineage
```

### Modified endpoints

- `PATCH /api/assigned-schedules/{id}` — split structural vs
  operational PATCH semantics per Part 2; reject structural
  changes per the layered guard rules; auto-fork is OUT OF SCOPE
  for v1 (return 409 with hint instead).
- All write endpoints — switch from `Depends(get_current_user)` to
  `Depends(require_auth)` per Part 6.

### New response fields

Schedule reads (`GET /api/assigned-schedules/{id}`,
`GET .../view-payload`) include:

```json
{
  ...existing fields...,
  "lifecycle": {
    "is_active": false,
    "is_official": true,
    "ever_official": true,
    "structural_frozen": true,
    "lock_status": {
      "is_locked": true,
      "locked_by_name": "Alice",
      "locked_by_user_id": 12,
      "locked_at": "2026-05-08T15:30:00Z",
      "expires_at": "2026-05-08T16:00:00Z",
      "is_held_by_me": false,
      "can_force": true
    },
    "forked_from_id": null,
    "event_frozen": false
  }
}
```

The frontend uses `lifecycle.structural_frozen` as the
authoritative "is this read-only" signal; it ORs the immutability
sources (ever_official, event_frozen, lock-by-other) so the editor
doesn't have to reproduce the layering logic.

---

## Part 10 — Frontend implications

The editor (`static/index.html`) already shows a lock banner. Two
additions:

1. **"Mark as official" button** with a confirmation dialog stating
   the consequence: "Marking this schedule as official will lock
   its structure permanently. To make further changes, you will
   need to fork this schedule. Continue?"

2. **"Fork" button** appearing on read-only schedules (official, or
   currently locked-by-other when the user wants to start their
   own copy). Disabled when the user isn't authenticated.

The view page (`static/view.html`) does not need lifecycle
controls — it's read-only by design. It can render a small badge
indicating the active schedule is official, but no interactive
elements.

---

## Part 11 — Migration plan

The work splits into independently shippable phases. Each is a
separate PR and can be rolled forward without rolling forward the
next.

### Phase A — Auth mandatory

Smallest, most operationally critical, no schema changes.

- Switch all write-side endpoints from `get_current_user` to
  `require_auth`.
- Update the frontend to handle 401 cleanly (already mostly works
  since the OAuth flow exists; just verify error states).
- Deploy note: anonymous writes broken from this point; any
  external scripts need tokens.
- Acceptance: every write returns 401 without a token; existing
  authenticated flows work end-to-end.

This is the foundational change that makes audit trails meaningful.
Ship first.

### Phase B — `forked_from_id` schema + fork endpoint

- Migration: add `forked_from_id` column + index.
- Implement `POST /api/assigned-schedules/{id}/fork`.
- Frontend: add fork button to read-only schedules.
- Acceptance: forking an official schedule creates a new draft
  with proper lineage; view payload includes `forked_from_id`.

### Phase C — Structural immutability check

- Migration: none.
- Implement the "ever official" check on PATCH/restore using the
  existing `assigned_schedule_history` table.
- 409 response when the check fails, with a "fork instead" hint
  pointing at the fork endpoint.
- Acceptance: an unmark-official'd schedule cannot have its
  slot_map changed; fork works as the escape hatch.

### Phase D — `event_audit_events` table + audit hooks

- Migration: create the new table.
- Wire audit-row writes into every write endpoint per the table in
  Part 8. Use a small helper function so each endpoint adds one
  line.
- Acceptance: every meaningful action produces an audit row; rows
  contain actor identity for all actions performed after Phase A.

### Phase E — `is_admin` flag + admin-gated endpoints

- Migration: add `is_admin` column.
- Implement env-var allow-list in `upsert_user()`.
- Add `POST /api/events/{id}/freeze`, `unfreeze`, `unmark-official`,
  force-unlock-by-admin behavior.
- Acceptance: non-admins get 403 on admin endpoints; admin path
  works end-to-end.

### Phase F — Lock TTL + heartbeat

- Migration: none (`locked_at` already exists).
- Update lock acquisition to refresh `locked_at` if held by
  caller; treat expired locks as released.
- Frontend: add heartbeat ping while editing; handle "your lock
  was taken" state.
- Acceptance: idle editors lose locks after 30 min; heartbeats
  prevent expiry while active.

### Phase G — Lifecycle response field on reads

- No schema changes; pure read-side enrichment.
- Add `lifecycle` block to schedule GET responses per Part 9.
- Frontend: consume `lifecycle.structural_frozen` to drive the
  read-only banner instead of reproducing the layering check.
- Acceptance: the editor and view page render correctly across all
  state combinations without bespoke per-flag checks.

Phases A–C are the foundation: auth, lineage, and immutability
truth. D adds the audit infrastructure. E adds admin powers. F
makes locking time-bounded. G is polish.

---

## Part 12 — Out of scope

Items deliberately deferred:

- **RBAC.** A real role/permission system is out of scope. The
  `is_admin` flag is a known interim; replacing it is a separate
  workstream once the interaction patterns settle.
- **Cross-event permissions.** "Alice can edit events 1 and 2 but
  not 3" requires RBAC.
- **Per-schedule access control.** All authenticated users with
  access to an event can edit any non-locked, non-official
  schedule under it. Per-schedule grant lists are out of scope.
- **Auto-fork on PATCH.** v1 returns 409 with a "fork instead"
  hint. Auto-forking when the user PATCHes an immutable schedule
  is a future enhancement once the lineage UI is in place.
- **Audit log UI.** The data is captured; surfacing it as a "who
  changed what when" view is a separate workstream.
- **Lock notification system.** When Bob force-takes Alice's lock,
  Alice should know. v1 detects this on Alice's next heartbeat or
  save attempt; a real notification system (email, in-app push)
  is out of scope.
- **Background lock-sweep job.** v1 detects expiry lazily; a
  scheduled sweep is unneeded until dashboard-level reporting
  demands eagerness.

If any of these become priorities, they get their own spec.

---

## Part 13 — Layered authorization rules

This section formalizes the actor-aware enforcement layered on
top of the lifecycle states. It supersedes ad-hoc per-endpoint
checks with a single decision rule.

### Conceptual model

Three sources of restriction stack at any mutation:

1. **Authentication** (Phase A — already shipped). The user must
   carry a valid JWT.
2. **Lifecycle state** (per Part 1–4). Once-official schedules
   are structurally frozen forever; locked schedules are owned
   by the locker.
3. **Event freeze** (per Part 1). An event in frozen state is
   under administrative hold.

A request to mutate is permitted iff **every** layer permits.
The lifecycle (state) layer answers "is this kind of change
ever allowed right now"; the event freeze answers "is this user
allowed to make changes to this event right now."

### Freezer-and-admin override semantics

Event freeze is **protective, not terminal**. The freezer says
"nobody else mess with this," but retains the ability to fix
things. Specifically:

- The freezer can mutate any schedule under their frozen event.
  They can promote-active, mark-official, edit, delete drafts,
  and unfreeze. Their ownership of the lock confers trust that
  they're the right person to make changes during the freeze.
- An admin can do the same — cross-event override authority.
  Useful for recovery (the freezer is unavailable, support
  needs to act) and for system-wide concerns. The admin's
  actions are auditable like any other.
- Anyone else gets 423 with a message naming the freezer.

This mirrors the working-lock semantics from Part 3: the locker
keeps full access to the locked schedule; others are blocked.
Freeze is the same idea at the event level.

### The single guard

A function that endpoints call before any mutation:

```python
def authorize_event_mutation(
    user: dict,
    *,
    event: Event,
    schedule: AssignedSchedule | None = None,
    action: str,
) -> None:
    """Raise HTTPException if `user` is not permitted to perform
    `action` on `event` (and optionally `schedule`).

    Rules, in priority order:
      1. If admin — permitted unconditionally for all actions
         except those explicitly admin-locked-out (none currently).
      2. If event is frozen — only the freezer may mutate.
         Anyone else: 423 "Event is frozen by {locked_by_name}".
      3. If `schedule` is given and is currently working-locked —
         only the locker may mutate. Anyone else: 423.
      4. If `schedule` has ever been official — structural
         mutations forbidden. Suggest fork.
      5. Otherwise: permit.

    The order matters for error messages: most specific layer
    wins. A frozen event with a locked schedule by another user
    surfaces the freeze first; if the freeze were lifted, the
    next attempt would surface the lock.
    """
```

The guard is called from every write endpoint after authentication
(Phase A's `Depends(require_auth)`) but before any database
mutations. Endpoints stop reproducing the layering logic.

### Capability matrix (state-aware)

Each row is a capability; each column is the actor's relationship
to the event. ✓ = permitted, • = subject to additional
schedule-level checks (locked, official), ✗ = forbidden.

| Capability                                | Anonymous | Auth, no role | Schedule locker | Event freezer | Admin |
|-------------------------------------------|:---------:|:-------------:|:---------------:|:-------------:|:-----:|
| View `/view`                              | ✓ | ✓ | ✓ | ✓ | ✓ |
| Edit schedule structure (unfrozen event)  | ✗ | • | • | • | • |
| Edit schedule structure (frozen event)    | ✗ | ✗ | ✗ | • | • |
| Take working lock (unfrozen)              | ✗ | ✓ | ✓ | ✓ | ✓ |
| Take working lock (frozen)                | ✗ | ✗ | ✗ | ✓ | ✓ |
| Force-unlock another user's lock          | ✗ | ✗ | ✗ | ✗ | ✓ |
| Promote-to-active (unfrozen)              | ✗ | ✓ | ✓ | ✓ | ✓ |
| Promote-to-active (frozen)                | ✗ | ✗ | ✗ | ✓ | ✓ |
| Mark schedule official                    | ✗ | • | • | • | • |
| Unmark official                           | ✗ | ✗ | ✗ | ✗ | ✓ |
| Edit event metadata (unfrozen)            | ✗ | ✓ | ✓ | ✓ | ✓ |
| Edit event metadata (frozen)              | ✗ | ✗ | ✗ | ✓ | ✓ |
| Freeze event                              | ✗ | ✓ | ✓ | n/a | ✓ |
| Unfreeze event                            | ✗ | ✗ | ✗ | ✓ | ✓ |
| Delete event (unfrozen)                   | ✗ | ✓ | ✓ | ✓ | ✓ |
| Delete event (frozen)                     | ✗ | ✗ | ✗ | ✓ | ✓ |

The "Auth, no role" column reflects current pre-RBAC reality —
any authenticated user has these privileges. RBAC narrows that
column further, but the freezer / admin overrides on this
matrix stay the same.

### Active-schedule promotion endpoint

The active-schedule decision deserves its own endpoint because
it's structurally different from a per-schedule field PATCH:

- It's a *cross-schedule* operation (promotes one, demotes all
  others in the event)
- The authorization model is different — promotion in a frozen
  event by a non-freezer must be blocked even if both involved
  schedules are unlocked
- The audit story is cleaner with a dedicated event-level row

Proposed shape:

```
POST /api/events/{event_id}/active-schedule
Body: {schedule_id: int}

Returns: {
  event_id, active_schedule_id,
  previous_active_schedule_id,
  promoted_at, promoted_by_user_id, promoted_by_name
}
```

Behavior:
1. Calls `authorize_event_mutation(user, event=event, action="promote-active")`
2. Sets `is_active=true` on the named schedule, `is_active=false`
   on all others in the event, in a single transaction
3. Writes an `event_audit_events` row with action='schedule-promote-active'
   and details `{new_active_id, previous_active_id}`

The PATCH endpoint can keep working for backward compatibility,
but it should reject `is_active` field changes — those route
through this dedicated endpoint exclusively.

### What's enforced today vs. what's deferred

The freezer-and-admin override is **shippable now** with the
existing `events.locked_at` model and the interim `is_admin`
flag from Phase E. This part of Part 13 ships in the same change
that adds the `is_admin` column and `ADMIN_EMAILS` env-var
allow-list.

The single-guard refactor and the active-schedule promotion
endpoint are **deferred**. The current code calls the freeze
helper from each write endpoint individually; it's correct but
duplicative. Centralizing into `authorize_event_mutation` is
mechanical refactoring that doesn't change behavior but reduces
the risk of new endpoints forgetting the check. That work can
ship after the live event without disrupting anything.

### Migration impact

This part doesn't require schema changes beyond the `is_admin`
column already specified in Phase E. The behavior changes are:

- The freezer can now mutate their own frozen event (previously
  blocked along with everyone else)
- Admins can now mutate any frozen event (previously blocked)
- Admins can unfreeze events they didn't freeze (previously
  blocked)

Those are all *expansions* of who can act, never restrictions.
No previously-permitted action becomes forbidden as a result of
this part landing.

---

## Decision points

Before implementation:

1. **Auto-fork on PATCH or 409+hint?** Recommendation: 409+hint
   for v1. Auto-fork creates new schedules silently which is
   surprising; an explicit fork button makes the intent legible.
2. **Lock TTL value?** 30 minutes proposed. Defensible alternates:
   15 min (more aggressive turnover) or 60 min (more forgiving for
   slow editors). Pick one; revisit after observation.
3. **Admin allow-list mechanism?** Env var (proposed) or DB-only?
   Env var is simpler; DB-only requires a separate admin-management
   flow. Recommendation: env var for v1.
4. **Auto-mark official on promote-active?** Proposed: NO. Active
   and official are independent. A user might promote a draft to
   active for testing without committing to officiality.
5. **Allow deletion of schedules never marked official?** Proposed:
   YES (existing behavior), as long as not currently active and
   event not frozen. Forbidden once ever-official.

---

*Spec drafted with auth-mandatory rollout (Phase A) as the
operationally urgent change. Audit-trail (Phase D) and admin
flag (Phase E) follow once auth is enforced. Schema groundwork
in `app/db.py` already supports most of the model — this spec
formalizes the contract and fills the remaining gaps.*
