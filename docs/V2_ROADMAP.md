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

## Phase 2 — DB migration

**Goal:** every row in the three day_config-bearing tables is
`dayConfigVersion: 2`.

**Work:** per [DB_V2_MIGRATION.md](DB_V2_MIGRATION.md) §3, §6.

**Exit criteria:**
- Pre-migration snapshot saved (rollback path).
- One-shot SQL migration applied; spot-checks pass.
- Server-side fallback verified on production traffic for 7 days
  with zero invocations.

**Risk:** low. The migration is idempotent and reversible.

---

## Phase 3 — editor V2-only

**Goal:** `static/index.html` no longer renders or reads V1 markup.
The V2 editor (`#v2DaysContainer`) is the only editor.

**Work:**
1. Delete the V1 form rendering: `buildDaysUI`, `addDayRow`, the
   `.day-row` HTML template, the practice-day form fields
   (`#practiceStart` etc.), `#numDays`. Per
   [V1_RETIREMENT.md](V1_RETIREMENT.md) R-11 and the markup list.
2. Delete the V1 form READ helpers: `getCycleTimeChanges`,
   `getDayStartCycleTime`, `getDayForMatch`, `addDayCycleChange`.
   Per [V1_RETIREMENT.md](V1_RETIREMENT.md) R-05/R-06/R-07/R-10.
3. Strip `applyDayConfigToUI` of its V1 branches; rename to reflect
   V2-only role (e.g. `applyDayConfig` — no -ToUI suffix).
4. Delete the `dayConfigUseV2` toggle. V2 is the only mode.
5. Delete the V1 fallback paths in `getPracticeConfig` etc. — already
   V2-aware, just remove the `if (!v2cb.checked)` branches.
6. Remove the `migrateLegacyDayConfig` function (W-03). The server
   migrator is the only place V1→V2 happens.
7. The `downgradeToV1` function (W-04) survives this phase if the
   URL still uses V1 params; gets killed in phase 4.
8. Walk-down: `git grep '\.day-row\|day-cc-row\|practiceStart\|practiceEnd\|practiceGuaranteed\|practiceFiller\|practiceCycleTime\|getCycleTimeChanges\|migrateLegacyDayConfig'`
   should return only doc-comment matches.

**Exit criteria:**
- Editor builds, runs, generates schedules identical to phase 2 output.
- The grep above returns only doc references.
- The URL still uses V1 params; tests confirm shared links from before
  the phase still load correctly.

**Risk:** low-medium. Mostly deletion. The risk is missing a V1 reference
that fails silently (e.g. an event listener wired in HTML).

---

## Phase 4 — URL parameters V2-shape

**Goal:** the URL emits V2-native params, with a back-compat parser for
old shared links. Risk is unusually low here — only one V1 URL has
been published publicly to date, so the back-compat surface is
essentially zero.

**Work:**
1. URL encoding is decided (per [V2_SPEC.md](V2_SPEC.md) §9.2):
   - Default: human-readable structured params (`dcv=2`, `dN=`,
     `dNbM=`, `dNbMcc=`, `dNbMcK=`).
   - Compact fallback: `dc=base64(JSON)` when length > 2000 chars
     or `dcc=1` is explicitly set.
2. Update `buildShareUrl` to emit V2 params. Always include `dcv=2`
   so the parser can route by version cleanly.
3. Update the URL parser to read V2 params first; fall back to legacy
   params (`d1=`, `d1b=`, `cc=`, `pday=`, etc.) when `dcv=` is absent.
   Indefinite back-compat retention — see phase 5.
4. Delete `downgradeToV1` (W-04 in [V1_RETIREMENT.md](V1_RETIREMENT.md))
   when no caller remains.
5. Confirm [V2_SPEC.md](V2_SPEC.md) §9.2 matches the implementation.

**Exit criteria:**
- New shares produce structured V2 URLs by default; `dc=` fallback
  triggers correctly at the 2000-char threshold.
- Old shares (the one V1 link, plus any test fixtures we capture)
  still load correctly.
- The V2 parser is exercised by a fixture suite covering each block
  type, nesting case, and cycle change shape.

**Risk:** low. The single published V1 URL is in chat history; we
test against it before deploy.

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

---

## Status tracker

| Phase | Status      | Owner | Notes                                       |
|-------|-------------|-------|---------------------------------------------|
| 0     | ✓ Done      | claude| Specs ratified, doc reviews complete        |
| 1     | ✓ Done (pending review) | claude | Backend V2 in place — see phase 1 notes  |
| 2     | Not started |       | One-shot SQL migration                      |
| 3     | Not started |       | Frontend cleanup; mostly deletion           |
| 4     | Not started |       | URL format change with back-compat          |
| 5     | Not started |       | Cleanup; 6 months after phase 4            |
