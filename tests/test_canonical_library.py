# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the canonical schedule library + quality report builder.

Coverage:
  1. canonical_filename produces expected names
  2. CanonicalEntry round-trips via to_dict/from_dict
  3. save_canonical + load_canonical round-trip
  4. load_canonical returns None for missing files
  5. list_canonicals enumerates correctly
  6. build_quality_report produces correctly-shaped output
  7. quality_report metric values match observed values
  8. matches_floor flag is True when achieved == floor, False otherwise
  9. Loading one of the actual canonicals + rebuilding its quality
     report produces the same metrics (round-trip integrity check)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.canonical_library import (   # noqa: E402
    CanonicalEntry,
    canonical_filename,
    canonical_path,
    load_canonical,
    save_canonical,
    list_canonicals,
    SCHEDULE_CONFIDENCE_BEST_KNOWN,
    SCHEDULE_CONFIDENCE_MATCHES_FLOOR,
)
from app.quality_report import build_quality_report   # noqa: E402


_failures = 0


def check(name, cond, detail=""):
    global _failures
    if cond:
        print(f"  ✓ {name}")
    else:
        _failures += 1
        print(f"  ✗ {name}: {detail}")


# ─────────────────────────────────────────────────────────────────────────
# 1. canonical_filename
# ─────────────────────────────────────────────────────────────────────────

print("Filename and path helpers:")
check("filename 12x6x3 cd2", canonical_filename(12, 6, 3, 2) == "12x6x3_cd2.json")
check("filename 36x7x3 cd2", canonical_filename(36, 7, 3, 2) == "36x7x3_cd2.json")
check("filename 60x12x3 cd2", canonical_filename(60, 12, 3, 2) == "60x12x3_cd2.json")


# ─────────────────────────────────────────────────────────────────────────
# 2-4. CanonicalEntry save/load round-trip
# ─────────────────────────────────────────────────────────────────────────

print("\nSave/load round-trip:")

with tempfile.TemporaryDirectory() as tmpdir:
    tmp_base = Path(tmpdir)
    sample = CanonicalEntry(
        n_teams=12, matches_per_team=6, teams_per_alliance=3, cooldown=2,
        confidence=SCHEDULE_CONFIDENCE_BEST_KNOWN,
        matches=[
            {"red": [1, 2, 3], "blue": [4, 5, 6],
             "red_surrogate": [False, False, False],
             "blue_surrogate": [False, False, False]},
        ],
        achieved_lex_tuple=[0, 192, 408, 0, 30, 27, 0, 0],
        quality_report={'achieved_lex_tuple': [0, 192, 408, 0, 30, 27, 0, 0],
                        'is_valid_paramount': True, 'metrics': {}, 'summary': {}},
        provenance={'method': 'sa_best_of_n', 'sa_iterations': 100000},
    )

    path = save_canonical(sample, base_dir=tmp_base)
    check("save_canonical returns Path", isinstance(path, Path))
    check("save_canonical writes file", path.exists())

    loaded = load_canonical(12, 6, 3, 2, base_dir=tmp_base)
    check("load_canonical returns CanonicalEntry", isinstance(loaded, CanonicalEntry))
    check("loaded n_teams matches", loaded.n_teams == 12)
    check("loaded confidence matches",
          loaded.confidence == SCHEDULE_CONFIDENCE_BEST_KNOWN)
    check("loaded matches round-trip",
          len(loaded.matches) == 1 and loaded.matches[0]['red'] == [1, 2, 3])
    check("loaded lex tuple round-trip",
          loaded.achieved_lex_tuple == [0, 192, 408, 0, 30, 27, 0, 0])
    check("loaded provenance round-trip",
          loaded.provenance.get('method') == 'sa_best_of_n')

    # Missing file returns None
    missing = load_canonical(99, 99, 3, 2, base_dir=tmp_base)
    check("load_canonical missing returns None", missing is None)

    # list_canonicals enumerates
    entries = list_canonicals(base_dir=tmp_base)
    check("list_canonicals returns one entry", len(entries) == 1)
    check("listed entry matches saved",
          entries[0].n_teams == 12 and entries[0].cooldown == 2)


# ─────────────────────────────────────────────────────────────────────────
# 5. build_quality_report shape
# ─────────────────────────────────────────────────────────────────────────

print("\nQuality report shape:")

# 4 teams, 2 matches each, 2 per alliance — minimal sanity check
small_matches = [
    {"red": [1, 2], "blue": [3, 4],
     "red_surrogate": [False, False], "blue_surrogate": [False, False]},
    {"red": [1, 3], "blue": [2, 4],
     "red_surrogate": [False, False], "blue_surrogate": [False, False]},
]
report = build_quality_report(
    matches=small_matches, n_teams=4, matches_per_team=2,
    teams_per_alliance=2, cooldown=1,
)
check("report has achieved_lex_tuple", 'achieved_lex_tuple' in report)
check("report has is_valid_paramount", 'is_valid_paramount' in report)
check("report has metrics dict", isinstance(report.get('metrics'), dict))
check("report has summary dict", isinstance(report.get('summary'), dict))
check("metrics include cooldown_violations",
      'cooldown_violations' in report['metrics'])
check("metrics include par_quad", 'par_quad' in report['metrics'])
check("metrics include opp_quad", 'opp_quad' in report['metrics'])
check("metrics include surrogate_count", 'surrogate_count' in report['metrics'])
check("metrics include rb_per_team", 'rb_per_team' in report['metrics'])
check("metrics include station_per_team_spread",
      'station_per_team_spread' in report['metrics'])

# Each metric has the required fields
for k, v in report['metrics'].items():
    check(f"metric '{k}' has value", 'value' in v)
    check(f"metric '{k}' has floor", 'floor' in v)
    check(f"metric '{k}' has floor_confidence", 'floor_confidence' in v)
    check(f"metric '{k}' has distance_from_floor", 'distance_from_floor' in v)
    check(f"metric '{k}' has matches_floor", 'matches_floor' in v)

# Summary
check("summary has all_proven_floors_matched",
      'all_proven_floors_matched' in report['summary'])
check("summary has n_metrics_at_floor",
      'n_metrics_at_floor' in report['summary'])


# ─────────────────────────────────────────────────────────────────────────
# 6. matches_floor flag behavior
# ─────────────────────────────────────────────────────────────────────────

print("\nmatches_floor flag:")

# A schedule where surrogate_count=0 should hit the floor for that metric
# on a fixture with no surrogate slots needed (12×6: 72 slots, 12 matches × 6)
twelve_matches = []
for i in range(12):
    twelve_matches.append({
        "red": [1 + (i % 12), 1 + ((i+1) % 12), 1 + ((i+2) % 12)],
        "blue": [1 + ((i+3) % 12), 1 + ((i+4) % 12), 1 + ((i+5) % 12)],
        "red_surrogate": [False, False, False],
        "blue_surrogate": [False, False, False],
    })
# Don't bother making this a real schedule, just check the report structure
report_12 = build_quality_report(
    matches=twelve_matches, n_teams=12, matches_per_team=6,
    teams_per_alliance=3, cooldown=2,
)
# surrogate_count floor is 0; observed surrogate count must be 0
check("surrogate_count floor is 0",
      report_12['metrics']['surrogate_count']['floor'] == 0)
check("surrogate_count value is 0",
      report_12['metrics']['surrogate_count']['value'] == 0)
check("surrogate_count matches_floor is True",
      report_12['metrics']['surrogate_count']['matches_floor'] is True)


# ─────────────────────────────────────────────────────────────────────────
# 7. Load real canonicals (if any have been built)
# ─────────────────────────────────────────────────────────────────────────

print("\nReal canonical round-trip:")

real_dir = Path(_REPO_ROOT) / "app" / "canonical_schedules"
if real_dir.exists():
    real_entries = list_canonicals(base_dir=real_dir)
    if real_entries:
        for e in real_entries:
            # Rebuild the quality report from the stored matches; should
            # match what's in the canonical (modulo the embedded
            # achieved_lex_tuple which was computed from the same matches).
            rebuilt = build_quality_report(
                matches=e.matches, n_teams=e.n_teams,
                matches_per_team=e.matches_per_team,
                teams_per_alliance=e.teams_per_alliance,
                cooldown=e.cooldown,
            )
            stored_par = e.quality_report['metrics']['par_quad']['value']
            rebuilt_par = rebuilt['metrics']['par_quad']['value']
            check(f"{e.n_teams}×{e.matches_per_team}: par_quad rebuild matches stored",
                  stored_par == rebuilt_par,
                  f"stored={stored_par} rebuilt={rebuilt_par}")
            stored_lex = e.quality_report['achieved_lex_tuple']
            rebuilt_lex = rebuilt['achieved_lex_tuple']
            check(f"{e.n_teams}×{e.matches_per_team}: lex tuple rebuild matches stored",
                  stored_lex == rebuilt_lex,
                  f"stored={stored_lex} rebuilt={rebuilt_lex}")
    else:
        print("  (no real canonicals built yet — skipping round-trip)")
else:
    print(f"  (no {real_dir} directory — skipping round-trip)")


# ─────────────────────────────────────────────────────────────────────────
# Done
# ─────────────────────────────────────────────────────────────────────────

print()
if _failures > 0:
    print(f"{_failures} failure(s).")
    sys.exit(1)
print("All canonical library / quality report tests passed.")
