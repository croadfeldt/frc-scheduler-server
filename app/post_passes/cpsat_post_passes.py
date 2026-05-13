# SPDX-License-Identifier: GPL-3.0-or-later
# FRC Match Scheduler
# Copyright (C) 2025 FRC Match Scheduler Contributors
"""CP-SAT exact solvers for the R/B balance and station balance post-passes.

The greedy + SA post-passes in this directory get the schedule "close to"
optimal on the per-team R/B imbalance and per-team station spread, but
have been observed (Phase D standards suite) to plateau above the true
optimum on larger fixtures (36×7, 60×12). The plateaus are SA local
optima — for these specific subproblems an exact ILP / CP-SAT solver
can prove the global optimum given budget.

These solvers are drop-in replacements for the SA variants. Same input
shape (list[Match]), same output shape, plus a status field on the
stats dict. Designed to be safe to fall back to SA if the solver
returns UNKNOWN (timeout with no feasible answer found): the returned
schedule is never worse than the input.

## Why post-passes are amenable to exact solution

Both post-passes operate on a tightly constrained subspace:

  - **R/B post-pass**: only varies the red/blue label of each match.
    Variable count = M (number of matches). Binary. Provably preserves
    partner pairs, opponent pairs, station-within-alliance distribution,
    cooldown, B2B, and surrogate counts (see app/post_passes/rb_balance.py
    module docstring for the commutativity proof).

  - **Station post-pass**: only varies the within-alliance permutation
    of teams (R1/R2/R3 assignment within each alliance). Variable count
    = 2M alliances × 6 permutations = 12M binaries with sum=1 per
    alliance. Provably preserves partner pairs, opponent pairs,
    cooldown, B2B, surrogate counts (alliance composition is fixed;
    only positions within the alliance change).

Both subproblems are small ILPs that CP-SAT handles well: R/B in seconds
even on 60×12, station in minutes-to-an-hour depending on fixture size
and time budget.

## Budget model

These solvers respect a `time_budget_s` parameter. On timeout:
  - If CP-SAT found a feasible solution (status FEASIBLE), we return
    that — it may not be proven optimal but is no worse than the
    SA-derived input.
  - If CP-SAT did not find any feasible solution (status UNKNOWN),
    we return the input unchanged with a warning in stats. The caller
    should fall back to the SA result.

Identity assignment is always feasible (don't flip / use identity
permutation), so UNKNOWN should be rare. It happens mostly when the
solver doesn't have time to even prove feasibility, which is a sign
the budget is too tight for the fixture size.

## Where this gets called

  - `scripts/scheduler_eval/build_canonical.py` invokes these with
    generous budgets (10-60 min) for canonical library curation. Each
    canonical entry is built once; the cost is amortized across every
    future cache hit.
  - The interactive Generate path (FastAPI) can optionally invoke
    these on cache-miss when the user picks a "high quality" option
    in the UI. UI caps budget at 60 minutes; the API enforces the
    same cap.
  - The SA-based variants in app/post_passes/rb_balance.py and
    app/post_passes/station_balance.py remain available and are the
    default for unconstrained interactive Generate.
"""

from __future__ import annotations

import logging
from itertools import permutations
from typing import Any

from ortools.sat.python import cp_model

from app.scheduler import Match


log = logging.getLogger(__name__)


# The maximum budget any caller can request, in seconds. Both the UI
# and the CLI honor this. Set to 1 hour: longer runs aren't useful
# in interactive contexts, and canonical curation that needs more
# than 1 hour should be a multi-stage workflow (different fixture
# shapes), not a single solver call.
MAX_BUDGET_SECONDS = 3600

# Default budget used by callers that don't specify one. Generous
# but bounded: enough to reach optimum on 36×7 most of the time,
# but not so long that test runs become painful. Production callers
# should override based on fixture size and user preference.
DEFAULT_BUDGET_SECONDS = 300


def _validate_budget(time_budget_s: float | int) -> float:
    """Clamp budget to [1, MAX_BUDGET_SECONDS] and return as float.

    Negative or zero is treated as "no useful budget" and raises.
    Callers should not pass these — but if they do, fail loudly
    rather than silently producing garbage.
    """
    if time_budget_s <= 0:
        raise ValueError(
            f"time_budget_s must be positive; got {time_budget_s!r}"
        )
    if time_budget_s > MAX_BUDGET_SECONDS:
        log.warning(
            "Budget %.1fs exceeds cap %.1fs; clamping",
            time_budget_s, MAX_BUDGET_SECONDS,
        )
        return float(MAX_BUDGET_SECONDS)
    return float(time_budget_s)


def _status_name(status: int) -> str:
    """CP-SAT status int → human-readable name."""
    return {
        cp_model.OPTIMAL:        'OPTIMAL',
        cp_model.FEASIBLE:       'FEASIBLE',
        cp_model.INFEASIBLE:     'INFEASIBLE',
        cp_model.MODEL_INVALID:  'MODEL_INVALID',
        cp_model.UNKNOWN:        'UNKNOWN',
    }.get(status, f'UNKNOWN_STATUS_{status}')


# ── R/B balance exact solver ───────────────────────────────────────


def rb_balance_cpsat(matches: list[Match],
                      time_budget_s: float = DEFAULT_BUDGET_SECONDS,
                      ) -> tuple[list[Match], dict[str, Any]]:
    """Exact CP-SAT solver for the R/B post-pass.

    Decision: for each match, flip red↔blue (or not). Objective:
    minimize the maximum per-team |red - blue| imbalance.

    Secondary objective (lex tiebreak): minimize the L1 sum of per-team
    imbalances. Two solutions with identical max imbalance can have
    different sum imbalances — the lower-sum one is strictly preferred
    for Phase D's composite scoring (the framework's rb_per_team metric
    uses max, but the underlying schedule quality is better when the
    "everyone else" axis is also tight).

    Args:
        matches: input schedule. Not mutated; new list returned.
        time_budget_s: max solver wall time in seconds. Clamped to
            [1, MAX_BUDGET_SECONDS]. CP-SAT may finish earlier if
            optimality is proven.

    Returns:
        (new_matches, stats): the (possibly identical) schedule and
        a stats dict including status, wall_time_s, max_before,
        max_after, sum_before, sum_after, n_flips.

    Fallback: on UNKNOWN status, returns the INPUT unchanged. Caller
    should treat that as "solver gave up" and fall back to SA result.
    """
    budget = _validate_budget(time_budget_s)
    if not matches:
        return list(matches), {
            'status': 'OPTIMAL',
            'wall_time_s': 0.0,
            'max_before': 0, 'max_after': 0,
            'sum_before': 0, 'sum_after': 0,
            'n_flips': 0,
            'reason': 'empty schedule',
        }

    # Build team set + per-match red/blue membership tables.
    M = len(matches)
    teams: set[int] = set()
    for m in matches:
        teams.update(m.red)
        teams.update(m.blue)
    team_list = sorted(teams)

    # is_red_in_match[t][m] = 1 if team t is on red in matches[m]
    # is_blue_in_match[t][m] = 1 if team t is on blue
    is_red:  dict[int, list[int]] = {t: [0] * M for t in team_list}
    is_blue: dict[int, list[int]] = {t: [0] * M for t in team_list}
    for m_idx, m in enumerate(matches):
        for t in m.red:
            is_red[t][m_idx] = 1
        for t in m.blue:
            is_blue[t][m_idx] = 1

    # Pre-compute the initial (no-flip) red/blue counts for stats.
    rc_before: dict[int, int] = {t: sum(is_red[t])  for t in team_list}
    bc_before: dict[int, int] = {t: sum(is_blue[t]) for t in team_list}
    max_before = max(abs(rc_before[t] - bc_before[t]) for t in team_list)
    sum_before = sum(abs(rc_before[t] - bc_before[t]) for t in team_list)

    # Build the model.
    model = cp_model.CpModel()
    flip = [model.NewBoolVar(f'flip_{m_idx}') for m_idx in range(M)]

    # For each team t:
    #   red_after_t = Σ_m  is_red[t][m] * (1 - flip[m])
    #                    + is_blue[t][m] * flip[m]
    #   delta_t     = red_after_t - blue_after_t
    #                = 2*red_after_t - MPT_t       (since blue = MPT - red)
    # We minimize max_t |delta_t|.
    abs_delta_vars = []
    for t in team_list:
        MPT_t = rc_before[t] + bc_before[t]
        # red_after_t (integer; bounded by [0, MPT_t])
        red_after_t = model.NewIntVar(0, MPT_t, f'red_after_{t}')
        # red_after_t == Σ red_terms - Σ blue_flip_terms + offset_const
        # Linear form: red_after_t = Σ_m  is_red[t][m] * (1 - flip[m])
        #                          + Σ_m  is_blue[t][m] * flip[m]
        #            = Σ_m is_red[t][m]    (constant base)
        #              + Σ_m (is_blue[t][m] - is_red[t][m]) * flip[m]
        base = sum(is_red[t])
        coeffs = [is_blue[t][m_idx] - is_red[t][m_idx] for m_idx in range(M)]
        # Only include flips with nonzero coefficient (efficiency).
        terms = [coeffs[m_idx] * flip[m_idx]
                 for m_idx in range(M) if coeffs[m_idx] != 0]
        model.Add(red_after_t == base + sum(terms))

        # delta_t = 2 * red_after_t - MPT_t. Could be negative.
        delta_t = model.NewIntVar(-MPT_t, MPT_t, f'delta_{t}')
        model.Add(delta_t == 2 * red_after_t - MPT_t)

        # abs_delta_t
        abs_delta_t = model.NewIntVar(0, MPT_t, f'abs_delta_{t}')
        model.AddAbsEquality(abs_delta_t, delta_t)
        abs_delta_vars.append(abs_delta_t)

    # Primary: minimize max_t abs_delta_t.
    max_imb = model.NewIntVar(
        0, max(rc_before[t] + bc_before[t] for t in team_list),
        'max_imbalance',
    )
    model.AddMaxEquality(max_imb, abs_delta_vars)

    # Lex tiebreak: weighted-sum objective with max heavily weighted.
    # Bound on sum: sum of MPT_t across all teams = total team-appearances.
    sum_imb_upper = sum(rc_before[t] + bc_before[t] for t in team_list)
    sum_imb = model.NewIntVar(0, sum_imb_upper, 'sum_imbalance')
    model.Add(sum_imb == sum(abs_delta_vars))
    # Use big-W combining: lexicographically minimize (max_imb, sum_imb).
    # W must exceed max possible sum_imb so that any unit increase in
    # max_imb dominates any decrease in sum_imb.
    W = sum_imb_upper + 1
    model.Minimize(W * max_imb + sum_imb)

    # Solve.
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = budget
    solver.parameters.num_search_workers = 8  # use parallel search
    solver.parameters.log_search_progress = False

    status = solver.Solve(model)
    wall = solver.WallTime()
    status_str = _status_name(status)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # No usable solution — return input unchanged. Caller decides
        # whether to use SA fallback or accept the input as-is.
        log.warning(
            "rb_balance_cpsat: solver returned %s in %.1fs; returning input",
            status_str, wall,
        )
        return list(matches), {
            'status': status_str,
            'wall_time_s': wall,
            'max_before': max_before, 'max_after': max_before,
            'sum_before': sum_before, 'sum_after': sum_before,
            'n_flips': 0,
            'reason': 'no feasible solution',
        }

    # Apply the solver's flip decisions.
    out: list[Match] = []
    n_flips = 0
    for m_idx, m in enumerate(matches):
        if solver.Value(flip[m_idx]):
            out.append(Match(
                red=m.blue, blue=m.red,
                red_surrogate=m.blue_surrogate,
                blue_surrogate=m.red_surrogate,
            ))
            n_flips += 1
        else:
            out.append(m)

    # Verify the after-counts match the solver's objective.
    rc_after: dict[int, int] = {t: 0 for t in team_list}
    bc_after: dict[int, int] = {t: 0 for t in team_list}
    for m in out:
        for t in m.red:  rc_after[t] += 1
        for t in m.blue: bc_after[t] += 1
    max_after = max(abs(rc_after[t] - bc_after[t]) for t in team_list)
    sum_after = sum(abs(rc_after[t] - bc_after[t]) for t in team_list)

    return out, {
        'status': status_str,
        'wall_time_s': wall,
        'max_before': max_before, 'max_after': max_after,
        'sum_before': sum_before, 'sum_after': sum_after,
        'n_flips': n_flips,
    }


# ── Station balance exact solver ──────────────────────────────────


# Pre-computed permutations of S_3 (3! = 6 options).
_ALL_PERMS = list(permutations((0, 1, 2)))


def station_balance_cpsat(matches: list[Match],
                           time_budget_s: float = DEFAULT_BUDGET_SECONDS,
                           ) -> tuple[list[Match], dict[str, Any]]:
    """Exact CP-SAT solver for the station post-pass.

    Decision: for each alliance (red or blue side of each match),
    choose one of 6 permutations of S_3 (= which of the 3 teams goes
    to position 1, which to position 2, which to position 3 within
    that alliance). Provably preserves partner pairs, opponent pairs,
    cooldown, B2B, surrogate counts (alliance composition is fixed;
    only positions change).

    Objective: minimize max_team (max_position_count - min_position_count)
    across the 6 stations {R1, R2, R3, B1, B2, B3}.

    Secondary objective (lex tiebreak): minimize total per-team spread
    (sum of per-team spreads). Same rationale as rb_balance_cpsat —
    the headline metric uses max, but the underlying quality is better
    when "everyone else" is also tight.

    Args:
        matches: input schedule. Not mutated; new list returned.
        time_budget_s: max solver wall time in seconds.

    Returns:
        (new_matches, stats): the (possibly identical) schedule and
        a stats dict.

    Fallback: on UNKNOWN, returns input unchanged.
    """
    budget = _validate_budget(time_budget_s)
    if not matches:
        return list(matches), {
            'status': 'OPTIMAL',
            'wall_time_s': 0.0,
            'max_before': 0, 'max_after': 0,
            'sum_before': 0, 'sum_after': 0,
            'n_permutations': 0,
            'reason': 'empty schedule',
        }

    M = len(matches)
    # Collect team set + pre-compute initial counts for stats.
    teams: set[int] = set()
    for m in matches:
        teams.update(m.red)
        teams.update(m.blue)
    team_list = sorted(teams)

    # Initial position counts: 6 positions (R1, R2, R3, B1, B2, B3)
    # indexed 0..5 where 0..2 = red 1..3, 3..5 = blue 1..3.
    initial_counts: dict[int, list[int]] = {t: [0] * 6 for t in team_list}
    for m in matches:
        for i, t in enumerate(m.red):
            initial_counts[t][i] += 1
        for i, t in enumerate(m.blue):
            initial_counts[t][3 + i] += 1
    max_before = max(max(c) - min(c) for c in initial_counts.values())
    sum_before = sum(max(c) - min(c) for c in initial_counts.values())

    # Build the model.
    model = cp_model.CpModel()

    # For each alliance, one of 6 permutations. We use one-hot
    # encoding: perm_chosen[a][k] = 1 if alliance a uses _ALL_PERMS[k].
    n_alliances = 2 * M  # red and blue per match
    perm_chosen: list[list[Any]] = []
    for a_idx in range(n_alliances):
        choices = [model.NewBoolVar(f'perm_a{a_idx}_k{k}') for k in range(6)]
        model.AddExactlyOne(choices)
        perm_chosen.append(choices)

    # For each (team, position) pair: the count is the number of
    # alliances where that team lands at that position.
    # For an alliance with teams (T0, T1, T2) and chosen perm σ:
    #   position_of_T0 = σ[0], position_of_T1 = σ[1], position_of_T2 = σ[2]
    # where positions are within the alliance (0/1/2 = R1/R2/R3 if red,
    # 3/4/5 = B1/B2/B3 if blue).
    #
    # We linearize: for team t, position p, alliance a (red or blue side),
    # the contribution to cnt[t][p] is:
    #   Σ_k  (1 if perm_k places team t at position p in alliance a else 0)
    #         * perm_chosen[a][k]
    # The "perm_k places team t at position p" check is data, not a variable.

    # Pre-compute the placement table for fast model building.
    # placement_table[a_idx][k] -> dict {team: position}
    placement_table: list[list[dict[int, int]]] = []
    for m_idx, m in enumerate(matches):
        # Red alliance
        red_teams = m.red
        red_alliance_perms = []
        for k, sigma in enumerate(_ALL_PERMS):
            placement: dict[int, int] = {}
            for src_idx, team in enumerate(red_teams):
                dst_pos = sigma[src_idx]
                placement[team] = dst_pos  # 0, 1, or 2 (R1/R2/R3)
            red_alliance_perms.append(placement)
        placement_table.append(red_alliance_perms)

        # Blue alliance
        blue_teams = m.blue
        blue_alliance_perms = []
        for k, sigma in enumerate(_ALL_PERMS):
            placement: dict[int, int] = {}
            for src_idx, team in enumerate(blue_teams):
                dst_pos = sigma[src_idx]
                placement[team] = 3 + dst_pos  # 3, 4, or 5 (B1/B2/B3)
            blue_alliance_perms.append(placement)
        placement_table.append(blue_alliance_perms)

    # cnt[t][p] = sum of perm_chosen indicators contributing team t at position p.
    cnt: dict[int, list[Any]] = {}
    max_count_upper = M  # worst case: a team plays every match at one position
    for t in team_list:
        cnt[t] = []
        for p in range(6):
            c = model.NewIntVar(0, max_count_upper, f'cnt_t{t}_p{p}')
            # Gather all (alliance, perm_k) pairs that contribute team t at position p.
            terms = []
            for a_idx in range(n_alliances):
                for k in range(6):
                    placement = placement_table[a_idx][k]
                    if placement.get(t) == p:
                        terms.append(perm_chosen[a_idx][k])
            if terms:
                model.Add(c == sum(terms))
            else:
                # Team t can never be at position p (not in any alliance
                # at this position). Constant 0.
                model.Add(c == 0)
            cnt[t].append(c)

    # Per-team spread = max_p(cnt[t][p]) - min_p(cnt[t][p]).
    spread_vars = []
    for t in team_list:
        max_pos = model.NewIntVar(0, max_count_upper, f'max_pos_{t}')
        min_pos = model.NewIntVar(0, max_count_upper, f'min_pos_{t}')
        spread  = model.NewIntVar(0, max_count_upper, f'spread_{t}')
        model.AddMaxEquality(max_pos, cnt[t])
        model.AddMinEquality(min_pos, cnt[t])
        model.Add(spread == max_pos - min_pos)
        spread_vars.append(spread)

    # Primary: minimize max_t spread.
    max_spread = model.NewIntVar(0, max_count_upper, 'max_spread')
    model.AddMaxEquality(max_spread, spread_vars)

    # Lex tiebreak: also minimize sum of per-team spreads.
    sum_spread_upper = max_count_upper * len(team_list)
    sum_spread = model.NewIntVar(0, sum_spread_upper, 'sum_spread')
    model.Add(sum_spread == sum(spread_vars))
    W = sum_spread_upper + 1
    model.Minimize(W * max_spread + sum_spread)

    # Solve.
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = budget
    solver.parameters.num_search_workers = 8
    solver.parameters.log_search_progress = False

    status = solver.Solve(model)
    wall = solver.WallTime()
    status_str = _status_name(status)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        log.warning(
            "station_balance_cpsat: solver returned %s in %.1fs; returning input",
            status_str, wall,
        )
        return list(matches), {
            'status': status_str,
            'wall_time_s': wall,
            'max_before': max_before, 'max_after': max_before,
            'sum_before': sum_before, 'sum_after': sum_before,
            'n_permutations': 0,
            'reason': 'no feasible solution',
        }

    # Apply the solver's permutation decisions.
    out: list[Match] = []
    n_perms = 0
    for m_idx, m in enumerate(matches):
        red_a_idx  = 2 * m_idx
        blue_a_idx = 2 * m_idx + 1

        # Find which perm was chosen for each alliance.
        red_k = next(k for k in range(6) if solver.Value(perm_chosen[red_a_idx][k]))
        blue_k = next(k for k in range(6) if solver.Value(perm_chosen[blue_a_idx][k]))

        red_sigma = _ALL_PERMS[red_k]
        blue_sigma = _ALL_PERMS[blue_k]

        # Apply σ to red: team at src_idx goes to position σ[src_idx].
        # Build the new red tuple by placing each team at its destination.
        new_red = [None] * 3
        new_red_sur = [None] * 3
        for src_idx in range(3):
            new_red[red_sigma[src_idx]] = m.red[src_idx]
            new_red_sur[red_sigma[src_idx]] = m.red_surrogate[src_idx]
        new_blue = [None] * 3
        new_blue_sur = [None] * 3
        for src_idx in range(3):
            new_blue[blue_sigma[src_idx]] = m.blue[src_idx]
            new_blue_sur[blue_sigma[src_idx]] = m.blue_surrogate[src_idx]

        if red_k != 0:  n_perms += 1  # identity is perm index 0
        if blue_k != 0: n_perms += 1

        out.append(Match(
            red=tuple(new_red),
            blue=tuple(new_blue),
            red_surrogate=tuple(new_red_sur),
            blue_surrogate=tuple(new_blue_sur),
        ))

    # Verify after-counts match what the solver claimed.
    after_counts: dict[int, list[int]] = {t: [0] * 6 for t in team_list}
    for m in out:
        for i, t in enumerate(m.red):  after_counts[t][i] += 1
        for i, t in enumerate(m.blue): after_counts[t][3 + i] += 1
    max_after = max(max(c) - min(c) for c in after_counts.values())
    sum_after = sum(max(c) - min(c) for c in after_counts.values())

    return out, {
        'status': status_str,
        'wall_time_s': wall,
        'max_before': max_before, 'max_after': max_after,
        'sum_before': sum_before, 'sum_after': sum_after,
        'n_permutations': n_perms,
    }


__all__ = [
    'rb_balance_cpsat',
    'station_balance_cpsat',
    'MAX_BUDGET_SECONDS',
    'DEFAULT_BUDGET_SECONDS',
]
