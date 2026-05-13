# SPDX-License-Identifier: GPL-3.0-or-later
# FRC Match Scheduler
# Copyright (C) 2025 FRC Match Scheduler Contributors
"""Per-schedule quality data — split into:

  - compute_metrics(matches, shape): pure metrics calculation, persisted
    to DB. Deterministic given the matches; stable for the lifetime
    of an AbstractSchedule.

  - apply_scores(metrics_report, weights): derives the per-criterion +
    composite scores. Never persisted. Computed at read time so that
    evolving scoring curves don't strand stored scores in the past.

  - build_quality_report(matches, shape, weights): convenience compose
    of the two for API response builders that want metrics + scores
    in a single round trip.

Why the split? Scoring curves and weight defaults will evolve as we
learn more about what good schedules look like. If we persist
scores, they go stale the moment we tune the curves. By persisting
only the metrics (observed facts about the schedule, immutable given
the schedule's matches) and deriving scores at every read, the
displayed composite always reflects the current scoring code.

Storage shape (metrics_report — what gets written to DB):

    {
      "achieved_lex_tuple": [int, ...],
      "is_valid_paramount": bool,
      "metrics": {
        "cooldown_violations": {value, floor, floor_confidence,
                                 distance_from_floor, matches_floor},
        "par_quad":            {...},
        "opp_quad":            {...},
        "surrogate_count":     {...},
        "rb_per_team":         {...},
        "station_per_team_spread": {...},
      },
      "summary": {
        "all_proven_floors_matched": bool,
        "n_metrics_at_floor": int,
        "n_metrics_total": int,
      }
    }

After apply_scores() adds the derived portion:

    {
      ...metrics_report...
      "scores": {
        "weights_used": {cooldown, partner, opponent, surrogate, color, station},
        "per_criterion": {cooldown: {score, value, floor, weight, curve}, ...},
        "composite": float,
        "composite_uncapped": float,
        "is_valid_paramount": bool,
        "best_known_floors_used": bool,
      }
    }
"""

from __future__ import annotations

from typing import Any

from app.quality_floors import (
    fixture_floors,
    FixtureFloors,
    CONFIDENCE_PROVEN_OPTIMAL,
)


# ── Helpers ─────────────────────────────────────────────────────────────


def _max_color_imbalance_per_team(matches: list[Any]) -> int:
    """Max |red_count - blue_count| across teams. Computes the
    'rb_per_team' observed value for the metrics dict."""
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
    station-color positions {R1, R2, R3, B1, B2, B3}."""
    if not matches:
        return 0
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


# ── compute_metrics: pure, persisted ───────────────────────────────────


def compute_metrics(matches: list[Any],
                     n_teams: int,
                     matches_per_team: int,
                     teams_per_alliance: int,
                     cooldown: int,
                     lex_tuple: tuple | list | None = None,
                     ) -> dict[str, Any]:
    """Pure metrics calculation.

    Output is deterministic given the matches and is what gets
    persisted to DB. No scoring data, no weights — just observations
    of the schedule against the fixture's mathematical floors.

    Callers persisting to DB MUST use this function (not
    build_quality_report) so the stored data carries no scoring
    artifacts that could go stale.
    """
    # Compute lex tuple if not supplied. Late imports avoid module
    # load cycles (app.scheduler -> app.quality -> app.quality_report).
    if lex_tuple is None:
        from app.scheduler import score_tuple_for_schedule, Match
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

    rb_max      = _max_color_imbalance_per_team(matches)
    station_max = _max_station_spread_per_team(matches)

    ff: FixtureFloors = fixture_floors(
        n_teams, matches_per_team, teams_per_alliance, cooldown
    )

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

    proven_optimal_floors = [m for m in metrics.values()
                             if m['floor_confidence'] == CONFIDENCE_PROVEN_OPTIMAL]
    all_proven_floors_matched = (
        bool(proven_optimal_floors)
        and all(m['matches_floor'] for m in proven_optimal_floors)
    )
    n_at_floor = sum(1 for m in metrics.values() if m['matches_floor'])

    is_valid_paramount = metrics['cooldown_violations']['value'] == 0

    return {
        'achieved_lex_tuple':  lex_tuple,
        'is_valid_paramount':  is_valid_paramount,
        'metrics':             metrics,
        'summary': {
            'all_proven_floors_matched': all_proven_floors_matched,
            'n_metrics_at_floor':        n_at_floor,
            'n_metrics_total':           len(metrics),
        },
    }


# ── apply_scores: derived, never persisted ────────────────────────────


def apply_scores(metrics_report: dict[str, Any],
                  weights: dict[str, float] | None = None,
                  *,
                  n_teams: int | None = None,
                  matches_per_team: int | None = None,
                  teams_per_alliance: int | None = None,
                  cooldown: int | None = None,
                  use_best_known_floors: bool = True,
                  ) -> dict[str, Any]:
    """Derive per-criterion + composite scores from a metrics_report.

    Returns a NEW dict; does not mutate input. The shape parameters
    are used to look up canonical library entries for best-known
    floor scoring; if any is missing, scoring falls back to
    count-floors only.

    This function is called at read time (GET endpoint, /rescore,
    /score-preview) — never at write time. That guarantees displayed
    scores always reflect current scoring code under current weights.
    """
    from app.quality_scoring import compute_scores, best_known_floors_from_canonical

    bk_floors = None
    if use_best_known_floors and n_teams is not None and matches_per_team is not None:
        bk_floors = best_known_floors_from_canonical(
            n_teams, matches_per_team,
            teams_per_alliance if teams_per_alliance is not None else 3,
            cooldown if cooldown is not None else 2,
        )
    scores = compute_scores(metrics_report, weights=weights,
                             best_known_floors=bk_floors)

    out = dict(metrics_report)
    # Defensive: if input had a stale 'scores' field (from pre-split
    # persistence), the new derived one replaces it.
    out['scores'] = dict(scores)
    out['scores']['best_known_floors_used'] = bk_floors is not None
    return out


# ── build_quality_report: convenience compose ─────────────────────────


def build_quality_report(matches: list[Any],
                         n_teams: int,
                         matches_per_team: int,
                         teams_per_alliance: int,
                         cooldown: int,
                         lex_tuple: tuple | list | None = None,
                         weights: dict[str, float] | None = None,
                         use_best_known_floors: bool = True,
                         ) -> dict[str, Any]:
    """Convenience: compute metrics AND apply scores in one call.

    Used by API response builders that want a complete view of a
    schedule's quality data. Persistence callers should use
    compute_metrics() directly — persisting the output of this
    function would store derivable scoring data, defeating the
    point of the split.
    """
    metrics_report = compute_metrics(
        matches, n_teams, matches_per_team, teams_per_alliance, cooldown,
        lex_tuple=lex_tuple,
    )
    return apply_scores(
        metrics_report, weights=weights,
        n_teams=n_teams, matches_per_team=matches_per_team,
        teams_per_alliance=teams_per_alliance, cooldown=cooldown,
        use_best_known_floors=use_best_known_floors,
    )


__all__ = ['compute_metrics', 'apply_scores', 'build_quality_report']
