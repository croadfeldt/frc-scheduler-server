# FRC Match Scheduler — Placement Priorities & Technical Reference

## Match Placement Priorities (P1–P10)

These rules govern how teams are placed into match slots during abstract schedule generation (Stage 1). Rules are applied in priority order — higher priority rules are never violated to satisfy lower priority ones.

| Priority | Rule | Description |
|----------|------|-------------|
| P1 | No surrogate in last match | A surrogate team must not appear in the final match of the schedule |
| P2 | No surrogate in first match | A surrogate team must not appear in the first match of the schedule |
| P3 | Cooldown enforcement | A team must not play again within `cooldown` matches of their last appearance |
| P4 | Alliance balance | Each match must have exactly 3 red and 3 blue teams |
| P5 | No repeat opponents | Teams should not face the same opponent more than necessary |
| P6 | No repeat partners | Teams should not partner with the same team more than necessary |
| P7 | Surrogate placement | Surrogates must be clearly identified and placed in early-middle matches |
| P8 | Back-to-back minimisation | Minimise matches where a team plays consecutive matches |
| P9 | Imbalance minimisation | Minimise the difference between a team's red and blue appearances |
| P10 | Repeat minimisation | Minimise total repeat opponents and partners across the schedule |

---

## Surrogate Rules

When `numTeams × matchesPerTeam` is not evenly divisible by 6, some teams play one extra match as a "surrogate". Post-generation sweep rules:
- **R1:** No surrogate in first or last match — moved to early-middle by swapping with a regular team
- **R2:** Swap preserves alliance balance

---

## Break Buffer

`breakBuffer` (default 5 min, URL param `bb`) controls when to stop scheduling matches before a break.

**Rule:** Schedule a match if `breakStart - cursor >= breakBuffer`. The cycle time does not factor into this check — a match that clears the buffer is committed to run even if its cycle time overlaps the break start.

---

## Auto Flags

| Flag | ID | Default | Trigger |
|------|----|---------|---------|
| Regenerate on change | `autoPopulate` | ✅ On | Debounced Stage 1 on any param change (2.5s) |
| Apply PDF agenda to day config | `autoApplyAgenda` | ✅ On | `applyAgendaToSchedule()` on PDF parse success |
| Calculate max matches/team | `autoMaxCycles` | ✅ On | `calcMaxMatches()` after day config applied → writes matchesPerTeam → `generateSchedule()` |
| Assign teams after generation | `autoAssign` | ☐ Off | `assignTeams()` 200ms after Stage 1 completion |

**URL encoding:** Flags defaulting on are omitted when on, stored as `=0` when off. `autoAssign` (default off) stored as `=1` when on. `day_config` JSON stores named booleans (`autoPopulate`, `autoApplyAgenda`, `autoMaxCycles`, `autoAssign`).

**Precedence chain** (each step only runs if its flag is on):
```
1. PDF fetch → applyAgendaToSchedule()   [autoApplyAgenda]
2. → calcMaxMatches()                    [autoMaxCycles]
3. → generateSchedule()                  [autoPopulate]
4. → assignTeams()                       [autoAssign]
```

**`onCycleTimeChanged()`** — all cycle-time inputs (start-of-day and after-match rows) call this instead of `onParamChanged()`. Applies a 1.2s debounce then calls `calcMaxMatches()` if `autoMaxCycles` is on, bypassing the plain 2.5s debounce. Prevents mid-keystroke fires that caused infinite loops.

**`calcMaxMatches()` safety guards** — the simulation loop has a `_safetyLimit = 2000` iteration cap and a `ct < 0.5 → break` guard. Without these, a blank or zero cycle-time field (e.g. mid-keystroke) causes an infinite loop that permanently hangs the browser tab.

---

## Day Break (Early End)

A per-day match count limit that stops scheduling after N matches on a given day, **without changing the day's configured time slot**. Used when a non-time event (field reset, awards, etc.) ends match play early.

**UI:** `+ Add Day Break (stop scheduling)` button on each day row. Single field: "Stop scheduling after match # on this day". Only one day break per day (adding a second replaces the first).

**Effect:**
- `calcMaxMatches` stops counting slots when `dayMatchCount >= earlyEnd`
- `_finishGenerationInner` breaks the placement loop when `dayMatchCount >= day.earlyEnd`
- Day start/end times are **unchanged** — agenda fit shows the full time slot as available
- Committed match time in the fill bar is naturally reduced, reflecting the shorter session

**Persistence:**
- `collectDayConfig` saves `earlyEnd` per day in `day_config` JSON → DB
- `applyDayConfigToUI` restores it via `addDayEarlyEnd(row, day.earlyEnd)`
- URL encoded as `d1e=44`, `d2e=38` etc.; decoded in `parseUrlParams`
- `applyUrlParams` restores via `addDayEarlyEnd(row, day.earlyEnd)`

---

## Page Load Performance

**API calls on first load (sequential):**
1. `loadEvents()` → `GET /api/events` — local DB, fast
2. `initAuth()` → `GET /auth/me` — validates JWT against DB

**Deferred:**
- `fetchTbaDropdown()` — deferred to first focus on the event code input (was 800ms eager)
- `ensureTbaSearchIndex()` — deferred 5s; uses `localStorage` cache (`tba_idx_{year}`, 6h TTL)
- `GET /api/health` — deferred 2s (only needed for overlay CPU count display)

**Diagnosis:** `apiFetch()` logs `[api] METHOD /path Nms STATUS` to the browser console on every call. Open DevTools → Console on first page load to see exact timing for each call.

**`_agendaFetchPending` flag** — set in `activateEvent` before async work begins, cleared in `.finally()`. `onParamChanged()` returns early when this is true, preventing debounced generation from racing the PDF chain.

**`applyAgendaToSchedule()` does NOT call `calcMaxMatches()`** — the chain in `fetchAndRenderAgendaFit` is the sole orchestrator. This prevents the double-`calcMaxMatches` bug that caused generation to abort.

---

## Processing Overlay (`_overlay`)

IIFE module. Shown automatically during the auto chain on event load. Only fires for auto-chain operations — manual button clicks do not trigger it.

Methods: `show(title, steps)`, `step(id, detail)`, `done(id)`, `error(id, msg)`, `hide()`, `isVisible()`

Steps shown = only enabled flags. Order: `roster → pdf → apply → maxcycles → generate → assign`

**`hide()` is called from three places:**
1. After `assignTeams()` completes (full chain done)
2. After Stage 1 completes when `autoAssign` is off
3. In PDF fail path when neither `autoMaxCycles` nor `autoPopulate` are on

The overlay is shown and `roster` stepped **before** `loadRoster()` is called so timing is correct.

---

## Agenda Fit — Section Bars

Built from `window._frcScheduled` (actual generated schedule), not from PDF blocks.

**Section definition:** contiguous match play split at breaks > 5 minutes (`AGENDA_BREAK_THRESHOLD`). Short breaks (≤5 min) appear as tick marks inside the bar.

**Per section:**
- `slotStart` = day start (or break end for afternoon sessions) — from `day.start` stored on `_frcScheduled` entries
- `slotEnd` = break start (for sessions with trailing break) or day end
- `available` = `slotEnd - slotStart - (hasTrailingBreak ? breakBuffer : 0)`
- `committed` = sum of `min(m.endMin, effectiveEnd) - m.startMin` per match (caps at break buffer boundary)
- `fillPct` = `committed / available * 100`
- `fillColor` = day color from `_DAY_COLORS`; amber if >95% or over
- `avgCt` = `committed / matchCount` (true weighted average)
- `ctProgression` = from `cycle-change` entries: e.g. `9→8 min/match`

**Day label** in section header uses `scrollToMatch(firstMatchNum)` — scrolls to the first match of that session, not just the top of the day. Falls back to `scrollToDay(dayNum)` if no schedule is loaded.

**Summary stats** use `_availFromDayConfig()` — reads day rows directly for available time, independent of whether a schedule exists.

**Day color palette** (`_DAY_COLORS` — module-level constant, defined before `buildDaysUI`):

| Day | Hex | Color |
|-----|-----|-------|
| 1 | `#5b9bd5` | Steel blue |
| 2 | `#4aab8a` | Teal green |
| 3 | `#8b74c8` | Violet |
| 4 | `#c48b3a` | Amber gold |
| 5 | `#c05a6e` | Rose crimson |
| 6 | `#5a7fa8` | Slate blue |
| 7 | `#6a9455` | Moss green |

Same colors applied to day row backgrounds (8% opacity tint, 31% opacity border) in the Daily Schedule section.

---

## Stage 2 — Incremental Scoring SA

`assign_teams()` in `scheduler.py`:

**`build_score_state(slot_map)`** — full O(matches²) rescore. Called once per iteration start. Returns `(score, b2b, opp, par, rc, bc, tbm)`.

**`delta_swap(slot_map, sa, sb, ...)`** — incremental delta for a 2-swap. Only rescores matches containing slot `sa` or `sb` (~10-20 matches vs all 88). Returns score delta. State rebuild only on accepted moves.

- Budget: `num_teams` steps/iteration
- `T0 = 500`, linear cooling; accept worse when `exp(Δ/T)` and `Δ/T > -10`
- Performance: ~30ms/iter (vs 80ms with full rescore)

**`_gen_concurrency = max(2, CPU_WORKERS // 3)`** — limits simultaneous jobs so each gets ≥3 workers.

---

## PDF Parsing

`normalizePDFText(text)` pre-processes before `parseQualBlocks(text)`:
- Repairs `fi` ligature splits (`Qualifi cation` → `Qualification`)
- Repairs truncated AM/PM (`12:30P` → `12:30PM`)
- Collapses fragmented time tokens from PDF.js character spacing

`parseQualBlocks(text)` handles format variants:
- **Standard / Peachtree / Chesapeake:** optional footnote markers, `~` on end time
- **Ontario:** two-column no-separator format
- **North Carolina:** start-time-only `Begin/Continue` keywords with open-block tracking
- **Colorado:** numeric date format `Friday, 4/10/26`
- **Fallback:** joins all lines and retries with global regex
- **Block merging:** consecutive blocks with gap ≤30 min are merged (Wisconsin brief field resets)

---

## TBA Search Index

- **Client pre-fetch:** current year + next year via `Promise.allSettled([/api/tba/events/Y, /api/tba/events/Y+1])`, deferred 5s after load
- **`localStorage` cache:** key `tba_idx_{year}`, TTL 6 hours — second page load is instant
- **Server cache:** `/api/tba/search_index` caches in `app.state` for 6 hours (available for direct API use)
- **Prior years:** not pre-loaded. User changes the year field; `fetchTbaDropdown()` fetches on demand. Warning shown in status area when year < current year. Dropdown hint links to year field.

---

## URL Parameters

| Param | Example | Description |
|-------|---------|-------------|
| `n` | `51` | Number of teams |
| `mpt` | `11` | Matches per team |
| `cd` | `3` | Cooldown |
| `ct` | `8` | Default cycle time (min) |
| `days` | `2` | Competition days |
| `seed` | `a1b2c3d4` | Stage 1 hex seed |
| `aseed` | `cafebabe` | Stage 2 hex seed |
| `teams` | `254,1114` | Team numbers in slot order |
| `d1`–`d5` | `09:00-18:00` | Per-day start–end |
| `d1b`–`d5b` | `Lunch\|12:00\|13:00` | Per-day breaks |
| `cc` | `1:45:7.5` | Cycle changes: Day:AfterMatch:Time |
| `bb` | `5` | Break buffer minutes |
| `autoPopulate` | *(omitted)* | Omitted=on; `=0`=off |
| `autoApplyAgenda` | *(omitted)* | Omitted=on; `=0`=off |
| `autoMaxCycles` | *(omitted)* | Omitted=on; `=0`=off |
| `autoAssign` | *(omitted)* | Omitted=off; `=1`=on |
| `sid` | `16` | Restore abstract schedule from DB |
| `aid` | `7` | Restore assigned schedule from DB |
| `event` | `2026wasno` | Event key to auto-load |

**Restore priority:** `?aid=` → `?sid=` → `?seed=`
