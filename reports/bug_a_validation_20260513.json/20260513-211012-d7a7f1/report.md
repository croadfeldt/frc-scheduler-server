# Scheduler eval — 20260513-211012-d7a7f1

Generated: 2026-05-14T02:10:12.985654+00:00

## Summary

- Fixtures: 3
- Adapters per fixture: varies (see per-fixture sections)
- Total runs: 6 (6 successful)

Markers: ✓ near-optimal · acceptable · ✗ poor · — descriptive

## Cross-fixture aggregate

Composite score: lower is better. 0 = all metrics near-optimal; ~110 = all metrics poor. The 5-25 band is mixed.

| Adapter | Fixtures | Near-optimal | Acceptable | Poor | Mean composite |
|---|---|---|---|---|---|
| frc-scheduler-server | 3 | 0 | 0 | 3 | 46.97 |
| matchmaker | 3 | 0 | 0 | 3 | 27.00 |

### Head-to-head

Per-fixture wins on composite score. T = within 0.01.

| | frc-scheduler-server | matchmaker |
|---|---|---|
| **frc-scheduler-server** | — | 0W-3L-0T |
| **matchmaker** | 3W-0L-0T | — |

## 2023mnmi — Minnesota 10,000 Lakes Regional presented by Medtronic

- 61 teams, 9 matches each, 3v3
- Expected total matches: 92
- Notes: Pulled from TBA on 2026-05-09. 61 teams, 92 qual matches.

| Metric | Threshold (good / accept) | frc-scheduler-server | matchmaker |
|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✓ 0 | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | ✓ 1 | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✓ 16 | ✓ 14 |
| max_opponent_repeats | ≤2 / ≤2 | ✓ 2 | ✓ 2 |
| max_color_imbalance | ≤1 / ≤2 | ✗ 3 | ✗ 4 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ✗ 1 |
| max_station_spread | ≤1 / ≤1 | ✗ 5 | ✓ 1 |
| min_match_gap | ≥4 / ≥4 | ✗ 3 | ✓ 7 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 3 | — 3 |
| matches_per_team | — | ✗ 9 | ✗ 9 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 40.30 | 50.75s | sa_iters=500,000 (good) |
| matchmaker | ✗ poor | 30.40 | 2.11s |  |

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 2515 | 3.23 | 1 | 2 | 3 | 0 | 1 | 7 |
| 2 | 2606 | 3.16 | 1 | 2 | 3 | 0 | 2 | 3 |
| 3 | 3871 | 2.95 | 1 | 2 | 3 | 0 | 1 | 5 |
| 4 | 5278 | 2.88 | 1 | 2 | 3 | 0 | 2 | 1 |
| 5 | 3278 | 2.68 | 1 | 2 | 4 | 0 | 2 | 1 |

**Most-affected teams in matchmaker's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 3082 | 3.50 | 4 | 1 | 7 | 0 | 1 | 0 |
| 2 | 4549 | 3.17 | 3 | 0 | 7 | 0 | 1 | 1 |
| 3 | 2450 | 3.00 | 1 | 0 | 7 | 0 | 2 | 1 |
| 4 | 2509 | 3.00 | 1 | 0 | 7 | 0 | 2 | 1 |
| 5 | 4664 | 3.00 | 1 | 0 | 7 | 0 | 2 | 1 |

## 2024mndu — Lake Superior Regional

- 55 teams, 9 matches each, 3v3
- Expected total matches: 83
- Notes: Pulled from TBA on 2026-05-09. 55 teams, 83 qual matches.

| Metric | Threshold (good / accept) | frc-scheduler-server | matchmaker |
|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✓ 0 | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | ✓ 1 | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 31 | ✓ 20 |
| max_opponent_repeats | ≤2 / ≤2 | ✓ 2 | ✓ 2 |
| max_color_imbalance | ≤1 / ≤2 | ✗ 3 | ✗ 3 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 3 | ✓ 1 |
| min_match_gap | ≥4 / ≥4 | ✗ 3 | ✓ 6 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 3 | — 3 |
| matches_per_team | — | ✗ 9 | ✗ 9 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 50.30 | 42.75s | sa_iters=500,000 (good) |
| matchmaker | ✗ poor | 20.30 | 1.89s |  |

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 2181 | 3.33 | 1 | 3 | 3 | 0 | 0 | 5 |
| 2 | 7797 | 3.25 | 1 | 2 | 3 | 0 | 1 | 5 |
| 3 | 930 | 3.10 | 1 | 2 | 3 | 0 | 2 | 3 |
| 4 | 4174 | 3.03 | 1 | 3 | 3 | 0 | 2 | 1 |
| 5 | 3267 | 3.00 | 1 | 2 | 3 | 0 | 0 | 5 |

**Most-affected teams in matchmaker's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 2977 | 4.67 | 2 | 1 | 6 | 1 | 0 | 2 |
| 2 | 4741 | 4.33 | 0 | 1 | 6 | 1 | 1 | 2 |
| 3 | 9532 | 4.00 | 0 | 1 | 6 | 0 | 3 | 2 |
| 4 | 7915 | 2.33 | 3 | 0 | 6 | 0 | 1 | 1 |
| 5 | 4174 | 2.33 | 1 | 0 | 6 | 0 | 3 | 1 |

## 2025mnmi — Minnesota 10,000 Lakes Regional

- 51 teams, 9 matches each, 3v3
- Expected total matches: 77
- Notes: Pulled from TBA on 2026-05-09. 51 teams, 77 qual matches.

| Metric | Threshold (good / accept) | frc-scheduler-server | matchmaker |
|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✓ 0 | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | ✓ 1 | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 44 | ✓ 16 |
| max_opponent_repeats | ≤2 / ≤2 | ✓ 2 | ✗ 3 |
| max_color_imbalance | ≤1 / ≤2 | ✗ 3 | ✗ 3 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 4 | ✓ 1 |
| min_match_gap | ≥4 / ≥4 | ✗ 3 | ✓ 5 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 3 | — 3 |
| matches_per_team | — | ✗ 9 | ✗ 9 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 50.30 | 37.78s | sa_iters=500,000 (good) |
| matchmaker | ✗ poor | 30.30 | 1.75s |  |

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 3883 | 3.83 | 1 | 2 | 3 | 0 | 5 | 5 |
| 2 | 3792 | 3.43 | 1 | 2 | 3 | 0 | 3 | 5 |
| 3 | 2538 | 3.03 | 1 | 2 | 3 | 0 | 1 | 5 |
| 4 | 3082 | 2.93 | 1 | 2 | 4 | 0 | 3 | 5 |
| 5 | 2207 | 2.83 | 1 | 2 | 3 | 0 | 4 | 1 |

**Most-affected teams in matchmaker's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 8570 | 4.00 | 0 | 1 | 5 | 0 | 2 | 2 |
| 2 | 2502 | 3.67 | 2 | 1 | 5 | 0 | 2 | 0 |
| 3 | 3454 | 3.67 | 2 | 1 | 5 | 0 | 2 | 0 |
| 4 | 3630 | 2.83 | 1 | 0 | 5 | 0 | 2 | 1 |
| 5 | 3792 | 2.83 | 1 | 0 | 5 | 0 | 2 | 1 |

---

## Methodology

- For stochastic adapters, the harness runs N trials per fixture and reports the BEST.
  'Best' = fewest 'poor' metrics, then most 'near_optimal', then lowest repeat-partner count.
- Composite score collapses classifications into a single float for ranking and head-to-head:
  `10 × poor + 3 × acceptable + 0.1 × repeat_partners + 0.1 × max_color_imbalance`. Lower = better.
- Trial distribution shows variance across all N trials, not just the best — catches
  high-variance adapters whose median output isn't production-deployable.
- Per-team burden normalizes color, station, gap, repeats, and day rhythm across teams
  in a single schedule, so the most-affected teams surface automatically.
- Thresholds in the metric table are calibrated from FRC community norms and the
  reviewer's the reference scheduler analysis (800 trials on 36-team field).
- Surrogate slot-fills count toward color/station balance (team is physically there)
  but not toward repeat-partner / repeat-opponent counts (team is filling in,
  not playing competitively).
