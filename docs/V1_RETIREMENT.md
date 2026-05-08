# V1 retirement plan

**Status:** active. Goal — remove V1 day_config entirely from the
editor, the URL parameter shape, and the database.

The V1 model represents a day as `(start, end, breaks[],
cycleChanges[])` — a single match-window with breaks. It cannot
represent multiple match blocks per day, type-aware ceremonies, or
per-block cycle times (see [V2_SPEC.md](V2_SPEC.md) §1). V2 has
been the editor's source of truth for several months, but V1 still
exists in three places that produce the recurring "V1 markup is
stale because V2 is the truth" bug class:

1. The V1 form-field DOM (still rendered, still read by some paths).
2. The URL parameter format (`d1=HH:MM-HH:MM`, `d1b=…`, `cc=…`).
3. The database (`day_config` columns store V1-shape downgrades).

This doc inventories every V1-coupled site in the codebase and gives
each one a kill order.

---

## Phase plan (high-level)

| Phase | What changes                                                               | Risk to user data            |
|-------|----------------------------------------------------------------------------|------------------------------|
| 0     | This doc + [V2_SPEC.md](V2_SPEC.md) ratified                                | None                         |
| 1     | Backend reads V2 day_config natively (alongside legacy-V1 read tolerance)   | None — additive              |
| 2     | DB migration: existing rows rewritten to V2 shape                          | One-shot data write          |
| 3     | Editor reads/writes V2 only; V1 form code removed                          | None — UI only               |
| 4     | URL params updated to V2 shape; legacy params still parsed for shared links | Low — old shared URLs work   |
| 5     | Backend stops accepting V1 input; schema's `day_config` documented as V2    | High if skipped — see §6     |

Phases 1-3 can ship piecemeal; phase 4 requires phase 3 first; phase
5 can be deferred indefinitely.

---

## Frontend (static/index.html) inventory

Each entry: site, current behavior, replacement, kill phase. Line
numbers from current revision; treat as approximate.

### V1-coupled READ sites

#### R-01 `buildShareUrl` — day encoding *(✓ partially fixed)*
- **Was:** walked `document.querySelectorAll('.day-row')` directly.
- **Now:** drives day encoding from `collectDayConfig()` (V2-aware)
  and iterates the V1-shape downgrade. Still emits V1 URL params.
- **Phase 4 target:** emit V2-shape URL params (`v2_day_1=…` or a
  base64-packed JSON blob); deprecate `d1=`/`d1b=`/`cc=`.

#### R-02 `buildShareUrl` — practice day fields *(✓ partially fixed)*
- **Was:** read `#practiceStart`, `#practiceEnd`, `#pdayBreaksList`.
- **Now:** reads from `collectDayConfig().practiceDay`. Still emits
  V1 URL params (`pday=`, `pd=`, `pdb=`, `pdcc=`, `pde=`).
- **Phase 4 target:** practice becomes a regular V2 block with
  `type:"practice"`. The `pday=`/`pd=` params disappear.

#### R-03 `buildShareUrl` — cycle changes *(✓ partially fixed)*
- **Was:** `getCycleTimeChanges()` walks `.day-cc-row` (V1 markup).
- **Now:** flattens `_urlDays[].cycleChanges` from `collectDayConfig`,
  with global→local afterMatch translation per day.
- **Phase 4 target:** cycle changes encode per-block, not per-day.

#### R-04 `renderSchedule` — cycle changes for day-title labels *(✓ fixed)*
- **Was:** `var cycleChanges = getCycleTimeChanges();` — V1 markup.
- **Now:** flattens from `collectDayConfig()`.
- **Phase 4 target:** read directly from V2 day_config; per-block.

#### R-05 `getCycleTimeChanges` — global helper
- **What it does:** walks `.day-cc-row` elements, returns a flat
  `[{after, time, day}]` array.
- **Callers:** R-03, R-04 above (both now go through V2-aware paths
  but still call this as fallback). Also called by other places that
  display cycle change labels in the UI.
- **Phase 3 target:** delete the function. All callers move to
  `collectDayConfig().days[i].cycleChanges`.

#### R-06 `getDayStartCycleTime(dayRow)`
- **What it does:** reads `.day-cc-row[data-is-start="1"] .cc-time`
  from a V1 day-row.
- **Callers:** legacy generation path; not currently invoked when V2
  is active.
- **Phase 3 target:** delete. Each schedulable V2 block's
  `cycleTime` field replaces this entirely.

#### R-07 `getDayForMatch(matchNum, useNextMatch)`
- **What it does:** scans the materialized schedule (`_frcScheduled`)
  to find which day a global match number belongs to. Used to
  attribute cycle changes to a day for URL encoding.
- **Phase 4 target:** unneeded once URL params encode per-block.

#### R-08 `getPracticeConfig` — practice block fields *(✓ V2-aware)*
- **Status:** already V2-aware. When `dayConfigUseV2` checked, reads
  via `collectDayConfigV2()` + `downgradeToV1`. Otherwise V1 fields.
- **Phase 3 target:** drop the V1 fallback branch; always V2.

#### R-09 `applyDayConfigToUI(dc)` — populate form from a day_config
- **What it does:** writes V1 form fields AND triggers V2 render.
  The V1 writes happen even in V2 mode (so V1 is "live" but hidden).
- **Phase 3 target:** when V2 is active (which will be always),
  skip the V1 writes entirely.

#### R-10 `addDayCycleChange(dayRow, afterMatch, newTime, isStart)`
- **What it does:** appends a `.day-cc-row` to a V1 day-row. Called
  by the URL parser to restore cc params.
- **Phase 4 target:** delete; URL parser writes V2 markup directly.

#### R-11 `buildDaysUI` / `addDayRow` / day-row building
- **What it does:** renders the V1 form (`.day-row` elements). Hidden
  when V2 is active but still rendered.
- **Phase 3 target:** delete the rendering. Stop building this DOM
  entirely. The V2 form (`#v2DaysContainer`) is the only editor.

#### R-12 `renderAgendaBlocks` `siblingBreaks` filter *(✓ fixed)*
- **Was:** `b.type === 'break'` only — missed awards/ceremony/alliance.
- **Now:** filters all four tier-3 types, preserves subtype.
- **Phase 0 (done).**

#### R-13 `renderAgendaBlocks` tier-3 inline labels *(✓ fixed)*
- **Was:** anonymous "small white tick" rendering for breaks.
- **Now:** type-aware colored insets with width-tiered labels.
- **Phase 0 (done).**

### V1-coupled WRITE sites

#### W-01 `applyDayConfigToUI` — V1 form population
- **What it does:** writes `#cycleTime`, `#breakBuffer`, `#numDays`,
  per-row `.day-start`/`.day-end`, `.break-row`, `.day-cc-row`.
- **Phase 3 target:** stop writing V1 fields. The V2 render is the
  only output. (Delete the V1 portions of the function.)

#### W-02 URL parser → V1 markup
- **What it does:** parses `d1=`/`d1b=`/`cc=`/`pday=` etc. and writes
  V1 form fields, then triggers V2 re-render via the migration path.
- **Phase 4 target:** parse straight to V2 markup. The migration step
  is what loses metadata (subtype, ceremonyKind, per-block ct).

#### W-03 `migrateLegacyDayConfig(dc)` — V1 → V2 reconstructor
- **What it does:** turns a V1-shape `dc` into V2 markup. Used on URL
  load and saved-schedule load to populate the V2 editor.
- **The lossy bit:** V1 break entries don't carry parent info, so
  the function classifies them against the day window heuristically
  — the source of the "alliance selection absorbed into qualification"
  bug.
- **Improved fix (interim):** route `subtype === 'alliance_selection'
  | 'awards' | 'ceremony'` to the day level always; only `subtype ===
  'break'` participates in the heuristic. Subtypes were preserved
  through downgrade post-fix-3, so this works for round-trips but
  not for original V1 data (which never had subtypes).
- **Phase 2 target:** unneeded once the DB stores V2 natively. The
  function survives only as a one-shot migration helper for the
  pre-migration data already in the DB.
- **Phase 3 target:** delete entirely after one-shot migration runs.

#### W-04 `downgradeToV1(dc)` — V2 → V1 reverse
- **What it does:** the reverse of W-03. Produces a V1-shape object
  from V2 for backend transmission and URL encoding. The wire format
  is V1 today, so this is the only way V2 reaches the backend.
- **Phase 1 target:** stops being called for backend transmission
  once the backend accepts V2 natively.
- **Phase 4 target:** stops being called for URL encoding once the
  URL is V2-shape.
- **Phase 5 target:** delete.

### Markup that exists only because V1 exists

- The `.day-row` markup template (in HTML, hidden when V2 active)
- The `#pdayBreaksList`, `#pdayCcList`, `#pdayEarlyEndList` containers
- The `#practiceDayEnabled`, `#practiceStart`, `#practiceEnd`,
  `#practiceGuaranteed`, `#practiceFiller`, `#practiceCycleTime`
  inputs
- The `#numDays` input (V2 derives day count from `#v2DaysContainer`)

**Phase 3:** delete the HTML templates; delete the IDs that no longer
have referents. Anything in JS that still references them gets caught
at the same time.

---

## Backend (app/) inventory

#### B-01 `app/main.py` — `AbstractScheduleRequest.day_config: Any`
- **Line ~261.** Pydantic accepts any shape; no validation.
- **Phase 1 target:** add a Pydantic V2 model for `day_config` with
  full validation per [V2_SPEC.md](V2_SPEC.md) §3-§7. Reject V1-shape
  with a 400 (or auto-migrate server-side, then reject 30 days later).

#### B-02 `app/main.py` — `AssignRequest.day_config: Any`
- **Line ~284.** Same as B-01.
- **Phase 1 target:** same model.

#### B-03 `app/main.py` — endpoint handlers writing day_config
- **Lines ~707, 869, 1142.** POST/PATCH paths persist `body.day_config`
  via SQLAlchemy.
- **Phase 1 target:** validate shape on entry. (Storage stays JSON,
  so no schema migration.)

#### B-04 `app/main.py` — endpoint handlers returning day_config
- **Lines ~751, 984, 1044.** GET paths return whatever's stored.
- **Phase 2 target:** if a row is still V1, run the legacy migrator
  server-side before returning. (Avoids client-side migration logic;
  consolidates the migration story in one place.)
- **Phase 3 target:** unneeded after one-shot migration runs.

#### B-05 `app/db.py` — model columns
- **Lines 130-200, 235-265.** Three tables hold `day_config: JSON`.
  No type info beyond "any JSON."
- **Phase 1 target:** no schema change. Documentation comment on the
  column noting "V2 shape per docs/V2_SPEC.md, dayConfigVersion: 2."
- **Phase 2 target:** during migration, set `dayConfigVersion: 2`
  on every row.

#### B-06 `app/scheduler.py` — match generation
- **Reads:** day_config to determine cycle times and break placement.
- **Currently:** ingests the same V1-shape the editor sends.
- **Phase 1 target:** rewrite to consume V2 directly. The materializer
  in [V2_SPEC.md](V2_SPEC.md) §10 is the contract.

#### B-07 `app/schedule_derive.py` — emits day_config from a parsed PDF
- **Lines ~92, 262.** Builds a V1-shape day_config from a FIRST agenda PDF.
- **Phase 1 target:** emit V2 shape directly. The PDF parser already
  separates ceremonies from quals — it just collapses them on the way
  out. Lift the collapse.

#### B-08 `app/pdf_dayplan.py` — `to_legacy_day_config`
- **Lines ~219, 494.** Adapter that produces V1 shape.
- **Phase 1 target:** rename to `to_v2_day_config`; emit native V2.

---

## URL parameter retirement

The current URL carries a V1-shape encoding. After phase 4, the URL
will carry V2 shape (per [V2_SPEC.md](V2_SPEC.md) §9.2). Back-compat:
the V1 parser stays indefinitely — only one V1 URL has been published
publicly, so the back-compat load is essentially zero, and the parser
costs nothing to keep around.

| Param                                                            | Current (V1)             | Phase 4 (V2)                                                     |
|------------------------------------------------------------------|---------------------------|------------------------------------------------------------------|
| `n`, `mpt`, `cd`, `ct`, `bb`, `seed`, `eventid` / `event_key`   | unchanged                 | unchanged (root-level fields, V2 too)                            |
| `dcv`                                                            | —                         | new — wire version (`2`); presence signals V2 shape              |
| `d1`, `d2`, …                                                    | `HH:MM-HH:MM`             | `<date>\|<label>` per [V2_SPEC.md](V2_SPEC.md) §9.2.1            |
| `d1b1`, `d1b2`, …                                                | —                         | new — block tuple per type                                       |
| `d1b1cc`                                                         | —                         | new — block-local cycle changes                                  |
| `d1b1c1`, `d1b1c2`, …                                            | —                         | new — tier-3 children of a block                                 |
| `d1b`, `d2b`, …                                                  | pipe/comma break list     | gone — children live in `dNbMcK`                                 |
| `cc`                                                             | `Day:After:Time,…`        | gone — replaced by `dNbMcc` (per-block local)                    |
| `pday`, `pd`, `pmpt`, `pfill`, `pct`, `pdb`, `pdcc`, `pde`       | practice day              | gone — practice is a regular `dNbM=practice\|…` block             |
| `dc`                                                             | —                         | optional compact form: `base64(JSON.stringify(day_config))`      |
| `dcc`                                                            | —                         | `1` to force compact emit (`dc=`); else human-readable           |

The default emit is **human-readable**. Compact mode kicks in
automatically only when the human-readable URL exceeds 2000
characters, or when explicitly requested via `dcc=1`.

The size cost of human-readable encoding for typical events
(2-4 days, 5-10 blocks each, a handful of children): ~500-1500
characters. Compact (`dc=`) of the same: ~600-1200 characters
(base64 vs URL-encoded JSON is a wash). The readability tradeoff
favors structured for almost all real-world cases.

---

## Test plan for retirement phases

Each phase has a stop-the-line test:

- **Phase 1:** the existing test suite passes against a backend that
  consumes V2. Generation of a saved schedule produces identical
  matches[] given identical inputs.
- **Phase 2:** every existing DB row reads back as `dayConfigVersion: 2`
  with no data loss. (Snapshot before migration; spot-check after.)
- **Phase 3:** the editor never references `.day-row` or any V1-only
  selector. Burn-down of `git grep '\.day-row\|day-cc-row\|practiceStart'`.
- **Phase 4:** old URL shared links still load and produce the same
  V2 day_config. New shares produce shorter / lossless URLs.
- **Phase 5:** `git grep 'V1\|day_config_v1\|legacy'` returns only doc files.
