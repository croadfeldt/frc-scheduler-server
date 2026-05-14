# Scheduler eval — 20260513-204812-d7a7f1

Generated: 2026-05-14T01:48:12.244113+00:00

## Summary

- Fixtures: 3
- Adapters per fixture: varies (see per-fixture sections)
- Total runs: 6 (3 successful)

Markers: ✓ near-optimal · acceptable · ✗ poor · — descriptive

## Cross-fixture aggregate

Composite score: lower is better. 0 = all metrics near-optimal; ~110 = all metrics poor. The 5-25 band is mixed.

| Adapter | Fixtures | Near-optimal | Acceptable | Poor | Mean composite |
|---|---|---|---|---|---|
| frc-scheduler-server | 3 | 0 | 0 | 3 | 47.97 |
| matchmaker | 0 | 0 | 0 | 0 | nan |

### Head-to-head

Per-fixture wins on composite score. T = within 0.01.

| | frc-scheduler-server | matchmaker |
|---|---|---|
| **frc-scheduler-server** | — | 0W-0L-0T |
| **matchmaker** | 0W-0L-0T | — |

## 2023mnmi — Minnesota 10,000 Lakes Regional presented by Medtronic

- 61 teams, 9 matches each, 3v3
- Expected total matches: 91
- Notes: Pulled from TBA on 2026-05-09. 61 teams, 92 qual matches.

| Metric | Threshold (good / accept) | frc-scheduler-server | matchmaker |
|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✓ 0 | ERROR |
| max_partner_repeats | ≤1 / ≤2 | ✓ 1 | ERROR |
| repeat_opponents | ≤20 / ≤27 | ✓ 20 | ERROR |
| max_opponent_repeats | ≤2 / ≤2 | ✓ 2 | ERROR |
| max_color_imbalance | ≤1 / ≤2 | ✗ 3 | ERROR |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ERROR |
| max_station_spread | ≤1 / ≤1 | ✗ 2 | ERROR |
| min_match_gap | ≥4 / ≥4 | ✗ 3 | ERROR |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ERROR |
| surrogate_count | ≤0 / ≤0 | — 3 | ERROR |
| matches_per_team | — | ✗ 9 | ERROR |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 40.30 | 50.51s | sa_iters=500,000 (good) |
| matchmaker | ERROR | — | — | ValueError: MatchMaker output has 92 matches; fixture expects 91. Parser may be missing rows or fixture parameters are wrong. First 3KB of output:
Create schedule for 61 teams playing 9 rounds in 92 matches
with a minimum match separation of 7 running 100000 iterations.

   0:00   11.88% complete (197 updates), less than a minute to go   
   0:00   23.84% complete (217 updates), less than a minute to go   
   0:00   35.84% complete (237 updates), less than a minute to go   
   0:01   47.89% complete (245 updates), less than a minute to go   
   0:01   59.88% complete (256 updates), less than a minute to go   
   0:01   71.92% complete (260 updates), less than a minute to go   
   0:01   83.97% complete (263 updates), less than a minute to go   
   0:02   96.03% complete (274 updates), less than a minute to go   
   0:02   100.00% complete (275 updates), operation complete         
Results for 61 teams playing 9 rounds in 92 matches
with a minimum match separation of 7.

Match Schedule
--------------
  1:   53    50     5    34    46     6 
  2:   60    30    61    14    11    31 
  3:    2    36    12    35     9    37 
  4:   17    43    49     8    52    48 
  5:   38    42    25    23    22    51 
  6:   10    44     7    18    15    58 
  7:   41    26    28    16    27    57 
  8:   55     4    54    21    45    19 
  9:   32    20    33    40    13    29 
 10:   24     1    56    47    39     3 
 11:   60    36    35     8    59    46 
 12:   22     5     6    49     9    38 
 13:   44    15    31    10    25    43 
 14:   37    27     2    16    61    23 
 15:   26    54    42     7    48    50 
 16:   18    40    34    19    55    13 
 17:   12    41    52    21    33     3 
 18:   28    17    51    39    29    14 
 19:    1    32    11    45    56    20 
 20:   57    24    53    59    30     4 
 21:   58    25     2    47    46    27 
 22:   36    10    16    60     5    43 
 23:   40    37    49    50    54     6 
 24:    7    12     8    33    61    13 
 25:   41    39    48    29    55    15 
 26:   17    14     9    42    45    44 
 27:   32     3    31    57    51    34 
 28:   58    23    59    28    19    20 
 29:   35     1    38     4    24    18 
 30:   11    47    22    52    53    21 
 31:    6    26    56     2    10    30 
 32:   50    60    25    55    33    12 
 33:   61    43    39     9    40    42 
 34:   34    14    32    57    54    15 
 35:   44    20    13     5    41    51 
 36:   27     7    45    48     3    59 
 37:   53    47     8    37    28    38 
 38:   29    21    58    26    24    35 
 39:   30    19    56    36    17    22 
 40:    4    52    11    16    31    18 
 41:   23    49    57    46    40     1 
 42:   13     2    60    50    44    39 
 43:    3     9     7    20    10    55 
 44:   59    41    54    12    42    47 
 45:   34    58    35    45    25    37 
 46:   61    26    17    32    38    36 
 47:   33    18    48    53    56    22 
 48:   49    29    27     4    31    19 
 49:    1     6    14    21     8    16 
 50:   15    23    30    52    28     5 
 51:   24    51    55    43    11    46 
 52:   13    35    42    58    60     3 
 |

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 2177 | 3.53 | 1 | 2 | 3 | 0 | 3 | 1 |
| 2 | 3202 | 3.27 | 1 | 2 | 3 | 0 | 1 | 3 |
| 3 | 4215 | 3.27 | 1 | 2 | 3 | 0 | 1 | 3 |
| 4 | 2509 | 3.20 | 1 | 2 | 3 | 0 | 2 | 1 |
| 5 | 2513 | 3.20 | 1 | 2 | 3 | 0 | 2 | 1 |

## 2024mndu — Lake Superior Regional

- 55 teams, 9 matches each, 3v3
- Expected total matches: 82
- Notes: Pulled from TBA on 2026-05-09. 55 teams, 83 qual matches.

| Metric | Threshold (good / accept) | frc-scheduler-server | matchmaker |
|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✓ 0 | ERROR |
| max_partner_repeats | ≤1 / ≤2 | ✓ 1 | ERROR |
| repeat_opponents | ≤20 / ≤27 | · 23 | ERROR |
| max_opponent_repeats | ≤2 / ≤2 | ✓ 2 | ERROR |
| max_color_imbalance | ≤1 / ≤2 | ✗ 3 | ERROR |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ERROR |
| max_station_spread | ≤1 / ≤1 | ✗ 3 | ERROR |
| min_match_gap | ≥4 / ≥4 | ✗ 3 | ERROR |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ERROR |
| surrogate_count | ≤0 / ≤0 | — 3 | ERROR |
| matches_per_team | — | ✗ 9 | ERROR |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 43.30 | 43.03s | sa_iters=500,000 (good) |
| matchmaker | ERROR | — | — | ValueError: MatchMaker output has 83 matches; fixture expects 82. Parser may be missing rows or fixture parameters are wrong. First 3KB of output:
Create schedule for 55 teams playing 9 rounds in 83 matches
with a minimum match separation of 6 running 100000 iterations.

   0:00   12.72% complete (200 updates), less than a minute to go   
   0:00   25.86% complete (225 updates), less than a minute to go   
   0:00   39.13% complete (235 updates), less than a minute to go   
   0:01   52.42% complete (242 updates), less than a minute to go   
   0:01   65.76% complete (248 updates), less than a minute to go   
   0:01   79.04% complete (250 updates), less than a minute to go   
   0:01   92.34% complete (254 updates), less than a minute to go   
   0:01   100.00% complete (260 updates), operation complete         
Results for 55 teams playing 9 rounds in 83 matches
with a minimum match separation of 6.

Match Schedule
--------------
  1:   50    13    55    48     4    43 
  2:   21    41    52    19    53    23 
  3:    3    49    51     8    35    14 
  4:   22    12     5    38    47    17 
  5:   44     2    18    46    30    45 
  6:   33    39    28    27    25     9 
  7:   54    11    34    32    31    26 
  8:    7    16    42    36    10    29 
  9:   15     6    40    20    37     1 
 10:   24    50    48    21    53    51 
 11:   43     8    12    30    19    41 
 12:   35     4    27    46    18    47 
 13:   14    54     3    39    34    38 
 14:   23    29    33     5    31     2 
 15:   28     6     1    13     7    22 
 16:    9    11    15    10    16    55 
 17:   26    42    49    24    17    20 
 18:   37    40    25    44    52    32 
 19:   45    21    39    36     8     4 
 20:   34    47    43    29    46    51 
 21:   14     1    19    28    31    35 
 22:   10    12    30     6    33    54 
 23:   22    38    53    26    15     2 
 24:   16    41    25    20    48     5 
 25:   24     9    18    32    45    40 
 26:   13    17    52    44    36     3 
 27:   50    37    11    27    49     7 
 28:   23    42     6    55    34    14 
 29:   15    53    33    54    43    35 
 30:   29    22    19    51    25     4 
 31:    5    26    46     1    10    45 
 32:   31    18     8    52    36    38 
 33:    9    16    37    41    12    24 
 34:   20    42    11    23    28    44 
 35:   21     3     7     2    47    55 
 36:   32    39    50    49    30    13 
 37:   40    27    46    17    48    14 
 38:   51    15    31    45     5    18 
 39:    6     9    36    43    26    25 
 40:   33    44    41     4    28    16 
 41:   35    20    12    11    29    21 
 42:   49    32    23    47     7    39 
 43:   30    38     3    37    48    42 
 44:    2    27     1     8    10    24 
 45:   53    13    54    40    55    22 
 46:   50    17    34    19    52    15 
 47:   14    43    11    25    18    21 
 48:   28    41    32     6    46    31 
 49:   48    23    47    26    33    16 
 50:    7    30    44    38    51    12 
 51:    5    36    27    54    40    49 
 52:    1    29     8    37    55    17 
 53:   35     2    13    34    52     9 
 54:   45    22    42    19  |

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 4511 | 3.50 | 1 | 2 | 3 | 0 | 3 | 3 |
| 2 | 6217 | 3.42 | 0 | 2 | 3 | 0 | 3 | 4 |
| 3 | 3267 | 3.00 | 1 | 2 | 3 | 0 | 0 | 5 |
| 4 | 5690 | 3.00 | 1 | 2 | 3 | 0 | 0 | 5 |
| 5 | 6421 | 3.00 | 1 | 2 | 3 | 0 | 3 | 1 |

## 2025mnmi — Minnesota 10,000 Lakes Regional

- 51 teams, 9 matches each, 3v3
- Expected total matches: 76
- Notes: Pulled from TBA on 2026-05-09. 51 teams, 77 qual matches.

| Metric | Threshold (good / accept) | frc-scheduler-server | matchmaker |
|---|---|---|---|
| repeat_partners | ≤0 / ≤2 | ✓ 0 | ERROR |
| max_partner_repeats | ≤1 / ≤2 | ✓ 1 | ERROR |
| repeat_opponents | ≤20 / ≤27 | ✗ 51 | ERROR |
| max_opponent_repeats | ≤2 / ≤2 | ✗ 3 | ERROR |
| max_color_imbalance | ≤1 / ≤2 | ✗ 3 | ERROR |
| teams_with_5_2_color | ≤0 / ≤0 | ✓ 0 | ERROR |
| max_station_spread | ≤1 / ≤1 | ✗ 3 | ERROR |
| min_match_gap | ≥4 / ≥4 | ✗ 3 | ERROR |
| back_to_back_matches | ≤0 / ≤0 | ✓ 0 | ERROR |
| surrogate_count | ≤0 / ≤0 | — 3 | ERROR |
| matches_per_team | — | ✗ 9 | ERROR |

**Overall + diagnostics**

| Adapter | Overall | Composite | Generation time | Notes |
|---|---|---|---|---|
| frc-scheduler-server | ✗ poor | 60.30 | 37.98s | sa_iters=500,000 (good) |
| matchmaker | ERROR | — | — | ValueError: MatchMaker output has 77 matches; fixture expects 76. Parser may be missing rows or fixture parameters are wrong. First 3KB of output:
Create schedule for 51 teams playing 9 rounds in 77 matches
with a minimum match separation of 5 running 100000 iterations.

   0:00   13.53% complete (165 updates), less than a minute to go   
   0:00   27.71% complete (189 updates), less than a minute to go   
   0:00   42.03% complete (203 updates), less than a minute to go   
   0:01   56.44% complete (213 updates), less than a minute to go   
   0:01   70.93% complete (219 updates), less than a minute to go   
   0:01   85.43% complete (221 updates), less than a minute to go   
   0:01   100.00% complete (223 updates), operation complete         
Results for 51 teams playing 9 rounds in 77 matches
with a minimum match separation of 5.

Match Schedule
--------------
  1:   30    12    37     3     4    35 
  2:   38     6     7    16    14    45 
  3:    5    22    19    31    47    18 
  4:    9    36     8    27    48    13 
  5:   24     2    33    28    39    17 
  6:   43    49    29    20    26    23 
  7:   42    46    44    11    34    32 
  8:    1    10    50    40    25    21 
  9:   15     3    41    51     6     4 
 10:    7    37    28    31    39    19 
 11:   17    18    13    23    45    43 
 12:   30    20    34    38    11    16 
 13:   47    21    35    25     8    27 
 14:   32    42    22    41    33     9 
 15:   36    10    15    12     2    29 
 16:   14     1     5    44    26    48 
 17:   51    24    46    50    40    49 
 18:   21    45    18    47     3    20 
 19:   23    22    11    37    19     6 
 20:   36    25    41    30    28    16 
 21:   43    32    48     7    10     2 
 22:   26    38    17    46    12    50 
 23:   33    13    31    24     1    40 
 24:   39     9    27    49    44    51 
 25:   42    35    14    29     5     4 
 26:   34     8    45    15    28    32 
 27:    6    25    48    46    18    37 
 28:   21    41    38    17    31    36 
 29:   12    44    22    49    13    30 
 30:    5    23    33    11    50    20 
 31:   26    47     2     4     7    24 
 32:   51     3    39     8    14    10 
 33:   29    16    40    42    27    19 
 34:    1    15    34    35    43     9 
 35:   22    37    25    36    44    13 
 36:    6    20    24    32     7    12 
 37:   14    46    30    45     5    10 
 38:   28    47    50     3    29    42 
 39:    8    51     2    18    49     1 
 40:   16    21    33     9    15    26 
 41:   11    19     4    34    17    43 
 42:   40    48    41    35    39    38 
 43:   31    27    30    23    32    46 
 44:   50    36    29     1    45     7 
 45:   20     9    14     2    28    25 
 46:   33    17    49     6     5     3 
 47:   19    18    10    41    35    44 
 48:   26    40     8    37    23    34 
 49:   48     4    16    39    22    47 
 50:   27    38    24    15    43    42 
 51:   13    11    12    21    31    51 
 52:   25    30     7    19     9    17 
 53:   44    50     3    35     2    23 
 54:   10    40    28    22     6    26 
 55:   18     4    38    32    27     1 
 56:   13    29 |

**Most-affected teams in frc-scheduler-server's best schedule**

| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |
|---|---|---|---|---|---|---|---|---|
| 1 | 7594 | 4.17 | 3 | 2 | 3 | 0 | 2 | 5 |
| 2 | 2667 | 3.50 | 1 | 2 | 3 | 0 | 2 | 5 |
| 3 | 3630 | 3.50 | 1 | 2 | 3 | 0 | 2 | 5 |
| 4 | 6045 | 3.50 | 1 | 2 | 3 | 0 | 2 | 5 |
| 5 | 4687 | 3.43 | 1 | 3 | 3 | 0 | 2 | 3 |

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
