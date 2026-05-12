# Phase 1 — Q2 first-cut findings

**Date:** 2026-05-11
**Status:** Initial CP-SAT formulation built and measured. Findings
inform the next iteration; do not yet answer Q2 fully.

**Script:** `scripts/cp_sat/pairing_optimum.py`
**Source:** `docs/workstreams/best-possible-schedule.md` Q2

---

## What was built

A first-cut CP-SAT model for the Stage 1 pairing problem. Decision
variables: `in_match[m, t]` (team t plays match m), `on_side[m, t]`
(arbitrary side-label, decoupled from red/blue since pairing is
color-symmetric), and derived `partner[m, i, j]` / `opponent[m, i, j]`
indicators per match-pair. Objective: minimize `par_quad` (sum of
squared partner counts).

The formulation deliberately ignores red-vs-blue color identity and
station positions — both are commutative with pairing per the
existing post-pass architecture, so they're solved separately.

R/B and station optimization will be a separate CP-SAT formulation
in a follow-up. This first run targets the *pairing* sub-problem
specifically.

---

## What was measured

Three fixture shapes, all with `tpa=3`:

| Fixture | cooldown | Time limit | Result | par_quad (best found) | par_quad (LP bound) | Notes |
|---|---:|---:|---|---:|---:|---|
| 6t × 4MPT | 1 | 30s | **OPTIMAL** | 48 | — | Proven optimal in 6.4s |
| 6t × 6MPT | 1 | 60s | Feasible | 96 | 62 | LP bound loose; true optimum likely 90 |
| 8t × 6MPT | 2 | 120s | Infeasible | — | — | Cooldown too tight: 6 plays in 8 matches with gap≥2 has no schedule |
| 12t × 6MPT | 2 | 60s | Feasible | 192 | — | Same answer at 60s and 180s — solver stuck |
| 12t × 6MPT | 2 | 180s | Feasible | 192 | — | No improvement vs 60s budget |

---

## What the data says

### CP-SAT can prove optimal on very small fixtures

6t × 4MPT terminated with OPTIMAL status in 6.4 seconds. That's the
proof-of-concept: the model is correct, the solver finds and proves
optima when the search space is small enough.

### Feasibility constraints rule out some fixture/cooldown combinations entirely

The 8t × 6MPT × cooldown=2 case is mathematically infeasible: with 6
plays in 8 matches and minimum gap of 2 between plays, the team must
have plays at positions where p_{k+1} ≥ p_k + 2, requiring a span of
≥ 10 across 6 plays — but max span is 7 (match indices 0..7). This
matches FRC manual section 10.6.6 small-event exception: very small
events allow back-to-back matches.

**Implication:** Q5 (cooldown's role in shaping the solution space)
has concrete data here. Cooldown is not just a soft preference — it
can render entire fixture shapes infeasible. Q5 needs to map the
(n, MPT, cooldown) feasibility boundary alongside the FRC manual's
per-event-size cooldown specifications.

### The model scales poorly even at modest sizes

12 teams × 6 MPT did not improve from 60s to 180s. The solver found
`par_quad = 192` early and never beat it within the budget.
Meanwhile, the theoretical lower bound is much tighter than the LP
relaxation reports (LP gave 62; the true optimum is closer to ~110
based on counting).

**The discrepancy between the SA-tuple values and the achievable
ones is large:**

- 12t × 6MPT theoretical: total par-encounters = 12×6×2/2 = 72
  across 66 pairs. Floor-distribution: 60 pairs at 1, 6 pairs at 2
  → par_quad = 60 + 24 = 84.
- 12t × 6MPT CP-SAT result: par_quad = 192 (distribution skewed
  toward many 3-count and 4-count pairs).

Either:
1. The SA on this fixture actually does *worse* than CP-SAT's 192
   (haven't measured — our SA has a known bug at this fixture size
   that prevented direct comparison this session).
2. The optimum is achievable but CP-SAT isn't reaching it due to
   model-encoding inefficiency.
3. The optimum is genuinely closer to 192 than 84 (in which case
   the theoretical-floor calculation needs revisiting for forced-
   repeat cases like this).

Option 2 is most likely given the LP bound is loose. Options 1
and 3 are worth investigating but lower priority.

### Sources of inefficiency in the current model

The model has at least four likely sources of slow convergence:

1. **Symmetry not broken.** Match ordering, team relabeling, and
   side-A/side-B labeling are all currently free. The solver
   explores many equivalent schedules redundantly.

2. **Boolean-AND-with-enforce-if encoding.** The current
   formulation uses many `AddBoolAnd([a, b]).OnlyEnforceIf(c)`
   patterns. CP-SAT prefers direct linear reified constraints
   (`c ↔ a + b ≥ 2` etc.) for tighter LP relaxations.

3. **Quadratic objective via `AddMultiplicationEquality`.** Each
   pair gets a multiplication constraint. For 66 pairs × 2 (par +
   opp), that's 132 quadratic constraints. There are tighter
   encodings (channeling integer counts directly through a
   pre-computed lookup table for small max-count values) that
   could replace these.

4. **No warm start.** CP-SAT has no good initial solution to
   compare against. Seeding it with our SA's best output would let
   it focus on improving rather than discovering structure.

---

## What this means for Q2

The frontier of CP-SAT applicability for this problem may be **much
smaller than initially hoped** if the current encoding represents
the best we can do. Specifically:

- **6 teams (any MPT):** CP-SAT proves optimal in seconds.
- **12 teams (low MPT):** CP-SAT finds feasible solutions but
  doesn't prove optimal within minutes. Probably reachable with
  encoding work + symmetry-breaking + longer time budget.
- **24+ teams:** Almost certainly out of CP-SAT's reach for proven
  optimality, regardless of encoding work, given the explosion in
  search space.

The Q2 investigation should not declare the frontier yet. The next
step is **encoding refinement**: rewrite the model with
symmetry-breaking, direct reified constraints, and warm-starting
from SA output. *Then* re-measure the frontier.

Estimate for encoding refinement: ~2-3 days of CP-SAT modeling work.

If the refined encoding pushes the frontier to ~24 teams (the
practical small-FRC-event size), CP-SAT is genuinely useful for
small fixtures and the project gains a real "provable optimum"
capability for those. If the refined encoding doesn't improve much
beyond 12 teams, CP-SAT's role narrows to "proof of correctness on
toy fixtures" — useful for algorithm validation but not for
production use.

Either outcome is informative for Q2.

---

## Open follow-ups

- **F1.** Refine the CP-SAT encoding (symmetry-breaking, reified
  constraints, warm-start) and re-measure the frontier.
- **F2.** Investigate the SA bug at 12t × 6MPT
  (`IndexError: tuple index out of range` in `_is_valid_swap`)
  — likely an unrelated regression worth fixing.
- **F3.** Add a CP-SAT formulation for the R/B + station post-passes
  (separate sub-problem; commutative with pairing).
- **F4.** Q5 data point captured: cooldown can be infeasibility-
  inducing. Document the (n, MPT, cooldown) feasibility boundary
  alongside the FRC §10.5.2 minimum-cooldown table.

---

## Next session

Pick from F1-F4 based on priority. F1 is the natural continuation if
we want a real Q2 answer; F2 is small and unblocks comparison; F3
expands the CP-SAT coverage to the rest of the lex tuple; F4 is
documentation only and can happen anytime.

My recommendation: **F1 first.** The Q2 answer depends on knowing
the frontier with a properly-encoded model, not the rough first-cut
encoding. ~2-3 days of work.
