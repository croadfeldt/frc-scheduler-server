#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""CP-SAT formulation for Stage 1 pairing — Q2 investigation.

Formulates the FRC qualification schedule pairing problem as a CP-SAT
constraint program. The goal is to find a provably-optimal schedule by
the lex tuple's pairing slots (par_quad, opp_quad) for small fixtures
where CP-SAT can terminate.

This deliberately ignores:
  - Red vs blue alliance assignment (commutative with pairing; handled
    by separate post-pass)
  - Station position within alliance (commutative; separate post-pass)
  - Surrogate decisions (this formulation only handles fixtures where
    n*MPT is divisible by 6 — no surrogates needed)

What it solves:
  - For each match: which 6 teams play, partitioned into two
    same-color groups of 3 (the "with each other" partition)
  - Subject to: cooldown, each team plays exactly MPT matches
  - Objective: lex-min (par_quad, opp_quad)

Outputs:
  - The optimal pair-count distribution
  - Solver wall-clock
  - Whether the solver proved optimality or hit a time limit
  - Comparison to the lex tuple our SA produces on the same fixture

This is research code for the Phase 1 investigation per
`docs/workstreams/best-possible-schedule.md` Q2. Not production code.
Run:
    python3 scripts/cp_sat/pairing_optimum.py --teams 12 --mpt 6 --cooldown 3
"""

from __future__ import annotations

import argparse
import sys
import time
from itertools import combinations
from pathlib import Path

# Repo root for imports.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ortools.sat.python import cp_model


def build_pairing_model(n_teams: int,
                       matches_per_team: int,
                       teams_per_alliance: int,
                       cooldown: int,
                       time_limit_s: float = 60.0,
                       ) -> tuple[cp_model.CpModel, dict, dict]:
    """Build the CP-SAT model and return (model, variables, metadata).

    Variables dict has structure:
        {
            'in_match':  dict[(match, team)] -> BoolVar,
            'on_side':   dict[(match, team)] -> BoolVar,  # arbitrary color label
            'partner':   dict[(match, i, j)] -> BoolVar,  # i<j; 1 iff same side
            'opponent':  dict[(match, i, j)] -> BoolVar,  # i<j; 1 iff opposite sides
            'par_count': dict[(i, j)] -> IntVar,           # i<j; total partner encounters
            'opp_count': dict[(i, j)] -> IntVar,           # i<j; total opponent encounters
            'par_quad':  IntVar,                            # sum of par_count^2
            'opp_quad':  IntVar,                            # sum of opp_count^2
        }
    """
    total_slots = n_teams * matches_per_team
    if total_slots % (2 * teams_per_alliance) != 0:
        raise ValueError(
            f"n*MPT = {total_slots} not divisible by 2*tpa = "
            f"{2 * teams_per_alliance}; this formulation doesn't handle "
            f"surrogates"
        )
    n_matches = total_slots // (2 * teams_per_alliance)

    model = cp_model.CpModel()
    teams = list(range(1, n_teams + 1))
    matches = list(range(n_matches))
    pairs = list(combinations(teams, 2))

    # --- Variables ---

    # in_match[m, t] = 1 iff team t plays in match m
    in_match = {}
    for m in matches:
        for t in teams:
            in_match[m, t] = model.NewBoolVar(f"in_match_m{m}_t{t}")

    # on_side[m, t] = 1 iff team t is on "side A" of match m (arbitrary
    # color label). Only meaningful when in_match[m, t] = 1. We don't
    # constrain on_side to 0 when not in the match — it's just a free
    # variable in that case. The partner/opponent encoding handles the
    # "must be in match" gate.
    on_side = {}
    for m in matches:
        for t in teams:
            on_side[m, t] = model.NewBoolVar(f"on_side_m{m}_t{t}")

    # partner[m, i, j] = 1 iff i and j are both in match m AND on same side
    # opponent[m, i, j] = 1 iff i and j are both in match m AND opposite sides
    partner = {}
    opponent = {}
    for m in matches:
        for i, j in pairs:
            partner[m, i, j] = model.NewBoolVar(f"partner_m{m}_t{i}_t{j}")
            opponent[m, i, j] = model.NewBoolVar(f"opp_m{m}_t{i}_t{j}")

    # par_count[i, j] = sum over m of partner[m, i, j]
    # opp_count[i, j] = sum over m of opponent[m, i, j]
    par_count = {}
    opp_count = {}
    max_count = matches_per_team  # can't pair more times than smaller team plays
    for i, j in pairs:
        par_count[i, j] = model.NewIntVar(0, max_count, f"par_count_t{i}_t{j}")
        opp_count[i, j] = model.NewIntVar(0, max_count, f"opp_count_t{i}_t{j}")

    # Per-pair quadratic terms
    par_count_sq = {}
    opp_count_sq = {}
    for i, j in pairs:
        par_count_sq[i, j] = model.NewIntVar(0, max_count * max_count,
                                              f"par_sq_t{i}_t{j}")
        opp_count_sq[i, j] = model.NewIntVar(0, max_count * max_count,
                                              f"opp_sq_t{i}_t{j}")

    # Aggregate squared sums
    par_quad = model.NewIntVar(0, len(pairs) * max_count * max_count, "par_quad")
    opp_quad = model.NewIntVar(0, len(pairs) * max_count * max_count, "opp_quad")

    # --- Constraints ---

    # Each match has exactly 2*tpa teams; tpa on each side
    side_size = teams_per_alliance
    for m in matches:
        # tpa teams on each side; total 2*tpa in the match
        # "on side A" among in-match teams must equal tpa
        # AddBoolAnd-style: side_A_count = sum(in_match[m,t] AND on_side[m,t])
        side_A_terms = []
        side_B_terms = []
        for t in teams:
            # Need: this team is on side A iff in_match[m, t] = 1 AND on_side[m, t] = 1
            # Use auxiliary indicator
            on_A = model.NewBoolVar(f"on_A_m{m}_t{t}")
            on_B = model.NewBoolVar(f"on_B_m{m}_t{t}")
            # on_A = in_match AND on_side
            model.AddBoolAnd([in_match[m, t], on_side[m, t]]).OnlyEnforceIf(on_A)
            model.AddBoolOr([in_match[m, t].Not(), on_side[m, t].Not()]).OnlyEnforceIf(on_A.Not())
            # on_B = in_match AND NOT on_side
            model.AddBoolAnd([in_match[m, t], on_side[m, t].Not()]).OnlyEnforceIf(on_B)
            model.AddBoolOr([in_match[m, t].Not(), on_side[m, t]]).OnlyEnforceIf(on_B.Not())
            side_A_terms.append(on_A)
            side_B_terms.append(on_B)
        model.Add(sum(side_A_terms) == side_size)
        model.Add(sum(side_B_terms) == side_size)

    # Each team plays exactly MPT matches
    for t in teams:
        model.Add(sum(in_match[m, t] for m in matches) == matches_per_team)

    # Cooldown: for any window of `cooldown` consecutive matches, team
    # appears at most once
    for t in teams:
        for m_start in range(n_matches - cooldown + 1):
            window = [in_match[m_start + k, t] for k in range(cooldown)]
            model.Add(sum(window) <= 1)

    # Partner/opponent indicator constraints
    # partner[m, i, j] = 1 iff both in match AND same side
    # opponent[m, i, j] = 1 iff both in match AND opposite sides
    for m in matches:
        for i, j in pairs:
            # both_in[m, i, j] = in_match[m, i] AND in_match[m, j]
            both_in = model.NewBoolVar(f"both_in_m{m}_t{i}_t{j}")
            model.AddBoolAnd([in_match[m, i], in_match[m, j]]).OnlyEnforceIf(both_in)
            model.AddBoolOr([in_match[m, i].Not(), in_match[m, j].Not()]).OnlyEnforceIf(both_in.Not())

            # same_side[m, i, j] = (on_side[m, i] == on_side[m, j])
            same_side = model.NewBoolVar(f"same_side_m{m}_t{i}_t{j}")
            # same_side = 1 iff on_side[i] = on_side[j]
            # equivalent: same_side <=> (on_side[i] XOR on_side[j]) = 0
            # Encode via two implications:
            #   on_side[i] = on_side[j] => same_side = 1
            #   on_side[i] != on_side[j] => same_side = 0
            # Using indicators:
            model.Add(on_side[m, i] == on_side[m, j]).OnlyEnforceIf(same_side)
            model.Add(on_side[m, i] != on_side[m, j]).OnlyEnforceIf(same_side.Not())

            # partner = both_in AND same_side
            model.AddBoolAnd([both_in, same_side]).OnlyEnforceIf(partner[m, i, j])
            model.AddBoolOr([both_in.Not(), same_side.Not()]).OnlyEnforceIf(partner[m, i, j].Not())

            # opponent = both_in AND NOT same_side
            model.AddBoolAnd([both_in, same_side.Not()]).OnlyEnforceIf(opponent[m, i, j])
            model.AddBoolOr([both_in.Not(), same_side]).OnlyEnforceIf(opponent[m, i, j].Not())

    # par_count and opp_count are sums of indicators
    for i, j in pairs:
        model.Add(par_count[i, j] == sum(partner[m, i, j] for m in matches))
        model.Add(opp_count[i, j] == sum(opponent[m, i, j] for m in matches))

    # Squared terms via AddMultiplicationEquality
    for i, j in pairs:
        model.AddMultiplicationEquality(par_count_sq[i, j],
                                         [par_count[i, j], par_count[i, j]])
        model.AddMultiplicationEquality(opp_count_sq[i, j],
                                         [opp_count[i, j], opp_count[i, j]])

    # Aggregate sums
    model.Add(par_quad == sum(par_count_sq[i, j] for i, j in pairs))
    model.Add(opp_quad == sum(opp_count_sq[i, j] for i, j in pairs))

    # --- Objective: lex-min (par_quad, opp_quad) ---
    # CP-SAT doesn't natively do lex objectives. Two approaches:
    # 1. Weighted sum with large weight on par_quad. Works if we know
    #    a tight upper bound on opp_quad. Here, opp_quad ≤ pairs * max^2.
    # 2. Two-stage: minimize par_quad first, fix it, then minimize opp_quad.
    # Use option 2 — it's cleaner and produces an exact lex-min.
    # For this first formulation, just minimize par_quad and report
    # par_quad along with the achieved opp_quad. A future iteration will
    # add the two-stage refinement.
    model.Minimize(par_quad)

    return model, {
        'in_match': in_match,
        'on_side': on_side,
        'partner': partner,
        'opponent': opponent,
        'par_count': par_count,
        'opp_count': opp_count,
        'par_quad': par_quad,
        'opp_quad': opp_quad,
    }, {
        'n_teams': n_teams,
        'matches_per_team': matches_per_team,
        'teams_per_alliance': teams_per_alliance,
        'cooldown': cooldown,
        'n_matches': n_matches,
        'n_pairs': len(pairs),
    }


def solve_and_report(n_teams: int, matches_per_team: int,
                     teams_per_alliance: int = 3,
                     cooldown: int = 2,
                     time_limit_s: float = 60.0,
                     n_workers: int = 8) -> dict:
    """Build and solve. Returns a dict of results.

    cooldown defaults to 2 per project policy (F1-e methodology decision).
    """
    print(f"Building CP-SAT model for {n_teams}t × {matches_per_team}MPT × "
          f"{teams_per_alliance}tpa, cooldown={cooldown}...")
    t0 = time.time()
    model, vars, meta = build_pairing_model(n_teams, matches_per_team,
                                            teams_per_alliance, cooldown,
                                            time_limit_s)
    build_time = time.time() - t0
    print(f"  Model built in {build_time:.1f}s")
    print(f"  {meta['n_matches']} matches, {meta['n_pairs']} pairs")

    print(f"\nSolving (time_limit={time_limit_s}s, workers={n_workers})...")
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_search_workers = n_workers
    solver.parameters.log_search_progress = False

    t0 = time.time()
    status = solver.Solve(model)
    solve_time = time.time() - t0

    status_name = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE (time limit hit)",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
        cp_model.UNKNOWN: "UNKNOWN (no solution within time)",
    }.get(status, f"status={status}")

    print(f"  Status: {status_name}")
    print(f"  Solve time: {solve_time:.1f}s")

    result = {
        'n_teams': n_teams,
        'matches_per_team': matches_per_team,
        'teams_per_alliance': teams_per_alliance,
        'cooldown': cooldown,
        'n_matches': meta['n_matches'],
        'build_time_s': round(build_time, 2),
        'solve_time_s': round(solve_time, 2),
        'status': status_name,
        'status_code': status,
    }

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        par_quad_val = solver.Value(vars['par_quad'])
        opp_quad_val = solver.Value(vars['opp_quad'])
        result['par_quad'] = par_quad_val
        result['opp_quad'] = opp_quad_val

        # Pair distribution
        par_dist = {}
        opp_dist = {}
        for (i, j), v in vars['par_count'].items():
            c = solver.Value(v)
            par_dist[c] = par_dist.get(c, 0) + 1
        for (i, j), v in vars['opp_count'].items():
            c = solver.Value(v)
            opp_dist[c] = opp_dist.get(c, 0) + 1
        result['par_dist'] = par_dist
        result['opp_dist'] = opp_dist
        result['par_max'] = max(par_dist.keys())
        result['opp_max'] = max(opp_dist.keys())
        result['par_repeats'] = sum(c for n, c in par_dist.items() if n >= 2)
        result['opp_repeats'] = sum(c for n, c in opp_dist.items() if n >= 2)

        # Theoretical floors
        partner_slots_per_team = matches_per_team * (teams_per_alliance - 1)
        opponent_slots_per_team = matches_per_team * teams_per_alliance
        result['partner_floor'] = -(-partner_slots_per_team // (n_teams - 1))  # ceil div
        result['opponent_floor'] = -(-opponent_slots_per_team // (n_teams - 1))

        print(f"\nResults:")
        print(f"  par_quad: {par_quad_val}")
        print(f"  opp_quad: {opp_quad_val}")
        print(f"  partner distribution: {sorted(par_dist.items())}")
        print(f"  opponent distribution: {sorted(opp_dist.items())}")
        print(f"  partner floor: {result['partner_floor']}, max in solution: {result['par_max']}")
        print(f"  opponent floor: {result['opponent_floor']}, max in solution: {result['opp_max']}")
        print(f"  pairs that partner >=2 times: {result['par_repeats']}")
        print(f"  pairs that face off >=2 times: {result['opp_repeats']}")

        if status == cp_model.OPTIMAL:
            print(f"\n  *** OPTIMALITY PROVEN for par_quad = {par_quad_val} ***")
            print(f"  (opp_quad = {opp_quad_val} is what was achieved at par_quad-optimum;")
            print(f"   full lex-min requires a 2-stage solve: fix par_quad, then min opp_quad)")

    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--teams', type=int, required=True)
    ap.add_argument('--mpt', type=int, required=True)
    ap.add_argument('--tpa', type=int, default=3)
    ap.add_argument('--cooldown', type=int, default=2,
                    help="Project default 2 per F1-e methodology; "
                         "override for stress-testing tight fixtures.")
    ap.add_argument('--time-limit', type=float, default=60.0)
    ap.add_argument('--workers', type=int, default=8)
    args = ap.parse_args()

    result = solve_and_report(args.teams, args.mpt, args.tpa, args.cooldown,
                              args.time_limit, args.workers)
    return result


if __name__ == '__main__':
    main()
