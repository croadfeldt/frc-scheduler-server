# HANDOFF

State of the world for the next person picking up the FRC Match Scheduler
project. Practical, terse, code-anchored — same convention as the rest of
`docs/`. Read this first if you're new to the codebase or coming back
after a gap.

Last updated: 2026-05-10, end of the practice-import-from-MatchMaker-xlsx
debugging session, render-pdf auth removal, session-deliverable protocol
documentation, cycle-time-change off-by-one regression fix,
documentation-status sweep surfacing the RBAC + lifecycle workstreams,
and a follow-up audit of the UI-side schedule-quality tools that
produced a roadmap doc for exposing the `scheduler_eval` harness work
in the UI. Three layered xlsx-import bugs in §4.7, auth-removal in
§4.8, doc convention in §4.9, cycle-change semantics in §4.10. Three
new tracked workstreams in §5.6 (RBAC), §5.7 (lifecycle phases D/F/G),
and §5.8 (UI exposure of harness quality data).

---

## 1 · Where we are

The scheduler operates under **FRC §10.5.2 paramount lexicographic semantics**.
Cooldown is paramount; the remaining criteria are compared lexicographically.
The Python SA + post-passes implement this; the import + assign + view paths
all surface FRC compliance state to the user.

| Workstream | Status | Notes |
|------------|--------|-------|
| V2 day_config (phases 0–5c)                                     | ✓ | Complete from prior sessions. |
| View UX overhaul                                                 | ✓ | Status pills, field-position alliance, source-aware tints. |
| **Phase 0a — Lex score**                                         | ✓ | `score_tuple_for_schedule` returns 8-element tuple; SA accept/reject lex-compare. |
| **Phase 0b — Hard cooldown filter**                              | ✓ | `_swap_preserves_cooldown` filters violations BEFORE state mutation. ~5x SA speedup. |
| **Phase 0c — Targeted move generator**                           | ✓ | Biases SA toward duplicate-pair bottlenecks. 1/3 partner-targeted, 1/3 opponent-targeted, 1/3 random. |
| **Phase 1 — R/B post-pass**                                      | ✓ | `app/post_passes/rb_balance.py`. Whole-match flip + SA. 8 commutativity tests. |
| **Phase 2 — Sykes station post-pass**                            | ✓ | `app/post_passes/station_balance.py`. Within-alliance permutation + SA-from-greedy. 12 commutativity tests. |
| Iteration sweep + K* analysis                                    | ✓ | K* > 5M; practical ceiling at 5M. See `docs/scheduler/ITERATION_CEILING.md`. |
| Quality presets (fair/good/best/maximum)                         | ✓ | `app/quality_presets.py`. |
| Competition-approved checkbox + audit trail                      | ✓ | DB columns + `app/frc_compliance.py` + UI surfaces in index + view. |
| /assign chunking fix                                             | ✓ | Each worker runs full SA budget; best-of-N over independent trials. |
| /assign auth-header bug fix                                      | ✓ | `assignTeams()` was sending raw fetch with no Authorization. |
| EventTeam.team_number bug fix                                    | ✓ | Seven sites in main.py; replaced with proper join through `Team.number`. |
| MatchMaker import path                                           | ✓ | `state_qual_schedule.txt` → FMS xlsx → import flow. Practice sheet supported. |
| Practice-import wiring (storage + UI + commit)                   | ✓ | XLSX/CSV cache stores practice; preview UI renders it; commit body sends it. |
| Import flow event-id resolution                                  | ✓ | `ensureEventLoadedForImport` helper used by 3 import call sites. |
| MatchMaker comparison language softened                          | ✓ | Removed all "beats MatchMaker" / "OURS WINS" framing across UI + tests + docs. |
| **Practice-from-MatchMaker-xlsx** (this session)                 | ✓ | Stale-cache invalidation + datetime time-cell handling + derived practiceDay. §4.7. |
| **Print + export unauthenticated** (this session)                | ✓ | `render-pdf` no longer requires auth; matches `/teams/export` posture. §4.8. |
| **Session-deliverable protocol documented** (this session)       | ✓ | Two-tarball + commit-ready-commands + commit-message-style convention canonicalised in `REPRODUCTION_PROMPT.md`. §4.9. |
| **Cycle-change off-by-one regression** (this session)            | ✓ | `afterMatch=N` now correctly applies new ct to gap N→N+1 per V2_SPEC §7 (was N+1→N+2). Six application sites fixed. §4.10. |
| Schedule lifecycle (Phases A/B/C/E shipped; D/F/G open)          | ◐ | Auth-mandatory + fork + structural-immutability + is_admin shipped. `event_audit_events` table, lock TTL/heartbeat, lifecycle response field deferred. See `docs/SCHEDULE_LIFECYCLE.md` and §5.7. |
| RBAC (proper roles + permissions)                                | ☐ | Designed in `docs/RBAC_MODEL.md` (5 roles, 7 phases R-1..R-7); zero implementation. Current model is interim `is_admin` flag. Paused pending change-freeze lift + open-question decisions. §5.6. |
| UI exposure of `scheduler_eval` quality data                     | ☐ | Designed in `docs/UI_QUALITY_EXPOSURE.md` — 4-tier plan to surface per-pair / per-team / lex-tuple / reference-comparison detail in the editor + viewer. Today only the headline diversity card is shown. §5.8. |

---

## 2 · FRC §10.5.2 lex tuple — the canonical scoring model

```
(cooldown_violations,    # paramount — never traded against anything else
 par_quad,               # partner-pair sum-of-squares (penalizes repeats hard)
 opp_quad,               # opponent-pair sum-of-squares
 surrogate_count,
 rb_metric,              # R/B imbalance — variant by num_teams (max-imbalance ≥24, swap-count <24)
 station_pen,            # station distribution penalty (FRC #6)
 surrogate_spread,       # P11
 match_equity)           # P5
```

Comparison: lexicographic, lower = better. Cooldown is paramount —
never accept any swap that worsens it. SA accept-reject uses lex
compare with stochastic uphill on lower-priority criteria only.

Reference fixture (2026mnst, 36 teams × 7 MPT):

| Source                                         | Tuple                          |
|------------------------------------------------|--------------------------------|
| MatchMaker reference                           | `(0, 252, 416, 0, 3, 65, 0, 0)` |
| Best-of-30 at SA=2M (sweep)                    | `(0, 252, 404, 0, 1, 39, 0, 0)` |
| Best-of-30 at SA=5M (sweep)                    | `(0, 252, 386, 0, 1, 44, 0, 0)` |
| par_quad floor (theoretical optimum)           | 252                             |
| opp_quad floor (theoretical optimum)           | 378                             |

MatchMaker is the long-standing community reference scheduler used by
event organizers. Comparing against it is sanity-check, not competition.

---

## 3 · Architecture snapshot

```
            ┌──────────────────────────┐
            │ Browser (static/index.html) │
            │ • Generate (browser SA)     │  ← still client-side, weighted-sum
            │ • Assign Teams              │──┐
            │ • Import (xlsx/csv/pdf)     │  │
            └──────────────────────────┘  │
                                          ▼
           ┌────────────────────────────────────────────┐
           │ FastAPI (app/main.py)                      │
           │ /api/abstract-schedules/{id}/assign        │ ← Python lex SA
           │ /api/schedules/import-{xlsx,csv,pdf}       │
           │ /api/schedules/import-pdf/commit           │
           │ PATCH /api/assigned-schedules/{id}         │ ← accepts day_config + practice_matches
           └────────────────────────────────────────────┘
                                          ▼
           ┌────────────────────────────────────────────┐
           │ app/scheduler.py                           │
           │ • generate_matches() — fresh abstract+SA   │
           │ • _assign_unified() — relabel + SA + posts │
           │ • _sa_optimize() — lex SA over Match[]     │
           │ • Phase 1 (R/B) + Phase 2 (station)        │
           └────────────────────────────────────────────┘
                                          ▼
                            PostgreSQL (asyncpg/SQLAlchemy)
```

**Two-stage data model:**
- `AbstractSchedule` (slot indices 1..N, no team numbers) → reusable across rosters
- `AssignedSchedule` (`slot_map: {1: 3276, 2: 7797, ...}`) → real teams + day_config + practice_matches + competition_approved + audit_trail

**Browser scheduler still exists.** `generateMatches()` at static/index.html:8689 (~500 lines) is a complete client-side scheduler with old weighted-sum scoring. It builds the abstract that the server then takes through `/assign`. The browser uses simpler weighted-sum scoring; the server's lex SA fixes whatever it can on the assign step. **Eventual cleanup**: retire the browser scheduler entirely or update it to match Python lex semantics. Tracked in §5.

---

## 4 · This session's bug fixes

### 4.1 /assign chunking
Pre-fix: 720 chunks × ~694 iters each. Each chunk barely warmed up
before stopping. Result: par_quad ~262 vs floor 252; opp_quad ~470
(construction-quality). Confirmed by user uploading buggy output:
`(0, 260, 462, 0, 3, 45, 0, 0)`.

Fix: each worker runs the FULL iteration budget on its own seed.
Best-of-N over independent SA trials, capped at 30 trials. Wall-clock
≈ single-trial time (workers in parallel). Best-of-N comparison uses
the lex tuple, not the legacy summary float.

`app/main.py:1131-1175` (worker dispatch). `app/scheduler.py:run_assignment_chunk` returns `score_tuple` + `worker_elapsed_s` + `us_per_iter` for diagnostics.

### 4.2 /assign auth header
`assignTeams()` was using raw fetch with `Content-Type` only —
no `Authorization`. Pre-existing bug surfaced by tightened auth dep.
Fix: standard `getToken()` + Bearer token pattern.

### 4.3 EventTeam.team_number
Seven SQL queries referenced `EventTeam.team_number` — column doesn't
exist. Team number lives on `Team.number`, joined via `team_id`.
Fixed all sites: `select(Team.number).join(EventTeam, EventTeam.team_id == Team.id).where(EventTeam.event_id == event_id)`.

### 4.4 Practice matches dropped on import
Three concurrent bugs:
- **Storage:** `pdf_import.parsed = {"matches": ..., "notes": ...}` — practice stripped at write time. Fixed at 4 sites (XLSX + CSV, initial + upsert).
- **Display:** `renderPdfImportPreview` only rendered `d.matches`. Fixed: parameterized `renderPdfImportTable(matches, opts)` with target table id + state path; new practice section in modal HTML.
- **Commit:** `confirmPdfImport` body had only `matches`. Fixed: added `practice` field; backend `PdfImportCommitRequest.practice` accepts it; commit handler prefers body over cached parse.

### 4.5 Import flow event-id resolution
Three import call sites silently created an ad-hoc event whenever
`_currentEventId` was null. Common case: post page-reload from
`/view` link sets `_currentEventInfo` but not `_currentEventId`.

Fix: `ensureEventLoadedForImport(label)` helper. Tries
`_currentEventId`, then typed event code in `eventCodeInput`,
then `_currentEventInfo`, then asks the user before falling back to
ad-hoc. Also: `restoreFromFile` now preserves event across `fullReset`
(was wiping `_currentEventId` before the helper could run).

### 4.6 PATCH endpoint accepts practice_matches
For post-import grafting of practice onto an existing schedule.
Same snapshot-history pattern as day_config edits.

`app/main.py:patch_assigned_schedule`.

### 4.7 Practice-from-MatchMaker-xlsx — three layered bugs (2026-05-10)

User report: restoring a MatchMaker-exported xlsx with a Practice sheet
landed 42 quals but silently dropped the 6 practice matches, even though
the import preview's `format_detected` line said "FMS xlsx (42 qual,
6 practice)". The string came from the parser; the data was gone.

Three bugs on the `xlsx → /view` path, layered such that each fix is
needed to surface the next:

**Bug A — stale cache poisoning.** `pdf_imports` is content-hash keyed.
Entries written before §4.4's storage fix have `parsed = {"matches",
"notes"}` — no `practice` key. Cache hit returns `practice: []`, the
preview hides the practice section, commit body sends `practice: []`.
`format_detected` was set at parse time so it still mentions the practice
count even though the data is missing — that's the user-visible "it
sees 6 [practice] but doesn't import them."

Fix: in `import_xlsx` and `import_csv` cache-hit branches, check
`"practice" not in cached_parsed` and fall through to a fresh parse.
Cheap (no LLM call), self-healing for any similar future schema bumps.
The dedicated PDF import path has a `?nocache=1` toggle; the restore
path doesn't, so users couldn't bypass this manually.

**Bug B — datetime time-cells.** openpyxl returns Python `datetime`
objects for date/time-formatted cells (typical for MatchMaker exports).
The parser was doing `str(time_val).strip()`, producing
`"2026-05-15 19:00:00"`. Downstream `_hhmm_to_min` rejects this; cycle
and start/end derivation falls back to defaults (8.0 min cycle,
08:30–17:00). Pre-existing; also affects the app's own xlsx export
which writes `"8:30:00 AM"` strings.

Fix: `xlsx_extract._normalize_time(value)` handles `datetime` /
`time` / `"08:30"` / `"8:30 AM"` / `"8:30:00 AM"` / Excel float serial
→ `"HH:MM"`. Unparseable strings pass through (display still works,
only derivation degrades). Six unit tests in `tests/test_day_config_v2.py
TestXlsxTimeNormalization`.

**Bug C — no derived practiceDay.** Even with practice matches in the
DB, `view.html:3648` requires `cfg.practiceDay && cfg.practiceDay.enabled
!== false` to render the practice tab. `derive_parameters` only
inspected qual matches; the V2 day_config it emitted had one qual day
and no practice block, so the V2→V1 downgrade in `_v2DowngradeToV1ForView`
never produced an `out.practiceDay`.

Fix: `derive_parameters(matches, practice_matches=None)`. New
`_derive_practice_block` helper builds a V2 `practice` block (start =
earliest practice time, end = latest + cycle, cycleTime = modal delta
between consecutive practice matches, with `guaranteed=3` and
`maxFiller=99` per `docs/PRACTICE_DAY.md`). When practice is supplied,
a practice-only V2 day is prepended to `days[]` before the qual day.

`_safe_derive(matches, practice_matches)` updated at all 4 call sites
(xlsx hit + miss, csv hit + miss). Argument is optional and defaults
to `None`, so the existing `test_schedule_derive_emits_v2` test keeps
working with single-arg calls.

End-to-end on the user's `2026mnst-matchmaker-with-practice.xlsx`:
- format_detected: `FMS xlsx (42 qual, 6 practice)` (unchanged)
- `practice.length: 6` (was 0)
- num_days: 2, with practice as day[0] (label "Practice", 19:00–20:00, 10-min cycle) and qual as day[1]
- All confidence flags high

`app/xlsx_extract.py`, `app/main.py`, `app/schedule_derive.py`,
`tests/test_day_config_v2.py`.

### 4.8 Print + export unauthenticated (2026-05-10)

User-visible: clicking Print or Export PDF from `/view` failed with 401
because `view.html` (public spectator/kiosk page) doesn't send an
Authorization header, but `POST /api/schedules/render-pdf` was gated
behind `Depends(require_auth)`. The data those endpoints render is
already exposed publicly via `GET /api/assigned-schedules/{id}` and
the `/view` page itself, so requiring auth on the render path was
inconsistent.

Fix: removed the `user: dict = Depends(require_auth)` param from
`render_schedule_pdf_endpoint`. Mirrors the existing posture of
`GET /api/events/{id}/teams/export` (no auth dep at all). Editor's
`assignTeams`-style auth-bearing fetches from `index.html` continue
to work — the server just ignores the token.

Audit of all print/export-flavoured routes (`@app.get|post(...)`
matching `export|render|print|download|snapshot`):
- `GET /api/events/{event_id}/teams/export` — already unauth
- `POST /api/schedules/render-pdf` — unauth as of this session

Browser-only export paths (`downloadXLSX`, `downloadCSV`,
`downloadJSON` in `static/index.html`) build files in the browser
via SheetJS and don't hit any server endpoint, so they were
already auth-free.

`app/main.py:render_schedule_pdf_endpoint`.

### 4.9 Session-deliverable protocol canonicalised (2026-05-10)

Until this session there was no documented expectation about what a
Claude session should produce when it ends. Each handoff was bespoke.
Result: occasional dropped tarballs, inconsistent commit-message
style, and one stale `REPRODUCTION_PROMPT.md` exclusion in the §9
tarball pattern (which would have silently swallowed any doc updates
to that file — bugged for unknown duration).

Fix: `REPRODUCTION_PROMPT.md` now has a "Session deliverables
(standard process)" section that's the single source of truth for:
- Two-tarball convention (full + changes-only) with the corrected
  exclusion list (no longer drops `REPRODUCTION_PROMPT.md`)
- Commit-ready command sequence (with `apply.sh --build` omitted
  for doc-only commits)
- Commit-message style + canonical example

This handoff's §9 is now a brief operator-cheat-sheet that points
forward to that section. Future Claude sessions read
`REPRODUCTION_PROMPT.md` as part of onboarding, so the convention
propagates without per-session re-explanation.

`REPRODUCTION_PROMPT.md`, `docs/HANDOFF.md`.

### 4.10 Cycle-time-change off-by-one regression (2026-05-10)

User report: cycle-time changes were applying one match late. A change
with `afterMatch=N` was changing the cycle for the gap from match N+1
to match N+2 instead of the gap from match N to match N+1. Direct
contradiction of `docs/V2_SPEC.md` §7, which specifies a worked
example: `block.cycleTime=9, changes=[{afterMatch: 4, cycleTime: 8}]`
should produce match starts at 0, 9, 18, 27, **35**, 43 — match 5
arriving 8 min after match 4 (the new ct), not 9 min.

Root cause: every cycle-change application site used `>` where it
should have used `>=` against `(matchIdx + 1)` (or equivalently in the
capacity counter, fired one iter too late). Six sites:

  1. `static/view.html:3819` — display walker (the user-visible one)
  2. `static/index.html:15210` — practice-day walker `_pracEffectiveCt`
  3. `static/index.html:15560` — qual-day walker `dayCt`
  4. `static/index.html:15612` — `prevDayCt` (used to detect when
     to emit a cycle-change marker; bare `matchIdx >` since matchIdx
     is post-increment / 1-based here)
  5. `static/index.html:15621` — `nextDayCt` (same emitter)
  6. `static/index.html:8425` — `calcMaxMatches` capacity counter,
     where the equivalent fix is `<= matchCount + 1` instead of
     `<= matchCount` (apply change one iter earlier in the loop)

Fix: changed each comparison. The 1-based match index `matchIdx + 1`
must be `>=` the change's `afterMatch` for the change to apply at
this iter — match N's own slot is the first to use the new ct, per
spec.

New regression test `tests/test_cycle_change_walker.js` runs in two
modes: substring guards on the production source pin the `>=` (and
`<= matchCount + 1`) at every site, and a faithful walker re-
implementation reproduces V2_SPEC §7's worked example exactly. An
explicit anti-test runs the buggy `>` walker to confirm the two
semantics are actually distinguishable (buggy walker puts match 5
at 36 instead of 35; new test catches that).

`static/view.html`, `static/index.html`,
`tests/test_cycle_change_walker.js`.

---

## 5 · Open items

### 5.1 Browser scheduler retirement
The client-side `generateMatches()` in `static/index.html` builds
the abstract using old weighted-sum scoring. The Python SA on `/assign`
fixes some but not all of what suboptimal abstract construction
produces.

**Two options:**
- A. Move construction to the server entirely. `/api/generate-abstract`
  builds via `generate_matches()` (Python). Browser is presentation only.
- B. Update browser scoring to match Python lex SA. Keeps client-side
  preview but aligns semantics.

A is cleaner. Either way, the legacy "Placement Criteria" panel that
references browser-only weights becomes irrelevant and should be removed
or relabeled.

### 5.2 Container parallelism investigation
User reported 2m 48s wall-clock for "Best" preset (2M iters × best-of-30)
on the OpenShift container. Math says 30 × 2M iters at ~37μs/iter on
12 effective cores = ~187 seconds minimum. 168 actual is *faster* than
that — suggests trials may not all be running their full budget, OR
container per-iter cost is shorter than the test environment.

`app/scheduler.py:run_assignment_chunk` now logs `worker_elapsed_s` +
`us_per_iter` per worker. After the next "Best" run, check:
```bash
oc logs deploy/<app-pod> --since=10m | grep "Stage 2 worker"
```

If all 30 workers report `iters=2000000` with `elapsed≈75s`, we're
fine — the schedule quality just reflects best-of-30-at-2M variance.
If many show truncated iterations or excessive elapsed, investigate
further (CPU contention, broken pool, FastAPI cancellation).

### 5.3 par_quad=256 outlier on container vs Stark sweep stdev=0
Stark sweep at SA=2M had stdev 0.0 across 30 trials — every trial hit
floor 252. User's 2m48s "Best" run produced par_quad=256. With the
chunking fix landed and quality presets correctly resolving 2M, the
likely cause is the container's worker timing (5.2). Re-running an
additional 2M-iter SA pass on top of the user's output drops to floor
in 75s, proving the schedule wasn't structurally stuck.

### 5.4 Best-of-N production runner (deferred)
`/assign` currently caps at `BEST_OF_N_TARGET=30`. Could expose a
top-level "Generate Best Schedule" workflow for state events that
explicitly runs N-trial SA at high iteration budgets, with progress
reporting and cancellation. Stark recommended.

### 5.5 Extended iteration sweep (deferred)
Find K* per the tight-criterion definition. Levels 10M, 20M, 50M.
~5 hours wall-clock on Stark. Documented in
`docs/scheduler/ITERATION_CEILING.md` "Future work".

### 5.6 RBAC (proper roles + permissions) — designed, paused

Full design lives in `docs/RBAC_MODEL.md` (~935 lines, status:
"Proposal — paused"). Five roles: Admin / Support (global) and
Owner / Manager / Viewer (event-scoped), with implicit Public for
read-only `/view`. Capability matrix, delegation rules ("you can
only delegate what you have"), expiration model, in-app
notifications, and a request mechanism for users to seek elevated
access are all spec'd out.

**Status: zero phases implemented.** Current authorization model
is the `is_admin` interim flag (see §5.7). No `role_grants` /
`role_requests` / `notifications` tables exist; no `can(user,
capability)` checker. The doc is explicit that all 7 phases (R-1..
R-7) are paused pending change-freeze lift + decisions on the seven
open design questions in `RBAC_MODEL.md` "Open design questions."

R-1 is the foundation everything else builds on (schema +
authorization checker, replacing `is_admin` references). Doc
recommends shipping R-1 + R-2 (back-end enforcement) before any
UI work begins.

Trigger to revisit: when the live-event change-freeze lifts and
the tool starts being shared beyond a single team's internal use.

### 5.7 Schedule-lifecycle phases D / F / G — partially shipped

Full design lives in `docs/SCHEDULE_LIFECYCLE.md` (~1019 lines,
status: "Draft for implementation"). 7 phases (A–G) plus Part 13's
layered authorization rules.

**Shipped:**
- A — Auth mandatory on writes (see §4.8)
- B — `forked_from_id` schema (`db.py:193`) + fork via
  `/api/assigned-schedules/{id}/duplicate` (`main.py:2499`)
- C — Structural immutability check (`_was_ever_official` at
  `main.py:1656`, gate at `:1760`)
- E — `is_admin` flag (`db.py:342`) + admin-gated `freeze` /
  `unfreeze` / `unmark-official` / force-unlock-by-admin

**Open:**
- **D — Consolidated `event_audit_events` table.** Partial today:
  `assigned_schedule_history` and `assigned_schedule_lock_events`
  capture the most-active event types, but the unified table the
  spec defines (one row per meaningful action across all event
  surfaces) doesn't exist. Until it does, `event_audit_events`
  is implicit — readers reconstruct it by joining the per-table
  histories, which is why an audit-log UI hasn't shipped.
- **F — Lock TTL + heartbeat.** Basic locks ship; lock acquisition
  sets `locked_at` and `locked_by_user_id`. No TTL check (locks
  don't expire on their own), no heartbeat endpoint to refresh
  while editing, no client-side ping. Result: a closed-tab editor
  leaves the lock pinned until someone manually unlocks. Schema
  changes: none required (`locked_at` already exists).
- **G — Lifecycle response field.** Schedule GET responses don't
  include the `lifecycle` block (`structural_frozen`, `lock_state`,
  `freeze_state`) the spec defines. Frontend reproduces the
  layering check ad-hoc against `is_official` / `locked_at` /
  the event freeze flag. Schema changes: none required; pure
  read-side enrichment.

Each is independently shippable per `SCHEDULE_LIFECYCLE.md` Part 11.
F is the highest-immediate-UX-value (kills the "dead lock from
closed tab" papercut); G removes a class of frontend bugs by
centralising the layering check; D unblocks the audit-log UI
workstream.

### 5.8 UI exposure of `scheduler_eval` quality data — designed, parked

Full design lives in `docs/UI_QUALITY_EXPOSURE.md`. Status: future
roadmap, no active development. Captures a four-tier plan for
surfacing harness-side quality measurements in the editor and
viewer UIs.

**Today's UI quality surface:** the Schedule Quality card
(`#diversityReportCard` at `static/index.html:2757`, rendered by
`renderDiversityCard()` at `:4220`). Card is effective at what it
does — uses floor-relative semantics rather than the harness's
mis-calibrated threshold classification, sidesteps the
"MatchMaker = poor" embarrassment in the harness output, cleanly
separates configuration knobs from measurement. **What's missing:**
per-pair specifics with team numbers, per-team breakdowns, the
8-element FRC §10.5.2 lex tuple, reference-distribution comparison,
and any quality info on the public `/view` page.

**Four-tier plan** (full detail in the dedicated doc):

- **T1 — Surface what's already on the wire.** Small (~3–4 hours).
  The diversity-report endpoint already returns `worst_pairs` and
  `slot_table`; the card uses only their counts. Render the
  per-pair list with team numbers, expose `slot_table` as a
  per-team `<details>` panel. No backend change. Closes the most-
  reported gap.
- **T2 — Surface the lex tuple.** Medium effort. New endpoint
  returning the 8-element tuple with labels and per-element
  annotations. New "Quality breakdown" section in the card. Adds
  side-by-side schedule comparison view with per-criterion deltas.
  Pre-work: fix the `match_equity` placeholder (currently
  hardcoded to 0 in `_score_from_state:1101` — inert tuple slot).
- **T3 — Reference comparison via recalibrated thresholds.**
  Substantial. Pull TBA played-schedule corpus, compute metric
  distributions per fixture-size bucket, set thresholds at real
  percentiles (acceptable=80th, near-optimal=50th). Bake into
  shipped JSON. Server endpoint returning percentile rank.
  Percentile badges in UI. Highest user value, most calibration
  judgment required. Should not ship until calibration is
  validated against multiple reference fixtures.
- **T4 — Surface to `/view`.** Independent of tier choice. Public
  spectator view currently has zero quality info; can expose any
  subset of T1/T2/T3 to coaches viewing the public link. Open
  product question: is exposing schedule-quality detail to a
  public audience desirable, or does it invite litigation of
  mathematically-forced edge cases.

**Recommended ordering when this resumes:** T1 alone is the
tightest single increment. T1 + T2 together is the natural
"expose scheduler_eval in the UI" scope. T3 is its own workstream.
T4 parallel to any of the above.

**Pre-work that becomes more visible if T2 ships:** the lex-tuple
audit findings from the prior session — fix `match_equity` slot,
clarify the `score` DB column's non-authoritative-ness, add a
cooldown verifier for imported schedules.

---

## 6 · Code locations (verbatim)

### `app/main.py` (~4400 lines)

| Line   | Symbol                                                | What it does                              |
|--------|-------------------------------------------------------|-------------------------------------------|
| ~371   | `AssignRequest` Pydantic model                        | quality_preset, competition_approved, rb_post_pass, station_post_pass, cooldown |
| ~1131  | `assign_teams_endpoint` worker dispatch               | best-of-N parallel SA trials              |
| ~1701  | `patch_assigned_schedule`                              | accepts day_config + practice_matches     |
| ~2768  | `_resolve_practice_matches`                            | slot→team translation; identity fallback   |
| ~3330  | `PdfImportCommitRequest`                               | matches + practice + day_config           |
| ~3815  | XLSX import storage (4 sites)                          | preserves practice in pdf_import.parsed   |
| ~4096  | `commit_pdf_import`                                    | reads body.practice OR cached parse       |

### `app/scheduler.py` (~2120 lines)

| Symbol                          | What it does                                      |
|---------------------------------|---------------------------------------------------|
| `generate_matches`              | construction + SA + post-passes (one process)     |
| `_assign_unified`               | relabel slot→team + SA + post-passes              |
| `_sa_optimize`                  | lex-compare SA over Match[]                       |
| `score_tuple_for_schedule`      | 8-element FRC §10.5.2 lex tuple                   |
| `score_schedule`                | legacy float (UI/CSV/DB display only)             |
| `_swap_preserves_cooldown`      | hard filter — paramount preserved before mutation |
| `_propose_targeted_move`        | duplicate-pair-aware move generator               |
| `run_assignment_chunk`          | worker entry; logs elapsed + μs/iter              |

### `app/post_passes/`

- `rb_balance.py` — Phase 1, whole-match R/B flip + SA, 8 property tests
- `station_balance.py` — Phase 2, Sykes-style within-alliance permutation + SA-from-greedy, 12 property tests

### `app/frc_compliance.py`

- `FRC_DEFAULTS` — `{"rb_post_pass": True, "station_post_pass": True, ...}`
- `compute_deviations(settings)` — list of human-readable deviation strings
- `build_audit_record(settings, cooldown, preset, iterations)` — full audit JSON

### `app/quality_presets.py`

- `QUALITY_PRESETS` — `fair=50K, good=500K, best=2M, maximum=5M`
- `MAX_ITERATIONS = 5_000_000`
- `iterations_for_preset(name)`, `preset_for_iterations(n)`

### `static/index.html` (~17,700 lines)

| Line   | Symbol                                  | What it does                                       |
|--------|-----------------------------------------|----------------------------------------------------|
| ~2645  | FRC compliance section in Generate form | checkbox + deviation banner + algorithm toggles    |
| ~3099  | `restoreFromFile`                       | preserves event across fullReset                   |
| ~3315  | `_restoreMatchListFile` (xlsx/csv)      | uses `ensureEventLoadedForImport`                  |
| ~3406  | `openPdfImportModal`                    | uses `ensureEventLoadedForImport`                  |
| ~3553  | `renderPdfImportPreview`                | renders qual + practice tables                     |
| ~3872  | `renderPdfImportTable(matches, opts)`   | parameterized for qual or practice rendering       |
| ~5050  | `recomputeFrcCompliance` + handlers     | live banner update on algorithm-toggle change      |
| ~8689  | `generateMatches` (browser SA)          | client-side abstract construction (legacy weighted-sum) |
| ~9861  | `ensureEventLoadedForImport`            | shared event-resolution helper                      |
| ~14000 | `assignTeams`                           | sends quality_preset, competition_approved, etc.   |

### `static/view.html` (~8200 lines)

| Symbol                  | What it does                                          |
|-------------------------|-------------------------------------------------------|
| `renderFrcBanner`       | top-of-page green/yellow/gray banner from audit_trail |
| `_renderFrcAudit`       | audit modal — deviations + settings table             |
| `_applyLoadedSchedule`  | calls renderFrcBanner on every load                   |

---

## 7 · Test status

All green:
- Smoke test (canonical metrics)
- V2 URL (36 tests)
- Three-up (23 tests)
- day_config_v2
- Phase 0 lex SA + targeted moves
- Phase 1 R/B (8 commutativity)
- Phase 2 station (12 commutativity)
- FRC compliance (11 tests in `tests/test_frc_compliance.py`)
- Cycle-change walker (`tests/test_cycle_change_walker.js`) — V2_SPEC §7 semantic + source-guards on all 6 application sites
- Inline JS in static/index.html and static/view.html parses cleanly

---

## 8 · Operational knowledge

### Production
- Hostname: `frc-scheduler.roadfeldt.com`
- Pod label: `app=frc-scheduler-server-git`
- Postgres: pod label `app=frc-postgres`, db `frc_scheduler`
- Container: 12 effective cores via cgroup quota (1.2 CPU = 12 effective). `os.cpu_count()` reports 16 (host) but cpu.max limits to 12.
- Event for state: `2026mnst`, event_id `4`, 36 teams (MSHSL)
- HAProxy timeout: 120s (`openshift/05-route.yaml`) — SSE keep-alive resets idle timer

### Stark (eval machine)
- 36 cores
- Used for iteration sweeps + production-quality state schedules
- `CPU_WORKERS=36` env

### DB migration applied
```bash
oc cp migrate_competition_approved.sql frc-postgres-XXXXX:/tmp/
oc rsh pod/frc-postgres-XXXXX
psql -U postgres -d frc_scheduler -f /tmp/migrate_competition_approved.sql
```

Verify columns:
```bash
psql -U postgres -d frc_scheduler -c "\d assigned_schedules" | grep -E 'competition_approved|audit_trail'
```

---

## 9 · Deploy

Standard flow:
```bash
cd ~/git/frc-scheduler-server
git pull && git add -A
git commit -m "<message>"
git push
./openshift/apply.sh --build       # omit for doc-only commits
```

Hard-refresh Safari/Chrome after deploy (`⌘⇧R` / `Ctrl+Shift+R`) — UI
changes from this session won't appear without it.

For the canonical Claude-session deliverable convention — two
tarballs (full + changes-only), commit-ready commands, and the
commit-message style — see `REPRODUCTION_PROMPT.md` "Session
deliverables (standard process)". That's the source of truth;
this section is just the operator-side cheat sheet.

---

## 10 · Reproduction prompt

`REPRODUCTION_PROMPT.md` (root) is the canonical AI onboarding doc.
Pair it with this handoff for current state. They're complementary,
not redundant — the prompt covers project goals + structure + constraints,
this doc covers what's done + what's pending.

`docs/REPRODUCTION_PROMPT.md` is a stub redirecting to the root copy
(used to be diverged; consolidated this session).

---

## 11 · TL;DR

If you're picking this up:

1. **Read this handoff + `REPRODUCTION_PROMPT.md` + `PRIORITIES.md`** in that order.
2. **Open items** are §5 above — split into two buckets:
   - *Scheduler-quality polish*: browser scheduler retirement (5.1), container parallelism investigation (5.2), par_quad outlier diagnosis (5.3).
   - *Authorization + lifecycle*: schedule-lifecycle phases D/F/G (5.7) and the full RBAC workstream (5.6). Both have detailed dedicated docs (`SCHEDULE_LIFECYCLE.md`, `RBAC_MODEL.md`) but neither is in active development. Paused pending change-freeze lift and open-question decisions; tracked here so they don't drift out of sight.
   - *UI exposure of harness work*: surfacing `scheduler_eval` quality data in the editor + viewer (5.8). Designed in `UI_QUALITY_EXPOSURE.md` as a four-tier plan; no active development. Today's editor card is effective at what it does but hides per-pair / per-team detail and the lex tuple.
3. **For state events**, recommend Stark via best-of-30 at SA=2M (~75s wall-clock). Container "Best" works but with the caveat in §5.2.
4. **Never silently bypass FRC §10.5.2 paramount.** The lex tuple is the contract. Cooldown comes first, always.
5. **MatchMaker is a peer**, not a competitor. The framing throughout the codebase reflects this.

The scheduler core is in good shape, all tests pass, algorithm work is mostly polish + diagnostics from here. The remaining substantive work is on the authorization side — see §5.6 / §5.7 and the dedicated docs they point to.
