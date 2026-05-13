# SPDX-License-Identifier: GPL-3.0-or-later
# FRC Match Scheduler
# Copyright (C) 2025 FRC Match Scheduler Contributors
"""Theoretical floors for schedule-quality metrics.

For any FRC fixture shape `(n, MPT, tpa, cooldown)`, this module
computes lower bounds for each schedule-quality metric. The bounds
are **mathematical lower bounds** — no schedule can score better
than these. Whether the bound is *achievable* by a real schedule is
a separate question that varies by metric:

  - Some bounds are **trivially achievable** by inspection
    (cooldown_violations = 0 if cooldown ≤ cooldown_max; surrogate
    count = the structurally-required minimum).
  - Some bounds are **proven achievable** by combinatorial design
    theory (e.g., resolvable balanced incomplete block designs
    when (n, MPT, tpa) parameters match a known design).
  - Some bounds are **proven lower bounds whose achievability is
    unknown** (the count-floor for par_quad/opp_quad is a strict
    lower bound, but additional schedule-structure constraints can
    push the achievable minimum higher).

For each floor returned by this module, the `Floor` object carries
a `confidence` label that distinguishes these cases:

  - 'proven_optimal':   floor IS the achievable minimum (no schedule
                         can match or beat it)
  - 'proven_lower_bound': floor is a strict lower bound; achievability
                         is unknown without further analysis
  - 'best_known':       floor is the best minimum observed; the
                         true mathematical minimum may be lower

The module is the single source of truth for floors used by the
scoring framework. Callers should treat floors with caution
depending on the confidence label.

See `docs/scheduler/quality-floors.md` for the math derivations and
proof sketches for each floor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Any


# ── Confidence labels ────────────────────────────────────────────────────


CONFIDENCE_PROVEN_OPTIMAL    = 'proven_optimal'
CONFIDENCE_PROVEN_LOWER      = 'proven_lower_bound'
CONFIDENCE_BEST_KNOWN        = 'best_known'


# ── Floor result containers ──────────────────────────────────────────────


@dataclass
class Floor:
    """A single metric's theoretical floor + confidence."""
    metric:     str
    value:      float | int
    confidence: str
    proof_note: str
    units:      str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FixtureFloors:
    """Complete floor catalog for a fixture shape.

    Every quality metric tracked by the scheduler has a floor here.
    """
    # Fixture shape inputs
    n_teams:            int
    matches_per_team:   int
    teams_per_alliance: int
    cooldown:           int

    # Derived structural quantities
    total_matches:      int
    needs_surrogate:    bool
    surrogate_count:    int
    cooldown_max:       int
    feasible:           bool

    # Floors per metric (each a Floor object)
    floors: dict[str, Floor]

    def to_dict(self) -> dict[str, Any]:
        return {
            'n_teams':            self.n_teams,
            'matches_per_team':   self.matches_per_team,
            'teams_per_alliance': self.teams_per_alliance,
            'cooldown':           self.cooldown,
            'total_matches':      self.total_matches,
            'needs_surrogate':    self.needs_surrogate,
            'surrogate_count':    self.surrogate_count,
            'cooldown_max':       self.cooldown_max,
            'feasible':           self.feasible,
            'floors':             {k: v.to_dict() for k, v in self.floors.items()},
        }


# ── Floor derivations ────────────────────────────────────────────────────


def _cooldown_max(n_teams: int, matches_per_team: int,
                  teams_per_alliance: int) -> int:
    """Largest cooldown the fixture can mathematically tolerate.

    Per Q5 derivation (`docs/scheduler/phase1-q5-cooldown-feasibility.md`):

        M = ceil(n * MPT / (2 * tpa))   # total matches
        cooldown_max = floor((M - 1) / (MPT - 1))

    A schedule with cooldown > cooldown_max has no feasible solution
    (some team would need to play too soon after its previous match).

    Proven via pigeonhole: each of MPT appearances for a team must be
    in distinct matches; gaps of at least cooldown require the team's
    last appearance to be in match >= (MPT-1)*cooldown + 1, which
    cannot exceed M.
    """
    if matches_per_team < 2:
        return n_teams * matches_per_team  # trivial
    total_slots    = n_teams * matches_per_team
    slots_per_match = 2 * teams_per_alliance
    M = math.ceil(total_slots / slots_per_match)
    return (M - 1) // (matches_per_team - 1)


def _surrogate_count_floor(n_teams: int, matches_per_team: int,
                            teams_per_alliance: int) -> tuple[int, int, bool]:
    """Minimum surrogate slot-fills required.

    Per FRC convention, when n * MPT is not divisible by 2 * tpa, some
    teams play an extra match to fill the schedule's match count up to
    the next integer. Each surrogate appearance is one team-match slot.

    Number of surrogate slots = total_match_slots - n * MPT
        where total_match_slots = ceil(n*MPT / (2*tpa)) * (2*tpa)

    Proven by arithmetic.
    """
    total_slots     = n_teams * matches_per_team
    slots_per_match = 2 * teams_per_alliance
    M               = math.ceil(total_slots / slots_per_match)
    surrogate_slots = M * slots_per_match - total_slots
    needs_surrogate = surrogate_slots > 0
    return surrogate_slots, M, needs_surrogate


def _color_balance_per_team_floor(matches_per_team: int) -> int:
    """Minimum |red_count - blue_count| achievable per team.

    Each team plays MPT matches across two color labels (red, blue).
    The closest-to-balanced split is:
        - MPT even: (MPT/2, MPT/2), diff = 0
        - MPT odd:  ((MPT-1)/2 or (MPT+1)/2 split), diff = 1

    Proven by pigeonhole.
    """
    return 0 if matches_per_team % 2 == 0 else 1


def _station_per_team_floor(matches_per_team: int) -> int:
    """Minimum max-min spread across the 6 station-color positions.

    Each team's appearances distribute across {R1, R2, R3, B1, B2, B3}.
    If MPT is divisible by 6, perfect even distribution gives spread=0.
    Otherwise, some positions get floor(MPT/6) and some get ceil(MPT/6),
    giving spread=1.

    Proven by pigeonhole.

    Note: this is per-team optimum. Whether ALL teams can simultaneously
    achieve their per-team optimum is a combinatorial-design question
    and may not always be achievable.
    """
    return 0 if matches_per_team % 6 == 0 else 1


def _pair_count_floors(n_teams: int, matches_per_team: int,
                        teams_per_alliance: int,
                        which: str) -> dict[str, int]:
    """Lower bound for per-pair partner OR opponent encounter counts.

    Each team plays MPT matches:
        partner slots per team = MPT * (tpa - 1)
        opponent slots per team = MPT * tpa

    Total unordered pair-encounters across all (team, match) pairs:
        partners: n * MPT * (tpa - 1) / 2
        opponents: n * MPT * tpa / 2

    Distributed over C(n, 2) = n*(n-1)/2 unique pairs.

    Average per pair (call it avg):
        partner_avg  = (MPT * (tpa - 1)) / (n - 1)
        opponent_avg = (MPT * tpa) / (n - 1)

    Floor for each pair: floor(avg). Ceil for each pair: ceil(avg).
    The distribution that minimizes Σx_i² (the par_quad / opp_quad
    metric) is: r pairs at ceil, (total_pairs - r) at floor, where
    r is chosen to satisfy Σ x_i = total encounters.

    Specifically: r = total_encounters - floor * total_pairs.

    Proven via convexity of x → x² (Jensen's inequality argument):
    redistributing any unit from a higher-count pair to a lower-count
    pair never increases Σx², and the redistributed minimum is when
    counts are as equal as possible.

    NOTE: this is the *count distribution* lower bound. The achievable
    minimum par_quad/opp_quad may be HIGHER if additional schedule-
    structure constraints (cooldown, station, color, etc.) preclude
    that count distribution being realized in an actual round-robin.

    Returns dict with: avg, count_floor, count_ceil, total_encounters,
    total_pairs, quad_floor.
    """
    if n_teams < 2 or matches_per_team < 1:
        return {
            'avg':              0.0,
            'count_floor':      0,
            'count_ceil':       0,
            'total_encounters': 0,
            'total_pairs':      0,
            'quad_floor':       0,
        }
    if which == 'partner':
        slots_per_team = matches_per_team * (teams_per_alliance - 1)
    elif which == 'opponent':
        slots_per_team = matches_per_team * teams_per_alliance
    else:
        raise ValueError(f"which must be 'partner' or 'opponent', got {which!r}")

    total_pairs       = n_teams * (n_teams - 1) // 2
    # total_encounters: each match contributes (tpa choose 2) partner-pairs and
    # tpa*tpa opponent-pairs. Across all matches, summed over teams it equals
    # n * slots_per_team / 2.
    total_encounters  = n_teams * slots_per_team // 2
    if total_pairs == 0:
        return {
            'avg': 0.0, 'count_floor': 0, 'count_ceil': 0,
            'total_encounters': 0, 'total_pairs': 0, 'quad_floor': 0,
        }

    avg          = total_encounters / total_pairs
    count_floor  = math.floor(avg)
    count_ceil   = math.ceil(avg)
    F            = count_floor
    r            = total_encounters - F * total_pairs   # number of pairs at F+1

    # Sum of squares under minimum-variance distribution
    quad_floor = r * (F + 1)**2 + (total_pairs - r) * F**2

    return {
        'avg':              avg,
        'count_floor':      count_floor,
        'count_ceil':       count_ceil,
        'total_encounters': total_encounters,
        'total_pairs':      total_pairs,
        'quad_floor':       quad_floor,
    }


# ── Top-level entry ──────────────────────────────────────────────────────


def fixture_floors(n_teams: int, matches_per_team: int,
                   teams_per_alliance: int = 3,
                   cooldown: int = 2) -> FixtureFloors:
    """Compute every theoretical floor for a fixture shape.

    Returns a `FixtureFloors` object with structural metadata (total
    matches, surrogate count, cooldown feasibility) and a `floors`
    dict of `Floor` objects keyed by metric name.

    Metrics covered:
        - cooldown_violations
        - surrogate_count
        - color_per_team       (per-team |red - blue| max)
        - station_per_team     (per-team max-min spread across 6 positions)
        - partner_pair_count_floor    (basic count for any single pair)
        - partner_quad         (sum of partner-pair count²)
        - opponent_pair_count_floor   (basic count for any single pair)
        - opponent_quad        (sum of opponent-pair count²)

    Each floor object has a `confidence` label indicating whether the
    floor is `proven_optimal` (provably achievable), `proven_lower_bound`
    (provably a lower bound, but achievability unknown), or `best_known`
    (the best value seen empirically; true minimum may be lower).

    See `docs/scheduler/quality-floors.md` for math + proof sketches.
    """
    # Structural quantities
    surrogate_count, total_matches, needs_surrogate = _surrogate_count_floor(
        n_teams, matches_per_team, teams_per_alliance
    )
    cd_max   = _cooldown_max(n_teams, matches_per_team, teams_per_alliance)
    feasible = cooldown <= cd_max

    # Build per-metric floors
    floors: dict[str, Floor] = {}

    # FRC #1: cooldown_violations
    # A schedule satisfying cooldown ≤ cooldown_max can have 0 violations.
    # If cooldown > cooldown_max, no schedule is feasible. We still report
    # 0 as the "floor" but feasible=False makes it moot.
    floors['cooldown_violations'] = Floor(
        metric='cooldown_violations',
        value=0,
        confidence=CONFIDENCE_PROVEN_OPTIMAL,
        proof_note=(
            "Floor is 0 by inspection: a schedule satisfies the cooldown "
            "constraint iff every team-gap is ≥ cooldown. The Q5 cooldown_max "
            "formula determines whether any schedule can achieve 0 violations; "
            "for cooldown ≤ cooldown_max the floor is achievable."
        ),
        units='violations',
    )

    # FRC #2: par_quad (sum of partner-pair count²)
    partner = _pair_count_floors(n_teams, matches_per_team, teams_per_alliance, 'partner')
    # Confidence: proven lower bound (the count distribution is the optimum
    # in the unconstrained case). Whether achievable under cooldown +
    # other constraints is unclear.
    par_confidence = CONFIDENCE_PROVEN_LOWER
    par_proof = (
        f"Partner-pair encounters total {partner['total_encounters']} across "
        f"{partner['total_pairs']} unique pairs (n*(n-1)/2). Average is "
        f"{partner['avg']:.4f}. Sum-of-squares is minimized when counts are "
        f"as even as possible: {partner['count_ceil']} pairs at floor+1 vs "
        f"{partner['total_pairs'] - (partner['total_encounters'] - partner['count_floor'] * partner['total_pairs'])} "
        f"at floor. Proof via convexity of x → x²; redistributing any unit from "
        f"a high-count pair to a low-count pair never increases the sum. "
        f"Achievability under structural constraints (cooldown, station, etc.) "
        f"may push the realized minimum higher."
    )
    floors['par_quad'] = Floor(
        metric='par_quad',
        value=partner['quad_floor'],
        confidence=par_confidence,
        proof_note=par_proof,
        units='sum of squares',
    )
    floors['partner_pair_count'] = Floor(
        metric='partner_pair_count',
        value=partner['count_floor'],
        confidence=CONFIDENCE_PROVEN_OPTIMAL,
        proof_note=(
            f"At least one pair must encounter another ≥ floor({partner['avg']:.4f}) "
            f"= {partner['count_floor']} times by pigeonhole."
        ),
        units='encounters',
    )

    # FRC #3: opp_quad (sum of opponent-pair count²)
    opp = _pair_count_floors(n_teams, matches_per_team, teams_per_alliance, 'opponent')
    opp_proof = (
        f"Opponent-pair encounters total {opp['total_encounters']} across "
        f"{opp['total_pairs']} pairs. Average is {opp['avg']:.4f}. Same "
        f"sum-of-squares minimization as partner-quad. Floor "
        f"is a proven lower bound; achievability may be higher under "
        f"schedule-structure constraints."
    )
    floors['opp_quad'] = Floor(
        metric='opp_quad',
        value=opp['quad_floor'],
        confidence=CONFIDENCE_PROVEN_LOWER,
        proof_note=opp_proof,
        units='sum of squares',
    )
    floors['opponent_pair_count'] = Floor(
        metric='opponent_pair_count',
        value=opp['count_floor'],
        confidence=CONFIDENCE_PROVEN_OPTIMAL,
        proof_note=(
            f"At least one pair must face another ≥ floor({opp['avg']:.4f}) "
            f"= {opp['count_floor']} times by pigeonhole."
        ),
        units='encounters',
    )

    # FRC #4: surrogate_count
    floors['surrogate_count'] = Floor(
        metric='surrogate_count',
        value=surrogate_count,
        confidence=CONFIDENCE_PROVEN_OPTIMAL,
        proof_note=(
            f"Surrogate count is structurally determined: "
            f"M * (2*tpa) - (n * MPT) = "
            f"{total_matches} * {2 * teams_per_alliance} - "
            f"{n_teams * matches_per_team} = {surrogate_count}. "
            f"Each surrogate is one team-match. Proven by arithmetic."
        ),
        units='surrogate slots',
    )

    # FRC #5: rb_metric (max |red_count - blue_count| across teams)
    color_floor = _color_balance_per_team_floor(matches_per_team)
    floors['rb_per_team'] = Floor(
        metric='rb_per_team',
        value=color_floor,
        confidence=CONFIDENCE_PROVEN_OPTIMAL,
        proof_note=(
            f"Per team: each plays {matches_per_team} matches across two colors. "
            f"If MPT is even, perfect (MPT/2, MPT/2) split is the optimum. "
            f"If MPT is odd, |red-blue| ≥ 1 is forced. Proven by pigeonhole."
        ),
        units='|red - blue|',
    )

    # FRC #6: station_pen / station_spread per team
    station_floor = _station_per_team_floor(matches_per_team)
    floors['station_per_team_spread'] = Floor(
        metric='station_per_team_spread',
        value=station_floor,
        confidence=CONFIDENCE_PROVEN_OPTIMAL,
        proof_note=(
            f"Per team: max - min across the 6 station-color positions "
            f"{{R1, R2, R3, B1, B2, B3}}. If MPT is divisible by 6, exactly "
            f"MPT/6 at each position gives spread=0. Otherwise some positions "
            f"get floor(MPT/6), others get ceil(MPT/6); spread=1 is forced. "
            f"Proven by pigeonhole over the 6 positions."
        ),
        units='positions',
    )

    return FixtureFloors(
        n_teams=n_teams,
        matches_per_team=matches_per_team,
        teams_per_alliance=teams_per_alliance,
        cooldown=cooldown,
        total_matches=total_matches,
        needs_surrogate=needs_surrogate,
        surrogate_count=surrogate_count,
        cooldown_max=cd_max,
        feasible=feasible,
        floors=floors,
    )


# ── Public re-exports ────────────────────────────────────────────────────


__all__ = [
    'CONFIDENCE_PROVEN_OPTIMAL',
    'CONFIDENCE_PROVEN_LOWER',
    'CONFIDENCE_BEST_KNOWN',
    'Floor',
    'FixtureFloors',
    'fixture_floors',
]
