# Scheduler eval — 20260509-110904-b03980

Generated: 2026-05-09T16:09:09.415950+00:00

## Summary

- Fixtures: 16
- Adapters per fixture: varies (see per-fixture sections)
- Total runs: 3216 (1542 successful)

Markers: ✓ near-optimal · acceptable · ✗ poor · — descriptive

## Cross-fixture aggregate

Composite score: lower is better. 0 = all metrics near-optimal; ~110 = all metrics poor. The 5-25 band is mixed.

| Adapter | Fixtures | Near-optimal | Acceptable | Poor | Mean composite |
|---|---|---|---|---|---|
| frc-scheduler-server | 16 | 0 | 0 | 16 | 47.67 |
| matchmaker | 0 | 0 | 0 | 0 | nan |
| actual | 16 | 0 | 0 | 16 | 25.77 |

### Head-to-head

Per-fixture wins on composite score. T = within 0.01.

| | frc-scheduler-server | matchmaker | actual |
|---|---|---|---|
| **frc-scheduler-server** | — | 0W-0L-0T | 2W-14L-0T |
| **matchmaker** | 0W-0L-0T | — | 0W-0L-0T |
| **actual** | 14W-2L-0T | 0W-0L-0T | — |

## 2023mndu — Lake Superior Regional

- 60 teams, 9 matches each, 3v3
- Expected total matches: 90
- Notes: Pulled from TBA on 2026-05-09. 60 teams, 90 qual matches.

| Metric | Threshold (good / accept) | frc-scheduler-server | matchmaker | actual |
|---|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✗ 12 | ERROR | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | · 2 | ERROR | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 93 | ERROR | ✓ 4 |
| max_opponent_repeats | ≤2 / ≤2 | ✓ 2 | ERROR | ✓ 2 |
| max_color_imbalance | ≤1 / ≤2 | ✗ 3 | ERROR | ✗ 3 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ERROR | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 2 | ERROR | ✓ 0 |
| min_match_gap | ≥4 / ≥4 | ✓ 6 | ERROR | ✓ 7 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ERROR | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 0 | ERROR | — 0 |
| matches_per_team | — | ✓ 9 | ERROR | ✓ 9 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 44.50 | 5.28s | score=-108300 |
| matchmaker | ERROR | — | — | ValueError: MatchMaker output produced 0 matches — parser may be wrong for this MatchMaker version. Sample of output:
Create schedule for 60 teams playing 9 rounds in 90 matches
with a minimum match separation of 7 running 100000 iterations.

   0:00   11.46% complete (230 updates), less than a minute to go   
   0:00   22.27% complete (248 updates), less than a minute to go   
   0:00   33.69% complete (263 updates), less than a minute to go   
   0:01   45.05% complete (268 updates), less than a minute to go   
   0:01   56.39% complete (274 updates), less than a minute to go   
   0:01   67.73% complete (277 updates), less than a minute to go   
   0:01   79.15% complete (278 updates), less than a minute to go   
   0:02   90.55% complete (279 updates), less than a minute to go   
   0:02   100.00% complete (279 updates), operation complete         
Results for 60 teams playing 9 rounds in 90 matches
with a minimum match separation of 7.

Match Schedule
--------------
  1:   60    16    24    36    22    42 
  2:   43    14    11     7    35    56 
  3:   50    32    59    47    13    54 
  4:    3 |
| actual | ✗ poor | 10.30 | 0.00s | source=tba |

**Trial distribution**

- **frc-scheduler-server** (100 trials): composite best 44.50, median 64.90, worst 72.80, std 5.45
  - repeat_partners: best 8, median 16, worst 23
  - max_color_imbalance: best 3, median 5, worst 9

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 3276 | 3.43 | 3 | 2 | 8 | 1 | 3 | 1 |
| 2 | 2861 | 3.27 | 3 | 2 | 10 | 2 | 3 | 1 |
| 3 | 6318 | 3.08 | 1 | 2 | 7 | 1 | 5 | 1 |
| 4 | 2847 | 3.07 | 1 | 2 | 6 | 2 | 2 | 1 |
| 5 | 4656 | 2.80 | 3 | 2 | 10 | 0 | 4 | 1 |

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

| Metric | Threshold (good / accept) | frc-scheduler-server | matchmaker | actual |
|---|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✗ 10 | ERROR | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | · 2 | ERROR | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 86 | ERROR | ✓ 4 |
| max_opponent_repeats | ≤2 / ≤2 | ✓ 2 | ERROR | ✓ 2 |
| max_color_imbalance | ≤1 / ≤2 | ✗ 3 | ERROR | ✗ 3 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ERROR | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 3 | ERROR | ✓ 1 |
| min_match_gap | ≥4 / ≥4 | ✓ 6 | ERROR | ✓ 7 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ERROR | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 3 | ERROR | — 3 |
| matches_per_team | — | ✗ 9 | ERROR | ✗ 9 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 54.30 | 5.58s | score=-110260 |
| matchmaker | ERROR | — | — | RuntimeError: MatchMaker exited 255 for 2023mnmi.
cmd:    /usr/local/bin/matchmaker -t 61 -r 9 -a 3 -u 22
stderr:  |
| actual | ✗ poor | 20.30 | 0.00s | source=tba |

**Trial distribution**

- **frc-scheduler-server** (84 trials): composite best 54.30, median 84.40, worst 95.30, std 9.78
  - repeat_partners: best 5, median 12, worst 18
  - max_color_imbalance: best 3, median 5, worst 9

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 7849 | 3.85 | 3 | 3 | 9 | 0 | 4 | 1 |
| 2 | 3871 | 3.82 | 3 | 2 | 9 | 1 | 3 | 1 |
| 3 | 8255 | 3.65 | 3 | 3 | 9 | 0 | 3 | 1 |
| 4 | 7068 | 3.55 | 1 | 2 | 9 | 1 | 5 | 1 |
| 5 | 2518 | 3.35 | 1 | 2 | 9 | 1 | 4 | 1 |

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

| Metric | Threshold (good / accept) | frc-scheduler-server | matchmaker | actual |
|---|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✗ 9 | ERROR | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | · 2 | ERROR | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 63 | ERROR | ✗ 34 |
| max_opponent_repeats | ≤2 / ≤2 | ✓ 2 | ERROR | ✓ 2 |
| max_color_imbalance | ≤1 / ≤2 | · 2 | ERROR | · 2 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ERROR | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 4 | ERROR | ✓ 1 |
| min_match_gap | ≥4 / ≥4 | ✗ 3 | ERROR | ✓ 4 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ERROR | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 0 | ERROR | — 0 |
| matches_per_team | — | ✓ 8 | ERROR | ✓ 8 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 47.10 | 1.97s | score=-60130 |
| matchmaker | ERROR | — | — | ValueError: MatchMaker output produced 0 matches — parser may be wrong for this MatchMaker version. Sample of output:
Create schedule for 36 teams playing 8 rounds in 48 matches
with a minimum match separation of 4 running 100000 iterations.

   0:00   21.37% complete (133 updates), less than a minute to go   
   0:00   42.99% complete (140 updates), less than a minute to go   
   0:00   64.50% complete (141 updates), less than a minute to go   
   0:01   86.26% complete (141 updates), less than a minute to go   
   0:01   100.00% complete (142 updates), operation complete         
Results for 36 teams playing 8 rounds in 48 matches
with a minimum match separation of 4.

Match Schedule
--------------
  1:   15    25    31     4    21    11 
  2:   12    16    26     8    34     9 
  3:   28     3    10    24    19    18 
  4:   14    36    27    29    17    35 
  5:   22     7     1    23    33    20 
  6:    6    32    30     2    13     5 
  7:    3    26     4    16     9    24 
  8:   19    31    35    34    18    15 
  9:   20    10    14     1    27    25 
 10:   21     6    23    33    17    32 |
| actual | ✗ poor | 13.20 | 0.00s | source=tba |

**Trial distribution**

- **frc-scheduler-server** (100 trials): composite best 47.10, median 74.30, worst 82.20, std 7.61
  - repeat_partners: best 3, median 10, worst 18
  - max_color_imbalance: best 2, median 4, worst 8

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 2470 | 4.80 | 2 | 1 | 3 | 3 | 5 | 2 |
| 2 | 4536 | 2.97 | 0 | 2 | 4 | 1 | 5 | 2 |
| 3 | 4728 | 2.63 | 2 | 1 | 4 | 1 | 5 | 0 |
| 4 | 6146 | 2.47 | 2 | 3 | 5 | 0 | 5 | 0 |
| 5 | 2264 | 2.33 | 2 | 1 | 5 | 1 | 6 | 0 |

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

| Metric | Threshold (good / accept) | frc-scheduler-server | matchmaker | actual |
|---|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✗ 28 | ERROR | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | · 2 | ERROR | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 136 | ERROR | ✗ 113 |
| max_opponent_repeats | ≤2 / ≤2 | ✗ 3 | ERROR | ✗ 3 |
| max_color_imbalance | ≤1 / ≤2 | · 2 | ERROR | · 2 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ERROR | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 4 | ERROR | ✓ 0 |
| min_match_gap | ≥4 / ≥4 | ✓ 4 | ERROR | ✓ 4 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ERROR | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 0 | ERROR | — 0 |
| matches_per_team | — | ✓ 12 | ERROR | ✓ 12 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 49.00 | 3.50s | score=-106730 |
| matchmaker | ERROR | — | — | ValueError: MatchMaker output produced 0 matches — parser may be wrong for this MatchMaker version. Sample of output:
Create schedule for 40 teams playing 12 rounds in 80 matches
with a minimum match separation of 4 running 100000 iterations.

   0:00   13.60% complete (147 updates), less than a minute to go   
   0:00   31.14% complete (168 updates), less than a minute to go   
   0:00   48.75% complete (173 updates), less than a minute to go   
   0:01   66.30% complete (177 updates), less than a minute to go   
   0:01   83.93% complete (184 updates), less than a minute to go   
   0:01   100.00% complete (185 updates), operation complete         
Results for 40 teams playing 12 rounds in 80 matches
with a minimum match separation of 4.

Match Schedule
--------------
  1:   19     3    25    33     7    14 
  2:   29    15    20     4    37    27 
  3:   12    35    13    22     2    32 
  4:   23     5    34    28    18    24 
  5:   39    16    10    36     1    21 
  6:   31     9     6    26    11    40 
  7:    8    38    33    30    17    15 
  8:   22    28     3    34    14    20 
  9:   16 |
| actual | ✗ poor | 23.20 | 0.00s | source=tba |

**Trial distribution**

- **frc-scheduler-server** (99 trials): composite best 49.00, median 65.50, worst 83.40, std 6.36
  - repeat_partners: best 15, median 26, worst 40
  - max_color_imbalance: best 2, median 4, worst 10

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 4362 | 4.07 | 2 | 2 | 5 | 2 | 7 | 2 |
| 2 | 2224 | 3.96 | 2 | 4 | 5 | 3 | 8 | 0 |
| 3 | 2959 | 3.96 | 2 | 2 | 5 | 1 | 8 | 2 |
| 4 | 6615 | 3.61 | 2 | 2 | 5 | 3 | 9 | 0 |
| 5 | 9618 | 3.46 | 2 | 2 | 5 | 3 | 8 | 0 |

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

| Metric | Threshold (good / accept) | frc-scheduler-server | matchmaker | actual |
|---|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✗ 25 | ERROR | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | · 2 | ERROR | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 130 | ERROR | ✗ 132 |
| max_opponent_repeats | ≤2 / ≤2 | ✓ 2 | ERROR | ✗ 3 |
| max_color_imbalance | ≤1 / ≤2 | ✗ 4 | ERROR | · 2 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ERROR | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 4 | ERROR | ✓ 0 |
| min_match_gap | ≥4 / ≥4 | ✓ 4 | ERROR | ✓ 4 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ERROR | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 0 | ERROR | — 0 |
| matches_per_team | — | ✓ 12 | ERROR | ✓ 12 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 45.90 | 3.44s | score=-104580 |
| matchmaker | ERROR | — | — | ValueError: MatchMaker output produced 0 matches — parser may be wrong for this MatchMaker version. Sample of output:
Create schedule for 40 teams playing 12 rounds in 80 matches
with a minimum match separation of 4 running 100000 iterations.

   0:00   14.18% complete (137 updates), less than a minute to go   
   0:00   31.07% complete (159 updates), less than a minute to go   
   0:00   48.18% complete (167 updates), less than a minute to go   
   0:01   65.37% complete (170 updates), less than a minute to go   
   0:01   82.80% complete (179 updates), less than a minute to go   
   0:01   100.00% complete (183 updates), operation complete         
Results for 40 teams playing 12 rounds in 80 matches
with a minimum match separation of 4.

Match Schedule
--------------
  1:   26    13    38     1    29    18 
  2:    5    12    23    32    33    39 
  3:   15     3    21    11    19    17 
  4:   30    36    35     6    25    34 
  5:   40    16     7    28    37     9 
  6:   22    14    10    24     4     2 
  7:   20    31     3     8    27     5 
  8:    6    23    33    17    38    36 
  9:   12 |
| actual | ✗ poor | 23.20 | 0.00s | source=tba |

**Trial distribution**

- **frc-scheduler-server** (97 trials): composite best 45.90, median 58.40, worst 76.80, std 6.47
  - repeat_partners: best 18, median 27, worst 37
  - max_color_imbalance: best 2, median 4, worst 10

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 70 | 3.88 | 2 | 2 | 4 | 2 | 6 | 2 |
| 2 | 3620 | 3.88 | 4 | 2 | 5 | 1 | 8 | 2 |
| 3 | 245 | 3.38 | 4 | 2 | 5 | 1 | 4 | 2 |
| 4 | 3175 | 3.00 | 2 | 2 | 5 | 0 | 7 | 2 |
| 5 | 4004 | 2.75 | 2 | 2 | 5 | 1 | 11 | 0 |

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

| Metric | Threshold (good / accept) | frc-scheduler-server | matchmaker | actual |
|---|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✗ 31 | ERROR | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | · 2 | ERROR | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 125 | ERROR | ✗ 121 |
| max_opponent_repeats | ≤2 / ≤2 | ✗ 3 | ERROR | ✗ 3 |
| max_color_imbalance | ≤1 / ≤2 | · 2 | ERROR | · 2 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ERROR | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 4 | ERROR | ✓ 0 |
| min_match_gap | ≥4 / ≥4 | ✓ 4 | ERROR | ✓ 4 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ERROR | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 0 | ERROR | — 0 |
| matches_per_team | — | ✓ 12 | ERROR | ✓ 12 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 49.30 | 3.50s | score=-104660 |
| matchmaker | ERROR | — | — | ValueError: MatchMaker output produced 0 matches — parser may be wrong for this MatchMaker version. Sample of output:
Create schedule for 40 teams playing 12 rounds in 80 matches
with a minimum match separation of 4 running 100000 iterations.

   0:00   15.13% complete (138 updates), less than a minute to go   
   0:00   32.39% complete (156 updates), less than a minute to go   
   0:00   49.69% complete (164 updates), less than a minute to go   
   0:01   67.11% complete (165 updates), less than a minute to go   
   0:01   84.54% complete (166 updates), less than a minute to go   
   0:01   100.00% complete (166 updates), operation complete         
Results for 40 teams playing 12 rounds in 80 matches
with a minimum match separation of 4.

Match Schedule
--------------
  1:   32    21    18    34     3    19 
  2:   28    31    29     8     4    26 
  3:   40    15     2    36     5    25 
  4:   17    20    30    33     7    22 
  5:    6    16    12    37    11    10 
  6:   24    13     9    38     1    35 
  7:   39    23     3    27    14    29 
  8:   33    19     4    28    22    32 
  9:   17 |
| actual | ✗ poor | 23.20 | 0.00s | source=tba |

**Trial distribution**

- **frc-scheduler-server** (98 trials): composite best 49.30, median 62.10, worst 86.00, std 6.94
  - repeat_partners: best 15, median 27, worst 35
  - max_color_imbalance: best 2, median 4, worst 8

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 1 | 4.35 | 2 | 2 | 4 | 1 | 7 | 2 |
| 2 | 1684 | 4.20 | 2 | 2 | 5 | 4 | 5 | 2 |
| 3 | 3572 | 3.20 | 2 | 4 | 5 | 2 | 5 | 0 |
| 4 | 68 | 2.90 | 2 | 2 | 5 | 2 | 6 | 0 |
| 5 | 5436 | 2.90 | 2 | 2 | 5 | 2 | 6 | 0 |

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

| Metric | Threshold (good / accept) | frc-scheduler-server | matchmaker | actual |
|---|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✗ 21 | ERROR | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | · 2 | ERROR | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 136 | ERROR | ✗ 133 |
| max_opponent_repeats | ≤2 / ≤2 | ✗ 3 | ERROR | ✗ 3 |
| max_color_imbalance | ≤1 / ≤2 | ✗ 4 | ERROR | · 2 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ERROR | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 3 | ERROR | ✓ 0 |
| min_match_gap | ≥4 / ≥4 | ✓ 5 | ERROR | ✓ 4 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ERROR | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 0 | ERROR | — 0 |
| matches_per_team | — | ✓ 12 | ERROR | ✓ 12 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 55.50 | 3.53s | score=-105560 |
| matchmaker | ERROR | — | — | ValueError: MatchMaker output produced 0 matches — parser may be wrong for this MatchMaker version. Sample of output:
Create schedule for 40 teams playing 12 rounds in 80 matches
with a minimum match separation of 4 running 100000 iterations.

   0:00   15.20% complete (145 updates), less than a minute to go   
   0:00   31.95% complete (163 updates), less than a minute to go   
   0:00   48.77% complete (170 updates), less than a minute to go   
   0:01   65.85% complete (178 updates), less than a minute to go   
   0:01   82.94% complete (181 updates), less than a minute to go   
   0:01   99.84% complete (183 updates), less than a minute to go   
   0:01   100.00% complete (183 updates), operation complete         
Results for 40 teams playing 12 rounds in 80 matches
with a minimum match separation of 4.

Match Schedule
--------------
  1:   24     8     2    27     4    40 
  2:    7     6    22    28     3     1 
  3:   21     5    19    16    14    38 
  4:   17    36    26    15    35    13 
  5:   23    33    32    11    37     9 
  6:   18    34    31    30    25    10 
  7:   12    20     4  |
| actual | ✗ poor | 23.20 | 0.00s | source=tba |

**Trial distribution**

- **frc-scheduler-server** (97 trials): composite best 55.50, median 65.40, worst 76.60, std 5.50
  - repeat_partners: best 16, median 27, worst 36
  - max_color_imbalance: best 4, median 4, worst 10

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 226 | 4.00 | 2 | 2 | 5 | 3 | 8 | 0 |
| 2 | 1711 | 4.00 | 2 | 3 | 5 | 2 | 8 | 0 |
| 3 | 5641 | 4.00 | 2 | 2 | 5 | 1 | 6 | 2 |
| 4 | 6090 | 4.00 | 2 | 3 | 5 | 3 | 6 | 0 |
| 5 | 2137 | 3.83 | 4 | 2 | 5 | 3 | 4 | 0 |

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

| Metric | Threshold (good / accept) | frc-scheduler-server | matchmaker | actual |
|---|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✗ 12 | ERROR | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | · 2 | ERROR | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 69 | ERROR | ✓ 1 |
| max_opponent_repeats | ≤2 / ≤2 | ✓ 2 | ERROR | ✓ 2 |
| max_color_imbalance | ≤1 / ≤2 | ✗ 3 | ERROR | ✗ 3 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ERROR | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 3 | ERROR | ✓ 1 |
| min_match_gap | ≥4 / ≥4 | ✓ 4 | ERROR | ✓ 5 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ERROR | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 3 | ERROR | — 3 |
| matches_per_team | — | ✗ 9 | ERROR | ✗ 9 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 54.50 | 4.67s | score=-98790 |
| matchmaker | ERROR | — | — | RuntimeError: MatchMaker exited 255 for 2024mndu.
cmd:    /usr/local/bin/matchmaker -t 55 -r 9 -a 3 -u 20
stderr:  |
| actual | ✗ poor | 20.30 | 0.00s | source=tba |

**Trial distribution**

- **frc-scheduler-server** (76 trials): composite best 54.50, median 75.10, worst 95.50, std 9.03
  - repeat_partners: best 6, median 12, worst 20
  - max_color_imbalance: best 3, median 5, worst 9

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 1732 | 3.33 | 1 | 2 | 8 | 2 | 5 | 1 |
| 2 | 7864 | 3.17 | 3 | 2 | 8 | 1 | 3 | 1 |
| 3 | 5143 | 3.08 | 3 | 2 | 7 | 1 | 1 | 1 |
| 4 | 2823 | 3.00 | 1 | 2 | 4 | 0 | 3 | 1 |
| 5 | 7797 | 2.83 | 1 | 2 | 8 | 1 | 5 | 1 |

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

| Metric | Threshold (good / accept) | frc-scheduler-server | matchmaker | actual |
|---|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✗ 7 | ERROR | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | · 2 | ERROR | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 71 | ERROR | ✓ 4 |
| max_opponent_repeats | ≤2 / ≤2 | ✓ 2 | ERROR | ✓ 2 |
| max_color_imbalance | ≤1 / ≤2 | ✗ 3 | ERROR | ✗ 3 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ERROR | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 3 | ERROR | ✓ 0 |
| min_match_gap | ≥4 / ≥4 | ✓ 7 | ERROR | ✓ 7 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ERROR | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 0 | ERROR | — 0 |
| matches_per_team | — | ✓ 9 | ERROR | ✓ 9 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 44.00 | 6.81s | score=-108070 |
| matchmaker | ERROR | — | — | ValueError: MatchMaker output produced 0 matches — parser may be wrong for this MatchMaker version. Sample of output:
Create schedule for 62 teams playing 9 rounds in 93 matches
with a minimum match separation of 7 running 100000 iterations.

   0:00   10.94% complete (204 updates), less than a minute to go   
   0:00   21.81% complete (231 updates), less than a minute to go   
   0:00   32.65% complete (242 updates), less than a minute to go   
   0:01   43.47% complete (247 updates), less than a minute to go   
   0:01   54.33% complete (260 updates), less than a minute to go   
   0:01   65.24% complete (265 updates), less than a minute to go   
   0:01   76.21% complete (266 updates), less than a minute to go   
   0:02   87.12% complete (267 updates), less than a minute to go   
   0:02   98.01% complete (267 updates), less than a minute to go   
   0:02   100.00% complete (268 updates), operation complete         
Results for 62 teams playing 9 rounds in 93 matches
with a minimum match separation of 7.

Match Schedule
--------------
  1:   19    20    37    14    24    60 
  2:   36     5    28  |
| actual | ✗ poor | 10.30 | 0.00s | source=tba |

**Trial distribution**

- **frc-scheduler-server** (100 trials): composite best 44.00, median 54.60, worst 71.70, std 6.90
  - repeat_partners: best 4, median 10, worst 18
  - max_color_imbalance: best 3, median 5, worst 9

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 3202 | 3.00 | 1 | 2 | 9 | 1 | 5 | 1 |
| 2 | 4664 | 2.93 | 3 | 0 | 9 | 1 | 3 | 1 |
| 3 | 9157 | 2.93 | 1 | 3 | 9 | 1 | 3 | 1 |
| 4 | 2518 | 2.80 | 1 | 2 | 9 | 1 | 4 | 1 |
| 5 | 4225 | 2.73 | 3 | 0 | 9 | 1 | 2 | 1 |

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

| Metric | Threshold (good / accept) | frc-scheduler-server | matchmaker | actual |
|---|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✗ 12 | ERROR | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | · 2 | ERROR | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 60 | ERROR | ✗ 37 |
| max_opponent_repeats | ≤2 / ≤2 | ✓ 2 | ERROR | ✗ 3 |
| max_color_imbalance | ≤1 / ≤2 | · 2 | ERROR | · 2 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ERROR | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 3 | ERROR | ✓ 1 |
| min_match_gap | ≥4 / ≥4 | ✓ 4 | ERROR | ✓ 4 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ERROR | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 0 | ERROR | — 0 |
| matches_per_team | — | ✓ 8 | ERROR | ✓ 8 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 37.40 | 1.93s | score=-60400 |
| matchmaker | ERROR | — | — | ValueError: MatchMaker output produced 0 matches — parser may be wrong for this MatchMaker version. Sample of output:
Create schedule for 36 teams playing 8 rounds in 48 matches
with a minimum match separation of 4 running 100000 iterations.

   0:00   12.58% complete (106 updates), less than a minute to go   
   0:00   25.17% complete (113 updates), less than a minute to go   
   0:00   37.78% complete (118 updates), less than a minute to go   
   0:01   56.85% complete (122 updates), less than a minute to go   
   0:01   78.04% complete (127 updates), less than a minute to go   
   0:01   99.20% complete (132 updates), less than a minute to go   
   0:01   100.00% complete (132 updates), operation complete         
Results for 36 teams playing 8 rounds in 48 matches
with a minimum match separation of 4.

Match Schedule
--------------
  1:    9    16    24     5     3    30 
  2:   35    32    31     7    33    26 
  3:   25     2    20    23     6    19 
  4:   12    34    11    17    14    18 
  5:   27    28     4    29    15    10 
  6:   21    36    22     1    13     8 
  7:   30     7    32    |
| actual | ✗ poor | 23.20 | 0.00s | source=tba |

**Trial distribution**

- **frc-scheduler-server** (99 trials): composite best 37.40, median 74.10, worst 81.60, std 8.31
  - repeat_partners: best 3, median 10, worst 18
  - max_color_imbalance: best 2, median 4, worst 8

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 5232 | 4.00 | 2 | 1 | 4 | 0 | 5 | 2 |
| 2 | 3102 | 3.83 | 0 | 3 | 5 | 1 | 5 | 2 |
| 3 | 3184 | 3.83 | 2 | 1 | 5 | 1 | 5 | 2 |
| 4 | 4539 | 3.80 | 2 | 1 | 4 | 0 | 4 | 2 |
| 5 | 6146 | 3.77 | 2 | 1 | 5 | 2 | 3 | 2 |

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

| Metric | Threshold (good / accept) | frc-scheduler-server | matchmaker | actual |
|---|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✓ 0 | ERROR | · 1 |
| max_partner_repeats | ≤1 / ≤2 | ✓ 1 | ERROR | · 2 |
| repeat_opponents | ≤20 / ≤27 | ✓ 6 | ERROR | ✓ 3 |
| max_opponent_repeats | ≤2 / ≤2 | ✓ 2 | ERROR | ✓ 2 |
| max_color_imbalance | ≤1 / ≤2 | ✗ 3 | ERROR | ✗ 3 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ERROR | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 2 | ERROR | ✗ 2 |
| min_match_gap | ≥4 / ≥4 | ✓ 4 | ERROR | ✗ 1 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ERROR | ✗ 3 |
| surrogate_count | ≤0 / ≤0 | — 0 | ERROR | — 0 |
| matches_per_team | — | ✓ 3 | ERROR | ✗ 3 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 20.30 | 0.67s | score=-19500 |
| matchmaker | ERROR | — | — | ValueError: MatchMaker output produced 0 matches — parser may be wrong for this MatchMaker version. Sample of output:
Create schedule for 32 teams playing 3 rounds in 16 matches
with a minimum match separation of 3 running 100000 iterations.

   0:00   31.29% complete (32 updates), less than a minute to go   
   0:00   76.96% complete (33 updates), less than a minute to go   
   0:00   100.00% complete (33 updates), operation complete         
Results for 32 teams playing 3 rounds in 16 matches
with a minimum match separation of 3.

Match Schedule
--------------
  1:   24     4     9    15    17     5 
  2:   16     8    28    25    22    18 
  3:   27     1    13    12    32    23 
  4:   31     3    20    19    14    11 
  5:    7    30    21    29    10     6 
  6:    5    26    22     2    23    17 
  7:   32    31     4    20    25     8 
  8:   21    29    27    11    16    15 
  9:   30    18    14     6    24     1 
 10:   10    28    19     9    13     2 
 11:    3    12    16     4     7    26 
 12:   17    11    25    23     6    30 
 13:   14    15    10    22    19    32 
 14:    1     5  |
| actual | ✗ poor | 56.40 | 0.00s | source=tba |

**Trial distribution**

- **frc-scheduler-server** (100 trials): composite best 20.30, median 26.40, worst 36.50, std 5.15
  - repeat_partners: best 0, median 0, worst 2
  - max_color_imbalance: best 3, median 3, worst 3

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 131 | 3.00 | 1 | 2 | 4 | 0 | 1 | 1 |
| 2 | 501 | 3.00 | 1 | 2 | 4 | 0 | 1 | 1 |
| 3 | 1768 | 2.50 | 1 | 2 | 5 | 0 | 1 | 1 |
| 4 | 3467 | 2.50 | 3 | 0 | 5 | 0 | 1 | 1 |
| 5 | 4909 | 2.50 | 1 | 2 | 5 | 0 | 1 | 1 |

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

| Metric | Threshold (good / accept) | frc-scheduler-server | matchmaker | actual |
|---|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✗ 13 | ERROR | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | · 2 | ERROR | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 80 | ERROR | ✓ 8 |
| max_opponent_repeats | ≤2 / ≤2 | ✓ 2 | ERROR | ✓ 2 |
| max_color_imbalance | ≤1 / ≤2 | ✗ 3 | ERROR | ✗ 3 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ERROR | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 2 | ERROR | ✓ 0 |
| min_match_gap | ≥4 / ≥4 | ✓ 4 | ERROR | ✓ 6 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ERROR | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 0 | ERROR | — 0 |
| matches_per_team | — | ✓ 9 | ERROR | ✓ 9 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 44.60 | 4.42s | score=-97540 |
| matchmaker | ERROR | — | — | ValueError: MatchMaker output produced 0 matches — parser may be wrong for this MatchMaker version. Sample of output:
Create schedule for 54 teams playing 9 rounds in 81 matches
with a minimum match separation of 6 running 100000 iterations.

   0:00   12.13% complete (190 updates), less than a minute to go   
   0:00   24.91% complete (207 updates), less than a minute to go   
   0:00   37.95% complete (220 updates), less than a minute to go   
   0:01   50.70% complete (226 updates), less than a minute to go   
   0:01   63.53% complete (233 updates), less than a minute to go   
   0:01   76.43% complete (239 updates), less than a minute to go   
   0:01   89.13% complete (242 updates), less than a minute to go   
   0:01   100.00% complete (243 updates), operation complete         
Results for 54 teams playing 9 rounds in 81 matches
with a minimum match separation of 6.

Match Schedule
--------------
  1:   31    42    11     1    47     6 
  2:   37    35    15    16    29     7 
  3:   41    20    36    45    28    23 
  4:   46    13    25     2    32    51 
  5:   50    27    54    12    43     |
| actual | ✗ poor | 10.30 | 0.00s | source=tba |

**Trial distribution**

- **frc-scheduler-server** (100 trials): composite best 44.60, median 64.60, worst 81.90, std 6.34
  - repeat_partners: best 7, median 14, worst 21
  - max_color_imbalance: best 3, median 5, worst 9

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 3294 | 2.60 | 1 | 2 | 4 | 0 | 4 | 1 |
| 2 | 1619 | 2.40 | 3 | 2 | 8 | 0 | 2 | 1 |
| 3 | 2181 | 2.40 | 1 | 2 | 8 | 2 | 2 | 1 |
| 4 | 7038 | 2.40 | 1 | 2 | 8 | 2 | 2 | 1 |
| 5 | 7235 | 2.40 | 3 | 0 | 8 | 2 | 2 | 1 |

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

| Metric | Threshold (good / accept) | frc-scheduler-server | matchmaker | actual |
|---|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✗ 4 | ERROR | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | · 2 | ERROR | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 61 | ERROR | ✓ 7 |
| max_opponent_repeats | ≤2 / ≤2 | ✓ 2 | ERROR | ✓ 2 |
| max_color_imbalance | ≤1 / ≤2 | ✗ 3 | ERROR | ✗ 3 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ERROR | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 2 | ERROR | ✓ 1 |
| min_match_gap | ≥4 / ≥4 | ✓ 4 | ERROR | ✓ 5 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ERROR | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 3 | ERROR | — 3 |
| matches_per_team | — | ✗ 9 | ERROR | ✗ 9 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 53.70 | 4.03s | score=-90680 |
| matchmaker | ERROR | — | — | RuntimeError: MatchMaker exited 255 for 2025mnmi.
cmd:    /usr/local/bin/matchmaker -t 51 -r 9 -a 3 -u 18
stderr:  |
| actual | ✗ poor | 20.30 | 0.00s | source=tba |

**Trial distribution**

- **frc-scheduler-server** (79 trials): composite best 53.70, median 74.50, worst 95.30, std 10.14
  - repeat_partners: best 3, median 8, worst 18
  - max_color_imbalance: best 3, median 5, worst 7

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 5464 | 4.15 | 3 | 2 | 7 | 1 | 2 | 1 |
| 2 | 4687 | 3.97 | 2 | 1 | 4 | 0 | 4 | 2 |
| 3 | 4663 | 3.88 | 1 | 2 | 7 | 1 | 4 | 1 |
| 4 | 3745 | 3.68 | 1 | 2 | 7 | 1 | 3 | 1 |
| 5 | 4664 | 3.68 | 1 | 2 | 7 | 1 | 3 | 1 |

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

| Metric | Threshold (good / accept) | frc-scheduler-server | matchmaker | actual |
|---|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✗ 3 | ERROR | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | · 2 | ERROR | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 43 | ERROR | ✓ 20 |
| max_opponent_repeats | ≤2 / ≤2 | ✓ 2 | ERROR | ✗ 3 |
| max_color_imbalance | ≤1 / ≤2 | ✗ 5 | ERROR | ✗ 3 |
| teams_with_5_2_color | ≤0 / ≤0 | ✗ 4 | ERROR | ✗ 2 |
| max_station_spread | ≤1 / ≤1 | ✗ 4 | ERROR | ✓ 1 |
| min_match_gap | ≥4 / ≥4 | ✓ 4 | ERROR | ✓ 4 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ERROR | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 0 | ERROR | — 0 |
| matches_per_team | — | ✓ 7 | ERROR | ✓ 7 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 53.80 | 1.71s | score=-52330 |
| matchmaker | ERROR | — | — | ValueError: MatchMaker output produced 0 matches — parser may be wrong for this MatchMaker version. Sample of output:
Create schedule for 36 teams playing 7 rounds in 42 matches
with a minimum match separation of 4 running 100000 iterations.

   0:00   21.42% complete (100 updates), less than a minute to go   
   0:00   43.60% complete (103 updates), less than a minute to go   
   0:00   65.80% complete (107 updates), less than a minute to go   
   0:01   88.29% complete (110 updates), less than a minute to go   
   0:01   100.00% complete (112 updates), operation complete         
Results for 36 teams playing 7 rounds in 42 matches
with a minimum match separation of 4.

Match Schedule
--------------
  1:   15     7    24     5     1    10 
  2:   13    20    30    32    17    25 
  3:    9    23    26    11     6     3 
  4:   29    28     2    16     8    12 
  5:   36    22    31    14     4    21 
  6:   35    34    18    27    33    19 
  7:   30    26     7    20    24     9 
  8:   25    12     5    23    16     1 
  9:   10     3     2    22    21    13 
 10:   32     6    27    33    31    28 |
| actual | ✗ poor | 30.30 | 0.00s | source=tba |

**Trial distribution**

- **frc-scheduler-server** (100 trials): composite best 53.80, median 64.30, worst 84.10, std 7.28
  - repeat_partners: best 2, median 6, worst 12
  - max_color_imbalance: best 3, median 5, worst 7

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 2470 | 3.43 | 3 | 2 | 4 | 1 | 3 | 1 |
| 2 | 3082 | 3.13 | 3 | 2 | 5 | 1 | 4 | 1 |
| 3 | 3058 | 2.60 | 5 | 1 | 4 | 0 | 3 | 1 |
| 4 | 2491 | 2.50 | 1 | 1 | 5 | 1 | 5 | 1 |
| 5 | 3313 | 1.90 | 1 | 1 | 5 | 1 | 2 | 1 |

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

| Metric | Threshold (good / accept) | frc-scheduler-server | matchmaker | actual |
|---|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✗ 17 | ERROR | ✓ 0 |
| max_partner_repeats | ≤1 / ≤2 | · 2 | ERROR | ✓ 1 |
| repeat_opponents | ≤20 / ≤27 | ✗ 130 | ERROR | ✗ 86 |
| max_opponent_repeats | ≤2 / ≤2 | ✗ 3 | ERROR | ✗ 3 |
| max_color_imbalance | ≤1 / ≤2 | ✗ 5 | ERROR | ✗ 3 |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ERROR | ✓ 0 |
| max_station_spread | ≤1 / ≤1 | ✗ 3 | ERROR | ✓ 1 |
| min_match_gap | ≥4 / ≥4 | ✓ 4 | ERROR | ✓ 5 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ERROR | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 0 | ERROR | — 0 |
| matches_per_team | — | ✓ 11 | ERROR | ✓ 11 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 55.20 | 3.26s | score=-102390 |
| matchmaker | ERROR | — | — | ValueError: MatchMaker output produced 0 matches — parser may be wrong for this MatchMaker version. Sample of output:
Create schedule for 42 teams playing 11 rounds in 77 matches
with a minimum match separation of 5 running 100000 iterations.

   0:00   16.12% complete (162 updates), less than a minute to go   
   0:00   33.33% complete (179 updates), less than a minute to go   
   0:00   50.56% complete (191 updates), less than a minute to go   
   0:01   68.21% complete (199 updates), less than a minute to go   
   0:01   85.92% complete (199 updates), less than a minute to go   
   0:01   100.00% complete (199 updates), operation complete         
Results for 42 teams playing 11 rounds in 77 matches
with a minimum match separation of 5.

Match Schedule
--------------
  1:   20    42    29    22    34    12 
  2:    9    32    24    40    28    39 
  3:   11    13     5    19    35    37 
  4:   31    17    27     7     2    18 
  5:   10    41    23    21    15    25 
  6:   26     8    30     6     3     1 
  7:   16    14    38     4    33    36 
  8:   40    29    35     9    13    39 
  9:   42 |
| actual | ✗ poor | 30.30 | 0.00s | source=tba |

**Trial distribution**

- **frc-scheduler-server** (97 trials): composite best 55.20, median 65.90, worst 82.90, std 5.82
  - repeat_partners: best 16, median 26, worst 36
  - max_color_imbalance: best 3, median 5, worst 9

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 8422 | 3.10 | 5 | 1 | 4 | 1 | 7 | 1 |
| 2 | 4741 | 2.50 | 1 | 3 | 6 | 1 | 9 | 1 |
| 3 | 5690 | 2.30 | 1 | 1 | 5 | 2 | 8 | 1 |
| 4 | 3042 | 2.10 | 3 | 1 | 6 | 2 | 7 | 1 |
| 5 | 2181 | 1.80 | 1 | 1 | 5 | 1 | 8 | 1 |

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

| Metric | Threshold (good / accept) | frc-scheduler-server | matchmaker | actual |
|---|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✗ 4 | ERROR | ✗ 9 |
| max_partner_repeats | ≤1 / ≤2 | · 2 | ERROR | · 2 |
| repeat_opponents | ≤20 / ≤27 | ✗ 49 | ERROR | ✗ 33 |
| max_opponent_repeats | ≤2 / ≤2 | ✓ 2 | ERROR | ✗ 3 |
| max_color_imbalance | ≤1 / ≤2 | ✗ 3 | ERROR | ✗ 5 |
| teams_with_5_2_color | ≤0 / ≤0 | ✗ 3 | ERROR | ✗ 10 |
| max_station_spread | ≤1 / ≤1 | ✗ 3 | ERROR | ✗ 3 |
| min_match_gap | ≥4 / ≥4 | ✓ 4 | ERROR | ✗ 3 |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ERROR | ✓ 0 |
| surrogate_count | ≤0 / ≤0 | — 0 | ERROR | — 0 |
| matches_per_team | — | ✓ 7 | ERROR | ✓ 7 |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 53.70 | 1.57s | score=-52210 |
| matchmaker | ERROR | — | — | ValueError: MatchMaker output produced 0 matches — parser may be wrong for this MatchMaker version. Sample of output:
Create schedule for 36 teams playing 7 rounds in 42 matches
with a minimum match separation of 4 running 100000 iterations.

   0:00   22.61% complete (100 updates), less than a minute to go   
   0:00   46.12% complete (118 updates), less than a minute to go   
   0:00   69.89% complete (122 updates), less than a minute to go   
   0:01   93.95% complete (122 updates), less than a minute to go   
   0:01   100.00% complete (122 updates), operation complete         
Results for 36 teams playing 7 rounds in 42 matches
with a minimum match separation of 4.

Match Schedule
--------------
  1:   29    24     3    14    31    27 
  2:    7     5    15    17    35    18 
  3:   36    26    33    10     2     4 
  4:    1    20    11    22    16    21 
  5:   13    19    23     6    12    25 
  6:    8    30    34    28     9    32 
  7:   27     2    35    31    10    24 
  8:   18    33     7     3    14    16 
  9:   25     4    19    15    22     1 
 10:   32    11    30     6    13    26 |
| actual | ✗ poor | 74.40 | 0.00s | source=csv |

**Trial distribution**

- **frc-scheduler-server** (100 trials): composite best 53.70, median 64.20, worst 84.30, std 7.55
  - repeat_partners: best 1, median 6, worst 12
  - max_color_imbalance: best 3, median 5, worst 7

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 4778 | 2.75 | 3 | 3 | 5 | 0 | 4 | 1 |
| 2 | 2052 | 2.25 | 1 | 3 | 5 | 1 | 2 | 1 |
| 3 | 4174 | 2.00 | 1 | 1 | 5 | 1 | 5 | 1 |
| 4 | 3100 | 1.75 | 3 | 1 | 5 | 0 | 4 | 1 |
| 5 | 4728 | 1.75 | 1 | 1 | 5 | 1 | 4 | 1 |

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
