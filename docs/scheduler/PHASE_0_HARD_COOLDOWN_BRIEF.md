# Phase 0 — Hard Cooldown Constraint: Implementation Brief

**Repository:** `github.com/croadfeldt/frc-scheduler-server`
**Target branch:** `cooldown-hard` (cut from `main`)
**Estimated effort:** 2–4 hours implementation + comparison runs
**Risk level:** Low — narrow, decomposable change with measurable correctness criteria
**Status:** **Proposal — paused.** Scheduler change-freeze in effect during the live event. The brief is implementation-ready, but no scheduler code changes ship until the freeze lifts. See `docs/HANDOFF.md` for current operational guidance.

---

## Context for the implementing session

This repo is a two-stage FRC qualification match scheduler. Stage 1 generates an abstract slot-based schedule; Stage 2 does simulated annealing to assign real teams into slots. The defaults are aligned with the FRC manual's six §13.6.2 criteria, and `docs/PRIORITIES.md` documents that alignment criterion-by-criterion.

We've completed a review of the current implementation against the manual's criteria and identified six concrete opportunities to strengthen the scheduler. **This brief covers Phase 0 only** — the smallest of those, fixing a documentation truthfulness issue. Future phases will be issued as separate briefs after Phase 0 lands and we measure outcomes. See `SCHEDULER_QUALITY_ROADMAP.md` for the full phase plan.

---

## The problem

`docs/PRIORITIES.md` lists priority **P4 (Cooldown)** as a **Hard** constraint with weight `−1000 × deficit`. The label and the implementation contradict each other:

- A "hard" constraint means a violating schedule cannot be produced — the move generator filters violations out before they're considered.
- A `−1000 × deficit` weight means violations are *penalized very heavily in the score function*, but the SA can technically still produce or accept a violating schedule if the rest of the score pushes hard enough in the other direction.

At default weights (W_PARTNER=80, W_OPPONENT=60, etc.) the soft penalty is heavy enough that violations are vanishingly rare. But:

1. The documentation is untrue as written.
2. With pathological user weight overrides (e.g., W_PARTNER=10000) the soft penalty can lose.
3. Enforcing this constraint structurally is a prerequisite for several downstream improvements where we want the SA's score function to focus on pairing diversity without competing with constraints that should be filtered out before scoring.

---

## The change

Convert cooldown from soft penalty to hard rejection in both the SA move generator and the initial-state generators. Remove the cooldown term from the score function once it's structurally unreachable.

### Files to modify

The implementing session should locate and edit:

- `app/scheduler.py` — primary target. Contains:
  - `generate_matches(...)` — Stage 1 abstract schedule generator
  - `assign_teams(...)` — Stage 2 simulated annealing
  - `delta_swap(...)` — incremental score delta for proposed swaps
  - `build_score_state(...)` — full rescore on iteration start
  - Score function (location of the `−1000 × deficit` term)

- `docs/PRIORITIES.md` — update the P4 row and any prose that references the `−1000 × deficit` weight to reflect the new hard-constraint reality.

- Any URL parameter / weight-override wiring that currently exposes a configurable cooldown weight — the cooldown threshold remains configurable, but its enforcement weight no longer exists as a tunable.

### Implementation guidance

1. **Initial-state generators (Stage 1 + Stage 2 seed builders):** When constructing the initial permutation, reject any placement that would put a team in a match within `cooldown` matches of its previous appearance. If the constructor backs into a corner where no valid placement exists for the current match, the existing fallback / retry logic should handle it — but flag with a clear error if the cooldown is mathematically unsatisfiable for the given (N, MPT, cooldown) combination (e.g., cooldown ≥ ⌈N/6⌉ for typical configurations).

2. **`delta_swap` move filter:** Before computing the score delta for a proposed 2-swap, check whether the swap would push any team's match-to-match gap below `cooldown`. If yes, return a sentinel (e.g., `None` or `float('inf')`) that the SA loop interprets as "reject without scoring." This must run *before* the delta computation so we don't waste cycles scoring invalid moves.

3. **Score function:** Remove the `−1000 × deficit` term. The cooldown column / counter in `build_score_state` is no longer needed for scoring — but the *gap data* it tracks may still be needed by the move filter. Refactor so the gap state is maintained for filtering, but doesn't contribute to score.

4. **SA loop:** Account for the fact that some proposed moves now return early (rejected by filter rather than rejected by acceptance probability). This shouldn't change correctness — the SA still terminates on iteration count — but log the filter-rejection rate alongside the existing acceptance rate so we can see how often the filter is engaging.

5. **Edge case — Phase 1 of Stage 1:** Phase 1 (round 1) places every slot exactly once before any plays twice, so no cooldown can be violated within Phase 1 by construction. Phase 2 (open scheduling) is where the filter does real work. Make sure the filter is engaged in Phase 2's "60 random candidate sets per match" generator — each candidate must satisfy cooldown, not just the chosen one.

### Documentation update

In `docs/PRIORITIES.md`, the P4 row currently reads:

> | P4 | Cooldown | **Hard** | −1000 × deficit | Slot cannot replay within cooldown matches of last appearance |

Update to:

> | P4 | Cooldown | **Hard** | — (structural) | Move generator and initial-state generator reject any placement that violates minimum match separation. Cannot be produced. |

Remove any prose that describes cooldown as a weighted term in the score function. Add a short note in the "FIRST Alignment" section that P4 is now structurally enforced — schedules violating minimum match separation cannot be produced.

---

## Acceptance criteria

The PR must demonstrate all of:

1. **Zero violations across a fuzz corpus.** Run schedule generation 200 times with randomized `(N, MPT, cooldown, seed)` parameters drawn from realistic ranges (N: 24–80, MPT: 8–14, cooldown: 1–5). For each generated schedule, assert that every team's match-to-match gap is `≥ cooldown`. Zero violations expected.

2. **Pathological weight robustness.** Run generation with `W_PARTNER=10000` (or any weight 100× the default) and the same fuzz corpus. Zero cooldown violations expected. This is the case where the old soft-penalty implementation could leak through; the new hard implementation cannot.

3. **Default-config schedule equivalence.** For 10 fixed `(seed, N, MPT, cooldown)` tuples at default weights, schedules generated by the new implementation should be effectively identical to those generated by the old implementation. "Effectively identical" means: same total match count, same surrogate set, partner-repeat distribution within ±1 over-floor pair, opponent-repeat distribution within ±1 over-floor pair. (Exact identity is not expected because the score function changed; near-identity confirms we didn't break the optimization at default settings.)

4. **Documentation truth.** `docs/PRIORITIES.md` no longer claims a weight for P4. Reading the doc should match what the code does.

5. **Performance non-regression.** Median wall-clock for Stage 2 generation at `(N=51, MPT=11, cd=3, default weights)` should not increase. Filter rejection happens before scoring, so per-iteration cost should be flat or slightly lower.

---

## Comparison harness — for tangible-benefit assessment

This is the part Chris specifically wants to evaluate. Build the comparison artifact as part of the PR so the schedules can be diffed directly.

### Test scenarios

Run each scenario on **both** the pre-change `main` and the post-change `cooldown-hard` branch. Capture outputs as committed artifacts under `tests/phase0_comparison/`.

| Scenario | Params | Why |
|---|---|---|
| **A — Realistic small** | N=36, MPT=10, cd=3, seed=`a1b2c3d4`, default weights | Typical district event size; expect identical schedules |
| **B — Realistic large** | N=60, MPT=12, cd=4, seed=`deadbeef`, default weights | Typical regional event size; expect near-identical schedules |
| **C — Pathological weights** | N=51, MPT=11, cd=3, seed=`cafebabe`, W_PARTNER=10000, W_OPPONENT=8000 | Where soft penalty may have leaked; expect old implementation to produce violations, new to produce zero |
| **D — Tight cooldown** | N=24, MPT=12, cd=4, seed=`12345678`, default weights | Edge case where the filter does real work; expect new implementation to converge to a clean schedule that may differ structurally from old |

### Artifacts to capture per scenario

For each (scenario, branch) combination, commit to `tests/phase0_comparison/{scenario}/{branch}/`:

1. `schedule.csv` — full match list: `match_num,red1,red2,red3,blue1,blue2,blue3,is_surrogate_*` columns
2. `diversity_report.json` — output of the existing `/api/abstract-schedules/{id}/diversity-report` endpoint
3. `gap_distribution.csv` — for each team, list of all match-to-match gaps; include min, mean, count-below-cooldown
4. `metrics.json` — headline numbers: total over-floor partner pairs, total over-floor opponent pairs, max station imbalance, surrogate count, surrogate distribution, alliance imbalance per team
5. `wall_clock.txt` — median over 5 runs for Stage 2 at the scenario's iteration budget
6. `filter_stats.json` (new branch only) — filter rejection rate, acceptance rate, total iterations

### Comparison output

Generate `tests/phase0_comparison/SUMMARY.md` containing one section per scenario, each with:

- Side-by-side metrics table (`main` column vs `cooldown-hard` column vs delta)
- Wall-clock comparison
- "Schedules identical?" verdict (true/false based on CSV diff)
- For Scenario C: explicit count of cooldown violations on each branch

The expected verdict pattern:

| Scenario | Schedules identical? | Violations old | Violations new | Wall-clock delta |
|---|---|---|---|---|
| A | Yes (or near, ±1 metric) | 0 | 0 | ≈ 0 |
| B | Yes (or near, ±1 metric) | 0 | 0 | ≈ 0 |
| C | **No** | **>0** | **0** | ≈ 0 |
| D | Possibly different structure | 0 | 0 | ≈ 0 |

This pattern is the tangible-benefit story: at defaults nothing changes (good — proves no regression), under pathological weights the new implementation is strictly safer, and the documentation finally matches reality.

---

## PR description template

Use this for the PR body:

```
## Phase 0: Make cooldown a hard constraint

Per the analysis in [link to comparison doc], P4 (Cooldown) was documented as a "Hard" constraint in `docs/PRIORITIES.md` but implemented as a soft penalty with weight `−1000 × deficit`. This PR brings the implementation in line with the documentation by enforcing cooldown structurally in the move generator and initial-state generators. After this change, schedules violating minimum match separation cannot be produced — the constraint is filtered out before scoring rather than weighted heavily within it.

### Changes
- `delta_swap` rejects swaps that would violate cooldown before computing score delta
- Initial-state generators (Stage 1 + Stage 2) reject violating placements during construction
- `−1000 × deficit` term removed from score function
- `docs/PRIORITIES.md` updated to describe P4 as structurally enforced
- New comparison harness in `tests/phase0_comparison/` with four scenarios

### Verification
- 200-run fuzz corpus: zero cooldown violations
- Pathological weights (W_PARTNER=10000): zero violations (vs. >0 on main)
- Default-config equivalence: 10/10 fixed seeds produce schedules within ±1 metric on all headline numbers
- Wall-clock at default config: no regression

### Comparison artifacts
See `tests/phase0_comparison/SUMMARY.md` for the full benefit assessment.
```

---

## What this PR does *not* do

To keep scope tight and the change reviewable, the following are explicitly out of scope and will be addressed in later phases:

- Pulling W_BALANCE out of the score function (Phase 1)
- Pulling W_STATION out of the score function (Phase 2)
- Quality presets / iteration budget changes (Phase 3)
- External comparison harness with TBA / multi-source corpus (Phase 4)
- Stage 1 SA optimizer (Phase 5)

If during implementation you find a refactor opportunity that touches one of these, leave a TODO comment referencing the phase number and move on.

---

## Handoff notes

- The implementing session has full latitude on internal code organization. The acceptance criteria and comparison artifacts are the contract.
- If any acceptance criterion can't be met, stop and report rather than working around it. In particular: if Scenario C on the `main` branch produces zero violations, that's a meaningful finding (the soft penalty was sufficient in practice) and should be reported; the truthfulness fix in `PRIORITIES.md` is still worth landing on its own.
- Chris will run the comparison harness against generated schedules and assess tangible benefit before greenlighting Phase 1.
- **Adjacent observation, out of scope for this PR:** the current `delta_swap` in `app/scheduler.py` only computes `-(w_imbal * 500)` — it ignores partner / opponent / station / cooldown deltas and the SA does a full rescore on accept. That's a pre-existing inconsistency, unrelated to the cooldown work. Worth flagging now because Phase 1 removes `W_BALANCE` from the score (the only term `delta_swap` currently uses), so the Phase 1 brief will need to address what `delta_swap` becomes — either re-implement for the remaining terms, or accept that it becomes a no-op and the SA always full-rescores. Don't fix it in this PR; just leave a TODO comment referencing Phase 1.
