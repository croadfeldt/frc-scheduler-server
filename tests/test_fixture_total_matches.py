# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for scripts/scheduler_eval/harness_types.py:Fixture.total_matches.

Regression guard for the 2026-05-13 off-by-one bug:

Previously `total_matches` used floor division (`//`), which is correct
when team-slots divide evenly into matches (e.g., 36×7 = 252 slots / 6 =
42 matches, even). But for fixtures where N×MPT doesn't divide evenly,
the floor undercounted by one — the extra match needed to absorb the
remainder via surrogate slot-fills was missing.

This bug manifested as a misdiagnosed "MatchMaker exited 255" error
on three MN regional fixtures (2023mnmi 61t, 2024mndu 55t, 2025mnmi
51t). The actual chain: MatchMaker exited cleanly with the correct
number of matches; the matchmaker adapter's parser threw a ValueError
because the count didn't equal `fixture.total_matches`; the adapter
wrapped that in a RuntimeError; and earlier sessions misattributed
the failure to MatchMaker itself.

This test pins the correct behavior so the floor-division bug can't
return.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.scheduler_eval.harness_types import Fixture  # noqa: E402


_failures = 0


def check(name, cond, detail=""):
    global _failures
    if cond:
        print(f"  ✓ {name}")
    else:
        _failures += 1
        print(f"  ✗ {name}: {detail}")


def fx(n, mpt, tpa=3):
    return Fixture(
        fixture_id=f"test_{n}x{mpt}",
        name=f"test {n}×{mpt}",
        teams=list(range(1, n + 1)),
        matches_per_team=mpt,
        teams_per_alliance=tpa,
    )


print("Fixture.total_matches: even-division shapes (no surrogates)")
# These shapes have N×MPT divisible by 2×TPA. Floor == ceil, so the
# pre-bugfix value already matched the post-bugfix value. Pin them so
# we don't regress in the other direction (e.g., off-by-one over-count).
for n, mpt, expected in [
    (12, 6, 12),   # 72 / 6 = 12
    (36, 7, 42),   # 252 / 6 = 42
    (24, 8, 32),   # 192 / 6 = 32
    (60, 12, 120), # 720 / 6 = 120
    (20, 6, 20),   # 120 / 6 = 20
    (18, 6, 18),   # 108 / 6 = 18
]:
    f = fx(n, mpt)
    check(f"{n}×{mpt}: total_matches = {expected}",
          f.total_matches == expected,
          f"got {f.total_matches}")
    check(f"{n}×{mpt}: needs_surrogate = False",
          f.needs_surrogate is False,
          f"got {f.needs_surrogate}")


print()
print("Fixture.total_matches: surrogate-required shapes (off-by-one fix)")
# These shapes have N×MPT NOT divisible by 2×TPA. The total must be
# rounded UP to absorb the remainder via surrogate slot-fills in the
# final round(s). Pre-fix these were all off by one; this test pins
# the correct (ceil) values.
for n, mpt, expected in [
    # The three MN regional fixtures that originally surfaced the bug
    (51, 9, 77),   # 459 / 6 = 76.5 → 77
    (55, 9, 83),   # 495 / 6 = 82.5 → 83
    (61, 9, 92),   # 549 / 6 = 91.5 → 92
    # Other surrogate-required shapes we hit in the construction-malformation
    # investigation, at the more typical MN-regional MPT=7
    (51, 7, 60),   # 357 / 6 = 59.5 → 60
    (55, 7, 65),   # 385 / 6 = 64.17 → 65
    (61, 7, 72),   # 427 / 6 = 71.17 → 72
    # MPT=8 variants
    (55, 8, 74),   # 440 / 6 = 73.33 → 74
    (61, 8, 82),   # 488 / 6 = 81.33 → 82
]:
    f = fx(n, mpt)
    check(f"{n}×{mpt}: total_matches = {expected}",
          f.total_matches == expected,
          f"got {f.total_matches} (pre-fix bug would give {expected - 1})")
    check(f"{n}×{mpt}: needs_surrogate = True",
          f.needs_surrogate is True,
          f"got {f.needs_surrogate}")


print()
print("Invariant: total_matches × (2 × tpa) >= num_teams × mpt for all shapes")
# This is the structural property the fix restores. Without it, the
# schedule can't possibly contain every team's required appearances.
for n, mpt, tpa in [
    (12, 6, 3), (36, 7, 3), (51, 9, 3), (55, 9, 3), (61, 9, 3),
    (51, 7, 3), (55, 8, 3), (61, 8, 3),
]:
    f = fx(n, mpt, tpa)
    slots_available = f.total_matches * (2 * tpa)
    slots_needed = n * mpt
    check(f"{n}×{mpt} (tpa={tpa}): slots_available ({slots_available}) ≥ slots_needed ({slots_needed})",
          slots_available >= slots_needed,
          f"shortfall = {slots_needed - slots_available}")


print()
if _failures > 0:
    print(f"{_failures} failure(s).")
    sys.exit(1)
print("All Fixture.total_matches tests passed.")
