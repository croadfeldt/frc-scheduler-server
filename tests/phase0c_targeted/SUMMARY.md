# Phase 0c: Targeted Move Generator

**Status:** Complete. Achieves first lex-tuple wins over MatchMaker.

## Problem

Random 2-swap is sluggish under FRC-paramount lex semantics. After
par_quad reaches floor (252 on the 36-team / MPT=7 fixture), the only
acceptable moves are those that:
- Hold par_quad ≤ 252 (no worsening at #2)
- Improve opp_quad

Random swaps mostly worsen par_quad slightly and get rejected. The SA
spends most of its budget on rejected proposals.

## Solution

Add a `_propose_targeted_move(state, matches, rng, kind)` helper that
identifies a duplicate partner or opponent pair and proposes a swap
aimed at breaking it. The SA loop probabilistically alternates:
- 1/3 partner-targeted: pick a duplicate partner pair, move one of
  them to a random destination
- 1/3 opponent-targeted: pick a duplicate opponent pair, move one
- 1/3 random 2-swap (ergodic exploration / plateau escape)

Targeted moves fall through to random when their target pool is empty
(typical when par_quad reaches floor and only opp_quad has duplicates).

The proposed swap may still fail `_is_valid_swap` (dupe check) or
`_swap_preserves_cooldown`, and the lex compare in the SA loop still
gates acceptance. The targeted generator just *biases* exploration
toward the bottleneck; it doesn't bypass any correctness checks.

## Results — first MatchMaker lex-tuple wins

On the user's actual state qual schedule (36 teams × 7 MPT):

Trial at seed=42×7919+42 (1 of 5), SA=1,000,000:
```
MatchMaker: (0, 252, 416, 0, 3, 65, 0, 0)
Ours:       (0, 252, 416, 0, 1, 43, 0, 0)
```

**Lex verdict: ours wins.** Tied at #1 (cooldown), #2 (partner), #3
(opponent), #4 (surrogate). Wins at #5 (R/B: 1 vs 3, max imbalance).
Bonus: also better at #6 (station: 43 vs 65), though #5 already
decided lex.

## Win rate

Roughly **1 in 10 trials at SA=1M** finds a tuple that matches or beats
MatchMaker's. The variance across trials means best-of-N with N≥10
should reliably produce a winning schedule.

| Iteration count | Best opp_quad over 5 trials | Win rate (lex) |
|---|---|---|
| Pre-Phase-0c, SA=1M (8 trials) | 422 | 0/8 |
| Phase 0c, SA=500K (5 trials) | 436 | 0/5 |
| Phase 0c, SA=1M (5 trials) | 416 (matched MM) | 1/5 |
| Phase 0c, SA=1M (5 trials, alt seeds) | 430 | 0/5 |

Variance is significant. The targeted generator narrows the search,
which can trap us in a basin slightly above MM's floor — but it also
finds the MM floor occasionally, which random 2-swap couldn't.

## Cost

No measurable per-iteration overhead. Each SA step is one move-generator
call (random vs targeted have similar cost), one validity check, one
cooldown check, and the existing apply/score/revert. Targeted move
generator scans the par/opp dicts once per call; cost is O(N) where N
is the number of duplicate pairs (small, bounded by total pair count).

Timing: SA=1M in ~50s per trial single-threaded (similar to before).

## How to consistently win

Use best-of-N with N ≥ 10 trials at SA ≥ 1M. At Stark scale (36 cores
parallel), 30 trials × SA=1M ≈ 30 minutes wall-clock. We'd expect
**majority of best-of-30 attempts** to produce a lex-tuple ≤ MM.

Or push SA budget higher (2M, 5M) per single trial — we haven't measured
single-trial behavior at those budgets yet.
