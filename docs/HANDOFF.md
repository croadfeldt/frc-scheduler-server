# HANDOFF

State of the world for the next person picking up the FRC Match Scheduler
project. Practical, terse, code-anchored — same convention as the rest of
`docs/`. Read this first if you're new to the codebase or coming back
after a gap.

Last updated: 2026-05-08, end of the View UX Overhaul session.

---

## 1 · Where we are

The V2 day_config migration is **done through phase 5c** plus a follow-on
**View UX Overhaul** (status pills, field-position alliance layout,
unified agenda fit bar, source-aware row tints).

| Phase | Status | Notes |
|-------|--------|-------|
| 0 — specs ratified                           | ✓ | Phase gate met. |
| 1 — backend V2 native                        | ✓ | POST/PATCH validate, GET normalize. |
| 2 — DB migration applied                     | ✓ | All rows V2-shape. |
| 3 — V1 toggle removed + V1 markup deleted    | ✓ | Two stages, both done. |
| 4 — V2 URL emit/parse                        | ✓ | 36 tests. V1 back-compat parse retained. |
| 5 — V1 helpers deleted                       | ✓ | ~870 lines gone. |
| 5b — renames + view-page color fix           | ✓ | |
| 5c — V2-native qual scheduler                | ✓ | `_v2BuildQualPlan` + V1 fallback branch. |
| **VUX — View UX overhaul (post-roadmap)**    | ✓* | See §3 below. *Pending live verification. |

The `docs/V2_ROADMAP.md` document tracks phases 0–5c. The View UX
overhaul isn't part of the V2 roadmap proper — it's a UX polish pass
that piggybacks on the V2 plumbing now that all data flows through
the unified pipeline.

---

## 2 · Architecture snapshot

```
                ┌──────────────┐
                │   Editor     │  static/index.html (~17,113 lines)
                │  (V2 native) │  collectDayConfigV2 → POST /api/schedules
                └───────┬──────┘
                        │ V2 wire shape
                        ▼
                ┌──────────────┐
                │   Backend    │  app/*.py (FastAPI, Pydantic V2 models)
                │  (V2 native) │  app/day_config_v2.py is canonical
                └───────┬──────┘
                        │ V2 wire shape
                        ▼
                ┌──────────────┐
                │   Postgres   │  All rows V2-shape post-phase-2
                └───────┬──────┘
                        │
                        ▼
                ┌──────────────┐
                │  View page   │  static/view.html (~7,957 lines)
                │  V2 → V1     │  _v2DowngradeToV1ForView() shim, then
                │  shim layer  │  legacy renderers consume V1 shape
                └──────────────┘
```

**Why the shim survives:** the view-page renderers were never
rewritten for V2-native consumption — they read V1 shape. Rather than
rewrite ~3000 lines of viewer rendering code, we run a one-shot
downgrade at load time. This keeps the seam clean: backend & editor
are V2-native, view is V1-native with a V2 adapter at the boundary.

The downgrade is **lossy by design** for fields the view doesn't use,
but preserves everything the view renders (rosters, timing, breaks,
playoff blocks, subtypes for break colors). The reverse direction
(V1 → V2) does NOT exist anywhere — the editor never round-trips
through V1. That asymmetry is intentional.

---

## 3 · View UX overhaul (current session, mostly done)

The view page got a substantial UX update. All implemented in
`static/view.html`. Snapshot of what changed:

### 3.1 Schedule-table row tints

Was: yellow / orange row tints driven by direct `STATE.liveByMatch`
reads in the renderer.

Now: green / amber / purple, driven by `_findFieldThreeUp()` (the
same source the 3-up status grid uses). Three states tracked:

| Class                 | Color                | Meaning                             |
|-----------------------|----------------------|-------------------------------------|
| `tr.current-match`    | green `#639922`      | Match is on the field.              |
| `tr.upcoming-match`   | amber `#BA7517`      | Match is on deck (next up).         |
| `tr.queueing-match`   | purple `#7F77DD`     | Match is queueing (after on-deck).  |
| `tr.estimated`        | (modifier)           | Source is `'scheduled'`, not live.  |

Estimated rows get:
- Tint alpha dropped 18% → 10%
- `box-shadow` left bar replaced with `border-left: 4px dashed`
- Field-state pill switches from solid → hollow

### 3.2 Field-state pills

Inline next to the match number in the schedule table. Distinct from
the existing `.queue-pill` (which is per-match Nexus `queue_status`)
— field-state pills only render on the three field-relevant rows.

| Class                       | Solid bg / text       |
|-----------------------------|-----------------------|
| `.field-pill-on-field`      | `#4d8b1a` / `#fff`    |
| `.field-pill-on-deck`       | `#c66800` / `#fff`    |
| `.field-pill-queueing`      | `#5d4ec9` / `#fff`    |
| `.field-pill.estimated`     | transparent / colored |

Dark-mode hollow pills lighten the text color so it reads against the
dark surrounding surface.

### 3.3 Live-status source banner

`<div id="statusSourceBanner">` between the match-table-header and
the match table. Three states:

| State         | Visible | Text                                                     |
|---------------|---------|----------------------------------------------------------|
| `live`        | yes     | "Live status from Nexus / TBA — confirmed by feed."      |
| `estimated`   | yes     | "Status estimated from the schedule — no live data yet." |
| (none)        | hidden  | When `_findFieldThreeUp()` returns no field/deck/queueing. |

Populated post-render, after the table is in the DOM, in the
`renderTable()` flow.

### 3.4 Pre-event guard on `_findFieldThreeUp()`

Was: the scheduled fallback walked all matches with no date or time
gating. Result: 3-up grid + table tints lit up days before the event.

Now (the scheduled-only branch — Nexus/TBA paths bypass these):

1. **Active-day filter.** Only matches whose `entry.date` matches
   today's `YYYY-MM-DD` get into the candidate pool. Entries without
   a date attribute stay eligible (old saves / fresh local
   schedules), with the timestamp guard below as the safety net.

2. **15-min pre-start window.** The earliest candidate must start
   within 15 minutes (or already be past its scheduled start with no
   live confirmation). Outside that window the function returns
   `{ field: null, deck: null, queueing: null, source: null }`.

Live data (Nexus / TBA actuals) overrides both gates — those branches
return earlier with `source: 'nexus'`.

### 3.5 Field-position alliance layout

`_buildAllianceFieldHtml(entry, opts)` — top-down field view:

```
Blue stack (left wall)              Red stack (right wall)
┌────────────────┐                  ┌────────────────┐
│ ¹ 3633         │                  │         3082 ³ │   top
├────────────────┤                  ├────────────────┤
│ ² 5172         │     [ field ]    │         4198 ² │
├────────────────┤                  ├────────────────┤
│ ³ 7137         │                  │         6162 ¹ │   bottom
└────────────────┘                  └────────────────┘
                  ━━━━━━━━━━━━━━━━━━
                    scoring table
```

Stations follow the "1, 2, 3 left to right from driver POV" rule:
blue 1→3 reads top-to-bottom; red 3→1 reads top-to-bottom (red driver
faces left, mirror across centerline). B3 and R1 sit at the
table-side end.

Companion to `_buildAllianceLineHtml` (linear blue-vs-red layout).
Picked at runtime via `_allianceHtmlForMode()` based on
`localStorage['frc_field_view_mode']` (`'linear'` or `'field'`).

Station label = digit-only superscript with 8-direction white
text-shadow ring. Just the digit — alliance color carries the B/R.

### 3.6 Field/linear view toggle

Toggle button **lives in the match-table-actions toolbar** (next to
Print/Export, QR, theme toggle). Always visible — does NOT hide
pre-event. Persists to `localStorage['frc_field_view_mode']`.

`toggleFieldView()` flips the preference, calls
`_updateFieldViewToggleLabel()`, then triggers a full `rerender()`
so all four alliance-rendering surfaces refresh:

1. 3-up status grid cells
2. Team-card next-match alliance roster
3. Next-only fallback alliance line
4. Any future caller using `_allianceHtmlForMode()`

### 3.7 Unified agenda fit bar

Match-segment label now matches the editor's two-line format:

```
   12 matches            ← line1, always visible
 22/35 min · 9→8 min     ← line2, shown when widthPct >= 14%
```

Cycle progression auto-derived by walking `seg.entries` and
collecting distinct `endMin - startMin` values in order.

Bar height bumped 36px → 38px to match the editor.

Day-head structure aligned with editor's `renderScheduleBars`:

- Clickable colored day label (practice green / qual blue) that
  scrolls to the first match of the day.
- Inline date label via `formatDateLabel(d.date)`.
- Window time range in muted text.
- Right-justified summary stats.

### 3.8 Agenda legend additions

Legend in the agenda fit panel gained:

- Awards (`#d9a13e`)
- Alliance selection (`#3fa6a0`)
- Ceremony (`#dd7858`)
- Playoff (`#bd92f0`)

Plus existing: Matches, Practice, Breaks, Unallocated, Elapsed, Now,
Selected team.

### 3.9 8T → 8A label

Playoff alliance count label changed from `8T` to `8A` everywhere
in the view's agenda bar (inline label and tooltip). Editor already
used "Alliance" — verified.

---

## 4 · Bug fixes from the live-test feedback round

User reported four issues after seeing the deployed code in production.
All four addressed in this session:

### 4.1 Practice cycleTime discrepancy (10 min in editor → 9 min in view)

**Root cause:** `_v2DowngradeToV1ForView` emits `practiceDay.ct`
(canonical V1 field name). The view's renderer at line ~3344 was
reading `pday.cycleTime` (the V2 field name). Mismatch → fallback
to `cfg.practiceCycleTime || 9`.

**Fix:** renderer now reads `pday.ct || pday.cycleTime ||
cfg.practiceCycleTime || 9`. V1 field wins, V2 alias kept as
back-compat for any renderer caller that bypasses the downgrade.

### 4.2 Pre-event status rows showing days early

**Root cause:** `_findFieldThreeUp()` scheduled fallback walked all
matches with no date/time gating. Day 1 + Day 2 of an event 8 days
out got marked as on-field / on-deck / queueing.

**Fix:** active-day filter + 15-minute pre-start window in the
scheduled-only branch. See §3.4.

### 4.3 Field-view toggle invisible pre-event

**Root cause:** the toggle button was inside `status-three-up-wrap`,
which has `display: none` until `_renderFieldThreeUp()` finds a
field/deck/queueing match. Pre-event the wrap stayed hidden, so the
toggle was unreachable.

**Fix:** moved the button to the always-visible
`match-table-actions` toolbar. Uses `.btn .btn-secondary` styling
consistent with the theme and Print/Export buttons.

### 4.4 Agenda bar consistency edit ↔ view

**Partial fix this session:**

- View's day-head now mirrors editor's `renderScheduleBars` head
  structure: clickable colored label, inline date label, window
  time, summary with `<strong>` highlights.
- View's match-segment color hardcoded to `#5daf78` / `--blue-alliance`
  to match editor's hardcoded `#5daf78` / `var(--accent)` exactly.

**Not yet aligned (open issue):**

- Editor's `renderScheduleBars` uses `dayColor()` to give each day
  its own color from a palette. View uses the same blue across all
  days. Question for the next round: should editor adopt view's
  uniform color, or should view adopt editor's per-day cycling?
  Direction unclear from the user's "use the colors from the page,
  but the initialization and other info from the edit page" — could
  be read either way.

---

## 5 · Open items

### 5.1 Needs live verification

- All four fixes from §4 — practice CT, pre-event guard, toggle
  placement, day-head alignment.
- 3-up grid and table behavior across all four `_findFieldThreeUp()`
  outcomes:
  - Nexus queue_status flowing → solid pills, full tints.
  - TBA actuals only (no Nexus queue) → next-only fallback.
  - Pre-event clock-only, > 15 min out → no rows marked, banner hidden.
  - Pre-event clock-only, < 15 min out → hollow pills, faint tints.

### 5.2 Confirm view loads ACTIVE schedule

User raised this in the same feedback round. Practice CT discrepancy
was symptomatic — the field-name fix probably resolves it — but the
underlying confirm is still pending. Worth checking the view's load
path (`/api/schedules/{id}` → STATE.schedule) and Cache-Control
headers to make sure the user isn't hitting a stale CDN copy.

### 5.3 Editor agenda bar color decision

See §4.4 above. Three options:

1. Editor adopts view's single-color approach. Day distinction comes
   from the day label + date.
2. View adopts editor's per-day color cycling. Days visually
   distinguished even at a glance.
3. Status quo. Document the divergence as intentional (editor =
   "designing", view = "viewing").

Need user input before making the call.

### 5.4 Optional V2-native cleanups (out of scope, tracked)

- `_v2BuildSchedulerInput` is still load-bearing for `getPracticeConfig`
  + `collectDayConfig` save/load paths. Could rewrite those callers
  V2-native; would let us delete the V1-shape transform entirely.
  Deferred since the current path works and the win is purely
  internal.

### 5.5 Roadmap update

`docs/V2_ROADMAP.md` doesn't include the View UX overhaul. Should
add a "Phase 6 — View UX" section documenting the status pills,
field-position layout, source banner, and the four fixes above.
Low priority but worth doing before the next major workstream.

---

## 6 · Code locations (verbatim)

### `static/view.html` (~7,957 lines)

| Function / DOM                                              | Line   |
|-------------------------------------------------------------|--------|
| `_v2DowngradeToV1ForView`                                   | ~2665  |
| `_v2BlockToV1Break`                                         | ~2687  |
| `_v2DowngradeToV1ForView` practiceDay emit (`ct:` field)    | ~3036  |
| Practice CT renderer read (`pday.ct \|\| pday.cycleTime`)   | ~3344  |
| `renderAgendaFitView` entry                                 | ~4072  |
| Match-segment two-line label render                         | ~4350  |
| Day-head with clickable colored label                       | ~4524  |
| `_findFieldThreeUp` (with active-day + 15-min guard)        | ~5341  |
| `_renderFieldThreeUp`                                       | ~5470  |
| `_buildAllianceFieldHtml`                                   | ~6045  |
| `_buildAllianceLineHtml`                                    | ~6155  |
| `_allianceHtmlForMode` (dispatcher)                         | ~6178  |
| `toggleFieldView`                                           | ~6101  |
| `_updateFieldViewToggleLabel`                               | ~6113  |
| `<div id="statusSourceBanner">`                             | ~2127  |
| `<button id="btnFieldViewToggle">` (toolbar)                | ~2330  |
| `<div id="statusThreeUpWrap">` (no header inside)           | ~2192  |

### `static/index.html` (~17,113 lines)

| Function / DOM                                              | Line   |
|-------------------------------------------------------------|--------|
| `_v2BuildQualPlan`                                          | ~12273 |
| `_v2BuildSchedulerInput`                                    | ~11874 |
| `_v2dayCycleChanges`                                        | ~12207 |
| `_v2blockChangesToV1` (single-block shim)                   | ~12238 |
| `_finishGenerationInner`                                    | ~14420 |
| `getPracticeConfig` (reads `pd.ct` correctly)               | ~7702  |
| `renderScheduleBars`                                        | ~6657  |
| `dayColor` (per-day palette cycling)                        | ~6666  |

### `app/day_config_v2.py`

`downgrade_v2_to_v1` mirrors phase 5c per-block cycleTime + synthetic
gap breaks. Companion to view's `_v2DowngradeToV1ForView` for any
backend code path that needs V1 shape.

### Tests

| File                                        | Count       | Runner   |
|---------------------------------------------|-------------|----------|
| `tests/test_v2_url.js`                      | 36 tests    | node     |
| `tests/test_v2_scheduler_input.js`          | 20 tests    | node     |
| `tests/test_day_config_v2.py`               | 31 tests    | python   |
| `tests/test_migration_script.py`            | 7 tests     | python   |

All four green as of this commit.

---

## 7 · Operational knowledge

Things the next person will trip over if they don't know.

### 7.1 Field-name dance: practice cycle time

- V2 native: block has `cycleTime` field.
- V1 canonical (used by view's renderer + editor's `getPracticeConfig`):
  `practiceDay.ct`.
- The view's `_v2DowngradeToV1ForView` emits `ct:` (correct V1).
- View's renderer reads `pday.ct || pday.cycleTime || cfg.practiceCycleTime || 9`
  for forward + back compat.

If you're adding a new consumer of `practiceDay.cycleTime` somewhere,
prefer reading both names.

### 7.2 `fieldSource === 'nexus'` covers TBA too

`_findFieldThreeUp()` returns `source: 'nexus'` whenever it found data
via the Nexus `queue_status` path **or** the TBA `actual_time && !post_result_time`
fallback. There's no separate `'tba'` value — both upstream live
sources collapse into the `'nexus'` bucket.

If you need to distinguish them in the future (e.g. to show different
banner text for TBA-only), split the source field into
`'nexus' | 'tba' | 'scheduled'` and update the banner +
estimated-modifier callers.

### 7.3 Pre-event guard timing

The 15-minute window is hardcoded as `WINDOW_MS = 15 * 60 * 1000`
in `_findFieldThreeUp()`. If the event organizer wants more lead
time (say, 30 min), this is the single knob.

`todayStr` is computed from local Date, not from the schedule's
event timezone. If the user is viewing the schedule from a different
timezone than the event, the active-day filter may misfire. Worth
revisiting if it bites — would need to plumb the event timezone into
the function.

### 7.4 V2 palette colors (canonical)

| Block subtype       | Hex       | Used in                         |
|---------------------|-----------|----------------------------------|
| `practice`          | `#5daf78` | match seg + practice day-head    |
| `qualification`     | (`--blue-alliance`) `#0969da` light / `#58a6ff` dark | match seg + qual day-head |
| `playoff`           | `#bd92f0` | playoff segments + agenda inset  |
| `break` (default)   | `#ec8a3f` | unsubtyped breaks                |
| `awards`            | `#d9a13e` | awards subtype                   |
| `alliance_selection`| `#3fa6a0` | alliance selection subtype       |
| `ceremony`          | `#dd7858` | opening / closing ceremonies     |

Status pill colors (different palette — these are interactive signals):

| State    | Hex       |
|----------|-----------|
| On field | `#4d8b1a` |
| On deck  | `#c66800` |
| Queueing | `#5d4ec9` |

### 7.5 localStorage keys

| Key                       | Values                | Default       |
|---------------------------|------------------------|---------------|
| `frcDayConfigUseV2`       | `'1'`                  | `'1'` (toggle retired) |
| `frc_field_view_mode`     | `'linear'` / `'field'` | `'linear'`    |
| `frc_view_theme`          | `'light'` / `'dark'`   | `'light'`     |
| `frcUse24h`               | `'1'` / `'0'`          | `'0'` (12h)   |
| `frc_theme` (editor)      | palette index          | `'dark'`      |

### 7.6 Container WORKDIR

`/app`. The OpenShift deployment expects all paths (static files,
app code, migrations) rooted at `/app/...`. If you're running locally
in a different layout, the `apply.sh` script handles the path mapping.

### 7.7 Network allowlist for `bash_tool`

Only these domains are reachable from this sandbox:
`api.anthropic.com, archive.ubuntu.com, crates.io, files.pythonhosted.org,
github.com, index.crates.io, npmjs.com, npmjs.org, pypi.org, pythonhosted.org,
registry.npmjs.org, registry.yarnpkg.com, security.ubuntu.com,
static.crates.io, www.npmjs.com, www.npmjs.org, yarnpkg.com`.

If you need to add a dependency from a different host, you'll get a
clear `x-deny-reason` header and have to ask the user to update the
sandbox config. Tests don't need network access — they're all local.

---

## 8 · Deploy

Standard flow:

```bash
cd ~/git/frc-scheduler-server
git pull && git add -A
git commit -m "<message>"
git push
./openshift/apply.sh
```

The `apply.sh` script handles the OpenShift rollout. It tags the
commit, builds the container, pushes to the registry, and triggers
a rolling deploy. No manual step on the cluster side.

Pod label `app=frc-scheduler-server-git`. Postgres pod label
`app=frc-postgres`. Hostname `frc-scheduler.roadfeldt.com`.

DB name `frc_scheduler`, event key `2026mnst`, event_id `4`,
team count 36 (MSHSL).

---

## 9 · Reproduction prompt

If you're an AI coming into this project cold, the
`docs/REPRODUCTION_PROMPT.md` document is the standard onboarding
context. Pair it with this handoff for the most up-to-date picture.

`REPRODUCTION_PROMPT.md` covers the project goals + structure +
constraints. This document covers what was just done + what's
pending. They're complementary, not redundant.

---

## 10 · TL;DR

If you're reading this and have to pick up tomorrow:

1. **Verify** the four fixes from §4 in production. Most likely all
   working, but live confirmation matters.
2. **Decide** on the editor agenda bar color question (§5.3) and
   apply the chosen direction.
3. **Update** `docs/V2_ROADMAP.md` to include "Phase 6 — View UX"
   summarizing this session's work.
4. **Repackage** if you've made code changes — current build is in
   `/mnt/user-data/outputs/frc-scheduler-server.tgz`.

That's it. The code is in good shape, all tests pass, the architecture
is clean. The next work is polish and verification, not structural.
