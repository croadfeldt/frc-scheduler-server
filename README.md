# FRC Match Scheduler

A two-stage qualification match scheduler for FIRST Robotics Competition events.
Built as a containerised FastAPI + PostgreSQL server with a single-file HTML/CSS/JS
frontend. Deployable via Docker Compose or OpenShift.

---

## ⚠ AI-Assisted Development Notice

This project was substantially written with the assistance of
[Claude](https://claude.ai), an AI assistant developed by Anthropic.

### What this means

- **Architecture, requirements, and design decisions** were directed by human
  contributors who have domain knowledge of FRC competition operations.
- **All AI-generated code was reviewed, tested, and modified** by human contributors
  before inclusion. No code was merged without human verification.
- **The scheduling algorithm logic** — priorities, weights, surrogate rules, and
  post-generation sweeps — was designed and validated by humans, then implemented
  with AI assistance.
- **Bugs and limitations** may still exist. AI assistance does not guarantee
  correctness. Please report issues via GitHub.

### For contributors

If you contribute to this project using AI assistance, follow these practices:

1. **Review everything the AI generates.** Do not commit AI output verbatim without
   reading and understanding it. You are responsible for code you submit.
2. **Test AI-generated logic independently.** Particularly for algorithmic code,
   write your own test cases rather than accepting the AI's self-validation.
3. **Disclose AI use in your PR description.** Note which parts were AI-assisted
   and what review you performed. Example: *"Generated initial implementation with
   Claude, verified surrogate logic by hand with 3 test cases."*
4. **Do not use AI to generate security-sensitive code without expert review.**
   Authentication flows, JWT handling, and OAuth integration require careful
   human scrutiny.
5. **Maintain the SPDX header.** All source files carry `SPDX-License-Identifier:
   GPL-3.0-or-later`. Do not remove it.

This project follows the emerging open-source community norm of transparent
disclosure for AI-assisted contributions. See also:
[OSAID](https://opensource.org/ai/open-source-ai-definition),
[GitHub's guidance on AI-generated code](https://docs.github.com/en/copilot/responsible-use-of-github-copilot-features).

---

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE).

Copyright (C) 2025 FRC Match Scheduler Contributors.

---

## Quick Start (Docker Compose)

```bash
# 1. Clone
git clone https://github.com/croadfeldt/frc-scheduler-server.git
cd frc-scheduler-server

# 2. Configure
cp env.example .env
# Edit .env — at minimum set TBA_API_KEY (optional) and auth secrets

# 3. Build and start
docker compose up --build

# App is at http://localhost:8080
```

---

## Quick Start (OpenShift)

```bash
# 1. Create project
oc new-project frc-scheduler-server

# 2. Edit secrets (set passwords, TBA key, auth credentials)
vi openshift/01-secrets.yaml

# 3. Apply in order
oc apply -f openshift/01-secrets.yaml
oc apply -f openshift/02-postgres.yaml
oc rollout status deployment/frc-postgres -n frc-scheduler-server
oc apply -f openshift/03-buildconfig.yaml
oc start-build frc-scheduler-server-git --follow -n frc-scheduler-server
oc apply -f openshift/04-deployment.yaml
oc apply -f openshift/05-route.yaml
oc apply -f openshift/07-build-trigger-sa.yaml
oc apply -f openshift/08-build-cronjob.yaml

# Get the public URL
oc get route frc-scheduler-server -n frc-scheduler-server -o jsonpath='{.spec.host}'
```

See `openshift/README.md` for full details.

---

## Container Builds

Two Containerfiles are provided — use the one appropriate for your build environment:

| File | Build target | Base image | Package manager |
|------|-------------|-----------|----------------|
| `Containerfile` | Docker, Podman, any OCI builder | `python:3.12-slim` (Docker Hub) | apt-get |
| `Containerfile.openshift` | **OpenShift BuildConfig only** | `quay.io/sclorg/python-312-c10s` | dnf |

**`Containerfile.openshift` is not intended for local Docker/Podman use.** It exists solely to avoid Docker Hub rate limits in OpenShift build pods and is referenced by `openshift/03-buildconfig.yaml` via `dockerfilePath: Containerfile.openshift`.

### Rootless container support

Both Containerfiles are rootless-compliant. The following environment variables control runtime identity and port binding:

| Variable | Default | Description |
|----------|---------|-------------|
| `PUID` | `1000` | User ID the process runs as. Set to `$(id -u)` to match your host user (linuxserver.io convention). |
| `PGID` | `1000` | Group ID the process runs as. Set to `$(id -g)` to match your host group. |
| `APP_PORT` | `8080` | Port uvicorn listens on. Ports ≥1024 require no special capabilities. |

All app files are `chgrp -R 0 && chmod -R g=u` so any UID in GID 0 can write without privilege escalation.

Standard Docker/Podman builds always use `Containerfile`:
```bash
docker compose up --build                        # uses Containerfile, port 8080

# Rootless Podman with host user mapping:
podman run --rm -e PUID=$(id -u) -e PGID=$(id -g) \
  -p 8080:8080 frc-scheduler-server
```

OpenShift builds are triggered via:
```bash
bash openshift/rebuild.sh        # full teardown + rebuild
# or after a git push, the CronJob auto-triggers within 5 minutes
```

---

## Architecture

### Two-stage scheduling

```
Stage 1 — Abstract Schedule
  Input:  numTeams, matchesPerTeam, cooldown, seed (hex)
  Output: slot-indexed match structure (no real team numbers)
          reproducible: same seed → identical structure

Stage 2 — Team Assignment
  Input:  abstract schedule + event roster + assign_seed (hex)
  Output: slot_map {slot: team_number}
          reproducible: same assign_seed → identical mapping
```

### System components

```
Browser (static/index.html)
    │  REST + SSE  +  Authorization: Bearer <jwt>
    ▼
FastAPI (app/main.py)              port 8080
    │
    ├─ /auth/*          OAuth2 (Google, Apple) → JWT
    ├─ /api/events/*    Event + team management + TBA import
    ├─ /api/generate-abstract   Stage 1 SSE stream
    ├─ /api/abstract-schedules/{id}/assign  Stage 2 SSE stream
    └─ /api/assigned-schedules/*  History, activate, duplicate
    │
    │  ProcessPoolExecutor (CPU_WORKERS processes)
    ├─► Worker 0  ──┐
    ├─► Worker 1  ──┤  app/scheduler.py  (pure Python, no I/O, seeded RNG)
    └─► Worker N  ──┘
    │
    │  asyncpg
    ▼
PostgreSQL                         port 5432 (internal)
```

### Why ProcessPoolExecutor?
Python's GIL prevents CPU parallelism with threads. `ProcessPoolExecutor` spawns
real OS processes. On a 16-core pod, 500 assignment iterations finish in ~1/16th
the single-core time.

### Seeded RNG
Both stages use deterministic seeded PRNGs:
- JS: mulberry32 (`makeRng(parseInt(seed, 16))`)
- Python: `random.Random(int(seed, 16))`

Same seed always produces identical output. Seeds are auto-generated, stored in
the database, and encoded in the share URL so any schedule can be exactly reproduced.

### UI controls

| Button | Where | Description |
|--------|-------|-------------|
| ⟳ Calc Max Matches | Config panel | Calculates max matches per team given current time/day/break/cycle parameters; writes result back to Matches per Team field |
| 👁 Show Slot Numbers | Config panel (after Stage 1) | Toggles abstract slot indices (S1–SN) on/off in the schedule; B2B recalculates with slot indices when visible |
| ✓ Commit Schedule as Active | Stage 2 panel | Marks the current assigned schedule as active in the DB; posts structured JSON completion log |
| ✗ Reset | Share bar | Clears all schedule state, resets stats and output to blank slate, clears URL; keeps parameters |

### URL reproducibility
After generating a schedule, the browser URL is updated:
```
?n=51&mpt=11&cd=3&ct=8&days=2&seed=a1b2c3d4&aseed=cafebabe
  &d1=08:00-17:00&d1b=Lunch|12:00|13:00
  &d2=08:00-15:00
  &teams=254,1114,...
```

| Parameter | Example | Description |
|-----------|---------|-------------|
| `n` | `51` | Number of teams |
| `mpt` | `11` | Matches per team (auto-filled by Calc Max Matches button) |
| `cd` | `3` | Cooldown |
| `ct` | `8` | Default cycle time (minutes). Pushed down to all day start-of-day cycle time rows on change. Secondary cycle time changes are not affected. |
| `days` | `2` | Number of competition days |
| `seed` | `a1b2c3d4` | Stage 1 hex seed |
| `aseed` | `cafebabe` | Stage 2 hex seed |
| `teams` | `254,1114,...` | Team numbers in slot order |
| `d1`–`d5` | `09:00-18:00` | Per-day start–end (`HH:MM-HH:MM`). Day 1 defaults to 09:00 start/18:00 end; Day 2+ default to 08:45 start/18:00 end; last day always defaults to 12:00 end. |
| `d1b`–`d5b` | `Lunch\|12:00\|13:00,...` | Per-day breaks: `Name\|start\|end`, comma-separated |
| `cc` | `1:45:7.5,2:90:6` | Cycle time changes: `Day:AfterMatch:NewTime`, comma-separated |
| `bb` | `5` | Break buffer minutes (minimum time before break/end-of-day to fit one more match) |

Opening this URL auto-reproduces the full schedule including day/time configuration.
Without `teams`, the abstract structure renders with blank slots.

### UI controls

| Button | Location | Description |
|--------|----------|-------------|
| ⚡ Stage 1: Generate Structure | Config panel | Generates abstract slot schedule |
| ▶ Assign Teams to Schedule | Config panel | Runs Stage 2 team assignment |
| ✓ Commit Schedule as Active | Config panel | Marks assigned schedule as active, logs to server |
| ↻ Calc Max Matches | Config panel | Calculates maximum matches/team from schedule parameters and fills the field |
| + Add Day | Daily Schedule section | Appends a new competition day (max 5). The previously-last day is updated to 18:00 end; the new last day defaults to 12:00 (noon). |
| ✕ (day header) | Each day row | Removes that day. The new last day is set to 12:00 end; any breaks or cycle changes after that time are pruned. Day 1 cannot be removed. |
| Default Cycle Time | Parameters | Pushes the value to all day start-of-day cycle rows (one-way). A blue notice confirms the update. Secondary cycle time changes per day are unaffected. |
| Number of Days | Parameters | Bidirectionally synced with day rows: changing the field adds/removes day rows; using Add Day or Remove updates the field. |
| ✕ (day header) | Each day row | Removes that day from the schedule (Day 1 cannot be removed) |
| Break Buffer (min) | Config panel | Minimum minutes remaining before a break or end-of-day to still schedule a match. Default 5. Applied in both schedule generation and Calc Max Matches. |
| 👁 Show / Hide Slot Numbers | Config panel | Toggle showing abstract slot indices (S1…N) vs blank dashes; B2B recalculates accordingly |
| ✖ Reset | Config panel header & share bar | Two-stage reset: clears results (keeps params), optionally resets params to defaults too. Clears URL. |
| Share | Share bar | Copies full reproducible URL to clipboard |
| TBA event dropdown | Event bar (code input) | Automatically fetches TBA events for the selected year. Typing filters the list by key or name. Clicking an entry fills the code input and loads the event. Results are cached per year. |
| ⬇ CSV | Results panel header | Downloads `frc_schedule.csv` — Match, Day, Time, Red 1-3, Blue 1-3, Surrogates |
| ⬇ JSON | Results panel header | Downloads `frc_schedule.json` — full structured schedule with parameters, day config, break rows, cycle-change rows, and per-match time in minutes for import into other tools |
| ✓ Committed | Share bar | After commit, shows confirmation state |

---

## UI Features

### Calc Max Matches
The **⟳ Calc Max Matches** button calculates the maximum equal matches each team
can receive given the current schedule parameters (teams, cycle time, days,
breaks, cycle changes). It simulates the exact scheduling loop — stepping through
each day accounting for breaks and per-segment cycle times — then divides total
6-slot capacity by team count. The result is written back to the Matches per Team
field. A status message reports total matches, slots available, and any surrogates
needed.

### Show Slot Numbers toggle
After Stage 1 generates an abstract schedule, a **👁 Show Slot Numbers** toggle
appears. This is a UI-only view aid:

| State | Team cells | B2B stat | Notes |
|-------|-----------|----------|-------|
| Off (default) | `—` | Always 0 | Slot indices have no team identity |
| On | `S1`…`SN` italic | Recalculated with slot indices | Makes match structure visible |

The toggle resets automatically when Stage 1 regenerates or real teams are
assigned. It is not encoded in the share URL (transient display state only).

### B2B stat behaviour
- **Abstract mode** (Stage 1 complete, no real teams): always 0 — slot indices
  are structural placeholders, not real teams, so back-to-back analysis is
  meaningless.
- **Fake teams visible** (Show Slot Numbers on): B2B recalculated using slot
  indices — shows the structural back-to-backs inherent in the schedule layout.
- **Real teams assigned** (Stage 2 complete): B2B calculated with real team
  numbers as normal.

---

## API Reference

### Events
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | /api/events | — | List events |
| POST | /api/events | — | Create event |
| GET | /api/events/{id} | — | Event + team roster |
| DELETE | /api/events/{id} | — | Delete event |
| GET | /api/events/{id}/teams | — | List teams |
| POST | /api/events/{id}/teams | — | Add team |
| DELETE | /api/events/{id}/teams/{num} | — | Remove team |

### TBA Integration
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | /api/tba/events/{year}?search= | — | Search TBA events |
| POST | /api/tba/import/{event_key} | — | Import event + teams from TBA |

### Stage 1 — Abstract Schedule
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /api/generate-abstract | optional | Generate slot structure (SSE stream) |
| GET | /api/abstract-schedules | — | List abstract schedules |
| GET | /api/abstract-schedules/{id} | — | Full slot-based schedule + seed |
| DELETE | /api/abstract-schedules/{id} | — | Delete |

### Stage 2 — Team Assignment
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /api/abstract-schedules/{id}/assign | optional | Assign teams (SSE stream) |
| GET | /api/events/{id}/assigned-schedules | — | Version history |
| GET | /api/assigned-schedules/{id} | — | Resolved schedule + seeds |
| POST | /api/assigned-schedules/{id}/activate | — | Promote to active |
| DELETE | /api/assigned-schedules/{id} | owned | Delete (requires ownership) |
| POST | /api/assigned-schedules/{id}/duplicate | optional | Copy as new owned schedule |

### Authentication
| Method | Path | Description |
|--------|------|-------------|
| GET | /auth/google/login | Redirect to Google consent |
| GET | /auth/google/callback | Exchange code → issue JWT |
| GET | /auth/apple/login | Redirect to Apple consent |
| POST | /auth/apple/callback | Exchange code (form_post) → issue JWT |
| GET | /auth/me | Current user info from JWT |
| GET | /auth/providers | Which providers are configured |

### Health & Logging
| Method | Path | Description |
|--------|------|-------------|
| GET | /api/health | Status + CPU worker count |
| POST | /api/log-commit | Receives structured schedule completion payload from the browser; logs at INFO (summary) and DEBUG (full JSON) to container stdout |

### Commit log payload (`POST /api/log-commit`)
Posted automatically by the browser when a schedule is committed as active.
Appears in container logs as `SCHEDULE_COMMITTED` (summary) and `SCHEDULE_COMMITTED_DETAIL` (full JSON at DEBUG level).

```json
{
  "event": "schedule_committed",
  "timestamp": "2026-03-16T12:00:00.000Z",
  "url": "https://host/?n=51&mpt=11&cd=3&ct=8&days=2&seed=a1b2c3d4&aseed=cafebabe&...",
  "event_info":  { "id": 3, "key": "2026mnwi", "name": "MN North Star", "year": 2026 },
  "schedule":    { "assigned_schedule_id": 7, "abstract_schedule_id": 12, "name": "...",
                   "created_at": "...", "created_by": "user@example.com", "is_active": true },
  "parameters":  { "num_teams": 51, "matches_per_team": 11, "cooldown": 3,
                   "cycle_time_min": 8, "num_days": 2,
                   "cycle_changes": [{"day":2,"after":45,"time":7.5}],
                   "seed": "a1b2c3d4", "assign_seed": "cafebabe" },
  "day_config":  { "cycleTime": 8, "numDays": 2, "days": [...], "cycleChanges": [...] },
  "teams":       [254, 1114, 148, 27, 67, 111],
  "match_count": 93,
  "surrogate_count": { "1": 1, "3": 2 },
  "stats":       { "total_matches": 93, "back_to_backs": 2, "surrogates": 6 }
}
```

**Auth notes:**
- All reads are public — no token required.
- `Authorization: Bearer <jwt>` enables ownership. Schedules gain a `created_by`
  field (OAuth subject). Deletion requires matching `created_by`.
- Anonymous schedules (`created_by = NULL`) are publicly readable but not deletable.
- Anyone can duplicate a schedule; the copy is owned by the caller.

Interactive docs: http://localhost:8080/docs (Swagger UI)

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://frc:frc@localhost:5432/frc_scheduler` | Postgres DSN |
| `TBA_API_KEY` | (empty) | The Blue Alliance read key — [get one free](https://www.thebluealliance.com/account) |
| `CPU_WORKERS` | `0` (auto) | Scheduler worker processes; 0 = `os.cpu_count()` |
| `WEB_WORKERS` | `1` | Uvicorn process count. 1 = single user, 2–4 = multi-user. Each worker has its own ProcessPoolExecutor. |
| `JWT_SECRET` | (required for auth) | Long random string — `openssl rand -hex 32` |
| `BASE_URL` | `http://localhost:8080` | Public URL — used for OAuth redirect URIs |
| `GOOGLE_CLIENT_ID` | (empty) | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | (empty) | Google OAuth client secret |
| `APPLE_CLIENT_ID` | (empty) | Apple Service ID (web) |
| `APPLE_TEAM_ID` | (empty) | Apple developer team ID |
| `APPLE_KEY_ID` | (empty) | Apple private key ID |
| `APPLE_PRIVATE_KEY` | (empty) | Apple ES256 PEM key (newlines as `\n`) |

Auth is **optional** — the scheduler works fully without OAuth configured.
Users can generate, view, and share schedules anonymously.

---

## Authentication (Optional)

Authentication is **entirely optional** — all schedule generation, viewing, and sharing works without signing in. Auth adds ownership tracking so you can delete your own schedules, and the `created_by` field in the commit log.

The "no auth providers configured" message means the relevant environment variables are empty. You must configure at least one OAuth provider to enable sign-in.

### Setting Up Google OAuth (recommended — easier)

1. Go to [Google Cloud Console → APIs → Credentials](https://console.cloud.google.com/apis/credentials)
2. Create **OAuth 2.0 Client ID** → Web application
3. Add authorized redirect URI:
   ```
   https://your-host/auth/google/callback
   ```
4. Copy the Client ID and Client Secret
5. Set these in your `.env` or `openshift/01-secrets.yaml`:
   ```yaml
   GOOGLE_CLIENT_ID:     "123456789-abc.apps.googleusercontent.com"
   GOOGLE_CLIENT_SECRET: "GOCSPX-..."
   JWT_SECRET:           "<run: openssl rand -hex 32>"
   BASE_URL:             "https://your-host"
   ```
6. For OpenShift: `oc apply -f openshift/01-secrets.yaml` then restart the pod, or re-run `bash openshift/rebuild.sh`

### Setting Up Apple OAuth

Requires an active Apple Developer account ($99/year).

1. Go to [Apple Developer → Identifiers](https://developer.apple.com/account/resources/identifiers/serviceId/add)
2. Register a **Services ID** (not an App ID)
3. Enable **Sign In with Apple**, add redirect URI: `https://your-host/auth/apple/callback`
4. Go to [Keys](https://developer.apple.com/account/resources/authkeys/add), create a key with Sign In with Apple enabled, download the `.p8` file
5. Set in your environment:
   ```yaml
   APPLE_CLIENT_ID:    "com.your.services-id"
   APPLE_TEAM_ID:      "XXXXXXXXXX"
   APPLE_KEY_ID:       "YYYYYYYYYY"
   APPLE_PRIVATE_KEY:  "-----BEGIN PRIVATE KEY-----\nMIG...\n-----END PRIVATE KEY-----"
   ```
   (replace actual newlines in the PEM with literal `\n`)

### JWT Secret

`JWT_SECRET` must be set for any auth to work — it signs the tokens issued after OAuth completes:
```bash
openssl rand -hex 32
```

Without `JWT_SECRET`, the server starts but `/auth/google/login` and `/auth/apple/login` will fail with a 500 error.

---

## Share bar & schedule IDs

After Stage 1 completes, a bar appears below the header with clickable identifiers:

```
Schedule ID: #16  seed: 1f213205  ·  Assignment ID: #7  assign seed: cafebabe
```

| Element | Purpose | Click action |
|---|---|---|
| **Schedule ID `#16`** | `abstract_schedule_id` — DB primary key for the slot-based schedule | Copies `#16`; tooltip shows `?sid=16` URL syntax |
| **seed `1f213205`** | 8-hex seed that reproduces the schedule from scratch (no server needed) | Copies seed |
| **Assignment ID `#7`** | `assigned_schedule_id` — DB primary key for the team assignment | Copies `#7`; tooltip shows `?aid=7` URL syntax |
| **assign seed** | Seed used for team assignment iteration | Copies assign seed |

### URL restore priority

When loading a URL, the app resolves the schedule in this order:

1. `?aid=7` — fetches the assigned schedule + its abstract from DB, renders immediately with real teams. No regeneration needed.
2. `?sid=16` — fetches the abstract schedule from DB, restores its stored day/timing config to the UI, and renders the schedule. Fully self-contained — no URL timing params needed. Shows "Load saved assignment" banner if an assignment exists.
3. `?seed=…` — falls back to client-side regeneration from the seed (original behaviour).

The **Share** button copies the full URL including `sid` and `aid` so any recipient can load the exact same schedule instantly.

## Known behaviour & recent fixes

### DB migration required — `abstract_schedules.day_config`

The `abstract_schedules` table needs a new `day_config` column. On any **existing** database run:

```bash
oc exec -n frc-scheduler-server $(oc get pod -l app=frc-postgres -o name) \
  -- psql -U frc -d frc_scheduler \
  -c "ALTER TABLE abstract_schedules ADD COLUMN IF NOT EXISTS day_config JSON;"
```

Or use the included `migrate_abstract_day_config.sql`. Fresh databases are unaffected (`create_all` builds the correct schema).

### TBA import — team name length
TBA sponsor names can exceed 256 characters (e.g. WildStang team 111). The `teams.name`,
`events.name`, and `events.location` columns use SQLAlchemy `Text` (unlimited) rather than
`VARCHAR(256)` to avoid `StringDataRightTruncationError` on import.

### matches_per_team API cap
The `AbstractGenerateRequest` model accepts `matches_per_team` up to 50.
The UI input is also capped at 50. `calcMaxMatches()` can legitimately return values above 20
for small team counts with long schedules.

### TBA client — no singleton
`tba.py` creates a fresh `httpx.AsyncClient` per request (using `async with`). The previous
module-level singleton was created outside any running event loop, causing silent hangs and
502 errors from the OCP router. Per-request clients have negligible overhead for TBA calls.

### Break buffer definition

`breakBuffer` (URL param `bb`, default 5 min) controls when to stop scheduling matches before a break.

**Rule:** Schedule a match if its **start time** is at least `breakBuffer` minutes before the break:
```
breakStart - cursor >= breakBuffer
```
Only defer (flush break early) if `breakStart - cursor < breakBuffer`.

- `breakBuffer = 5`, lunch at 12:00: a match starting at 11:55 (exactly 5 min gap) — **scheduled** ✓ (may run 3 min past noon if cycle=8)
- A match starting at 11:56 (only 4 min gap) — **deferred until after the break** ✓

The cycle time does **not** factor into this check. A match that clears the buffer is committed to run even if its cycle time overlaps the break start. The interrupt check (which would otherwise cancel mid-match breaks) is suppressed for any match that already passed the buffer test.

### 503 under rapid parameter changes
The auto-generate debounce is 2500ms. The Stage 1 retry counter is reset to 0 at the start
of every new `generateSchedule()` call so accumulated retries from previous edits don't
consume the retry budget for the next attempt.

## Development


```bash
# Install dependencies
pip install -r requirements.txt

# Run with local Postgres
DATABASE_URL=postgresql+asyncpg://frc:frc@localhost:5432/frc_scheduler \
  uvicorn app.main:app --reload

# Test scheduler reproducibility
python3 -c "
from app.scheduler import generate_matches
r1 = generate_matches(30, 6, 3, seed=0xdeadbeef)
r2 = generate_matches(30, 6, 3, seed=0xdeadbeef)
print('Reproducible:', r1.matches == r2.matches)
print('Score:', r1.score)
"

# Verify surrogate rules
python3 -c "
from app.scheduler import generate_matches
r = generate_matches(51, 11, 3, seed=42)
last = r.matches[-1]
assert not any(last.red_surrogate), 'R1 violated: surrogate in last match'
assert not any(last.blue_surrogate), 'R1 violated: surrogate in last match'
print('Post-gen sweep rules OK')
"
```

---

## Scaling

| Concern | Approach |
|---------|----------|
| More iterations | Increase Assignment Iterations in UI (default 1000) |
| More cores | Set `CPU_WORKERS` to physical core count |
| Memory | Each worker ≈ 50 MB; 16 workers ≈ 800 MB |
| Multiple replicas | Each replica has its own worker pool; note — more small pods beats one big pod for scheduling throughput only if each pod has enough cores |
| Concurrent users | Set `WEB_WORKERS=2–4`. A generation semaphore (CPU_WORKERS÷2, min 2) prevents pool saturation. The client AbortController cancels in-flight requests on param changes. |
| DB migrations | `create_all` is used (dev-friendly). Add Alembic for production schema migrations. |
