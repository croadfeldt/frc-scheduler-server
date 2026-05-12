#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Refined CP-SAT formulation for Stage 1 pairing — Q2 investigation (F1).

F1 follow-up to `pairing_optimum.py`. Addresses the four suspected
sources of inefficiency from v1:

  1. Match-ordering / color / partial team symmetry — anchor: team 1
     plays in match 0 on side A. Breaks color symmetry (2×) and the
     "which match team 1 plays in" symmetry.
  2. Tighter indicator encoding — direct linear reified constraints
     (a ≤ b, a ≤ c, a ≥ b+c-1) instead of AddBoolAnd-with-
     OnlyEnforceIf.
  3. Linear histogram objective — replaced AddMultiplicationEquality
     with count-at-each-level indicators and Σ k² × n_at_k.
  4. (Not yet implemented in v2) Warm start from SA output.

Like v1, this ignores red-vs-blue color identity and station
positions (both commutative with pairing per the post-pass
architecture). Surrogate-free fixtures only.

Run:
    python3 scripts/cp_sat/pairing_optimum_v2.py --teams 12 --mpt 6 --cooldown 2

Compare to v1 (same flags) to measure F1's impact.
"""

from __future__ import annotations

import argparse
import sys
import time
from itertools import combinations
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ortools.sat.python import cp_model


def build_pairing_model_v2(n_teams: int,
                           matches_per_team: int,
                           teams_per_alliance: int,
                           cooldown: int,
                           ) -> tuple[cp_model.CpModel, dict, dict]:
    """Refined CP-SAT model. Returns (model, variables, metadata)."""
    total_slots = n_teams * matches_per_team
    if total_slots % (2 * teams_per_alliance) != 0:
        raise ValueError(
            f"n*MPT = {total_slots} not divisible by 2*tpa = "
            f"{2 * teams_per_alliance}; this formulation doesn't handle "
            f"surrogates"
        )
    n_matches = total_slots // (2 * teams_per_alliance)
    if n_teams < 2 * teams_per_alliance:
        raise ValueError(
            f"n_teams={n_teams} < 2*tpa={2 * teams_per_alliance}; "
            f"can't form a match"
        )

    model = cp_model.CpModel()
    teams = list(range(1, n_teams + 1))
    matches = list(range(n_matches))
    pairs = list(combinations(teams, 2))
    max_count = matches_per_team

    # --- Decision variables ---
    in_match = {}
    for m in matches:
        for t in teams:
            in_match[m, t] = model.NewBoolVar(f"in_match_m{m}_t{t}")

    on_side = {}
    for m in matches:
        for t in teams:
            on_side[m, t] = model.NewBoolVar(f"on_side_m{m}_t{t}")

    # on_A, on_B via tight linear reification
    on_A = {}
    on_B = {}
    for m in matches:
        for t in teams:
            on_A[m, t] = model.NewBoolVar(f"on_A_m{m}_t{t}")
            on_B[m, t] = model.NewBoolVar(f"on_B_m{m}_t{t}")
            # on_A = in_match AND on_side
            model.Add(on_A[m, t] <= in_match[m, t])
            model.Add(on_A[m, t] <= on_side[m, t])
            model.Add(on_A[m, t] >= in_match[m, t] + on_side[m, t] - 1)
            # on_B = in_match AND NOT on_side
            model.Add(on_B[m, t] <= in_match[m, t])
            model.Add(on_B[m, t] <= 1 - on_side[m, t])
            model.Add(on_B[m, t] >= in_match[m, t] - on_side[m, t])
        model.Add(sum(on_A[m, t] for t in teams) == teams_per_alliance)
        model.Add(sum(on_B[m, t] for t in teams) == teams_per_alliance)

    # Each team plays exactly MPT matches
    for t in teams:
        model.Add(sum(in_match[m, t] for m in matches) == matches_per_team)

    # Cooldown
    for t in teams:
        for m_start in range(n_matches - cooldown + 1):
            window = [in_match[m_start + k, t] for k in range(cooldown)]
            model.Add(sum(window) <= 1)

    # --- Partner / opponent indicators ---
    partner = {}
    opponent = {}
    for m in matches:
        for (i, j) in pairs:
            sAA = model.NewBoolVar(f"sAA_m{m}_t{i}_t{j}")
            sBB = model.NewBoolVar(f"sBB_m{m}_t{i}_t{j}")
            cAB = model.NewBoolVar(f"cAB_m{m}_t{i}_t{j}")
            cBA = model.NewBoolVar(f"cBA_m{m}_t{i}_t{j}")
            model.Add(sAA <= on_A[m, i])
            model.Add(sAA <= on_A[m, j])
            model.Add(sAA >= on_A[m, i] + on_A[m, j] - 1)
            model.Add(sBB <= on_B[m, i])
            model.Add(sBB <= on_B[m, j])
            model.Add(sBB >= on_B[m, i] + on_B[m, j] - 1)
            model.Add(cAB <= on_A[m, i])
            model.Add(cAB <= on_B[m, j])
            model.Add(cAB >= on_A[m, i] + on_B[m, j] - 1)
            model.Add(cBA <= on_B[m, i])
            model.Add(cBA <= on_A[m, j])
            model.Add(cBA >= on_B[m, i] + on_A[m, j] - 1)
            partner[m, i, j] = model.NewBoolVar(f"par_m{m}_t{i}_t{j}")
            opponent[m, i, j] = model.NewBoolVar(f"opp_m{m}_t{i}_t{j}")
            model.Add(partner[m, i, j] == sAA + sBB)
            model.Add(opponent[m, i, j] == cAB + cBA)

    # par_count / opp_count
    par_count = {}
    opp_count = {}
    for i, j in pairs:
        par_count[i, j] = model.NewIntVar(0, max_count, f"par_count_t{i}_t{j}")
        opp_count[i, j] = model.NewIntVar(0, max_count, f"opp_count_t{i}_t{j}")
        model.Add(par_count[i, j] == sum(partner[m, i, j] for m in matches))
        model.Add(opp_count[i, j] == sum(opponent[m, i, j] for m in matches))

    # --- Linear histogram objective ---
    par_count_eq = {}
    opp_count_eq = {}
    for i, j in pairs:
        for k in range(max_count + 1):
            par_count_eq[(i, j), k] = model.NewBoolVar(
                f"par_eq_t{i}_t{j}_k{k}")
            opp_count_eq[(i, j), k] = model.NewBoolVar(
                f"opp_eq_t{i}_t{j}_k{k}")
            model.Add(par_count[i, j] == k).OnlyEnforceIf(par_count_eq[(i, j), k])
            model.Add(par_count[i, j] != k).OnlyEnforceIf(par_count_eq[(i, j), k].Not())
            model.Add(opp_count[i, j] == k).OnlyEnforceIf(opp_count_eq[(i, j), k])
            model.Add(opp_count[i, j] != k).OnlyEnforceIf(opp_count_eq[(i, j), k].Not())
        model.AddExactlyOne(par_count_eq[(i, j), k] for k in range(max_count + 1))
        model.AddExactlyOne(opp_count_eq[(i, j), k] for k in range(max_count + 1))

    par_quad = model.NewIntVar(0, len(pairs) * max_count * max_count, "par_quad")
    opp_quad = model.NewIntVar(0, len(pairs) * max_count * max_count, "opp_quad")
    model.Add(par_quad == sum(
        k * k * par_count_eq[(i, j), k]
        for (i, j) in pairs for k in range(max_count + 1)))
    model.Add(opp_quad == sum(
        k * k * opp_count_eq[(i, j), k]
        for (i, j) in pairs for k in range(max_count + 1)))

    # --- Symmetry breaking (anchor) ---
    # Team 1 plays in match 0 on side A.
    # Breaks color symmetry and partially breaks the team-1 placement
    # symmetry. Doesn't over-constrain — feasibility only requires that
    # *some* team plays in match 0 on side A, which is always true.
    model.Add(in_match[0, 1] == 1)
    model.Add(on_side[0, 1] == 1)

    # --- Objective ---
    model.Minimize(par_quad)

    return model, {
        'in_match': in_match,
        'on_side': on_side,
        'on_A': on_A,
        'on_B': on_B,
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


def solve_and_report(n_teams, matches_per_team, teams_per_alliance=3,
                     cooldown=1, time_limit_s=60.0, n_workers=8,
                     log_progress=False):
    print(f"Building CP-SAT v2 model for {n_teams}t × {matches_per_team}MPT × "
          f"{teams_per_alliance}tpa, cooldown={cooldown}...")
    t0 = time.time()
    model, vars, meta = build_pairing_model_v2(
        n_teams, matches_per_team, teams_per_alliance, cooldown)
    build_time = time.time() - t0
    print(f"  Model built in {build_time:.1f}s")
    print(f"  {meta['n_matches']} matches, {meta['n_pairs']} pairs")
    proto = model.Proto()
    print(f"  Variables: {len(proto.variables)}, constraints: {len(proto.constraints)}")

    print(f"\nSolving (time_limit={time_limit_s}s, workers={n_workers})...")
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_search_workers = n_workers
    solver.parameters.log_search_progress = log_progress

    t0 = time.time()
    status = solver.Solve(model)
    solve_time = time.time() - t0

    status_name = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE (time limit)",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
        cp_model.UNKNOWN: "UNKNOWN",
    }.get(status, f"status={status}")
    print(f"  Status: {status_name}; Solve time: {solve_time:.1f}s")
    print(f"  Best bound: {solver.BestObjectiveBound()}")

    out = {
        'n_teams': n_teams, 'matches_per_team': matches_per_team,
        'cooldown': cooldown,
        'build_time_s': round(build_time, 2),
        'solve_time_s': round(solve_time, 2),
        'status': status_name,
        'num_vars': len(proto.variables),
        'num_constraints': len(proto.constraints),
        'best_bound': solver.BestObjectiveBound() if status != cp_model.INFEASIBLE else None,
    }
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        out['par_quad'] = solver.Value(vars['par_quad'])
        out['opp_quad'] = solver.Value(vars['opp_quad'])
        par_dist = {}
        for (i, j), v in vars['par_count'].items():
            c = solver.Value(v)
            par_dist[c] = par_dist.get(c, 0) + 1
        opp_dist = {}
        for (i, j), v in vars['opp_count'].items():
            c = solver.Value(v)
            opp_dist[c] = opp_dist.get(c, 0) + 1
        out['par_dist'] = par_dist
        out['opp_dist'] = opp_dist
        print(f"\nResults:")
        print(f"  par_quad: {out['par_quad']}")
        print(f"  opp_quad: {out['opp_quad']}")
        print(f"  partner distribution: {sorted(par_dist.items())}")
        print(f"  opponent distribution: {sorted(opp_dist.items())}")

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--teams', type=int, required=True)
    ap.add_argument('--mpt', type=int, required=True)
    ap.add_argument('--tpa', type=int, default=3)
    ap.add_argument('--cooldown', type=int, default=1)
    ap.add_argument('--time-limit', type=float, default=60.0)
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--log', action='store_true')
    args = ap.parse_args()
    return solve_and_report(args.teams, args.mpt, args.tpa, args.cooldown,
                            args.time_limit, args.workers, log_progress=args.log)


if __name__ == '__main__':
    main()
