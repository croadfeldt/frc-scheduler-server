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
