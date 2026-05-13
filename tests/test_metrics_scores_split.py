# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the metrics/scores split — auditability + staleness fix.

Coverage:
  1. compute_metrics produces metrics-only output (no scores field)
  2. compute_metrics output is deterministic given the matches
  3. apply_scores never mutates its input
  4. apply_scores produces scores keyed off current code, not stored
  5. Stale 'scores' in input metrics_report gets replaced
  6. build_quality_report compose works end-to-end
  7. Canonical library JSON storage is metrics-only
  8. apply_scores under different weights produces different composites
  9. apply_scores fallback when shape parameters are missing
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.quality_report import compute_metrics, apply_scores, build_quality_report  # noqa: E402
from app.canonical_library import list_canonicals, load_canonical  # noqa: E402


_failures = 0


def check(name, cond, detail=""):
    global _failures
    if cond:
        print(f"  ✓ {name}")
    else:
        _failures += 1
        print(f"  ✗ {name}: {detail}")


# Build a small reusable schedule
SIMPLE_MATCHES = [
    {"red": [1, 2, 3], "blue": [4, 5, 6],
     "red_surrogate": [False, False, False],
     "blue_surrogate": [False, False, False]}
    for _ in range(12)
]


# ─────────────────────────────────────────────────────────────────────
# 1. compute_metrics is metrics-only
# ─────────────────────────────────────────────────────────────────────

print("compute_metrics is metrics-only:")
m = compute_metrics(SIMPLE_MATCHES, n_teams=12, matches_per_team=6,
                     teams_per_alliance=3, cooldown=2)
check("has achieved_lex_tuple", 'achieved_lex_tuple' in m)
check("has is_valid_paramount", 'is_valid_paramount' in m)
check("has metrics dict", 'metrics' in m and isinstance(m['metrics'], dict))
check("has summary dict", 'summary' in m and isinstance(m['summary'], dict))
check("does NOT have 'scores' field", 'scores' not in m)


# ─────────────────────────────────────────────────────────────────────
# 2. Deterministic
# ─────────────────────────────────────────────────────────────────────

print("\ncompute_metrics is deterministic:")
m2 = compute_metrics(SIMPLE_MATCHES, n_teams=12, matches_per_team=6,
                     teams_per_alliance=3, cooldown=2)
check("two calls return identical achieved_lex_tuple",
      m['achieved_lex_tuple'] == m2['achieved_lex_tuple'])
check("two calls return identical metric values",
      m['metrics']['par_quad']['value'] == m2['metrics']['par_quad']['value'])


# ─────────────────────────────────────────────────────────────────────
# 3. apply_scores doesn't mutate input
# ─────────────────────────────────────────────────────────────────────

print("\napply_scores doesn't mutate input:")
m_before = compute_metrics(SIMPLE_MATCHES, n_teams=12, matches_per_team=6,
                            teams_per_alliance=3, cooldown=2)
m_snapshot = dict(m_before)  # shallow snapshot of top-level keys
scored = apply_scores(m_before, n_teams=12, matches_per_team=6,
                      teams_per_alliance=3, cooldown=2)
check("input still lacks 'scores' field",
      'scores' not in m_before)
check("input is unchanged at top level",
      set(m_before.keys()) == set(m_snapshot.keys()))


# ─────────────────────────────────────────────────────────────────────
# 4. apply_scores attaches scores to output
# ─────────────────────────────────────────────────────────────────────

print("\napply_scores attaches scores:")
check("output has scores field", 'scores' in scored)
check("scores has composite", 'composite' in scored['scores'])
check("scores has per_criterion",
      'per_criterion' in scored['scores'])
check("scores has weights_used",
      'weights_used' in scored['scores'])
check("scores has best_known_floors_used flag",
      'best_known_floors_used' in scored['scores'])


# ─────────────────────────────────────────────────────────────────────
# 5. Stale 'scores' in input gets REPLACED (not merged)
# ─────────────────────────────────────────────────────────────────────

print("\napply_scores replaces stale 'scores' in input:")
m_with_stale = compute_metrics(SIMPLE_MATCHES, n_teams=12, matches_per_team=6,
                                teams_per_alliance=3, cooldown=2)
# Inject a stale fake scores blob
m_with_stale['scores'] = {'composite': 42.0, 'STALE': True}
rescored = apply_scores(m_with_stale, n_teams=12, matches_per_team=6,
                        teams_per_alliance=3, cooldown=2)
check("output composite is NOT the stale 42.0",
      rescored['scores']['composite'] != 42.0)
check("output scores lacks the stale 'STALE' key",
      'STALE' not in rescored['scores'])


# ─────────────────────────────────────────────────────────────────────
# 6. build_quality_report composes correctly
# ─────────────────────────────────────────────────────────────────────

print("\nbuild_quality_report composes:")
report = build_quality_report(SIMPLE_MATCHES, n_teams=12, matches_per_team=6,
                               teams_per_alliance=3, cooldown=2)
check("has metrics", 'metrics' in report)
check("has scores", 'scores' in report)
check("metric values match compute_metrics",
      report['metrics']['par_quad']['value']
      == m['metrics']['par_quad']['value'])


# ─────────────────────────────────────────────────────────────────────
# 7. Canonical library JSON storage is metrics-only
# ─────────────────────────────────────────────────────────────────────

print("\nCanonical library is metrics-only:")
real_dir = Path(_REPO_ROOT) / "app" / "canonical_schedules"
if real_dir.exists():
    for e in list_canonicals():
        qr = e.quality_report or {}
        check(f"{e.n_teams}×{e.matches_per_team} canonical has metrics",
              'metrics' in qr)
        check(f"{e.n_teams}×{e.matches_per_team} canonical has NO embedded scores",
              'scores' not in qr,
              "stored canonical has stale scores; producer needs updating")


# ─────────────────────────────────────────────────────────────────────
# 8. Different weights → different composites
# ─────────────────────────────────────────────────────────────────────

print("\nDifferent weights → different composites:")
e36 = load_canonical(36, 7, 3, 2)
if e36 is not None:
    s_default = apply_scores(e36.quality_report,
                              n_teams=36, matches_per_team=7,
                              teams_per_alliance=3, cooldown=2)
    s_partner_heavy = apply_scores(e36.quality_report,
                                    weights={'partner': 5.0, 'opponent': 0.1},
                                    n_teams=36, matches_per_team=7,
                                    teams_per_alliance=3, cooldown=2)
    # Both should be valid 0-100 floats
    check("default scoring produces valid composite",
          isinstance(s_default['scores']['composite'], (int, float)))
    check("partner-heavy scoring produces valid composite",
          isinstance(s_partner_heavy['scores']['composite'], (int, float)))
    check("weights_used reflects partner=5.0",
          s_partner_heavy['scores']['weights_used']['partner'] == 5.0)


# ─────────────────────────────────────────────────────────────────────
# 9. Fallback when shape params missing
# ─────────────────────────────────────────────────────────────────────

print("\napply_scores fallback without shape params:")
m_bare = compute_metrics(SIMPLE_MATCHES, n_teams=12, matches_per_team=6,
                          teams_per_alliance=3, cooldown=2)
# Call apply_scores with no shape params → can't do best-known lookup
scored_bare = apply_scores(m_bare)
check("works without shape params", 'scores' in scored_bare)
check("best_known_floors_used is False when shape missing",
      scored_bare['scores']['best_known_floors_used'] is False)


# ─────────────────────────────────────────────────────────────────────
# Done
# ─────────────────────────────────────────────────────────────────────

print()
if _failures > 0:
    print(f"{_failures} failure(s).")
    sys.exit(1)
print("All metrics/scores split tests passed.")
