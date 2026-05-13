# SPDX-License-Identifier: GPL-3.0-or-later
# FRC Match Scheduler
# Copyright (C) 2025 FRC Match Scheduler Contributors
"""Per-schedule quality report builder.

Constructs the rich `quality_report` dict embedded in canonical
library entries and stored in the `quality_report` column of
`abstract_schedules`. The report is the single source of truth for
"how good is this schedule" — used by:

  - canonical producer (build_canonical.py): captures the report at
    library-build time so the API can serve it without recomputation
  - /api/schedules endpoint: builds the report at generation time
    for non-canonical schedules
  - UI Quality card: consumes the report to display per-criterion
    scores, floor comparisons, and confidence labels

Report shape:

    {
      "achieved_lex_tuple": [int, ...],     # 8-element from _score_from_state
      "is_valid_paramount": bool,            # F1-e validity check
      "metrics": {
        "cooldown_violations": {
          "value": int,
          "floor": int,
          "floor_confidence": "proven_optimal" | "proven_lower_bound",
          "distance_from_floor": int,
          "matches_floor": bool,
        },
        "par_quad": { ... },
        "opp_quad": { ... },
        "surrogate_count": { ... },
        "rb_per_team": { ... },
        "station_per_team_spread": { ... },
      },
      "summary": {
        "all_proven_floors_matched": bool,   # every proven_optimal floor hit
        "n_metrics_at_floor": int,
        "n_metrics_total": int,
      }
    }

The report doesn't yet include the per-criterion 1-100 scoring (that's
Phase C of the workstream). When Phase C lands, scoring fields are
added to each metric dict.
"""

from __future__ import annotations

from typing import Any

from app.quality_floors import (
    fixture_floors,
    FixtureFloors,
    CONFIDENCE_PROVEN_OPTIMAL,
)


# Maps metric names in the floor catalog to where to find the corresponding
# observed value in the lex tuple and other quality structures.
# The lex tuple is, per app.scheduler._score_from_state:
#   [0] cooldown_violations
#   [1] par_quad
#   [2] opp_quad
#   [3] surrogate_count
#   [4] rb_metric
#   [5] station_pen
#   [6] surrogate_spread (not yet in floor catalog)
#   [7] match_equity (not yet in floor catalog)


def _max_color_imbalance_per_team(matches: list[Any]) -> int:
    """Max |red_count - blue_count| across teams. Used to compute
    'rb_per_team' against its per-team floor.
    """
    if not matches:
        return 0
    red_counts: dict[int, int] = {}
    blue_counts: dict[int, int] = {}
    for m in matches:
        red  = m['red']  if isinstance(m, dict) else m.red
        blue = m['blue'] if isinstance(m, dict) else m.blue
        for t in red:
            red_counts[t] = red_counts.get(t, 0) + 1
        for t in blue:
            blue_counts[t] = blue_counts.get(t, 0) + 1
    teams = set(red_counts) | set(blue_counts)
    if not teams:
        return 0
    return max(abs(red_counts.get(t, 0) - blue_counts.get(t, 0))
               for t in teams)


def _max_station_spread_per_team(matches: list[Any]) -> int:
    """Max (max_pos_count - min_pos_count) across teams over the 6
    station-color positions {R1, R2, R3, B1, B2, B3}.
    """
    if not matches:
        return 0
    # counts[t] = [r1, r2, r3, b1, b2, b3]
    counts: dict[int, list[int]] = {}
    for m in matches:
        red  = m['red']  if isinstance(m, dict) else m.red
        blue = m['blue'] if isinstance(m, dict) else m.blue
        for i, t in enumerate(red):
            counts.setdefault(t, [0] * 6)[i] += 1
        for i, t in enumerate(blue):
            counts.setdefault(t, [0] * 6)[3 + i] += 1
    if not counts:
        return 0
    return max(max(c) - min(c) for c in counts.values())


def build_quality_report(matches: list[Any],
                         n_teams: int,
                         matches_per_team: int,
                         teams_per_alliance: int,
                         cooldown: int,
                         lex_tuple: tuple | list | None = None,
                         weights: dict[str, float] | None = None,
                         use_best_known_floors: bool = True,
                         ) -> dict[str, Any]:
    """Construct the quality_report dict for a schedule.

    Args:
        matches: list of Match-shaped dicts (red, blue, surrogate flags)
                  or Match NamedTuples. Either accepted.
        n_teams: number of teams in the fixture.
        matches_per_team: MPT.
        teams_per_alliance: TPA (typically 3 for FRC).
        cooldown: paramount cooldown floor.
        lex_tuple: optional pre-computed lex tuple. If None, computed
                   from matches.
        weights: optional quality_weights dict for scoring (Phase C). If
                 None, FRC-priority-derived DEFAULT_QUALITY_WEIGHTS used.
        use_best_known_floors: when True (default), the scoring layer
                 looks up the fixture's canonical library entry and uses
                 its achieved values as best-known floors. Set False for
                 strict count-floor scoring.

    Returns:
        Quality report dict (see module docstring for shape) including
        Phase C scoring fields: `scores.composite`, `scores.per_criterion`,
        `scores.weights_used`.
    """
    # Compute lex tuple if not supplied. Late import to avoid app/quality.py
    # → app/scheduler.py import cycle at module load (app.quality_report is
    # imported by app.quality / app.main).
    if lex_tuple is None:
        from app.scheduler import score_tuple_for_schedule
        # Convert dict matches to Match NamedTuple if needed
        from app.scheduler import Match
        ms: list[Match] = []
        for m in matches:
            if isinstance(m, dict):
                ms.append(Match(
                    red=tuple(m['red']),
                    blue=tuple(m['blue']),
                    red_surrogate=tuple(m.get('red_surrogate', [False] * teams_per_alliance)),
                    blue_surrogate=tuple(m.get('blue_surrogate', [False] * teams_per_alliance)),
                ))
            else:
                ms.append(m)
        lex_tuple = score_tuple_for_schedule(ms, num_teams=n_teams,
                                              ideal_gap=cooldown)
    lex_tuple = list(lex_tuple)

    # Compute the per-team max metrics that aren't directly in the lex tuple
    rb_max      = _max_color_imbalance_per_team(matches)
    station_max = _max_station_spread_per_team(matches)

    # Look up floors
    ff: FixtureFloors = fixture_floors(
        n_teams, matches_per_team, teams_per_alliance, cooldown
    )

    # Build per-metric dicts. For each, capture:
    #   - observed value
    #   - floor value
    #   - floor confidence
    #   - distance from floor
    #   - matches_floor flag (value == floor)
    def _metric_record(metric_name: str, observed: int | float) -> dict[str, Any]:
        floor = ff.floors.get(metric_name)
        if floor is None:
            return {
                'value':              observed,
                'floor':              None,
                'floor_confidence':   None,
                'distance_from_floor': None,
                'matches_floor':      False,
            }
        dist = observed - floor.value
        return {
            'value':              observed,
            'floor':              floor.value,
            'floor_confidence':   floor.confidence,
            'distance_from_floor': dist,
            'matches_floor':      dist == 0,
        }

    metrics: dict[str, dict[str, Any]] = {
        'cooldown_violations':     _metric_record('cooldown_violations',     lex_tuple[0]),
        'par_quad':                _metric_record('par_quad',                lex_tuple[1]),
        'opp_quad':                _metric_record('opp_quad',                lex_tuple[2]),
        'surrogate_count':         _metric_record('surrogate_count',         lex_tuple[3]),
        'rb_per_team':             _metric_record('rb_per_team',             rb_max),
        'station_per_team_spread': _metric_record('station_per_team_spread', station_max),
    }

    # Summary
    proven_optimal_floors = [m for m in metrics.values()
                             if m['floor_confidence'] == CONFIDENCE_PROVEN_OPTIMAL]
    all_proven_floors_matched = (
        bool(proven_optimal_floors)
        and all(m['matches_floor'] for m in proven_optimal_floors)
    )
    n_at_floor = sum(1 for m in metrics.values() if m['matches_floor'])

    # F1-e validity check: cooldown_violations == 0
    is_valid_paramount = metrics['cooldown_violations']['value'] == 0

    report: dict[str, Any] = {
        'achieved_lex_tuple':  lex_tuple,
        'is_valid_paramount':  is_valid_paramount,
        'metrics':             metrics,
        'summary': {
            'all_proven_floors_matched': all_proven_floors_matched,
            'n_metrics_at_floor':        n_at_floor,
            'n_metrics_total':           len(metrics),
        },
    }

    # ── Phase C: per-criterion scoring + composite ─────────────────────
    # Compute 1-100 scores per criterion + a weighted composite. When
    # use_best_known_floors=True and a canonical library entry exists
    # for this shape, the canonical's achieved values are used as the
    # floor for scoring purposes — meaningful for fixtures with
    # structural gaps (e.g., 12×6 cd=2) where count-floors aren't
    # achievable.
    from app.quality_scoring import compute_scores, best_known_floors_from_canonical
    bk_floors = None
    if use_best_known_floors:
        bk_floors = best_known_floors_from_canonical(
            n_teams, matches_per_team, teams_per_alliance, cooldown
        )
    scores = compute_scores(report, weights=weights, best_known_floors=bk_floors)
    report['scores'] = scores
    report['scores']['best_known_floors_used'] = bk_floors is not None

    return report


__all__ = ['build_quality_report']
