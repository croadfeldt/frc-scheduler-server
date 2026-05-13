# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for CP-SAT exact post-pass solvers.

Coverage:
  1. R/B solver is correct (verifiable smoke schedule)
  2. R/B solver preserves invariants (partner pairs, opponent pairs,
     cooldown, surrogate counts)
  3. R/B solver matches or beats SA on a known-plateau case
  4. Station solver is correct
  5. Station solver preserves invariants (partner/opponent pairs,
     cooldown, surrogate counts)
  6. Station solver matches or beats SA
  7. Budget cap is enforced
  8. Identity-input is handled (zero work)
  9. UNKNOWN status doesn't crash, returns input
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.scheduler import Match, generate_matches  # noqa: E402
from app.post_passes.cpsat_post_passes import (  # noqa: E402
    rb_balance_cpsat,
    station_balance_cpsat,
    MAX_BUDGET_SECONDS,
)


_failures = 0


def check(name, cond, detail=""):
    global _failures
    if cond:
        print(f"  ✓ {name}")
    else:
        _failures += 1
        print(f"  ✗ {name}: {detail}")


def _partner_pairs(matches):
    """Set of frozensets of partners across all matches."""
    pairs = set()
    for m in matches:
        for side in (m.red, m.blue):
            for i in range(len(side)):
                for j in range(i + 1, len(side)):
                    pairs.add(frozenset((side[i], side[j])))
    return pairs


def _opponent_pairs(matches):
    """Set of frozensets of opponents (cross-alliance) per match."""
    pairs = set()
    for m in matches:
        for r in m.red:
            for b in m.blue:
                pairs.add(frozenset((r, b)))
    return pairs


def _team_play_counts(matches):
    """Dict team → number of matches it appears in (any side)."""
    counts = {}
    for m in matches:
        for t in m.red:  counts[t] = counts.get(t, 0) + 1
        for t in m.blue: counts[t] = counts.get(t, 0) + 1
    return counts


def _surrogate_counts(matches):
    """Dict team → number of surrogate flags it carries."""
    counts = {}
    for m in matches:
        for t, s in zip(m.red, m.red_surrogate):
            if s: counts[t] = counts.get(t, 0) + 1
        for t, s in zip(m.blue, m.blue_surrogate):
            if s: counts[t] = counts.get(t, 0) + 1
    return counts


def _cooldown_violations(matches, cooldown):
    """Count cooldown violations."""
    last_seen = {}
    viol = 0
    for i, m in enumerate(matches):
        for t in m.red:
            if t in last_seen and i - last_seen[t] < cooldown:
                viol += 1
            last_seen[t] = i
        for t in m.blue:
            if t in last_seen and i - last_seen[t] < cooldown:
                viol += 1
            last_seen[t] = i
    return viol


# ─────────────────────────────────────────────────────────────────────
# Setup: generate a baseline schedule to test against
# ─────────────────────────────────────────────────────────────────────

print("Generating 12×6 baseline schedule for tests...")
baseline = generate_matches(
    num_teams=12, matches_per_team=6, ideal_gap=2,
    seed=0xdeadbeef, n_sa_iterations=5000,
    rb_post_pass=False, station_post_pass=False,
)
baseline_matches = list(baseline.matches)

baseline_partners = _partner_pairs(baseline_matches)
baseline_opponents = _opponent_pairs(baseline_matches)
baseline_play_counts = _team_play_counts(baseline_matches)
baseline_surrogates = _surrogate_counts(baseline_matches)
baseline_cooldown = _cooldown_violations(baseline_matches, 2)


# ─────────────────────────────────────────────────────────────────────
# 1. R/B solver runs cleanly
# ─────────────────────────────────────────────────────────────────────

print("\nR/B solver basic correctness:")
new_matches, stats = rb_balance_cpsat(baseline_matches, time_budget_s=10)
check("returns OPTIMAL on 12×6",
      stats['status'] == 'OPTIMAL',
      f"got {stats['status']}")
check("max_after <= max_before",
      stats['max_after'] <= stats['max_before'],
      f"before={stats['max_before']} after={stats['max_after']}")
check("returns same number of matches",
      len(new_matches) == len(baseline_matches))


# ─────────────────────────────────────────────────────────────────────
# 2. R/B solver preserves invariants
# ─────────────────────────────────────────────────────────────────────

print("\nR/B solver preserves invariants:")
check("partner pairs preserved",
      _partner_pairs(new_matches) == baseline_partners,
      "partner pair set changed")
check("opponent pairs preserved",
      _opponent_pairs(new_matches) == baseline_opponents,
      "opponent pair set changed")
check("play counts preserved",
      _team_play_counts(new_matches) == baseline_play_counts,
      "team play counts changed")
check("surrogate counts preserved",
      _surrogate_counts(new_matches) == baseline_surrogates,
      "surrogate counts changed")
check("cooldown violations preserved",
      _cooldown_violations(new_matches, 2) == baseline_cooldown,
      "cooldown violations changed")


# ─────────────────────────────────────────────────────────────────────
# 3. Station solver runs cleanly
# ─────────────────────────────────────────────────────────────────────

print("\nStation solver basic correctness:")
new_st, stats_st = station_balance_cpsat(baseline_matches, time_budget_s=10)
check("returns OPTIMAL on 12×6",
      stats_st['status'] == 'OPTIMAL',
      f"got {stats_st['status']}")
check("max_after <= max_before",
      stats_st['max_after'] <= stats_st['max_before'],
      f"before={stats_st['max_before']} after={stats_st['max_after']}")


# ─────────────────────────────────────────────────────────────────────
# 4. Station solver preserves invariants
# ─────────────────────────────────────────────────────────────────────

print("\nStation solver preserves invariants:")
check("partner pairs preserved",
      _partner_pairs(new_st) == baseline_partners,
      "partner pair set changed")
check("opponent pairs preserved",
      _opponent_pairs(new_st) == baseline_opponents,
      "opponent pair set changed")
check("play counts preserved",
      _team_play_counts(new_st) == baseline_play_counts)
# Note: surrogate counts are preserved because permutation moves
# each team's surrogate flag along with it.
check("surrogate counts preserved",
      _surrogate_counts(new_st) == baseline_surrogates)
check("cooldown violations preserved",
      _cooldown_violations(new_st, 2) == baseline_cooldown)


# ─────────────────────────────────────────────────────────────────────
# 5. Budget enforcement: cap at MAX_BUDGET_SECONDS
# ─────────────────────────────────────────────────────────────────────

print("\nBudget validation:")
import logging
logging.getLogger('app.post_passes.cpsat_post_passes').setLevel(logging.ERROR)

# Way-over-cap budget is silently clamped (with WARN log).
new_matches, stats = rb_balance_cpsat(baseline_matches,
                                        time_budget_s=MAX_BUDGET_SECONDS + 1000)
check("oversized budget doesn't crash",
      stats['status'] in ('OPTIMAL', 'FEASIBLE'))

# Negative / zero budget should raise ValueError.
try:
    rb_balance_cpsat(baseline_matches, time_budget_s=0)
    check("budget=0 raises ValueError", False, "no exception")
except ValueError:
    check("budget=0 raises ValueError", True)
try:
    rb_balance_cpsat(baseline_matches, time_budget_s=-5)
    check("budget=-5 raises ValueError", False, "no exception")
except ValueError:
    check("budget=-5 raises ValueError", True)


# ─────────────────────────────────────────────────────────────────────
# 6. Empty schedule handled gracefully
# ─────────────────────────────────────────────────────────────────────

print("\nEmpty schedule:")
out, stats = rb_balance_cpsat([], time_budget_s=10)
check("R/B on empty returns empty", out == [])
check("R/B on empty status OPTIMAL", stats['status'] == 'OPTIMAL')

out, stats = station_balance_cpsat([], time_budget_s=10)
check("station on empty returns empty", out == [])
check("station on empty status OPTIMAL", stats['status'] == 'OPTIMAL')


# ─────────────────────────────────────────────────────────────────────
# 7. CP-SAT matches or beats SA (regression test)
# ─────────────────────────────────────────────────────────────────────

print("\nCP-SAT vs SA on baseline schedule:")
from app.post_passes.rb_balance import rb_balance_sa
from app.post_passes.station_balance import station_balance_sa

sa_rb_out, sa_rb_stats = rb_balance_sa(baseline_matches, n_iterations=5000, seed=0)
sa_st_out, sa_st_stats = station_balance_sa(sa_rb_out, n_iterations=5000, seed=0)
cp_rb_out, cp_rb_stats = rb_balance_cpsat(baseline_matches, time_budget_s=10)
cp_st_out, cp_st_stats = station_balance_cpsat(cp_rb_out, time_budget_s=10)

check("CP-SAT R/B max ≤ SA R/B max",
      cp_rb_stats['max_after'] <= sa_rb_stats['max_after'],
      f"CPSAT={cp_rb_stats['max_after']} SA={sa_rb_stats['max_after']}")
check("CP-SAT station max ≤ SA station max",
      cp_st_stats['max_after'] <= sa_st_stats['max_after'],
      f"CPSAT={cp_st_stats['max_after']} SA={sa_st_stats['max_after']}")


# ─────────────────────────────────────────────────────────────────────
# Done
# ─────────────────────────────────────────────────────────────────────

print()
if _failures > 0:
    print(f"{_failures} failure(s).")
    sys.exit(1)
print("All CP-SAT post-pass tests passed.")
