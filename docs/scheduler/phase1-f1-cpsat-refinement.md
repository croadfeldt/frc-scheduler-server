# Phase 1 — F1 follow-up: CP-SAT encoding refinement (and what it actually revealed)

**Date:** 2026-05-12
**Status:** Refined model built and measured. The encoding work didn't
move the needle on the hardest target case (12×6×2) — but the
comparison process surfaced a more important Phase 1 finding about
SA's failure on tight fixtures.

**Source:** `docs/workstreams/best-possible-schedule.md` Q2/Q4

---

## What we built (v2 model)

`scripts/cp_sat/pairing_optimum_v2.py` is a refined CP-SAT model
addressing three of v1's four suspected inefficiency sources:

1. **Tighter indicator encoding.** Replaced the v1
   `AddBoolAnd(...).OnlyEnforceIf(...)` pattern with direct linear
   reified constraints (`a ≤ b`, `a ≤ c`, `a ≥ b+c-1`). This is
   the standard CP-SAT idiom for boolean conjunction and produces
   tighter LP relaxations than the boolean-logic encoding.

2. **Linear histogram objective.** Replaced `AddMultiplicationEquality(par_quad_sq, [par_count, par_count])`
   with a histogram encoding: indicator variables
   `par_count_eq[(i,j), k]` = "pair (i,j) has count == k", with
   `Σ_k par_count_eq[k] = 1` per pair, and
   `par_quad = Σ_{pair,k} k² × par_count_eq[(pair,k)]`. This makes
   the objective a linear function of the indicators rather than a
   quadratic function of the counts.

3. **Anchor-based symmetry breaking.** Pin team 1 to play in match 0
   on side A. Breaks the (A/B) color-label symmetry (2× reduction)
   and partially breaks the team-1 placement symmetry over matches.

The fourth source (warm-start from SA output) was not implemented in
v2 — see "what we learned" for why.

A first attempt at full lex-ordering symmetry breaking (matches must
be in lexicographically non-decreasing order by team-membership
vector) was started but produced an over-constrained model that
returned INFEASIBLE on cases known to be feasible. Removed before
v2 was finalized.

---

## What we measured

Same three reference cases from v1, plus larger fixtures:

| Fixture | v1 result | v2 result | Notes |
|---|---|---|---|
| 6t × 4MPT × cd=1 | OPTIMAL in 6.4s | OPTIMAL in 3.8s (par_quad=48) | Modest 1.7× speedup |
| 6t × 6MPT × cd=1 | FEAS par_quad=96, bound=62 in 60s | FEAS par_quad=96, bound=53 in 60s | Same result; bound looser |
| 12t × 6MPT × cd=2 | FEAS par_quad=192, bound=— in 180s | FEAS par_quad=192, bound=36 in 180s | Same result |
| 14t × 6MPT × cd=2 | (not run) | FEAS par_quad=112, bound=8 in 30s | Lower par_quad than 12×6! |
| 16t × 6MPT × cd=3 | (not run) | INFEASIBLE in 1.2s | See Q5 refinement below |
| 16t × 6MPT × cd=2 | (not run) | FEAS par_quad=120, bound=8 in 30s | 36 pairs at 0; 72 at 1; 12 at 2 |
| 18t × 6MPT × cd=3 | (not run) | FEAS par_quad=288, bound=6 in 30s | |
| 20t × 6MPT × cd=3 | (not run) | FEAS par_quad=196, bound=6 in 30s | |
| 24t × 6MPT × cd=3 | (not run) | FEAS par_quad=144, bound=3 in 30s | |

**Key observations:**

- v2 is modestly faster than v1 on the easy case (1.7× on 6×4×1)
  but **finds the same solutions on the harder cases**.
- LP bounds are *looser* under v2's histogram encoding (53 vs 62 on
  6×6; 36 on 12×6 vs N/A in v1). The histogram trades bound-
  tightness for tractability. The bound is *correct* (still a valid
  lower bound) but less informative.
- v2 finds feasible solutions on fixtures up to 24 teams within 30s,
  but doesn't prove optimality on any beyond 6×4×1.

---

## What the refinement didn't fix

**v2 is still stuck at par_quad=192 on 12×6×2** — same as v1, same
distribution (36 pairs at 0, 4 at 1, 12 at 2, 12 at 3, 2 at 4).
The encoding refinements help the model compile faster but don't
solve the underlying combinatorial difficulty.

The theoretical optimum on 12×6×3-tpa is approximately par_quad ≈
84 (60 pairs at 1, 6 pairs at 2, all under floor). CP-SAT (v1 or v2)
isn't reaching it.

The bottleneck isn't model size or quadratic encoding — it's the
combinatorial search space. The standard CP-SAT machinery
(no_overlap, cumulative, etc.) doesn't have natural primitives for
"minimize pair-distribution variance" objectives. Symmetry breaking
beyond simple anchoring is non-trivial here.

---

## What the refinement attempt actually revealed (the bigger finding)

While trying to compare v2 against the SA on 12×6×2, I discovered:

**The SA cannot achieve cooldown=0 on 12×6×2.**

Across 18 trials of SA=500K and 5 trials of SA=2M with the
ConstructionMalformedError retry from F2:

- Best SA result on 12×6×2: par_quad=116, **cooldown_violations=31**
- CP-SAT result: par_quad=192, **cooldown_violations=0**

The cooldown=2 constraint on 12×6 *is* mathematically feasible
(every-other-match pattern: 0, 2, 4, 6, 8, 10 — verified by Q5
formula and by CP-SAT finding feasible). But our SA cannot find a
valid schedule.

CP-SAT's par_quad=192 is *worse* than SA's par_quad=116 on this
fixture — but **CP-SAT's schedule is valid (cooldown=0) while
SA's is not (cooldown=31)**. The lex tuple comparison is:
- SA:    (31, 116, 268, ...) — fails the paramount cooldown criterion
- CP-SAT: ( 0, 192, 408, ...) — satisfies paramount, worse on pairing

Per ADR 002 (paramount cooldown), CP-SAT wins decisively. The SA is
producing schedules that don't satisfy FRC §10.5.2's first priority
criterion on tight fixtures.

This is much bigger than F1's stated scope. It's direct Phase 1 Q4
data:

> **On tight fixtures, the SA-on-greedy-construction architecture
> cannot satisfy the paramount cooldown constraint, even with
> high budgets. CP-SAT can.**

The architectural implication is clear: for fixture sizes where
CP-SAT terminates (even just to FEASIBLE), CP-SAT should be the
construction tool, with SA as the optimization layer on top.

---

## What v2 tells us about the CP-SAT frontier

Beyond the 12×6 case, v2 demonstrates that CP-SAT can find feasible
schedules in 30s for fixtures up to 24 teams × 6 MPT. **The
"frontier" question (Q2) needs to be split into two:**

1. **The "feasibility frontier"** — how large a fixture can CP-SAT
   find ANY valid schedule for in reasonable time? Answer (v2): at
   least 24 teams × 6 MPT in 30s. Plausibly higher with more time.

2. **The "optimality frontier"** — how large a fixture can CP-SAT
   *prove* optimal in reasonable time? Answer (v1+v2): 6 teams × 4
   MPT × cd=1 was the only proven-optimal case. Everything larger
   times out with a feasibility-only answer.

The feasibility frontier matters more for the Q4 architectural
question. If CP-SAT can find ANY valid schedule on FRC-common
fixtures, it can serve as the construction step (replacing greedy)
even without optimality. SA then refines from CP-SAT's starting
point.

The optimality frontier matters for the "best possible" goal of
this workstream. For very small fixtures (6t-12t), CP-SAT-direct is
plausible. For larger, hybrid (CP-SAT construct + SA refine) is the
likely path.

---

## Refined Q5 finding: formula gives necessary but not always sufficient feasibility

The Q5 cooldown_max formula:
```
cooldown_max = floor((M - 1) / (MPT - 1))
```
gives a **necessary** condition for feasibility. It's not always
sufficient.

Counter-example surfaced this session: 16t × 6MPT × cd=3.
- Formula: M = 16, cooldown_max = (16-1)/(6-1) = 3.0
- CP-SAT: INFEASIBLE

Why: at cd=3 with M=16 and MPT=6, the only play pattern yielding
exactly 6 plays in 16 slots is `[0, 3, 6, 9, 12, 15]` (forced exact
spacing). Patterns starting at index 1 or 2 yield only 5 plays before
running out of slots. So all 16 teams would need the same pattern,
but a match has only 6 slots — infeasibility.

The general issue: at cooldown_max boundary, the *number of distinct
play patterns* yielding MPT plays may be much smaller than n_teams,
forcing infeasibility even though span fits.

**Implication for Q5:** the formula is a screening check but not a
guarantee. CP-SAT or careful additional combinatorics is needed for
true feasibility verification at the cooldown_max boundary. Most
fixtures comfortably below cooldown_max are unaffected; only
boundary cases need this care.

`scheduler/phase1-q5-cooldown-feasibility.md` should note this
caveat.

---

## What this means for the Phase 1 plan

Three updates to the workstream's open questions:

**Q2 (CP-SAT frontier):** Two-tier answer needed. Feasibility
frontier (24+ teams achievable in 30s). Optimality frontier (~6
teams). The optimality frontier is too small for direct use; the
feasibility frontier is large enough to be useful as a construction
primitive.

**Q4 (two-stage architecture):** The data strongly suggests
**replacing greedy construction with CP-SAT for tight fixtures**
where SA cannot achieve cooldown=0. For larger fixtures (>24 teams)
where CP-SAT doesn't reach feasibility in reasonable time, keep
greedy+SA. The threshold needs measurement but the architectural
shape is clearer.

**Q1 (lex tuple shape):** This work didn't address Q1 directly, but
revealed that **the lex tuple as currently scored is misleading**:
the SA's "best" result of par_quad=116 with cooldown=31 is *worse*
than CP-SAT's par_quad=192 with cooldown=0, per the paramount-
cooldown lex rule. Either:
  (a) the SA's tuple comparison is doing the right thing but the
      SA itself isn't finding cooldown=0 schedules, OR
  (b) the SA's tuple comparison is doing the wrong thing.

Need to check the SA's tuple-comparison logic to make sure
paramount-cooldown is actually being respected during accept/reject.

---

## Open follow-ups (updated)

- **F1-a.** Audit the SA's accept/reject logic to confirm
  paramount-cooldown is treated as strictly dominant. If it is and
  SA still can't find cooldown=0 on 12×6×2, then it's a search-
  space problem (the SA's moves can't reach cooldown=0 from its
  starting state).
- **F1-b.** Try warm-starting CP-SAT with CP-SAT-generated feasible
  solutions on each progressively-larger fixture (sequential
  decomposition). May extend the feasibility frontier.
- **F1-c.** Build a CP-SAT-as-construction prototype: solve to
  feasibility with CP-SAT, then hand off to SA for pairing
  optimization. Compare against SA-on-greedy.
- **F1-d.** Update `scheduler/phase1-q5-cooldown-feasibility.md`
  with the boundary-infeasibility caveat.

---

## Honest summary

F1 as scoped (encoding refinement) achieved modest gains on easy
cases and no measurable improvement on hard cases. The biggest
insight didn't come from the refinement itself but from running
CP-SAT and SA against each other on the 12×6×2 problem:

**On tight fixtures, our SA cannot satisfy the FRC §10.5.2
paramount cooldown criterion. CP-SAT can — even with sub-optimal
pairing. The architectural answer for Q4 is becoming clear: CP-SAT
construction for tight fixtures, SA refinement on top.**

The F1 work isn't a failure; it's how the question reframed. F1's
encoding work also produced data points on fixtures from 14-24
teams that v1 hadn't measured, giving us a real CP-SAT feasibility
frontier (~24 teams at 30s).
