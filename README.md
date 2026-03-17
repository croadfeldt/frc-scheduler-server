# FRC Match Scheduler

A two-stage qualification match scheduler for FIRST Robotics Competition events.
Built as a containerised FastAPI + PostgreSQL server with a single-file HTML/CSS/JS
frontend. Deployable via Docker Compose or OpenShift.

---

## ⚠ AI-Assisted Development Notice

This project was substantially written with the assistance of
[Claude](https://claude.ai), an AI assistant developed by Anthropic.

- Architecture, requirements, and design decisions were directed by human contributors with domain knowledge of FRC competition operations.
- All AI-generated code was reviewed, tested, and modified by human contributors before inclusion.
- The scheduling algorithm logic — priorities, weights, surrogate rules, and post-generation sweeps — was designed and validated by humans, then implemented with AI assistance.
- Bugs and limitations may still exist. Please report issues via GitHub.

---

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE).

Copyright (C) 2025 FRC Match Scheduler Contributors.

---

## Quick Start (Docker Compose)

```bash
git clone https://github.com/croadfeldt/frc-scheduler-server.git
cd frc-scheduler-server
cp env.example .env
# Edit .env — set TBA_API_KEY and/or FRC_EVENTS_USERNAME/TOKEN, plus auth secrets
docker compose up --build
# App is at http://localhost:8080
```

## Quick Start (OpenShift)

```bash
oc new-project frc-scheduler-server
vi openshift/01-secrets.yaml   # set passwords, TBA key, auth credentials
oc apply -f openshift/01-secrets.yaml
oc apply -f openshift/02-postgres.yaml
oc rollout status deployment/frc-postgres -n frc-scheduler-server
oc apply -f openshift/03-buildconfig.yaml
oc start-build frc-scheduler-server-git --follow -n frc-scheduler-server
oc apply -f openshift/04-deployment.yaml
oc apply -f openshift/05-route.yaml
oc apply -f openshift/07-build-trigger-sa.yaml
oc apply -f openshift/08-build-cronjob.yaml
oc get route frc-scheduler-server -n frc-scheduler-server -o jsonpath='{.spec.host}'
```

See `openshift/README.md` for full details.

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
    ├─ /api/events/*    Event + team management + TBA/FRC Events import
    ├─ /api/tba/*       TBA proxy (events, search_index, import)
    ├─ /api/frc/*       FRC Events API proxy (events, import, status)
    ├─ /api/generate-abstract       Stage 1 SSE stream
    ├─ /api/abstract-schedules/*/assign  Stage 2 SSE stream
    └─ /api/assigned-schedules/*    History, activate, duplicate
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

### Seeded RNG

Both stages use deterministic seeded PRNGs:
- JS: mulberry32 (`makeRng(parseInt(seed, 16))`)
- Python: `random.Random(int(seed, 16))`

Same seed always produces identical output. Seeds are auto-generated, stored in the database, and encoded in the share URL so any schedule can be exactly reproduced.

---

## UI Features

### Auto flags

Three checkboxes live in one box below Match Cooldown:

| Flag | Default | Behaviour |
|------|---------|-----------|
| **Auto-regenerate on parameter change** | ✅ On | Regenerates Stage 1 whenever a parameter changes (1.5s debounce) |
| **Auto-apply PDF agenda to day config** | ✅ On | Automatically fills day start/end times and breaks from the FIRST agenda PDF when an event is loaded |
| **Auto-calculate max matches/team** | ☐ Off | Runs Calc Max Matches immediately after day config is applied; sets the matches/team field to the maximum that fits the schedule |

**Interaction order when an event is loaded:**
1. Roster is fetched → `numTeams` set
2. Agenda PDF is fetched and parsed (non-blocking, runs concurrently)
3. If auto-apply is on → day config populated from real qual time blocks
4. If auto-max is on → `calcMaxMatches()` recalculates matches/team → `generateSchedule()` fires (shows `⏳ Generating schedule…`)
5. If auto-max is off and auto-regenerate is on → `onParamChanged()` triggers debounced `generateSchedule()`
6. If no agenda PDF is available → `onParamChanged()` fires with roster team count alone

A `_agendaFetchPending` flag prevents `loadRoster` from triggering generation before the PDF's day config has been applied.

### Calc Max Matches

The **⟳ Calc Max Matches** button (or auto flag) simulates the exact scheduling loop — stepping through each day accounting for breaks, break buffer, and per-segment cycle times — then divides total 6-slot capacity by team count. The result is written to Matches per Team. Also fires automatically after `applyAgendaToSchedule()` when the auto-max flag is on.

### Agenda Fit panel

Integrated from [github.com/phil-lopreiato/frc-schedule-builder](https://github.com/phil-lopreiato/frc-schedule-builder). Appears at the top of the results column when an event is loaded.

**What it shows (6 stats):** Time Needed · Available · Buffer/Overflow · Capacity % · Matches/Hour · Max Cycle to Fit

**Fit status badge:** ✓ Comfortable (≤85%) / ⚠ Tight (≤100%) / ✗ Over Capacity (>100%)

**PDF source:**
```
https://info.firstinspires.org/hubfs/web/event/frc/{year}/{YEAR}_{EVENTCODE}_Agenda.pdf
```

Times in FIRST agenda PDFs are local event time — no timezone is listed or needed. All scheduler times are implicitly local to the event venue.

**Per-block timeline bars** update live as numTeams, mpt, or cycle time change.

**↓ Apply to Day Configuration** button sets day count, start/end times, and break rows from the parsed qual blocks. When `autoApplyAgenda` is on this fires automatically.

**PDF.js:** loaded lazily via injected `<script type="module">` (`loadPdfJs()`). CDN: `cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379`.

**Fallback:** when PDF is unavailable, a manual "total available minutes" input is shown instead.

**PDF.js** loaded lazily via injected `<script type="module">` (non-module script workaround). CDN: `cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379`.

### Day/Night mode

🌙/☀️ toggle in the header (`toggleTheme()`/`initTheme()` IIFE). Dark mode (default) uses Catppuccin Mocha palette. Light mode uses a matching high-contrast light palette. `[data-theme="light"]` on `<html>` overrides all CSS custom properties. Preference persisted in `localStorage` under `frc_theme`.

### TBA event dropdown

- Fetches all events for the selected year from `GET /api/tba/events/{year}`, sorted by `start_date` ascending
- No row cap — all events are rendered; filter-as-you-type limits visible rows
- Cross-year search: when fewer than 3 local results match, augments with TBA global search index results under "Other years"
- When fewer than 3 local results match a query (≥2 chars), the dropdown augments with results from TBA's global search index (`GET /api/tba/search_index`) under an "Other years" separator — enabling event discovery without knowing the year
- Source badge on each row: `TBA` (blue) or `FRC` (green)

### Show Slot Numbers toggle

After Stage 1 generates an abstract schedule a **👁 Show Slot Numbers** toggle appears. When on, slot indices (`S1`…`SN`) are shown instead of dashes and B2B is recalculated with those indices. Resets when Stage 1 regenerates or real teams are assigned.

### URL reproducibility

```
?n=51&mpt=11&cd=3&ct=8&days=2&seed=a1b2c3d4&aseed=cafebabe
  &d1=08:00-17:00&d1b=Lunch|12:00|13:00
  &d2=08:00-15:00&teams=254,1114,...
```

| Parameter | Description |
|-----------|-------------|
| `n` | Number of teams |
| `mpt` | Matches per team |
| `cd` | Cooldown |
| `ct` | Default cycle time (minutes) |
| `days` | Number of competition days |
| `seed` | Stage 1 hex seed |
| `aseed` | Stage 2 hex seed |
| `teams` | Team numbers in slot order |
| `d1`–`d5` | Per-day start–end (`HH:MM-HH:MM`) |
| `d1b`–`d5b` | Per-day breaks: `Name\|start\|end`, comma-separated |
| `cc` | Cycle time changes: `Day:AfterMatch:NewTime`, comma-separated |
| `bb` | Break buffer minutes |

URL restore priority: `?aid=` (assigned, fastest) → `?sid=` (abstract from DB) → `?seed=` (client-side regeneration).

---

## Removed: Timezone Selector

The timezone dropdown and all associated code (`buildTimezoneSelect`, `getTimezoneAbbr`, `window._frcTzAbbr`) were removed. FIRST agenda PDFs list times in local event time only — no timezone information is present. All scheduler times are implicitly local to the event venue.

---

## API Reference

### TBA Integration
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/tba/events/{year}?search=` | Events for year, sorted by start_date |
| GET | `/api/tba/search_index` | All TBA events across all years (global search) |
| POST | `/api/tba/import/{event_key}` | Import event + teams from TBA |

### FRC Events API
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/frc/configured` | Whether credentials are set |
| GET | `/api/frc/status` | Alias for `/api/frc/configured` |
| GET | `/api/frc/events/{year}?search=` | Events for year from FIRST API |
| POST | `/api/frc/import/{year}/{event_code}` | Import event + teams from FIRST API |

### Events
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/events` | List events |
| POST | `/api/events` | Create event |
| GET | `/api/events/{id}` | Event + team roster |
| DELETE | `/api/events/{id}` | Delete event |
| GET/POST | `/api/events/{id}/teams` | List / add teams |
| DELETE | `/api/events/{id}/teams/{num}` | Remove team |

### Scheduling
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/generate-abstract` | Stage 1 SSE stream |
| GET/DELETE | `/api/abstract-schedules/{id}` | Get / delete abstract schedule |
| POST | `/api/abstract-schedules/{id}/assign` | Stage 2 SSE stream |
| GET | `/api/events/{id}/assigned-schedules` | Version history |
| GET | `/api/assigned-schedules/{id}` | Resolved schedule + seeds |
| POST | `/api/assigned-schedules/{id}/activate` | Promote to active |
| DELETE | `/api/assigned-schedules/{id}` | Delete (requires ownership) |
| POST | `/api/assigned-schedules/{id}/duplicate` | Copy as new owned schedule |

### Auth & Health
| Method | Path | Description |
|--------|------|-------------|
| GET | `/auth/google/login` | Redirect to Google consent |
| GET | `/auth/google/callback` | Exchange code → JWT |
| GET | `/auth/apple/login` | Redirect to Apple consent |
| POST | `/auth/apple/callback` | Exchange code → JWT |
| GET | `/auth/me` | Current user from JWT |
| GET | `/auth/providers` | Which providers are configured |
| GET | `/api/health` | Status + CPU worker count |
| POST | `/api/log-commit` | Receives schedule completion payload; logs to container stdout |

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://frc:frc@localhost:5432/frc_scheduler` | Postgres DSN |
| `TBA_API_KEY` | (empty) | The Blue Alliance read key |
| `FRC_EVENTS_USERNAME` | (empty) | FIRST FRC Events API username |
| `FRC_EVENTS_TOKEN` | (empty) | FIRST FRC Events API token |
| `CPU_WORKERS` | `0` (auto) | Scheduler worker processes; 0 = `os.cpu_count()` |
| `WEB_WORKERS` | `1` | Uvicorn process count |
| `JWT_SECRET` | (required for auth) | `openssl rand -hex 32` |
| `BASE_URL` | `http://localhost:8080` | Public URL — used for OAuth redirect URIs |
| `GOOGLE_CLIENT_ID` | (empty) | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | (empty) | Google OAuth client secret |
| `APPLE_CLIENT_ID` | (empty) | Apple Service ID |
| `APPLE_TEAM_ID` | (empty) | Apple developer team ID |
| `APPLE_KEY_ID` | (empty) | Apple private key ID |
| `APPLE_PRIVATE_KEY` | (empty) | Apple ES256 PEM key (newlines as `\n`) |
| `PUID` | `1000` | Process UID (rootless container) |
| `PGID` | `1000` | Process GID |
| `APP_PORT` | `8080` | Uvicorn listen port |

## FRC Events API credentials

Register free at `frc-events.firstinspires.org/services/API`, then:

```bash
oc patch secret frc-app-secret -n frc-scheduler-server --type=merge \
  -p '{"stringData": {"FRC_EVENTS_USERNAME": "user", "FRC_EVENTS_TOKEN": "token"}}'
oc rollout restart deployment/frc-scheduler-server -n frc-scheduler-server
```

---

## DB Migrations (existing databases)

```bash
# Add day_config column to abstract_schedules
oc exec -n frc-scheduler-server $(oc get pod -l app=frc-postgres -o name) \
  -- psql -U frc -d frc_scheduler \
  -c "ALTER TABLE abstract_schedules ADD COLUMN IF NOT EXISTS day_config JSON;"

# Widen name/location columns from VARCHAR(256) to TEXT
psql -U frc -d frc_scheduler -f migrate_text_columns.sql
```

Fresh databases are unaffected — `create_all` builds the correct schema.

---

## Stage 2 Algorithm (Simulated Annealing)

`assign_teams()` in `scheduler.py`:
- Budget: `num_teams × 2` steps per iteration
- Temperature: `T0 = 500`, linear cooling
- Moves: 2-swap only
- Accept worse move when `exp(Δ/T)` and `Δ/T > -10`
- Score: `-(b2b×1000 + imbalance×500 + surrogates×200 + repeat_opp×15 + repeat_part×12)`
- Performance: ~90ms/iter per worker; 1000 iters × 8 workers ≈ 11s wall time

---

## Known Behaviour

**Break buffer:** Schedule a match if `breakStart - cursor ≥ breakBuffer`. The cycle time does not factor into this check — a match that clears the buffer runs even if it overlaps the break.

**B2B in abstract mode:** Always 0 — slot indices are structural placeholders. Shows actual structure when Show Slot Numbers is on.

**503 on rapid param changes:** Auto-generate debounce is 2500ms. Retry counter resets on each new `generateSchedule()` call.

**TBA team name length:** `teams.name`, `events.name`, `events.location` are `Text` (unlimited) to handle long TBA sponsor names.
