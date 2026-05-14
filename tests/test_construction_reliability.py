# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for construction-phase malformation on tight + odd-team-count fixtures.

The construction phase can paint itself into a corner — running out of
under-quota teams to fill the last match. This file pins the empirically-
measured malformation rates so we can detect regressions.

Background (2026-05-13 investigation):

  The original docstring on ConstructionMalformedError claimed only
  "n<16" fixtures malformed. Smoke-testing revealed 20-30% malformation
  on 51/55/61-team fixtures at MPT=7 (i.e., real MSHSL/regional
  events). Root cause: the FIRST surrogate model pre-picked surrogate
  teams with target_count = MPT+1, but team_score used raw mc[t]
  without normalizing for target. Surrogate teams' mc reached MPT+1
  faster than regular teams reached MPT (proportionally), exiting
  under_quota early and leaving fewer than 6 teams in the pool for
  the last match.

Fix (this file's reason for existing):

  1. team_score normalizes by target_count[t] so surrogate teams
     advance at the same proportional rate as regular teams. When
     target == MPT (no surrogate), keeps a fast path that's
     bit-identical to the legacy code.
  2. FIRST surrogate phase 2 falls back to at-quota teams when
     under_quota < 6. Strictly preferred over a malformed match
     (which the malformed-check at end of construction would raise).
     Strictly preserves FIRST §10.5.2 placement on the common case;
     only deviates in the rare emergency.

Measured rates (this file pins them):

  Pre-fix:
    51×7 cd=2: ~20% malformed
    55×7 cd=2: ~23% malformed
    55×8 cd=2: ~37% malformed
    61×7 cd=2: ~30% malformed
    61×8 cd=2: ~20% malformed

  Post-fix:
    51×7 cd=2: 0% malformed
    55×7 cd=2: 0% malformed
    55×8 cd=2: 0% malformed
    61×7 cd=2: 0% malformed
    61×8 cd=2: 0% malformed

  These rates ARE the regression guard. If the test runs a 30-seed
  sample and finds any malformation, the fix has regressed.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.scheduler import generate_matches, ConstructionMalformedError  # noqa: E402


_failures = 0


def check(name, cond, detail=""):
    global _failures
    if cond:
        print(f"  ✓ {name}")
    else:
        _failures += 1
        print(f"  ✗ {name}: {detail}")


# Real-world fixture shapes (MN regionals, state events). These
# previously had 20-30%+ malformation rates pre-fix; post-fix
# they should all be at 0/30.
PROBLEM_FIXTURES = [
    # (n, mpt, cd, label)
    (51, 7, 2, "51×7 MSHSL-style"),
    (55, 7, 2, "55×7 MSHSL-style"),
    (55, 8, 2, "55×8"),
    (61, 7, 2, "61×7 MSHSL-style"),
    (61, 8, 2, "61×8"),
    (36, 7, 2, "36×7 MN state-event default"),
]

N_SEEDS_PER_FIXTURE = 30  # matches docstring methodology


print("Construction reliability on tight + odd-team-count fixtures:")
print(f"  ({N_SEEDS_PER_FIXTURE} seeds per fixture; pre-fix some were 20-37%)")

for n, mpt, cd, label in PROBLEM_FIXTURES:
    malformed_count = 0
    other_failure_count = 0
    for seed in range(N_SEEDS_PER_FIXTURE):
        try:
            generate_matches(
                num_teams=n, matches_per_team=mpt, ideal_gap=cd,
                seed=seed, n_sa_iterations=0,
            )
        except ConstructionMalformedError:
            malformed_count += 1
        except Exception:
            other_failure_count += 1
    check(
        f"{label} ({n}×{mpt} cd={cd}): no malformed matches "
        f"({malformed_count}/{N_SEEDS_PER_FIXTURE})",
        malformed_count == 0,
        f"got {malformed_count} malformed; fix has regressed",
    )
    check(
        f"{label}: no unexpected exceptions "
        f"({other_failure_count}/{N_SEEDS_PER_FIXTURE})",
        other_failure_count == 0,
        f"got {other_failure_count} unexpected exceptions",
    )


# Sanity: surrogate count is correctly produced for these shapes
print()
print("Surrogate model honors target_count for fixed seeds:")
for n, mpt, cd, label in [(51, 7, 2, "51×7"), (55, 7, 2, "55×7"), (61, 7, 2, "61×7")]:
    result = generate_matches(
        num_teams=n, matches_per_team=mpt, ideal_gap=cd,
        seed=0xDEAD, n_sa_iterations=0,
    )
    # Count appearances per team
    counts: dict[int, int] = {}
    for m in result.matches:
        for t in m.red:  counts[t] = counts.get(t, 0) + 1
        for t in m.blue: counts[t] = counts.get(t, 0) + 1
    # Total appearances should be 6 × num_matches
    num_matches = len(result.matches)
    total_appearances = sum(counts.values())
    expected = num_matches * 6
    check(
        f"{label}: total appearances = matches × 6 ({total_appearances} == {expected})",
        total_appearances == expected,
        f"got {total_appearances}, expected {expected}",
    )
    # Per-team appearance count should be either MPT or MPT+1
    invalid_counts = {t: c for t, c in counts.items()
                     if c != mpt and c != mpt + 1}
    check(
        f"{label}: all teams have mpt or mpt+1 appearances",
        len(invalid_counts) == 0,
        f"got {len(invalid_counts)} teams with off-target counts: {dict(list(invalid_counts.items())[:3])}",
    )


print()
if _failures > 0:
    print(f"{_failures} failure(s).")
    sys.exit(1)
print("All construction-reliability tests passed.")
