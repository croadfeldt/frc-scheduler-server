# SPDX-License-Identifier: GPL-3.0-or-later
# FRC Match Scheduler
# Copyright (C) 2025 FRC Match Scheduler Contributors
"""Per-criterion 1-100 scoring framework with organizer-tunable weights.

Phase C of the Schedule Quality Framework. Converts the per-metric
value/floor/distance data (from Phase B's quality_report) into
human-interpretable 1-100 scores. Each criterion gets its own score;
a weighted composite gives a single headline number.

Scoring philosophy:
  - 100 = the schedule matches the theoretical floor on this metric
    (best-possible outcome under current mathematical knowledge)
  - 0   = catastrophic / paramount-invalid / 2× the floor (depending
    on metric)
  - Curves are per-metric, not universal — each metric has its own
    natural scale

Per-metric curves (justified in docs/scheduler/quality-scoring.md):

  cooldown_violations: BINARY
    value == 0  → 100   (paramount-valid)
    value  > 0  → 0     (paramount-invalid; FRC §10.5.2 rejects)

  par_quad, opp_quad:  QUADRATIC DECAY
    score = 100 × max(0, 1 - (distance / floor)²)
    Hits 0 at distance == floor (i.e., value == 2× floor).
    Matches the metric's own quadratic nature.

  rb_per_team, station_per_team_spread, surrogate_count: LINEAR-BOUNDED
    score = 100 × max(0, 1 - distance × 25)
    Each +1 above floor costs 25 points; +4 above floor = 0.
    These metrics' floors are 0 or 1, so distance is small-integer
    and "+1 above" is already a meaningful regression.

Paramount gate:
  When cooldown_violations > 0 (paramount-invalid per FRC §10.5.2),
  the COMPOSITE is 0 regardless of other scores. Per-criterion
  scores still display so organizers can see what was achieved on
  non-paramount metrics — but the headline says "invalid."

Weights:
  Organizer-supplied dict {criterion: weight}. Defaults are FRC §10.5.2
  priority-derived. Weight of 0 means "ignore"; weight > 1 boosts.
  Cooldown is always weighted ≥ 1 — paramount can't be tuned away.

  composite = Σ(score_i × weight_i) / Σ(weight_i)   for valid schedules
  composite = 0                                       for invalid schedules

Best-known floor:
  When the schedule's fixture shape has a canonical library entry,
  the canonical's achieved value is the "best-known floor" — schedules
  at that value get 100 even if the count-distribution floor (Phase A)
  is lower. This matters for fixtures with structural gaps like
  12×6 cooldown=2, where the count-floor (84 on par_quad) isn't
  achievable.

  The scoring module accepts an optional `best_known_floors` dict
  override; defaults to count-floor from the quality_report.
"""

from __future__ import annotations

from typing import Any


# ── Defaults ─────────────────────────────────────────────────────────────


# FRC §10.5.2 priority-derived default weights. Cooldown is paramount
# (handled by gate, weight just adds to composite calc); partner and
# opponent are the two main pairing criteria; the rest are lower
# priority. Weights normalize during composite calculation.
DEFAULT_QUALITY_WEIGHTS: dict[str, float] = {
    "cooldown":  1.0,   # FRC #1 paramount (binary 100/0)
    "partner":   1.0,   # FRC #2 (par_quad)
    "opponent":  1.0,   # FRC #3 (opp_quad)
    "surrogate": 0.5,   # FRC #4 (almost always at floor)
    "color":     0.5,   # FRC #5 (rb_per_team)
    "station":   0.5,   # FRC #6 (station_per_team_spread)
}

# Map between weight-key names (organizer-facing) and metric-key names
# (internal). The split lets us rename a metric without breaking the
# organizer API.
WEIGHT_KEY_TO_METRIC: dict[str, str] = {
    "cooldown":  "cooldown_violations",
    "partner":   "par_quad",
    "opponent":  "opp_quad",
    "surrogate": "surrogate_count",
    "color":     "rb_per_team",
    "station":   "station_per_team_spread",
}


# ── Per-metric score curves ──────────────────────────────────────────────


def _score_binary_paramount(value: int | float, floor: int | float) -> float:
    """Cooldown-violations curve. Floor is always 0 here; any positive
    value is paramount-invalid."""
    return 100.0 if value <= floor else 0.0


def _score_quadratic_decay(value: int | float, floor: int | float) -> float:
    """par_quad / opp_quad curve.

    score = 100 × max(0, 1 - (distance / max(floor, 1))²)

    Floor=0 special case: any positive value scores 0 (no scale).
    """
    if floor <= 0:
        return 100.0 if value <= 0 else 0.0
    distance = max(0, value - floor)
    ratio    = distance / floor
    return 100.0 * max(0.0, 1.0 - ratio * ratio)


def _score_linear_bounded(value: int | float, floor: int | float,
                           per_unit_cost: float = 25.0) -> float:
    """rb_per_team / station_per_team_spread / surrogate_count curve.

    score = 100 - distance × per_unit_cost   (clamped to [0, 100])

    Default per_unit_cost=25 means +1 above floor costs 25 points
    and +4 above floor = 0.
    """
    distance = max(0, value - floor)
    return max(0.0, 100.0 - distance * per_unit_cost)


# Per-metric curve dispatch.
_CURVES = {
    "cooldown_violations":     _score_binary_paramount,
    "par_quad":                _score_quadratic_decay,
    "opp_quad":                _score_quadratic_decay,
    "rb_per_team":             _score_linear_bounded,
    "station_per_team_spread": _score_linear_bounded,
    "surrogate_count":         _score_linear_bounded,
}


def criterion_score(metric_name: str,
                    value: int | float,
                    floor: int | float) -> float:
    """Compute the 0-100 score for a single criterion.

    Returns float in [0, 100]. Higher is better.
    """
    curve = _CURVES.get(metric_name)
    if curve is None:
        # Unknown metric → assume "matches_floor or not", default behavior
        return 100.0 if value <= floor else 0.0
    return curve(value, floor)


# ── Weight handling ─────────────────────────────────────────────────────


def _normalize_weights(weights: dict[str, float] | None) -> dict[str, float]:
    """Fill in missing keys with defaults, clamp ranges, ensure cooldown ≥ 1.

    Returns a complete weights dict with all known criteria present.
    """
    out = dict(DEFAULT_QUALITY_WEIGHTS)
    if weights:
        for k, v in weights.items():
            if k in out:
                # Clamp to [0, 5]; negative weights make no sense, very
                # large weights would let one criterion dominate
                # everything else.
                out[k] = max(0.0, min(5.0, float(v)))
    # Cooldown is paramount per FRC §10.5.2 — never let it be zeroed.
    if out["cooldown"] < 1.0:
        out["cooldown"] = 1.0
    return out


# ── Composite computation ───────────────────────────────────────────────


def compute_scores(quality_report: dict,
                   weights: dict[str, float] | None = None,
                   best_known_floors: dict[str, int | float] | None = None,
                   ) -> dict[str, Any]:
    """Compute per-criterion scores + composite for a quality_report.

    Args:
        quality_report: dict produced by build_quality_report (Phase B).
                        Required keys: 'metrics' (per-metric dict with
                        'value', 'floor'), 'is_valid_paramount' (bool).
        weights: organizer-supplied weights dict, keys from
                 WEIGHT_KEY_TO_METRIC (cooldown, partner, opponent,
                 surrogate, color, station). Missing keys filled from
                 DEFAULT_QUALITY_WEIGHTS. Cooldown auto-clamped to ≥ 1.
        best_known_floors: optional override of floor values per
                           metric_name (not weight_key). When provided,
                           a metric's floor is replaced by the
                           best-known floor before scoring — useful for
                           shapes with structural gaps (12×6 cd=2)
                           where the count-floor isn't achievable.

    Returns:
        {
          'weights_used':       normalized weights dict (all 6 keys),
          'per_criterion': {
              'cooldown':  {'score': float, 'value': ..., 'floor': ...,
                            'weight': float, 'curve': 'binary' | 'quadratic' | 'linear'},
              ...
          },
          'composite':          float [0, 100] (0 if paramount-invalid),
          'composite_uncapped': float — what composite would be ignoring
                                paramount gate (debug/transparency),
          'is_valid_paramount': bool — echoed for caller convenience,
        }
    """
    w = _normalize_weights(weights)

    metrics = quality_report.get('metrics', {})
    is_valid = quality_report.get('is_valid_paramount', True)

    per_criterion: dict[str, dict[str, Any]] = {}
    sum_weighted = 0.0
    sum_weights  = 0.0

    curve_label = {
        "cooldown_violations":     "binary",
        "par_quad":                "quadratic",
        "opp_quad":                "quadratic",
        "rb_per_team":             "linear",
        "station_per_team_spread": "linear",
        "surrogate_count":         "linear",
    }

    for weight_key, metric_name in WEIGHT_KEY_TO_METRIC.items():
        m = metrics.get(metric_name)
        if m is None:
            continue
        value = m.get('value', 0)
        # Use best-known floor if supplied; otherwise count-floor from report
        floor = m.get('floor', 0)
        if best_known_floors and metric_name in best_known_floors:
            floor = best_known_floors[metric_name]

        weight = w.get(weight_key, 0.0)
        score  = criterion_score(metric_name, value, floor)

        per_criterion[weight_key] = {
            'metric':           metric_name,
            'value':            value,
            'floor':            floor,
            'score':            round(score, 1),
            'weight':           weight,
            'curve':            curve_label.get(metric_name, 'binary'),
        }

        if weight > 0:
            sum_weighted += score * weight
            sum_weights  += weight

    composite_uncapped = (sum_weighted / sum_weights) if sum_weights > 0 else 0.0
    # Paramount gate: invalid schedules score 0 regardless of other metrics.
    composite = composite_uncapped if is_valid else 0.0

    return {
        'weights_used':       w,
        'per_criterion':      per_criterion,
        'composite':          round(composite, 1),
        'composite_uncapped': round(composite_uncapped, 1),
        'is_valid_paramount': is_valid,
    }


# ── Convenience: best-known floors from canonical library ───────────────


def best_known_floors_from_canonical(n_teams: int, matches_per_team: int,
                                      teams_per_alliance: int,
                                      cooldown: int) -> dict[str, int | float] | None:
    """Look up the canonical library entry for a fixture shape and
    extract its achieved metric values as "best-known floors."

    Returns None if no canonical exists; otherwise a dict mapping
    metric_name → achieved value. The caller passes this to
    compute_scores' `best_known_floors` parameter.

    Useful for fixtures with structural gaps (12×6 cd=2) where the
    count-distribution floor (Phase A) isn't achievable — scoring
    against the canonical's achieved value gives meaningful
    "how close to known-best" answers.
    """
    # Late import to avoid load-time cycles
    from app.canonical_library import load_canonical
    entry = load_canonical(n_teams, matches_per_team, teams_per_alliance, cooldown)
    if entry is None:
        return None
    metrics = entry.quality_report.get('metrics', {})
    return {
        metric_name: m['value']
        for metric_name, m in metrics.items()
        if 'value' in m
    }


__all__ = [
    'DEFAULT_QUALITY_WEIGHTS',
    'WEIGHT_KEY_TO_METRIC',
    'criterion_score',
    'compute_scores',
    'best_known_floors_from_canonical',
]
