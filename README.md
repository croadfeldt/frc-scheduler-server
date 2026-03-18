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

### OpenShift scaling (recommended)

| Setting | Value | Rationale |
|---------|-------|-----------|
| `replicas` | `2` | Each pod on a separate node; 4 users per pod at good performance |
| `cpu request` | `4` | Guarantees headroom on 16-CPU nodes |
| `cpu limit` | `12` | Leaves 4 CPUs for OS/other pods per node |
| `CPU_WORKERS` | `12` | SA workers per pod; `_gen_concurrency = CPU_WORKERS // 3 = 4` |
| `WEB_WORKERS` | `1` | One uvicorn process owns the full pool — no contention |
| `maxUnavailable` | `0` | Zero-downtime rolling deploys |
| `PodDisruptionBudget` | `minAvailable: 1` | Node drain never takes both pods offline |

**Concurrent user capacity:** 2 pods × 4 jobs/pod = 8 simultaneous assignment jobs. Each job gets 3 SA workers → ~10s for 1000 iterations at full load.

### Seeded RNG

Both stages use deterministic seeded PRNGs:
- JS: mulberry32 (`makeRng(parseInt(seed, 16))`)
- Python: `random.Random(int(seed, 16))`

Same seed always produces identical output. Seeds are auto-generated, stored in the database, and encoded in the share URL so any schedule can be exactly reproduced.

---

## UI Features

### Auto flags

Four checkboxes in the "Auto Actions" box below Match Cooldown:

| Flag | ID | Default | Behaviour |
|------|----|---------|-----------| 
| Regenerate on change | `autoPopulate` | ✅ On | Debounced Stage 1 regeneration on any param change (2.5s) |
| Apply PDF agenda to day config | `autoApplyAgenda` | ✅ On | Fills day times and breaks from FIRST agenda PDF on event load |
| Calculate max matches/team | `autoMaxCycles` | ✅ On | `calcMaxMatches()` after day config applied; writes matchesPerTeam |
| Assign teams after generation | `autoAssign` | ☐ Off | Triggers Stage 2 automatically after Stage 1 completes |

**Precedence order on event load** (each step gated by its own flag):

```
1. PDF fetch → applyAgendaToSchedule()   [autoApplyAgenda]
2. → calcMaxMatches()                    [autoMaxCycles] → writes matchesPerTeam
3. → generateSchedule()                  [autoPopulate]  → Stage 1
4. → assignTeams()                       [autoAssign]    → Stage 2
```

**Auto flags are persisted** in the URL (`?autoPopulate=0` etc.) and in `day_config` JSON in the DB. Flags defaulting on are omitted from the URL when on; `autoAssign` (default off) is omitted when off.

**`onCycleTimeChanged()`** — cycle-time inputs fire a 1.2s debounced handler that calls `calcMaxMatches()` when `autoMaxCycles` is on, then `generateSchedule()`. Debounced to avoid firing mid-keystroke.

**`_agendaFetchPending` flag** — set before the PDF fetch, cleared in `.finally()`. Prevents `onParamChanged()` from triggering a premature generate while the PDF chain is running.

### Agenda Fit panel

Appears at the top of the results column when an event is loaded with a valid key.

**Stats row:** Time Needed · Available · Buffer/Overflow · Capacity % · Matches/Hour · Max Cycle to Fit

**Status badge:** ✓ Comfortable (≤85%) / ⚠ Tight (≤100%) / ✗ Over Capacity (>100%)

**Section bars** — one bar per contiguous match session (split at breaks >5 min):
- Bar always spans 100% of container width
- Fill = actual committed match time / available slot time (with break buffer applied)
- Short breaks (≤5 min) shown as tick marks inside the bar
- Fill color = day color from `_DAY_COLORS` palette; switches to amber if >95% full or over
- Bar track uses the day color at ~8% opacity
- Day label is clickable — scrolls schedule output to the first match in that session
- Header shows: Day label · time range · avg cycle time badge (with progression tooltip) · available minutes

**Day color palette** (`_DAY_COLORS` — permanent 7-color set, cycles for >7 days):

| Day | Hex | Color |
|-----|-----|-------|
| 1 | `#5b9bd5` | Steel blue |
| 2 | `#4aab8a` | Teal green |
| 3 | `#8b74c8` | Violet |
| 4 | `#c48b3a` | Amber gold |
| 5 | `#c05a6e` | Rose crimson |
| 6 | `#5a7fa8` | Slate blue |
| 7 | `#6a9455` | Moss green |

**PDF parsing** — `normalizePDFText()` + `parseQualBlocks()` handle multiple FIRST district format variants:
- Standard / Peachtree / Chesapeake (optional footnote markers, `~` on end time)
- Ontario (two-column, no dash separator)
- North Carolina (start-time-only Begin/Continue)
- Wisconsin (`fi` ligature split)
- Colorado (numeric date `Friday, 4/10/26`)
- Short gaps (≤30 min) between consecutive blocks are merged

**Fallback:** when PDF is unavailable, a manual "total available minutes" input is shown.

**Recalculates automatically** on changes to: numTeams, mpt, cycleTime, breakBuffer, any day start/end/break time, any cycle change row.

### Daily Schedule section

Each day row uses the day color from `_DAY_COLORS` as a subtle background tint (8% opacity) with a matching border (31% opacity). The Day label matches the agenda fit color and is clickable to scroll the schedule output to that day.

### Print Schedule

A **🖨 Print** button appears in the Schedule Output download bar alongside CSV and JSON. Clicking it opens a print options dialog then generates a clean printable page in a new browser tab and triggers `window.print()` automatically.

**Print options (with defaults):**

| Option | Default | Notes |
|--------|---------|-------|
| Cycle times in day header | ✅ On | Shows cycle time progression in each day title |
| Cycle time changes | ✅ On | Shows inline cycle-change rows |
| Breaks | ✅ On | Shows lunch and other break rows |
| Day break markers | ✅ On | Shows early-end day break markers |
| Team numbers | ✅ On | Disabled/greyed if Stage 2 not run; shows `—` when off |
| Round dividers | ☐ Off | Round boundary rows |
| Page break between days | ☐ Off | Each day starts on a new page |

**Key behaviours:**
- When no Stage 2 assignment exists, team numbers option is greyed out and all positions print as `—`
- Surrogate badge only shows when team numbers are visible (position may change on reassignment)
- If a team filter is active in the schedule view, only matches containing the filtered teams are printed
- Pop-up blocked warning shown if browser prevents the new tab

### Number of Days sync

The **Number of Days** field and the daily schedule rows are always kept in sync:
- Typing or changing the field immediately adds or removes day rows to match
- Clicking **+ Add Day** increments the field and adds a row
- Clicking **✕** on a day row removes it and decrements the field

### Day Break (Early End)

Each day row has a `+ Add Day Break (stop scheduling)` button. Enter a match count — scheduling stops after that many matches on that day without changing the configured start/end times.

Use case: a field issue, awards ceremony, or other non-time event ends match play early, but you still want to display the full agenda time slot in the fit bars.

Only one day break per day. Persisted to URL (`d1e=44`), `day_config` JSON, and restored on schedule reload.

### Calc Max Matches

Simulates the exact scheduling loop — stepping through each day accounting for breaks, break buffer, and per-segment cycle times — then divides total 6-slot capacity by team count. Includes a 2,000-iteration safety cap and a `ct < 0.5` guard against invalid cycle time values causing infinite loops.

### Ad-hoc Schedule

The **✎ Ad-hoc** button in the event bar creates (or loads) a persistent `adhoc` event in the database — no TBA or FRC Events import required. Once activated it behaves exactly like any named event:

- Teams are added/removed via the Teams modal and persist across sessions
- Schedule generation, Stage 2 assignment, and schedule history all work normally
- Each schedule gets a unique `?aid=N` / `?sid=N` URL for individual recall
- The Schedules modal shows full version history under the ad-hoc event
- The button hides once any event is loaded and reappears on Reset

### Team roster actions

The Teams modal header row has two action buttons:

- **⬇ Export** — downloads the current roster as `teams-event-{id}.csv` with `number,name` columns. Names with commas are properly quoted.
- **✕ Clear** — removes all teams from the event after a `confirm()` prompt. Resets `numTeams` to 0 and triggers `onParamChanged`.

### Team roster import

The Teams modal has an **Import** section that accepts team lists in any format — auto-detected, no configuration needed:

| Format | Example |
|--------|---------|
| JSON array | `[254, 1114, 2056]` |
| CSV | `254, 1114, 2056` |
| One per line | `254
1114
2056` |
| YAML list | `- 254
- 1114` |
| Plain text | any whitespace/comma separated numbers |

Input methods: **Paste** into the textarea · **📁 File** button (`.csv .json .yaml .yml .txt`) · **Drag and drop** a file onto the textarea.

Non-numbers are silently skipped. Duplicates ignored. After import, TBA is queried non-blockingly for each team's name/nickname — enriched in-place in the roster and persisted to the DB. Failures (TBA unavailable, unknown team) are silently ignored.

### TBA event dropdown

- Year-specific fetch on demand: `GET /api/tba/events/{year}`
- Current year + next year fetched on first focus of the event code input (not eager); cached in `localStorage` for 6 hours (key: `tba_idx_{year}`)
- **Prior years:** not pre-loaded. Changing the year field fetches that year on demand. A warning appears in the status area when a prior year is entered. The dropdown shows a hint linking to the year field.
- Cross-year fallback: when <3 local results match a query, augments from the pre-fetched index under "Other years"
- Source badge per row: `TBA` (blue) or `FRC` (green)

### Schedule output

- Day headers show: day number (clickable, scrolls to that day) · match count · cycle time progression (e.g. `9→8 min`)
- Cycle times in day headers are read from actual scheduled match durations (`endMin - startMin`), not from global cycle time — correctly reflects per-day start times
- Match rows have `id="schedule-match-N"` for direct scroll targeting
- `scrollToMatch(N)` and `scrollToDay(N)` both use `getBoundingClientRect()` for reliable cross-browser positioning

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
| `autoPopulate` | Omitted=on; `=0`=off |
| `autoApplyAgenda` | Omitted=on; `=0`=off |
| `autoMaxCycles` | Omitted=on; `=0`=off |
| `autoAssign` | Omitted=off; `=1`=on |
| `sid` | Restore abstract schedule from DB |
| `aid` | Restore assigned schedule from DB |
| `event` | Event key to auto-load |

URL restore priority: `?aid=` → `?sid=` → `?seed=`

---

## Stage 2 Algorithm (Simulated Annealing)

`assign_teams()` in `scheduler.py` — incremental scoring:

- **Full rescore** (`build_score_state`) called once per iteration start
- **Incremental delta** (`delta_swap`) for each swap attempt — only rescores the ~10-20 affected matches rather than all 88
- State rebuild only on accepted moves (majority of moves are rejected → near-zero per-step cost)
- Budget: `num_teams` steps per iteration (reduced from `×2` — incremental scoring makes each step cheap)
- `T0 = 500`, linear cooling; 2-swap moves
- Score: `-(b2b×1000 + imbalance×500 + surrogates×200 + repeat_opp×15 + repeat_part×12)`
- Performance: ~30ms/iter (vs 80ms before incremental scoring)
- `_gen_concurrency = max(2, CPU_WORKERS // 3)` — limits simultaneous jobs; each job gets ~3 workers minimum

---

## API Reference

### TBA Integration
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/tba/events/{year}?search=` | Events for year, sorted by start_date |
| GET | `/api/tba/search_index` | All TBA events across all years (server-cached 6h) |
| GET | `/api/tba/team/{number}` | Single team lookup by number (for roster enrichment) |
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
| GET | `/api/events/adhoc` | Get or create the persistent ad-hoc event (upsert by fixed key) |
| GET | `/api/events/{id}` | Event + team roster |
| DELETE | `/api/events/{id}` | Delete event |
| GET/POST | `/api/events/{id}/teams` | List / add teams |
| PATCH | `/api/events/{id}/teams/{num}` | Update team name/nickname (TBA enrichment) |
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
| GET | `/api/health` | `{"status":"ok","cpu_workers":N}` |
| POST | `/api/log-commit` | Logs schedule completion payload to container stdout |

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | *(assembled from secrets)* | Postgres DSN |
| `TBA_API_KEY` | (empty) | The Blue Alliance read key |
| `FRC_EVENTS_USERNAME` | (empty) | FIRST FRC Events API username |
| `FRC_EVENTS_TOKEN` | (empty) | FIRST FRC Events API token |
| `CPU_WORKERS` | `12` (OpenShift) | SA worker processes; `0` = `os.cpu_count()` |
| `WEB_WORKERS` | `1` | Uvicorn process count |
| `JWT_SECRET` | (required for auth) | `openssl rand -hex 32` |
| `BASE_URL` | `http://localhost:8080` | Public URL — used for OAuth redirect URIs |
| `GOOGLE_CLIENT_ID/SECRET` | (empty) | Google OAuth |
| `APPLE_*` | (empty) | Apple OAuth |
| `PUID` / `PGID` | `1000` | Process UID/GID (rootless container) |
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

## Known Behaviour

**Break buffer:** Schedule a match if `breakStart - cursor ≥ breakBuffer`. The cycle time does not factor into this check — a match that clears the buffer runs even if it overlaps the break.

**calcMaxMatches safety:** The simulation loop has a 2,000-iteration cap and rejects cycle times < 0.5 min to prevent browser hangs from invalid field values.

**B2B in abstract mode:** Always 0 — slot indices are structural placeholders. Shows actual structure when Show Slot Numbers is on.

**TBA search index:** Server-cached for 6 hours (`app.state`). Client caches current+next year in `localStorage` for 6 hours. Prior years fetched on demand by changing the year field.

**503 on rapid param changes:** Auto-generate debounce is 2500ms. `onCycleTimeChanged` has a separate 1200ms debounce. `_agendaFetchPending` blocks `onParamChanged` during the PDF chain.

**Single-day end time:** `applyDayEndTimes()` only applies noon (`12:00`) to the last day of a multi-day event. When there is exactly one day, it uses `18:00` — noon as a default makes no sense for a full-day event.

**Cycle time sync prompt:** When the global Cycle Time field is changed and any day's start-of-day row has a different value, a `confirm()` asks whether to apply the new value to all days. If all days already match the new value, it silently updates.

**Ad-hoc event key:** Fixed as `adhoc` in the DB. `GET /api/events/adhoc` upserts on first call — no migration needed for existing databases.

**Team TBA enrichment:** `PATCH /api/events/{id}/teams/{num}` updates `nickname`/`name` on the shared `Team` record — visible across all events that reference the same team number.

**Page load API calls:** On first load only `GET /api/events` (DB) and `GET /auth/me` (JWT check) fire immediately. TBA dropdown fetch is deferred to first focus on the event input. Health check deferred 2s. TBA search index deferred 5s with `localStorage` caching. `apiFetch()` logs `[api] METHOD /path Nms` to the browser console for timing diagnosis.
