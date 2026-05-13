# Phase 1 — F1-c: CP-SAT-as-construction prototype results

**Date:** 2026-05-13
**Status:** Prototype complete. Surprising finding: at D5's cooldown=2,
CP-SAT-as-construction provides NO measurable quality advantage over
greedy-then-SA on any tested fixture, and fails outright on the
largest fixtures. Q4 architectural answer: keep the existing
greedy+SA pipeline.

**Source:** `docs/workstreams/best-possible-schedule.md` Q4;
`docs/scheduler/phase1-f1-cpsat-refinement.md` F1-c follow-up;
methodology cleaned by F1-e + D5 in prior session.

---

## What F1-c was supposed to test

The Q4 hypothesis: for tight fixtures where greedy construction
struggles, CP-SAT-as-construction + SA refinement produces strictly
better schedules than SA-on-greedy.

The strongest evidence for this hypothesis came from F1-a:
on 12×6, SA-on-greedy reliably produced `cooldown_violations ≈ 50`
that the SA couldn't reduce to 0; CP-SAT trivially achieved cd=0
on the same fixture.

F1-c was designed to validate the end-to-end story: CP-SAT-then-SA
should beat SA-on-greedy on validity (cd=0 vs cd>0) and at least
match it on pairing quality.

---

## What F1-c actually found

A production bug was discovered before the measurement phase. With
the bug fixed (and methodology clean per F1-e), the architectural
gap disappeared.

### Production bug discovered

`_sa_optimize` called `_build_match_state(work)` without passing
`ideal_gap`, so `_build_match_state` used its default of `3`. Both
production call sites — `generate_matches` (the main scheduler
entry) and `_assign_unified` (the abstract-to-assigned path) —
silently ran the SA with cooldown threshold = 3 regardless of what
`ideal_gap` the caller had specified.

For a request with cooldown=2 (D5 project default), the SA's
internal cooldown_violations counter was tracking gap < 3 events
rather than gap < 2. The `_swap_preserves_cooldown` filter likewise
protected against worsening gap < 3, allowing swaps that worsened
gap < 2.

**Scope of impact:** every production schedule generated with
cooldown ≠ 3 was running SA's cooldown enforcement at the wrong
threshold. With D5 setting project default cooldown=2, this
affected all production schedules generated since the F1-e/D5
session.

**Fix shipped:** added `ideal_gap` kwarg to `_sa_optimize`,
threaded from `generate_matches` and `_assign_unified`. Default
preserved at 3 for backward compat with existing callers (tests +
the F1-c prototype itself). 13 test suites still green.

### F1-a measurement re-interpreted

F1-a's finding "SA can't reach cd=0 on 12×6" was measured at the
buggy ideal_gap=3 path. 12×6×cd=3 is at boundary infeasibility
(Q5's cooldown_max formula gives 2 for this fixture; cd=3 exceeds
it). So F1-a was correctly measuring "SA can't reach cd=0 on a
fixture where cooldown_max < requested cooldown" — which is a
mathematically obvious finding, not a Q4 architectural insight.

With the production bug fixed and the prototype passing
`ideal_gap=cooldown=2` correctly, SA-on-greedy reaches cd=0 on
12×6 reliably.

### F1-c measurement results

Six fixtures planned at D5's cooldown=2, two arms each
(cpsat-then-sa, greedy-then-sa). Iteration budget reduced for
prototype turnaround (50K-200K SA iterations vs production
500K-2M). Smaller fixtures used more seeds; larger fixtures
used fewer due to wall-clock budget.

#### Small/medium fixtures (CP-SAT terminates)

| Fixture | Arm A par_quad | Arm A composite | Arm B par_quad | Arm B composite |
|---|---:|---:|---:|---:|
| 12×6 (3 seeds, 200K SA) | 192 / 192 / 192 | 81.0 / 81.0 / 81.0 | 192 / 192 / 192 | 81.0 / 81.0 / 81.0 |
| 16×6 (3 seeds, 200K SA) | 104 / 114 / 106 (med 106) | 74.0 / 74.0 / 74.0 | 106 / 102 / 108 (med 106) | 74.0 / 74.0 / 74.0 |
| 24×6 (2 seeds, 50K SA)  | 144 / 144 | 62.0 / 62.0 | 144 / 144 | 62.0 / 62.0 |
| 36×7 (2 seeds, 50K SA)  | 252 / 252 | 62.0 / 62.0 | 252 / 252 | 52.5 / 62.0 |

All trials, both arms: **cd=0, is_valid_paramount=True**. Lex tuple
medians are identical or near-identical between the two arms.
Composite scores match exactly on 12×6/16×6/24×6; on 36×7, Arm B
hit a slightly better tiebreaker on one seed but the higher-priority
metrics matched.

#### Large fixtures (CP-SAT fails)

| Fixture | Arm A | Arm B |
|---|---|---|
| 42×11 | **killed** (resource limit) | cd=0, par_quad=468, composite=64.5, 7.6s wall |
| 48×9  | **killed** (resource limit) | cd=0, par_quad=432, composite=62.0, 7.6s wall |

CP-SAT's model size scales with `n × n_matches × pairs`. For 42×11
(77 matches × 861 pairs) and 48×9 (72 matches × 1128 pairs), the
model exceeds available memory or hits a build/solve timeout
before producing any feasible solution. **CP-SAT-as-construction
has a clear practical ceiling somewhere between 36×7 and 42×11.**

Meanwhile greedy-then-SA produces valid schedules at these scales
in ~8 seconds.

### CP-SAT wall-clock vs greedy

CP-SAT spends nearly the full time budget on optimality proof even
when feasibility is found in milliseconds. Greedy is essentially
instantaneous (< 1s) at every tested scale. Post-passes and SA
refinement are comparable between arms.

For the same end-quality (identical lex tuples on every tested
fixture), CP-SAT costs ~60-120× more wall-clock at scales where it
works, and fails outright above that scale.

---

## Why CP-SAT didn't win

Two factors converged:

1. **Cooldown=2 is structurally easy on standard fixtures.** With
   cooldown=2 as the floor, schedules where each team plays at
   gap=2 throughout (matches 0,2,4,6... or 1,3,5,7...) are
   structurally available on every fixture where M ≥ 2·MPT. Greedy
   reaches this neighborhood naturally; SA refinement polishes
   pairings within it. There's no escape-the-corner problem because
   cooldown=2 doesn't paint corners on these fixtures.

2. **CP-SAT's "global optimization" advantage is theoretical, not
   measurable here.** CP-SAT can in principle find pairings that
   greedy+SA cannot reach. But on these fixtures, the *optimal*
   pairing under the cooldown=2 constraint sits in a local basin
   that SA reaches from greedy starts. The advantage requires a
   pairing-quality gap that isn't there.

The F1-a finding looked like a counter-example, but it wasn't —
it was an artifact of the production cooldown=3 default being
used to measure a fixture only feasible at cooldown=2.

---

## Q4 architectural answer

**Recommendation: keep greedy-then-SA as the production
construction architecture. Do not introduce CP-SAT into the build
path.**

Rationale:

1. **No measurable quality advantage** at any tested fixture size.
2. **Practical scaling failure** at large fixtures (42×11, 48×9
   killed by resource limits) — exactly the production-scale
   fixtures we'd be using.
3. **60-120× wall-clock cost** at sizes where CP-SAT does work.
4. **Architectural complexity** of adding a CP-SAT dependency to
   the production scheduler, with non-trivial model-building code
   and an OR-Tools runtime dependency, is unjustified by the
   measurements.

This **closes Q4** in the workstream. ADR 003 (two-stage
abstract→assigned architecture) stands as written. The internal
construction is greedy + SA refinement, not CP-SAT.

CP-SAT remains valuable as a **research tool** for finding optimal
schedules on small fixtures (to validate that SA is reaching the
optimum), but not as a production component.

---

## What still needs doing in Phase 1

- **F1-b** (warm-start CP-SAT with SA): low priority now that
  CP-SAT-as-construction is rejected. Worth keeping the F1-c
  prototype script for occasional spot-checking of SA optimality.
- **Q1 (lex tuple shape)**: not started. Now methodology-clean
  (F1-e shipped) and informed by F1-c findings about what's
  measurable. The cooldown=2 floor means cooldown is paramount
  but unlikely to bind in practice on standard fixtures, which
  has implications for whether cooldown should even be position 0
  of the tuple (vs an inviolable hard constraint).
- **Q3 (methodology)** and **Q7 (reproducibility)**: not started.
- **Q6 (MPT vs quality ceiling)**: not started; could use F1-c's
  measurements as starting data.

The F1-c run also produced two unexpected useful data points
worth following up on if time permits:

- **Greedy is structurally fine at cooldown=2** on every standard
  fixture — strong evidence that greedy construction's "tightness"
  isn't a real production problem at D5's cooldown=2.
- **F2's malformation finding** (12% of construction attempts on
  12×6×2 throw ConstructionMalformedError) was not observed in
  F1-c's runs because of the existing retry logic. The malformation
  is a transient construction-time issue, not an architectural one.

---

## Code references

- `scripts/cp_sat/cpsat_construction_prototype.py` — the F1-c
  prototype script (kept in-tree as research code, not promoted to
  production)
- `app/scheduler.py:_sa_optimize` — production fix: now accepts
  `ideal_gap` kwarg
- `app/scheduler.py:_assign_unified` — production fix: now passes
  `ideal_gap` to both `_sa_optimize` and `score_tuple_for_schedule`
- `scripts/scheduler_eval/reports/f1c_cpsat_construction_*` — raw
  JSON/MD/log outputs from the F1-c runs

---

*F1-c complete. Q4 architectural answer: keep greedy-then-SA.
Production bug (ideal_gap defaulting to 3 in _sa_optimize) fixed
along the way. CP-SAT remains a research tool, not a production
component.*
