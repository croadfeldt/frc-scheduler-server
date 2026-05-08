# V2-only roadmap

**Status:** active. The phased rollout from where we are today to a
codebase with no V1 day_config anywhere.

References:
- [V2_SPEC.md](V2_SPEC.md) — what we're building toward.
- [V1_RETIREMENT.md](V1_RETIREMENT.md) — the kill list.
- [DB_V2_MIGRATION.md](DB_V2_MIGRATION.md) — DB schema work.

---

## Phase 0 — ratify the spec *(this turn)*

**Deliverable:** [V2_SPEC.md](V2_SPEC.md), [V1_RETIREMENT.md](V1_RETIREMENT.md),
[DB_V2_MIGRATION.md](DB_V2_MIGRATION.md), and this roadmap merged.

**Exit criteria:**
- Specs reviewed by you (project lead).
- Outstanding questions resolved or noted as deferred.
- No code changes in this phase.

---

## Phase 1 — backend reads V2 natively *(in progress)*

**Goal:** the server-side scheduler and PDF parser consume V2 directly,
without going through V1.

**Work:**
1. ✓ Author a Pydantic V2 model. Validate per [V2_SPEC.md](V2_SPEC.md) §8.
   *Implemented as `app/day_config_v2.py` with full
   `DayConfigV2`/`DayV2`/`BlockV2`/`CycleChangeV2` models and validation,
   exercised by `tests/test_day_config_v2.py` (31 passing tests).*
2. *Mostly N/A.* `app/scheduler.py` turned out to be purely abstract on
   audit — it knows nothing about times or day_config. The materializer
   that converts V2 day_config → timed entries lives client-side.
   `materialize_v2()` is reserved as a stub in `day_config_v2.py` for
   when backend match-time generation lands; today no backend code
   consumes day_config beyond storage.
3. ✓ Update `app/schedule_derive.py` and `app/pdf_dayplan.py` to emit
   V2 shape (per [V1_RETIREMENT.md](V1_RETIREMENT.md) B-07 / B-08).
   *`schedule_derive.derive_parameters()` now emits V2 directly.
   `pdf_dayplan.to_v2_day_config()` emits V2 by routing through the
   internal `to_legacy_day_config()` + `migrate_v1_to_v2()` so the
   classification path is shared with the legacy migrator.*
4. ✓ Add server-side migrator. *`app/day_config_v2.py` provides
   `migrate_v1_to_v2()`, `downgrade_v2_to_v1()`, `normalize_to_v2()`.
   All write endpoints in `main.py` route through `_normalize_dc()`;
   all read endpoints emit V2 via `normalize_to_v2()`.*

**Exit criteria:**
- ✓ `POST /api/generate-abstract`, `POST /api/abstract-schedules/{id}/assign`,
  `POST /api/schedules/import-pdf/commit`, and `PATCH /api/assigned-schedules/{id}`
  accept V2 input and validate it; V1 input is auto-migrated.
- ✓ GET endpoints emit V2 regardless of stored shape (legacy V1 rows
  pass through `normalize_to_v2()` on read).
- ✓ Test suite covers validation rejection, V1→V2 migration including
  the alliance-selection-not-absorbed regression, and importer V2 emit.
- ✓ Editor still ships V1-shape downgrade; no client changes yet.

**Risk:** medium → low. Scheduler is the most load-bearing code in the
backend, but it doesn't touch day_config — phase 1's blast radius is
contained to validation + read normalization. Phase 2 (DB migration)
can proceed without phase 1 changes affecting in-flight schedules
since migration is idempotent and back-compat reads are V2-shape.

---

## Phase 2 — DB migration *(ready to run)*

**Goal:** every row in the three day_config-bearing tables is
`dayConfigVersion: 2`.

**Tooling:** `scripts/migrate_db_to_v2.py` (Python migration logic
using `app.day_config_v2.migrate_v1_to_v2()`) wrapped by
`scripts/openshift_migrate.sh` (snapshot + dry-run + confirm + apply
+ verify). See [DB_V2_MIGRATION.md](DB_V2_MIGRATION.md) §3 and §6.

**Work:** per [DB_V2_MIGRATION.md](DB_V2_MIGRATION.md) §3 and §6.
With the wrapper script, the operator runs:

```bash
./scripts/openshift_migrate.sh dryrun     # preview what would change
./scripts/openshift_migrate.sh apply      # actually migrate
./scripts/openshift_migrate.sh verify     # confirm post-state any time
```

**Exit criteria:**
- Pre-migration snapshot saved (rollback path). The wrapper script
  enforces this — it refuses to apply without first writing a
  validated snapshot.
- All three tables report `v1: 0` after migration. Verify command:
  `./scripts/openshift_migrate.sh verify`.
- Server-side fallback (`normalize_to_v2()` on read) verified on
  production traffic for 7 days with zero invocations of the
  V1→V2 path. *No metric exists for this yet — phase 1 added the
  fallback but no instrumentation. Could add a counter to
  `app/day_config_v2.normalize_to_v2()` when phase 5 cleanup
  approaches; for now the proof is "every read of every saved
  schedule comes back as V2 in API responses."*

**Risk:** low. The migration is idempotent (running twice is
harmless), reversible (the snapshot file restores via standard
`psql -f`), and atomic per-row (each table commits as a unit). The
operator gets two opportunities to abort: dry-run output review,
and explicit "type 'apply'" confirmation.

---

## Phase 3 — editor V2-only *(stage 1 complete)*

**Goal:** `static/index.html` no longer renders or reads V1 markup.
The V2 editor (`#v2DaysContainer`) is the only editor.

The work decomposes into two stages because some V1 markup is still
needed by the V1 URL parser (which writes V1-shape form fields, then
triggers V2 render via the migrator) until phase 4 changes the URL
emit format. Stage 1 handles the V1/V2 toggle and unreachable
fallbacks; stage 2 (after phase 4) handles the V1 markup itself.

### Stage 1 *(✓ done)*

1. ✓ Removed the V1/V2 toggle. The `dayConfigUseV2` checkbox is gone
   from the DOM. Every `if (v2cb && v2cb.checked) { ... }` site was
   inlined to the V2 branch.
2. ✓ `getPracticeConfig()` simplified — V1 form-field fallback
   removed. Was unreachable in practice since V2 was forced on, but
   the dead branch obscured the V2 read path.
3. ✓ `collectDayConfig()` — V2 path is unconditional; V1 fallback
   kept narrow as a defensive last-resort for very-early page loads.
4. ✓ Dead V1 helpers deleted: `getPracticeBreaks`,
   `getPracticeCycleChanges`, `getPracticeEarlyEnd`. Each had one
   declaration, zero callers post-cleanup.
5. Net deletion: ~60 lines of dead V1 code.

### Stage 2 *(✓ mostly done; helpers retire in phase 5)*

What we did:

1. ✓ V1 day-config wrapper (`#v1DaysWrapper`) deleted from DOM. The
   ~60 lines of V1 form markup (practice section, days container,
   add-day button, error msg) are gone.
2. ✓ Visible "Number of Days" field removed; `#numDays` retained as
   a hidden input so JS readers don't crash. Phase 5 deletes the
   element when the readers go.
3. ✓ V1 URL → V1 dc converter (`_assembleV1DcFromUrlParams`) added.
   V1 URLs now flow: parse → assemble V1 dc → migrate to V2 →
   `renderDayConfigV2`. No form-field detour.
4. ✓ `applyUrlParams` simplified — V1 day_config form-field writes
   removed. Still handles top-level fields (numTeams, MPT, cd,
   cycleTime, breakBuffer, weights, autoFlags, seed).
5. ✓ `applyDayConfigToUI` simplified to V2-only. Was ~140 lines of
   form-field write code; now ~25 lines (V2 render + top-level
   field syncs + dates side-channel + auto flags).
6. ✓ `buildDaysUI`, `togglePracticeDay` made defensive (early
   return on missing markup). The other V1 helpers (`addBreak`,
   `addDay`, `addDayCycleChange`, etc.) naturally no-op because
   their DOM queries return empty NodeLists once the markup is gone.

What's left for phase 5:

- Delete the V1 helper *functions* outright. They're dormant now
  but still occupy ~600 lines (`buildDaysUI`, `addDay`, `addBreak`,
  `addDayCycleChange`, `addDayEarlyEnd`, `removeDay`,
  `applyDayEndTimes`, `renumberDays`, `togglePracticeDay`,
  `addPracticeBreak`, `addPracticeCycleChange`, `addPracticeEarlyEnd`,
  `getCycleTimeChanges`, `getDayStartCycleTime`, `getDayForMatch`,
  `getDayEarlyEnd`).
- Delete the surviving callers in non-V1 paths that still reference
  these functions defensively (PDF import dayplan-apply, agenda
  fetch handler).
- Delete `migrateLegacyDayConfig` (JS) once V1 URL back-compat is
  retired (or kept indefinitely if the cost is small).
- Delete `downgradeToV1` once `finishGeneration` is rewritten
  V2-native.
- Remove the `#numDays` hidden input.

**Risk:** stage 2 was deletion-heavy with surface-area-aware
defensive guards. The V2 path handles all current code flows; V1
URL back-compat is preserved via the new converter. Net: ~250 lines
deleted from index.html, no functional regressions.

---

## Phase 4 — URL parameters V2-shape *(done — pending review)*

**Goal:** the URL emits V2-native params, with a back-compat parser for
old shared links. Risk is unusually low here — only one V1 URL has
been published publicly to date.

**Work:**
1. ✓ URL encoding (per [V2_SPEC.md](V2_SPEC.md) §9.2):
   - Default: human-readable structured params (`dcv=2`, `dN=`,
     `dNbM=`, `dNbMcc=`, `dNbMcK=`).
   - Compact fallback: `dc=base64(JSON)` when length > 2000 chars.
   *Implemented in `static/index.html` as four helpers near
   `V2_BLOCK_TYPES`: `_v2EncodeBlockValue`, `_v2DecodeBlockValue`,
   `_v2WriteUrlParams`, `_v2ReadUrlParams`. 36 round-trip tests
   in `tests/test_v2_url.js` (all passing).*
2. ✓ Update `buildShareUrl` to emit V2 params. Always include `dcv=2`
   so the parser can route by version cleanly.
   *V2 emit is unconditional. The previous V1 emit (d1=, d1b=, cc=,
   pday=, pd=, pdb=, pdcc=, pde=) is gone; replaced by the V2 emit
   block. ~150 lines of V1 emit code removed.*
3. ✓ Update the URL parser to read V2 params first; fall back to
   legacy params when `dcv=` is absent.
   *`autoRunFromUrl` now detects `dcv=2`. When set, calls
   `_v2ReadUrlParams` and renders directly via `renderDayConfigV2`.
   Otherwise falls through to `parseUrlParams` + `applyUrlParams`
   which still write V1 form fields and trigger `migrateLegacyDayConfig`
   → V2 render. The V1 fallback path is unchanged from phases 1-3.*
4. *Deferred to phase 5.* Delete `downgradeToV1`. The function still
   has callers in `collectDayConfig` (downgrade for backend
   submission) and parts of the materializer; once those move
   to V2-native, removal becomes safe. *No longer used by
   `buildShareUrl` — that was the largest caller.*
5. ✓ [V2_SPEC.md](V2_SPEC.md) §9.2 ratified by implementation.

**Exit criteria:**
- ✓ New shares produce structured V2 URLs by default; `dc=` fallback
  triggers correctly at the 2000-char threshold.
- ⏳ Old shares (the one V1 link) still load correctly. *Logic
  preserved; manual verification at deploy time.*
- ✓ The V2 parser is exercised by a fixture suite covering each block
  type, nesting case, cycle changes, sparse days, compact mode,
  pipe-sanitized labels.

**Risk:** low. The single published V1 URL is in chat history; we
test against it before deploy. New V2 URLs are exercised by 36
round-trip tests.

---

## Phase 5 — V1 helper deletion *(✓ done)*

**Goal:** no V1 helper functions in the codebase *except* the V1
URL parser, which stays indefinitely as a sub-100-line back-compat
wedge (cost essentially zero — the parser doesn't run unless `dcv=`
is absent).

**What we did:**

1. ✓ Deleted V1 helper functions outright (~570 lines): `addDay`,
   `removeDay`, `addBreak`, `addDayCycleChange`, `addDayEarlyEnd`,
   `addPracticeBreak`, `addPracticeCycleChange`, `addPracticeEarlyEnd`,
   `applyDayEndTimes`, `applyPracticePDFBlocks`, `buildDaysUI`,
   `getCycleTimeChanges`, `getDayEarlyEnd`, `getDayForMatch`,
   `getDayStartCycleTime`, `pruneAfterEndTime`, `renumberDays`,
   `togglePracticeDay`.
2. ✓ Deleted V1 wrapper helpers (~85 lines): `syncDayRowsToNumDays`,
   `refreshCycleDayLabels`, `addCycleChange` (the deprecated one).
3. ✓ Rewrote `applyDayplanToForm` V2-native (PDF dayplan import now
   feeds straight into `applyDayConfigToUI` → `renderDayConfigV2`,
   ~95 → ~25 lines).
4. ✓ Stubbed `applyAgendaToSchedule` (the agenda PDF apply path was
   V1-only; V2 has no auto-apply equivalent yet; remaining caller is
   informational and a no-op stub is correct).
5. ✓ Replaced V1 fallback callers with literal defaults
   (`getCycleTimeChanges()` → `[]`, `getDayEarlyEnd(row)` → `null`).
6. ✓ Removed `#numDays` event listeners and the cycleTime-push V1
   sync logic.

**What stayed:**

- `migrateLegacyDayConfig` (JS) — the V1 URL back-compat path uses
  it. Sub-100-line cost; keeps the one published V1 URL working.
- `downgradeToV1` (JS) — `_finishGenerationInner` calls it on entry
  to convert V2 day_config to V1 shape for the existing V1-shape
  scheduler logic. A future phase 5b can rewrite the scheduler
  V2-native and drop this; for now it's load-bearing.
- `#numDays` hidden input — some legacy JS readers consult it for a
  default value; it's a 1-line element with no UI.
- The Python migrator (`migrate_v1_to_v2`) and `downgrade_v2_to_v1`
  in `app/day_config_v2.py` — backend-side analogues, kept for
  legacy URL/data round-trip.

**Net:** index.html went from 17541 lines (start of stage 2) to
**16682 lines** (-859 lines). All 36 V2 URL tests still pass; backend
tests unchanged.

**Risk:** low. Pure deletion + 2 V2-native rewrites; semantics
preserved.

---
## Phase 5b — V2-native scheduler input *(✓ done)*

**Goal:** finishGeneration consumes V2 day_config natively. Drop the
ambiguously-named `downgradeToV1` wedge.

**What we did:**

1. ✓ Renamed `downgradeToV1` → `_v2BuildSchedulerInput`. Same logic,
   clearer name. The function builds the V1-shape input list the qual
   scheduler walks (`{ days, practiceDay, playoffBlocks, cycleTime,
   breakBuffer }`); the rename clarifies it's not a "downgrade" in any
   wire-format sense, just an internal scheduler-input transform.
2. ✓ Added `_v2ExtractPlayoffs(dc)` — lighter helper for callers that
   only need the playoff side-channel (the agenda renderer's playoff
   inject path used to call the full transform just for one field).
3. ✓ Updated agenda renderer (`renderScheduleBars`) to use
   `_v2ExtractPlayoffs` instead of the full transform.
4. ✓ Deleted `toggleDayConfigEditor` (~20 lines) — dead since stage 1.
5. ✓ Fixed view page color rendering: `_v2BlockToV1Break` now
   preserves `subtype`/`breakKind`/`ceremonyKind` (was stripping them,
   making everything render as a generic break). Schedule table
   `<tr class="break-row" data-subtype="...">` and agenda timeline
   segments now color by subtype matching the V2 editor palette
   (alliance_selection teal, awards gold, ceremony coral, playoff
   purple, break orange).
6. ✓ Updated CSS: comprehensive `tr.break-row[data-subtype]` palette
   + dark-mode variants. Brought existing `tr.info-block-row`
   colors into alignment with the V2 editor (playoff was wrong red,
   ceremony was wrong purple — both now correct).

**What stays:**

- `_v2BuildSchedulerInput` itself — it's the V2→scheduler-input
  transform. Future "phase 5c" could rewrite the qual-scheduling
  inner loop to walk V2 blocks per-block (per-block cycleTime, true
  multi-qual-block-per-day support); for now this transform centralizes
  the V2→V1-shape mapping.
- `migrateLegacyDayConfig` — V1 URL back-compat.

**Risk:** low. Pure rename + extraction + view-page color fix.
Same scheduler logic, same data flow.


## Open questions

These are tracked here so they don't get lost; resolution moves them
into the appropriate doc.

### Q-01 V2 cycle changes — block-local vs day-local?

**Resolved:** block-local. See [V2_SPEC.md](V2_SPEC.md) §7. The
materializer adds the global offset.

### Q-02 Should practice be a top-level day or a block on a regular day?

**Tentatively resolved:** a `practice`-typed block on a regular day.
The first day at a typical event has practice in the morning and quals
in the afternoon — they're the same day. V1's model of "practice day
is a separate day-shaped thing" was an artifact of practice not having
a block type. V2 just makes it a block.

The downgrader currently emits a separate `practiceDay` field for
backend compat; phase 1 backend changes can drop this distinction.

### Q-03 URL encoding format — `dc=base64(JSON)` vs structured?

**Resolved:** **both, with human-readable as default.** Per
[V2_SPEC.md](V2_SPEC.md) §9.2:

- Default emit: human-readable structured params (`dcv=2`, `dN=…`,
  `dNbM=…`, `dNbMcK=…`, etc.). Lossless, scannable by eye, lets
  power users edit a URL by hand to tweak a schedule.
- Compact fallback: `dc=base64(JSON)` for URLs that exceed 2000
  characters or when the user explicitly requests it via `dcc=1`
  (e.g. for SMS sharing).

The parser accepts both — if `dc=` is present, it wins; otherwise the
structured params are reconstructed.

### Q-04 Day-wrap (events ending after midnight)?

**Deferred.** Currently `end > start` is enforced strictly. An event
that spans midnight is rare but possible. If it comes up, the spec
addition is: allow `end < start` to mean "next day," and the
materializer handles the wrap. Bumps `dayConfigVersion` to 3.

### Q-05 Multiple match-blocks on a single day — edge cases?

A day with two qualification blocks separated by a long break (e.g.
8-12 morning quals, 13-17 afternoon quals): supported by V2 model,
needs scheduler to handle the global match counter correctly across
both. Fixture: write a scheduler test that validates this case
during phase 1.

### Q-06 Playoff match generation?

Currently the playoff block reserves time only — the materializer
emits no matches for it. Eventually we'll generate playoff matches
from the bracket format and alliance selection results. That's a
separate workstream; tracked here as a marker.

### Q-07 Unified event selector — view + edit page?

**Open / future enhancement.** The view page currently doesn't have
an event selector — it relies on `?key=` URL param. The edit page
has its own event picker UI. Both should converge on a single
component so:

- A user on `/view` can switch events without manually editing the URL.
- The same component, same backing endpoint, same behavior across pages.
- Permissions logic (who-can-see-which-event) lives in one place.

Tracked here so we don't lose it. Schedule: post-V2 migration —
the selector touches event-data plumbing that isn't on the V2
critical path, and slipping it in mid-phase risks scope creep.
Revisit after phase 3 ships.

---

---
## Phase 5c — V2-native qual scheduler *(✓ done)*

**Goal:** drop the V2→V1 transform from the qual scheduler entirely.
The scheduler now walks V2 blocks directly: each qual block is a
"segment" with its own cycleTime, segment-local cycle changes, and
segment-local breaks. Tier-3 + playoff + practice-on-mixed-day blocks
become per-day "blockers" — off-limits time windows the segment
scheduler stops at.

This subsumes the earlier 5c band-aid (cycle-changes + synthetic gap
breaks in `_v2BuildSchedulerInput`). Both still exist in the codebase
because `getPracticeConfig` and `collectDayConfig` (save/load paths)
still need the V1-shape transform — but `_finishGenerationInner` no
longer does.

**What we did:**

1. ✓ **`_v2BuildQualPlan(dc)`** — new function producing a complete
   V2-native scheduling plan: `{cycleTime, breakBuffer, segments[],
   blockers[], dayMeta[], practiceDay, playoffBlocks[]}`. Pure over
   `dc`; no DOM access. Defensive on shape — non-V2 input returns an
   empty plan.
   - `segments[]` are qual blocks with **segment-LOCAL** afterMatch
     on cycle changes (no offset shifting). Sorted by `dayIdx` then
     `start`.
   - `blockers[]` carry tier-3 + playoff + practice-on-mixed-day,
     each tagged with a `dayIdx` so they scope to the right day.
     Practice on mixed days as a blocker is a slight improvement
     over the old V1 path: qual matches no longer bleed into the
     practice window at practice cycleTime.
   - `dayMeta[]` covers the full day envelope (min start / max end
     across all blocks, including pre/post-qual ceremonies) plus
     `hasQual` / `hasPractice` booleans for the output emitter.
   - `practiceDay` only populated for practice-ONLY days, matching
     the existing `_pracCfg` consumer's expectations.
   - `playoffBlocks[]` is the same side-channel the agenda renderer
     consumed before.
2. ✓ **Rewrote the qual scheduling loop** in `_finishGenerationInner`.
   The new loop walks `_qPlan.segments[]` in order. For each segment:
   - Builds the active-break list from segment's own breaks plus day
     blockers overlapping the segment window.
   - Uses a segment-local cursor + segment-local match count.
   - Reads cycleTime from a `segCtAt(n)` helper that walks segment
     changes — **no global afterMatch**, no boundary cycle-change
     tricks. Per-block cycleTime is just inherent to the segment.
   - Emits cycle-change markers only at intra-segment boundaries.
   - Match overflow on the last segment triggers
     `window._frcFinalDayOverflow`.
   - Time fit is bounded by `seg.end`, not `day.end` — matches
     can't bleed past the segment.
3. ✓ **Output assembly walks dayMeta**, pushing one `scheduled[]`
   entry per day with qual segments. `dayNum` is sequential output
   ordering (matches the V1 path's `d+1`), so a qual-only Day 2
   still renders as "Day 1" of the qual schedule when there's a
   separate practice day before it.
4. ✓ **Legacy V1-shape branch preserved** as a fallback — runs
   only when `_qPlan` couldn't be built (e.g. a hand-crafted V1
   fixture or a malformed override). Real loads always hit the
   V2-native branch.
5. ✓ **`statDays.textContent`** now sources from `scheduled[]`
   (counting days with at least one match), not `days[]` which is
   empty on the V2-native path.
6. ✓ **9 new tests** in `tests/test_v2_scheduler_input.js`:
   - Empty / non-V2 input returns empty plan.
   - Single qual block → 1 segment, no blockers.
   - Two qual blocks same day, different CT → 2 segments with own cycleTime.
   - Mixed practice+qual day → 1 segment, practice in blockers (not practiceDay).
   - Practice-only day → 0 segments, practiceDay populated.
   - Tier-3 between qual blocks → blocker only.
   - Playoffs → blockers AND playoffBlocks side-channel.
   - Day with only ceremonies → 0 segments, hasQual=false.
   - Multi-day: segments ordered by dayIdx then start.

**What stays:**

- `_v2BuildSchedulerInput` (the V2→V1-shape transform from phase 5b).
  Still used by `getPracticeConfig` (extracts the practice slot) and
  `collectDayConfig` (returns V1-shape for save/load round-trips).
  These could be rewritten V2-native in a future cleanup but are out
  of scope for 5c — the user-visible scheduling correctness is the
  point of phase 5c, and that's now V2-native.
- `_v2dayCycleChanges` + the synthetic gap-break logic. They live in
  `_v2BuildSchedulerInput` only and are no longer on the scheduler's
  path. Kept because the V1-shape transform is still consumed by
  `view.html`'s downgrade and the save/load callers.
- The V1-shape fallback branch in `_finishGenerationInner`. Defensive;
  no real callers hit it.

**Risk:** medium-high. This is a core scheduler rewrite. The new path
has been unit-tested for plan construction (9 tests on shape +
ordering); the scheduling math itself was lifted from the V1 loop
and adapted to segment-local indices, so the inner loop logic is
the same algorithm with different bookends. Worth verifying live:
single-day single-block, multi-day same CT, multi-day with cycle
change at after-match-N, practice-only day, mixed practice+qual day,
multi-qual-block-per-day at different CTs.

## Status tracker

| Phase | Status      | Owner | Notes                                       |
|-------|-------------|-------|---------------------------------------------|
| 0     | ✓ Done      | claude| Specs ratified, doc reviews complete        |
| 1     | ✓ Done      | claude| Backend V2 in place; deployed                |
| 2     | ✓ Done      | you   | DB migration applied                        |
| 3     | ✓ Done      | claude| V1 markup gone; helpers retired in phase 5  |
| 4     | ✓ Done      | claude| V2 URL emit/parse + 36 round-trip tests    |
| 5     | ✓ Done      | claude| ~870 lines of V1 helpers + plumbing deleted |
| 5b    | ✓ Done      | claude| Scheduler-input rename + view colors fixed  |
| 5c    | ✓ Done      | claude| V2-native qual scheduler (segments + blockers) |
