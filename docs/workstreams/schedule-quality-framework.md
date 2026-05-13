# Schedule Quality Framework — Empirical Validation v1.0

**Status:** Phase A complete (2026-05-13). Phases B/C/D follow.
**Workstream owner:** scheduler quality
**Related:** `docs/scheduler/quality-floors.md` (Phase A);
`docs/workstreams/best-possible-schedule.md` (Phase 1 investigation).

---

## Goal

Build a complete framework for **empirically validating any
schedule against principled, per-fixture theoretical floors and
acceptability bars**, with:

1. Theoretical floors (proven optimal or proven lower bounds) for
   every metric and every fixture shape.
2. A canonical schedule library of pre-computed best-known schedules
   for common FRC fixture shapes, so organizers get a known-good
   schedule without needing to generate one.
3. A scoring framework with per-criterion 1-100 scores and
   organizer-tunable weights, producing a weighted composite.
4. A standing evaluation suite that any future scheduling
   methodology runs through to prove it meets the bar.

When this work is complete:
- Any candidate scheduling method (CP-SAT, SA, hybrid, novel) can
  be evaluated objectively against the same per-fixture floors.
- Event organizers can request a canonical schedule from the
  library, or generate one fresh and see how close it gets to
  optimum.
- Production scheduler regressions are caught by the standing eval.

---

## Decisions locked in

- **D5** (from `best-possible-schedule.md`): paramount cooldown=2
  project-wide, user-tunable.
- **Quality framework scope**: FRC §10.5.2 criteria only; EPA /
  past-performance / strength-based scheduling is a roadmap item,
  not part of v1.
- **Floor confidence levels**: ship proven floors where provable
  by counting/pigeonhole; ship `proven_lower_bound` floors where
  the count distribution is provably a lower bound but achievability
  is uncertain; ship `best_known` floors for metrics where no
  closed-form exists, clearly labeled.
- **Comprehensive coverage**: build out the full FRC plausible-
  shape inventory (~27 shapes), but **prove the system on a small
  5-fixture inventory first** (12×6, 24×8, 36×7, 20×8 surrogate,
  60×12 CP-SAT-infeasible), then scale.
- **Pass criterion**: matching the floor is "best possible." Below
  that, a 1-100 weighted score lets organizers judge.

---

## Phases

### Phase A — Theoretical floors module ✓ COMPLETE

**Deliverables shipped:**
- `app/quality_floors.py` — per-metric, per-fixture floors with
  confidence labels and proof notes.
- `tests/test_quality_floors.py` — 50+ assertions covering math,
  serialization, confidence labels, cooldown feasibility.
- `docs/scheduler/quality-floors.md` — full derivations and proofs.
- Re-exported through `app/quality.py` for application access.

**Validated against F1-c observations:**
- 24×6 par_quad floor=144 matches observed exactly (proven optimal achievable)
- 36×7 par_quad floor=252 matches observed exactly (proven optimal achievable)
- 12×6 cooldown=2 shows floor=84 vs observed=192 (expected gap: cooldown=2
  structural constraint forces two non-interacting team groups; the count-
  distribution lower bound isn't achievable under this constraint)

**Confidence labels in v1.0:**
- `proven_optimal`: cooldown_violations, surrogate_count, rb_per_team,
  station_per_team_spread, partner_pair_count, opponent_pair_count (6 of 8)
- `proven_lower_bound`: par_quad, opp_quad (2 of 8 — tight on many fixtures,
  loose on cooldown-constrained ones)

---

### Phase B — Canonical schedule library ✓ COMPLETE (this session, partial)

**Deliverables shipped:**
- `app/canonical_library.py` — JSON-file-backed loader with `load_canonical()`, `save_canonical()`, `list_canonicals()`, `CanonicalEntry` dataclass, and 3-level confidence vocabulary (proven_optimal / matches_floor / best_known).
- `app/quality_report.py` — `build_quality_report()` constructs the rich per-metric report (value / floor / distance / confidence / matches_floor) embedded in every canonical entry and every newly-stored abstract schedule.
- `scripts/scheduler_eval/build_canonical.py` — producer script that runs SA-best-of-N for any fixture shape and writes the canonical JSON.
- `app/canonical_schedules/` — directory with 5 canonicals built (12×6, 20×8 surrogate, 24×8, 36×7, 60×12 at cooldown=2).
- `POST /api/schedules` — new unified endpoint with `source_preference` ('auto' / 'canonical_library' / 'generated') and import path (caller supplies matches).
- `GET /api/canonical-schedules` — list endpoint for available canonicals.
- `GET /api/abstract-schedules/{id}` — extended response with `source`, `source_url`, `quality_report` fields (NULL on legacy rows).
- `POST /api/generate-abstract` — preserved for UI back-compat; now populates `source='generated'` and `quality_report` on every new row.
- Schema migration adds `source`, `source_url`, `quality_report` columns to `abstract_schedules` table.
- UI Quality card extended: source banner showing where the schedule came from, plus collapsible "Theoretical floor comparison" section with per-metric value/floor/distance/confidence table.
- `tests/test_canonical_library.py` — 50+ assertions covering save/load round-trip, missing-file handling, report shape, real-canonical round-trip.
- `docs/scheduler/canonical-library.md` — full documentation.

**v1.0 build budget**: 100K SA iterations × 3 seeds per shape (low for prototyping; production target is 500K-2M × 20+ seeds on Stark).

**Confidence achieved**:
- 36×7 cd=2: par_quad floor matched (252/252); opp_quad above floor → `best_known`
- 60×12 cd=2: par_quad floor matched (720/720); opp_quad above floor → `best_known`
- 24×8 cd=2: par_quad close but not at floor (198/192) → `best_known`
- 20×8 cd=2: par_quad close but not at floor (198/160) → `best_known` (surrogate handling validated)
- 12×6 cd=2: par_quad expected gap (192/84) due to cooldown=2 structural constraint → `best_known`

**Future work** (out of Phase B scope, scheduled for v1.1+):
- Higher-budget re-curation on Stark
- CP-SAT producer mode for small fixtures (proves optimality)
- DB migration per `abstract-library.md` workstream
- Comprehensive ~27-shape FRC plausible-shape inventory

---

### Phase C — Scoring framework ✓ COMPLETE (this session)

**Deliverables shipped:**
- `app/quality_scoring.py` — per-criterion 0-100 scoring + weighted composite
  - Per-metric curves: binary (cooldown), quadratic decay (par_quad/opp_quad), linear-bounded (rb/station/surrogate)
  - `DEFAULT_QUALITY_WEIGHTS` — FRC §10.5.2 priority-derived
  - `compute_scores()` — per-criterion + composite calculator
  - `best_known_floors_from_canonical()` — bridge to Phase B library for shape-aware scoring
  - Paramount gate: invalid schedules get composite=0
  - Weight normalization: clamping `[0, 5]`, cooldown auto-clamped ≥ 1, unknown keys ignored
- `app/quality_report.py` extended — `build_quality_report()` now embeds the full scoring data (`scores.composite`, `scores.per_criterion`, `scores.weights_used`, `scores.best_known_floors_used`)
- Schema migration: new `quality_weights` JSONB column on `abstract_schedules` (NULL = DEFAULT_QUALITY_WEIGHTS used)
- API:
  - `POST /api/schedules` and `POST /api/generate-abstract` accept `quality_weights` body field
  - **NEW** `POST /api/abstract-schedules/{id}/rescore` — re-score existing schedule under different weights without regenerating
  - `GET /api/abstract-schedules/{id}` returns `quality_weights` alongside `quality_report`
- UI Quality card extended:
  - **Composite score badge** with color-graded label (Excellent/Good/Acceptable/Poor/Paramount-invalid) and `[Weights]` button
  - **Quality weights editor panel** — 6 per-criterion sliders (range 0-5, step 0.1), "Reset to defaults" button, "Re-score" button that calls /rescore endpoint and updates display in place
  - **Score column** added to floor comparison table — color-coded per-criterion 0-100 score alongside achieved/floor/confidence
- All 5 canonicals rebuilt with Phase C scoring embedded
- `tests/test_quality_scoring.py` — 60+ assertions covering per-metric curves, weights normalization (clamping, defaults fill-in, cooldown auto-clamp), composite math, paramount gate, best_known_floors override, build_quality_report integration, real canonical re-scoring
- `docs/scheduler/quality-scoring.md` — full doc

**Phase D (standing eval suite) follows next.**

---

### Phase D — Standing eval suite ✓ COMPLETE (this session)

**Deliverables shipped:**
- `scripts/scheduler_eval/standards.py` — runnable script that exercises the production scheduler on the proving inventory, scores via Phase C, asserts hard requirements and soft thresholds. Reports JSON + Markdown. Exit code conveys verdict.
- `scripts/scheduler_eval/standards_config.py` — per-fixture bar definitions:
  - Hard requirements (paramount-valid, cooldown score = 100) apply to all fixtures
  - Soft thresholds (composite ≥ 80, per-criterion ≥ 50) overridable per-fixture
  - Per-fixture override examples for 12×6 (structural gap), 20×8 (surrogates), 36×7 (production shape), 60×12 (largest)
- `tests/test_standards_smoke.py` — wires-the-framework-together smoke test for CI
- `docs/scheduler/quality-standards.md` — full doc

**CLI features**: `--fixtures` subset, `--seeds` configurable, `--sa-iterations` configurable, `--strict` (CI mode: soft becomes hard), `--smoke` (single-fixture quick sanity), `--no-report` (skip file writes).

**Validated**: 12×6 cd=2 at 500K SA iter × 3 seeds reliably passes (composite=100); 36×7 at 200K × 2 seeds passes (composite=100). Smoke test exits cleanly. Real findings catalogued (rb_per_team / station_per_team_spread post-passes underconverge on large fixtures at default budgets).

**Phase D complete.** Schedule Quality Framework v1.0 is **fully shipped**: Phase A (floors), Phase B (canonical library + unified endpoint), Phase C (scoring + organizer-tunable weights), Phase D (standing eval suite).

---

## Roadmap items (v1.1+, not in v1.0 scope)

- **EPA / past-performance criterion**: strength-based pairing as
  an optional 7th criterion. Decision deferred.
- **Best-known floor tightening**: for shapes where par_quad/opp_quad
  count-floors are loose (e.g., 12×6 cooldown=2), derive tighter
  lower bounds from structural constraints OR run deep search to
  establish best-known achievable floors.
- **Full 27-shape canonical library**: after v1.0 proves the
  framework on 5 shapes, extend to the full plausible-FRC inventory.
- **FIRST adoption-ready packaging**: per D1, design choices keep
  this path open. Phase D's standing eval is a strong asset for
  this — proves the scheduler meets a measurable bar.

---

## Code references

- `app/quality_floors.py` — Phase A entry point
- `app/quality.py` — re-exports floors + existing quality machinery
- `docs/scheduler/quality-floors.md` — Phase A math + proofs
- `tests/test_quality_floors.py` — Phase A tests
- `app/canonical_schedules/` — Phase B target (doesn't exist yet)
- `scripts/scheduler_eval/standards.py` — Phase D target (doesn't exist yet)
