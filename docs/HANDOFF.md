# HANDOFF

State of the world for the next person picking up the FRC Match Scheduler
project. Practical, terse, code-anchored — same convention as the rest of
`docs/`. Read this first if you're new to the codebase or coming back
after a gap.

Last updated: 2026-05-10, end of the practice-import-from-MatchMaker-xlsx
debugging session. Three layered bugs on the `MatchMaker xlsx → /view`
path: stale cache, datetime time-cells, no derived practiceDay. Details
in §4.7 below.

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
./openshift/apply.sh --build
```

Hard-refresh Safari/Chrome after deploy (`⌘⇧R` / `Ctrl+Shift+R`) — UI changes from this session won't appear without it.

Tarball pattern (Claude session):
```bash
cd /tmp && tar czf /mnt/user-data/outputs/frc-scheduler-server.tgz \
  --exclude='frc-scheduler-server/.git' \
  --exclude='*/__pycache__' \
  --exclude='frc-scheduler-server/REPRODUCTION_PROMPT.md' \
  --exclude='frc-scheduler-server/NOTES.md' \
  --exclude='frc-scheduler-server/notes.md' \
  --exclude='frc-scheduler-server/TODO.local.md' \
  frc-scheduler-server/
```

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
2. **Open items** are §5 above — browser scheduler retirement, container parallelism investigation, par_quad outlier diagnosis.
3. **For state events**, recommend Stark via best-of-30 at SA=2M (~75s wall-clock). Container "Best" works but with the caveat in §5.2.
4. **Never silently bypass FRC §10.5.2 paramount.** The lex tuple is the contract. Cooldown comes first, always.
5. **MatchMaker is a peer**, not a competitor. The framing throughout the codebase reflects this.

The code is in good shape, all tests pass, the architecture is clean. Mostly polish + diagnostics from here.
