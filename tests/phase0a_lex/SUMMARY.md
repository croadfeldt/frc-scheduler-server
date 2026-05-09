# Phase 0a: Lexicographic Score (FRC §10.5.2 paramount)

**Status:** Complete. The canonical score function returns a lex tuple ordered by FRC's stated priority. SA accept/reject and best-tracking use lex tuple comparison.

## Architectural change

**Before (Phase 0 + Phase 1):**
- `_score_from_state` returned a float (weighted sum: `Σ wᵢ × penaltyᵢ`)
- SA accepted swaps with non-negative score deltas (lower penalty = better)
- Weighted sum approximated FRC's stated priorities but did not enforce them

**After (Phase 0a + 0b, this work):**
- `_score_from_state` returns a lex tuple `(p1, p2, p3, p4, p5, p6, p7, p8)` indexed by FRC §10.5.2 priority order
- `score_schedule` returns a summary float (display only, NOT used for comparison)
- `score_tuple_for_schedule` returns the authoritative tuple
- SA accept/reject uses lex tuple comparison: never accept a swap that worsens a higher-priority criterion to gain on a lower-priority one
- Stochastic uphill acceptance is allowed only at the lowest-priority element where tuples differ; never at FRC #1 (cooldown — paramount)

## Lex tuple shape (8 elements)

| Index | Element | Source | FRC rank |
|---|---|---|---|
| 0 | cooldown_violations | hard structural check | #1 (paramount) |
| 1 | par_quad | sum of partner-pair count² | #2 |
| 2 | opp_quad | sum of opponent-pair count² | #3 |
| 3 | surrogate_count | total surrogate appearances | #4 (structural minimum) |
| 4 | rb_metric | max\|rc-bc\| (≥24 teams) or color-swap count (<24 teams) | #5 |
| 5 | station_pen | sum of station-spread per team | #6 |
| 6 | surrogate_spread | per-team surrogate variance × 100 | P11 (#7 tie-breaker) |
| 7 | match_equity | always 0 in finalized schedules | P5 (#8 construction-only) |

Lower tuple value = better. Comparison is lexicographic (first differing element wins).

## Confirmed user decisions

- **A:** Lexicographic semantics. Never trade up on higher priority for lower. ✓
- **B:** Lex tuple compare. Implemented as Python tuple comparison. ✓
- **C:** P11 stays as #7 tie-breaker. P7 (gap maximization) removed. ✓
- **D:** <24 teams R/B variant honored. `rb_metric` uses color-swap count for small events; max-imbal for large. ✓
- **E:** P7 removed from canonical score. ✓

## Property tests (all passing)

- 300 cross-match swaps × 3 fixture sizes: incremental SA-mutated state's tuple equals from-scratch rebuild's tuple
- 86 within-match swaps: same
- 50 self-inverse pairs: state byte-identical after swap-and-revert
- Dupe-rejection: 24 swap rejections verified
- SA on scrambled schedule: cooldown 74 → 9, partner 318 → 274 (improved at lex index 0, then index 1) — confirms FRC paramount behavior

## Eval impact on 2026mnst

Phase 1 (weighted-sum) best composite was 29.20.
Phase 0a (lex paramount) at same SA budget produces composite ~43-73.

**This is the expected result.** The composite metric is a weighted sum that does not match FRC's lex priority. With FRC paramount, the SA produces better lex tuples but worse weighted-sum composites. Per user direction "what is stated for FRC rules and priorities is paramount", we accept this tradeoff: schedules are now correctly optimized against FRC's actual stated priorities.

The eval composite is not a reliable indicator of FRC compliance — only the lex tuple is. We may want to add a "lex-distance to optimal" or "first-differing-element index" metric that better reflects FRC compliance.

## What's next

- **Phase 0b:** Hard cooldown filter in move generator. Currently the SA accepts cooldown-violating swaps via the tuple compare; a hard pre-filter would be more efficient and prevent any cooldown drift. Construction phase produces cooldown violations on small events (24×8 specifically); fixing this lets the SA spend its budget on higher-priority criteria.
- **Phase 0c (deferred):** Smarter move generator. Lex paramount makes random swaps rarely accept; targeted moves (e.g., resolve a partner duplicate) would be more efficient.
- **Iteration sweep:** Find K* per tight criterion (mean improvement at 2K < std-dev at K). Sweep harness will run on Stark since 30 trials × 7 levels × ~9 minutes/trial = ~9 hours single-threaded, ~15 min parallel.
- **Quality presets:** Tune Fair/Good/Best after K* is found. Cap raised to 5,000,000.
- **Competition-approved checkbox + audit trail:** UX layer.
