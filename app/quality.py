# SPDX-License-Identifier: GPL-3.0-or-later
# FRC Match Scheduler
# Copyright (C) 2025 FRC Match Scheduler Contributors
"""Canonical schedule-quality module.

The single source of truth for all schedule-quality computation in the
project. Three layers:

  1. Algorithm primitives (lex tuple) — delegates to app.scheduler.
  2. Count-based metrics (repeat partners/opponents, station spread,
     color imbalance, etc.) — delegates to scripts.scheduler_eval.metrics.
  3. Unified analyzer — combines both, plus the count-clustering and
     pair-distribution structures the editor's Quality card needs.

Every caller of "is this schedule any good?" in the codebase routes
through here. Today that means:

  - The /api/abstract-schedules/{id}/diversity-report endpoint (shrinks
    from ~145 lines of inline computation to a thin wrapper).
  - Future /api/schedules/{id}/quality-report endpoint (workstreams/
    schedule-quality-reporting.md Phase B).
  - The abstract library workstream's curation pipeline — entries are
    ranked by the composite score this module produces.
  - Eval harness — currently imports from scripts.scheduler_eval.metrics
    directly; can continue to do so since this module just re-exports
    those primitives. The harness's standalone use case (CLI runs
    against TBA-pulled fixtures) is unchanged.

Workstream reference: workstreams/schedule-quality-reporting.md.
ADR reference: ADR 001 (lex tuple is the canonical algorithm score).
Metric catalog: docs/scheduler/quality-metrics.md — every metric this
module computes is defined there with thresholds, floors, and sources.

Why this module exists rather than just calling metrics.py directly:

  - metrics.py's analyze() takes a harness Schedule + Fixture, neither
    of which the application code uses natively. This module provides
    an application-friendly entry point that accepts the data shapes
    the rest of app/ deals with (lists of match dicts, num_teams,
    matches_per_team, teams_per_alliance).
  - The diversity-report endpoint computes additional structures
    (pair histograms, theoretical floors, per-slot tables, worst-pair
    callouts) that aren't in metrics.py and that the editor's Quality
    card depends on. Those live here.
  - Future Phase B work adds a composite-score field, percentile-
    based reference comparison, and a unified report shape. Those
    additions land here, not in metrics.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Any

# Re-export the harness types for callers that want to use them
# (e.g. the eval harness itself, or anything that already speaks
# harness Schedule + Fixture). New code should prefer the
# QualityReport dataclass defined below.
from scripts.scheduler_eval.metrics import (
    THRESHOLDS,
    Threshold,
    MetricResult,
    AnalysisReport,
    analyze as analyze_harness_schedule,
)
from scripts.scheduler_eval.harness_types import (
    Fixture as HarnessFixture,
    Match as HarnessMatch,
    Schedule as HarnessSchedule,
)


# ─────────────────────────────────────────────────────────────────────────
# Match input — the application-friendly shape
# ─────────────────────────────────────────────────────────────────────────


# The application stores matches in two shapes:
#
#   1. As JSON dicts in the database (AbstractSchedule.matches column):
#      [{"red": [1,2,3], "blue": [4,5,6],
#        "red_surrogate": [false,false,false],
#        "blue_surrogate": [false,false,false]}, ...]
#
#   2. As app.scheduler.Match NamedTuples (in-memory during SA):
#      Match(red=(1,2,3), blue=(4,5,6),
#            red_surrogate=(False,False,False),
#            blue_surrogate=(False,False,False))
#
# Both shapes are accepted by the helper functions below. The harness
# Match type (with match_num/blue/red, dataclass) is converted only
# when explicitly entering the metrics.py code path.


def _normalize_match(m: Any) -> dict:
    """Coerce any of the three match representations into a uniform
    dict shape this module's internal logic uses.

    Accepts:
      - dict with red/blue/red_surrogate/blue_surrogate (the DB shape)
      - app.scheduler.Match NamedTuple
      - harness_types.Match dataclass
    """
    if isinstance(m, dict):
        return {
            "red":  list(m["red"]),
            "blue": list(m["blue"]),
            "red_surrogate":  list(m.get("red_surrogate",  [False] * len(m["red"]))),
            "blue_surrogate": list(m.get("blue_surrogate", [False] * len(m["blue"]))),
        }
    # Both NamedTuple and dataclass expose the same attribute names.
    return {
        "red":  list(m.red),
        "blue": list(m.blue),
        "red_surrogate":  list(m.red_surrogate)  if m.red_surrogate  else [False] * len(m.red),
        "blue_surrogate": list(m.blue_surrogate) if m.blue_surrogate else [False] * len(m.blue),
    }


def _to_harness_matches(matches: list[Any]) -> list[HarnessMatch]:
    """Convert any-shape match list to the harness Match dataclass list
    that metrics.py expects.
    """
    out: list[HarnessMatch] = []
    for i, m in enumerate(matches, start=1):
        d = _normalize_match(m)
        out.append(HarnessMatch(
            match_num=i,
            blue=d["blue"],
            red=d["red"],
            blue_surrogate=d["blue_surrogate"],
            red_surrogate=d["red_surrogate"],
        ))
    return out


# ─────────────────────────────────────────────────────────────────────────
# Pair / slot / station tables (was inline in the diversity-report endpoint)
# ─────────────────────────────────────────────────────────────────────────


def _build_pair_tables(matches: list[dict], teams: list[int],
                       teams_per_alliance: int) -> dict:
    """Compute the pair / station / surrogate tables used by both the
    headline metrics and the per-slot drill-down.

    `teams` is the list of team identifiers (slot indices 1..N for
    abstract schedules, real team numbers for assigned schedules).
    All team values in `matches` must be in `teams`.

    Output structure: dicts keyed by team identifier rather than
    arrays — this avoids the abstract-vs-assigned schedule ambiguity
    where slot indices 1..N can't share index space with team numbers
    100+.

      {
        "partner":   {team_id: {other_team_id: count}},
        "opponent":  {team_id: {other_team_id: count}},
        "station":   {team_id: [count per position, length 2*tpa]},
        "surrogate": {team_id: count},
        "teams":     [team_id, ...] sorted (caller convenience),
      }
    """
    tpa = teams_per_alliance
    n_stations = 2 * tpa
    teams_set = set(teams)

    # Initialise with zeros for every known team — even teams that
    # never appear in any match (shouldn't happen, but defensive).
    partner   = {t: {u: 0 for u in teams_set if u != t} for t in teams_set}
    opponent  = {t: {u: 0 for u in teams_set if u != t} for t in teams_set}
    station   = {t: [0] * n_stations for t in teams_set}
    surrogate = {t: 0 for t in teams_set}

    for m in matches:
        red = m["red"]
        blue = m["blue"]
        for i, t in enumerate(red):
            if t in teams_set:
                station[t][i] += 1
        for i, t in enumerate(blue):
            if t in teams_set:
                station[t][tpa + i] += 1
        for i, s in enumerate(m["red_surrogate"]):
            if s and red[i] in teams_set:
                surrogate[red[i]] += 1
        for i, s in enumerate(m["blue_surrogate"]):
            if s and blue[i] in teams_set:
                surrogate[blue[i]] += 1
        # Same-alliance pairs (partners)
        for alliance in (red, blue):
            for i in range(len(alliance)):
                for j in range(i + 1, len(alliance)):
                    x, y = alliance[i], alliance[j]
                    if x in teams_set and y in teams_set:
                        partner[x][y] += 1
                        partner[y][x] += 1
        # Cross-alliance pairs (opponents)
        for r in red:
            for b in blue:
                if r in teams_set and b in teams_set:
                    opponent[r][b] += 1
                    opponent[b][r] += 1

    return {
        "partner":   partner,
        "opponent":  opponent,
        "station":   station,
        "surrogate": surrogate,
        "teams":     sorted(teams_set),
    }


def _theoretical_floors(num_teams: int, matches_per_team: int,
                        teams_per_alliance: int) -> dict:
    """Compute the mathematical lower bounds for partner/opponent pair
    counts. A schedule that hits these floors has the structurally
    best possible pair distribution.

    For partners: each slot plays in matches_per_team matches and has
    (teams_per_alliance - 1) partners per match. Total partner-slots
    per team = matches_per_team * (teams_per_alliance - 1). Distributed
    across N - 1 other slots. Floor is ceil(partner_slots / (N-1)).

    For opponents: each slot plays teams_per_alliance opponents per
    match. Total opponent-slots = matches_per_team * teams_per_alliance.
    Floor is ceil(opponent_slots / (N-1)).
    """
    N = num_teams
    if N <= 1:
        return {"partner_floor": 0, "opponent_floor": 0}
    tpa = teams_per_alliance
    partner_slots_per_team  = matches_per_team * (tpa - 1)
    opponent_slots_per_team = matches_per_team * tpa
    return {
        "partner_floor":  math.ceil(partner_slots_per_team / (N - 1)),
        "opponent_floor": math.ceil(opponent_slots_per_team / (N - 1)),
    }


def _pair_histogram(pair_table: dict, teams: list[int],
                    floor: int) -> dict:
    """For one pair table (partner or opponent), produce a histogram and
    worst-pair callouts. `teams` is the sorted list of team ids that
    index into `pair_table`. The worst_pairs entries use the same team
    identifiers — caller can be slot indices or real team numbers.

      - hist: {repeat_count: number_of_pairs}
      - total_pairs: N*(N-1)/2
      - zero_pairs: count of pairs that never meet
      - max: highest repeat count
      - sum: total pair-encounters
      - worst_pairs: list of {slots: [a,b], count: n} above floor,
                     sorted by count desc, top 10. (Field is named
                     "slots" for backward compatibility with the
                     legacy /diversity-report endpoint response shape;
                     the editor's renderDiversityCard depends on it.
                     The values are slot indices for abstract
                     schedules, team numbers for assigned schedules —
                     interpretation is the caller's responsibility.)
    """
    sorted_teams = sorted(teams)
    hist: dict[int, int] = {}
    max_count = 0
    pair_sum = 0
    zero_pairs = 0
    worst: list[dict] = []
    for idx_a, a in enumerate(sorted_teams):
        for b in sorted_teams[idx_a + 1:]:
            c = pair_table[a].get(b, 0)
            hist[c] = hist.get(c, 0) + 1
            pair_sum += c
            if c == 0:
                zero_pairs += 1
            if c > max_count:
                max_count = c
            if c > floor:
                worst.append({"slots": [a, b], "count": c})
    worst.sort(key=lambda x: -x["count"])
    N = len(sorted_teams)
    return {
        "hist":         hist,
        "total_pairs":  (N * (N - 1)) // 2,
        "zero_pairs":   zero_pairs,
        "max":          max_count,
        "sum":          pair_sum,
        "worst_pairs":  worst[:10],
    }


def _slot_table(tables: dict, teams: list[int],
                teams_per_alliance: int) -> list[dict]:
    """Per-slot breakdown: distinct partners, distinct opponents, station
    distribution, surrogate count. One row per team.
    """
    out: list[dict] = []
    for t in sorted(teams):
        partner_row = tables["partner"][t]
        opp_row = tables["opponent"][t]
        distinct_partners  = sum(1 for v in partner_row.values() if v > 0)
        distinct_opponents = sum(1 for v in opp_row.values() if v > 0)
        station_dist = list(tables["station"][t])
        station_max = max(station_dist) if station_dist else 0
        station_min = min(station_dist) if station_dist else 0
        out.append({
            # Field is named "slot" for backward compatibility with the
            # legacy /diversity-report response shape. For abstract
            # schedules this is the slot index; for assigned schedules
            # it's the real team number.
            "slot":               t,
            "distinct_partners":  distinct_partners,
            "distinct_opponents": distinct_opponents,
            "stations":           station_dist,
            "station_spread":     station_max - station_min,
            "surrogates":         tables["surrogate"][t],
        })
    return out


# ─────────────────────────────────────────────────────────────────────────
# DiversityReport — the structure the editor's Quality card consumes today
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class DiversityReport:
    """Structured replacement for the inline /diversity-report response.

    Matches the existing response shape so the editor's renderDiversityCard()
    keeps working. The to_dict() method produces the legacy JSON shape
    exactly; the dataclass fields themselves use clearer names that future
    workstream additions can build on.
    """
    num_teams:           int
    matches_per_team:    int
    teams_per_alliance:  int

    partner_floor:       int
    opponent_floor:      int

    partner_hist:        dict       # {repeat_count: number_of_pairs}
    partner_max:         int
    partner_zero:        int
    partner_sum:         int
    partner_worst:       list[dict] # [{slots:[a,b], count:n}, ...] top 10

    opponent_hist:       dict
    opponent_max:        int
    opponent_zero:       int
    opponent_sum:        int
    opponent_worst:      list[dict]

    total_pairs:         int

    slot_table:          list[dict]
    surrogate_total:     int
    surrogate_concentrated_slots: int  # count of slots with >1 surrogate

    # Optional schedule_id — set when the report came from a stored
    # AbstractSchedule row, so the legacy endpoint response can echo it
    # back. None for ad-hoc reports.
    schedule_id:         int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Render as the JSON shape the existing diversity-report endpoint
        returns. Frontend renderDiversityCard() consumes this shape — the
        key names (partner.histogram, partner.average, stations,
        max_per_slot, slots[].max_partners, slots[].station_imbalance,
        slots[].surrogate_count) are load-bearing and must not drift.

        Frontend reference: static/index.html renderDiversityCard().
        """
        avg_partner = self.partner_sum / self.total_pairs if self.total_pairs else 0.0
        avg_opponent = self.opponent_sum / self.total_pairs if self.total_pairs else 0.0

        # Translate per-slot rows to the legacy field names. The
        # dataclass uses cleaner names (station_spread, surrogates);
        # the endpoint shape uses station_imbalance / surrogate_count /
        # max_partners / max_opponents. Keep both alive in the JSON for
        # one release so the rename is staged, then drop the legacy
        # aliases once the frontend migrates.
        max_partners_per_slot  = 2 * self.matches_per_team
        max_opponents_per_slot = (self.teams_per_alliance) * self.matches_per_team
        slots_payload = []
        for row in self.slot_table:
            slots_payload.append({
                "slot":               row["slot"],
                "distinct_partners":  row["distinct_partners"],
                "distinct_opponents": row["distinct_opponents"],
                "max_partners":       max_partners_per_slot,
                "max_opponents":      max_opponents_per_slot,
                "stations":           row["stations"],
                "station_imbalance":  row["station_spread"],
                "surrogate_count":    row["surrogates"],
            })

        # Compute the station summary block at this layer rather than
        # asking the caller to do it.
        max_station_imbalance = max(
            (row["station_spread"] for row in self.slot_table),
            default=0,
        )
        imbalanced_slots = sum(
            1 for row in self.slot_table if row["station_spread"] > 1
        )
        max_surrogate_per_slot = max(
            (row["surrogates"] for row in self.slot_table),
            default=0,
        )

        result: dict[str, Any] = {
            "num_teams":        self.num_teams,
            "matches_per_team": self.matches_per_team,
            "total_pairs":      self.total_pairs,
            "partner": {
                "histogram":   self.partner_hist,
                "max":         self.partner_max,
                "floor":       self.partner_floor,
                "average":     round(avg_partner, 3),
                "zero_pairs":  self.partner_zero,
                "worst_pairs": self.partner_worst,
            },
            "opponent": {
                "histogram":   self.opponent_hist,
                "max":         self.opponent_max,
                "floor":       self.opponent_floor,
                "average":     round(avg_opponent, 3),
                "zero_pairs":  self.opponent_zero,
                "worst_pairs": self.opponent_worst,
            },
            "stations": {
                "max_imbalance":    max_station_imbalance,
                "imbalanced_slots": imbalanced_slots,
            },
            "surrogates": {
                "total":              self.surrogate_total,
                "max_per_slot":       max_surrogate_per_slot,
                "concentrated_slots": self.surrogate_concentrated_slots,
            },
            "slots": slots_payload,
        }
        if self.schedule_id is not None:
            result["schedule_id"] = self.schedule_id
        return result


def compute_diversity_report(matches: list[Any], num_teams: int,
                             matches_per_team: int,
                             teams_per_alliance: int = 3,
                             team_numbers: list[int] | None = None,
                             ) -> DiversityReport:
    """Compute the full diversity report.

    Accepts matches in any of the three shapes (DB dict, scheduler
    NamedTuple, harness dataclass). The teams_per_alliance defaults to
    3 for FRC backward-compat.

    If `team_numbers` is provided, those are the team identifiers the
    pair tables are keyed by (typical for assigned schedules where
    matches use real team numbers). If not provided, the function
    derives the team set from the matches themselves (typical for
    abstract schedules where teams are slot indices 1..N).
    """
    normalized = [_normalize_match(m) for m in matches]

    # Derive the team set from the matches if not given. For abstract
    # schedules these will be slot indices 1..N; for assigned schedules
    # they'll be real team numbers.
    if team_numbers:
        teams_list = list(team_numbers)
    else:
        teams_set: set[int] = set()
        for m in normalized:
            teams_set.update(m["red"])
            teams_set.update(m["blue"])
        teams_list = sorted(teams_set)

    tables = _build_pair_tables(normalized, teams_list, teams_per_alliance)
    floors = _theoretical_floors(num_teams, matches_per_team, teams_per_alliance)
    partner_h  = _pair_histogram(tables["partner"],  teams_list, floors["partner_floor"])
    opponent_h = _pair_histogram(tables["opponent"], teams_list, floors["opponent_floor"])
    slot_rows  = _slot_table(tables, teams_list, teams_per_alliance)
    surrogate_total = sum(tables["surrogate"].values())
    concentrated   = sum(1 for s in tables["surrogate"].values() if s > 1)

    return DiversityReport(
        num_teams=num_teams,
        matches_per_team=matches_per_team,
        teams_per_alliance=teams_per_alliance,
        partner_floor=floors["partner_floor"],
        opponent_floor=floors["opponent_floor"],
        partner_hist=partner_h["hist"],
        partner_max=partner_h["max"],
        partner_zero=partner_h["zero_pairs"],
        partner_sum=partner_h["sum"],
        partner_worst=partner_h["worst_pairs"],
        opponent_hist=opponent_h["hist"],
        opponent_max=opponent_h["max"],
        opponent_zero=opponent_h["zero_pairs"],
        opponent_sum=opponent_h["sum"],
        opponent_worst=opponent_h["worst_pairs"],
        total_pairs=partner_h["total_pairs"],
        slot_table=slot_rows,
        surrogate_total=surrogate_total,
        surrogate_concentrated_slots=concentrated,
    )


# ─────────────────────────────────────────────────────────────────────────
# Threshold-classified metrics (delegates to the harness analyzer)
# ─────────────────────────────────────────────────────────────────────────


def analyze_against_thresholds(matches: list[Any], num_teams: int,
                                matches_per_team: int,
                                teams_per_alliance: int = 3,
                                team_numbers: list[int] | None = None,
                                fixture_id: str = "ad-hoc",
                                adapter_name: str = "frc-scheduler-server",
                                cooldown: int | None = None,
                                ) -> AnalysisReport:
    """Run every threshold-based metric against the harness analyzer.

    Returns the same AnalysisReport shape the eval harness produces, but
    accepts application-friendly inputs (lists of match dicts/tuples plus
    fixture parameters) instead of requiring harness Schedule/Fixture
    objects.

    When team_numbers is None, the matches are assumed to already use
    real team numbers (the typical case for assigned schedules). For
    abstract schedules where matches are slot-indexed, pass team_numbers
    as the list of real team identifiers in slot order, or leave None
    if you want the slot indices themselves treated as team numbers
    (the analyzer doesn't care about identity beyond uniqueness).

    When `cooldown` is provided, the returned report's
    `is_valid_paramount` reflects whether the schedule satisfies FRC
    §10.5.2's paramount cooldown rule (any gap < cooldown → invalid
    output). When None (default), the legacy behavior is preserved —
    the report's `is_valid_paramount` is None and composite scoring
    doesn't reject the schedule. See Phase 1 F1-e for methodology
    rationale.
    """
    harness_matches = _to_harness_matches(matches)
    # Build the fixture's teams list. For an abstract schedule (no team
    # identity), the slot indices 1..N work fine.
    teams = team_numbers if team_numbers else list(range(1, num_teams + 1))
    fixture = HarnessFixture(
        fixture_id=fixture_id,
        name=fixture_id,
        teams=teams,
        matches_per_team=matches_per_team,
        teams_per_alliance=teams_per_alliance,
        cooldown=cooldown,
    )
    schedule = HarnessSchedule(
        fixture_id=fixture_id,
        adapter_name=adapter_name,
        matches=harness_matches,
    )
    return analyze_harness_schedule(schedule, fixture)


# ─────────────────────────────────────────────────────────────────────────
# Composite score
# ─────────────────────────────────────────────────────────────────────────


def composite_score(report: AnalysisReport) -> float:
    """Compute a single composite score from a threshold-classified report.

    Lower is better. 0 means every metric near-optimal; ~110 means every
    metric poor. Matches the formula the eval harness uses in its report
    summary (scripts/scheduler_eval/runner.py). Kept in this module so
    the abstract-library workstream can rank entries by composite without
    pulling in the runner.

    Per-metric contribution (weight 10):
        near_optimal → 0.5
        acceptable   → 3.0
        poor         → 10.0
        descriptive  → 0 (informational only)

    Paramount-cooldown handling (per Phase 1 F1-e): when the report's
    `is_valid_paramount` is explicitly False, return `inf`. Schedules
    that violate FRC §10.5.2 paramount cooldown are invalid output, not
    low-quality output, and shouldn't be ranked alongside valid
    schedules. None (legacy, no cooldown declared in fixture) preserves
    the old behavior; True is the standard score.
    """
    if getattr(report, "is_valid_paramount", None) is False:
        return float("inf")
    total = 0.0
    for m in report.metrics.values():
        c = m.classification
        if c == "poor":
            total += 10.0
        elif c == "acceptable":
            total += 3.0
        elif c == "near_optimal":
            total += 0.5
        # descriptive contributes 0
    return total


# ─────────────────────────────────────────────────────────────────────────
# Public entry points
# ─────────────────────────────────────────────────────────────────────────


__all__ = [
    # Re-exports from metrics.py — callers that already know the harness
    # API can keep using these.
    "THRESHOLDS",
    "Threshold",
    "MetricResult",
    "AnalysisReport",
    # Application-friendly entry points.
    "DiversityReport",
    "compute_diversity_report",
    "analyze_against_thresholds",
    "composite_score",
]
