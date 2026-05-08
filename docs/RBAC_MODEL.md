# RBAC Model — Roles, Delegation, and Lifecycle

**Repository:** `github.com/croadfeldt/frc-scheduler-server`
**Document type:** Specification / design proposal
**Status:** Proposal — paused. Captures the role model that will replace the current `is_admin` interim flag once the live-event change-freeze lifts and the architectural direction is committed.
**Companion docs:**
- `AUTH_DESIGN.md` — earlier auth proposal; partially superseded by Phase A reality and this doc
- `SCHEDULE_LIFECYCLE.md` — lifecycle, lock, freeze model that this RBAC layer gates
- `OAUTH_SETUP.md` — Google + Apple sign-in operational setup
- `HANDOFF.md` — current operational state

---

## What this is

A design for a real role-based access control model to replace the
single `is_admin` flag proposed in `SCHEDULE_LIFECYCLE.md` Phase E.
The end state: **distribute scheduling administration to multiple
people**, identified by their Google or Apple OAuth identities,
**with the ability to delegate** roles and responsibilities to
others, **with notifications** when status changes, and **with a
request mechanism** for users to seek elevated access.

This document is design, not implementation. It describes the
shape we want, not the code that gets us there. Implementation
sequencing is in the migration section at the end.

## What this is not

- **A pre-event deliverable.** None of this ships during the
  current change-freeze. The doc captures decisions to be made
  deliberately when work resumes, not work to start now.
- **A sanctioning-body authorization model.** This is internal
  authorization for who can edit what within this tool. Sanctioning
  bodies (FIRST, FTC, etc.) don't grant or revoke access through
  this system.
- **A replacement for OAuth identity.** Google and Apple remain
  the identity providers; RBAC sits on top of authenticated
  identity to answer "what can this person do."
- **Multi-tenant isolation.** All authorized users see all events
  they have access to. Hard partitioning between organizations is
  out of scope; addressable later if needed.

---

## Why we need this

The current model after Phase A:

- Authentication is mandatory on writes
- Anyone with a Google or Apple account can sign in and become a
  user record
- Once authenticated, any user can edit any non-locked, non-official
  schedule for any event
- Locks prevent accidental concurrent edits but don't prevent
  unauthorized edits — a different authenticated user can wait for
  the lock to release, then edit
- Audit trail records what happened, but not whether it was
  permitted

For a single-school internal tool this is acceptable because the
URL isn't widely shared and trust is implicit. It stops being
acceptable when:

- The tool is shared with other teams or schools
- Multiple people legitimately need different levels of access
  (e.g., one person owns scheduling, another runs the event, a
  third manages venue logistics)
- An event organizer wants to grant an assistant temporary edit
  access without giving them admin powers
- A team coach should be able to view their team's schedule but
  not modify the event
- We need to demonstrate access controls for sanctioning-body or
  insurance-related compliance

The tool doesn't need to support all of these immediately, but the
model needs to anticipate them so we don't ship a v1 that paints
us into a corner.

---

## Design principles

These shape every decision in the rest of the doc.

### Identity-first

Roles are granted to **identities** (a `users` row, keyed by
provider + sub), not to email addresses or name strings. This is
already the data model — Phase A wired the FK linkage correctly.
Roles inherit that grounding.

### Scope-aware

A role grant exists at one of three scopes:

- **Global** — applies across all events (admins, support staff)
- **Event** — applies to a specific event (event owners, managers)
- **Schedule** — applies to a specific assigned_schedule (rare,
  for cases like "let this team review their proposed schedule")

Most grants will be event-scoped. Global is for true
administrators. Schedule scope is reserved for edge cases and may
not ship in v1.

### Delegation, with limits

A user with sufficient role can grant **the same or lesser** role
to another user. They cannot grant a higher role than they hold.
This is the standard "you can only delegate what you have"
principle. It enables organic distribution of authority without
requiring a single bottleneck admin.

### Immutable audit

Every role grant, revocation, and request is recorded permanently.
The `actor_user_id` linkage Phase A enabled extends to RBAC
operations. A revoked role doesn't disappear from the audit log —
it gets a revocation row.

### Honest defaults

The default for any unauthenticated user: read-only access to
public surfaces (the `/view` page). The default for any
authenticated user with no roles: same as unauthenticated. They
can sign in, but signing in alone doesn't grant edit access. This
prevents the current "anyone with a Google account can edit"
state.

### Reversible decisions

Every role action can be undone. Granting can be revoked,
revocations can be re-granted, requests can be withdrawn. Hard
deletes are avoided in favor of state transitions with audit
rows, so post-hoc analysis (and post-hoc undo) remains possible.

---

## Role hierarchy

Five roles, ordered by authority. Each higher role implicitly
holds the capabilities of all lower roles in the same scope.

### Global roles (apply across all events)

**Admin**
- Grant, revoke, or modify any role at any scope (including other
  Admins)
- Override any lock or freeze, including unmark-official
- Delete events (subject to existing freeze rules)
- Manage system-wide settings, integrations, and feature flags
- View audit trails for any event
- Cannot be revoked by anyone except another Admin (with the
  caveat that "the last Admin cannot revoke themselves" — see
  bootstrapping)

**Support**
- View any event and its schedules read-only
- Cannot edit, lock, or modify any data
- Cannot grant roles to others
- Used for: helping users debug their own events without granting
  edit authority. Useful for cross-organization support.

### Event-scoped roles (apply to a specific event)

**Owner**
- Full control of the event: edit metadata, create/delete
  schedules, mark official, freeze/unfreeze
- Grant Manager or Viewer roles for this event
- Cannot grant Owner role to others (only Admin can do that)
- Multiple owners per event allowed
- The user who creates an event is automatically granted Owner
  for it

**Manager**
- Edit existing schedules, take working locks, mark official
- Cannot create or delete schedules
- Cannot freeze or unfreeze the event
- Cannot grant any roles
- Used for: assistant scheduler, event coordinator who handles
  day-of changes

**Viewer**
- View the event and all its schedules, including draft schedules
  not yet published
- Cannot make any changes
- Cannot grant any roles
- Used for: judges, volunteers, team coaches who need preview
  access before publishing

### Implicit role: Public

Anyone (authenticated or not) has read-only access to the `/view`
page for any event whose URL they have. This isn't a granted role
— it's the default. Public access:
- Sees only the currently active schedule (not drafts)
- Sees only the published event metadata, no internal notes
- Cannot see the audit log, role grants, or other events

---

## Capability matrix

Mapping every capability to the roles that have it. Read top-to-bottom.

| Capability                                 | Public | Viewer | Manager | Owner | Support | Admin |
|--------------------------------------------|:------:|:------:|:-------:|:-----:|:-------:|:-----:|
| View `/view` page (public surface)          | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| View draft schedules                        |   | ✓ | ✓ | ✓ | ✓ | ✓ |
| View event audit log                        |   |   | ✓ | ✓ | ✓ | ✓ |
| Take a working lock                         |   |   | ✓ | ✓ |   | ✓ |
| Edit schedule structure                     |   |   | ✓ | ✓ |   | ✓ |
| Mark schedule official                      |   |   | ✓ | ✓ |   | ✓ |
| Unmark official                             |   |   |   | ✓ |   | ✓ |
| Create new schedules                        |   |   |   | ✓ |   | ✓ |
| Delete non-official schedules               |   |   |   | ✓ |   | ✓ |
| Edit event metadata                         |   |   |   | ✓ |   | ✓ |
| Freeze / unfreeze event                     |   |   |   | ✓ |   | ✓ |
| Force-unlock another user's lock            |   |   |   | ✓ |   | ✓ |
| Grant Viewer role on this event             |   |   |   | ✓ |   | ✓ |
| Grant Manager role on this event            |   |   |   | ✓ |   | ✓ |
| Grant Owner role on this event              |   |   |   |   |   | ✓ |
| Grant Support role (global)                 |   |   |   |   |   | ✓ |
| Grant Admin role (global)                   |   |   |   |   |   | ✓ |
| Approve/deny role requests on this event    |   |   |   | ✓ |   | ✓ |
| Approve/deny role requests globally         |   |   |   |   |   | ✓ |
| Delete an event                             |   |   |   | ✓ |   | ✓ |
| View activity across all events             |   |   |   |   | ✓ | ✓ |

A few specific observations:

- **Manager can mark official but not unmark.** Marking is a
  forward commitment ("yes, this is the schedule"); unmarking is a
  reversal of someone else's decision and stays with the Owner.
- **Owner can force-unlock.** Practical reality: someone takes a
  lock and walks away. Owner needs to reclaim the schedule.
  Force-unlock generates a noisy audit row and a notification to
  the displaced locker.
- **Only Admin can grant Owner.** Owner is a significant
  delegation; we don't want one Owner cascading the role to
  others without explicit Admin involvement. Owners *can* grant
  Manager and Viewer (the lesser roles within their event), which
  covers most delegation needs.
- **Support is read-only across events.** It's the "I'm helping
  Chris debug his event" role. It doesn't change anything; it can
  see anything.

---

## Data model

Three new tables plus extensions to existing tables.

### `roles` (lookup)

Static enum-like table listing the role types.

```sql
CREATE TABLE roles (
  id          SMALLINT PRIMARY KEY,
  name        VARCHAR(32) NOT NULL UNIQUE,
  scope_kind  VARCHAR(16) NOT NULL,  -- 'global' | 'event' | 'schedule'
  description TEXT
);

INSERT INTO roles (id, name, scope_kind, description) VALUES
  (1, 'admin',   'global', 'Full system control, including granting any role'),
  (2, 'support', 'global', 'Read-only access across all events for debugging assistance'),
  (3, 'owner',   'event',  'Full control of an event including delegating Manager and Viewer'),
  (4, 'manager', 'event',  'Edit existing schedules, take locks, mark official'),
  (5, 'viewer',  'event',  'Read drafts and audit logs without edit access');
```

The lookup table form lets us add a `permissions` JSONB column
later without schema migration if specific capabilities need to
become tunable. For v1, role → capability is hardcoded in the
authorization checker.

### `role_grants`

The actual role assignments.

```sql
CREATE TABLE role_grants (
  id           BIGSERIAL PRIMARY KEY,
  user_id      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role_id      SMALLINT NOT NULL REFERENCES roles(id),

  -- Scope columns. Exactly one of (event_id, schedule_id) is
  -- non-null when the role is event- or schedule-scoped; both
  -- are null for global roles. Enforced by check constraint.
  event_id     BIGINT REFERENCES events(id) ON DELETE CASCADE,
  schedule_id  BIGINT REFERENCES assigned_schedules(id) ON DELETE CASCADE,

  -- Lifecycle
  granted_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
  granted_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  -- Soft revocation. NULL = active. Non-NULL = revoked.
  revoked_at         TIMESTAMPTZ,
  revoked_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
  revoke_reason      TEXT,

  -- Optional expiration (e.g., "Manager for the next 30 days")
  expires_at         TIMESTAMPTZ,

  CONSTRAINT scope_consistency CHECK (
    (event_id IS NULL AND schedule_id IS NULL) OR
    (event_id IS NOT NULL AND schedule_id IS NULL) OR
    (event_id IS NULL AND schedule_id IS NOT NULL)
  )
);

CREATE INDEX role_grants_user_active_idx
  ON role_grants(user_id) WHERE revoked_at IS NULL;
CREATE INDEX role_grants_event_active_idx
  ON role_grants(event_id) WHERE revoked_at IS NULL AND event_id IS NOT NULL;
CREATE UNIQUE INDEX role_grants_unique_active_idx
  ON role_grants(user_id, role_id, COALESCE(event_id, 0), COALESCE(schedule_id, 0))
  WHERE revoked_at IS NULL;
```

The unique-active index prevents granting the same role twice.
Granting Manager-of-event-5 to a user who already has it
returns the existing grant (idempotent) rather than creating a
duplicate.

Soft revocation (rather than DELETE) preserves the historical
record. A revoked grant is invisible to authorization checks but
visible in audit views.

### `role_requests`

User-initiated requests for a role. Pending requests await
approval; approved requests trigger a `role_grants` insert.

```sql
CREATE TABLE role_requests (
  id           BIGSERIAL PRIMARY KEY,
  user_id      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role_id      SMALLINT NOT NULL REFERENCES roles(id),

  -- Scope (same shape as role_grants)
  event_id     BIGINT REFERENCES events(id) ON DELETE CASCADE,
  schedule_id  BIGINT REFERENCES assigned_schedules(id) ON DELETE CASCADE,

  -- User's reason for the request — shown to approvers
  reason       TEXT,

  -- Lifecycle
  requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  -- Status: 'pending' | 'approved' | 'denied' | 'withdrawn'
  status       VARCHAR(16) NOT NULL DEFAULT 'pending',
  resolved_at         TIMESTAMPTZ,
  resolved_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
  resolution_note     TEXT,
  resulting_grant_id  BIGINT REFERENCES role_grants(id) ON DELETE SET NULL,

  CONSTRAINT scope_consistency CHECK (
    (event_id IS NULL AND schedule_id IS NULL) OR
    (event_id IS NOT NULL AND schedule_id IS NULL) OR
    (event_id IS NULL AND schedule_id IS NOT NULL)
  )
);

CREATE INDEX role_requests_pending_idx
  ON role_requests(status, requested_at) WHERE status = 'pending';
CREATE INDEX role_requests_event_pending_idx
  ON role_requests(event_id, status) WHERE status = 'pending' AND event_id IS NOT NULL;
```

A request is a separate object from the grant it eventually
creates. This lets us preserve the request narrative (the
`reason` field, the resolution note) even after the grant itself
is later revoked.

### `notifications`

Lightweight in-app notification queue. Users see their unread
notifications when they sign in.

```sql
CREATE TABLE notifications (
  id              BIGSERIAL PRIMARY KEY,
  user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,

  -- 'role_granted' | 'role_revoked' | 'role_request_approved' |
  -- 'role_request_denied' | 'role_requested' (sent to approvers) |
  -- 'lock_force_taken' | 'event_frozen' | 'event_unfrozen'
  kind            VARCHAR(64) NOT NULL,

  -- Free-form payload — kind-specific data the renderer uses
  payload         JSONB NOT NULL DEFAULT '{}',

  -- Read state
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  read_at         TIMESTAMPTZ,
  dismissed_at    TIMESTAMPTZ
);

CREATE INDEX notifications_user_unread_idx
  ON notifications(user_id, created_at DESC) WHERE read_at IS NULL;
```

Email notifications are out of scope for v1 — in-app only. Once
this works in-app, an opt-in email digest can be layered on top
without changing this table's shape.

### Extensions to existing tables

The `users` table doesn't need any new columns. The `is_admin`
flag from the lifecycle spec's Phase E is replaced by a row in
`role_grants` with `role_id = 1` (admin) and null scope. Cleaner.

Audit tables (`assigned_schedule_history`,
`assigned_schedule_lock_events`, future `event_audit_events`)
keep their existing shape. New audit kind: `role_grant`,
`role_revoke`, `role_request_resolve` — captured by an extension
to whatever cross-cutting audit table exists by then.

---

## Authorization checker

A single function the codebase calls before any sensitive action:

```python
def can(user: User, capability: str, *,
        event: Event | None = None,
        schedule: AssignedSchedule | None = None) -> bool:
    """Return True if `user` has `capability` for the given scope.

    Capability strings are stable identifiers like
    'schedule.edit', 'event.freeze', 'role.grant.manager'.
    """
```

The checker collects all of the user's active role grants whose
scope matches (or is broader than) the requested scope, then
checks whether any of those roles holds the requested capability.

Two principles in the implementation:

- **Capability strings, not role checks.** Endpoints check
  `can(user, 'schedule.edit', event=...)`, never
  `if user.role == 'manager'`. The capability map can change
  without the endpoint changing.
- **Default deny.** Unknown capability strings return False with
  a logged warning. Role grants that don't cover the requested
  scope return False silently.

The capability strings inventory (subject to refinement):

```
schedule.view                  schedule.edit
schedule.lock.acquire          schedule.lock.force_release
schedule.mark_official         schedule.unmark_official
schedule.create                schedule.delete
schedule.fork

event.view                     event.view_drafts
event.edit_metadata            event.freeze
event.unfreeze                 event.delete
event.audit.view

role.grant.viewer              role.grant.manager
role.grant.owner               role.grant.support
role.grant.admin
role.revoke.<role>             role.request.resolve

system.audit.view              system.support_view
```

---

## Notification flow

Every state change in the RBAC graph produces a notification for
the affected user, stored in the `notifications` table.

### Triggering events

| Event | Notify whom | Notification kind |
|-------|-------------|-------------------|
| User receives a role grant | The user receiving the role | `role_granted` |
| User's role is revoked | The user who lost the role | `role_revoked` |
| User submits a role request | All users who can resolve it (Owner of the event for event-scoped, Admin for global) | `role_requested` |
| Role request is approved | The requester | `role_request_approved` |
| Role request is denied | The requester | `role_request_denied` |
| User's lock is force-taken | The displaced locker | `lock_force_taken` |
| Event is frozen | All Owners and Managers of the event | `event_frozen` |
| Event is unfrozen | Same | `event_unfrozen` |

### Display

The editor UI shows an unread badge in the top nav. Clicking
opens a panel listing recent notifications with action links
("View grant", "Reply", "Dismiss"). Read state is per-user;
dismissing removes from the panel but preserves in the table for
audit.

### Out of scope (for v1)

- Email delivery
- Push notifications (mobile)
- SMS
- Notification preferences (frequency, opt-out per kind)
- Real-time push to active sessions (notification appears on
  next page load instead)

These are layerable atop the in-app store without changing it.

---

## User-facing flows

The five flows that matter most.

### Flow 1: Bootstrap (first Admin)

The system needs a way to create the first Admin. Without it, no
roles can be granted. Options:

**A — environment variable allow-list (recommended for v1).**
`ADMIN_EMAILS=alice@example.com` checked in `upsert_user()` at
login time. If the user's email matches and they don't already
have a global Admin grant, one is created automatically with
`granted_by_user_id = NULL` (system-issued). Removing the email
later doesn't revoke; that requires explicit revocation.

**B — bootstrap CLI command.** A management script
`./scripts/grant_admin.py --email alice@example.com` that any
deployment operator with database access can run. More explicit
but requires another moving piece.

**C — first-user-becomes-admin.** Whoever creates the first
account gets Admin. Simple but unsafe if the deployment is
public-facing before configuration is complete.

Recommended: **A** with **B** as a safety valve for emergencies.

### Flow 2: Granting a role

A user with grant authority (Owner for Manager/Viewer in their
event, Admin for any role) navigates to Event Settings → Members
→ Add member.

```
┌─────────────────────────────────────────────────┐
│ Add member to "2026 MN State Tournament"        │
│                                                 │
│ Email: [alice@example.com         ]             │
│ Role:  [▼ Manager                  ]            │
│ Reason (optional):                              │
│ [                                  ]            │
│                                                 │
│ [Cancel]              [Send invitation]         │
└─────────────────────────────────────────────────┘
```

Behavior:

1. **If alice@example.com matches an existing user:** the grant
   is created immediately. Alice gets a `role_granted`
   notification on next sign-in.
2. **If alice@example.com doesn't match a user yet:** a pending
   grant is queued, keyed by email. When Alice signs in for the
   first time and her email matches, the grant activates. (This
   solves the "I want to invite someone who hasn't logged in
   yet" case without inventing a separate invitation system.)

### Flow 3: Requesting a role

Any authenticated user can request a role they don't have. This
is the "I need access to this event" path.

The user navigates to the event's `/view` page and sees a
"Request edit access" link. Clicking opens:

```
┌─────────────────────────────────────────────────┐
│ Request access to "2026 MN State Tournament"    │
│                                                 │
│ Role:  [▼ Manager                  ]            │
│ Reason (required):                              │
│ [I help run the queueing for this event and    │
│  need to update the schedule on day-of.       ] │
│                                                 │
│ [Cancel]              [Send request]            │
└─────────────────────────────────────────────────┘
```

The request goes to all Owners of the event (Admins also see all
requests system-wide). Owners receive a `role_requested`
notification and can approve or deny:

```
┌─────────────────────────────────────────────────┐
│ Access request: alice@example.com               │
│                                                 │
│ Wants:    Manager of 2026 MN State Tournament   │
│ Reason:   "I help run the queueing for this    │
│           event and need to update the schedule │
│           on day-of."                           │
│ Sent:     2 hours ago                           │
│                                                 │
│ Note (optional, sent to alice):                 │
│ [                                  ]            │
│                                                 │
│ [Deny]                          [Approve]       │
└─────────────────────────────────────────────────┘
```

Approval creates the grant; denial closes the request with the
note. Alice gets a notification either way.

### Flow 4: Revoking a role

Symmetric to granting. From Event Settings → Members:

```
Members of "2026 MN State Tournament"

  Chris Roadfeldt    Owner    granted by system        [⋯]
  Alice Cooper       Manager  granted by Chris         [⋯]
  Bob Smith          Viewer   granted by Chris         [⋯]
                                                        │
                                                        ├ Edit role
                                                        ├ View activity
                                                        └ Revoke role
```

Revoking sets `revoked_at`, `revoked_by_user_id`, optional
`revoke_reason`. The revoked user gets a `role_revoked`
notification on next sign-in. The grant row stays in the
database (soft revoke) for audit.

### Flow 5: Self-service status check

Every user has a "My access" page showing what they have:

```
Your roles

  Global
    (none)

  By event
    2026 MN State Tournament    Owner       since Apr 12, 2026
    2026 MN District Northwest  Manager     since May 1, 2026
                                            granted by Chris Roadfeldt
                                            expires Jun 30, 2026  ⓘ

  Active requests
    2026 District 8112 Regional  Viewer    pending  ⓘ
```

This answers "what can I do" without requiring a support ticket.
The expiration tooltip shows when the grant lapses; pending
requests link to the request detail.

---

## Edge cases and rules

### Last Admin protection

The system must always have at least one active Admin grant. The
revoke action checks this before applying:

```
If revoke would leave zero active Admin grants:
  refuse with "Cannot revoke the last Admin"
```

Workaround: grant Admin to another user first, then revoke.

### Grant cycles

There are none possible — roles don't reference each other; a
user's grants don't depend on another user's grants. A user can
grant a role to themselves (no), the checker prevents this:

```
If grantor.user_id == grantee.user_id:
  refuse with "Cannot grant a role to yourself"
```

This avoids the "Owner gives themselves Admin" path. Admin is
granted only by other Admins.

### Event deletion cascades

When an event is deleted (Owner or Admin action), all
event-scoped role grants on it are cascaded by FK
`ON DELETE CASCADE`. The `role_grants` rows are deleted, not
soft-revoked, because the event itself is gone. Audit trail for
the deletion captures the user identities that lost roles, but
the granular grant rows are not preserved.

If preserving grant history through event deletion matters, the
FK becomes `ON DELETE SET NULL` and the rows live as orphans
referring to a deleted event. Decision deferred; v1 takes the
simpler cascade.

### User account deletion

If a user account is deleted (rare, but possible for
GDPR-compliance or testing), `ON DELETE CASCADE` removes all
their role grants and requests. Audit rows referring to them set
`actor_user_id` to NULL but preserve `actor_name`. This matches
the existing pattern.

### Provider-collision case

A human signs in via Google (creates user row 1), later signs in
via Apple (creates user row 3). The two rows are independent;
roles granted to row 1 don't apply to row 3. This is consistent
with the existing OAuth model.

If we later add identity unification (the `person` table pattern
mentioned in `OAUTH_SETUP.md`), grants would migrate from `user_id`
to `person_id`. Pre-unification, the grant flow tells the user
"You also need to grant this role to your other identity" if they
sign in with a different provider.

### Expiration handling

Grants with `expires_at` set become inactive automatically when
the timestamp passes. The authorization checker filters out
expired grants by `WHERE expires_at IS NULL OR expires_at > NOW()`.

A nightly background job (when we have one) could write
`role_expired` notifications a few days before lapse, but v1
doesn't include scheduled work — expiration is silent until the
user notices they can't act anymore.

### Schedule-scoped roles

Reserved but not implemented in v1. The data model supports them
(`schedule_id` column on `role_grants`), but the UI flows and
capability checker treat them as "not yet supported."

The intended use case: "Grant Team 2530 view access to draft
schedule X so their coach can review their match assignments
before the schedule is published." Out of scope for now.

---

## Implementation phases

This work decomposes into independently shippable phases. Each
phase produces shippable value on its own; the user-facing flows
build up incrementally.

### Phase R-1 — Schema and authorization checker

- Migration: create `roles`, `role_grants`, `role_requests`,
  `notifications` tables
- Implement `can(user, capability, ...)` checker
- Replace the `is_admin` flag references in
  `SCHEDULE_LIFECYCLE.md` Phase E with role grants
- Bootstrap path: env-var-based first-Admin grant in
  `upsert_user()`
- No UI work yet — checker is consumed by API gates only

Acceptance: `can()` returns correct results for every capability
× scope × role combination in the matrix. Default deny on
unknown capabilities.

### Phase R-2 — Owner/Manager/Viewer event-scoped enforcement

- Wire `can()` into all event and schedule write endpoints
- Replace per-endpoint authorization checks (currently:
  "is the user authenticated") with capability checks
- Auto-grant Owner role to event creators
- API endpoints for role grant/revoke (operating on
  `role_grants` directly; UI still TBD)

Acceptance: an authenticated user without an event role gets 403
on any write to that event. Owners can grant Manager and Viewer
via API. End-to-end test: alice creates event, grants bob
Manager, bob can edit; alice revokes, bob gets 403.

### Phase R-3 — In-app notifications

- Migration: `notifications` table (already in R-1; this phase
  wires the producers)
- Notification writes triggered by every role/lock/freeze action
- API endpoint for fetching unread notifications
- Editor UI: unread badge + notifications panel

Acceptance: granting a role to alice writes a `role_granted`
notification she sees on next sign-in. Dismissing a notification
sets `dismissed_at` but doesn't delete the row.

### Phase R-4 — Member management UI

- "Members" panel in event settings
- Add/edit/revoke role flows from the UI
- Email-based grants for users who haven't signed in yet
  (pending grant queue)

Acceptance: end-to-end UI test where a user with Owner role
adds a Manager via the panel, and the Manager can edit on next
sign-in.

### Phase R-5 — Role requests

- Migration adds `role_requests` columns if not in R-1
- "Request access" link on `/view` page for unauthorized users
- Request submission flow + approval/deny UI
- Notifications to approvers on request, to requester on
  resolution

Acceptance: bob (no role) requests Manager of alice's event;
alice sees a notification, approves; bob gets approval
notification and can edit.

### Phase R-6 — Self-service "My access" page

- Page listing all the user's active grants and pending requests
- Linked from a top-nav user menu

Acceptance: navigation discoverability + correct data display.

### Phase R-7 — Expiration + revocation polish

- Migration adds `expires_at` if not in R-1
- Honor expiration in checker
- Revocation UI shows reason field
- Audit log surfaces all role lifecycle events

Acceptance: setting an expiration causes the grant to stop being
honored after the timestamp without any background job needed.

### Out of scope for this work

- Email notifications
- Push notifications
- Per-user notification preferences
- Schedule-scoped roles (data model supports; UX deferred)
- Identity unification across OAuth providers
- Multi-tenant organization isolation
- API tokens for external automation
- Role templates ("FRC standard event template" with pre-defined
  Owner + 2 Manager slots)

Each is a separate workstream once the core RBAC ships.

---

## Open design questions

Worth discussing before R-1 implementation begins.

**1. Should "Manager" be able to grant "Viewer"?** Currently the
matrix says no — only Owner can grant any role. Allowing
Managers to grant Viewer would distribute the workload but
muddies the "delegation requires equal-or-higher authority"
principle. Recommendation: stick with Owner-only for v1, revisit
if it becomes a friction point.

**2. Should grant approval be one-touch or two-touch?** The
current design is one-touch (Owner grants directly). A two-touch
model (Owner proposes, second Owner confirms) adds a check
against accidental or malicious grants but doubles the
coordination cost. Recommendation: one-touch for v1, two-touch
behind a future "high security" event setting.

**3. Should expiration be required for some role types?** E.g.,
Manager grants must expire within 90 days, Viewer grants must
expire within 30 days, Owner is permanent. Forces periodic
review. Recommendation: optional in v1, revisit based on
real-world usage.

**4. How do we handle unregistered email grants long-term?**
Pending grants keyed by email work for the "invite someone who
hasn't signed in" case, but they accumulate if the invitee never
signs in. Recommendation: pending grants expire after 90 days
unless explicitly extended, with a notification to the granter
before expiration.

**5. Should "Support" be tracked per session or per grant?**
Granting Support permanently is broad — they can read anything
for as long as the grant lasts. An alternative is "Support mode"
that requires re-auth and logs the session start/end with a
reason. Recommendation: permanent grant for v1; if abuse or
auditability concerns emerge, layer session-bound Support on top.

**6. Capability strings — granular or coarse?** The list above
is moderately granular (separate `schedule.edit` and
`schedule.create`). More granular (`schedule.edit.day_config`,
`schedule.edit.match_assignments`) would let us craft narrower
roles, but multiplies maintenance. Recommendation: stay at the
current granularity; subdivide only when a real use case demands.

**7. Audit retention?** Same as
`SCHEDULE_LIFECYCLE.md` — no retention policy, kept indefinitely.
Role grant tables are small (one row per grant lifecycle event).

---

## Decision points

Before implementation begins:

1. **Bootstrap mechanism: env var, CLI, or first-user-wins?**
   Recommendation: env var with CLI safety valve.
2. **Phase ordering: ship R-1 + R-2 (back-end enforcement) before
   any UI?** Recommendation: yes — ungraceful 403s are better
   than ungated writes, and the UI can be staged in over R-3
   through R-6.
3. **Replace `AUTH_DESIGN.md`'s `EventManager` proposal entirely?**
   Recommendation: yes; this doc supersedes that section. The
   per-event-roles concept is preserved but generalized.
4. **Coexistence with the lifecycle spec's `is_admin` flag?**
   Recommendation: this doc's R-1 migration replaces the
   `is_admin` flag with role grants. The lifecycle spec's Phase E
   becomes a no-op in light of the RBAC work — its capabilities
   are absorbed into the Admin role.
5. **Do nothing during the change-freeze.** This whole document
   is a paused proposal. No code changes ship until the live
   event concludes and architectural direction is committed.

---

*Draft captures the role model, delegation rules, notification
flow, and request lifecycle. Implementation starts after the
live-event change-freeze lifts and decisions on the open
questions are made deliberately. The data model and authorization
checker (R-1) are the foundation everything else builds on; that
phase should ship before any UI work begins.*
