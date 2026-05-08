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

## Phase 5 — final cleanup

**Goal:** no V1 references anywhere in the codebase *except* the V1
URL parser, which stays indefinitely as a sub-100-line back-compat
wedge (cost essentially zero — the parser doesn't run unless `dcv=`
is absent).

**Work:**
1. Remove the server-side migrator (B-04 fallback). Confirmed unused
   in phase 2 metrics.
2. Add a JSONB check constraint in DB (per
   [DB_V2_MIGRATION.md](DB_V2_MIGRATION.md) §4):
   `(day_config IS NULL) OR (day_config->>'dayConfigVersion' = '2')`.
3. **Keep** the V1 URL parser (per phase 4 decision — back-compat
   load is essentially zero, retention cost is essentially zero).
   No retention timer.
4. Final grep walkthrough: `git grep -i 'v1\|legacy\|day_config_v1'`
   returns only doc files describing the history and the retained
   V1 URL parser.
5. Archive [V1_RETIREMENT.md](V1_RETIREMENT.md) (move to
   `docs/archive/` with the completion date) once everything except
   the V1 URL parser is gone.

**Exit criteria:** the archive plus the V1 URL parser is what remains.

**Risk:** low. Cleanup only.

---

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

## Status tracker

| Phase | Status      | Owner | Notes                                       |
|-------|-------------|-------|---------------------------------------------|
| 0     | ✓ Done      | claude| Specs ratified, doc reviews complete        |
| 1     | ✓ Done      | claude| Backend V2 in place; deployed                |
| 2     | ✓ Done      | you   | DB migration applied                        |
| 3     | ✓ Mostly done | claude | V1 markup gone; helper deletion in phase 5 |
| 4     | ✓ Done      | claude| V2 URL emit/parse + 36 round-trip tests    |
| 5     | Not started |       | Helper function deletion + final cleanup    |
