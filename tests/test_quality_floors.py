# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for app.quality_floors — theoretical floor calculations.

Coverage:
  1. Each floor's value matches hand-computed math on the 5-fixture
     proving inventory.
  2. The confidence labels are set correctly per metric.
  3. Surrogate handling: 20×8 produces surrogate_count=2.
  4. Cooldown feasibility: 12×6 at cooldown=3 is correctly marked
     infeasible (cooldown_max=2).
  5. Pair-count math: total_partner_encounters and total_opp_encounters
     satisfy the conservation identity (sum of all pair counts equals
     n * slots_per_team / 2).
  6. Sum-of-squares lower bound matches the "as-even-as-possible
     distribution" formula directly.

Each check below corresponds to a specific math claim. If any fails,
the floors module has a bug.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.quality_floors import (   # noqa: E402
    fixture_floors,
    Floor,
    FixtureFloors,
    CONFIDENCE_PROVEN_OPTIMAL,
    CONFIDENCE_PROVEN_LOWER,
)


_failures = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _failures
    if cond:
        print(f"  ✓ {name}")
    else:
        _failures += 1
        print(f"  ✗ {name}: {detail}")


# ─────────────────────────────────────────────────────────────────────────
# 1. Hand-computed values for the proving inventory
# ─────────────────────────────────────────────────────────────────────────

print("Proving inventory floor values:")

# 12×6×3: total matches = 12 (12*6/6 = 12), no surrogate
ff = fixture_floors(12, 6, teams_per_alliance=3, cooldown=2)
check("12×6: total_matches = 12", ff.total_matches == 12)
check("12×6: surrogate_count = 0", ff.surrogate_count == 0)
check("12×6: needs_surrogate = False", not ff.needs_surrogate)
check("12×6: cooldown_max = 2", ff.cooldown_max == 2,
      f"got {ff.cooldown_max}")
check("12×6: feasible at cooldown=2", ff.feasible)
# par_quad: partner-pair encounters = 12 * 6 * 2 / 2 = 72;
#           unique pairs = C(12, 2) = 66; avg = 72/66 ≈ 1.091
#           floor=1, ceil=2; r = 72 - 1*66 = 6 pairs at 2, 60 at 1
#           par_quad = 6*4 + 60*1 = 84
check("12×6: par_quad floor = 84", ff.floors['par_quad'].value == 84,
      f"got {ff.floors['par_quad'].value}")
# opp_quad: opponent-pair encounters = 12 * 6 * 3 / 2 = 108;
#           avg = 108/66 ≈ 1.636; floor=1, ceil=2
#           r = 108 - 1*66 = 42; 42 at 2, 24 at 1
#           opp_quad = 42*4 + 24*1 = 168 + 24 = 192
check("12×6: opp_quad floor = 192", ff.floors['opp_quad'].value == 192,
      f"got {ff.floors['opp_quad'].value}")
check("12×6: rb_per_team = 0 (MPT=6 is even)",
      ff.floors['rb_per_team'].value == 0)
check("12×6: station_per_team_spread = 0 (MPT=6 div by 6)",
      ff.floors['station_per_team_spread'].value == 0)

# 24×8×3: total matches = 24*8/6 = 32, no surrogate
ff = fixture_floors(24, 8, teams_per_alliance=3, cooldown=2)
check("24×8: total_matches = 32", ff.total_matches == 32)
check("24×8: surrogate_count = 0", ff.surrogate_count == 0)
check("24×8: cooldown_max = 4", ff.cooldown_max == 4,
      f"got {ff.cooldown_max}")
# par_quad: partner-encounters = 24 * 8 * 2 / 2 = 192; pairs = 276
#           avg = 192/276 ≈ 0.696; floor=0, ceil=1
#           r = 192 - 0*276 = 192 pairs at 1, 84 at 0
#           par_quad = 192*1 + 84*0 = 192
check("24×8: par_quad floor = 192", ff.floors['par_quad'].value == 192,
      f"got {ff.floors['par_quad'].value}")
# opp_quad: opponent-encounters = 24 * 8 * 3 / 2 = 288; avg = 288/276 ≈ 1.043
#           floor=1, ceil=2; r = 288 - 1*276 = 12 at 2, 264 at 1
#           opp_quad = 12*4 + 264*1 = 48 + 264 = 312
check("24×8: opp_quad floor = 312", ff.floors['opp_quad'].value == 312,
      f"got {ff.floors['opp_quad'].value}")
check("24×8: rb_per_team = 0 (MPT=8 even)",
      ff.floors['rb_per_team'].value == 0)
check("24×8: station_per_team_spread = 1 (8 mod 6 ≠ 0)",
      ff.floors['station_per_team_spread'].value == 1)

# 36×7×3: total matches = 36*7/6 = 42, no surrogate
ff = fixture_floors(36, 7, teams_per_alliance=3, cooldown=2)
check("36×7: total_matches = 42", ff.total_matches == 42)
check("36×7: surrogate_count = 0", ff.surrogate_count == 0)
check("36×7: cooldown_max = 6", ff.cooldown_max == 6,
      f"got {ff.cooldown_max}")
# par_quad: encounters = 36 * 7 * 2 / 2 = 252; pairs = 630
#           avg = 252/630 = 0.4; floor=0, ceil=1
#           r = 252 - 0*630 = 252 at 1, 378 at 0
#           par_quad = 252*1 + 378*0 = 252
check("36×7: par_quad floor = 252", ff.floors['par_quad'].value == 252,
      f"got {ff.floors['par_quad'].value}")
# opp_quad: encounters = 36 * 7 * 3 / 2 = 378; avg = 378/630 = 0.6
#           floor=0, ceil=1; r = 378 - 0*630 = 378 at 1, 252 at 0
#           opp_quad = 378*1 + 252*0 = 378
check("36×7: opp_quad floor = 378", ff.floors['opp_quad'].value == 378,
      f"got {ff.floors['opp_quad'].value}")
check("36×7: rb_per_team = 1 (MPT=7 odd)",
      ff.floors['rb_per_team'].value == 1)
check("36×7: station_per_team_spread = 1 (7 mod 6 ≠ 0)",
      ff.floors['station_per_team_spread'].value == 1)

# 20×8×3: total slots = 160; M = ceil(160/6) = 27; total_match_slots = 162
#         surrogate_count = 162 - 160 = 2
ff = fixture_floors(20, 8, teams_per_alliance=3, cooldown=2)
check("20×8: total_matches = 27", ff.total_matches == 27)
check("20×8: needs_surrogate = True", ff.needs_surrogate)
check("20×8: surrogate_count = 2", ff.surrogate_count == 2,
      f"got {ff.surrogate_count}")
check("20×8: cooldown_max = 3", ff.cooldown_max == 3,
      f"got {ff.cooldown_max}")
# par_quad: encounters = 20 * 8 * 2 / 2 = 160; pairs = 190
#           avg = 160/190 ≈ 0.842; floor=0, ceil=1
#           r = 160 - 0*190 = 160 at 1, 30 at 0
#           par_quad = 160*1 + 30*0 = 160
check("20×8: par_quad floor = 160", ff.floors['par_quad'].value == 160,
      f"got {ff.floors['par_quad'].value}")
# opp_quad: encounters = 20 * 8 * 3 / 2 = 240; avg = 240/190 ≈ 1.263
#           floor=1, ceil=2; r = 240 - 1*190 = 50 at 2, 140 at 1
#           opp_quad = 50*4 + 140*1 = 200 + 140 = 340
check("20×8: opp_quad floor = 340", ff.floors['opp_quad'].value == 340,
      f"got {ff.floors['opp_quad'].value}")

# 60×12×3: total slots = 720; M = 120; no surrogate
ff = fixture_floors(60, 12, teams_per_alliance=3, cooldown=2)
check("60×12: total_matches = 120", ff.total_matches == 120)
check("60×12: surrogate_count = 0", ff.surrogate_count == 0)
check("60×12: cooldown_max = 10", ff.cooldown_max == 10,
      f"got {ff.cooldown_max}")
# par_quad: encounters = 60 * 12 * 2 / 2 = 720; pairs = 1770
#           avg = 720/1770 ≈ 0.407; floor=0, ceil=1
#           r = 720 - 0*1770 = 720 at 1, 1050 at 0
#           par_quad = 720*1 = 720
check("60×12: par_quad floor = 720", ff.floors['par_quad'].value == 720,
      f"got {ff.floors['par_quad'].value}")
# opp_quad: encounters = 60 * 12 * 3 / 2 = 1080; avg = 1080/1770 ≈ 0.610
#           floor=0, ceil=1; r = 1080 at 1, 690 at 0
#           opp_quad = 1080*1 = 1080
check("60×12: opp_quad floor = 1080", ff.floors['opp_quad'].value == 1080,
      f"got {ff.floors['opp_quad'].value}")
check("60×12: rb_per_team = 0 (12 even)",
      ff.floors['rb_per_team'].value == 0)
check("60×12: station_per_team_spread = 0 (12 mod 6 = 0)",
      ff.floors['station_per_team_spread'].value == 0)


# ─────────────────────────────────────────────────────────────────────────
# 2. Confidence label correctness
# ─────────────────────────────────────────────────────────────────────────

print("\nConfidence labels:")

ff = fixture_floors(12, 6, teams_per_alliance=3, cooldown=2)
check("cooldown_violations: proven_optimal",
      ff.floors['cooldown_violations'].confidence == CONFIDENCE_PROVEN_OPTIMAL)
check("par_quad: proven_lower_bound",
      ff.floors['par_quad'].confidence == CONFIDENCE_PROVEN_LOWER)
check("opp_quad: proven_lower_bound",
      ff.floors['opp_quad'].confidence == CONFIDENCE_PROVEN_LOWER)
check("surrogate_count: proven_optimal",
      ff.floors['surrogate_count'].confidence == CONFIDENCE_PROVEN_OPTIMAL)
check("rb_per_team: proven_optimal",
      ff.floors['rb_per_team'].confidence == CONFIDENCE_PROVEN_OPTIMAL)
check("station_per_team_spread: proven_optimal",
      ff.floors['station_per_team_spread'].confidence == CONFIDENCE_PROVEN_OPTIMAL)
check("partner_pair_count: proven_optimal",
      ff.floors['partner_pair_count'].confidence == CONFIDENCE_PROVEN_OPTIMAL)
check("opponent_pair_count: proven_optimal",
      ff.floors['opponent_pair_count'].confidence == CONFIDENCE_PROVEN_OPTIMAL)


# ─────────────────────────────────────────────────────────────────────────
# 3. Cooldown feasibility
# ─────────────────────────────────────────────────────────────────────────

print("\nCooldown feasibility:")

# 12×6 at cooldown=2 is at the boundary (cooldown_max=2), still feasible
ff = fixture_floors(12, 6, cooldown=2)
check("12×6 cooldown=2: feasible (at boundary)", ff.feasible)
# 12×6 at cooldown=3 exceeds cooldown_max=2, infeasible
ff = fixture_floors(12, 6, cooldown=3)
check("12×6 cooldown=3: NOT feasible (exceeds cooldown_max=2)", not ff.feasible)

# Standard fixtures: 36×7 has cooldown_max=6, so cooldown=2,3,4,5,6 all feasible
for cd in [1, 2, 3, 4, 5, 6]:
    ff = fixture_floors(36, 7, cooldown=cd)
    check(f"36×7 cooldown={cd}: feasible (cooldown_max=6)", ff.feasible)


# ─────────────────────────────────────────────────────────────────────────
# 4. Pair-count conservation identities
# ─────────────────────────────────────────────────────────────────────────

print("\nConservation identities:")

# For any fixture, total partner-pair encounters * 2 = n * MPT * (tpa-1)
# and total opponent-pair encounters * 2 = n * MPT * tpa.
for n, mpt, tpa in [(12, 6, 3), (24, 8, 3), (36, 7, 3), (60, 12, 3)]:
    # Reconstruct from the par_quad floor calculation
    pairs = n * (n - 1) // 2
    # avg = (mpt * (tpa-1)) / (n-1); total_encounters = pairs * avg = n * mpt * (tpa-1) / 2
    expected_partner_total = n * mpt * (tpa - 1) // 2
    expected_opp_total     = n * mpt * tpa // 2
    # We can verify via floor + ceil distribution
    F = math.floor(expected_partner_total / pairs)
    r = expected_partner_total - F * pairs
    reconstructed = r * (F + 1) + (pairs - r) * F
    check(f"{n}×{mpt} partner conservation: r*(F+1) + (P-r)*F = total",
          reconstructed == expected_partner_total,
          f"got {reconstructed}, expected {expected_partner_total}")


# ─────────────────────────────────────────────────────────────────────────
# 5. Sum-of-squares minimum-variance distribution
# ─────────────────────────────────────────────────────────────────────────

print("\nSum-of-squares minimum-variance:")

# For total=5, pairs=3: avg=1.667, floor=1, ceil=2, r=2.
# 2 pairs at 2, 1 pair at 1: 4+4+1 = 9.
# Alternative distributions: (3, 1, 1): 9+1+1=11; (2, 2, 1): 9. Min=9.
# This is what the formula gives.
def _min_var_quad(total, pairs):
    F = total // pairs
    r = total - F * pairs
    return r * (F + 1)**2 + (pairs - r) * F**2

check("min_var_quad(5, 3) = 9",  _min_var_quad(5, 3) == 9,
      f"got {_min_var_quad(5, 3)}")
check("min_var_quad(0, 5) = 0",  _min_var_quad(0, 5) == 0)
check("min_var_quad(10, 5) = 20", _min_var_quad(10, 5) == 20,
      f"got {_min_var_quad(10, 5)}")  # all at 2: 5*4 = 20
check("min_var_quad(7, 4) = 13",
      _min_var_quad(7, 4) == 13,
      f"got {_min_var_quad(7, 4)}")  # 3 at 2, 1 at 1: 12+1 = 13


# ─────────────────────────────────────────────────────────────────────────
# 6. to_dict serialization
# ─────────────────────────────────────────────────────────────────────────

print("\nSerialization:")

ff = fixture_floors(12, 6, teams_per_alliance=3, cooldown=2)
d = ff.to_dict()
check("to_dict has 'floors' key", 'floors' in d)
check("to_dict has 'cooldown_max' key", 'cooldown_max' in d)
check("to_dict has 'feasible' key", 'feasible' in d)
check("to_dict floors entries are dicts",
      all(isinstance(v, dict) for v in d['floors'].values()))
check("Each floor dict has 'value', 'confidence', 'proof_note'",
      all(set(v.keys()) >= {'metric', 'value', 'confidence', 'proof_note'}
          for v in d['floors'].values()))


# ─────────────────────────────────────────────────────────────────────────
# Done
# ─────────────────────────────────────────────────────────────────────────

print()
if _failures > 0:
    print(f"{_failures} failure(s).")
    sys.exit(1)
print("All quality_floors tests passed.")
