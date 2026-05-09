# Scheduler eval — 20260509-104227-bd3b50

Generated: 2026-05-09T15:42:29.406125+00:00

## Summary

- Fixtures: 16
- Adapters per fixture: varies (see per-fixture sections)
- Total runs: 816 (788 successful)

Markers: ✓ near-optimal · acceptable · ✗ poor · — descriptive

## Cross-fixture aggregate

Composite score: lower is better. 0 = all metrics near-optimal; ~110 = all metrics poor. The 5-25 band is mixed.

| Adapter | Fixtures | Near-optimal | Acceptable | Poor | Mean composite |
|---|---|---|---|---|---|
| frc-scheduler-server | 16 | 0 | 0 | 16 | 48.58 |
| actual | 16 | 0 | 0 | 16 | 25.77 |

### Head-to-head

Per-fixture wins on composite score. T = within 0.01.

| | frc-scheduler-server | actual |
|---|---|---|
| **frc-scheduler-server** | — | 2W-14L-0T |
| **actual** | 14W-2L-0T | — |

## 2023mndu — Lake Superior Regional

- 60 teams, 9 matches each, 3v3
- Expected total matches: 90
- Notes: Pulled from TBA on 2026-05-09. 60 teams, 90 qual matches.

| Metric | Threshold (good / accept) | frc-scheduler-server | actual |
|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✗ 15 | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | · 2 | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 95 | ✓ 4 |
| max_opponent_repeats | ≤2 / ≤2 | ✓ 2 | ✓ 2 |
| max_color_imbalance | ≤1 / ≤2 | ✗ 3 | ✗ 3 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 3 | ✓ 0 |
| min_match_gap | ≥4 / ≥4 | ✓ 5 | ✓ 7 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 0 | — 0 |
| matches_per_team | — | ✓ 9 | ✓ 9 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 44.80 | 5.43s | score=-108990 |
| actual | ✗ poor | 10.30 | 0.00s | source=tba |

**Trial distribution**

- **frc-scheduler-server** (50 trials): composite best 44.80, median 64.90, worst 75.50, std 5.76
  - repeat_partners: best 9, median 15, worst 23
  - max_color_imbalance: best 3, median 5, worst 7

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 1716 | 2.63 | 3 | 0 | 9 | 2 | 3 | 1 |
| 2 | 3692 | 2.51 | 3 | 2 | 9 | 1 | 1 | 1 |
| 3 | 4728 | 2.49 | 3 | 0 | 9 | 2 | 2 | 1 |
| 4 | 6160 | 2.30 | 1 | 2 | 9 | 2 | 3 | 1 |
| 5 | 8836 | 2.30 | 1 | 2 | 9 | 2 | 3 | 1 |

**Most-affected teams in actual's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 93 | 2.00 | 1 | 0 | 7 | 0 | 1 | 1 |
| 2 | 1714 | 2.00 | 1 | 0 | 7 | 0 | 1 | 1 |
| 3 | 2823 | 2.00 | 1 | 0 | 7 | 0 | 1 | 1 |
| 4 | 3122 | 2.00 | 1 | 0 | 7 | 0 | 1 | 1 |
| 5 | 3276 | 2.00 | 3 | 0 | 7 | 0 | 0 | 1 |

## 2023mnmi — Minnesota 10,000 Lakes Regional presented by Medtronic

- 61 teams, 9 matches each, 3v3
- Expected total matches: 91
- Notes: Pulled from TBA on 2026-05-09. 61 teams, 92 qual matches.

| Metric | Threshold (good / accept) | frc-scheduler-server | actual |
|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✗ 5 | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | · 2 | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 85 | ✓ 4 |
| max_opponent_repeats | ≤2 / ≤2 | ✓ 2 | ✓ 2 |
| max_color_imbalance | ≤1 / ≤2 | ✗ 3 | ✗ 3 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 3 | ✓ 1 |
| min_match_gap | ≥4 / ≥4 | ✓ 5 | ✓ 7 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 3 | — 3 |
| matches_per_team | — | ✗ 9 | ✗ 9 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 53.80 | 5.59s | score=-109220 |
| actual | ✗ poor | 20.30 | 0.00s | source=tba |

**Trial distribution**

- **frc-scheduler-server** (44 trials): composite best 53.80, median 75.20, worst 102.40, std 9.27
  - repeat_partners: best 2, median 11, worst 19
  - max_color_imbalance: best 3, median 5, worst 7

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 5434 | 3.94 | 3 | 2 | 9 | 1 | 4 | 1 |
| 2 | 2549 | 3.50 | 1 | 2 | 10 | 1 | 7 | 1 |
| 3 | 1816 | 3.13 | 1 | 2 | 9 | 1 | 3 | 1 |
| 4 | 3407 | 3.13 | 1 | 2 | 9 | 1 | 3 | 1 |
| 5 | 3454 | 3.13 | 1 | 2 | 9 | 1 | 3 | 1 |

**Most-affected teams in actual's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 2515 | 3.67 | 2 | 1 | 7 | 0 | 1 | 0 |
| 2 | 5271 | 3.00 | 0 | 1 | 7 | 0 | 0 | 2 |
| 3 | 2450 | 2.83 | 1 | 0 | 7 | 0 | 1 | 1 |
| 4 | 2502 | 2.83 | 1 | 0 | 7 | 0 | 1 | 1 |
| 5 | 3018 | 2.83 | 1 | 0 | 7 | 0 | 1 | 1 |

## 2023mnst — Minnesota State High School League Championship

- 36 teams, 8 matches each, 3v3
- Expected total matches: 48
- Notes: Pulled from TBA on 2026-05-09. 36 teams, 48 qual matches.

| Metric | Threshold (good / accept) | frc-scheduler-server | actual |
|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✗ 9 | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | · 2 | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 63 | ✗ 34 |
| max_opponent_repeats | ≤2 / ≤2 | ✓ 2 | ✓ 2 |
| max_color_imbalance | ≤1 / ≤2 | · 2 | · 2 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 3 | ✓ 1 |
| min_match_gap | ≥4 / ≥4 | ✓ 4 | ✓ 4 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 0 | — 0 |
| matches_per_team | — | ✓ 8 | ✓ 8 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 37.10 | 1.94s | score=-60160 |
| actual | ✗ poor | 13.20 | 0.00s | source=tba |

**Trial distribution**

- **frc-scheduler-server** (50 trials): composite best 37.10, median 65.00, worst 74.80, std 8.01
  - repeat_partners: best 4, median 9, worst 17
  - max_color_imbalance: best 2, median 4, worst 6

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 2264 | 3.17 | 2 | 1 | 5 | 1 | 4 | 2 |
| 2 | 3184 | 3.17 | 2 | 1 | 4 | 1 | 4 | 0 |
| 3 | 3082 | 3.00 | 2 | 2 | 5 | 2 | 3 | 0 |
| 4 | 4536 | 2.67 | 2 | 1 | 5 | 0 | 4 | 2 |
| 5 | 4663 | 2.67 | 2 | 1 | 5 | 0 | 4 | 2 |

**Most-affected teams in actual's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 2220 | 3.00 | 2 | 1 | 4 | 0 | 3 | 0 |
| 2 | 2987 | 3.00 | 2 | 1 | 4 | 0 | 3 | 0 |
| 3 | 3926 | 3.00 | 2 | 1 | 4 | 0 | 3 | 0 |
| 4 | 5638 | 3.00 | 2 | 1 | 4 | 0 | 3 | 0 |
| 5 | 7257 | 3.00 | 2 | 1 | 4 | 0 | 3 | 0 |

## 2024micmp1 — FIRST in Michigan State Championship - DTE Energy Foundation Division

- 40 teams, 12 matches each, 3v3
- Expected total matches: 80
- Notes: Pulled from TBA on 2026-05-09. 40 teams, 80 qual matches.

| Metric | Threshold (good / accept) | frc-scheduler-server | actual |
|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✗ 17 | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | · 2 | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 126 | ✗ 113 |
| max_opponent_repeats | ≤2 / ≤2 | ✗ 3 | ✗ 3 |
| max_color_imbalance | ≤1 / ≤2 | ✗ 6 | · 2 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 3 | ✓ 0 |
| min_match_gap | ≥4 / ≥4 | ✓ 4 | ✓ 4 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 0 | — 0 |
| matches_per_team | — | ✓ 12 | ✓ 12 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 55.30 | 3.51s | score=-106040 |
| actual | ✗ poor | 23.20 | 0.00s | source=tba |

**Trial distribution**

- **frc-scheduler-server** (50 trials): composite best 55.30, median 63.30, worst 73.20, std 4.98
  - repeat_partners: best 17, median 27, worst 37
  - max_color_imbalance: best 2, median 4, worst 8

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 6538 | 3.90 | 2 | 2 | 5 | 2 | 6 | 2 |
| 2 | 6120 | 3.30 | 2 | 2 | 5 | 0 | 8 | 2 |
| 3 | 4453 | 3.17 | 0 | 2 | 5 | 2 | 9 | 0 |
| 4 | 818 | 3.10 | 2 | 2 | 5 | 0 | 7 | 2 |
| 5 | 2224 | 3.10 | 0 | 0 | 5 | 2 | 7 | 2 |

**Most-affected teams in actual's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 7769 | 3.00 | 2 | 0 | 4 | 0 | 9 | 0 |
| 2 | 6538 | 2.86 | 2 | 0 | 4 | 0 | 8 | 0 |
| 3 | 857 | 2.71 | 2 | 0 | 4 | 0 | 7 | 0 |
| 4 | 3641 | 2.57 | 2 | 0 | 4 | 0 | 6 | 0 |
| 5 | 7056 | 2.57 | 2 | 0 | 4 | 0 | 6 | 0 |

## 2024micmp2 — FIRST in Michigan State Championship - Hemlock Semiconductor Division

- 40 teams, 12 matches each, 3v3
- Expected total matches: 80
- Notes: Pulled from TBA on 2026-05-09. 40 teams, 80 qual matches.

| Metric | Threshold (good / accept) | frc-scheduler-server | actual |
|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✗ 31 | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | · 2 | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 136 | ✗ 132 |
| max_opponent_repeats | ≤2 / ≤2 | ✗ 3 | ✗ 3 |
| max_color_imbalance | ≤1 / ≤2 | · 2 | · 2 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 4 | ✓ 0 |
| min_match_gap | ≥4 / ≥4 | ✓ 5 | ✓ 4 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 0 | — 0 |
| matches_per_team | — | ✓ 12 | ✓ 12 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 49.30 | 3.56s | score=-105560 |
| actual | ✗ poor | 23.20 | 0.00s | source=tba |

**Trial distribution**

- **frc-scheduler-server** (49 trials): composite best 49.30, median 65.20, worst 76.00, std 5.92
  - repeat_partners: best 15, median 26, worst 38
  - max_color_imbalance: best 2, median 4, worst 8

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 5901 | 4.10 | 0 | 3 | 5 | 3 | 7 | 2 |
| 2 | 27 | 4.00 | 2 | 2 | 5 | 2 | 9 | 0 |
| 3 | 548 | 4.00 | 2 | 2 | 5 | 2 | 9 | 0 |
| 4 | 7211 | 4.00 | 2 | 2 | 5 | 2 | 9 | 0 |
| 5 | 5216 | 3.85 | 2 | 2 | 5 | 3 | 7 | 0 |

**Most-affected teams in actual's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 4004 | 3.00 | 2 | 0 | 4 | 0 | 11 | 0 |
| 2 | 548 | 2.71 | 2 | 0 | 4 | 0 | 9 | 0 |
| 3 | 3655 | 2.71 | 2 | 0 | 4 | 0 | 9 | 0 |
| 4 | 5712 | 2.71 | 2 | 0 | 4 | 0 | 9 | 0 |
| 5 | 3707 | 2.57 | 2 | 0 | 4 | 0 | 8 | 0 |

## 2024micmp3 — FIRST in Michigan State Championship - Consumers Energy Division

- 40 teams, 12 matches each, 3v3
- Expected total matches: 80
- Notes: Pulled from TBA on 2026-05-09. 40 teams, 80 qual matches.

| Metric | Threshold (good / accept) | frc-scheduler-server | actual |
|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✗ 19 | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | · 2 | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 123 | ✗ 121 |
| max_opponent_repeats | ≤2 / ≤2 | ✗ 3 | ✗ 3 |
| max_color_imbalance | ≤1 / ≤2 | ✗ 4 | · 2 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 3 | ✓ 0 |
| min_match_gap | ≥4 / ≥4 | ✓ 4 | ✓ 4 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 0 | — 0 |
| matches_per_team | — | ✓ 12 | ✓ 12 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 55.30 | 3.52s | score=-104160 |
| actual | ✗ poor | 23.20 | 0.00s | source=tba |

**Trial distribution**

- **frc-scheduler-server** (49 trials): composite best 55.30, median 65.70, worst 76.20, std 6.13
  - repeat_partners: best 17, median 27, worst 37
  - max_color_imbalance: best 2, median 4, worst 8

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 3688 | 3.95 | 0 | 3 | 4 | 2 | 5 | 2 |
| 2 | 3770 | 3.57 | 2 | 3 | 5 | 3 | 7 | 0 |
| 3 | 5530 | 3.48 | 2 | 2 | 5 | 2 | 4 | 2 |
| 4 | 1506 | 2.86 | 2 | 3 | 5 | 0 | 9 | 0 |
| 5 | 4967 | 2.76 | 2 | 2 | 5 | 2 | 6 | 0 |

**Most-affected teams in actual's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 3538 | 3.00 | 2 | 0 | 4 | 0 | 8 | 0 |
| 2 | 4967 | 3.00 | 2 | 0 | 4 | 0 | 8 | 0 |
| 3 | 8427 | 3.00 | 2 | 0 | 4 | 0 | 8 | 0 |
| 4 | 68 | 2.80 | 2 | 0 | 4 | 0 | 7 | 0 |
| 5 | 280 | 2.80 | 2 | 0 | 4 | 0 | 7 | 0 |

## 2024micmp4 — FIRST in Michigan State Championship - Aptiv Division

- 40 teams, 12 matches each, 3v3
- Expected total matches: 80
- Notes: Pulled from TBA on 2026-05-09. 40 teams, 80 qual matches.

| Metric | Threshold (good / accept) | frc-scheduler-server | actual |
|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✗ 30 | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | · 2 | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 136 | ✗ 133 |
| max_opponent_repeats | ≤2 / ≤2 | ✓ 2 | ✗ 3 |
| max_color_imbalance | ≤1 / ≤2 | ✗ 4 | · 2 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 3 | ✓ 0 |
| min_match_gap | ≥4 / ≥4 | ✓ 5 | ✓ 4 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 0 | — 0 |
| matches_per_team | — | ✓ 12 | ✓ 12 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 46.40 | 3.59s | score=-106010 |
| actual | ✗ poor | 23.20 | 0.00s | source=tba |

**Trial distribution**

- **frc-scheduler-server** (50 trials): composite best 46.40, median 58.40, worst 76.20, std 5.79
  - repeat_partners: best 17, median 27, worst 33
  - max_color_imbalance: best 2, median 4, worst 8

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 6002 | 4.58 | 2 | 2 | 5 | 2 | 9 | 2 |
| 2 | 5534 | 4.33 | 2 | 2 | 5 | 2 | 7 | 2 |
| 3 | 6548 | 3.88 | 2 | 0 | 5 | 3 | 6 | 2 |
| 4 | 6121 | 3.79 | 2 | 2 | 5 | 3 | 8 | 0 |
| 5 | 7782 | 3.54 | 2 | 2 | 5 | 3 | 6 | 0 |

**Most-affected teams in actual's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 9572 | 3.00 | 2 | 0 | 4 | 0 | 10 | 0 |
| 2 | 9312 | 2.86 | 2 | 0 | 4 | 0 | 9 | 0 |
| 3 | 226 | 2.71 | 2 | 0 | 4 | 0 | 8 | 0 |
| 4 | 2620 | 2.71 | 2 | 0 | 4 | 0 | 8 | 0 |
| 5 | 3604 | 2.71 | 2 | 0 | 4 | 0 | 8 | 0 |

## 2024mndu — Lake Superior Regional

- 55 teams, 9 matches each, 3v3
- Expected total matches: 82
- Notes: Pulled from TBA on 2026-05-09. 55 teams, 83 qual matches.

| Metric | Threshold (good / accept) | frc-scheduler-server | actual |
|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✗ 8 | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | · 2 | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 76 | ✓ 1 |
| max_opponent_repeats | ≤2 / ≤2 | ✓ 2 | ✓ 2 |
| max_color_imbalance | ≤1 / ≤2 | ✗ 3 | ✗ 3 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 2 | ✓ 1 |
| min_match_gap | ≥4 / ≥4 | ✓ 5 | ✓ 5 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 3 | — 3 |
| matches_per_team | — | ✗ 9 | ✗ 9 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 54.10 | 4.71s | score=-99050 |
| actual | ✗ poor | 20.30 | 0.00s | source=tba |

**Trial distribution**

- **frc-scheduler-server** (42 trials): composite best 54.10, median 84.60, worst 95.10, std 10.12
  - repeat_partners: best 7, median 12, worst 17
  - max_color_imbalance: best 3, median 5, worst 7

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 5903 | 3.85 | 3 | 2 | 8 | 1 | 3 | 1 |
| 2 | 3267 | 3.80 | 0 | 2 | 7 | 1 | 4 | 2 |
| 3 | 2526 | 3.70 | 3 | 2 | 7 | 1 | 1 | 1 |
| 4 | 6217 | 3.68 | 1 | 2 | 8 | 2 | 3 | 1 |
| 5 | 2847 | 3.58 | 1 | 2 | 8 | 1 | 5 | 1 |

**Most-affected teams in actual's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 2977 | 3.50 | 2 | 1 | 5 | 0 | 1 | 0 |
| 2 | 5278 | 3.50 | 2 | 1 | 5 | 0 | 1 | 0 |
| 3 | 3291 | 3.17 | 2 | 1 | 6 | 0 | 0 | 2 |
| 4 | 3197 | 2.50 | 3 | 0 | 5 | 0 | 0 | 1 |
| 5 | 5253 | 2.50 | 3 | 0 | 5 | 0 | 0 | 1 |

## 2024mnmi — Minnesota 10,000 Lakes Regional

- 62 teams, 9 matches each, 3v3
- Expected total matches: 93
- Notes: Pulled from TBA on 2026-05-09. 62 teams, 93 qual matches.

| Metric | Threshold (good / accept) | frc-scheduler-server | actual |
|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✗ 6 | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | · 2 | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 72 | ✓ 4 |
| max_opponent_repeats | ≤2 / ≤2 | ✓ 2 | ✓ 2 |
| max_color_imbalance | ≤1 / ≤2 | ✗ 3 | ✗ 3 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 5 | ✓ 0 |
| min_match_gap | ≥4 / ≥4 | ✓ 5 | ✓ 7 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 0 | — 0 |
| matches_per_team | — | ✓ 9 | ✓ 9 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 43.90 | 5.81s | score=-108090 |
| actual | ✗ poor | 10.30 | 0.00s | source=tba |

**Trial distribution**

- **frc-scheduler-server** (50 trials): composite best 43.90, median 54.60, worst 71.60, std 7.29
  - repeat_partners: best 4, median 10, worst 21
  - max_color_imbalance: best 3, median 5, worst 7

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 2846 | 2.60 | 1 | 2 | 9 | 2 | 5 | 1 |
| 2 | 2823 | 2.00 | 3 | 0 | 9 | 0 | 4 | 1 |
| 3 | 2855 | 2.00 | 3 | 2 | 9 | 0 | 2 | 1 |
| 4 | 5271 | 1.80 | 1 | 2 | 8 | 0 | 5 | 1 |
| 5 | 2143 | 1.80 | 3 | 2 | 9 | 0 | 1 | 1 |

**Most-affected teams in actual's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 2472 | 3.00 | 3 | 0 | 7 | 0 | 1 | 1 |
| 2 | 2500 | 2.00 | 3 | 0 | 7 | 0 | 0 | 1 |
| 3 | 2502 | 2.00 | 1 | 0 | 7 | 0 | 1 | 1 |
| 4 | 2530 | 2.00 | 1 | 0 | 7 | 0 | 1 | 1 |
| 5 | 3122 | 2.00 | 1 | 0 | 7 | 0 | 1 | 1 |

## 2024mnst — Minnesota State High School League Championship

- 36 teams, 8 matches each, 3v3
- Expected total matches: 48
- Notes: Pulled from TBA on 2026-05-09. 36 teams, 48 qual matches.

| Metric | Threshold (good / accept) | frc-scheduler-server | actual |
|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✗ 12 | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | · 2 | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 61 | ✗ 37 |
| max_opponent_repeats | ≤2 / ≤2 | ✓ 2 | ✗ 3 |
| max_color_imbalance | ≤1 / ≤2 | ✗ 4 | · 2 |
| teams_with_5_2_color | ≤0 / ≤0 | ✗ 4 | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 4 | ✓ 1 |
| min_match_gap | ≥4 / ≥4 | ✓ 4 | ✓ 4 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 0 | — 0 |
| matches_per_team | — | ✓ 8 | ✓ 8 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 54.60 | 1.97s | score=-61520 |
| actual | ✗ poor | 23.20 | 0.00s | source=tba |

**Trial distribution**

- **frc-scheduler-server** (50 trials): composite best 54.60, median 74.40, worst 84.40, std 6.01
  - repeat_partners: best 5, median 10, worst 15
  - max_color_imbalance: best 2, median 4, worst 8

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 2977 | 3.17 | 0 | 2 | 5 | 1 | 6 | 2 |
| 2 | 9745 | 3.13 | 0 | 2 | 4 | 3 | 5 | 0 |
| 3 | 5690 | 3.10 | 0 | 4 | 5 | 0 | 4 | 2 |
| 4 | 5172 | 2.90 | 4 | 1 | 5 | 3 | 3 | 0 |
| 5 | 6045 | 2.90 | 2 | 1 | 4 | 0 | 3 | 2 |

**Most-affected teams in actual's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 2977 | 3.00 | 2 | 1 | 4 | 0 | 4 | 0 |
| 2 | 4607 | 3.00 | 2 | 1 | 4 | 0 | 4 | 0 |
| 3 | 1816 | 2.75 | 2 | 1 | 4 | 0 | 3 | 0 |
| 4 | 3102 | 2.75 | 2 | 1 | 4 | 0 | 3 | 0 |
| 5 | 9745 | 2.75 | 2 | 1 | 4 | 0 | 3 | 0 |

## 2024week0 — Week 0

- 32 teams, 3 matches each, 3v3
- Expected total matches: 16
- Notes: Pulled from TBA on 2026-05-09. 32 teams, 16 qual matches. NOTE: 8 teams played a non-modal count ([88, 238, 509, 811, 2342]...)

| Metric | Threshold (good / accept) | frc-scheduler-server | actual |
|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✓ 0 | · 1 |
| max_partner_repeats | ≤1 / ≤2 | ✓ 1 | · 2 |
| repeat_opponents | ≤20 / ≤27 | ✓ 5 | ✓ 3 |
| max_opponent_repeats | ≤2 / ≤2 | ✓ 2 | ✓ 2 |
| max_color_imbalance | ≤1 / ≤2 | ✗ 3 | ✗ 3 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 2 | ✗ 2 |
| min_match_gap | ≥4 / ≥4 | ✓ 4 | ✗ 1 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ✗ 3 |
| surrogate_count | ≤0 / ≤0 | — 0 | — 0 |
| matches_per_team | — | ✓ 3 | ✗ 3 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 20.30 | 0.67s | score=-19410 |
| actual | ✗ poor | 56.40 | 0.00s | source=tba |

**Trial distribution**

- **frc-scheduler-server** (50 trials): composite best 20.30, median 26.40, worst 36.40, std 5.79
  - repeat_partners: best 0, median 0, worst 2
  - max_color_imbalance: best 3, median 3, worst 3

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 811 | 2.50 | 1 | 2 | 5 | 0 | 1 | 1 |
| 2 | 2084 | 2.50 | 1 | 2 | 5 | 0 | 1 | 1 |
| 3 | 2713 | 2.50 | 3 | 0 | 5 | 0 | 1 | 1 |
| 4 | 4761 | 2.50 | 1 | 2 | 5 | 0 | 1 | 1 |
| 5 | 5422 | 2.50 | 3 | 2 | 5 | 0 | 0 | 1 |

**Most-affected teams in actual's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 2423 | 4.50 | 0 | 1 | 1 | 1 | 2 | 2 |
| 2 | 88 | 4.04 | 2 | 1 | 2 | 0 | 2 | 2 |
| 3 | 811 | 4.00 | 0 | 1 | 1 | 1 | 1 | 2 |
| 4 | 6153 | 2.71 | 1 | 2 | 6 | 0 | 1 | 1 |
| 5 | 2084 | 2.58 | 1 | 2 | 3 | 0 | 0 | 1 |

## 2025mndu — Lake Superior Regional

- 54 teams, 9 matches each, 3v3
- Expected total matches: 81
- Notes: Pulled from TBA on 2026-05-09. 54 teams, 81 qual matches.

| Metric | Threshold (good / accept) | frc-scheduler-server | actual |
|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✗ 14 | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | · 2 | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 98 | ✓ 8 |
| max_opponent_repeats | ≤2 / ≤2 | ✓ 2 | ✓ 2 |
| max_color_imbalance | ≤1 / ≤2 | ✗ 3 | ✗ 3 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 2 | ✓ 0 |
| min_match_gap | ≥4 / ≥4 | ✓ 6 | ✓ 6 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 0 | — 0 |
| matches_per_team | — | ✓ 9 | ✓ 9 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 44.70 | 4.55s | score=-99860 |
| actual | ✗ poor | 10.30 | 0.00s | source=tba |

**Trial distribution**

- **frc-scheduler-server** (50 trials): composite best 44.70, median 64.80, worst 75.00, std 6.67
  - repeat_partners: best 8, median 15, worst 22
  - max_color_imbalance: best 3, median 5, worst 7

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 2861 | 3.03 | 3 | 2 | 8 | 1 | 3 | 1 |
| 2 | 6217 | 2.93 | 1 | 2 | 8 | 2 | 5 | 1 |
| 3 | 8122 | 2.67 | 1 | 2 | 7 | 0 | 7 | 1 |
| 4 | 3206 | 2.63 | 1 | 2 | 8 | 1 | 6 | 1 |
| 5 | 1714 | 2.57 | 1 | 2 | 7 | 1 | 4 | 1 |

**Most-affected teams in actual's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 8122 | 2.50 | 3 | 0 | 6 | 0 | 1 | 1 |
| 2 | 1306 | 2.00 | 1 | 0 | 6 | 0 | 2 | 1 |
| 3 | 2143 | 2.00 | 3 | 0 | 6 | 0 | 0 | 1 |
| 4 | 3206 | 2.00 | 3 | 0 | 6 | 0 | 0 | 1 |
| 5 | 4511 | 2.00 | 3 | 0 | 6 | 0 | 0 | 1 |

## 2025mnmi — Minnesota 10,000 Lakes Regional

- 51 teams, 9 matches each, 3v3
- Expected total matches: 76
- Notes: Pulled from TBA on 2026-05-09. 51 teams, 77 qual matches.

| Metric | Threshold (good / accept) | frc-scheduler-server | actual |
|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✗ 11 | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | · 2 | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 58 | ✓ 7 |
| max_opponent_repeats | ≤2 / ≤2 | ✓ 2 | ✓ 2 |
| max_color_imbalance | ≤1 / ≤2 | ✗ 3 | ✗ 3 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 2 | ✓ 1 |
| min_match_gap | ≥4 / ≥4 | ✓ 4 | ✓ 5 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 3 | — 3 |
| matches_per_team | — | ✗ 9 | ✗ 9 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 54.40 | 4.08s | score=-91070 |
| actual | ✗ poor | 20.30 | 0.00s | source=tba |

**Trial distribution**

- **frc-scheduler-server** (39 trials): composite best 54.40, median 74.20, worst 94.60, std 9.70
  - repeat_partners: best 3, median 8, worst 14
  - max_color_imbalance: best 3, median 5, worst 7

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 2513 | 4.08 | 1 | 2 | 5 | 2 | 3 | 1 |
| 2 | 3891 | 4.00 | 0 | 2 | 4 | 0 | 6 | 2 |
| 3 | 5996 | 3.75 | 0 | 1 | 5 | 1 | 6 | 2 |
| 4 | 2502 | 3.42 | 3 | 2 | 7 | 1 | 1 | 1 |
| 5 | 3745 | 3.42 | 1 | 2 | 7 | 2 | 2 | 1 |

**Most-affected teams in actual's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 6217 | 3.50 | 0 | 1 | 5 | 0 | 1 | 2 |
| 2 | 2491 | 3.00 | 0 | 1 | 5 | 0 | 2 | 0 |
| 3 | 2846 | 3.00 | 0 | 1 | 5 | 0 | 2 | 0 |
| 4 | 2511 | 2.83 | 1 | 0 | 5 | 0 | 2 | 1 |
| 5 | 2502 | 2.50 | 3 | 0 | 6 | 0 | 1 | 1 |

## 2025mnst — Minnesota State High School League Championship

- 36 teams, 7 matches each, 3v3
- Expected total matches: 42
- Notes: Pulled from TBA on 2026-05-09. 36 teams, 42 qual matches.

| Metric | Threshold (good / accept) | frc-scheduler-server | actual |
|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✗ 5 | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | · 2 | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 44 | ✓ 20 |
| max_opponent_repeats | ≤2 / ≤2 | ✓ 2 | ✗ 3 |
| max_color_imbalance | ≤1 / ≤2 | ✗ 7 | ✗ 3 |
| teams_with_5_2_color | ≤0 / ≤0 | ✗ 4 | ✗ 2 |
| max_station_spread | ≤1 / ≤1 | ✗ 4 | ✓ 1 |
| min_match_gap | ≥4 / ≥4 | ✓ 4 | ✓ 4 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 0 | — 0 |
| matches_per_team | — | ✓ 7 | ✓ 7 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 54.20 | 1.72s | score=-53920 |
| actual | ✗ poor | 30.30 | 0.00s | source=tba |

**Trial distribution**

- **frc-scheduler-server** (50 trials): composite best 54.00, median 64.30, worst 83.90, std 6.77
  - repeat_partners: best 2, median 6, worst 11
  - max_color_imbalance: best 3, median 5, worst 7

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 9576 | 3.25 | 7 | 1 | 5 | 1 | 3 | 1 |
| 2 | 3102 | 2.75 | 1 | 1 | 4 | 1 | 3 | 1 |
| 3 | 2225 | 2.50 | 1 | 1 | 4 | 1 | 2 | 1 |
| 4 | 3130 | 2.50 | 1 | 4 | 5 | 0 | 4 | 1 |
| 5 | 2491 | 2.25 | 1 | 1 | 5 | 1 | 3 | 1 |

**Most-affected teams in actual's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 3130 | 2.00 | 1 | 1 | 4 | 0 | 3 | 1 |
| 2 | 3883 | 2.00 | 1 | 1 | 4 | 0 | 3 | 1 |
| 3 | 4728 | 2.00 | 3 | 1 | 4 | 0 | 0 | 1 |
| 4 | 6146 | 2.00 | 1 | 1 | 4 | 0 | 3 | 1 |
| 5 | 2472 | 1.67 | 1 | 1 | 4 | 0 | 2 | 1 |

## 2026mndu — Lake Superior Regional

- 42 teams, 11 matches each, 3v3
- Expected total matches: 77
- Notes: Pulled from TBA on 2026-05-09. 42 teams, 77 qual matches.

| Metric | Threshold (good / accept) | frc-scheduler-server | actual |
|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✗ 18 | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | · 2 | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 129 | ✗ 86 |
| max_opponent_repeats | ≤2 / ≤2 | ✗ 3 | ✗ 3 |
| max_color_imbalance | ≤1 / ≤2 | ✗ 5 | ✗ 3 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 3 | ✓ 1 |
| min_match_gap | ≥4 / ≥4 | ✓ 4 | ✓ 5 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 0 | — 0 |
| matches_per_team | — | ✓ 11 | ✓ 11 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 55.30 | 3.49s | score=-102700 |
| actual | ✗ poor | 30.30 | 0.00s | source=tba |

**Trial distribution**

- **frc-scheduler-server** (49 trials): composite best 55.30, median 66.00, worst 76.40, std 6.12
  - repeat_partners: best 14, median 26, worst 35
  - max_color_imbalance: best 3, median 5, worst 11

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 3883 | 2.83 | 3 | 1 | 6 | 3 | 9 | 1 |
| 2 | 3297 | 2.50 | 1 | 3 | 6 | 1 | 8 | 1 |
| 3 | 7849 | 2.33 | 1 | 1 | 6 | 3 | 9 | 1 |
| 4 | 2503 | 2.17 | 1 | 1 | 6 | 3 | 8 | 1 |
| 5 | 4741 | 2.00 | 1 | 1 | 6 | 3 | 7 | 1 |

**Most-affected teams in actual's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 10490 | 1.80 | 3 | 1 | 5 | 0 | 6 | 1 |
| 2 | 2181 | 1.60 | 3 | 1 | 5 | 0 | 5 | 1 |
| 3 | 3630 | 1.60 | 3 | 1 | 5 | 0 | 5 | 1 |
| 4 | 3691 | 1.60 | 3 | 1 | 5 | 0 | 5 | 1 |
| 5 | 3297 | 1.40 | 3 | 1 | 5 | 0 | 4 | 1 |

## 2026mnst — 2026 MN State Tournament

- 36 teams, 7 matches each, 3v3
- Expected total matches: 42
- Notes: MSHSL state tournament, 36 teams, single-day quals. Reviewer-flagged baseline.

| Metric | Threshold (good / accept) | frc-scheduler-server | actual |
|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✗ 3 | ✗ 9 |
| max_partner_repeats | ≤1 / ≤2 | · 2 | · 2 |
| repeat_opponents | ≤20 / ≤27 | ✗ 42 | ✗ 33 |
| max_opponent_repeats | ≤2 / ≤2 | ✓ 2 | ✗ 3 |
| max_color_imbalance | ≤1 / ≤2 | ✗ 5 | ✗ 5 |
| teams_with_5_2_color | ≤0 / ≤0 | ✗ 4 | ✗ 10 |
| max_station_spread | ≤1 / ≤1 | ✗ 4 | ✗ 3 |
| min_match_gap | ≥4 / ≥4 | ✓ 4 | ✗ 3 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 0 | — 0 |
| matches_per_team | — | ✓ 7 | ✓ 7 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 53.80 | 1.63s | score=-52330 |
| actual | ✗ poor | 74.40 | 0.00s | source=csv |

**Trial distribution**

- **frc-scheduler-server** (50 trials): composite best 53.70, median 66.80, worst 74.40, std 6.41
  - repeat_partners: best 1, median 5, worst 9
  - max_color_imbalance: best 3, median 5, worst 7

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 5348 | 2.50 | 1 | 4 | 5 | 0 | 4 | 1 |
| 2 | 3630 | 2.17 | 5 | 1 | 5 | 0 | 3 | 1 |
| 3 | 4728 | 2.17 | 1 | 3 | 5 | 2 | 1 | 1 |
| 4 | 7257 | 2.17 | 1 | 1 | 4 | 1 | 3 | 1 |
| 5 | 3100 | 2.00 | 1 | 1 | 4 | 0 | 4 | 1 |

**Most-affected teams in actual's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 5348 | 3.00 | 3 | 3 | 3 | 0 | 2 | 1 |
| 2 | 2052 | 2.58 | 5 | 1 | 5 | 1 | 3 | 1 |
| 3 | 7028 | 2.58 | 3 | 3 | 5 | 1 | 1 | 1 |
| 4 | 7257 | 2.58 | 3 | 3 | 5 | 0 | 3 | 1 |
| 5 | 2491 | 2.08 | 1 | 3 | 5 | 0 | 3 | 1 |

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
  reviewer's MatchMaker analysis (800 trials on 36-team field).
- Surrogate slot-fills count toward color/station balance (team is physically there)
  but not toward repeat-partner / repeat-opponent counts (team is filling in,
  not playing competitively).
