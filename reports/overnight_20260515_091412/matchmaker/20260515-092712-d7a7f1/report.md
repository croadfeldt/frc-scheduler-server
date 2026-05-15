# Scheduler eval — 20260515-092712-d7a7f1

Generated: 2026-05-15T14:27:12.444296+00:00

## Summary

- Fixtures: 3
- Adapters per fixture: varies (see per-fixture sections)
- Total runs: 6 (6 successful)

Markers: ✓ near-optimal · acceptable · ✗ poor · — descriptive

## Cross-fixture aggregate

Composite score: lower is better. 0 = all metrics near-optimal; ~110 = all metrics poor. The 5-25 band is mixed.

| Adapter | Fixtures | Near-optimal | Acceptable | Poor | Mean composite |
|---|---|---|---|---|---|
| frc-scheduler-server | 3 | 0 | 0 | 3 | 40.10 |
| matchmaker | 3 | 0 | 0 | 3 | 23.67 |

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
| repeat_opponents | ≤20 / ≤27 | ✗ 72 | ✓ 16 |
| max_opponent_repeats | ≤2 / ≤2 | ✗ 3 | ✓ 2 |
| max_color_imbalance | ≤1 / ≤2 | ✓ 1 | ✗ 4 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ✗ 2 |
| max_station_spread | ≤1 / ≤1 | ✗ 2 | ✓ 1 |
| min_match_gap | ≥4 / ≥4 | ✓ 7 | ✓ 7 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 3 | — 3 |
| matches_per_team | — | ✗ 9 | ✗ 9 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 40.10 | 22.13s | sa_iters=500,000 (good) |
| matchmaker | ✗ poor | 30.40 | 2.09s |  |

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 1816 | 3.90 | 1 | 2 | 7 | 0 | 4 | 1 |
| 2 | 2549 | 3.90 | 1 | 2 | 7 | 0 | 4 | 1 |
| 3 | 3082 | 3.90 | 1 | 2 | 7 | 0 | 4 | 1 |
| 4 | 3202 | 3.90 | 1 | 2 | 7 | 0 | 4 | 1 |
| 5 | 2491 | 3.76 | 1 | 2 | 7 | 0 | 3 | 1 |

**Most-affected teams in matchmaker's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 4277 | 3.42 | 3 | 0 | 7 | 0 | 2 | 1 |
| 2 | 2500 | 3.33 | 4 | 1 | 7 | 0 | 1 | 0 |
| 3 | 4198 | 3.33 | 4 | 1 | 7 | 0 | 1 | 0 |
| 4 | 2450 | 3.25 | 1 | 0 | 7 | 0 | 3 | 1 |
| 5 | 4215 | 3.08 | 3 | 0 | 7 | 0 | 1 | 1 |

## 2024mndu — Lake Superior Regional

- 55 teams, 9 matches each, 3v3
- Expected total matches: 83
- Notes: Pulled from TBA on 2026-05-09. 55 teams, 83 qual matches.

| Metric | Threshold (good / accept) | frc-scheduler-server | matchmaker |
|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✓ 0 | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | ✓ 1 | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 86 | ✓ 12 |
| max_opponent_repeats | ≤2 / ≤2 | ✗ 3 | ✓ 2 |
| max_color_imbalance | ≤1 / ≤2 | ✓ 1 | ✗ 3 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 2 | ✓ 1 |
| min_match_gap | ≥4 / ≥4 | ✓ 6 | ✓ 6 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 3 | — 3 |
| matches_per_team | — | ✗ 9 | ✗ 9 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 40.10 | 21.50s | sa_iters=500,000 (good) |
| matchmaker | ✗ poor | 20.30 | 1.90s |  |

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 8516 | 4.17 | 1 | 2 | 6 | 0 | 6 | 1 |
| 2 | 930 | 4.00 | 1 | 2 | 6 | 0 | 5 | 1 |
| 3 | 7038 | 4.00 | 1 | 0 | 6 | 0 | 7 | 3 |
| 4 | 7068 | 4.00 | 1 | 2 | 6 | 0 | 1 | 3 |
| 5 | 7915 | 4.00 | 1 | 2 | 6 | 0 | 1 | 3 |

**Most-affected teams in matchmaker's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 5653 | 3.67 | 2 | 1 | 6 | 0 | 2 | 0 |
| 2 | 2847 | 3.50 | 3 | 0 | 6 | 0 | 1 | 1 |
| 3 | 2181 | 3.33 | 1 | 0 | 6 | 0 | 2 | 1 |
| 4 | 3294 | 3.33 | 1 | 0 | 6 | 0 | 2 | 1 |
| 5 | 4778 | 3.33 | 1 | 0 | 6 | 0 | 2 | 1 |

## 2025mnmi — Minnesota 10,000 Lakes Regional

- 51 teams, 9 matches each, 3v3
- Expected total matches: 77
- Notes: Pulled from TBA on 2026-05-09. 51 teams, 77 qual matches.

| Metric | Threshold (good / accept) | frc-scheduler-server | matchmaker |
|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✓ 0 | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | ✓ 1 | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 80 | ✓ 13 |
| max_opponent_repeats | ≤2 / ≤2 | ✗ 3 | ✓ 2 |
| max_color_imbalance | ≤1 / ≤2 | ✓ 1 | ✗ 3 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 2 | ✓ 1 |
| min_match_gap | ≥4 / ≥4 | ✓ 5 | ✓ 5 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 3 | — 3 |
| matches_per_team | — | ✗ 9 | ✗ 9 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 40.10 | 21.81s | sa_iters=500,000 (good) |
| matchmaker | ✗ poor | 20.30 | 1.76s |  |

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 2667 | 4.67 | 1 | 2 | 5 | 0 | 4 | 3 |
| 2 | 5271 | 4.67 | 1 | 2 | 5 | 0 | 4 | 3 |
| 3 | 6217 | 4.67 | 1 | 2 | 5 | 0 | 4 | 3 |
| 4 | 8570 | 4.50 | 1 | 2 | 5 | 0 | 3 | 3 |
| 5 | 2502 | 4.33 | 1 | 2 | 5 | 0 | 6 | 1 |

**Most-affected teams in matchmaker's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 2823 | 4.33 | 2 | 1 | 6 | 1 | 0 | 2 |
| 2 | 2855 | 3.50 | 0 | 1 | 5 | 1 | 1 | 0 |
| 3 | 4174 | 3.00 | 3 | 0 | 5 | 0 | 1 | 1 |
| 4 | 2472 | 2.83 | 1 | 0 | 5 | 0 | 2 | 1 |
| 5 | 3755 | 2.83 | 1 | 0 | 5 | 0 | 2 | 1 |

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
