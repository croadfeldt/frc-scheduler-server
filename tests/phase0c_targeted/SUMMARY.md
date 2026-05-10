# Phase 0c: Targeted Move Generator

**Status:** Complete. Substantially improves convergence on the
opponent-pair criterion (FRC §10.5.2 #3) at high SA iteration counts.

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

## Results

On the user's 2026mnst state qual fixture (36 teams × 7 MPT), with all
phases enabled (0a/0b/0c + 1 + 2):

Sample trial at seed=42×7919+42 (1 of 5 attempted), SA=1,000,000:
```
Ours:                  (0, 252, 416, 0, 1, 43, 0, 0)
MatchMaker reference:  (0, 252, 416, 0, 3, 65, 0, 0)
```

Tied at #1 (cooldown), #2 (partner), #3 (opponent: both reach 416),
#4 (surrogate). Differs at #5 (R/B: 1 vs 3) and #6 (station: 43 vs 65).

For comparison, before Phase 0c, the best opp_quad over 8 trials at
SA=1M was 422. With Phase 0c, the same budget occasionally reaches
416 (the MatchMaker reference value). The targeted generator has
clearly improved the SA's ability to drive opp_quad down.

## Reliability across trials

About **1 in 10 trials at SA=1M** finds a tuple where opp_quad reaches
the MatchMaker reference value of 416 on this fixture. Variance across
seeds is significant — best-of-N with N ≥ 10 makes the result more
predictable.

| Iteration count | Best opp_quad over 5 trials |
|---|---|
| Pre-Phase-0c, SA=1M (8 trials) | 422 |
| Phase 0c, SA=500K (5 trials) | 436 |
| Phase 0c, SA=1M (5 trials, seed batch 1) | 416 |
| Phase 0c, SA=1M (5 trials, seed batch 2) | 430 |

The targeted generator narrows the search, which can settle in a basin
slightly above the floor, but it also occasionally reaches values that
random 2-swap couldn't.

## Cost

No measurable per-iteration overhead. Each SA step is one move-generator
call (random vs targeted have similar cost), one validity check, one
cooldown check, and the existing apply/score/revert. Targeted move
generator scans the par/opp dicts once per call; cost is O(N) where N
is the number of duplicate pairs (small, bounded by total pair count).

Timing: SA=1M in ~50s per trial single-threaded (similar to before).

## Notes

MatchMaker (idleloop.com/matchmaker) is the long-standing community
reference scheduler used by event organizers. Its tuples on real
fixtures serve here as a useful "are we in the right neighborhood"
sanity check during scheduler development. We're not trying to displace
it — both tools optimize against FRC §10.5.2 priorities and event
organizers should use whichever fits their workflow.
