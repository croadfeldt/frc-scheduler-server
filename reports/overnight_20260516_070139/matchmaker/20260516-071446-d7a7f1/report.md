# Scheduler eval — 20260516-071446-d7a7f1

Generated: 2026-05-16T12:14:46.101786+00:00

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
| matchmaker | 3 | 0 | 0 | 3 | 21.30 |

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
| repeat_opponents | ≤20 / ≤27 | ✗ 87 | ✓ 12 |
| max_opponent_repeats | ≤2 / ≤2 | ✗ 3 | ✓ 2 |
| max_color_imbalance | ≤1 / ≤2 | ✓ 1 | ✗ 3 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 2 | ✓ 1 |
| min_match_gap | ≥4 / ≥4 | ✓ 7 | ✓ 7 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 3 | — 3 |
| matches_per_team | — | ✗ 9 | ✗ 9 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 40.10 | 21.49s | sa_iters=500,000 (good) |
| matchmaker | ✗ poor | 20.30 | 2.11s |  |

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 7849 | 4.50 | 1 | 2 | 7 | 0 | 4 | 3 |
| 2 | 3610 | 4.38 | 1 | 2 | 7 | 0 | 3 | 3 |
| 3 | 2500 | 4.08 | 1 | 2 | 7 | 0 | 6 | 1 |
| 4 | 2606 | 4.00 | 1 | 2 | 7 | 0 | 0 | 3 |
| 5 | 2491 | 3.96 | 1 | 2 | 7 | 0 | 5 | 1 |

**Most-affected teams in matchmaker's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 3082 | 4.50 | 2 | 1 | 7 | 1 | 0 | 2 |
| 2 | 4664 | 4.50 | 2 | 1 | 7 | 1 | 0 | 2 |
| 3 | 2491 | 3.00 | 3 | 0 | 7 | 0 | 1 | 1 |
| 4 | 3871 | 3.00 | 2 | 1 | 7 | 0 | 1 | 0 |
| 5 | 4198 | 3.00 | 3 | 0 | 7 | 0 | 1 | 1 |

## 2024mndu — Lake Superior Regional

- 55 teams, 9 matches each, 3v3
- Expected total matches: 83
- Notes: Pulled from TBA on 2026-05-09. 55 teams, 83 qual matches.

| Metric | Threshold (good / accept) | frc-scheduler-server | matchmaker |
|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✓ 0 | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | ✓ 1 | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 75 | ✓ 19 |
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
| frc-scheduler-server | ✗ poor | 40.10 | 21.44s | sa_iters=500,000 (good) |
| matchmaker | ✗ poor | 20.30 | 1.89s |  |

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 5653 | 4.60 | 1 | 2 | 6 | 0 | 3 | 3 |
| 2 | 6318 | 4.40 | 1 | 2 | 6 | 0 | 2 | 3 |
| 3 | 8422 | 4.40 | 1 | 2 | 6 | 0 | 2 | 3 |
| 4 | 2239 | 4.33 | 1 | 2 | 6 | 0 | 5 | 1 |
| 5 | 4011 | 4.33 | 1 | 2 | 6 | 0 | 5 | 1 |

**Most-affected teams in matchmaker's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 2531 | 4.25 | 0 | 1 | 6 | 1 | 1 | 2 |
| 2 | 8516 | 3.00 | 0 | 1 | 6 | 1 | 0 | 0 |
| 3 | 6160 | 2.75 | 0 | 1 | 6 | 0 | 3 | 0 |
| 4 | 8298 | 2.75 | 3 | 0 | 6 | 0 | 1 | 1 |
| 5 | 7038 | 2.58 | 1 | 0 | 6 | 0 | 3 | 1 |

## 2025mnmi — Minnesota 10,000 Lakes Regional

- 51 teams, 9 matches each, 3v3
- Expected total matches: 77
- Notes: Pulled from TBA on 2026-05-09. 51 teams, 77 qual matches.

| Metric | Threshold (good / accept) | frc-scheduler-server | matchmaker |
|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✓ 0 | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | ✓ 1 | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 95 | · 21 |
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
| frc-scheduler-server | ✗ poor | 40.10 | 21.41s | sa_iters=500,000 (good) |
| matchmaker | ✗ poor | 23.30 | 1.76s |  |

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 2847 | 5.00 | 1 | 2 | 5 | 0 | 6 | 3 |
| 2 | 4174 | 5.00 | 1 | 2 | 5 | 0 | 6 | 3 |
| 3 | 2220 | 4.80 | 1 | 2 | 5 | 0 | 5 | 3 |
| 4 | 3018 | 4.80 | 1 | 2 | 5 | 0 | 5 | 3 |
| 5 | 3745 | 4.80 | 1 | 2 | 5 | 0 | 5 | 3 |

**Most-affected teams in matchmaker's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 6217 | 5.00 | 2 | 1 | 5 | 1 | 1 | 2 |
| 2 | 2513 | 4.67 | 0 | 1 | 5 | 1 | 2 | 2 |
| 3 | 2207 | 3.50 | 3 | 0 | 5 | 0 | 3 | 1 |
| 4 | 6045 | 3.33 | 2 | 1 | 5 | 0 | 2 | 0 |
| 5 | 4664 | 2.83 | 3 | 0 | 5 | 0 | 1 | 1 |

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
