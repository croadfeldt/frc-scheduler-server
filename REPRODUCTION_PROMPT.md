# FRC Match Scheduler — Full Reproduction Prompt

Build a two-stage FRC (FIRST Robotics Competition) qualification match scheduler.
Single-file HTML/CSS/JS frontend + FastAPI + PostgreSQL backend.
OpenShift-deployable via Containerfile. GNU GPL v3. AI-generated with human review.

---

## STAGE 1 — ABSTRACT SCHEDULE (slot indices 1..N, no real team numbers)

### Match Count (pure math — Step 1)

```
totalMatches    = ceil(N × MPT / 6)
matchesPerRound = ceil(N / 6)
totalSurSlots   = totalMatches × 6 − N × MPT
phase1Surplus   = matchesPerRound × 6 − N
fairSurCap      = ceil(totalSurSlots / N) + 1
```

### Team Placement (Step 2)

Phase 1 — matchesPerRound matches:
- Every slot plays once before any plays twice.
- Last match fills phase1Surplus slots with early second-plays (NOT surrogates).
- Alliance assignment: enumerate all C(6,3)=20 splits; last-match variant penalises
  unequal second-play distribution (−500 per imbalance unit).
- No slot in Phase 1 is flagged surrogate.

Phase 2 — remaining matches:
```
underQuota = slots with mc[s] < MPT
atQuota    = slots with mc[s] == MPT  (only when surNeeded > 0)
surNeeded  = max(0, 6 − len(underQuota))
```
60 random candidate sets per match; score each; pick best.
Flag slot as surrogate only when mc[s] >= MPT at selection time.

### Post-Generation Sweeps

R1 — No surrogate in last match: swap with earlier match (R2 guard prevents first-appearance)
R2 — No surrogate as first appearance: guard in R1, skip M if M ≤ first_appearance[S]
R3 — No surrogate as last appearance: move flag to earlier non-first appearance (up to 3 passes)

### Priorities

```
P1  [HARD]  6 teams/match, 3 red / 3 blue
P2  [HARD]  Each slot plays exactly MPT times; surrogates fill structural surplus (cap fairSurCap)
P3  [HARD]  Round 1: all slots play once before any plays twice
P4  [HARD]  Cooldown: −1000×(idealGap−gap) if gap < cooldown
P5  [SOFT]  Match equity:       W_COUNT   = 5
P6  [SOFT]  Alliance balance:   W_BALANCE = 50  (all C(6,3)=20 splits)
P7  [SOFT]  Gap maximisation:   W_GAP     = 10
P8  [SOFT]  Opponent diversity: W_OPPONENT= 15
P9  [SOFT]  Partner diversity:  W_PARTNER = 12
P10 [SOFT]  Surrogate fairness: W_SUR_RPT = 200, hard cap fairSurCap
R1  [POST]  No surrogates in last match (team swap)
R2  [POST]  No surrogate as first appearance (guard in R1)
R3  [POST]  No surrogate as last appearance (flag reassignment)
```

### Iteration Scoring

```
score = −(B2B×1000 + maxAllianceImbalance×500 + surrogates×200 + repeatOpponents×15 + repeatPartners×12)
```

Stage 1 runs as a single deterministic pass (iterations=1, no UI iterations field).

### Seeding

`generateMatches(numTeams, matchesPerTeam, idealGap, seed)` — hex string.
JS: mulberry32 (`makeRng(parseInt(seed,16))`). Python: `random.Random(int(seed,16))`.
Same seed → identical output always. Auto-generated per run via `randomSeed()`.

---

## STAGE 2 — TEAM ASSIGNMENT

Input: abstract schedule + N real team numbers + assign_seed (hex)
Method: N iterations with seeded RNG; each shuffles team numbers into slots;
scores against P5–P10 with real numbers; returns best slot_map {slot: team_number}.
Default: 500 iterations. Same assign_seed → same mapping always.

---

## URL REPRODUCIBILITY

After generating, browser URL is updated (no page reload). Opening the URL
auto-restores all config and re-runs Stage 1 (and optionally Stage 2).

### URL Parameter Reference

| Parameter | Example | Description |
|-----------|---------|-------------|
| `n` | `51` | Number of teams |
| `mpt` | `11` | Matches per team |
| `cd` | `3` | Cooldown (matches between appearances) |
| `ct` | `8` | Default cycle time in minutes |
| `days` | `2` | Number of competition days |
| `seed` | `a1b2c3d4` | Stage 1 hex seed |
| `aseed` | `cafebabe` | Stage 2 hex seed |
| `teams` | `254,1114,...` | Team numbers in slot order |
| `d1` | `08:00-17:00` | Day 1 start-end (`HH:MM-HH:MM`) |
| `d2` | `08:00-15:30` | Day 2 start-end |
| `d1b` | `Lunch\|12:00\|13:00,...` | Day 1 breaks: `Name\|start\|end`, comma-separated |
| `d2b` | `Break\|14:30\|14:45` | Day 2 breaks |

Up to 5 days: `d1`–`d5` and `d1b`–`d5b`.

Without `teams`: abstract schedule with S1/S2 labels.
Without `seed`: params applied to UI but auto-run not triggered.

### Example

```
?n=51&mpt=11&cd=3&ct=8&days=2&seed=a1b2c3d4&aseed=cafebabe
  &d1=08:00-17:00&d1b=Lunch|12:00|13:00
  &d2=08:00-15:00
  &teams=254,1114,2052,...
```

---

## UI FLOW

### Event bar (top)
[Year input] [Event code e.g. "mnwi"] [Load]
- Prepends year: "mnwi" + 2025 → "2025mnwi". Checks DB first, falls back to TBA.
- Year auto-sets on event load. Recent events dropdown (secondary).
- Auth bar on right: Sign In / user email + Sign Out.

### Header / Share bar (shown after schedule generated)
- Seed: `a1b2c3d4` (click-to-copy) · assign: `cafebabe`
- Share button: copies full reproducible URL (includes all day/time/break params)
- Duplicate button: shown for any loaded assigned schedule

### Config panel
- Number of Teams, Matches/Team, Cycle Time (min), Number of Days (1–5)
- Match Cooldown
- Timezone selector (IANA, display-only, appends abbreviation to times)
- Auto-generate on parameter change (default ON, 800ms debounce)
  Triggers on Teams, MPT, Cooldown changes. Amber warning if OFF and params changed.
- Cycle Time Changes (per-match overrides)
- Daily Schedule:
  Per-day rows (up to 5), each with:
    - Start Time and End Time (time inputs, HH:MM)
    - Named breaks with start/end times (+ Add Break button)

### Stage 1 button: "⚡ Stage 1: Generate Structure"
→ SSE → abstract schedule (S1/S2 labels) → URL updated with seed + all day params

### Stage 2 panel
- Blue banner if saved assignment found in DB
- Event team count status, Assignment Iterations (default 500)
- "▶ Assign Teams to Schedule" (green)
→ SSE → real team numbers displayed → URL updated with aseed + teams

### Schedule output
- Stats bar: Total Matches, Teams, Matches/Team, Days, B2Bs (filter), Surrogates (filter)
- Surrogates subtitle: "N min · optimal" or "+X extra"
- Filter chips (team, alliance header, day title, stat tiles)
- Per-day tables: match#, time (AM/PM + TZ abbr), Red, Blue
- Surrogate: amber S badge. Back-to-back: blue B2B badge.
- Round boundary rows. Overflow warning only if last day runs out of time.
- Export CSV.

### Schedules modal (History)
- Versions grouped by abstract schedule params
- Latest/v2/v1 badges, timestamps
- View, prominent "⬆ Promote to Active" (accent), Delete per version

### Auth modal
- Google / Apple buttons (shown only if server has credentials configured)
- Popup OAuth flow; token stored in localStorage; Bearer header on all API calls

---

## BACKEND API

```
# Events
GET/POST  /api/events
GET/DEL   /api/events/{id}
GET/POST  /api/events/{id}/teams
DEL       /api/events/{id}/teams/{number}

# TBA
GET       /api/tba/events/{year}?search=
POST      /api/tba/import/{event_key}

# Stage 1
POST      /api/generate-abstract                    SSE → abstract_schedule_id
GET       /api/abstract-schedules?event_id=N
GET/DEL   /api/abstract-schedules/{id}

# Stage 2
POST      /api/abstract-schedules/{id}/assign       SSE → assigned_schedule_id
GET       /api/events/{id}/assigned-schedules        version history
GET       /api/assigned-schedules/{id}               resolved matches + seeds
POST      /api/assigned-schedules/{id}/activate
DEL       /api/assigned-schedules/{id}              requires ownership
POST      /api/assigned-schedules/{id}/duplicate    open to all

# Auth
GET       /auth/google/login        redirect to Google
GET       /auth/google/callback     code exchange → JWT → popup closer
GET       /auth/apple/login         redirect to Apple
POST      /auth/apple/callback      form_post exchange → JWT → popup closer
GET       /auth/me                  {authenticated, sub, email, provider}
GET       /auth/providers           {google: bool, apple: bool}

GET       /api/health
```

---

## DATABASE SCHEMA

```
users
  id, sub (unique: "google:<id>" or "apple:<id>"), provider,
  email, name, created_at, updated_at

events
  id, key (unique e.g. "2025mnwi"), name, year, location,
  start_date, end_date, tba_synced, created_at, updated_at

teams
  id, number (unique), name, nickname, city, state, country, rookie_year

event_teams
  id, event_id FK, team_id FK  (unique)

abstract_schedules
  id, event_id (nullable FK), name,
  num_teams, matches_per_team, cooldown,
  seed (hex, nullable),
  iterations_run, best_iteration, score,
  created_by (nullable OAuth sub),
  matches (JSON — slot indices), surrogate_count (JSON), round_boundaries (JSON),
  created_at

assigned_schedules
  id, abstract_schedule_id FK, event_id FK, name, is_active,
  slot_map (JSON {"1": 254, "2": 1114, ...}),
  day_config (JSON — cycle time, days with start/end/breaks),
  assign_seed (hex, nullable),
  created_by (nullable OAuth sub),
  created_at
  ← Always INSERT. History preserved for revert.

match_rows
  id, assigned_schedule_id FK, match_num,
  red1/2/3, blue1/2/3 (team numbers),
  red1/2/3_surrogate, blue1/2/3_surrogate (bool)
```

---

## ENV VARS

```bash
DATABASE_URL=postgresql+asyncpg://frc:frc@localhost:5432/frc_scheduler
TBA_API_KEY=                # optional
CPU_WORKERS=0               # 0 = auto-detect
JWT_SECRET=                 # openssl rand -hex 32
BASE_URL=                   # https://your-host.example.com
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
APPLE_CLIENT_ID=
APPLE_TEAM_ID=
APPLE_KEY_ID=
APPLE_PRIVATE_KEY=          # PEM with \n for newlines
```

---

## DESIGN SYSTEM

```css
--bg #1a1d27  --surface #22263a  --surface2 #2a2f46  --border #3a4060
--accent #7aa4f0  --accent2 #e07b50  --accent3 #5cb87a
--text #dde2f0  --text-strong #f2f5ff  --text-muted #929cb6
--red-team #e87878  --blue-team #6fa8e8  --amber #c8992a  --danger #cc5555
```
Fonts: Barlow Condensed (700/900) + Barlow (300/400/500). Google Fonts.
Layout: 390px config panel + fluid results panel.

---

## CONTAINER / OPENSHIFT

Two Containerfiles — use the appropriate one for your build target:
- `Containerfile` — generic, `python:3.12-slim` (Docker Hub), apt-get.
  Works with Docker, Podman, and any standard OCI builder.
- `Containerfile.openshift` — OpenShift builds only, `quay.io/sclorg/python-312-c10s`,
  dnf/rpm. Avoids Docker Hub rate limits. Referenced by BuildConfig via
  `dockerfilePath: Containerfile.openshift`. Not for local use.

Both files are rootless-compliant. Runtime env vars (linuxserver.io convention):
  PUID=1000       — process UID (set to $(id -u) for rootless Podman host mapping)
  PGID=1000          — process GID (GID 0 enables OpenShift arbitrary-UID compatibility)
  APP_PORT=8080   — port uvicorn listens on (no capabilities needed for ≥1024)
Entrypoint script (entrypoint.sh): if running as root, creates user matching
PUID/PGID and drops privileges via gosu/runuser before exec-ing uvicorn.
All app files: `chgrp -R 0 /app && chmod -R g=u /app`
Namespace: `frc-scheduler-server`

```
01-secrets.yaml  frc-db-secret, frc-app-secret (TBA), git-contents-token,
                 frc-auth-secret (JWT_SECRET, BASE_URL, GOOGLE_*, APPLE_*)
02-postgres.yaml PVC 5Gi + Deployment + Service
03-buildconfig.yaml  ImageStream + BuildConfig (GitHub, Containerfile, no webhooks)
04-deployment.yaml   App + Service (DATABASE_URL from secret)
05-route.yaml    Edge HTTPS
07-build-trigger-sa.yaml  RBAC for CronJob
08-build-cronjob.yaml     git ls-remote poll every 5 min → oc start-build
```

---

## LICENSING

GNU GPL v3. SPDX-License-Identifier: GPL-3.0-or-later in all source files.
LICENSE includes full GPL v3 text + AI-generation disclosure.
AI use disclosed, human review confirmed, license terms unaffected.

---

## RECENT CHANGES (post initial implementation)

### Frontend — UI / UX

**Time display:** `minToTime(m)` always outputs `H:MM:SS AM/PM` (seconds always shown for consistency with import tools). Converts fractional minutes to total seconds via `Math.round(m * 60)`.

**Cycle time fractions:** Both the main cycle time input and cycle change rows use `type="number" step="any" min="0.1" max="60"`. Any positive decimal is accepted (e.g. `7.3`, `6.75`, `8.25`). All parsing uses `parseFloat` not `parseInt`. Filter allows `c.time > 0`.

**Cycle change rows** now have 4 columns: Day selector + After Match # + New Cycle (min) + Remove. `estimateFirstMatchOfDay(dayIdx)` computes the default match number. Day dropdown rebuilds when numDays changes.

**Break improvements:**
- Every day gets a default 12:00–13:00 Lunch break (not just Day 1)
- Break name `input`/`change` events trigger auto-recalc
- `addBreak()` defaults to noon–1pm (first break) or 1hr after last break end (subsequent)
- Break remove button wired via `addEventListener` not inline onclick

**Validation:** `validateTimes()` checks day start/end and break start/end. Invalid inputs get `.input-error` class (red border). Error message shown below days config. Generate button blocked with status message.

**Auto-populate gate:** `onParamChanged` only schedules auto-generate debounce if `_abstractParams !== null` (Stage 1 has run at least once). No auto-calc on fresh page load.

**AbortController:** `_s1AbortController` cancels any in-flight Stage 1 SSE fetch before starting a new one on param change. `AbortError` in catch is silently ignored.

**Debounce:** 1500ms (increased from 800ms).

**503/502/504 retry:** Client detects these status codes before throwing, shows "Server busy" status, retries once after 3s. Network drops also retry once after 3s.

**Stage 1 display:** Abstract mode shows `—` (dimmed, opacity 0.35) instead of slot labels (S1, S2…). Stage 1 is team-agnostic structure only.

**Round boundaries:** Reduced visual weight — dashed border, muted color, 0.55 opacity, 3px dot.

**Overflow warnings:** Moved from inline `warning-box` divs in the schedule output to `showApiStatus(…, true)` in the status bar.

**Color scheme:** Catppuccin-inspired — `--accent: #89b4fa`, `--accent2: #f38ba8`, `--accent3: #a6e3a1`, `--text: #cdd6f4`, `--amber: #f9e2af`, `--danger: #f38ba8`, `--bg: #13151f`, `--surface: #1e2235`.

### Backend — Server

**DB session lifecycle:** `generate_abstract` and `assign_teams` no longer hold a DB session open during CPU-bound worker execution. Each opens `async with AsyncSessionLocal() as db:` only for the actual read or write — prevents connection pool exhaustion under load.

**Generation semaphore:** `asyncio.Semaphore(max(2, cpu_count // 2))` limits concurrent Stage 1+2 generations. If fully acquired, stream immediately returns `{type: error, message: "Server busy"}` so the client retries rather than the request hanging.

**`WEB_WORKERS` env var:** Controls uvicorn process count (default 1, OpenShift deployment sets 2). Each worker has its own ProcessPoolExecutor and semaphore.

**422 logging:** `RequestValidationError` handler logs full request body and Pydantic errors at ERROR level.

**Seed validation:** `AbstractGenerateRequest` has `@field_validator('seed', mode='before')` that coerces empty string to `None`.

**`matchesPerTeam` fallback:** `|| 6` default prevents NaN being sent to API.

**`animInterval` scope:** Declared outside `try` block so `catch` can call `clearInterval`.

### Container / Deployment

**`entrypoint.sh`:** linuxserver.io PUID/PGID convention. When running as root, creates user matching PUID:PGID and drops privileges via `gosu` (Debian) or `runuser` (RHEL). Non-root (OpenShift arbitrary UID) runs directly.

**Defaults:** `PUID=1000`, `PGID=1000`, `APP_PORT=8080`, `WEB_WORKERS=1`.

**OpenShift route:** `haproxy.router.openshift.io/timeout: 120s` annotation on `05-route.yaml`.

**`rebuild.sh`:** Full teardown + registry credential refresh (Removed→Managed NooBaa cycle) + wait for registry deployment + secrets + postgres + buildconfig + builder SA wait + image-builder role grant + build (no `--follow`, polls status via `wait_for_build`) + deploy + route + cronjob. `set -euo pipefail`.

### Cycle time and number of days (UI)

`cycleTime` and `numDays` are **visible fields** in the parameters section.

**`cycleTime` (Default Cycle Time):** One-way push — changing the field updates all day start-of-day cycle rows. Secondary after-match cycle time changes are never affected. A blue `#cycleTimePushWarning` div is shown for 4 seconds to confirm the update.

**`numDays` (Number of Days):** Bidirectionally synced with day rows. Changing the field calls `buildDaysUI()` to add rows or removes excess rows. `addDay()` / `removeDay()` also update the `numDays` field.

**End time rules (enforced by `applyDayEndTimes()`):**
- All days except the last default to `18:00`
- The last day always defaults to `12:00` (noon)
- Only "default" end times (`17:00`, `18:00`, `12:00`) are updated — user-customised times are left alone
- Called on: `buildDaysUI`, `addDay`, `removeDay`, `numDays` field change, `fullReset`

**`pruneAfterEndTime(row)`:** When a day's end time shrinks (e.g. on remove), removes breaks whose start ≥ new end time, and after-match cycle changes beyond the approximate last schedulable match.

**`renumberDays()`:** Updates day header text and `dataset.day` for all rows. Also hides the remove button on Day 1.

`cycleTime` and `numDays` are **hidden inputs** — not visible fields. The visible cycle time is the "Cycle Time (min)" field inside each day's start-of-day cycle change row. Changing Day 1's start-of-day cycle time syncs the hidden `cycleTime` input so downstream JS (calcMaxMatches, estimateFirstMatchOfDay, etc.) stays consistent.

Days are managed via `addDay()` / `removeDay(dayEl)` buttons:
- `+ Add Day` button below the last day row. Max 5 days. Default end time: Day 1 = 17:00, Day 2+ = 12:00 (noon).
- Each day row header has a ✕ remove button (Day 1 has none).
- `buildDaysUI()` reads the hidden `numDays` input and adds missing rows up to that count.

### Full Reset button

Two-stage reset available from the ✖ Reset button in both the config panel header (always visible) and the share bar:
1. First confirm clears results: abstract/assigned schedule IDs, seeds, slot map, rendered schedule, stats, filter bar, URL params. Parameters kept.
2. Second confirm optionally resets parameters to defaults (numTeams=24, mpt=8, cooldown=3, cycleTime=8, numDays=2, cycleChanges cleared, days rebuilt).

### Break buffer

`breakBuffer` field (default 5 min) in the config panel, stored in `dayConfig.breakBuffer`.

Applied in `finishGeneration` scheduling loop:
1. Before each match, find the next break or end-of-day boundary.
2. If `boundary - cursor < breakBuffer`, flush the break (if one exists before day end) or roll to next day.
3. This prevents scheduling a match that would start with insufficient time before a break.

Also applied identically in `calcMaxMatches()` simulation.

Day title shows effective cycle time: single value `· 8 min/match` or progression `· 8 min → 7.5 min` when cycle changes exist.
Cycle change row label shows: `⇅ Cycle time → 7.5 min · starts match 46 at 12:00:00 PM`.

### Calc Max Matches button

`calcMaxMatches()` — simulates stepping through all days/breaks/cycle changes with exact cursor logic matching `finishGeneration`. Counts how many matches fit, computes `floor(totalSlots*6 / numTeams)` and writes to the Matches per Team field. Status shows match count, slot count, and surrogate count.

### Show / Hide Slot Numbers toggle (fake teams)

`toggleFakeTeams()` — flips `window._frcShowFakeTeams` and `window._frcAbstractMode`:
- Off (default after Stage 1): `_frcAbstractMode=true` → `—` in team cells, B2B stat=0
- On: `_frcAbstractMode=false`, `_frcShowFakeTeams=true` → italic `S1`…`SN` with tooltip, B2B recalculated with slot indices

`updateB2BStat()` — standalone function to recompute and display B2B respecting abstract mode. Called by toggleFakeTeams and finishGeneration.

Button shown after Stage 1 completes, hidden on Stage 1 regeneration and after real teams are assigned.

### Commit button & server-side logging

**Commit button** (`btnCommit`) appears below Assign Teams after Stage 2 completes. Calls `/api/assigned-schedules/{id}/activate` (POST), then calls `/api/log-commit` (POST) with the full structured payload. Button changes to "✓ Committed" and disables. Resets on Stage 2 re-run or Stage 1 regeneration.

**`/api/log-commit` endpoint** (POST, status 204):
- Pydantic model `CommitLogEntry` with fields: `event`, `timestamp`, `url`, `event_info`, `schedule`, `parameters`, `day_config`, `teams`, `match_count`, `surrogate_count`, `stats`.
- Logs `SCHEDULE_COMMITTED` summary at INFO level (user, event key, schedule ID, team count, match count, seeds).
- Logs `SCHEDULE_COMMITTED_DETAIL` full JSON at DEBUG level.
- Auth optional — `created_by` captured from JWT if present.

**URL params — complete list:**
`n`, `mpt`, `cd`, `ct`, `days`, `seed`, `aseed`, `d1`–`d5` (HH:MM-HH:MM), `d1b`–`d5b` (Name|start|end,...), `teams` (slot-ordered comma list), `cc` (Day:AfterMatch:Time,... for cycle changes).

URL updated after Stage 1 completes AND after Stage 2 completes. All params needed to fully reproduce or retrieve any committed schedule are present.

### Break buffer

`breakBuffer` field (default 5 min) in the config panel, stored in `dayConfig.breakBuffer`.

Applied in `finishGeneration` scheduling loop:
1. Before each match, find the next break or end-of-day boundary.
2. If `boundary - cursor < breakBuffer`, flush the break (if one exists before day end) or roll to next day.
3. This prevents scheduling a match that would start with insufficient time before a break.

Also applied identically in `calcMaxMatches()` simulation.

Day title shows effective cycle time: single value `· 8 min/match` or progression `· 8 min → 7.5 min` when cycle changes exist.
Cycle change row label shows: `⇅ Cycle time → 7.5 min · starts match 46 at 12:00:00 PM`.

### Calc Max Matches button

`calcMaxMatches()` — simulates the exact scheduling loop across all days/breaks/cycle changes, counting how many matches fit. Divides `totalSlotMatches * 6` by `numTeams` to get `mpt = floor(...)`. Verifies `ceil(numTeams * mpt / 6) <= totalSlotMatches`, backs off by 1 if not. Writes result to `#matchesPerTeam`, calls `onParamChanged()`. Reports surrogates needed. Button: `#btnCalcMaxMatches`.

### Show Slot Numbers toggle

`toggleFakeTeams()` — flips `window._frcShowFakeTeams` (bool) and `window._frcAbstractMode` inversely. Calls `renderSchedule()` then `updateB2BStat()`.

- Off (default after S1): `_frcAbstractMode=true` → `—` in team cells, B2B=0
- On: `_frcAbstractMode=false`, `_frcShowFakeTeams=true` → slot numbers as italic `S1`…`SN`, B2B recalculated with slot indices

Button `#btnShowFakeTeams`: hidden initially, shown after S1 completes, hidden on S1 regen or S2 real-team load. Label toggles "Show Slot Numbers" / "Hide Slot Numbers". Accent outline/color when active.

`updateB2BStat()` — standalone function that recomputes B2B from `_frcScheduled` entries respecting `_frcAbstractMode`. Called by `toggleFakeTeams()` and after schedule renders.

`renderTeam(team, isSurrogate, isB2B, colorClass)` — three modes:
1. `_frcAbstractMode`: `—` at 35% opacity
2. `_frcShowFakeTeams && !_currentSlotMap`: italic `S{team}` at 60% opacity with tooltip
3. Real teams: clickable team number as normal

### B2B stat in finishGeneration
`const b2b = window._frcAbstractMode ? 0 : b2bRaw` — zero in abstract mode regardless of slot-index coincidences.

### URL params — no change
`mpt` already encodes matches per team. `calcMaxMatches` writes to the field which is then captured by `buildShareUrl`. Fake teams toggle is transient display state and is not URL-encoded.

### fullReset()

Clears all schedule state back to blank slate. Triggered by ✗ Reset button in share bar.

- Aborts any in-flight Stage 1 SSE request via AbortController
- Nulls: `_currentAbstractScheduleId`, `_currentAssignedScheduleId`, `_abstractParams`, `_currentSlotMap`, `_currentSeed`, `_currentAssignSeed`, `_urlAutoTeams`
- Resets: `_frcScheduled`, `_frcAbstractMode=true`, `_frcShowFakeTeams=false`, `_frcRoundBoundaries`, `_frcFilters`, retry counters
- Hides: stage2Panel, progressWraps, paramChangedWarning, loadFromDbBanner, btnCommit, shareBar, btnShowFakeTeams, btnSavedSchedules (disabled)
- Restores scheduleOutput to empty-state div
- Resets all stat bar values to —
- Calls `window.history.replaceState` to clear URL params
- Asks confirmation before proceeding

### calcMaxMatches()

Steps through all days/breaks/cycle changes using the same cursor logic as schedule rendering.
Counts how many matches fit (`totalSlotMatches`). Each match provides 6 player-slots.
`mpt = floor(totalSlotMatches * 6 / numTeams)`. Verifies `ceil(numTeams * mpt / 6) <= totalSlotMatches`, backs off by 1 if not.
Writes result to matchesPerTeam input. Shows status with match count, slot count, and surrogate count.

### toggleFakeTeams()

`window._frcShowFakeTeams` boolean. When toggled on:
- `_frcAbstractMode = false` — slot numbers are rendered
- `renderTeam()` shows `S{n}` in italic at 60% opacity with tooltip "Slot N (no real team assigned)"
- B2B stat recalculated with slot indices (may be non-zero)
When toggled off: `_frcAbstractMode = true`, dashes shown, B2B = 0.
Button hidden when real teams are assigned (loadAssignedSchedule resets it).


### Download buttons (CSV / JSON)

Appear in the Schedule Output panel header after Stage 1 or Stage 2 completes. Hidden on reset.

**CSV** (`downloadCSV`) — `frc_schedule.csv` columns: Match, Day, Time (H:MM:SS AM/PM), Red 1, Red 2, Red 3, Blue 1, Blue 2, Blue 3, Surrogates (semicolon-separated team numbers).

**JSON** (`downloadJSON`) — `frc_schedule.json` structure:
```json
{
  "generated_at": "...",
  "abstract_schedule_id": 12,
  "assigned_schedule_id": 7,
  "seed": "a1b2c3d4",
  "assign_seed": "cafebabe",
  "parameters": { "num_teams":51, "matches_per_team":11, "cooldown":3,
                  "cycle_time_min":8, "num_days":2, "cycle_changes":[...] },
  "day_config": { ... },
  "days": [
    { "day": 1, "entries": [
      { "type":"break", "name":"Lunch", "start":"12:00:00 PM", "end":"1:00:00 PM" },
      { "type":"match", "match":1, "time":"8:00:00 AM", "time_min":480,
        "red":[254,1114,148], "blue":[27,67,111], "surrogates":[] },
      { "type":"cycle-change", "after_match":45, "new_cycle_min":7.5, "at":"2:00:00 PM" }
    ]}
  ]
}
```
Includes break rows and cycle-change rows interleaved with matches. `time_min` is fractional minutes from midnight for precise import.


### TBA Event Dropdown

The event code input in the event bar has an inline dropdown overlay (`#tbaDropdown`) that shows TBA-registered events for the selected year.

**Behaviour:**
- On page load, `fetchTbaDropdown()` is called after 800ms to pre-populate the dropdown for the current year
- When the year field changes (`onEventYearInput`), a 600ms debounce fires `fetchTbaDropdown()`
- Results are cached in `_tbaDropdownCache[year]` to avoid repeat API calls
- Typing in the code input calls `filterTbaDropdown(query)` which shows/hides rows by key or name match
- Clicking a row calls `selectTbaEvent(key)` which fills the input and immediately calls `loadEventByCode()`
- Clicking outside the input/dropdown hides it; focusing the input re-shows it if data is loaded
- If TBA is not configured or the request fails, the dropdown is silently skipped (no error shown)

### Authentication Setup

Auth is optional. The "no auth providers configured" message means `GOOGLE_CLIENT_ID` / `APPLE_CLIENT_ID` env vars are empty strings. Set them in `openshift/01-secrets.yaml` (see README for full steps).

`JWT_SECRET` must also be set or token issuance will fail with a 500 error. Generate with: `openssl rand -hex 32`

The server reads `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `APPLE_CLIENT_ID`, `APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_PRIVATE_KEY` from env at startup. The `/auth/providers` endpoint returns `{"google": bool, "apple": bool}` so the frontend only shows configured provider buttons.

### Default day start/end times

`buildDaysUI()` sets defaults based on day index:
- Day 1 (`i === 0`): start `09:00`, end `18:00` (until `applyDayEndTimes` sets last day to `12:00`)
- Day 2+ (`i > 0`): start `08:45`, end `18:00`
- Last day always: end `12:00` (enforced by `applyDayEndTimes()`)

### Auto-generate 503 mitigation

- Debounce delay: 2500ms (increased from 1500ms) to consolidate rapid field edits
- `window._stage1RetryCount` is reset to `0` at the start of every `generateSchedule()` call, not just on success, so accumulated retries from one burst don't exhaust the budget for the next
- AbortController cancels any in-flight Stage 1 request before starting a new one

### Break buffer logic

`breakBuffer` (field `#breakBuffer`, URL param `bb`, default 5 min).

**Condition to schedule a match before a break (start-based):**
```
breakStart - cursor >= breakBuffer   →  schedule
breakStart - cursor <  breakBuffer   →  flush break early
```

- Equal counts: cursor=11:55, buffer=5, lunch=12:00 → gap=5 ≥ 5 → **schedule** (even if cycle=8 means it ends at 12:03)
- cursor=11:56 → gap=4 < 5 → **flush break early**
- The cycle time is **not** part of the check.

**Interrupt suppression:** After the buffer check passes, the interrupt check (which detects a break starting *inside* a match's cycle window) is suppressed. Without this, a match starting at 11:55 with cycle=8 would be cancelled by the interrupt check because lunch at 12:00 falls within 11:55–12:03. The guard:
```javascript
const interruptBreak = (!nextBreak || breakBuffer <= 0 || (nextBreak.start - cursor < breakBuffer))
  ? breaks.find(b => !b.done && b.start > cursor && b.start < matchEnd)
  : null;
```

**`_assigningTeams` guard:** `window._assigningTeams = true` is set at the start of Stage 2 completion and cleared after 100ms. `onParamChanged()` returns immediately if this flag is set, preventing the `autoPopulate` debounce from firing a new Stage 1 generate immediately after teams are assigned (which would wipe the assigned schedule).

**`doneMsg2` scope fix:** declared with `let` before the `try {}` block (not inside it) so the `catch` block can reference it to detect successful completion even when the stream close throws.

Applied in `_finishGenerationInner` and `calcMaxMatches`.
`bb` encoded in share URL, restored via `applyUrlParams`.
### FRC Events API (`app/frc_events.py`)

HTTP Basic auth: `base64(FRC_EVENTS_USERNAME:FRC_EVENTS_TOKEN)`. No credentials → `ValueError` → HTTP 503.

Key functions:
- `get_events(year)` — `GET /{year}/events` → `data["Events"]`
- `get_event(year, code)` — same endpoint with `?eventCode=CODE` (uppercase), returns first or None
- `get_event_teams(year, code)` — `GET /{year}/teams?eventCode=CODE`, paginates (page size 65)
- `normalise_event(frc, year)` — converts FRC dict to our schema; builds `key = f"{year}{code.lower()}"`, stores original code in `_frc_code` (stripped before DB write)
- `normalise_team(frc)` — maps `teamNumber`, `nameFull`/`nameShort`, `city`, `stateProv`, `country`, `rookieYear`
- `is_configured()` — bool, used by `/api/frc/configured` + `/api/frc/status`

Routes (single set, no duplicates):
- `GET /api/frc/configured` and `GET /api/frc/status` → same handler via stacked decorators
- `GET /api/frc/events/{year}` → list/search
- `POST /api/frc/import/{year}/{event_code}` → upsert event + teams into DB

Frontend integration:
- `getEventSource()` reads `#eventSource` select (`tba` or `frc`)
- `fetchTbaDropdown()` branches on source; FRC path hits `/api/frc/events/{year}`
- Credential errors surfaced immediately in `showApiStatus` (not hidden in dropdown)
- `loadEventByCode()` uses `/api/frc/import/{year}/{frcCode}` when source=frc
- Cache key: `frc_{year}` in `_frcDropdownCache`


### Stage 2 search: simulated annealing (`scheduler.py: assign_teams`)

```python
budget = num_teams * 2   # steps per iteration (matches old hill-climber count)
T0 = 500.0               # initial temperature
for step in range(budget):
    T = T0 * (1.0 - step / budget)   # linear cooling
    a, b = _rng.sample(slots, 2)
    # swap, score, compute delta
    if delta >= 0: accept
    elif T > 0 and delta/T > -10 and random() < exp(delta/T): accept
    else: revert
```

**Budget kept at `num_teams × 2`** to match original hill-climber performance (~90ms/iter per worker). 3-way rotation removed — calling `score_assignment` on every step is already expensive; 3-way didn't improve score enough to justify 3× overhead.

**Score display in progress bar:** decoded into `N B2B, N imbal, N sur, rep` or `✓ optimal`.

### Iteration estimate (`updateIterationEstimate`)

- Default `window._msPerIteration = null` → uses `11ms` fallback (benchmark: 90ms/worker ÷ 8 workers)
- After run: `window._msPerIteration = elapsed / iterations` (wall-clock, parallelism already included)
- Guard: `!== null` not `||` so a calibrated value of `0` (impossibly fast) wouldn't revert to default
- Called from: `showStage2Panel()`, post-calibration in `assignTeams()`, `oninput`/`onchange` on `#assignIterations`

### TBA dropdown — sort and row limit

`tba.py: get_events(year)` now calls `events.sort(key=lambda e: e.get("start_date") or "")` before returning. Previously events came back in TBA's alphabetical-by-key default order, which put late-alphabet events (e.g. `2026wasno`) past the old 200-row cap.

`populateTbaDropdown()` previously used `events.slice(0, 200)` — removed. All events are now rendered; filter-as-you-type limits visible rows.

### TBA error handling (`loadEventByCode`)

Four distinct error messages based on `e.message` content matching server's `detail` field:
- `includes('not found on The Blue Alliance')` → event key wrong/missing
- `includes('No TBA_API_KEY') || includes('503')` → server not configured  
- `includes('timed out') || includes('504')` → retry
- fallback → shows raw message

`showApiStatus(msg, isErr)`: errors no longer auto-hide (only success messages do, after 3s). Uses `clearTimeout(window._apiStatusTimer)` to prevent stale hides.

### Break/cycle-change row Tab navigation

`addBreak()`: on new row (no pre-filled nameVal), focuses break-name with `.select()`. Tab handlers:
- name `Tab` → break-start
- break-start `Tab` → break-end, `Shift+Tab` → break-name
- break-end `Shift+Tab` → break-start

`addDayCycleChange()`: on new row (no afterMatch), focuses cc-after with `.select()`. Tab handlers:
- cc-after `Tab` → cc-time, cc-time `Shift+Tab` → cc-after

Fields added during restore (nameVal or afterMatch pre-filled) skip auto-focus entirely.

### `applyDayConfigToUI(dc)`

Restores a `day_config` object (from `AbstractSchedule.day_config` or `AssignedSchedule.day_config`) back into the UI fields. Called during `?sid=` restore so the UI reflects the exact timing config used when the schedule was generated.

Steps: sets `cycleTime`, `breakBuffer`; calls `buildDaysUI()` with the correct `numDays`; for each day row sets `start`/`end`, clears and re-adds breaks via `addBreak()`, updates the start-of-day cycle time input, and adds after-match cycle changes via `addDayCycleChange()`.

### `AbstractSchedule.day_config` (DB column)

`JSON, nullable=True` — stores the full `collectDayConfig()` snapshot at Stage 1 time. This makes `?sid=` restores fully self-contained: no URL timing params needed. The column is also copied by the duplicate endpoint.

**DB migration required for existing databases:**
```sql
ALTER TABLE abstract_schedules ADD COLUMN IF NOT EXISTS day_config JSON;
```
See `migrate_abstract_day_config.sql`.

### Schedule & assignment IDs (`sid` / `aid`)

**Share bar** (visible after Stage 1):
```
Schedule ID: #16  seed: 1f213205  ·  Assignment ID: #7  assign seed: cafebabe
```
- `#16` = `_currentAbstractScheduleId` (DB PK). Clicking copies it; tooltip shows `?sid=16`.
- `#7` = `_currentAssignedScheduleId` (DB PK). Clicking copies it; tooltip shows `?aid=7`.
- Seeds are shown smaller/dimmed as secondary identifiers.

**`buildShareUrl`** encodes `sid` and `aid` alongside seed/aseed.

**`autoRunFromUrl` restore priority:**
1. `params.aid` → `GET /api/assigned-schedules/{aid}` + `GET /api/abstract-schedules/{abstract_id}` → `loadAssignedSchedule()` (no regeneration)
2. `params.sid` → `GET /api/abstract-schedules/{sid}` → `displayAbstractSchedule()` + `checkForSavedAssignment()` (no regeneration)
3. `params.seed` → `generateScheduleWithSeed()` (original client-side path)

**`updateSeedDisplay(seed, assignSeed)`** updates both seed text and ID badges. ID badges also updated via `refreshIdBadges()` when IDs change independently.

**Copy functions:** `copyAbstractId()`, `copyAssignedId()`, `copySeed()`, `copyAssignSeed()` — all show a status message explaining how to use the copied value in a URL.

### db.py column types

`teams.name`, `events.name`, `events.location` use `Text` (SQLAlchemy `Text`, PostgreSQL `TEXT`, unlimited length). Needed because TBA sponsor names regularly exceed 256 characters. Import `Text` from `sqlalchemy` alongside `String`.

### matches_per_team limit

API model: `Field(6, ge=1, le=50)`. Frontend input: `max="50"`. Previously capped at 20 which was too low for small team counts with long schedules.

### tba.py — per-request httpx client

```python
async with httpx.AsyncClient(base_url=TBA_BASE, headers=..., timeout=15.0) as client:
    resp = await client.get(path)
```

No module-level singleton. Previous singleton was created at import time (outside async event loop) causing silent hangs → raw OCP 502s.

---

## Agenda Fit Integration (from frc-schedule-builder)

Ported from `github.com/phil-lopreiato/frc-schedule-builder` — a standalone HTML tool by Phil Lopreiato.

### State
```javascript
let _agendaBlocks = null;  // [{start, end, duration, startStr, endStr, day}] or null
```

### PDF.js loading (`loadPdfJs`)
Cannot use `import()` directly in a non-module script tag. Uses a dynamically injected `<script type="module">` that imports PDF.js from CDN and dispatches a `pdfjsloaded` event, exposing the lib on `window._pdfjsLib`. Deduped via `_pdfjsLoading` promise.

```
CDN: https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379
Files: pdf.min.mjs, pdf.worker.min.mjs
```

### PDF fetch (`fetchAgendaPDF(eventKey)`)
```
GET https://info.firstinspires.org/hubfs/web/event/frc/{year}/{YEAR}_{EVENTCODE}_Agenda.pdf
```
Requires CORS to be open on FIRST's CDN (it is for GET requests). Throws if status ≠ 200 or content-type ≠ pdf.

### PDF parsing (`parsePDFBlocks`, `parseQualBlocks`)
1. Extract text per page, group items by Y coordinate (PDF coordinate space), sort Y descending, join items by X ascending → reconstructs lines
2. Collapse PDF.js character-spacing artifacts in time tokens (regex: digits with internal spaces before AM/PM)
3. Line-by-line scan:
   - Day pattern: `Monday|Tuesday|…` followed by month+day
   - Qual block pattern: `HH:MM AM/PM – HH:MM AM/PM Qualification Match`
4. Fallback: scan joined full text if line-by-line finds nothing

### Fit calculation (`updateAgendaFit`)
Called on: `activateEvent` completion, `numTeams`/`matchesPerTeam`/`cycleTime` input events, manual minutes change.

```
totalMatches = ceil(numTeams * mpt / 6)
surrogates   = totalMatches * 6 - numTeams * mpt
timeNeeded   = totalMatches * cycleTime
available    = sum(_agendaBlocks[i].duration)  OR  agendaManualMin input
surplus      = available - timeNeeded
pct          = timeNeeded / available * 100
reqCycle     = available / totalMatches
```

### Block distribution (`distributeMatchesToBlocks`)
When fits (surplus ≥ 0): distribute proportionally by block duration using floor + fractional remainder sort.
When over: fill each block to floor capacity, pour overflow into block[1] (Saturday/later block).

### HTML elements
- `#agendaFitPanel` — outer container, hidden until event loaded
- `#agendaFitBadge` — fit status badge in header
- `#agendaChevron` — collapse/expand indicator
- `#agendaFitLoading` — loading/error text
- `#agendaFitStats` — 5-stat grid (time needed, available, buffer, capacity%, max cycle)
- `#agendaFitBlocks` — per-block rows with timeline bars (`#agendaBar_{start}`)
- `#agendaFitManual` — shown when PDF unavailable; contains `#agendaManualMin`

### Lifecycle hooks
- `activateEvent(ev)` → calls `fetchAndRenderAgendaFit(ev.key)` (non-blocking, `.catch(() => {})`)
- `fullReset()` → calls `resetAgendaPanel()` (hides panel, clears `_agendaBlocks`)
- `['numTeams','matchesPerTeam','cycleTime']` input events → `onScheduleParamsChanged()` → `updateAgendaFit()`
