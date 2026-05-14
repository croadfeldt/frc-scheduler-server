# Scheduler eval — 20260513-214133-d7a7f1

Generated: 2026-05-14T02:41:33.367604+00:00

## Summary

- Fixtures: 3
- Adapters per fixture: varies (see per-fixture sections)
- Total runs: 6 (3 successful)

Markers: ✓ near-optimal · acceptable · ✗ poor · — descriptive

## Cross-fixture aggregate

Composite score: lower is better. 0 = all metrics near-optimal; ~110 = all metrics poor. The 5-25 band is mixed.

| Adapter | Fixtures | Near-optimal | Acceptable | Poor | Mean composite |
|---|---|---|---|---|---|
| frc-scheduler-server | 0 | 0 | 0 | 0 | nan |
| matchmaker | 3 | 0 | 0 | 3 | 28.00 |

### Head-to-head

Per-fixture wins on composite score. T = within 0.01.

| | frc-scheduler-server | matchmaker |
|---|---|---|
| **frc-scheduler-server** | — | 0W-0L-0T |
| **matchmaker** | 0W-0L-0T | — |

## 2023mnmi — Minnesota 10,000 Lakes Regional presented by Medtronic

- 61 teams, 9 matches each, 3v3
- Expected total matches: 92
- Notes: Pulled from TBA on 2026-05-09. 61 teams, 92 qual matches.

| Metric | Threshold (good / accept) | frc-scheduler-server | matchmaker |
|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ERROR | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | ERROR | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ERROR | ✓ 13 |
| max_opponent_repeats | ≤2 / ≤2 | ERROR | ✓ 2 |
| max_color_imbalance | ≤1 / ≤2 | ERROR | ✗ 4 |
| teams_with_5_2_color | ≤0 / ≤0 | ERROR | ✗ 1 |
| max_station_spread | ≤1 / ≤1 | ERROR | ✓ 1 |
| min_match_gap | ≥4 / ≥4 | ERROR | ✓ 7 |
| back_to_back_matches | ≤0 / ≤0 | ERROR | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | ERROR | — 3 |
| matches_per_team | — | ERROR | ✗ 9 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ERROR | — | — | ModuleNotFoundError: No module named 'ortools' |
| matchmaker | ✗ poor | 30.40 | 2.10s |  |

**Most-affected teams in matchmaker's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 3278 | 4.00 | 2 | 1 | 7 | 0 | 1 | 2 |
| 2 | 2052 | 3.50 | 4 | 1 | 7 | 0 | 1 | 0 |
| 3 | 2509 | 3.00 | 0 | 1 | 7 | 0 | 2 | 0 |
| 4 | 2855 | 2.75 | 3 | 0 | 7 | 0 | 1 | 1 |
| 5 | 3206 | 2.75 | 1 | 0 | 7 | 0 | 2 | 1 |

## 2024mndu — Lake Superior Regional

- 55 teams, 9 matches each, 3v3
- Expected total matches: 83
- Notes: Pulled from TBA on 2026-05-09. 55 teams, 83 qual matches.

| Metric | Threshold (good / accept) | frc-scheduler-server | matchmaker |
|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ERROR | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | ERROR | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ERROR | · 21 |
| max_opponent_repeats | ≤2 / ≤2 | ERROR | ✗ 3 |
| max_color_imbalance | ≤1 / ≤2 | ERROR | ✗ 3 |
| teams_with_5_2_color | ≤0 / ≤0 | ERROR | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ERROR | ✓ 1 |
| min_match_gap | ≥4 / ≥4 | ERROR | ✓ 6 |
| back_to_back_matches | ≤0 / ≤0 | ERROR | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | ERROR | — 3 |
| matches_per_team | — | ERROR | ✗ 9 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ERROR | — | — | ModuleNotFoundError: No module named 'ortools' |
| matchmaker | ✗ poor | 33.30 | 1.91s |  |

**Most-affected teams in matchmaker's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 8298 | 3.67 | 2 | 1 | 6 | 0 | 0 | 2 |
| 2 | 5826 | 3.50 | 3 | 0 | 6 | 0 | 3 | 1 |
| 3 | 2181 | 3.33 | 0 | 1 | 6 | 0 | 1 | 2 |
| 4 | 3197 | 3.00 | 0 | 1 | 6 | 0 | 3 | 0 |
| 5 | 3294 | 2.83 | 3 | 0 | 6 | 0 | 1 | 1 |

## 2025mnmi — Minnesota 10,000 Lakes Regional

- 51 teams, 9 matches each, 3v3
- Expected total matches: 77
- Notes: Pulled from TBA on 2026-05-09. 51 teams, 77 qual matches.

| Metric | Threshold (good / accept) | frc-scheduler-server | matchmaker |
|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ERROR | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | ERROR | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ERROR | ✓ 18 |
| max_opponent_repeats | ≤2 / ≤2 | ERROR | ✓ 2 |
| max_color_imbalance | ≤1 / ≤2 | ERROR | ✗ 3 |
| teams_with_5_2_color | ≤0 / ≤0 | ERROR | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ERROR | ✓ 1 |
| min_match_gap | ≥4 / ≥4 | ERROR | ✓ 5 |
| back_to_back_matches | ≤0 / ≤0 | ERROR | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | ERROR | — 3 |
| matches_per_team | — | ERROR | ✗ 9 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ERROR | — | — | ModuleNotFoundError: No module named 'ortools' |
| matchmaker | ✗ poor | 20.30 | 1.74s |  |

**Most-affected teams in matchmaker's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 8234 | 3.67 | 0 | 1 | 5 | 0 | 2 | 2 |
| 2 | 2846 | 3.33 | 2 | 1 | 5 | 0 | 2 | 0 |
| 3 | 4778 | 3.33 | 2 | 1 | 5 | 0 | 2 | 0 |
| 4 | 4174 | 3.17 | 3 | 0 | 5 | 0 | 2 | 1 |
| 5 | 5541 | 2.83 | 3 | 0 | 5 | 0 | 1 | 1 |

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
