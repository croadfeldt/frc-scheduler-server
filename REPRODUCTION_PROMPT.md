# FRC Match Scheduler — Reproduction Prompt

This document contains the complete technical detail required to reproduce this project from scratch. It documents every non-obvious design decision, algorithm, and implementation detail.

---

## Project Overview

A two-stage FRC qualification match scheduler. FastAPI + PostgreSQL backend, single-file HTML/CSS/JS frontend. Deployable via Docker Compose or OpenShift.

---

## Architecture

### Stage 1 — Abstract Schedule (SSE stream)

`POST /api/generate-abstract` accepts:
```json
{ "num_teams": 51, "matches_per_team": 11, "cooldown": 3, "seed": "a1b2c3d4", "day_config": {...} }
```

Returns SSE events: `progress` (intermediate) and `complete` (final JSON with `abstract_schedule_id`).

The scheduler runs in a `ProcessPoolExecutor` worker (not the event loop). Progress is piped back via `multiprocessing.Queue` polled with `asyncio.get_event_loop().run_in_executor`.

### Stage 2 — Team Assignment (SSE stream)

`POST /api/abstract-schedules/{id}/assign` accepts:
```json
{ "team_numbers": [254, 1114, ...], "iterations": 1000, "assign_seed": "cafebabe" }
```

Chunked: sends `progress` SSE every N iterations with best score so far.

### Database

SQLAlchemy async with asyncpg. Models: `Event`, `Team`, `EventTeam`, `AbstractSchedule`, `AssignedSchedule`. `create_all` on startup. No Alembic (add for production).

Required migrations for existing databases:
```sql
ALTER TABLE abstract_schedules ADD COLUMN IF NOT EXISTS day_config JSON;
ALTER TABLE teams ALTER COLUMN name TYPE TEXT;
ALTER TABLE events ALTER COLUMN name TYPE TEXT;
ALTER TABLE events ALTER COLUMN location TYPE TEXT;
```

---

## Frontend Architecture

Single file: `static/index.html` (~300KB). Non-module `<script>` tag — no bundler.

### State variables
```javascript
let _currentEventId = null;
let _currentAbstractScheduleId = null;
let _currentAssignedScheduleId = null;
let _abstractParams = null;           // params snapshot from Stage 1
let _currentSlotMap = null;           // {slot_str: team_number} from Stage 2
let _currentSeed = null;              // hex Stage 1 seed
let _currentAssignSeed = null;        // hex Stage 2 seed
let _agendaBlocks = null;             // [{start, end, duration, startStr, endStr, day}]
let _tbaSearchIndex = null;           // TBA global event index (all years)
let _tbaDropdownCache = {};           // year → events array
let _frcDropdownCache = {};           // "frc_{year}" → events array
let _pdfjsLib = null;                 // lazy-loaded PDF.js
let _pdfjsLoading = null;             // dedup promise
let _authUser = null;                 // {sub, email, provider} or null
let _urlAutoTeams = null;             // teams from URL for Stage 2 auto-assign
```

### Seeded PRNG (mulberry32)
```javascript
function makeRng(seed) {
  return function() {
    seed |= 0; seed = seed + 0x6D2B79F5 | 0;
    var t = Math.imul(seed ^ seed >>> 15, 1 | seed);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}
```

### Auto flags (checkboxes)

Three checkboxes in one bordered box below Match Cooldown:

| ID | Default | Behaviour |
|----|---------|-----------|
| `autoPopulate` | `checked` | Debounced Stage 1 regeneration on param change (1.5s) |
| `autoApplyAgenda` | `checked` | Calls `applyAgendaToSchedule()` after successful PDF parse |
| `autoMaxCycles` | `checked` | Calls `calcMaxMatches()` after day config applied (auto or manual) |

**`window._agendaFetchPending` flag** — set `true` in `activateEvent` before firing `fetchAndRenderAgendaFit`, cleared in `.finally()`. Prevents `loadRoster()` from calling `onParamChanged()` prematurely (before day config is applied from the PDF).

**`loadRoster()`** — after setting `numTeams.value`, calls `onParamChanged()` only when `!window._agendaFetchPending`. This allows auto-regenerate to fire when there is no event key (and thus no PDF fetch).

**Full auto-trigger chain on event load:**
```
activateEvent(ev)
  → _agendaFetchPending = true
  → loadRoster()
      sets numTeams.value
      _agendaFetchPending is true → skip onParamChanged()
  → fetchAndRenderAgendaFit(ev.key)   [non-blocking]
      [PDF fetch + parse]
      applyAgendaToSchedule()          [if autoApplyAgenda on]
        sets day start/end/breaks via .value
        if autoMaxCycles on → calcMaxMatches()
          writes matchesPerTeam.value
          if autoPopulate on → generateSchedule()  ← TRIGGERS
      else if autoMaxCycles on → calcMaxMatches() → generateSchedule()
      else → onParamChanged()  ← debounced generateSchedule() if autoPopulate on
  .finally() → _agendaFetchPending = false

  [PDF fail path]:
      shows manual minutes input
      onParamChanged()  ← still triggers generation with numTeams from roster
```

`applyAgendaToSchedule()` also calls `calcMaxMatches()` at its end if `autoMaxCycles` is checked (covers the manual Apply button case).

**Duplicate `mpr` variable** — `updateAgendaFit` had `var mpr` declared twice (once after `reqCycle`, once after). Second declaration removed.

**`generateSchedule()`** — shows `⏳ Generating schedule…` in `showApiStatus()` immediately when called, before the SSE stream begins.

---

## Agenda Fit Integration (from frc-schedule-builder)

Ported from `github.com/phil-lopreiato/frc-schedule-builder` by Phil Lopreiato.

### State
```javascript
let _agendaBlocks = null;  // [{start, end, duration, startStr, endStr, day}] | null
```

### PDF.js loading (`loadPdfJs`)
Cannot use `import()` directly in a non-module script. Solution: inject a `<script type="module">` that imports PDF.js and dispatches `pdfjsloaded` event:
```javascript
var s = document.createElement('script');
s.type = 'module';
s.textContent = `
  import * as pdfjsLib from '${PDFJS_CDN}/pdf.min.mjs';
  pdfjsLib.GlobalWorkerOptions.workerSrc = '${PDFJS_CDN}/pdf.worker.min.mjs';
  window._pdfjsLib = pdfjsLib;
  window.dispatchEvent(new Event('pdfjsloaded'));
`;
document.head.appendChild(s);
```
Deduped via `_pdfjsLoading` promise. CDN: `https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379`

### PDF fetch
```
GET https://info.firstinspires.org/hubfs/web/event/frc/{year}/{YEAR}_{EVENTCODE}_Agenda.pdf
```
Times in FIRST agenda PDFs are local event time — no timezone. Throws on non-200 or non-PDF content-type.

### PDF parsing (`parsePDFBlocks`, `parseQualBlocks`)
1. Extract text per page grouped by Y coordinate (PDF space), sorted Y descending, items within a line sorted X ascending
2. Collapse PDF.js character-spacing artifacts: `\d[ \t]?\d?[ \t]*:[ \t]*\d[ \t]*\d[ \t]*[AaPp][ \t]*[Mm]` → remove internal spaces
3. Line-by-line scan: day pattern (`Monday|Tuesday|…` + month+day), qual block pattern (`HH:MM AM/PM – HH:MM AM/PM Qualification Match`)
4. Fallback: scan joined full text if line-by-line finds nothing

### Fit calculation (`updateAgendaFit`)
```javascript
totalMatches = Math.ceil(numTeams * mpt / 6)
surrogates   = totalMatches * 6 - numTeams * mpt
timeNeeded   = totalMatches * ct
available    = sum(agendaBlocks[i].duration)  // or agendaManualMin
surplus      = available - timeNeeded
pct          = timeNeeded / available * 100
mpr          = 60 / ct                        // matches per hour
reqCycle     = available / totalMatches       // max cycle to fit
```

### Block distribution (`distributeMatchesToBlocks`)
Fits: floor-proportional by duration + fractional remainder sort.
Over capacity: floor each block (`Math.floor(duration / ct)`), pour overflow into block index 1.

### Auto-apply (`applyAgendaToSchedule`)
1. Group `_agendaBlocks` by `b.day` → `dayMap` / `dayOrder`
2. `numDays.value = dayOrder.length`; call `buildDaysUI()`
3. Per day row: `.day-start` = `minToTimeStr(min(block.start))`, `.day-end` = `minToTimeStr(max(block.end))`
4. Sort blocks by start; gaps → `addBreak(row.querySelector('.btn-add-break-day'), gapStart, gapEnd, "Lunch"|"Break")`
5. `applyDayEndTimes()` → `validateTimesAndRecalc()`
6. If `autoMaxCycles.checked` → `calcMaxMatches()`

### HTML elements
- `#agendaFitPanel` — outer container, `display:none` until event loaded
- `#agendaFitBadge` — fit status badge in collapsible header
- `#agendaChevron` — ▼/▶ collapse indicator
- `#agendaFitLoading` — loading/error text
- `#agendaFitStats` — 6-stat grid (CSS: `repeat(6, 1fr)`, mobile `repeat(3, 1fr)`)
- `#agendaFitBlocks` — per-block rows with `#agendaBar_{start}` timeline bars
- `#agendaApplyRow` — shown only after successful parse; contains Apply button
- `#agendaFitManual` — shown when PDF unavailable; contains `#agendaManualMin`

### Lifecycle hooks
- `activateEvent(ev)` → `fetchAndRenderAgendaFit(ev.key).catch(() => {})` (non-blocking)
- `fullReset()` → `resetAgendaPanel()` (hides panel, nulls `_agendaBlocks`, hides apply row)
- `['numTeams','matchesPerTeam','cycleTime']` input → `onScheduleParamsChanged()` → `updateAgendaFit()`

---

## Day/Night Mode

`[data-theme="light"]` on `<html>` overrides CSS custom properties:
```css
[data-theme="light"] {
  --bg: #f4f4f8;  --surface: #ffffff;  --surface2: #eaeaf0;
  --border: #c8c9d4;  --accent: #3b7dd8;  --accent2: #c0394e;
  --accent3: #2a8c5a;  --text: #2c2f42;  --text-muted: #6b6e84;
  --text-strong: #1a1c2a;  --red-team: #c0394e;  --blue-team: #3b7dd8;
  --amber: #9a6c00;  --danger: #c0394e;
}
```

`initTheme()` IIFE: reads `localStorage.getItem('frc_theme')`, applies `data-theme="light"` before render if saved. Button emoji: 🌙 (dark) / ☀️ (light). Stored as `'light'` or `'dark'`.

---

## TBA Integration (`app/tba.py`)

HTTP: `httpx.AsyncClient` created per request (no singleton — module-level singleton caused event loop issues). Auth header: `X-TBA-Auth-Key: {TBA_API_KEY}`. Raises `ValueError` if key not set → HTTP 503.

Key functions:
- `get_events(year)` → `GET /events/{year}/simple`, sorted by `start_date` ascending
- `get_event(key)` → `GET /event/{key}/simple`
- `get_event_teams(key)` → `GET /event/{key}/teams/simple`
- `search_events(year, q)` → `get_events(year)` filtered client-side
- `normalise_event(tba)` → `{key, name, year, location, start_date, end_date, tba_synced}`
- `normalise_team(tba)` → `{number, name, nickname, city, state, country, rookie_year}`


### Auto flags — URL and DB persistence

Auto flags are stored as **named booleans** in two places:

**URL:** Each flag has its own param (`autoPopulate`, `autoApplyAgenda`, `autoMaxCycles`). A param is only included when it is **off** (`=0`) — all defaults are on, so omitting a param means on. This keeps share URLs clean for the common all-on case and is trivially extensible: adding a new flag never reinterprets existing URLs.

```
?autoPopulate=0              — only autoPopulate is off
?autoApplyAgenda=0           — only autoApplyAgenda is off
?autoMaxCycles=0&autoApplyAgenda=0  — two flags off
(no flag params)             — all flags on (default)
```

**DB:** `day_config` JSON stores named boolean fields. `collectDayConfig()` writes `autoPopulate`, `autoApplyAgenda`, `autoMaxCycles`. `applyDayConfigToUI()` restores them; `null` (field absent) leaves the current default unchanged.

**`parseBoolFlag(name)`** helper in `parseUrlParams()`: returns `true` if param present and not `"0"`, `false` if present and `"0"`, `null` if absent. Downstream code only applies the value when non-null.
### `GET /api/tba/search_index`
Proxies `tba_client._get("/search_index")` → returns `data["events"]` (key+name pairs, all years, all events).

### Cross-year search (`filterTbaDropdown`)
When `visibleCount < 3 && query.length >= 2 && source === 'tba'`:
1. Calls `searchTbaIndex(query)` → filters `_tbaSearchIndex`, sort by key desc, top 20
2. Removes stale `[data-cross-year="1"]` rows
3. Injects separator div + cross-year rows with `data-cross-year="1"`
4. Calls `ensureTbaSearchIndex()` to pre-fetch if not yet loaded

`ensureTbaSearchIndex()`: deduped via `_tbaSearchIndexLoading` flag, pre-fetched `setTimeout(..., 2000)` on load.

---

## FRC Events API (`app/frc_events.py`)

HTTP Basic auth: `base64(FRC_EVENTS_USERNAME:FRC_EVENTS_TOKEN)`. `ValueError` if not set → HTTP 503.

Key functions:
- `get_events(year)` → `GET /{year}/events` → `data["Events"]`, sorted by `start_date`
- `get_event(year, code)` → same with `?eventCode=CODE` (uppercase), returns first or None
- `get_event_teams(year, code)` → `GET /{year}/teams?eventCode=CODE`, paginates (page size 65)
- `normalise_event(frc, year)` → `{key, name, year, location, start_date, end_date, tba_synced, _frc_code}`; `_frc_code` stripped before DB write
- `normalise_team(frc)` → maps `teamNumber`, `nameFull/nameShort`, `city`, `stateProv`, `country`, `rookieYear`
- `is_configured()` → bool

Routes (stacked decorators for alias):
```python
@app.get("/api/frc/configured")
@app.get("/api/frc/status")
async def frc_events_status(): ...
```

Frontend: credential errors surfaced in `showApiStatus()` (visible immediately, not just in hidden dropdown).

---

## Calc Max Matches (`calcMaxMatches`)

Simulates the exact scheduling loop used by `_finishGenerationInner`:
1. For each day row: step cursor from `dayStart` to `dayEnd`
2. Flush breaks at or before cursor
3. Check break buffer: if `breakStart - cursor < breakBuffer` → flush break and continue
4. Get effective cycle time from per-day cycle change list (uses global `totalSlotMatches` for cross-day cycle changes)
5. If `cursor + ct > dayEnd` → break
6. Check interrupt suppression (skip if already cleared buffer)
7. `cursor += ct; dayMatchCount++; totalSlotMatches++`

Result: `mpt = floor(totalSlotMatches * 6 / numTeams)`, back off by 1 if `ceil(n * mpt / 6) > totalSlotMatches`.

Writes result to `#matchesPerTeam`. Shows status message with match/slot/surrogate counts. If `autoPopulate` checked → triggers `generateSchedule()`.

---

## Stage 2 Simulated Annealing (`scheduler.py: assign_teams`)

```python
budget = num_teams * 2
T0 = 500.0
for step in range(budget):
    T = T0 * (1.0 - step / budget)   # linear cooling
    a, b = _rng.sample(slots, 2)     # 2-swap
    # score delta
    if delta >= 0: accept
    elif T > 0 and delta/T > -10 and random() < exp(delta/T): accept
    else: revert
```

Best result across all iterations and all parallel workers is kept.

Score: `-(b2b×1000 + imbalance×500 + surrogates×200 + repeat_opp×15 + repeat_part×12)`

### Iteration estimate (`updateIterationEstimate`)
- Default: `11ms/iter` wall-clock (90ms/worker ÷ 8 workers benchmark)
- After run: `window._msPerIteration = elapsed / iterations`
- Guard: `!== null` (not `||`) so calibrated `0` doesn't revert to default
- Shows `(estimated)` until calibrated, then `(calibrated)`

---

## Authentication (`app/auth.py`)

JWT issued after OAuth. Payload: `{sub, email, provider, uid}`. Signed with `JWT_SECRET` (HS256, 30-day expiry). Auth is optional — all endpoints work without a token; ownership features require it.

Google: standard PKCE flow. Apple: `response_mode=form_post`, client secret is a self-signed JWT using ES256 + Apple private key.

---

## TBA Error Handling (`loadEventByCode`)

Four distinct messages from `e.message` content:
- `includes('not found')` or `404` → event key wrong
- `includes('No TBA_API_KEY')` or `503` → server not configured
- `includes('timed out')` or `504` → retry
- else → raw message

`showApiStatus(msg, isErr)`: errors persist (no auto-hide); success hides after 3s. Uses `clearTimeout(window._apiStatusTimer)`.

---

## Day/Night Mode (`toggleTheme`, `initTheme`)

`toggleTheme()`: sets/clears `document.documentElement.setAttribute('data-theme', 'light')`, updates `#btnTheme` emoji (🌙/☀️), saves to `localStorage('frc_theme')`.

`initTheme()` IIFE: reads `localStorage.getItem('frc_theme')` synchronously before first render. If `'light'`, sets `data-theme="light"` and updates button after `DOMContentLoaded`.

## CSS Architecture

Single `<style>` block, CSS custom properties. Dark default (Catppuccin Mocha). Light override via `[data-theme="light"]`.

Typography (all reduced from original heavy weights for readability):
- `.stat-value` — `600` weight, `1.5rem`
- `.panel-header` — `600` weight, `0.1em` letter-spacing
- `.day-title` — `600` weight
- `.teams-red/blue` — `600` weight, `0.88rem`
- `.match-num` — `500` weight
- All table borders use `var(--border)` (not hardcoded rgba)
- Break row color uses `var(--amber)` (not hardcoded `#b89040`)

Mobile `@media (max-width: 640px)`: iOS zoom prevention (all inputs `font-size: 16px`), event bar stacks to two rows, field rows collapse to 1-col, stats bar 2-col, schedule table horizontal scroll.

Agenda fit grid: `repeat(6, 1fr)` desktop, `repeat(3, 1fr)` mobile. Stat values `font-size:1.15rem; font-weight:600` (inline override).

---

## OpenShift Manifests

| File | Purpose |
|------|---------|
| `00-namespace.yaml` | Project/namespace |
| `01-secrets.yaml` | All env vars as a Secret |
| `02-postgres.yaml` | StatefulSet + PVC + Service |
| `03-buildconfig.yaml` | BuildConfig (git source, `Containerfile.openshift`) |
| `04-deployment.yaml` | Deployment (envFrom secret, liveness probe) |
| `05-route.yaml` | HTTPS edge-terminated Route |
| `07-build-trigger-sa.yaml` | ServiceAccount + RoleBinding for CronJob |
| `08-build-cronjob.yaml` | CronJob: polls git, triggers build if new commits |
| `09-hpa-optional.yaml` | HorizontalPodAutoscaler (optional) |
| `rebuild.sh` | Full teardown + rebuild script |

Two Containerfiles: `Containerfile` (generic, apt-get, Docker Hub base) and `Containerfile.openshift` (dnf/rpm, Quay base — avoids Docker Hub rate limits in OCP build pods). Both rootless-compliant with `chgrp -R 0 && chmod -R g=u`.

---

## Removed Features

**Timezone selector** — removed. FIRST agenda PDFs list times in local event time with no timezone information. All scheduler times are implicitly local to the venue. Removed: `tzSelect` field, `buildTimezoneSelect()`, `getTimezoneAbbr()`, `window._frcTzAbbr`, and the inline timezone span in schedule time cells (`window._frcTzAbbr ? '<span>...' : ''`). FIRST agenda PDFs list times in local event time with no timezone information. All scheduler times are implicitly local to the venue. The `tzSelect` field, `buildTimezoneSelect()`, `getTimezoneAbbr()`, `window._frcTzAbbr`, and the inline timezone span in schedule time cells were all removed.


### Day section input fix
**`onParamChanged()`** — two fixes:

1. Previously only debounced `generateSchedule()` when `_abstractParams !== null`. After a reset, `_abstractParams` is `null` so nothing fired. Fixed: debounce now fires whenever `autoPopulate` is checked AND `numTeams >= 6`, regardless of `_abstractParams`. Stale-warning and btnAssign-disable logic still only runs when `_abstractParams !== null`.

2. Day section `input` events were not calling `onParamChanged()` — only `change` (blur/tab-away) was. Users editing cycle time fields mid-type would see no auto-regeneration. Fixed by adding `onParamChanged()` to every `input` handler in the day section:

| Input | Fixed |
|-------|-------|
| Per-day cycle time `.cc-time` `input` | ✓ |
| Cycle-change after-match `.cc-after` `input` | ✓ |
| Day-level secondary cycle-change `input` | ✓ |
| Break name `input` | ✓ (replaced old `_abstractParams !== null` guard) |
| Global `cycleTime` field | ✓ (added `input` listener alongside existing `change`) |

All `onParamChanged()` calls go through the 2.5s debounce — rapid typing resets the timer and fires once when the user pauses.

**`fetchAndRenderAgendaFit` calls `generateSchedule()` directly** (not via debounce) after the PDF work completes. This avoids a 2500ms delay and eliminates a race condition where the debounce could fire before `generateSchedule` was ready. `applyAgendaToSchedule()` uses `validateTimes()` instead of `validateTimesAndRecalc()` so it does not queue a spurious debounce — generation is entirely the caller's responsibility.

**Precedence chain in `fetchAndRenderAgendaFit`** (simplified — always runs steps in order, each gated by its own flag):
```javascript
if (autoApplyAgenda.checked) applyAgendaToSchedule();
if (autoMaxCycles.checked)   calcMaxMatches();   // → generateSchedule() if autoPopulate on
else if (autoPopulate.checked) generateSchedule();
// autoAssign fires inside Stage 1 completion hook
```

**PDF fail path:** same chain starting at `calcMaxMatches` / `generateSchedule`.

**`getBlockCycleTime(blockIndex)`** — reads `.day-cc-row[data-is-start="1"] .cc-time` from the nth day row. Falls back to global `#cycleTime` if not found.

**`distributeMatchesToBlocksPerCt(totalMatches, blocks, blockCts)`** — replaces single-ct `distributeMatchesToBlocks`. Uses each block's own capacity (`duration / blockCts[i]`) for proportional distribution. When over capacity, fills each block to floor capacity and puts overflow in the last block. `distributeMatchesToBlocks` is kept as a legacy wrapper.

**`updateAgendaFit()`** now called from:
- `finishGeneration` end (after `renderSchedule()`) — syncs timeline with rendered schedule
- `calcMaxMatches` before triggering `generateSchedule` — syncs after mpt update
- `onScheduleParamsChanged` — on numTeams/matchesPerTeam/cycleTime input events
- `fetchAndRenderAgendaFit` success and fail paths

**Duplicate `mpr` variable** — `updateAgendaFit` had `var mpr` declared twice (once after `reqCycle`, once after). Second declaration removed.

**`generateSchedule()`** — shows `⏳ Generating schedule…` in `showApiStatus()` immediately on entry, before the SSE stream begins.