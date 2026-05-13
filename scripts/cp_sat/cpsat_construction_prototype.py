#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""F1-c: CP-SAT-as-construction prototype.

Tests the Q4 architectural hypothesis: for fixtures where greedy
construction can't satisfy paramount cooldown (per F1-a finding), does
CP-SAT-as-construction + SA-refinement produce strictly better
schedules than SA-on-greedy?

Two arms per fixture, 5 seeds each:

  Arm A (CP-SAT-then-SA):
    1. CP-SAT solves pairing to feasibility/optimum at cooldown=2
    2. Random alliance + station assignment (commutative with pairing)
    3. R/B post-pass (whole-alliance color flip; pairing-safe)
    4. Station post-pass (within-alliance station permutation;
       pairing-safe and color-safe)
    5. SA refinement (500K iterations; cooldown filter active)
    6. Score via app.quality.analyze_against_thresholds(cooldown=2)

  Arm B (greedy-then-SA, the existing pipeline):
    1. greedy construction at cooldown=2 (via generate_matches, but
       with n_sa_iterations=0 so we get pre-SA construction output)
    2. R/B post-pass
    3. Station post-pass
    4. SA refinement (500K iterations; same as Arm A)
    5. Score

Fixtures (all at cooldown=2, the D5 project default):
  - 12×6×3 (tight; SA-on-greedy fails per F1-a)
  - 16×6×3 (sub-medium)
  - 24×6×3 (standard regional)
  - 36×7×3 (state event, 2026mnst shape)
  - 42×11×3 (championship division)
  - 48×9×3 (mid-size championship; 51×9 wanted but isn't divisible-by-6
              so CP-SAT formulation can't handle it without surrogates)

Output:
  - JSON results to scripts/scheduler_eval/reports/f1c_<timestamp>.json
  - Markdown summary to same dir

Run:
  python3 scripts/cp_sat/cpsat_construction_prototype.py
  python3 scripts/cp_sat/cpsat_construction_prototype.py --fixtures 12x6,16x6
  python3 scripts/cp_sat/cpsat_construction_prototype.py --seeds 3
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ortools.sat.python import cp_model  # noqa: E402

from app.scheduler import (  # noqa: E402
    Match,
    generate_matches,
    score_tuple_for_schedule,
    _sa_optimize,
    ConstructionMalformedError,
)
from app.post_passes.rb_balance import rb_balance_sa  # noqa: E402
from app.post_passes.station_balance import station_balance_sa  # noqa: E402
from app.quality import analyze_against_thresholds, composite_score  # noqa: E402
from scripts.cp_sat.pairing_optimum import build_pairing_model  # noqa: E402


# ── Fixture inventory ────────────────────────────────────────────────────


FIXTURES = [
    # (n, mpt, tpa, cpsat_time_limit_s, name)
    # CP-SAT times are budget for full optimality proof. CP-SAT typically
    # finds a FEASIBLE solution very fast and spends the rest of the budget
    # trying to prove optimality on par_quad. For F1-c we mostly care about
    # whether CP-SAT can find ANY cd=0 schedule (validity), so the time
    # budget here is generous enough to find feasibility on each fixture
    # but not so generous that one trial dominates wall-clock.
    (12, 6, 3,  60.0, "12x6"),
    (16, 6, 3,  60.0, "16x6"),
    (24, 6, 3,  60.0, "24x6"),
    (36, 7, 3, 120.0, "36x7"),
    (42, 11, 3, 240.0, "42x11"),
    (48, 9, 3, 240.0, "48x9"),
]


# ── CP-SAT construction ──────────────────────────────────────────────────


def cpsat_pairing(n_teams: int, mpt: int, tpa: int,
                  cooldown: int, time_limit_s: float,
                  seed: int) -> tuple[list[Match], dict]:
    """Run CP-SAT to produce an abstract pairing for the fixture.

    Returns (matches, meta_dict). The Match list has random alliance
    assignment for the colors (red vs blue) and random station
    permutation within each alliance — both will be optimized by the
    post-passes. The pairing decisions (who's with whom, who's against
    whom) come from CP-SAT.

    Raises RuntimeError if CP-SAT can't find any feasible solution
    within time_limit_s — that's a useful F1-c data point but it means
    we can't run the rest of the pipeline for this trial.
    """
    t0 = time.time()
    model, vars, meta = build_pairing_model(n_teams, mpt, tpa, cooldown,
                                            time_limit_s=time_limit_s)
    build_time = time.time() - t0

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_search_workers = 8
    solver.parameters.log_search_progress = False
    solver.parameters.random_seed = seed  # influence which solution we get

    t0 = time.time()
    status = solver.Solve(model)
    solve_time = time.time() - t0

    status_name = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE (time limit)",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.UNKNOWN: "UNKNOWN (timed out before any solution)",
    }.get(status, f"status={status}")

    cpsat_meta = {
        'build_time_s':  round(build_time, 2),
        'solve_time_s':  round(solve_time, 2),
        'status':        status_name,
        'optimality_proven':  status == cp_model.OPTIMAL,
    }

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(
            f"CP-SAT didn't find a feasible solution: {status_name} in {solve_time:.1f}s"
        )

    cpsat_meta['par_quad_cpsat']  = solver.Value(vars['par_quad'])
    cpsat_meta['opp_quad_cpsat']  = solver.Value(vars['opp_quad'])

    # Extract abstract pairing from the solver. For each match m,
    # in_match[m, t] tells us if team t is in match m. on_side[m, t]
    # tells us which side (only meaningful when in_match[m, t]).
    rng = random.Random(seed)
    matches: list[Match] = []
    for m in range(meta['n_matches']):
        side_a_teams = []
        side_b_teams = []
        for t in range(1, n_teams + 1):
            if solver.Value(vars['in_match'][m, t]):
                if solver.Value(vars['on_side'][m, t]):
                    side_a_teams.append(t)
                else:
                    side_b_teams.append(t)
        assert len(side_a_teams) == tpa, \
            f"match {m}: side A has {len(side_a_teams)} teams, expected {tpa}"
        assert len(side_b_teams) == tpa, \
            f"match {m}: side B has {len(side_b_teams)} teams, expected {tpa}"

        # CP-SAT's "side A" / "side B" is an arbitrary color label per match.
        # We randomly assign which one becomes red for *this* construction —
        # the R/B post-pass will optimize it afterward.
        if rng.random() < 0.5:
            red, blue = side_a_teams, side_b_teams
        else:
            red, blue = side_b_teams, side_a_teams

        # Random station permutation within each alliance — the station
        # post-pass will optimize it afterward.
        rng.shuffle(red)
        rng.shuffle(blue)

        matches.append(Match(
            red=tuple(red),
            blue=tuple(blue),
            red_surrogate=(False,) * tpa,
            blue_surrogate=(False,) * tpa,
        ))

    return matches, cpsat_meta


# ── Greedy construction (comparator) ─────────────────────────────────────


def greedy_construction(n_teams: int, mpt: int, tpa: int,
                        cooldown: int, seed: int) -> tuple[list[Match], dict]:
    """Run the existing greedy construction + the post-passes the SA
    would normally run, but stop short of SA refinement.

    Uses generate_matches with n_sa_iterations=0 so we get only the
    construction output (plus the construction-time R/B and station
    post-passes which generate_matches always runs). Then we'll add a
    matching SA refinement pass to match Arm A's pipeline shape.

    Raises ConstructionMalformedError if greedy can't produce a
    well-formed schedule (the F2 finding's mode). The caller retries
    with a different seed.
    """
    t0 = time.time()
    # ideal_gap is `cooldown` in this codebase's terminology (the cooldown
    # value the SA filter enforces). tpa is fixed at 3 in generate_matches.
    assert tpa == 3, "generate_matches hard-codes tpa=3"
    result = generate_matches(
        num_teams=n_teams,
        matches_per_team=mpt,
        ideal_gap=cooldown,
        seed=seed,
        team_numbers=list(range(1, n_teams + 1)),
        n_sa_iterations=0,            # no SA — we'll add it ourselves below
        rb_post_pass=True,            # match the F1-c Arm A pipeline
        station_post_pass=True,       # match the F1-c Arm A pipeline
    )
    construction_time = time.time() - t0

    return list(result.matches), {
        'construction_time_s': round(construction_time, 2),
    }


# ── Pipeline stages used by both arms ────────────────────────────────────


def run_rb_post_pass(matches: list[Match],
                     seed: int) -> tuple[list[Match], dict]:
    """Run R/B balance post-pass on the matches. Whole-alliance color
    flip only; pairings preserved by construction."""
    t0 = time.time()
    out, stats = rb_balance_sa(matches, n_iterations=5000, seed=seed)
    return out, {
        'rb_post_pass_time_s': round(time.time() - t0, 2),
        'rb_stats':            stats,
    }


def run_station_post_pass(matches: list[Match],
                          seed: int) -> tuple[list[Match], dict]:
    """Run station balance post-pass on the matches. Within-alliance
    station permutation only; pairings and colors preserved by
    construction."""
    t0 = time.time()
    out, stats = station_balance_sa(matches, n_iterations=5000, seed=seed)
    return out, {
        'station_post_pass_time_s': round(time.time() - t0, 2),
        'station_stats':            stats,
    }


def run_sa_refinement(matches: list[Match],
                      n_iterations: int,
                      seed: int,
                      cooldown: int) -> tuple[list[Match], dict]:
    """Run SA refinement on a feasible (cd=0) schedule.

    SA's _swap_preserves_cooldown filter (verified in F1-a) prevents
    accepting any swap that worsens cooldown, so cd=0 input stays
    cd=0 output. This refines pairing quality further while preserving
    paramount validity.

    Threads `cooldown` through as the `ideal_gap` parameter on
    _sa_optimize — this is critical because _build_match_state defaults
    ideal_gap=3 which would mis-count gap=2 cases as violations and
    mis-protect cooldown=3 instead of cooldown=2.
    """
    t0 = time.time()
    rng = random.Random(seed)
    out = _sa_optimize(matches, n_iterations=n_iterations, rng=rng,
                       ideal_gap=cooldown)
    return out, {
        'sa_refinement_time_s': round(time.time() - t0, 2),
        'sa_iterations':        n_iterations,
    }


# ── Per-trial driver ─────────────────────────────────────────────────────


def run_arm_a(n_teams: int, mpt: int, tpa: int, cooldown: int,
              cpsat_time_limit_s: float,
              seed: int, sa_iterations: int) -> dict:
    """Run the CP-SAT-then-SA arm. Returns a per-trial result dict."""
    out: dict[str, Any] = {
        'arm': 'cpsat_then_sa',
        'seed': seed,
    }
    try:
        # 1. CP-SAT
        matches, cpsat_meta = cpsat_pairing(
            n_teams=n_teams, mpt=mpt, tpa=tpa, cooldown=cooldown,
            time_limit_s=cpsat_time_limit_s, seed=seed,
        )
        out.update(cpsat_meta)
    except Exception as e:
        out['error'] = f"cpsat_pairing failed: {type(e).__name__}: {e}"
        out['ok'] = False
        return out

    # Score immediately after CP-SAT, before any post-pass — gives the
    # par_quad baseline that the rest of the pipeline can only improve
    # within the constraints imposed by the construction.
    pre_postpass_tuple = score_tuple_for_schedule(
        matches, num_teams=n_teams, ideal_gap=cooldown
    )
    out['lex_tuple_after_cpsat'] = list(pre_postpass_tuple)

    # 2. R/B post-pass
    matches, rb_meta = run_rb_post_pass(matches, seed=seed)
    out.update(rb_meta)

    # 3. Station post-pass
    matches, station_meta = run_station_post_pass(matches, seed=seed)
    out.update(station_meta)

    pre_sa_tuple = score_tuple_for_schedule(
        matches, num_teams=n_teams, ideal_gap=cooldown
    )
    out['lex_tuple_after_postpasses'] = list(pre_sa_tuple)

    # 4. SA refinement
    matches, sa_meta = run_sa_refinement(matches, n_iterations=sa_iterations,
                                          seed=seed, cooldown=cooldown)
    out.update(sa_meta)

    # 5. Score
    final_tuple = score_tuple_for_schedule(
        matches, num_teams=n_teams, ideal_gap=cooldown
    )
    out['lex_tuple_final'] = list(final_tuple)

    # 6. F1-e validity check + composite via harness
    report = analyze_against_thresholds(
        matches, num_teams=n_teams, matches_per_team=mpt,
        teams_per_alliance=tpa, team_numbers=list(range(1, n_teams + 1)),
        fixture_id=f"{n_teams}x{mpt}",
        adapter_name='cpsat_then_sa',
        cooldown=cooldown,
    )
    out['composite_score']   = composite_score(report)
    out['is_valid_paramount'] = report.is_valid_paramount
    out['cooldown_violations'] = report.cooldown_violations
    out['analysis']           = report.to_dict()
    out['ok']                 = True
    return out


def run_arm_b(n_teams: int, mpt: int, tpa: int, cooldown: int,
              seed: int, sa_iterations: int,
              max_construction_attempts: int = 20) -> dict:
    """Run the greedy-then-SA arm. Returns a per-trial result dict.

    Retries greedy construction on ConstructionMalformedError up to
    `max_construction_attempts` times with different seeds — that's
    the same retry behavior tests/test_match_sa.py uses to handle the
    F2 malformation finding on tight fixtures.
    """
    out: dict[str, Any] = {
        'arm': 'greedy_then_sa',
        'seed': seed,
    }

    construction_attempts = 0
    matches = None
    construction_meta: dict[str, Any] = {}
    last_err: str | None = None
    for attempt in range(max_construction_attempts):
        construction_attempts += 1
        attempt_seed = seed + attempt * 7919
        try:
            matches, construction_meta = greedy_construction(
                n_teams=n_teams, mpt=mpt, tpa=tpa,
                cooldown=cooldown, seed=attempt_seed,
            )
            break
        except ConstructionMalformedError as e:
            last_err = f"{type(e).__name__}: {e}"
            continue
        except Exception as e:
            out['error'] = f"greedy_construction failed: {type(e).__name__}: {e}"
            out['ok'] = False
            return out

    if matches is None:
        out['error'] = (f"greedy_construction malformed after "
                        f"{max_construction_attempts} attempts: {last_err}")
        out['ok'] = False
        return out

    out['construction_attempts'] = construction_attempts
    out.update(construction_meta)

    pre_sa_tuple = score_tuple_for_schedule(
        matches, num_teams=n_teams, ideal_gap=cooldown
    )
    out['lex_tuple_after_postpasses'] = list(pre_sa_tuple)

    # SA refinement (matches Arm A's iteration count)
    matches, sa_meta = run_sa_refinement(matches, n_iterations=sa_iterations,
                                          seed=seed, cooldown=cooldown)
    out.update(sa_meta)

    final_tuple = score_tuple_for_schedule(
        matches, num_teams=n_teams, ideal_gap=cooldown
    )
    out['lex_tuple_final'] = list(final_tuple)

    report = analyze_against_thresholds(
        matches, num_teams=n_teams, matches_per_team=mpt,
        teams_per_alliance=tpa, team_numbers=list(range(1, n_teams + 1)),
        fixture_id=f"{n_teams}x{mpt}",
        adapter_name='greedy_then_sa',
        cooldown=cooldown,
    )
    out['composite_score']    = composite_score(report)
    out['is_valid_paramount'] = report.is_valid_paramount
    out['cooldown_violations'] = report.cooldown_violations
    out['analysis']           = report.to_dict()
    out['ok']                 = True
    return out


# ── Reporting ────────────────────────────────────────────────────────────


def summarize_trials(trials: list[dict]) -> dict:
    """Aggregate per-arm-per-fixture trials into headline stats."""
    successful = [t for t in trials if t.get('ok')]
    failed = [t for t in trials if not t.get('ok')]

    summary: dict[str, Any] = {
        'n_trials':       len(trials),
        'n_successful':   len(successful),
        'n_failed':       len(failed),
        'failure_modes':  [t.get('error') for t in failed],
    }
    if not successful:
        return summary

    # is_valid_paramount distribution
    n_valid = sum(1 for t in successful if t.get('is_valid_paramount') is True)
    summary['n_valid_paramount'] = n_valid

    # composite_score range (excluding inf)
    composites = [t['composite_score'] for t in successful
                  if t['composite_score'] != float('inf')]
    if composites:
        summary['composite_min']    = round(min(composites), 2)
        summary['composite_max']    = round(max(composites), 2)
        summary['composite_median'] = round(sorted(composites)[len(composites) // 2], 2)
    else:
        summary['composite_min']    = None
        summary['composite_max']    = None
        summary['composite_median'] = None

    # lex tuple components, median over successful trials
    for idx, name in [(0, 'cooldown_violations'), (1, 'par_quad'),
                      (2, 'opp_quad'), (4, 'rb_metric'),
                      (5, 'station_pen')]:
        vals = sorted(t['lex_tuple_final'][idx] for t in successful)
        summary[f'{name}_median'] = vals[len(vals) // 2]
        summary[f'{name}_min']    = vals[0]
        summary[f'{name}_max']    = vals[-1]

    return summary


def write_markdown_report(report_data: dict, out_path: Path) -> None:
    """Write a human-readable summary."""
    lines: list[str] = []
    lines.append(f"# F1-c: CP-SAT-as-construction prototype results")
    lines.append("")
    lines.append(f"Run at: {report_data['started']}")
    lines.append(f"Elapsed: {report_data['elapsed_s']}s "
                 f"({report_data['elapsed_s']/60:.1f} min)")
    lines.append(f"SA iterations: {report_data['sa_iterations']}")
    lines.append(f"Seeds per arm per fixture: {report_data['n_seeds']}")
    lines.append(f"Cooldown (paramount floor): {report_data['cooldown']}")
    lines.append("")
    lines.append("## Headline by fixture")
    lines.append("")
    lines.append("`par_quad` lower is better (criterion 2: partner diversity); "
                 "`opp_quad` lower is better (criterion 3: opponent diversity); "
                 "`station_pen` lower is better (criterion 6: even distribution "
                 "across the 6 station-color positions). `cd_viol > 0` means "
                 "schedule is paramount-invalid per ADR 002.")
    lines.append("")
    lines.append("| Fixture | Arm | Valid | cd_viol(med) | par_quad(med) | opp_quad(med) | rb(med) | station(med) | composite(med) |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for fixture_name, fixture_data in report_data['fixtures'].items():
        for arm_name in ['cpsat_then_sa', 'greedy_then_sa']:
            s = fixture_data['summaries'].get(arm_name)
            if not s:
                continue
            row = (
                f"| {fixture_name} "
                f"| {arm_name.replace('_then_sa', '+sa').replace('greedy', 'gr').replace('cpsat', 'cp')} "
                f"| {s.get('n_valid_paramount', 'n/a')}/{s.get('n_trials', 'n/a')} "
                f"| {s.get('cooldown_violations_median', 'n/a')} "
                f"| {s.get('par_quad_median', 'n/a')} "
                f"| {s.get('opp_quad_median', 'n/a')} "
                f"| {s.get('rb_metric_median', 'n/a')} "
                f"| {s.get('station_pen_median', 'n/a')} "
                f"| {s.get('composite_median', 'n/a')} |"
            )
            lines.append(row)
    lines.append("")
    lines.append("## Detail by fixture")
    lines.append("")
    for fixture_name, fixture_data in report_data['fixtures'].items():
        lines.append(f"### {fixture_name}")
        lines.append("")
        n, mpt, tpa = fixture_data['shape']
        lines.append(f"Shape: {n} teams × {mpt} matches/team × {tpa} per alliance. "
                     f"Total matches: {fixture_data['total_matches']}. "
                     f"cooldown_max: {fixture_data['cooldown_max']}. "
                     f"CP-SAT time limit: {fixture_data['cpsat_time_limit_s']}s.")
        lines.append("")
        for arm_name in ['cpsat_then_sa', 'greedy_then_sa']:
            s = fixture_data['summaries'].get(arm_name)
            if not s:
                continue
            lines.append(f"**{arm_name}**:")
            lines.append(f"- Trials: {s['n_successful']}/{s['n_trials']} successful")
            if s['n_failed']:
                lines.append(f"- Failures: {s['failure_modes']}")
            if s['n_successful']:
                lines.append(f"- Valid (paramount): {s['n_valid_paramount']}/{s['n_successful']}")
                lines.append(f"- cooldown_violations: min {s['cooldown_violations_min']}, median {s['cooldown_violations_median']}, max {s['cooldown_violations_max']}")
                lines.append(f"- par_quad: min {s['par_quad_min']}, median {s['par_quad_median']}, max {s['par_quad_max']}")
                lines.append(f"- opp_quad: min {s['opp_quad_min']}, median {s['opp_quad_median']}, max {s['opp_quad_max']}")
                lines.append(f"- station_pen: min {s['station_pen_min']}, median {s['station_pen_median']}, max {s['station_pen_max']}")
                lines.append(f"- composite_score: min {s['composite_min']}, median {s['composite_median']}, max {s['composite_max']}")
            lines.append("")
    out_path.write_text("\n".join(lines))


# ── Main ─────────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fixtures', type=str, default='all',
                    help="Comma-separated fixture names (e.g. '12x6,16x6') "
                         "or 'all'.")
    ap.add_argument('--seeds', type=int, default=5,
                    help="Seeds per arm per fixture.")
    ap.add_argument('--sa-iterations', type=int, default=500_000,
                    help="SA refinement iteration count.")
    ap.add_argument('--cooldown', type=int, default=2,
                    help="Paramount cooldown floor (D5 default 2).")
    ap.add_argument('--out-dir', type=str,
                    default=str(_REPO_ROOT / 'scripts/scheduler_eval/reports'))
    args = ap.parse_args()

    if args.fixtures == 'all':
        fixtures = FIXTURES
    else:
        wanted = set(args.fixtures.split(','))
        fixtures = [f for f in FIXTURES if f[4] in wanted]
        if not fixtures:
            print(f"No fixtures matched: {args.fixtures}")
            sys.exit(1)

    started = datetime.now().strftime('%Y%m%d-%H%M%S')
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f'f1c_cpsat_construction_{started}.json'
    md_path   = out_dir / f'f1c_cpsat_construction_{started}.md'
    log_path  = out_dir / f'f1c_cpsat_construction_{started}.log'

    log_lines: list[str] = []
    def log(msg: str) -> None:
        print(msg, flush=True)
        log_lines.append(msg)

    log(f"F1-c CP-SAT-as-construction prototype")
    log(f"Started: {started}")
    log(f"Fixtures: {[f[4] for f in fixtures]}")
    log(f"Seeds per arm: {args.seeds}")
    log(f"SA iterations: {args.sa_iterations}")
    log(f"Cooldown: {args.cooldown}")
    log("=" * 70)

    report: dict[str, Any] = {
        'started':       started,
        'sa_iterations': args.sa_iterations,
        'n_seeds':       args.seeds,
        'cooldown':      args.cooldown,
        'fixtures':      {},
    }

    overall_t0 = time.time()
    for (n, mpt, tpa, cpsat_tl, fname) in fixtures:
        log(f"\n=== Fixture {fname} ({n}t × {mpt}mpt × {tpa}tpa) ===")
        import math as _math
        total_matches = _math.ceil(n * mpt / (2 * tpa))
        cooldown_max  = (total_matches - 1) // (mpt - 1) if mpt >= 2 else total_matches
        log(f"  total matches: {total_matches}, cooldown_max: {cooldown_max}, "
            f"CP-SAT time limit: {cpsat_tl}s")

        fixture_data: dict[str, Any] = {
            'shape':                (n, mpt, tpa),
            'total_matches':        total_matches,
            'cooldown_max':         cooldown_max,
            'cpsat_time_limit_s':   cpsat_tl,
            'trials':               {'cpsat_then_sa': [], 'greedy_then_sa': []},
            'summaries':            {},
        }

        # Arm A — CP-SAT then SA
        log(f"\n  Arm A (CP-SAT then SA), {args.seeds} seeds:")
        for s in range(args.seeds):
            seed = 10_000 * (fixtures.index((n, mpt, tpa, cpsat_tl, fname)) + 1) + s
            log(f"    seed={seed} ...")
            t0 = time.time()
            trial = run_arm_a(n, mpt, tpa, args.cooldown, cpsat_tl, seed,
                              sa_iterations=args.sa_iterations)
            wall = time.time() - t0
            trial['wall_clock_s'] = round(wall, 1)
            fixture_data['trials']['cpsat_then_sa'].append(trial)
            if trial.get('ok'):
                lt = trial.get('lex_tuple_final', [])
                cs = trial.get('composite_score', '?')
                ip = trial.get('is_valid_paramount', '?')
                log(f"      → wall={wall:.1f}s, lex={lt[:3]}..., comp={cs}, valid={ip}")
            else:
                log(f"      → wall={wall:.1f}s, FAILED: {trial.get('error')}")

        # Arm B — greedy then SA
        log(f"\n  Arm B (greedy then SA), {args.seeds} seeds:")
        for s in range(args.seeds):
            seed = 20_000 * (fixtures.index((n, mpt, tpa, cpsat_tl, fname)) + 1) + s
            log(f"    seed={seed} ...")
            t0 = time.time()
            trial = run_arm_b(n, mpt, tpa, args.cooldown, seed,
                              sa_iterations=args.sa_iterations)
            wall = time.time() - t0
            trial['wall_clock_s'] = round(wall, 1)
            fixture_data['trials']['greedy_then_sa'].append(trial)
            if trial.get('ok'):
                lt = trial.get('lex_tuple_final', [])
                cs = trial.get('composite_score', '?')
                ip = trial.get('is_valid_paramount', '?')
                log(f"      → wall={wall:.1f}s, lex={lt[:3]}..., comp={cs}, valid={ip}")
            else:
                log(f"      → wall={wall:.1f}s, FAILED: {trial.get('error')}")

        fixture_data['summaries']['cpsat_then_sa']  = summarize_trials(
            fixture_data['trials']['cpsat_then_sa']
        )
        fixture_data['summaries']['greedy_then_sa'] = summarize_trials(
            fixture_data['trials']['greedy_then_sa']
        )

        log(f"\n  Summary for {fname}:")
        for arm_name in ['cpsat_then_sa', 'greedy_then_sa']:
            s = fixture_data['summaries'][arm_name]
            log(f"    {arm_name}: {s['n_successful']}/{s['n_trials']} ok, "
                f"valid={s.get('n_valid_paramount', '?')}, "
                f"par_quad median={s.get('par_quad_median', '?')}, "
                f"composite median={s.get('composite_median', '?')}")

        report['fixtures'][fname] = fixture_data

        # Write partial results after each fixture so we don't lose data
        # if a later fixture times out or fails.
        report['elapsed_s'] = round(time.time() - overall_t0, 1)
        json_path.write_text(json.dumps(report, indent=2, default=str))
        log_path.write_text("\n".join(log_lines))
        write_markdown_report(report, md_path)

    elapsed = time.time() - overall_t0
    report['elapsed_s'] = round(elapsed, 1)

    log(f"\n{'=' * 70}")
    log(f"Total elapsed: {elapsed:.1f}s ({elapsed / 60:.1f} min)")

    # Save outputs
    json_path.write_text(json.dumps(report, indent=2, default=str))
    log_path.write_text("\n".join(log_lines))
    write_markdown_report(report, md_path)

    log(f"\nReports written to:")
    log(f"  {json_path}")
    log(f"  {md_path}")
    log(f"  {log_path}")


if __name__ == '__main__':
    main()
