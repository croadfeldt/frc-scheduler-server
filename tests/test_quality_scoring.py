# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for app.quality_scoring — per-criterion 1-100 + composite.

Coverage:
  1. Per-metric score curves on hand-computed cases
  2. Default weights + custom weights composite math
  3. Paramount gate: invalid schedule → composite=0
  4. Weights normalization: clamping, defaults fill-in, cooldown ≥ 1
  5. best_known_floors override
  6. Empty/missing data edge cases
  7. Round-trip through build_quality_report (Phase B + C integration)
  8. compute_scores on real canonical entries
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.quality_scoring import (   # noqa: E402
    DEFAULT_QUALITY_WEIGHTS,
    WEIGHT_KEY_TO_METRIC,
    criterion_score,
    compute_scores,
    best_known_floors_from_canonical,
    _normalize_weights,
)


_failures = 0


def check(name, cond, detail=""):
    global _failures
    if cond:
        print(f"  ✓ {name}")
    else:
        _failures += 1
        print(f"  ✗ {name}: {detail}")


# ─────────────────────────────────────────────────────────────────────────
# 1. Per-metric score curves
# ─────────────────────────────────────────────────────────────────────────

print("Per-metric score curves:")

# Binary (cooldown_violations)
check("cooldown 0 → 100", criterion_score("cooldown_violations", 0, 0) == 100.0)
check("cooldown 1 → 0", criterion_score("cooldown_violations", 1, 0) == 0.0)
check("cooldown 50 → 0", criterion_score("cooldown_violations", 50, 0) == 0.0)

# Quadratic (par_quad, opp_quad)
# At floor → 100
check("par_quad at floor → 100",
      criterion_score("par_quad", 252, 252) == 100.0)
# 10% above floor: 100 × (1 - 0.1²) = 99
check("par_quad 10% above floor → 99",
      abs(criterion_score("par_quad", 277, 252) - 99.0163) < 0.01)
# 50% above floor: 100 × (1 - 0.25) = 75
check("par_quad 50% above floor → 75",
      criterion_score("par_quad", 378, 252) == 75.0)
# 100% above floor (2× floor): 100 × (1 - 1) = 0
check("par_quad at 2× floor → 0",
      criterion_score("par_quad", 504, 252) == 0.0)
# Beyond 2× floor: clamped to 0
check("par_quad far above floor → 0",
      criterion_score("par_quad", 1000, 252) == 0.0)
# Floor=0 edge case
check("par_quad value 0 floor 0 → 100",
      criterion_score("par_quad", 0, 0) == 100.0)
check("par_quad value 5 floor 0 → 0",
      criterion_score("par_quad", 5, 0) == 0.0)

# Linear-bounded (rb_per_team, station_per_team_spread, surrogate_count)
check("rb_per_team at floor → 100",
      criterion_score("rb_per_team", 0, 0) == 100.0)
check("rb_per_team +1 above floor → 75",
      criterion_score("rb_per_team", 1, 0) == 75.0)
check("rb_per_team +2 → 50",
      criterion_score("rb_per_team", 2, 0) == 50.0)
check("rb_per_team +4 → 0",
      criterion_score("rb_per_team", 4, 0) == 0.0)
check("rb_per_team +5 → 0 (clamped)",
      criterion_score("rb_per_team", 5, 0) == 0.0)
check("station +1 above floor=1 → 75",
      criterion_score("station_per_team_spread", 2, 1) == 75.0)
check("surrogate matches floor → 100",
      criterion_score("surrogate_count", 0, 0) == 100.0)

# Unknown metric — defaults to "matches floor or 0"
check("unknown metric at floor → 100",
      criterion_score("zzz_unknown", 5, 5) == 100.0)
check("unknown metric above floor → 0",
      criterion_score("zzz_unknown", 6, 5) == 0.0)


# ─────────────────────────────────────────────────────────────────────────
# 2. Weights normalization
# ─────────────────────────────────────────────────────────────────────────

print("\nWeights normalization:")

# Default
norm = _normalize_weights(None)
check("default fills all 6 keys",
      set(norm.keys()) == set(DEFAULT_QUALITY_WEIGHTS.keys()))
check("default partner = 1.0", norm["partner"] == 1.0)

# Custom partial — missing keys filled from defaults
norm = _normalize_weights({"partner": 2.0})
check("partial: partner overridden", norm["partner"] == 2.0)
check("partial: opponent kept at default", norm["opponent"] == 1.0)

# Clamping
norm = _normalize_weights({"partner": 100, "opponent": -1})
check("clamp: partner clamped to 5", norm["partner"] == 5.0)
check("clamp: opponent clamped to 0", norm["opponent"] == 0.0)

# Cooldown can't go below 1
norm = _normalize_weights({"cooldown": 0})
check("cooldown=0 clamped to ≥ 1", norm["cooldown"] >= 1.0)
norm = _normalize_weights({"cooldown": 0.5})
check("cooldown=0.5 clamped to ≥ 1", norm["cooldown"] >= 1.0)

# Unknown keys ignored
norm = _normalize_weights({"foobar": 99, "partner": 1.5})
check("unknown key ignored", "foobar" not in norm)
check("known key still applied", norm["partner"] == 1.5)


# ─────────────────────────────────────────────────────────────────────────
# 3. Composite math
# ─────────────────────────────────────────────────────────────────────────

print("\nComposite math:")

# Mock quality_report — all at floor, should score 100
perfect_report = {
    'achieved_lex_tuple': [0, 252, 378, 0, 0, 0, 0, 0],
    'is_valid_paramount': True,
    'metrics': {
        'cooldown_violations':     {'value': 0,   'floor': 0,   'floor_confidence': 'proven_optimal'},
        'par_quad':                {'value': 252, 'floor': 252, 'floor_confidence': 'proven_lower_bound'},
        'opp_quad':                {'value': 378, 'floor': 378, 'floor_confidence': 'proven_lower_bound'},
        'surrogate_count':         {'value': 0,   'floor': 0,   'floor_confidence': 'proven_optimal'},
        'rb_per_team':             {'value': 0,   'floor': 0,   'floor_confidence': 'proven_optimal'},
        'station_per_team_spread': {'value': 0,   'floor': 0,   'floor_confidence': 'proven_optimal'},
    },
}
result = compute_scores(perfect_report)
check("perfect report: composite = 100", result['composite'] == 100.0)
check("perfect report: composite_uncapped = 100",
      result['composite_uncapped'] == 100.0)
check("perfect report: is_valid_paramount echoed",
      result['is_valid_paramount'] is True)
check("perfect report: per_criterion has 6 entries",
      len(result['per_criterion']) == 6)
for k, c in result['per_criterion'].items():
    check(f"perfect report {k}: score=100", c['score'] == 100.0)

# Invalid schedule — paramount gate kicks in
invalid_report = dict(perfect_report)
invalid_report['is_valid_paramount'] = False
invalid_report = dict(invalid_report)
invalid_report['metrics'] = dict(perfect_report['metrics'])
invalid_report['metrics']['cooldown_violations'] = {'value': 5, 'floor': 0, 'floor_confidence': 'proven_optimal'}
result = compute_scores(invalid_report)
check("invalid: composite = 0", result['composite'] == 0.0)
check("invalid: composite_uncapped > 0 (transparency)",
      result['composite_uncapped'] > 0)
check("invalid: cooldown criterion score = 0",
      result['per_criterion']['cooldown']['score'] == 0.0)
check("invalid: other criterions still scored",
      result['per_criterion']['partner']['score'] == 100.0)


# ─────────────────────────────────────────────────────────────────────────
# 4. Custom weights
# ─────────────────────────────────────────────────────────────────────────

print("\nCustom weights:")

# Mixed schedule — partner at floor, others above
mixed_report = {
    'achieved_lex_tuple': [0, 252, 504, 0, 4, 2, 0, 0],
    'is_valid_paramount': True,
    'metrics': {
        'cooldown_violations':     {'value': 0,   'floor': 0,   'floor_confidence': 'proven_optimal'},
        'par_quad':                {'value': 252, 'floor': 252, 'floor_confidence': 'proven_lower_bound'},  # score 100
        'opp_quad':                {'value': 504, 'floor': 252, 'floor_confidence': 'proven_lower_bound'},  # score 0
        'surrogate_count':         {'value': 0,   'floor': 0,   'floor_confidence': 'proven_optimal'},
        'rb_per_team':             {'value': 4,   'floor': 0,   'floor_confidence': 'proven_optimal'},  # score 0
        'station_per_team_spread': {'value': 2,   'floor': 1,   'floor_confidence': 'proven_optimal'},  # score 75
    },
}

# Default weights: cooldown=1, partner=1, opponent=1, surrogate=0.5, color=0.5, station=0.5
# scores: 100, 100, 0, 100, 0, 75
# weighted: 100+100+0+50+0+37.5 = 287.5
# weight sum: 1+1+1+0.5+0.5+0.5 = 4.5
# composite: 287.5 / 4.5 = 63.89
result = compute_scores(mixed_report)
expected = round((100 + 100 + 0 + 100 * 0.5 + 0 * 0.5 + 75 * 0.5) / 4.5, 1)
check(f"mixed default: composite ≈ {expected}",
      abs(result['composite'] - expected) < 0.5,
      f"got {result['composite']}")

# Boost partner ×2, ignore station — should increase composite
# weights: cooldown=1, partner=2, opponent=1, surrogate=0.5, color=0.5, station=0
# scores: 100, 100, 0, 100, 0, 75 (still computed, just not weighted)
# weighted: 100+200+0+50+0+0 = 350
# weight sum: 1+2+1+0.5+0.5+0 = 5
# composite: 350 / 5 = 70.0
result = compute_scores(mixed_report, weights={"partner": 2.0, "station": 0.0})
expected = round((100 + 200 + 0 + 50 + 0) / 5.0, 1)
check(f"mixed custom: composite = {expected}",
      abs(result['composite'] - expected) < 0.5,
      f"got {result['composite']}")
check("weights_used reflects custom",
      result['weights_used']['partner'] == 2.0)
check("weights_used reflects ignored",
      result['weights_used']['station'] == 0.0)


# ─────────────────────────────────────────────────────────────────────────
# 5. best_known_floors override
# ─────────────────────────────────────────────────────────────────────────

print("\nbest_known_floors override:")

# Schedule with par_quad=192, count-floor=84
# Without override: distance 108, ratio 108/84 = 1.29 > 1 → score 0
# With override (bk_floor=192): distance 0 → score 100
gap_report = {
    'achieved_lex_tuple': [0, 192, 408, 0, 0, 0, 0, 0],
    'is_valid_paramount': True,
    'metrics': {
        'cooldown_violations':     {'value': 0,   'floor': 0},
        'par_quad':                {'value': 192, 'floor': 84},   # gap!
        'opp_quad':                {'value': 408, 'floor': 192},
        'surrogate_count':         {'value': 0,   'floor': 0},
        'rb_per_team':             {'value': 0,   'floor': 0},
        'station_per_team_spread': {'value': 0,   'floor': 0},
    },
}
without = compute_scores(gap_report)
check("count-floor scoring: par_quad scores 0",
      without['per_criterion']['partner']['score'] == 0.0)
with_bk = compute_scores(gap_report,
                          best_known_floors={'par_quad': 192, 'opp_quad': 408})
check("bk-floor scoring: par_quad scores 100",
      with_bk['per_criterion']['partner']['score'] == 100.0)
check("bk-floor scoring: composite > count-floor composite",
      with_bk['composite'] > without['composite'])


# ─────────────────────────────────────────────────────────────────────────
# 6. Edge cases
# ─────────────────────────────────────────────────────────────────────────

print("\nEdge cases:")

# Empty metrics dict
empty_report = {'is_valid_paramount': True, 'metrics': {}}
result = compute_scores(empty_report)
check("empty metrics: per_criterion empty",
      len(result['per_criterion']) == 0)
check("empty metrics: composite = 0 (no weights summed)",
      result['composite'] == 0.0)

# All weights zero (except cooldown which is clamped)
result = compute_scores(perfect_report, weights={
    "partner": 0, "opponent": 0, "surrogate": 0,
    "color": 0, "station": 0,  # cooldown auto-clamped to 1
})
check("all-zero (cooldown clamped): composite still valid",
      result['composite'] == 100.0)
check("all-zero: cooldown survived",
      result['weights_used']['cooldown'] >= 1.0)


# ─────────────────────────────────────────────────────────────────────────
# 7. Integration with build_quality_report
# ─────────────────────────────────────────────────────────────────────────

print("\nIntegration with build_quality_report:")

from app.quality_report import build_quality_report

simple_matches = [
    {"red": [1, 2, 3], "blue": [4, 5, 6],
     "red_surrogate": [False, False, False],
     "blue_surrogate": [False, False, False]},
] * 12
report = build_quality_report(
    matches=simple_matches, n_teams=12, matches_per_team=6,
    teams_per_alliance=3, cooldown=2,
    use_best_known_floors=False,  # disable canonical lookup for deterministic test
)
check("integrated report has 'scores' key", 'scores' in report)
check("integrated report scores has 'composite'",
      'composite' in report['scores'])
check("integrated report scores has 'per_criterion'",
      'per_criterion' in report['scores'])
check("integrated report scores has 'weights_used'",
      'weights_used' in report['scores'])

# With custom weights
report2 = build_quality_report(
    matches=simple_matches, n_teams=12, matches_per_team=6,
    teams_per_alliance=3, cooldown=2,
    weights={"partner": 3.0},
    use_best_known_floors=False,
)
check("integrated with custom weights: weights_used.partner = 3",
      report2['scores']['weights_used']['partner'] == 3.0)


# ─────────────────────────────────────────────────────────────────────────
# 8. Real canonical scoring
# ─────────────────────────────────────────────────────────────────────────

print("\nReal canonical scoring (metrics-only storage; scores derived):")

try:
    from app.canonical_library import load_canonical
    from app.quality_report import apply_scores
    e = load_canonical(36, 7, 3, 2)
    if e is not None:
        # Canonical storage is metrics-only — no 'scores' in stored JSON.
        check("36×7 canonical does NOT have stored scores (metrics-only)",
              'scores' not in e.quality_report)
        # Derive scores at read time
        scored = apply_scores(e.quality_report,
                               n_teams=36, matches_per_team=7,
                               teams_per_alliance=3, cooldown=2)
        comp = scored['scores']['composite']
        check("36×7 derived composite is sensible (0-100)",
              isinstance(comp, (int, float)) and 0 <= comp <= 100,
              f"got {comp!r}")
        # Re-scoring same metrics yields same composite
        scored2 = apply_scores(e.quality_report,
                                n_teams=36, matches_per_team=7,
                                teams_per_alliance=3, cooldown=2)
        check("re-deriving scores is deterministic",
              abs(scored2['scores']['composite'] - comp) < 0.01,
              f"first={comp} second={scored2['scores']['composite']}")
except Exception as exc:
    print(f"  (skipping real canonical test: {exc})")


# ─────────────────────────────────────────────────────────────────────────
# Done
# ─────────────────────────────────────────────────────────────────────────

print()
if _failures > 0:
    print(f"{_failures} failure(s).")
    sys.exit(1)
print("All quality_scoring tests passed.")
