# FRC Match Scheduler — Full Reproduction Prompt

Build a two-stage FRC (FIRST Robotics Competition) qualification match scheduler.
Single-file HTML/CSS/JS frontend + FastAPI + PostgreSQL backend.
OpenShift-deployable via Containerfile. GNU GPL v3. AI-generated with human review.

---

## STAGE 1 — ABSTRACT SCHEDULE (slot indices 1..N, no real team numbers)

### Match Count (pure math — Step 1)

```
totalMatches    = ceil(N × MPT / 6)
matchesPerRound = ceil(N / 6)          ← Phase 1 only; cosmetic marker after
totalSurSlots   = totalMatches × 6 − N × MPT
phase1Surplus   = matchesPerRound × 6 − N
fairSurCap      = ceil(totalSurSlots / N) + 1
```

### Team Placement (Step 2)

Phase 1 — matchesPerRound matches, Round 1 strict:
- Every slot plays once before any plays twice.
- Last match fills phase1Surplus slots with early second-plays (NOT surrogates).
- Alliance assignment: enumerate all C(6,3)=20 splits; last-match variant penalises
  unequal second-play distribution (−500 per imbalance unit).
- No slot in Phase 1 is flagged surrogate.

Phase 2 — remaining matches, open scheduling:
```
underQuota = slots with mc[s] < MPT
atQuota    = slots with mc[s] == MPT  (only drafted when surNeeded > 0)
surNeeded  = max(0, 6 − len(underQuota))
```
Run 60 random candidate sets per match. Score each. Pick best.
Flag slot as surrogate only when mc[s] >= MPT at selection time.

### Post-Generation Sweeps (deterministic, after greedy phase)

R1 — No surrogate in last match:
  For each surrogate S in last match, find non-surrogate R in same match.
  Find earlier match M where S appears and R is absent, and M > first_appearance[S].
  Swap S↔R between M and last match. Surrogate flag moves to M.

R2 — No surrogate as first appearance:
  Guard inside R1: only accept match M if M index > first_appearance[S].

R3 — No surrogate as last appearance:
  If a slot's last appearance is flagged surrogate, move the flag to any earlier
  non-first appearance of the same slot. No teams change matches. Up to 3 passes.

### Priorities

```
P1  [HARD]  6 teams/match, 3 red / 3 blue
P2  [HARD]  Each slot plays exactly MPT times. Surrogates fill structural surplus (cap fairSurCap)
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

```js
generateMatches(numTeams, matchesPerTeam, idealGap, seed)
```

`seed` is a hex string. JS uses mulberry32 PRNG (`makeRng(parseInt(seed,16))`),
Python uses `random.Random(int(seed,16))`. Both replace all Math.random() / random.random()
calls so the same seed always produces identical output.
A new seed is auto-generated (`randomSeed()`) on each Stage 1 run.

---

## STAGE 2 — TEAM ASSIGNMENT

Input: abstract schedule + N real team numbers + assign_seed (hex string)
Method: N iterations with seeded RNG. Each shuffles team numbers into slots,
scores against P5–P10 with real numbers, returns best slot_map {slot: team_number}.
Default iterations: 500. Same seeded approach — same assign_seed → same mapping.

---

## URL REPRODUCIBILITY

After generating, browser URL is updated (no page reload) with all params:

```
?n=51&mpt=11&cd=3&seed=a1b2c3d4&aseed=cafebabe&teams=254,1114,2052,...
```

- `n` = numTeams, `mpt` = matchesPerTeam, `cd` = cooldown
- `seed` = Stage 1 hex seed, `aseed` = Stage 2 hex seed
- `teams` = comma-separated team numbers in slot order (slot 1 first)

On load: parse URL → pre-fill config → auto-run Stage 1 with seed.
If teams present and event loaded → auto-run Stage 2.
Without teams: abstract schedule shows with S1/S2 slot labels.
Share button copies the full URL to clipboard.

---

## UI FLOW

### Event bar (top)
[Year input (default current year)] [Event code input e.g. "mnwi"] [Load]
- Prepends year: "mnwi" + 2025 → "2025mnwi". Checks local DB first, falls back to TBA.
- Year auto-sets when event loads from TBA or dropdown.
- Recent events dropdown (secondary).
- Auth bar on right: Sign In button / user email chip + Sign Out.

### Header / Share bar
Shown after schedule generated. Contains:
- Seed display: "Seed: a1b2c3d4" (click to copy) + "· assign: cafebabe" if Stage 2 done
- Share button: copies full reproducible URL
- Duplicate button: shown when a saved assigned schedule is loaded (any user can duplicate)

### Config panel
- Number of Teams, Matches/Team, Cycle Time (min), Number of Days
- Match Cooldown (matches between appearances for a team)
- Timezone selector (IANA, display-only, appends abbreviation to match times)
- Auto-generate on parameter change (default ON, 800ms debounce)
  - Changes to Teams, MPT, Cooldown trigger automatic Stage 1 regeneration
  - Amber warning banner if params changed with auto-populate OFF
  - Assign button disables until Stage 1 re-run
- Cycle Time Changes (per-match overrides)
- Daily Schedule (per-day start/end, named breaks)

### Stage 1 button: "⚡ Stage 1: Generate Structure"
- Streams SSE progress
- Displays abstract schedule with S1/S2 slot labels
- Updates URL with seed and params
- Stage 2 panel opens below

### Stage 2 panel
- Blue "Saved schedule found" banner if saved assignment exists for this abstract+event
- Stage 2 status: event team count vs schedule count, ready/mismatch
- Assignment Iterations input (default 500)
- "▶ Assign Teams to Schedule" button (green)
- Streams SSE progress → displays resolved schedule with real team numbers
- Updates URL with aseed and teams, saves to DB (always new record = history preserved)

### Schedule output
- Stats bar: Total Matches, Teams, Matches/Team, Days, Back-to-Backs (clickable), Surrogates (clickable)
- Surrogates subtitle: "N min · optimal" or "N min · +X extra"
  Minimum = ceil(N×MPT/6)×6 − N×MPT (tooltip shows full math)
- Filter chips (team number, alliance header, day title, stat tiles)
- Per-day tables: match#, time (AM/PM + TZ abbr), Red Alliance, Blue Alliance
- Surrogate: amber "S" badge
- Back-to-back: blue "B2B" badge
- Round boundary rows every matchesPerRound matches
- Overflow warning ONLY if last day runs out of time (not for intermediate days)
- Export CSV

### Schedules modal (History)
- Versions grouped by abstract schedule parameters (teams/MPT/cooldown)
- Each version: Latest/v2/v1 badge, timestamp, name
- View button, prominent "⬆ Promote to Active" button (accent colour, non-active only)
- Delete button per version

### Auth modal
- Google "Continue with Google" button (shown if GOOGLE_CLIENT_ID configured)
- Apple "Continue with Apple" button (shown if APPLE_CLIENT_ID configured)
- Opens OAuth in popup window; token posted back via postMessage then stored in localStorage

### Client/server fallback
- Server available → SSE streams, saves to DB
- Server error → Web Workers (one per hardware core) → single-threaded fallback
- Client-side generates abstract schedule (S1/S2 labels); Stage 2 requires server

---

## BACKEND API

```
# Events
GET  /api/events
POST /api/events
GET  /api/events/{event_id}
DEL  /api/events/{event_id}
GET  /api/events/{event_id}/teams
POST /api/events/{event_id}/teams
DEL  /api/events/{event_id}/teams/{number}

# TBA
GET  /api/tba/events/{year}?search=
POST /api/tba/import/{event_key}

# Stage 1
POST /api/generate-abstract                    → SSE stream → abstract_schedule_id
GET  /api/abstract-schedules?event_id=N
GET  /api/abstract-schedules/{id}              (includes seed, created_by)
DEL  /api/abstract-schedules/{id}

# Stage 2
POST /api/abstract-schedules/{id}/assign       → SSE stream → assigned_schedule_id
GET  /api/events/{id}/assigned-schedules       (version history, includes num_teams/MPT/cooldown)
GET  /api/assigned-schedules/{id}              (resolved matches with real team numbers, seed, assign_seed)
POST /api/assigned-schedules/{id}/activate     (promote to active — ownership not required)
DEL  /api/assigned-schedules/{id}              (requires matching created_by)
POST /api/assigned-schedules/{id}/duplicate    (anyone; creates new record owned by caller)

# Auth
GET  /auth/google/login                        redirect to Google consent
GET  /auth/google/callback                     exchange code → JWT → HTML popup closer
GET  /auth/apple/login                         redirect to Apple consent
POST /auth/apple/callback                      exchange code (form_post) → JWT → HTML popup closer
GET  /auth/me                                  {authenticated, sub, email, provider, uid}
GET  /auth/providers                           {google: bool, apple: bool}

GET  /api/health
```

---

## DATABASE SCHEMA

```
users
  id, sub (unique — "google:<id>" or "apple:<id>"), provider,
  email, name, created_at, updated_at

events
  id, key (unique e.g. "2025mnwi"), name, year, location,
  start_date, end_date, tba_synced, created_at, updated_at

teams
  id, number (unique), name, nickname, city, state, country,
  rookie_year, created_at, updated_at

event_teams
  id, event_id FK, team_id FK  (unique constraint)

abstract_schedules
  id, event_id (nullable FK), name,
  num_teams, matches_per_team, cooldown,
  seed (hex string, nullable),
  iterations_run, best_iteration, score,
  created_by (nullable — OAuth sub),
  matches (JSON — slot indices, not team numbers),
  surrogate_count (JSON), round_boundaries (JSON),
  created_at

assigned_schedules
  id, abstract_schedule_id FK, event_id FK, name, is_active,
  slot_map (JSON — {"1": 254, "2": 1114, ...}),
  day_config (JSON),
  assign_seed (hex string, nullable),
  created_by (nullable — OAuth sub),
  created_at
  ← Always INSERT new record. History preserved for revert.

match_rows
  id, assigned_schedule_id FK, match_num,
  red1/2/3, blue1/2/3 (team numbers),
  red1/2/3_surrogate, blue1/2/3_surrogate (bool)
```

**Access control:**
- All reads: public (no auth required)
- Delete: requires JWT with matching `created_by`
- Duplicate: open to all; creates new records owned by caller
- NULL `created_by`: anonymous schedule, cannot be deleted

---

## AUTH IMPLEMENTATION

**JWT:** `python-jose[cryptography]`, HS256, 30-day expiry.
Payload: `{sub, uid, provider, email, iat, exp}`.
Sent by frontend as `Authorization: Bearer <token>`.

**Google OAuth:**
- Redirect URI: `${BASE_URL}/auth/google/callback`
- Scopes: `openid email profile`
- On success: fetch userinfo → upsert User → issue JWT → HTML that postMessages token to opener

**Apple OAuth:**
- Service ID (web), `response_mode: form_post`
- Redirect URI: `${BASE_URL}/auth/apple/callback`
- Client secret: signed ES256 JWT from APPLE_PRIVATE_KEY (PEM)
- ID token verified against Apple's JWKS endpoint
- User name only available on first login (from form field)
- On success: verify ID token → upsert User → issue JWT → HTML that postMessages token to opener

**Frontend flow:**
1. User clicks Sign In → `openAuthModal()` calls `/auth/providers` to show available buttons
2. `signInWith(provider)` opens popup: `window.open('/auth/{provider}/login', ...)`
3. OAuth completes → server returns HTML with JS that `postMessage({token})` to opener
4. Frontend stores token in `localStorage('frc_token')`
5. Every `apiFetch` adds `Authorization: Bearer <token>` header
6. `/auth/me` verifies token and returns user info on page load

---

## ENV VARS

```bash
# Database
DATABASE_URL=postgresql+asyncpg://frc:frc@localhost:5432/frc_scheduler

# TBA (optional — get free key at thebluealliance.com/account)
TBA_API_KEY=

# CPU workers (0 = auto-detect)
CPU_WORKERS=0

# Auth
JWT_SECRET=              # openssl rand -hex 32
BASE_URL=                # public URL e.g. https://frc-scheduler.apps.my-cluster.com

# Google OAuth — https://console.cloud.google.com/apis/credentials
# Redirect URI: ${BASE_URL}/auth/google/callback
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=

# Apple Sign In — https://developer.apple.com/account/resources/identifiers
# Service ID (web), redirect URI: ${BASE_URL}/auth/apple/callback
APPLE_CLIENT_ID=
APPLE_TEAM_ID=
APPLE_KEY_ID=
APPLE_PRIVATE_KEY=       # PEM content with \n for newlines
```

---

## DESIGN SYSTEM

```css
--bg: #1a1d27    --surface: #22263a    --surface2: #2a2f46    --border: #3a4060
--accent: #7aa4f0    --accent2: #e07b50    --accent3: #5cb87a
--text: #dde2f0    --text-strong: #f2f5ff    --text-muted: #929cb6
--red-team: #e87878    --blue-team: #6fa8e8    --amber: #c8992a    --danger: #cc5555
```

Fonts: Barlow Condensed (700/900) + Barlow (300/400/500). Google Fonts.
Layout: 390px config panel + fluid results panel. Dark theme throughout.

---

## CONTAINER / OPENSHIFT

**Containerfile** (not Dockerfile):
- `chgrp -R 0 /app && chmod -R g=u /app` for OpenShift arbitrary UID
- `USER 1001`, unprivileged port 8000

**Namespace:** `frc-scheduler-server`

**openshift/ manifests:**
```
00-namespace.yaml        Project namespace
01-secrets.yaml          frc-db-secret, frc-app-secret (TBA key),
                         git-contents-token (GitHub PAT),
                         frc-auth-secret (JWT_SECRET, BASE_URL, GOOGLE_*, APPLE_*)
02-postgres.yaml         PVC (5Gi) + Deployment + ClusterIP Service
03-buildconfig.yaml      ImageStream (frc-scheduler-server-git) + BuildConfig
                         Source: github.com/croadfeldt/frc-scheduler-server main
                         Strategy: Docker, dockerfilePath: Containerfile
                         No webhooks — CronJob polls instead
04-deployment.yaml       App Deployment + ClusterIP Service
                         DATABASE_URL assembled from frc-db-secret at runtime
                         initContainer waits for Postgres TCP readiness
05-route.yaml            Edge-terminated HTTPS, HTTP→HTTPS redirect
07-build-trigger-sa.yaml ServiceAccount + Role + RoleBindings for CronJob
08-build-cronjob.yaml    git-commit-hash ConfigMap + CronJob (every 5 min)
                         git ls-remote → oc start-build on commit change
                         Image: quay.io/croadfel/origin-cli-git:4.18
```

---

## LICENSING

GNU GPL v3. All source files include:
```
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 FRC Match Scheduler Contributors
# NOTE: Substantially generated with Claude (Anthropic AI), reviewed by humans.
```
LICENSE file contains full GPL v3 text and AI-generation disclosure note.
