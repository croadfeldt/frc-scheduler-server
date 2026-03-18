# FRC Match Scheduler — Reproduction Prompt

This document captures all architecture decisions, implementation details, and known pitfalls needed to reproduce or extend this codebase from scratch.

---

## Project Overview

Single-file HTML/CSS/JS frontend (`static/index.html`, ~6400 lines) + FastAPI backend (`app/main.py`) + pure Python scheduler (`app/scheduler.py`). PostgreSQL via asyncpg/SQLAlchemy. Containerised for OpenShift.

Two-stage scheduling:
- **Stage 1:** Abstract schedule (slot indices, no team numbers) — deterministic, one pass
- **Stage 2:** Team assignment (SA optimiser maps team numbers to slots)

---

## Critical Architecture Decisions

### Double-calcMaxMatches Bug (FIXED)
`applyAgendaToSchedule()` must NOT call `calcMaxMatches()`. The chain in `fetchAndRenderAgendaFit` calls it after `applyAgendaToSchedule` returns. Having both call it caused the first `generateSchedule()` to be aborted by the second, leaving the overlay stuck.

### _agendaFetchPending Flag
Set to `true` in `activateEvent` before any async work. `onParamChanged()` returns early when this is true. Cleared in `.finally()` after `fetchAndRenderAgendaFit` completes. Prevents debounced generation from racing the PDF chain.

### Overlay show() before loadRoster()
`_overlay.show()` and `_overlay.step('roster')` must be called **before** `await loadRoster()`. Previously they were called after, meaning overlay was always one step behind (roster already done when overlay shown).

### calcMaxMatches Infinite Loop Guard
The `while` loop in `calcMaxMatches()` has a `_safetyLimit = 2000` iteration cap and a `ct < 0.5` guard. Without this, a blank or zero cycle-time field (mid-keystroke) causes an infinite loop that permanently hangs the browser tab.

### Day Break / Early End

`addDayEarlyEnd(dayRow, afterMatch)` — adds a `.day-earlyend-row` to the day row. Only one per day (replaces existing). Calls `onCycleTimeChanged()` on input/change/remove.

`getDayEarlyEnd(dayRow)` — returns the integer limit or null. Used by `calcMaxMatches` and `_finishGenerationInner`.

**`calcMaxMatches`:** reads `getDayEarlyEnd(row)` into `dayEarlyEnd`; after incrementing `dayMatchCount`, checks `if (dayEarlyEnd !== null && dayMatchCount >= dayEarlyEnd) break`.

**`_finishGenerationInner`:** `earlyEnd` stored on day object (`isObj ? row.earlyEnd : getDayEarlyEnd(row)`); `dayMatchCount` counter incremented after each placed match; `if (day.earlyEnd !== null && dayMatchCount >= day.earlyEnd) break`.

**Persistence chain:** `collectDayConfig` → `earlyEnd: getDayEarlyEnd(row)` → DB `day_config`. `applyDayConfigToUI` → `if (day.earlyEnd != null) addDayEarlyEnd(row, day.earlyEnd)`. URL: `d{N}e=M`, parsed via `p.get('d' + i + 'e')`, applied in `applyUrlParams`.

---

### Print Schedule

`openPrintDialog()` — disables `#printOptTeamNums` if `hasAssignment` is false (opacity 0.45, `disabled`, tooltip). Calls `openModal('modalPrint')`.

`printSchedule()` — reads opts, builds HTML string, opens `window.open('', '_blank')`, calls `w.print()` after 300ms.

**CRITICAL — teamLabel:** `entry.red/blue` are already real team numbers after Stage 2 (server resolves in API). `teamLabel(val)` = `showTeamNums ? String(val) : '—'`. Do NOT look up `_currentSlotMap[val]` — keys are slot indices, not team numbers.

**matchPassesPrintFilter(entry):** `entry.red.concat(entry.blue)` checked against `_frcFilters.teams`. No mapping needed — values are already team numbers.

**Page break:** `opts.pageBreak` → day title gets class `page-break` on days after the first → CSS `page-break-before: always`.

**Opts:** `cycleTimes`(on), `cycleChanges`(on), `breaks`(on), `dayBreaks`(on), `teamNums`(on), `roundDividers`(off), `pageBreak`(off).

---

### Cycle Change Duplication Fix

Both `applyUrlParams` and `applyDayConfigToUI` add non-start cycle change rows. Without clearing first, each reload duplicated them. Fix applied in both functions:

```javascript
// Before adding saved cc rows:
document.querySelectorAll('.day-cc-row[data-is-start="0"]').forEach(function(r) { r.remove(); });
```

The `data-is-start="1"` row is always created by `buildDaysUI()` and is never removed — its `.cc-time` value is simply updated in place.

---

### Agenda Fit Overflow Bar

`renderScheduleBars()` appends `<div id="agendaFitOverflow">` as a sibling of `#agendaFitBlocks` (created on first call, reused thereafter). Shown when `window._frcFinalDayOverflow.unscheduled > 0`:

```javascript
// Estimate additional time from last section's avg cycle time
var estCt = lastSection.committed / lastSection.matchCount;
var extraMin = Math.round(ov.unscheduled * estCt);
```

Bar fills 100% width with `background:var(--danger)`. Hidden (`display:none`) when all matches fit. `resetAgendaPanel()` also clears it.

---

### Cycle Time Sync Prompt

`cycleTime` `change` listener checks `anyDiffers`: if any `.day-cc-row[data-is-start="1"] .cc-time` value ≠ new ct, shows `confirm()`. On OK: pushes to all start rows + shows `cycleTimePushWarning` 4s. `input` listener: only `onParamChanged()`.

---

### Team List Clear / Export

`clearTeamList()` — DOM-reads team nums, `confirm()`, sequential `DELETE` calls, `loadRoster()`, `numTeams=0`, `onParamChanged()`.

`exportTeamList()` — `#teamRoster .team-row` → CSV rows, Blob URL download as `teams-event-{id}.csv`.

---

### Single-Day End Time

`applyDayEndTimes()`: `isLast = (i === total - 1) && (total > 1)`. Single day → `18:00`. Multi-day last → `12:00`.

---

### Ad-hoc Event

`GET /api/events/adhoc` — upserts a `Team`-less event with `key='adhoc'` on first call:
```python
ADHOC_KEY = "adhoc"
event = await db.execute(select(Event).where(Event.key == ADHOC_KEY))
# if not found: create with current year, empty location, tba_synced=False
```
Returns same shape as `get_event` — `activateEvent(ev)` works unchanged. No migration needed; creates on demand.

Client: `loadAdhocEvent()` → `apiFetch('/api/events/adhoc')` → `activateEvent(ev)`. Button `#btnAdhoc` hides in `activateEvent` (`adhocBtn.style.display = 'none'`), reappears in `fullReset`.

---

### Team List Import

**`parseTeamListText(text)`** — auto-detects format, no dependencies:
- JSON: `t.startsWith('[')` → `JSON.parse` → integers
- YAML/bullets: `/^\s*[-*]\s+\d/m` → extract from `- N` lines
- Generic fallback: `text.match(/\d+/g)` → filter 1–99999
- Returns sorted, deduped array. Non-numbers silently skipped.

**`_bulkAddTeams(numbers)`** — sequential `POST /api/events/{id}/teams` (avoids server overload). Skips existing numbers via DOM query on `#teamRoster .team-num`. Single `loadRoster()` after all adds. Fires `enrichTeamFromTba(n)` for each new number.

**`enrichTeamFromTba(teamNumber)`** — completely non-blocking, all failures silent:
1. `GET /api/tba/team/{n}` → server calls `tba_client.get_team(f"frc{n}")` → `normalise_team()`
2. Updates `.team-name` span in existing row (no full re-render)
3. `PATCH /api/events/{id}/teams/{n}` → updates `Team.nickname`/`Team.name` in DB

**Server endpoints added:**
- `GET /api/tba/team/{team_number}` — wraps `tba_client.get_team()`, returns 404 on any error
- `PATCH /api/events/{event_id}/teams/{team_number}` — updates `Team.nickname`/`Team.name`, 200 response

**Input methods:** textarea paste, `#teamImportFile` FileReader, `ondrop` on textarea.

---

### Page Load Performance

**Immediately on load:** `loadEvents()` (GET /api/events), `initAuth()` (GET /auth/me).

**Deferred:**
- `fetchTbaDropdown()` — on first `focus` of `#eventCodeInput` (was 800ms eager)
- `ensureTbaSearchIndex()` — 5s after load; `localStorage` cache `tba_idx_{year}` 6h TTL
- `/api/health` — 2s timeout (only for `_cpuWorkers` count in overlay)

**Diagnosis:** `apiFetch()` logs `[api] METHOD /path Nms STATUS` to the browser console. Check this on first load to identify which call is slow.

---

### numDays ↔ Day Rows Sync

Bidirectional, always in sync. `syncDayRowsToNumDays()` is the single source of truth for numDays → rows:
```javascript
// Triggered by both 'change' and 'input' (input guarded: !isNaN(n) && n >= 1 && n <= 5)
document.getElementById('numDays').addEventListener('change', syncDayRowsToNumDays);
document.getElementById('numDays').addEventListener('input', function() {
  var n = parseInt(this.value);
  if (!isNaN(n) && n >= 1 && n <= 5) syncDayRowsToNumDays();
});
```

`addDay()` → increments `numDays.value` then calls `buildDaysUI()`.
`removeDay(el)` → removes row, sets `numDays.value = querySelectorAll('.day-row').length`.
`buildDaysUI()` → sets `numDays.value` to actual row count after add/remove.

**PDF fail warning** — `configuredDays = querySelectorAll('.day-row').length`. Warning says "Schedule is configured for N qual days" using actual row count, not date estimate.

---

### Print Schedule

`openPrintDialog()` — disables/unchecks `printOptTeamNums` if no assignment (`!hasAssignment`). `openModal('modalPrint')`.

`printSchedule()` — reads opts from checkboxes, builds HTML string, opens in new tab, calls `window.print()` after 300ms.

**`teamLabel(val)` — CRITICAL:** `entry.red/blue` already contain real team numbers after Stage 2 (server resolves slot→team). Return `String(val)` if `showTeamNums`, else `'—'`. Never look up `_currentSlotMap[val]` — slot map is keyed by slot index, not team number.

**`matchPassesPrintFilter(entry)`** — `entry.red.concat(entry.blue)` checked against `_frcFilters.teams`. No slot→team mapping needed.

**Page break:** `opts.pageBreak` → CSS `.day-title.page-break { page-break-before: always }` added to print style. Applied to all days except first (`isFirstDay = scheduled.indexOf(day) === 0`).

**Options:** `printOptCycleTimes`✓, `printOptCycleChanges`✓, `printOptBreaks`✓, `printOptDayBreaks`✓, `printOptTeamNums`✓ (disabled if no assign), `printOptRoundDividers`☐, `printOptPageBreak`☐.

---

### Cycle Change Duplication Fix

Both `applyUrlParams` and `applyDayConfigToUI` add non-start cycle change rows. Without clearing first, each reload duplicated them. Fix applied in both functions:

```javascript
// Before adding saved cc rows:
document.querySelectorAll('.day-cc-row[data-is-start="0"]').forEach(function(r) { r.remove(); });
```

The `data-is-start="1"` row is always created by `buildDaysUI()` and is never removed — its `.cc-time` value is simply updated in place.

---

### Agenda Fit Overflow Bar

`renderScheduleBars()` appends `<div id="agendaFitOverflow">` as a sibling of `#agendaFitBlocks` (created on first call, reused thereafter). Shown when `window._frcFinalDayOverflow.unscheduled > 0`:

```javascript
// Estimate additional time from last section's avg cycle time
var estCt = lastSection.committed / lastSection.matchCount;
var extraMin = Math.round(ov.unscheduled * estCt);
```

Bar fills 100% width with `background:var(--danger)`. Hidden (`display:none`) when all matches fit. `resetAgendaPanel()` also clears it.

---

### Global Cycle Time Field Routing

`#cycleTime` `input` → `onCycleTimeChanged()` (was `onParamChanged()` — wrong, skipped calcMaxMatches).
`#cycleTime` `change` → push to day start rows (with confirm if differs) → `onCycleTimeChanged()`.

Both must go through `onCycleTimeChanged()` so the 1.2s debounce fires `calcMaxMatches()` when autoMaxCycles is on.

---

### Agenda Fit Fill Bar Label

Format: `N matches · X / Y min · Z min/match avg`
- `Z = avgCtStr` = `committed / matchCount`, rounded: `avgCt % 1 < 0.05 ? Math.round(avgCt) : avgCt.toFixed(1)`
- Cycle change progression (`9→8 min/match`) shown as `title` tooltip on the bar track, not inline
- `ctBadge` header element removed entirely

---

### Cycle Time Sync Prompt

On `cycleTime` `change` event:
1. `var dayStartInputs = Array.from(querySelectorAll('.day-cc-row[data-is-start="1"] .cc-time'))`
2. `var anyDiffers = dayStartInputs.some(inp => parseFloat(inp.value) !== newCt)`
3. If `anyDiffers`: `confirm('Apply N min cycle time to all day start-of-day rows?')` — OK pushes to all, Cancel skips
4. If all match or no rows: push silently

---

### fullReset Event State Cleanup

After URL cleanup, `fullReset()` now also clears:
```javascript
_currentEventId = null;
codeInput.value = ''; codeInput.className = '';
codeStatus.textContent = '';
eventSel.value = '';
btnManageTeams.disabled = true;
btnDeleteEvent.disabled = true;
btnAdhoc.style.display = '';
```

---

### onCycleTimeChanged Debounce
Cycle-time inputs call `onCycleTimeChanged()` (1.2s debounce) not `onParamChanged()` (2.5s). This calls `calcMaxMatches()` when `autoMaxCycles` is on, bypassing the plain debounce. Without the 1.2s debounce, mid-keystroke values (typing "10" → field briefly shows "1") caused rapid-fire calcMaxMatches calls.

### _DAY_COLORS Must Be Defined Before buildDaysUI
`_DAY_COLORS` must be defined at module level directly above `buildDaysUI()` — before `buildDaysUI` in the source order. `buildDaysUI()` is called at page load (line ~1565) before most of the script body is parsed. Defining `_DAY_COLORS` anywhere after `buildDaysUI` causes `TypeError: undefined is not an object (evaluating '_DAY_COLORS.length')`.

### SA Incremental Scoring
`assign_teams()` uses `build_score_state()` once per iteration start, then `delta_swap()` for each swap attempt. `delta_swap()` only rescores the ~10-20 matches containing the swapped slots. State is fully rebuilt only on accepted moves. This gives ~30ms/iter vs 80ms for full rescore.

### CPU Worker Count Must Match Pod CPU Limit
`CPU_WORKERS=0` causes `os.cpu_count()` to return the node's full CPU count (e.g. 16+) even in a container with a 2-CPU limit. The pool spawns 16 workers competing for 2 CPUs → constant context switching → minimal throughput. Always set `CPU_WORKERS` explicitly to match the pod's CPU limit.

### WEB_WORKERS=1 with High CPU_WORKERS
With `WEB_WORKERS>1`, each uvicorn process has its own `ProcessPoolExecutor`. At `WEB_WORKERS=2, CPU_WORKERS=12`, two concurrent assignment jobs could spawn 24 Python processes for 12 CPUs. Use `WEB_WORKERS=1` so one process owns the full pool.

### scrollToMatch Uses getBoundingClientRect
`offsetTop` + `offsetParent` traversal is unreliable for `<tr>` elements inside `<table>`. Both `scrollToMatch()` and `scrollToDay()` use `getBoundingClientRect()` with `output.scrollTop + (rowRect.top - outputRect.top)` for reliable cross-browser scroll positioning.

### day.start / day.end Must Be Stored on _frcScheduled
`_finishGenerationInner` must push `{dayNum, start: day.start, end: day.end, entries}` to the `scheduled` array. Without `start`/`end`, `renderScheduleBars()` falls back to first/last match timestamps, showing match-span not the full agenda slot.

---

## Auto Chain Precedence

```javascript
// In fetchAndRenderAgendaFit success path:
if (autoApply.checked)   applyAgendaToSchedule();  // does NOT call calcMaxMatches
if (autoMax.checked)     calcMaxMatches();           // calls generateSchedule() if autoPopulate on
else if (autoGen.checked) generateSchedule();        // generateSchedule() steps 'generate' overlay internally

// In fetchAndRenderAgendaFit fail (PDF not found) path:
_overlay.done('pdf');
if (autoMax.checked)     calcMaxMatches();
else if (autoGen.checked) generateSchedule();
else                      _overlay.hide();

// In calcMaxMatches end:
_overlay.done('maxcycles');
updateAgendaFit();
if (_abstractParams !== null || autoPopulate.checked) generateSchedule();

// In generateSchedule Stage 1 completion:
_overlay.done('generate');
if (autoAssign.checked && _currentEventId) {
  _overlay.step('assign', '…');
  setTimeout(assignTeams, 200);
} else {
  _overlay.hide();
}

// In assignTeams completion:
_overlay.hide();
```

---

## Key Functions

**`buildDaysUI()`** — creates `.day-row` divs, applies `_DAY_COLORS[i % 7]` as background tint (`+14` hex alpha) and border (`+50`), sets day label color to the day color.

**`renumberDays()`** — called after add/remove day; reapplies colors and updates `scrollToDay` onclick handlers.

**`applyAgendaToSchedule()`** — groups `_agendaBlocks` by day, sets numDays, day start/end, adds breaks for gaps ≥30 min (label "Lunch") or shorter (label "Break"). Calls `validateTimes()` only — NOT `validateTimesAndRecalc()` and NOT `calcMaxMatches()`.

**`calcMaxMatches()`** — simulates scheduling loop per day. Guards: `_safetyLimit=2000`, `ct < 0.5 → break`. Calls `_overlay.done('maxcycles')`, `updateAgendaFit()`, then `generateSchedule()`.

**`onCycleTimeChanged()`** — 1.2s debounced; calls `calcMaxMatches()` (if autoMaxCycles on) or `onParamChanged()`. Called by all cycle-time input events.

**`renderScheduleBars()`** — builds section bars from `window._frcScheduled`. Splits at breaks > `AGENDA_BREAK_THRESHOLD` (5 min). Stores `firstMatchNum` on each section. Day label calls `scrollToMatch(firstMatchNum)`.

**`scrollToMatch(N)`** — `output.scrollTop + row.getBoundingClientRect().top - output.getBoundingClientRect().top - 48`

**`ensureTbaSearchIndex()`** — fetches `/api/tba/events/{curYear}` + `/api/tba/events/{curYear+1}` in parallel. `localStorage` key `tba_idx_{curYear}`, TTL 6h. Called 5s after page load and on first cross-year search.

**`_overlay.show(title, steps)`** — must be called before `loadRoster()` in `activateEvent`. Steps built from enabled flags only.

---

## Auto Flags Persistence

Named booleans in URL and `day_config` JSON:

| Flag | Default | URL when non-default | day_config key |
|------|---------|---------------------|----------------|
| `autoPopulate` | true | `?autoPopulate=0` | `autoPopulate: bool` |
| `autoApplyAgenda` | true | `?autoApplyAgenda=0` | `autoApplyAgenda: bool` |
| `autoMaxCycles` | true | `?autoMaxCycles=0` | `autoMaxCycles: bool` |
| `autoAssign` | false | `?autoAssign=1` | `autoAssign: bool` |

`parseBoolFlag(name)` in `parseUrlParams()`: returns `true/false/null` (null = absent = keep default).

---

## Agenda Fit Bar Math

```
slotStart   = day.start (morning) or break.end (afternoon)
slotEnd     = break.start (morning) or day.end (afternoon)
effectiveEnd = slotEnd - (hasTrailingBreak ? breakBuffer : 0)
available    = effectiveEnd - slotStart
committed    = Σ max(0, min(m.endMin, effectiveEnd) - m.startMin)
fillPct      = committed / available * 100
```

`avgCt = committed / matchCount` — true weighted average, reflects actual cycle time changes.

`ctProgression` built from `cycle-change` entries in `_frcScheduled`: `firstMatch.endMin - firstMatch.startMin` gives starting ct; each `cc.newTime` appended if different from previous.

---

## Day Color Palette

```javascript
var _DAY_COLORS = [
  '#5b9bd5', // Day 1 — steel blue
  '#4aab8a', // Day 2 — teal green
  '#8b74c8', // Day 3 — violet
  '#c48b3a', // Day 4 — amber gold
  '#c05a6e', // Day 5 — rose crimson
  '#5a7fa8', // Day 6 — slate blue
  '#6a9455', // Day 7 — moss green
];
```

Defined at module level before `buildDaysUI`. Applied as:
- Bar fill: full color (or amber if >95% full)
- Bar track: `color + '22'` (~13% opacity tint)
- Day row background: `color + '14'` (~8% opacity)
- Day row border: `color + '50'` (~31% opacity)
- Day label text: full color

---

## PDF Parsing Format Variants

`normalizePDFText()` fixes: `fi` ligature, truncated AM/PM, fragmented time tokens.

`parseQualBlocks()` patterns:
- `qualRe` — standard with optional footnote markers, `~` on end time, en/em dash
- `qualNoSepRe` — Ontario two-column (anchored at line start)
- `qualBeginRe` — NC Begin/Continue with `openBeginBlock` state tracking
- `dayRe` — handles both `Month Day` and `M/D/YY` (Colorado)
- Block merge: gap ≤30 min → merge (Wisconsin field resets)
- Fallback: join all lines, retry with global regex

---

## OpenShift Deployment Notes

`04-deployment.yaml` key settings:
- `replicas: 2` with `topologySpreadConstraints` (one pod per node)
- `strategy: RollingUpdate` with `maxUnavailable: 0`
- `PodDisruptionBudget: minAvailable: 1`
- `CPU_WORKERS: "12"`, `WEB_WORKERS: "1"`
- `cpu request: "4"`, `cpu limit: "12"`
- `_gen_concurrency = max(2, CPU_WORKERS // 3)` — with `CPU_WORKERS=12`: `= 4` concurrent jobs per pod
- **8 concurrent user capacity:** 2 pods × 4 jobs = 8 simultaneous assignments; each job gets 3 workers → ~10s at full load

**8 concurrent user capacity:** 2 pods × 4 jobs = 8. Each job gets 3 workers → ~10s at 1000 iterations full load, ~5s at half load.

---

## Status Messages (auto chain)

| Step | Message |
|------|---------|
| Event load | `⏳ Loading team roster…` → `✓ Roster loaded — N teams` |
| PDF | `⏳ Fetching agenda PDF…` (in agenda panel) |
| Apply | `⏳ Applying agenda to day config…` |
| Max cycles | `⏳ Calculating max matches…` → `✓ Max N matches/team — ...` |
| Stage 1 | `⏳ Generating schedule…` + progress bar → `Stage 1 complete` |
| Auto-assign | `⏳ Auto-assigning teams…` |
| Stage 2 | progress bar with iterations/ETA/score |
| Done | `Teams assigned — review the schedule then click Commit to activate` |
