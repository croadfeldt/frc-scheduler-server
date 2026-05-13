#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Test app/quality.py — the canonical schedule-quality module.

Three things to verify:

  1. The module accepts all three match shapes (dict, NamedTuple,
     dataclass) and produces equivalent output for each.
  2. The DiversityReport produces the same shape the
     /api/abstract-schedules/{id}/diversity-report endpoint historically
     returned. This is the consolidation's load-bearing claim — the
     editor's renderDiversityCard() consumes a specific JSON shape and
     must not see a regression.
  3. analyze_against_thresholds + composite_score produce the same
     numbers the harness produces on a known-good fixture.

Run via:  python3 tests/test_quality.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


from app.quality import (
    compute_diversity_report,
    analyze_against_thresholds,
    composite_score,
    DiversityReport,
)
from app.scheduler import Match as SchedMatch, generate_matches
from scripts.scheduler_eval.harness_types import (
    Fixture as HarnessFixture,
    Match as HarnessMatch,
    Schedule as HarnessSchedule,
)
from scripts.scheduler_eval.metrics import analyze as harness_analyze


_failures = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global _failures
    if ok:
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ {label}" + (f": {detail}" if detail else ""))
        _failures += 1


# ─────────────────────────────────────────────────────────────────────────
# Build a known-good test fixture
# ─────────────────────────────────────────────────────────────────────────

# Use the small synthetic fixture pattern from test_eval_harness_sa_plumbing.
# 24 teams, 6 matches each, 3 teams per alliance. Builds via the production
# pipeline with a low SA budget for fast tests.

print("Generating test schedule (24t × 6MPT, SA=5000)...")
result = generate_matches(
    num_teams=24,
    matches_per_team=6,
    ideal_gap=3,
    seed=1234,
    team_numbers=list(range(101, 125)),
    n_sa_iterations=5_000,
    rb_post_pass=True,
    station_post_pass=True,
)
matches_namedtuple = result.matches
print(f"  Generated {len(matches_namedtuple)} matches")

# Build the same matches in dict shape (mimics what the DB stores).
matches_dict = [
    {
        "red":             list(m.red),
        "blue":            list(m.blue),
        "red_surrogate":   list(m.red_surrogate),
        "blue_surrogate":  list(m.blue_surrogate),
    }
    for m in matches_namedtuple
]

# Build the same matches in harness dataclass shape.
matches_harness = [
    HarnessMatch(
        match_num=i,
        red=list(m.red),
        blue=list(m.blue),
        red_surrogate=list(m.red_surrogate),
        blue_surrogate=list(m.blue_surrogate),
    )
    for i, m in enumerate(matches_namedtuple, start=1)
]


# ─────────────────────────────────────────────────────────────────────────
# 1. Shape-agnostic input handling
# ─────────────────────────────────────────────────────────────────────────

print("\nShape-agnostic input handling (DiversityReport):")

report_from_dict = compute_diversity_report(
    matches_dict, num_teams=24, matches_per_team=6, teams_per_alliance=3,
)
report_from_namedtuple = compute_diversity_report(
    matches_namedtuple, num_teams=24, matches_per_team=6, teams_per_alliance=3,
)
report_from_harness = compute_diversity_report(
    matches_harness, num_teams=24, matches_per_team=6, teams_per_alliance=3,
)

check("dict-input report has correct num_teams",
      report_from_dict.num_teams == 24)
check("NamedTuple-input report equals dict-input report",
      report_from_dict.to_dict() == report_from_namedtuple.to_dict(),
      "shapes differ across input types")
check("harness-input report equals dict-input report",
      report_from_dict.to_dict() == report_from_harness.to_dict(),
      "shapes differ across input types")


# ─────────────────────────────────────────────────────────────────────────
# 2. JSON shape matches what /diversity-report historically returned
# ─────────────────────────────────────────────────────────────────────────

print("\nJSON output shape (frontend renderDiversityCard contract):")

d = report_from_dict.to_dict()

# Top-level keys the frontend reads. Must match the legacy
# /api/abstract-schedules/{id}/diversity-report response shape exactly
# because static/index.html renderDiversityCard() reads these keys.
required_top_keys = [
    "num_teams", "matches_per_team", "total_pairs",
    "partner", "opponent", "stations", "surrogates", "slots",
]
for k in required_top_keys:
    check(f"top-level key '{k}' present", k in d, f"missing from response")

# Partner sub-structure (legacy shape: histogram/max/floor/average/zero_pairs/worst_pairs)
partner_keys = ["histogram", "max", "floor", "average", "zero_pairs", "worst_pairs"]
for k in partner_keys:
    check(f"partner.{k} present", k in d["partner"])
opponent_keys = ["histogram", "max", "floor", "average", "zero_pairs", "worst_pairs"]
for k in opponent_keys:
    check(f"opponent.{k} present", k in d["opponent"])

# Stations summary block
check("stations.max_imbalance present", "max_imbalance" in d["stations"])
check("stations.imbalanced_slots present", "imbalanced_slots" in d["stations"])

# Surrogate sub-structure
check("surrogates.total present", "total" in d["surrogates"])
check("surrogates.max_per_slot present", "max_per_slot" in d["surrogates"])
check("surrogates.concentrated_slots present", "concentrated_slots" in d["surrogates"])

# Slot table (response field is "slots")
check("slots has 24 rows (one per team)",
      len(d["slots"]) == 24,
      f"got {len(d['slots'])} rows")
if d["slots"]:
    row = d["slots"][0]
    for k in ("slot", "distinct_partners", "distinct_opponents",
              "max_partners", "max_opponents",
              "stations", "station_imbalance", "surrogate_count"):
        check(f"slots[0].{k} present", k in row)
    check("slots[0].stations has 6 positions (2*tpa)",
          len(row["stations"]) == 6,
          f"got {len(row['stations'])}")

# worst_pairs shape: list of {slots: [a,b], count: n}
if d["partner"]["worst_pairs"]:
    wp = d["partner"]["worst_pairs"][0]
    check("worst_pairs[0] has slots + count",
          "slots" in wp and "count" in wp)
    check("worst_pairs[0].slots is a 2-element list",
          isinstance(wp["slots"], list) and len(wp["slots"]) == 2)


# ─────────────────────────────────────────────────────────────────────────
# 3. analyze_against_thresholds matches direct harness analyze()
# ─────────────────────────────────────────────────────────────────────────

print("\nThreshold analysis equivalence (app.quality vs metrics.analyze):")

# Direct harness call
fixture = HarnessFixture(
    fixture_id="test",
    name="Test 24-team fixture",
    teams=list(range(101, 125)),
    matches_per_team=6,
    teams_per_alliance=3,
)
schedule = HarnessSchedule(
    fixture_id="test",
    adapter_name="frc-scheduler-server",
    matches=matches_harness,
)
direct = harness_analyze(schedule, fixture)

# Via app.quality
via_quality = analyze_against_thresholds(
    matches_namedtuple, num_teams=24, matches_per_team=6,
    teams_per_alliance=3, team_numbers=list(range(101, 125)),
    fixture_id="test", adapter_name="frc-scheduler-server",
)

for metric_name in direct.metrics:
    d_val = direct.metrics[metric_name].value
    q_val = via_quality.metrics[metric_name].value
    check(f"{metric_name} value matches", d_val == q_val,
          f"direct={d_val}, app.quality={q_val}")
    d_cls = direct.metrics[metric_name].classification
    q_cls = via_quality.metrics[metric_name].classification
    check(f"{metric_name} classification matches", d_cls == q_cls,
          f"direct={d_cls}, app.quality={q_cls}")

check("overall classification matches",
      direct.overall == via_quality.overall,
      f"direct={direct.overall}, app.quality={via_quality.overall}")


# ─────────────────────────────────────────────────────────────────────────
# 4. composite_score is deterministic and well-formed
# ─────────────────────────────────────────────────────────────────────────

print("\nComposite score:")

score = composite_score(via_quality)
check("composite_score returns a non-negative float",
      isinstance(score, float) and score >= 0,
      f"got {score!r}")

# Sanity: a hand-built all-near-optimal report should score 5.0 (11 metrics
# × 0.5 each = 5.5, or fewer if some are descriptive). Just verify it's
# bounded.
check("composite_score is within plausible range (0..120)",
      0 <= score <= 120,
      f"got {score}")

# The function should be deterministic
score2 = composite_score(via_quality)
check("composite_score is deterministic",
      score == score2,
      f"first call {score}, second call {score2}")


# ─────────────────────────────────────────────────────────────────────────
# 5. Theoretical floors are correct
# ─────────────────────────────────────────────────────────────────────────

print("\nTheoretical pair floors:")

# 24 teams × 6 MPT × 3 tpa:
#   partner_slots/team = 6 * (3-1) = 12
#   spread across 23 others => ceil(12/23) = 1
#   opponent_slots/team = 6 * 3 = 18
#   spread across 23 others => ceil(18/23) = 1
check("partner.floor = 1 for 24t × 6MPT × 3tpa",
      d["partner"]["floor"] == 1,
      f"got {d['partner']['floor']}")
check("opponent.floor = 1 for 24t × 6MPT × 3tpa",
      d["opponent"]["floor"] == 1,
      f"got {d['opponent']['floor']}")

# 36 teams × 7 MPT × 3 tpa (the 2026mnst case):
#   partner_slots/team = 7 * 2 = 14
#   spread across 35 others => ceil(14/35) = 1
#   opponent_slots/team = 7 * 3 = 21
#   spread across 35 others => ceil(21/35) = 1
# Verify by computing on dummy matches (just need correct N/MPT)
from app.quality import _theoretical_floors
floors_36_7 = _theoretical_floors(num_teams=36, matches_per_team=7, teams_per_alliance=3)
check("36t × 7MPT partner_floor = 1",
      floors_36_7["partner_floor"] == 1,
      f"got {floors_36_7['partner_floor']}")
check("36t × 7MPT opponent_floor = 1",
      floors_36_7["opponent_floor"] == 1,
      f"got {floors_36_7['opponent_floor']}")

# 40 teams × 12 MPT × 3 tpa (the micmp case where we struggle):
#   partner_slots/team = 12 * 2 = 24
#   spread across 39 others => ceil(24/39) = 1
#   opponent_slots/team = 12 * 3 = 36
#   spread across 39 others => ceil(36/39) = 1
floors_40_12 = _theoretical_floors(num_teams=40, matches_per_team=12, teams_per_alliance=3)
check("40t × 12MPT partner_floor = 1",
      floors_40_12["partner_floor"] == 1)
check("40t × 12MPT opponent_floor = 1",
      floors_40_12["opponent_floor"] == 1)

# Edge case: 8 teams × 7 MPT × 3 tpa (small fixture):
#   partner_slots/team = 7 * 2 = 14
#   spread across 7 others => ceil(14/7) = 2
#   opponent_slots/team = 7 * 3 = 21
#   spread across 7 others => ceil(21/7) = 3
floors_8_7 = _theoretical_floors(num_teams=8, matches_per_team=7, teams_per_alliance=3)
check("8t × 7MPT partner_floor = 2 (forced repeats)",
      floors_8_7["partner_floor"] == 2,
      f"got {floors_8_7['partner_floor']}")
check("8t × 7MPT opponent_floor = 3 (forced repeats)",
      floors_8_7["opponent_floor"] == 3,
      f"got {floors_8_7['opponent_floor']}")


# ─────────────────────────────────────────────────────────────────────────
# 6. The pair tables are correctly counted (sanity)
# ─────────────────────────────────────────────────────────────────────────

print("\nPair-table sanity:")

# Partner-encounters per match: each match contributes 3 unordered
# partner pairs per alliance × 2 alliances = 6 per match. The endpoint
# exposes this as `average = sum / total_pairs`. So:
#   sum         = matches * 6
#   average     = matches * 6 / total_pairs
expected_avg_partner = round(len(matches_namedtuple) * 6 / 276, 3)
check("partner.average equals (6 × num_matches) / total_pairs",
      d["partner"]["average"] == expected_avg_partner,
      f"expected {expected_avg_partner}, got {d['partner']['average']}")

# Opponent-encounters: each match contributes tpa * tpa = 9 cross-alliance
# pairs, all unordered. So sum = matches * 9.
expected_avg_opponent = round(len(matches_namedtuple) * 9 / 276, 3)
check("opponent.average equals (9 × num_matches) / total_pairs",
      d["opponent"]["average"] == expected_avg_opponent,
      f"expected {expected_avg_opponent}, got {d['opponent']['average']}")

# total_pairs is C(N, 2)
check("total_pairs = C(24, 2) = 276",
      d["total_pairs"] == 276,
      f"got {d['total_pairs']}")


# ─────────────────────────────────────────────────────────────────────────
# 8. Paramount-cooldown validity (F1-e methodology fix)
# ─────────────────────────────────────────────────────────────────────────

print("\nParamount-cooldown validity:")

# When no cooldown is specified, is_valid_paramount is None and the
# composite score is finite (legacy behavior preserved).
report_no_cd = analyze_against_thresholds(
    matches_namedtuple, num_teams=24, matches_per_team=6,
    teams_per_alliance=3, team_numbers=list(range(101, 125)),
    fixture_id="test-no-cd",
)
check("no-cooldown fixture: is_valid_paramount is None",
      report_no_cd.is_valid_paramount is None,
      f"got {report_no_cd.is_valid_paramount}")
check("no-cooldown fixture: cooldown_violations is 0",
      report_no_cd.cooldown_violations == 0,
      f"got {report_no_cd.cooldown_violations}")
check("no-cooldown fixture: composite_score is finite",
      composite_score(report_no_cd) < float("inf"),
      f"got {composite_score(report_no_cd)}")

# When cooldown is specified, is_valid_paramount is bool (True or False)
# and composite_score reflects validity. The specific value 4 is chosen
# because the synthetic 24×6 schedule generated above plausibly violates
# it (forcing the False branch to be exercised). FRC §10.5.2 doesn't
# publish specific cooldown values; the value here is for test coverage,
# not as a claim about what FRC requires.
report_cd_typical = analyze_against_thresholds(
    matches_namedtuple, num_teams=24, matches_per_team=6,
    teams_per_alliance=3, team_numbers=list(range(101, 125)),
    fixture_id="test-cd-typical",
    cooldown=4,
)
check("cooldown=4 fixture: is_valid_paramount is set (bool)",
      isinstance(report_cd_typical.is_valid_paramount, bool),
      f"got {report_cd_typical.is_valid_paramount!r}")
check("cooldown=4 fixture: cooldown_violations is non-negative int",
      isinstance(report_cd_typical.cooldown_violations, int) and
      report_cd_typical.cooldown_violations >= 0,
      f"got {report_cd_typical.cooldown_violations!r}")

# If the report is invalid, composite must be inf; if valid, finite.
cs_cd_typical = composite_score(report_cd_typical)
if report_cd_typical.is_valid_paramount is False:
    check("paramount-invalid → composite_score is inf",
          cs_cd_typical == float("inf"),
          f"got {cs_cd_typical}")
else:
    check("paramount-valid → composite_score is finite",
          cs_cd_typical < float("inf"),
          f"got {cs_cd_typical}")

# Force-construct a known-invalid case: cooldown=100 is way larger
# than any plausible gap, so EVERY schedule violates it. is_valid_paramount
# must be False and composite must be inf.
report_cd_huge = analyze_against_thresholds(
    matches_namedtuple, num_teams=24, matches_per_team=6,
    teams_per_alliance=3, team_numbers=list(range(101, 125)),
    fixture_id="test-cd-huge",
    cooldown=100,  # impossibly high — all gaps violate
)
check("cooldown=100 fixture: is_valid_paramount is False (all gaps violate)",
      report_cd_huge.is_valid_paramount is False,
      f"got {report_cd_huge.is_valid_paramount!r}")
check("cooldown=100 fixture: cooldown_violations > 0",
      report_cd_huge.cooldown_violations > 0,
      f"got {report_cd_huge.cooldown_violations}")
check("cooldown=100 fixture: composite_score is inf",
      composite_score(report_cd_huge) == float("inf"),
      f"got {composite_score(report_cd_huge)}")

# The to_dict() output exposes the new fields for downstream consumers
d_dict = report_cd_huge.to_dict()
check("to_dict includes is_valid_paramount",
      "is_valid_paramount" in d_dict,
      f"keys: {list(d_dict.keys())}")
check("to_dict includes cooldown_violations",
      "cooldown_violations" in d_dict,
      f"keys: {list(d_dict.keys())}")


# ─────────────────────────────────────────────────────────────────────────
# Done
# ─────────────────────────────────────────────────────────────────────────

print()
if _failures > 0:
    print(f"{_failures} failure(s).")
    sys.exit(1)
print("All quality module tests passed.")
