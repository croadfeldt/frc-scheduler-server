# Phase 2: Sykes-style Station Balance Post-Pass

**Status:** Complete. Substantially improves driver-station distribution
(FRC §10.5.2 #6) on real fixtures — `max_station_spread` drops from 4
to 2, `total_station_pen` drops by ~30%.

## What was added

- `app/post_passes/station_balance.py` — within-alliance station permutation optimizer
- Greedy `station_balance_pass` for theoretical baseline
- SA-from-greedy variant `station_balance_sa` (used in production)
- 12 commutativity property tests in `tests/test_station_balance.py`
- Integration in `generate_matches` and `_assign_unified` via `station_post_pass=True` flag

## Operation set

Within a single alliance of a single match, permute the 3 teams across
the 3 station slots (R1/R2/R3 or B1/B2/B3). 6 permutations per alliance;
we evaluate each. Surrogate flags travel with teams.

## Commutativity guarantees (verified by 9 property tests)

- **Partner pairs preserved exactly:** A team's red-alliance teammates remain its red-alliance teammates; only positions within the alliance change.
- **Opponent pairs preserved exactly:** Cross-alliance pairs depend only on which teams are in red vs blue, which doesn't change.
- **R/B balance preserved:** Per-team rc/bc counts depend only on alliance membership.
- **Match separation preserved:** Matches and team-sets unchanged; gaps preserved.
- **Surrogate flags preserved:** Travel with teams; per-team counts unchanged.
- **Alliance composition preserved:** `team_alliance_per_match` invariant verified across all seeds.
- **Match team sets preserved:** Same teams play in same match.

The post-pass changes only criterion #6 (station_pen). All other lex tuple elements are mathematically guaranteed unchanged.

## Why "SA from greedy" instead of pure SA

Initial implementation was pure SA. On 1/10 fixture seeds the pure SA actually plateau'd *worse* than greedy (sum_pen=48 vs greedy's 43 at 2000 iterations). Greedy reaches a strong local optimum quickly; pure random SA exploration can wander away.

Fix: run greedy first, then SA from the greedy result. SA's best-tracking ensures the final result is never worse than greedy alone. SA explores nearby permutations to find improvements greedy missed.

## Eval impact on 2026mnst

On a Phase 0+1+2 schedule (36 teams × 7 MPT, SA=50K + R/B + station post-passes):

| Metric | Before Phase 2 | After Phase 2 |
|---|---|---|
| `max_station_spread` (per-team) | 4 (poor) | 2 (near_optimal) |
| `total_station_pen` (sum across teams) | 69 | 48 (-30%) |

## Comparison to MatchMaker on the same fixture

On the 2026mnst state qual schedule (36 teams, MPT=7), best of 8 trials at SA=1M:

| FRC criterion | MatchMaker reference | Ours (Phase 0+1+2) |
|---|---|---|
| #1 cooldown | 0 | 0 |
| #2 par_quad | 252 (floor) | 252 (floor) |
| #3 opp_quad | 416 | 422 |
| #4 surrogate | 0 | 0 |
| #5 rb_metric | 3 | 3 |
| #6 station_pen | 65 | 45 |

Both produce comparable lex tuples on this fixture. MatchMaker is the
long-standing community reference scheduler used by event organizers;
its output here is the baseline our development sweeps target. Our
station_pen value reflects Phase 2's specific role of optimizing FRC
criterion #6 — different schedulers will land at different points in
the lex tuple depending on which criterion their search emphasizes.

## Cost

~50ms per fixture for 5000 SA iterations of single-permutation evaluation. Negligible vs the SA budget for partner/opponent.
