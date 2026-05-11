# FRC Match Scheduler — Reproduction Prompt

Onboarding context for an AI assistant (or human contributor) coming
into this codebase cold. Pair with `docs/HANDOFF.md` for "what's
in-flight right now," `PRIORITIES.md` for "what the algorithm does,"
and `docs/PRIORITIES.md` for "how the algorithm is structured
internally."

Last verified against tree: 2026-05-09 (post-FRC-§10.5.2-paramount session).

---

## Licensing & IP Posture (READ FIRST)

This is **not a port of the reference scheduler**. The Python scheduler in
`app/scheduler.py` is a clean-room implementation against the published
FRC §10.5.2 rules. Two specific pieces have explicit prior-art
attribution:

- **R/B post-pass** (`app/post_passes/rb_balance.py`): inspired by
  the reference scheduler's R/B handling as documented at the published algorithm description.
- **Station post-pass** (`app/post_passes/station_balance.py`): based
  on the public the station-balance algorithm (Tom + Cathy Saxton, 2017) as
  described at the published station-balance description.

Neither is a port of any external reference scheduler's code. Throughout the codebase,
the established FRC reference scheduling approach is treated as a **peer reference used by event
organizers**, not as a competitor. Comparison numbers are sanity-checks
during development, not "we beat them" claims. See
`docs/scheduler/REFERENCE_SCHEDULER_LICENSING.md` if curious.

The codebase is GPLv3. AI-assisted development; humans direct
architecture and validate output. See README.md for the AI assistance
notice.

---

## Project Overview

Single-file HTML/CSS/JS frontend in `static/index.html` (~17,700 lines)
+ FastAPI backend in `app/main.py` (~4,400 lines) + pure Python
scheduler in `app/scheduler.py` (~2,120 lines). PostgreSQL via
asyncpg/SQLAlchemy. Containerised for OpenShift.

**Frontend has TWO HTML pages:**
- `static/index.html` — the editor (Generate, Assign, Save, Import).
- `static/view.html` (~8,200 lines) — read-only schedule viewer. Used
  by competitors / spectators / kiosks. Loaded via `/view/{schedule_id}`
  or `/view?event=<key>`.

**Two-stage scheduling data model:**
- **Stage 1** (Abstract Schedule): slot indices 1..N, no team numbers.
  Reusable across rosters of the same size. Built by either the browser
  scheduler (legacy weighted-sum, still in use) or `generate_matches()`
  in Python.
- **Stage 2** (Team Assignment): `slot_map: {1: 3276, 2: 7797, ...}`
  layered on top. Per-schedule fields: `day_config`, `practice_matches`,
  `competition_approved`, `audit_trail`, lock state, official mark.

The browser still owns the Generate-step abstract construction. The
Python `/assign` endpoint runs lex SA + post-passes on the resulting
abstract. **Eventual cleanup** is to move construction server-side too
— tracked in `docs/HANDOFF.md` §5.1.

---

## Algorithm — FRC §10.5.2 Paramount Lex Tuple

The authoritative score is an 8-element tuple compared lexicographically.
Lower is better at every position. Cooldown is paramount and never
traded against any other criterion.

```
(cooldown_violations, par_quad, opp_quad, surrogate_count,
 rb_metric, station_pen, surrogate_spread, match_equity)
```

Maps to:
1. FRC §10.5.2 #1 — Cooldown (paramount)
2. FRC §10.5.2 #2 — Partner repeats (sum-of-squares)
3. FRC §10.5.2 #3 — Opponent repeats (sum-of-squares)
4. FRC §10.5.2 #4 — Surrogate count
5. FRC §10.5.2 #5 — R/B alliance distribution (variant by team count)
6. FRC §10.5.2 #6 — Station distribution
7. P11 (Surrogate spread, secondary)
8. P5 (Match equity, secondary)

`score_tuple_for_schedule(matches, num_teams)` computes this. The
legacy `score_schedule()` returns a float for UI/CSV/DB display only;
**never use it for accept-reject decisions**.

### Phase 0 SA core
- Phase 0a — `score_tuple_for_schedule` returns 8-element tuple. SA
  accept/reject lex-compares.
- Phase 0b — `_swap_preserves_cooldown` filters violations BEFORE state
  mutation. ~5x SA speedup over post-mutation reject.
- Phase 0c — `_propose_targeted_move` biases 2/3 of moves toward
  duplicate partner/opponent pairs. Substantially improves convergence
  on criterion #3.

### Post-passes
- Phase 1 — `app/post_passes/rb_balance.py`. Whole-match R/B flip + SA.
  Changes only `rb_metric`. 8 commutativity property tests prove it
  preserves all other criteria.
- Phase 2 — `app/post_passes/station_balance.py`. the station-balance technique-style within-
  alliance station permutation + SA-from-greedy. Changes only
  `station_pen`. 12 commutativity property tests.

### Quality presets (`app/quality_presets.py`)
| preset    | iters     | wall (Stark, best-of-30) |
|-----------|-----------|--------------------------|
| fair      | 50,000    | ~2s   |
| good      | 500,000   | ~20s  |
| best      | 2,000,000 | ~75s  |
| maximum   | 5,000,000 | ~3min |

`MAX_ITERATIONS = 5_000_000`. K* (mean improvement < stdev) was not met
within tested range; documented as ">5M, not found" in
`docs/scheduler/ITERATION_CEILING.md`.

### Competition compliance (`app/frc_compliance.py`)
A schedule is **competition-approved** iff generated with FRC defaults:
```python
FRC_DEFAULTS = {"rb_post_pass": True, "station_post_pass": True, ...}
```
Cooldown is intentionally NOT a deviation (per FRC, varies by event size
— logged but not penalized). UI surfaces approval state via:
- Green/yellow checkbox on Generate form
- Per-row badge in saved-schedules list (✓/!/?)
- Top-of-page banner on /view, click for audit modal
- `assigned_schedules.audit_trail` JSONB stores full forensics

---

## Two-stage scheduling: end-to-end

### Stage 1 — Abstract Schedule

Currently built **client-side** in `static/index.html:8689`
(`generateMatches()`, ~500 lines). Uses old weighted-sum scoring.
Output: a list of matches with slot indices 1..N, surrogate flags, R/B
distribution, station assignments.

`/api/generate-abstract` POSTs the browser-built result to the server
which stores it as an `AbstractSchedule` row.

**Why client-side:** legacy. The original tool was a static page that
ran entirely in the browser. The Python lex SA was added later for the
team-assignment step, but the construction phase didn't get migrated.

**Why it persists:** the browser scheduler works "well enough" for
construction. The Python SA on /assign cleans up most of what the
weighted-sum left suboptimal. But a fresh `generate_matches()` abstract
on the server reaches better tuples than a browser-built one going
through the same SA — see `docs/HANDOFF.md` §5.1.

### Stage 2 — Team Assignment

`POST /api/abstract-schedules/{id}/assign` triggers:
1. Build initial `Match[]` by relabeling slots → real team numbers
2. Run Phase 0 lex SA for `iterations` steps (resolved from
   `quality_preset` or explicit `iterations`)
3. Run R/B post-pass (Phase 1) if `rb_post_pass=True` (FRC default)
4. Run station post-pass (Phase 2) if `station_post_pass=True` (FRC
   default)

**Best-of-N is the default**: 30 trials in parallel (capped by
available cores via `min(actual_workers, BEST_OF_N_TARGET=30)`).
Best-of-N comparison uses the lex tuple. Wall-clock ≈ single-trial
time because workers run in parallel.

Each worker now returns timing diagnostics (`worker_elapsed_s`,
`us_per_iter`) for spotting CPU-contention or truncation issues — see
`docs/HANDOFF.md` §5.2.

---

## URL Reproducibility

The editor URL encodes the full schedule state for sharing /
bookmarking. Parameters: `n=<num_teams>`, `mpt=`, `cd=` (cooldown),
`ct=` (cycle time), `days=`, `bb=` (break buffer), `seed=`, `aseed=`
(assign seed), `sid=`, `aid=`, `dcv=2` (day-config version), and
day-specific fields like `d1=`, `d1b1=`, `d1b1cc=`.

Loading a URL recreates the exact schedule state. Useful for sharing
"my exact setup" between contributors.

---

## UI Flow (editor — `static/index.html`)

### Event bar (top)
- Type event code (e.g. `2026mnst`) → Load → activates event for
  editing. Sets `_currentEventId` + `_currentEventInfo`. Loads the
  most-recent active assigned schedule if one exists.
- "Quick / Ad-hoc" button creates an unnamed event for one-off use.

### Generate Schedule
- Form fields for num_teams, MPT, cooldown, cycle time, num_days, day_config.
- Click Generate → browser builds abstract → POST `/api/generate-abstract`.

### Assign Teams
- Quality preset dropdown (Fair / Good / Best / Maximum / Custom).
- Algorithm toggles: rb_post_pass, station_post_pass.
- Cooldown input (FRC says varies by event size; editable, audited).
- Competition Approved checkbox (defaults checked, auto-unchecks on
  any algorithm-toggle change). Re-check opens reset confirmation.
- Click Assign Teams → POST `/api/abstract-schedules/{id}/assign`
  (lex SA + post-passes, best-of-N).

### Saved schedules
- List modal shows all schedule versions for the event.
- Per-row badges: official (gold star), locked (lock icon), edited
  (amber pill), FRC compliance (✓ green / ! red / ? gray, clickable
  for audit modal).
- Promote, mark/unmark official, copy, view, delete actions.

### Import schedule
- Three sources: PDF (LLM-parsed), XLSX (FMS export format), CSV.
- Each goes through preview → user confirms or edits → commit.
- XLSX/CSV imports support a Practice sheet alongside Qualification.
  Preview UI shows both tables. Commit stores both.
- All imports use `ensureEventLoadedForImport()` to resolve event
  before falling back to ad-hoc.

---

## UI Flow (viewer — `static/view.html`)

- Read-only schedule display, no editing controls.
- Source pill: live (Nexus) / estimated / pre-event / TBA.
- 3-up grid showing on-field / on-deck / queueing.
- Practice + Qual + Playoff tabs.
- FRC compliance banner at top: green/yellow/gray, clickable for full
  audit modal.

Loaded via `/view/{schedule_id}` (specific) or
`/view/by-key/{event_key}` (latest active). TBA-only events
(no local schedules) load via `/api/events/by-key/{key}/view-payload`
which proxies TBA data.

---

## Key code locations

### `app/main.py`

| Symbol                                               | Purpose                                       |
|------------------------------------------------------|-----------------------------------------------|
| `AssignRequest`                                      | Pydantic model — quality_preset, competition_approved, rb_post_pass, station_post_pass, cooldown |
| `assign_teams_endpoint`                              | best-of-N parallel SA dispatch                |
| `patch_assigned_schedule`                            | accepts day_config + practice_matches edits   |
| `_resolve_practice_matches`                          | slot→team translation w/ identity fallback    |
| `PdfImportCommitRequest`                             | matches + practice + day_config commit body   |
| `commit_pdf_import`                                  | reads body.practice OR cached parse           |
| `import_xlsx`, `import_csv`, `import_pdf`            | preview endpoints, all cache by content hash  |
| `_build_assigned_schedule_response`                  | resolves slot_map → real teams; renders audit |

### `app/scheduler.py`

| Symbol                          | Purpose                                            |
|---------------------------------|----------------------------------------------------|
| `generate_matches`              | construction + SA + post-passes (one-shot)         |
| `_assign_unified`               | relabel slot→team + SA + post-passes               |
| `_sa_optimize`                  | lex-compare SA over `Match[]`                      |
| `score_tuple_for_schedule`      | 8-element FRC §10.5.2 lex tuple — authoritative    |
| `score_schedule`                | legacy float for UI/CSV display only               |
| `_swap_preserves_cooldown`      | hard filter — paramount preserved before mutation  |
| `_propose_targeted_move`        | duplicate-pair-aware move generator                |
| `run_assignment_chunk`          | worker entry; logs elapsed + μs/iter               |

### `app/post_passes/`

- `rb_balance.py` — Phase 1
- `station_balance.py` — Phase 2

### `app/frc_compliance.py`

- `FRC_DEFAULTS` — algorithm-default settings dict
- `compute_deviations(settings)` — list of human-readable deviations
- `build_audit_record(settings, cooldown, preset, iterations)` — audit JSON

### `app/quality_presets.py`

- `QUALITY_PRESETS` — `{fair: 50K, good: 500K, best: 2M, maximum: 5M}`
- `iterations_for_preset(name)`, `preset_for_iterations(n)`

### `static/index.html`

| Symbol                                  | Purpose                                            |
|-----------------------------------------|----------------------------------------------------|
| `generateMatches` (line ~8689)          | client-side abstract construction (legacy)         |
| `assignTeams`                           | sends quality_preset + FRC fields to /assign       |
| `recomputeFrcCompliance` + handlers     | live banner update on algorithm-toggle change      |
| `ensureEventLoadedForImport`            | shared event-resolution helper for imports         |
| `restoreFromFile`                       | dispatches xlsx/csv/json restore; preserves event  |
| `renderPdfImportTable(matches, opts)`   | parameterized for qual or practice rendering       |

### `static/view.html`

| Symbol                  | Purpose                                                    |
|-------------------------|------------------------------------------------------------|
| `renderFrcBanner`       | top-of-page green/yellow/gray banner from audit_trail     |
| `_renderFrcAudit`       | audit modal — deviations + settings table                  |
| `_applyLoadedSchedule`  | calls renderFrcBanner on every load                        |

---

## Critical pitfalls

### Browser cache after deploy
UI changes don't appear without a hard refresh (`⌘⇧R` on macOS,
`Ctrl+Shift+R` elsewhere). The HTML and JS are cached aggressively.

### Event-id resolution before imports
The browser used to silently fork to ad-hoc when `_currentEventId`
was unset, even when the user clearly intended a specific event.
`ensureEventLoadedForImport()` fixes this — but the legacy
`/api/events/adhoc` flow is still there for the deliberate
"Quick / Ad-hoc" button. Don't confuse the two.

### `pdf_import.parsed` storage shape
Cache narrowing was dropping the `practice` array. All four storage
sites (XLSX initial + upsert; CSV initial + upsert) now store
`{matches, practice, notes}`. Don't add a fifth without including
practice.

### `EventTeam.team_number` doesn't exist
`EventTeam` is just `event_id` + `team_id`. Team numbers live on
`Team.number`. Always join: `select(Team.number).join(EventTeam, ...)`.

### Import response cache hits
Cache-hit responses returned `matches` only — adding `practice` to
the response shape was a separate fix from the storage shape. Both
must be in sync.

### `_currentEventId` vs `_currentEventInfo`
The editor uses `_currentEventId` (int) and `_currentEventInfo`
(metadata dict). `fullReset(true)` wipes both. After a `/view` page
reload, only `_currentEventInfo` may be populated for editing flows
to find. The helper checks both.

### Container vs Stark CPU detection
`os.cpu_count()` returns 16 on the OpenShift container (host CPU
count) but the cgroup quota limits effective parallelism to 12.
`/sys/fs/cgroup/cpu.max` shows `1200000 100000` = 12 cores. Use
`actual_workers` from env override (`CPU_WORKERS=12`).

### Browser scheduler still in use
The Generate button uses client-side `generateMatches()` with old
weighted-sum scoring. `/assign` runs lex SA on top. Both are
authoritative for different parts of the lifecycle. Don't assume
"it's all Python lex SA" — there's a hybrid.

### HAProxy timeout on /assign
`openshift/05-route.yaml` has `haproxy.router.openshift.io/timeout: 120s`.
SSE `: ping` keep-alives reset the idle timer, so long-running /assign
requests work as long as progress events stream.

---

## Test expectations

All green:
- `python3 scripts/scheduler_eval/smoke_test.py` — canonical-metrics smoke
- `node tests/test_v2_url.js` — 36 URL round-trip cases
- `node tests/test_field_three_up.js` — 23 view-page 3-up cases
- `python3 tests/test_day_config_v2.py` — V2 day_config validation
- `python3 tests/test_match_sa.py` — Phase 0 lex SA + targeted moves (300 + 86 cases)
- `python3 tests/test_rb_balance.py` — 8 R/B commutativity property tests
- `python3 tests/test_station_balance.py` — 12 station commutativity tests
- `python3 tests/test_frc_compliance.py` — 11 audit / FRC compliance tests
- `node` parse on inline `<script>` blocks in both HTML files

`tests/iteration_sweep/2026mnst_30trials_analysis.txt` documents the
Stark sweep results that `app/quality_presets.py` was tuned against.

---

## Operational reference

- Production hostname: `frc-scheduler.roadfeldt.com`
- Pod label: `app=frc-scheduler-server-git`
- Postgres pod: `app=frc-postgres`, db `frc_scheduler`
- Container: 12 effective cores via cgroup
- State event: `2026mnst`, event_id 4, 36 teams
- Stark eval: 36 cores, used for sweeps + production state schedules

---

## Session deliverables (standard process)

When a Claude session ends with code or doc changes, the deliverable
is **two tarballs + commit-ready commands + a commit message**, every
session. Future Claude sessions: this is the contract — produce all
of it without being asked.

### 1. Two tarballs

Both written to `/mnt/user-data/outputs/` and presented via the
`present_files` tool at the end of the session:

**Full tree** — `frc-scheduler-server.tgz`. What the user extracts
over their working tree.

```bash
cd /home/claude && tar czf /mnt/user-data/outputs/frc-scheduler-server.tgz \
  --exclude='frc-scheduler-server/.git' \
  --exclude='*/__pycache__' \
  --exclude='frc-scheduler-server/NOTES.md' \
  --exclude='frc-scheduler-server/notes.md' \
  --exclude='frc-scheduler-server/TODO.local.md' \
  frc-scheduler-server/
```

**Changes-only** — `frc-scheduler-changes-only.tgz`. Just the files
modified this session, with paths intact. Speeds up review and
diffing without changing the deploy flow (the user can extract this
one too — same top-level dir).

```bash
cd /home/claude && tar czf /mnt/user-data/outputs/frc-scheduler-changes-only.tgz \
  frc-scheduler-server/<modified-file-1> \
  frc-scheduler-server/<modified-file-2> \
  ...
```

The exclusion list deliberately does NOT exclude `REPRODUCTION_PROMPT.md`
or any tracked doc — those are updated alongside code and the tarball
is how those updates reach the working tree. Local scratch files
(`NOTES.md`, `notes.md`, `TODO.local.md`) stay excluded.

### 2. Commit-ready commands

After the tarballs, output the literal command sequence the user
runs against their working tree:

```bash
cd ~/git/frc-scheduler-server
git pull && git add -A
git commit -m "<commit message — see §3 below>"
git push
./openshift/apply.sh --build       # omit for doc-only sessions
```

Then a one-line reminder: hard-refresh browsers (`⌘⇧R` /
`Ctrl+Shift+R`) after deploy when UI changes shipped.

`./openshift/apply.sh --build` is omitted when the session touched
only docs / tests / no-deploy-impact files. When in doubt, include
it — a redundant rebuild costs ~2 minutes; a missed rebuild leaves
production stale.

### 3. Commit message style

Terse, fact-dense, code-anchored. Subject is short with an em-dash
qualifier; body explains *why* and lists *what* with file paths
anchored so a future reader can grep them. No emoji. Hard-wrap the
body at ~72 columns.

Canonical single-issue example:

```
Doc sync — HANDOFF, REPRODUCTION_PROMPT, PRIORITIES current

End-of-session doc sweep capturing all FRC §10.5.2 paramount +
competition-approved + import-cleanup work.

- docs/HANDOFF.md: full rewrite as new 'state of the world' doc
- PRIORITIES.md (root): replaced P1-P10 with lex tuple + paramount cooldown
- REPRODUCTION_PROMPT.md (root): canonical AI onboarding doc, current
- docs/REPRODUCTION_PROMPT.md: stub redirect to root
- docs/PRIORITIES.md: overview updated for lex semantics + Phase 2 complete
- docs/workstreams/scheduler-quality.md: phases 0-4 marked complete
- README.md: Architecture section updated to FRC §10.5.2 paramount framing
```

For multi-issue sessions, structure the body by issue with a brief
header paragraph per issue, then a single trailing `Files: ...`
line listing all touched paths. Keep file lists in `Files:` even
when the body already mentioned them — it's the grep target.

---

## Reading order for new contributors

1. **`README.md`** — what is this thing, install, run.
2. **`PRIORITIES.md`** (root, this directory) — what the algorithm does, the lex tuple semantics.
3. **`docs/ROADMAP.md`** — where the project is going. v1.0/1.1/1.2/2.0 buckets pointing at design docs.
4. **`docs/HANDOFF.md`** — per-session log. What just shipped, what's in flight.
5. **`docs/decisions/`** — Architecture Decision Records (5 to start). Significant choices with reasoning.
6. **`docs/workstreams/`** — design docs for individual planned workstreams (RBAC, lifecycle phases, UI quality exposure, scheduler quality plan).
7. **`docs/PRIORITIES.md`** — algorithmic deep dive (Stage 1/2 implementation details).
8. **`docs/scheduler/`** — algorithm-specific reference and investigation docs.
9. **`tests/phase0a_lex/SUMMARY.md` through `tests/phase2_station/SUMMARY.md`** — per-phase summaries with concrete numbers.
10. **`CONTRIBUTING.md`** (root) — commit conventions, test requirements, session-deliverable protocol.

That should be enough to pick up the codebase and contribute.
