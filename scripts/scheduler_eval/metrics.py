"""Metrics module — analyzes a Schedule and produces quality measurements.

Every metric is implemented as a standalone function taking (Schedule,
Fixture) and returning a structured result. The `analyze` convenience
function runs all of them and returns a complete report.

Two-tier threshold system:

  - "FRC-acceptable" thresholds reflect what the FRC community considers
    minimum-acceptable quality. Schedules below these thresholds are
    problematic and would draw complaints.

  - "Near-optimal" thresholds reflect what good schedulers (MatchMaker
    after the Sykes algorithm landed) routinely achieve. Schedules
    that hit these thresholds are competitive with the best available.

Metrics are defined for qualification matches only. Practice matches
don't count. Surrogate slot-fills are tracked but excluded from
repeat-partner / repeat-opponent statistics — a surrogate is filling
in for capacity, not playing a competitive match.

Cross-checked against MatchRater output where MatchRater computes the
same metric. Where metrics disagree with MatchRater on test inputs,
the metric is wrong and gets fixed; MatchRater is the reference.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from itertools import combinations
from typing import Any

from .harness_types import Fixture, Match, Schedule


# ── Threshold configuration ─────────────────────────────────────────────


@dataclass(frozen=True)
class Threshold:
    """A single metric's acceptability bands.

    `lower_is_better` controls how the comparison works. For most
    metrics (repeat partners, max imbalance) lower is better; for a
    few (e.g. teams hitting near-optimal counts) higher is better.
    """
    name:           str
    lower_is_better: bool
    acceptable:     float       # threshold for "FRC-acceptable"
    near_optimal:   float       # threshold for "near-optimal"
    units:          str = ""

    def classify(self, value: float) -> str:
        """Returns 'near_optimal', 'acceptable', or 'poor'."""
        if self.lower_is_better:
            if value <= self.near_optimal:
                return "near_optimal"
            if value <= self.acceptable:
                return "acceptable"
            return "poor"
        else:
            if value >= self.near_optimal:
                return "near_optimal"
            if value >= self.acceptable:
                return "acceptable"
            return "poor"


# Thresholds calibrated from the reviewer's MatchMaker analysis (800
# runs, 36-team field) and FRC community norms. These are starting
# points; refinement is expected as we run on more fixtures.
THRESHOLDS: dict[str, Threshold] = {
    # --- Pairing diversity ---
    "repeat_partners":      Threshold("repeat partner pairs",   True,  acceptable=2,  near_optimal=0,  units="pairs"),
    "max_partner_repeats":  Threshold("max times any pair partners", True, acceptable=2, near_optimal=1, units="times"),
    "repeat_opponents":     Threshold("repeat opponent pairs",  True,  acceptable=27, near_optimal=20, units="pairs"),
    "max_opponent_repeats": Threshold("max times any pair opposes", True, acceptable=2, near_optimal=2, units="times"),

    # --- Color and station balance ---
    "max_color_imbalance":  Threshold("worst red/blue imbalance", True, acceptable=2,  near_optimal=1,  units="matches"),
    "teams_with_5_2_color": Threshold("teams with 5+ on one color", True, acceptable=0, near_optimal=0, units="teams"),
    "max_station_spread":   Threshold("worst driver-station spread", True, acceptable=1,  near_optimal=1,  units="positions"),

    # --- Timing ---
    "min_match_gap":        Threshold("shortest gap between matches", False, acceptable=4, near_optimal=4, units="matches"),
    "back_to_back_matches": Threshold("back-to-back match count",   True, acceptable=0,  near_optimal=0,  units="instances"),

    # --- Surrogate ---
    "surrogate_count":      Threshold("surrogate matches count",    True, acceptable=0,  near_optimal=0,  units="instances"),
}


# ── Result containers ───────────────────────────────────────────────────


@dataclass
class MetricResult:
    """One metric's output. `value` is the headline number; `detail`
    is structured per-team or per-pair data the reports can drill into."""
    name:           str
    value:          float
    classification: str          # 'near_optimal', 'acceptable', 'poor', 'descriptive'
    units:          str = ""
    detail:         Any = None
    notes:          str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Detail can be complex; let it serialize via json passthrough
        return d


@dataclass
class AnalysisReport:
    """All metrics for a single Schedule, plus aggregate roll-up."""
    fixture_id:    str
    adapter_name:  str
    metrics:       dict[str, MetricResult] = field(default_factory=dict)
    overall:       str = ""    # 'near_optimal', 'acceptable', 'poor'
    counts:        dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture_id":   self.fixture_id,
            "adapter_name": self.adapter_name,
            "metrics":      {k: v.to_dict() for k, v in self.metrics.items()},
            "overall":      self.overall,
            "counts":       self.counts,
        }


# ── Metric implementations ──────────────────────────────────────────────


def _team_match_index(schedule: Schedule) -> dict[int, list[Match]]:
    """team_number -> list of Matches (in match_num order)."""
    out: dict[int, list[Match]] = defaultdict(list)
    for m in schedule.matches:
        for t in m.all_teams:
            out[t].append(m)
    for t in out:
        out[t].sort(key=lambda m: m.match_num)
    return out


def repeat_partners(schedule: Schedule, fixture: Fixture) -> tuple[MetricResult, MetricResult]:
    """Pairs of teams that partner more than once.

    Returns two metrics:
      - count of distinct pairs that partner ≥2 times
      - max times any single pair partners

    Surrogate slot-fills are excluded — a surrogate filling in for
    capacity isn't a competitive partnership.
    """
    pair_counts: Counter[tuple[int, int]] = Counter()
    for m in schedule.matches:
        for color in ("blue", "red"):
            alliance     = getattr(m, color)
            surrogates   = getattr(m, f"{color}_surrogate")
            non_surrogate_teams = [
                alliance[i] for i in range(len(alliance)) if not surrogates[i]
            ]
            for a, b in combinations(sorted(non_surrogate_teams), 2):
                pair_counts[(a, b)] += 1

    repeats = {pair: n for pair, n in pair_counts.items() if n >= 2}
    detail = sorted(repeats.items(), key=lambda kv: (-kv[1], kv[0]))
    max_repeats = max(repeats.values()) if repeats else 1

    count_metric = MetricResult(
        name="repeat_partners",
        value=len(repeats),
        classification=THRESHOLDS["repeat_partners"].classify(len(repeats)),
        units="pairs",
        detail=[{"teams": list(p), "count": n} for p, n in detail],
    )
    max_metric = MetricResult(
        name="max_partner_repeats",
        value=max_repeats,
        classification=THRESHOLDS["max_partner_repeats"].classify(max_repeats),
        units="times",
        detail=detail[0] if detail else None,
    )
    return count_metric, max_metric


def repeat_opponents(schedule: Schedule, fixture: Fixture) -> tuple[MetricResult, MetricResult]:
    """Pairs of teams that face each other more than once.

    Returns two metrics:
      - count of distinct pairs that face ≥2 times
      - max times any single pair faces

    Surrogate slot-fills are excluded.
    """
    pair_counts: Counter[tuple[int, int]] = Counter()
    for m in schedule.matches:
        blue_active = [m.blue[i] for i in range(len(m.blue)) if not m.blue_surrogate[i]]
        red_active  = [m.red[i]  for i in range(len(m.red))  if not m.red_surrogate[i]]
        for b in blue_active:
            for r in red_active:
                pair = tuple(sorted([b, r]))
                pair_counts[pair] += 1

    repeats = {pair: n for pair, n in pair_counts.items() if n >= 2}
    detail = sorted(repeats.items(), key=lambda kv: (-kv[1], kv[0]))
    max_repeats = max(repeats.values()) if repeats else 1

    count_metric = MetricResult(
        name="repeat_opponents",
        value=len(repeats),
        classification=THRESHOLDS["repeat_opponents"].classify(len(repeats)),
        units="pairs",
        detail=[{"teams": list(p), "count": n} for p, n in detail],
    )
    max_metric = MetricResult(
        name="max_opponent_repeats",
        value=max_repeats,
        classification=THRESHOLDS["max_opponent_repeats"].classify(max_repeats),
        units="times",
        detail=detail[0] if detail else None,
    )
    return count_metric, max_metric


def color_balance(schedule: Schedule, fixture: Fixture) -> tuple[MetricResult, MetricResult]:
    """Per-team red/blue alliance count.

    Returns:
      - max color imbalance across all teams (worst delta)
      - count of teams with 5+ matches on one color (assuming 7 total;
        the threshold scales with matches_per_team)

    Surrogate slot-fills count toward color balance because the team
    physically plays from that alliance station even when filling in.
    """
    color_counts: dict[int, dict[str, int]] = defaultdict(lambda: {"blue": 0, "red": 0})
    for m in schedule.matches:
        for t in m.blue:
            color_counts[t]["blue"] += 1
        for t in m.red:
            color_counts[t]["red"] += 1

    max_imbalance = 0
    teams_5_plus  = 0
    detail = []
    # "5+" threshold is for 7-match schedules; scale by matches_per_team
    high_threshold = max(5, fixture.matches_per_team - 2)
    for t, c in color_counts.items():
        delta = abs(c["blue"] - c["red"])
        max_imbalance = max(max_imbalance, delta)
        if max(c["blue"], c["red"]) >= high_threshold:
            teams_5_plus += 1
        detail.append({"team": t, "blue": c["blue"], "red": c["red"], "delta": delta})
    detail.sort(key=lambda d: -d["delta"])

    return (
        MetricResult(
            name="max_color_imbalance",
            value=max_imbalance,
            classification=THRESHOLDS["max_color_imbalance"].classify(max_imbalance),
            units="matches",
            detail=detail[:10],  # top 10 worst
        ),
        MetricResult(
            name="teams_with_5_2_color",
            value=teams_5_plus,
            classification=THRESHOLDS["teams_with_5_2_color"].classify(teams_5_plus),
            units="teams",
            detail=[d for d in detail if max(d["blue"], d["red"]) >= high_threshold],
            notes=f"threshold for 'high' is {high_threshold}+ matches on one color "
                  f"(out of {fixture.matches_per_team})",
        ),
    )


def station_spread(schedule: Schedule, fixture: Fixture) -> MetricResult:
    """Per-team driver-station distribution.

    Returns max spread (max station count - min station count) across
    all teams. The Sykes algorithm in MatchMaker guarantees spread of
    1 for typical fixtures, so any value > 1 indicates a real defect.

    Surrogate slot-fills count toward station presence — the team is
    physically at that station regardless.
    """
    station_counts: dict[int, Counter[int]] = defaultdict(Counter)
    for m in schedule.matches:
        for color in ("blue", "red"):
            alliance = getattr(m, color)
            for pos, team in enumerate(alliance, start=1):
                station_counts[team][pos] += 1

    max_spread = 0
    detail = []
    for t in sorted(station_counts.keys()):
        counts_list = [station_counts[t].get(p, 0) for p in range(1, fixture.teams_per_alliance + 1)]
        spread = max(counts_list) - min(counts_list)
        max_spread = max(max_spread, spread)
        detail.append({"team": t, "stations": counts_list, "spread": spread})
    detail.sort(key=lambda d: -d["spread"])

    return MetricResult(
        name="max_station_spread",
        value=max_spread,
        classification=THRESHOLDS["max_station_spread"].classify(max_spread),
        units="positions",
        detail=detail[:10],
    )


def match_gap(schedule: Schedule, fixture: Fixture) -> tuple[MetricResult, MetricResult]:
    """Minimum gap between consecutive matches per team.

    Returns:
      - global minimum gap across all teams
      - count of back-to-back instances (gap == 1)
    """
    team_idx = _team_match_index(schedule)
    min_gap = None
    back_to_back = 0
    detail = []
    for t, matches in team_idx.items():
        if len(matches) < 2:
            continue
        nums = [m.match_num for m in matches]
        gaps = [nums[i+1] - nums[i] for i in range(len(nums)-1)]
        team_min = min(gaps)
        if min_gap is None or team_min < min_gap:
            min_gap = team_min
        b2b = sum(1 for g in gaps if g == 1)
        back_to_back += b2b
        if team_min <= 3 or b2b > 0:
            detail.append({"team": t, "matches": nums, "gaps": gaps, "min_gap": team_min, "back_to_back": b2b})
    detail.sort(key=lambda d: (d["min_gap"], -d["back_to_back"]))

    return (
        MetricResult(
            name="min_match_gap",
            value=min_gap if min_gap is not None else 0,
            classification=THRESHOLDS["min_match_gap"].classify(min_gap or 0),
            units="matches",
            detail=detail[:10],
        ),
        MetricResult(
            name="back_to_back_matches",
            value=back_to_back,
            classification=THRESHOLDS["back_to_back_matches"].classify(back_to_back),
            units="instances",
            detail=[d for d in detail if d["back_to_back"] > 0],
        ),
    )


def surrogate_count(schedule: Schedule, fixture: Fixture) -> MetricResult:
    """Total surrogate slot-fills."""
    n = sum(
        sum(m.blue_surrogate) + sum(m.red_surrogate)
        for m in schedule.matches
    )
    return MetricResult(
        name="surrogate_count",
        value=n,
        classification="descriptive",  # informational, not pass/fail per se
        units="instances",
        detail=None,
    )


def matches_per_team_distribution(schedule: Schedule, fixture: Fixture) -> MetricResult:
    """Sanity check: every team plays exactly fixture.matches_per_team."""
    counts = Counter()
    for m in schedule.matches:
        for t in m.all_teams:
            counts[t] += 1

    distribution = Counter(counts.values())
    expected = fixture.matches_per_team
    is_correct = all(c == expected for c in counts.values())
    notes = ""
    if not is_correct:
        notes = (f"expected {expected} matches per team; got distribution {dict(distribution)}")

    return MetricResult(
        name="matches_per_team",
        value=expected,
        classification="near_optimal" if is_correct else "poor",
        units="matches",
        detail=dict(distribution),
        notes=notes,
    )


# ── Aggregate analyzer ──────────────────────────────────────────────────


def analyze(schedule: Schedule, fixture: Fixture) -> AnalysisReport:
    """Run every metric and return a structured report."""
    report = AnalysisReport(
        fixture_id=schedule.fixture_id,
        adapter_name=schedule.adapter_name,
    )

    rp_count, rp_max = repeat_partners(schedule, fixture)
    ro_count, ro_max = repeat_opponents(schedule, fixture)
    color_max, color_5plus = color_balance(schedule, fixture)
    station = station_spread(schedule, fixture)
    gap_min, b2b = match_gap(schedule, fixture)
    surrogates = surrogate_count(schedule, fixture)
    mpt = matches_per_team_distribution(schedule, fixture)

    metrics = [rp_count, rp_max, ro_count, ro_max, color_max, color_5plus,
               station, gap_min, b2b, surrogates, mpt]
    for m in metrics:
        report.metrics[m.name] = m

    # Aggregate roll-up — count classifications. Overall is the worst.
    counts = Counter(m.classification for m in metrics)
    report.counts = dict(counts)
    if counts.get("poor", 0) > 0:
        report.overall = "poor"
    elif counts.get("acceptable", 0) > 0:
        report.overall = "acceptable"
    else:
        report.overall = "near_optimal"

    return report
