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

When `numTeams × matchesPerTeam` is not evenly divisible by 6 (teams per match), some teams play one extra match as a "surrogate". Surrogate teams are identified during abstract schedule generation.

Post-generation sweep rules (applied after Stage 1 completes):
- **R1:** No surrogate in first or last match — surrogates are moved to an early-middle position by swapping with a regular team
- **R2:** Surrogate swap preserves alliance balance — the swap must not create an imbalanced match

---

## Break Buffer

`breakBuffer` (default 5 min, URL param `bb`) controls when to stop scheduling matches before a break or end of day.

**Rule:** Schedule a match if its start time is at least `breakBuffer` minutes before the break:
```
breakStart - cursor >= breakBuffer
```

The cycle time does **not** factor into this check. A match that clears the buffer is committed to run even if its cycle time overlaps the break start.

---

## Agenda Fit (from frc-schedule-builder)

Integrated from [github.com/phil-lopreiato/frc-schedule-builder](https://github.com/phil-lopreiato/frc-schedule-builder).

### PDF.js
Loaded lazily via injected `<script type="module">` (`loadPdfJs()`). CDN: `cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379`. Deduped via `_pdfjsLoading` promise.

### PDF source
```
https://info.firstinspires.org/hubfs/web/event/frc/{year}/{YEAR}_{EVENTCODE}_Agenda.pdf
```

Times in FIRST agenda PDFs are local event time — no timezone information is present or needed.

### Fit metrics

| Metric | Formula |
|--------|---------|
| Total matches needed | `ceil(teams × mpt / 6)` |
| Surrogates | `totalMatches × 6 − teams × mpt` |
| Time needed | `totalMatches × cycleTime` |
| Time available | Sum of parsed qual block durations |
| Buffer / Overflow | `available − needed` |
| Capacity % | `needed / available × 100` |
| Matches / Hour | `60 / cycleTime` |
| Max cycle to fit | `available / totalMatches` |

**Status thresholds:** ✓ Comfortable (≤85%) / ⚠ Tight (≤100%) / ✗ Over Capacity (>100%)

### Auto flags

| Flag | ID | Default | Trigger |
|------|----|---------|---------|
| Auto-apply PDF agenda | `autoPopulate` | ✅ On | Debounced Stage 1 regeneration on param change (1.5s debounce) |
| `autoApplyAgenda` | ✅ On | Calls `applyAgendaToSchedule()` automatically after successful PDF parse |
| Auto-calculate max matches/team | `autoMaxCycles` | ☐ Off | Calls `calcMaxMatches()` after day config is applied (auto or manual) |

### Apply to Day Configuration

`applyAgendaToSchedule()` algorithm:
1. Group `_agendaBlocks` by `b.day` label → `dayMap` / `dayOrder`
2. Set `numDays` and call `buildDaysUI()`
3. Per day: `.day-start` = `min(block.start)`, `.day-end` = `max(block.end)`
4. Gaps between consecutive blocks → `addBreak()` calls (label = "Lunch" if ≥30 min, "Break" otherwise)
5. Call `applyDayEndTimes()` then `validateTimesAndRecalc()`
6. If `autoMaxCycles` on → call `calcMaxMatches()`

---

## Day/Night Mode

`[data-theme="light"]` attribute on `<html>` overrides all CSS custom properties to light palette values. `toggleTheme()` sets/clears the attribute and updates the 🌙/☀️ button. `initTheme()` IIFE reads `localStorage.getItem('frc_theme')` on load and applies preference before first render. Default: dark (Catppuccin Mocha).

---

## TBA Event Dropdown

- Year-specific fetch: `GET /api/tba/events/{year}` — events sorted by `start_date` ascending in `tba.py`; no row cap
- Cross-year fallback: when `visibleCount < 3 && query.length >= 2`, augments dropdown from `_tbaSearchIndex` (TBA global search index, all years) under "Other years" separator
- Search index pre-fetched 2s after page load via `ensureTbaSearchIndex()`
- Source badges: `TBA` (blue `var(--accent)`) / `FRC` (green `var(--accent3)`)
- FRC Events credential errors surfaced immediately in `showApiStatus` (not hidden in dropdown)

---


### Auto-trigger implementation notes

**`_agendaFetchPending` flag** — set `true` in `activateEvent` before the PDF fetch, cleared in `.finally()`. Prevents `loadRoster()` from calling `onParamChanged()` prematurely before the PDF day config is applied, which would cause a double-generate race condition.

**`loadRoster()`** — calls `onParamChanged()` only when `!window._agendaFetchPending`. Covers the no-event-key case (no PDF fetch pending).

**Day section `input` events** — all cycle time and break fields in the day section now call `onParamChanged()` on both `input` (keystroke) and `change` (blur). Previously only `change` fired `onParamChanged()`, so edits weren't picked up until the user tabbed away. The 2.5s debounce absorbs rapid typing.

**`generateSchedule()`** — shows `⏳ Generating schedule…` in `showApiStatus()` immediately on entry, before the SSE stream begins.

**`fetchAndRenderAgendaFit` calls `generateSchedule()` directly** after PDF processing — not via `onParamChanged()` debounce. `applyAgendaToSchedule()` uses `validateTimes()` (not `validateTimesAndRecalc()`) to avoid queuing a spurious debounce alongside the direct call.

**Full trigger chain on event load:**
```
activateEvent → _agendaFetchPending=true → loadRoster (holds) → fetchAndRenderAgendaFit
  PDF success + autoApplyAgenda → applyAgendaToSchedule
    autoMaxCycles on  → calcMaxMatches → generateSchedule  [status shown]
    autoMaxCycles off → onParamChanged → debounced generateSchedule (if autoPopulate on)
  PDF fail → onParamChanged → debounced generateSchedule (if autoPopulate on)
  .finally → _agendaFetchPending=false
```
## Stage 2 Simulated Annealing

`assign_teams()` in `scheduler.py`:
- Budget: `num_teams × 2` steps per iteration (matches old hill-climber)
- `T0 = 500`, linear cooling
- 2-swap moves; accept worse when `exp(Δ/T)` and `Δ/T > -10`
- Score: `-(b2b×1000 + imbalance×500 + surrogates×200 + repeat_opp×15 + repeat_part×12)`
- ~90ms/iter per worker; best result across all workers kept

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
| `sid` | `16` | Restore abstract schedule from DB |
| `aid` | `7` | Restore assigned schedule from DB |
| `event` | `2026wasno` | Event key to auto-load |

**Restore priority:** `?aid=` → `?sid=` → `?seed=`
