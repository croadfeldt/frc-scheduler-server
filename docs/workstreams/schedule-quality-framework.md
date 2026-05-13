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

### Phase B — Canonical schedule library

**Goal:** For each fixture in the proving inventory, find and cache
the best-known schedule. Tag each with achievability confidence.

**Tasks:**
- Build a producer script that, given a fixture shape, runs a deep
  search (CP-SAT for small fixtures with optimality proof; large-
  budget SA for large fixtures with best-known confidence).
- Cache schedules as JSON files in `app/canonical_schedules/`,
  named by shape (e.g., `12x6_cd2.json`, `60x12_cd2.json`).
- Each canonical entry includes:
  - The schedule matches
  - Achieved lex tuple
  - Achieved per-metric values
  - Floors for the fixture
  - Distance-from-floor per metric
  - Generation methodology + provenance
  - Confidence: `proven_optimal` if CP-SAT proved it, `best_known`
    otherwise
- API extension: `GET /api/canonical-schedules?n=12&mpt=6&cooldown=2`
  returns the cached canonical when available.
- Tests: each canonical's stored values match recomputation;
  proven_optimal entries actually meet their floors.

**Proving inventory (build first):**
1. 12×6×3 cooldown=2 — small, CP-SAT-provable, structurally tight
2. 24×8×3 cooldown=2 — medium, CP-SAT-provable
3. 36×7×3 cooldown=2 — medium-large, 2026mnst shape
4. 20×8×3 cooldown=2 — exercises surrogate code path
5. 60×12×3 cooldown=2 — large, CP-SAT-infeasible

**After proving:** scale to the full 27-shape inventory.

---

### Phase C — Scoring framework

**Goal:** Convert per-fixture floors + observed metrics into
human-interpretable 1-100 scores. Let organizers weight criteria
per their event's priorities.

**Tasks:**
- Distance-from-floor function: maps each metric's observed value
  + floor to a per-criterion 1-100 score. 100 = meets floor;
  approaches 0 as the gap widens. Specific scaling per metric
  (linear vs. quadratic decay, capping).
- Weights dict: `{"cooldown": 1.0, "partner": 1.0, "opponent": 1.0,
  "color": 0.5, "station": 0.5, ...}` — organizer-supplied,
  defaulting to FRC §10.5.2 priority-derived weights.
- Composite: weighted average of per-criterion scores.
- API: extend `AssignRequest` with `quality_weights` dict; return
  per-criterion scores + composite in the response.
- UI: display per-criterion scores in the Quality card; expose a
  weights editor for organizers.

**Open question for Phase C kickoff:**
- For metrics where the floor is `proven_lower_bound` (par_quad,
  opp_quad), should the scoring use the floor (which may be
  unachievable) or the best-known canonical (always achievable)?
  Argument for floor: principled, fair across methods. Argument
  for best-known: rewards matching what's actually achievable
  rather than punishing for unreachable ideals.
  Lean: use the floor; the score reflects distance from
  *mathematical* optimum, not distance from someone else's effort.

---

### Phase D — Standing eval suite

**Goal:** Catch production scheduler regressions and provide a
single-command "does this method meet the bar" report for any
candidate scheduling method.

**Tasks:**
- Test/CLI: `scripts/scheduler_eval/standards.py` runs the
  production scheduler on each fixture in the proving inventory,
  scores via Phase C framework, asserts pass/fail.
- Pass criterion: per-fixture per-criterion thresholds (default:
  every criterion ≥ 80/100). Configurable per fixture.
- CI hook: optional — production-scheduler regressions caught
  before merge. Likely too slow for every commit; gates major
  releases instead.
- Output: structured JSON report + Markdown summary; can be
  pointed at any adapter (current production, prototype, etc.)
  for fair comparison.

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
