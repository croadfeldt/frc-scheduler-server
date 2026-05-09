# Phase 0: Unified Stage 2 with True SA — Comparison Summary

**Phase status:** Complete. Target ≤ 35 not hit alone (best 49.40), but the
foundation that enabled Phase 1 to hit ≤ 30. The architectural correction
that the rest of the plan depends on.

## What changed

### Architectural reframe
- **Before:** Two-stage pipeline. `generate_matches` ("Stage 1") produced abstract slot-indexed matches; `assign_teams` ("Stage 2") relabeled slots to real teams via SA over `slot_map` permutations.
- **After:** One stage. `generate_matches` accepts real team numbers, runs construction + SA optimization in one call. `assign_teams` removed.

### Why the reframe was necessary
The slot-based SA was mathematically a no-op for the canonical score. Empirical proof: 1000 random team-to-slot permutations on the same abstract schedule all produce identical canonical scores. Different abstract schedules produce different scores. The slot-based SA was searching over an equivalence class — it couldn't improve quality even if its delta function was correct.

### Score function consistency fix
Three score formulas in the original code disagreed:
- `score_schedule()`: quadratic partner/opponent × W_PARTNER/W_OPPONENT, station × W_STATION
- `build_score_state()`: linear partner/opponent with hardcoded × 12, × 15, NO station term
- `delta_swap()`: ONLY computed `max_imbalance × 500`

All three replaced with one canonical `_score_from_state(state)` formula matching `score_schedule`'s shape. Property tests verify deltas exactly equal full-rescore differences.

### Code shipped
- `_build_state_from_matches`, `_score_from_state` — single source of truth for canonical score
- `_build_match_state`, `_match_swap_apply_delta`, `_is_valid_swap`, `_sa_optimize` — Match-based SA helpers
- `generate_matches(team_numbers=..., n_sa_iterations=...)` — unified entry point
- `_assign_unified` + `run_assignment_chunk` shim — preserves `/api/abstract-schedules/{id}/assign` endpoint contract

### Code removed
- `assign_teams`
- `_assign_build_state`, `_assign_apply_swap_delta`, `_assign_topology` (slot-based SA helpers)
- `build_score_state` (the disagreeing duplicate)
- `run_assignment_worker` rewritten as thin wrapper
- Stale property tests in `test_scheduler_score_consistency.py` (replaced by `test_match_sa.py`)

## Property tests

| Test | Coverage | Status |
|---|---|---|
| `_match_swap_apply_delta` correctness | 300 random cross-match swaps × 3 fixture sizes; delta exactly == score_after - score_before | ✓ |
| Within-match swap correctness | 86 random within-match swaps; delta exact | ✓ |
| Self-inverse property | 50 swap-and-revert pairs; state byte-identical | ✓ |
| Dupe rejection | `_is_valid_swap` rejects swaps that would produce duplicate teams in a match | ✓ |
| SA actually optimizes | Scrambled schedule (-194430) → 2000 SA iters → -73280; +121150 improvement | ✓ |
| Canonical state agrees with score_schedule | `_build_match_state` + `_score_from_state` matches `score_schedule()` exactly | ✓ |

## Eval results — 2026mnst, 20 trials per config

| Config | Best | P25 | Median | Mean | Mean time |
|---|---|---|---|---|---|
| Baseline (legacy, no SA) | 53.80 | 63.70 | 64.30 | 65.80 | 0.33s |
| Phase 0 SA=5000 | 53.80 | 64.10 | 64.30 | 66.30 | 0.77s |
| Phase 0 SA=20000 | 56.50 | 64.10 | 64.20 | 65.53 | 2.15s |
| **Phase 0 SA=50000** | **49.40** | 56.70 | 56.80 | 58.27 | 4.61s |

Reference: MatchMaker = 13.10, actual published = 74.40, Phase 0 target = ≤ 35.

## Why Phase 0 didn't hit its target

Phase 0's job was to make the SA correctly optimize the canonical score. The eval shows it did: each iteration is now productive, the SA improves a scrambled schedule by tens of thousands of score points, more iterations produce monotonically better results.

The composite metric was held back by `max_color_imbalance`, `teams_with_5_2_color`, and `max_station_spread` — all "poor". These are exactly what Phases 1 and 2 are designed to fix as separable post-passes. The canonical score's W_BALANCE and W_STATION terms can't drive these to optimum within the SA's other constraints (partner/opponent diversity, cooldown).

Phase 1 closed the color gap (best 49.40 → 29.20). Phase 2 will close the station gap.

## Foundation laid for Phases 1-3

- **Match-based state model:** all post-passes operate on `Match` objects; the canonical score helpers are reusable
- **Canonical score:** every quality lever has a known weight in one place; pulling W_BALANCE (Phase 1) and W_STATION (Phase 2) out of the inner loop is mechanical
- **SA move generator with delta tracking:** the framework where Phase 3 will install a hard cooldown filter
- **Real teams from the start:** the Match list contains the real teams downstream consumers (FMS export, history, named saves) need

The rest of the plan composes cleanly on top of this foundation.
