#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Iteration sweep — find K* for the FRC-paramount lex SA.

Tight criterion (per user direction): K* is the smallest iteration count
where the mean improvement at the next level is less than one standard
deviation at the current level. Past K*, additional iterations buy
randomness, not quality.

Because the score is a lex tuple (not a scalar), "improvement" is
analyzed per criterion. We focus on the lex element that's the
*current bottleneck* — the highest-priority element that's still being
optimized. For a 36-team / MPT=7 schedule with all phases on, that's
typically par_quad first (until floor 252) then opp_quad.

Usage:
    python3 scripts/iteration_sweep.py \\
        --fixture 2026mnst \\
        --trials 30 \\
        --levels 10000,50000,200000,500000,1000000,2000000,5000000 \\
        --workers 36

Designed for parallel execution on Stark (36 physical cores). Uses
multiprocessing.Pool to run trials in parallel — each trial is one
worker, so total wall-clock = (longest-trial-time × n_levels × n_trials) / n_workers.

Output JSON contains per-level statistics for every lex tuple element
plus a K* recommendation. Print summary table to stdout.
"""

import argparse
import json
import multiprocessing as mp
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Repo root → sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from app.scheduler import generate_matches, score_tuple_for_schedule
from scripts.scheduler_eval.harness_types import Fixture


# Lex tuple element names — keep in sync with _score_from_state in app/scheduler.py
LEX_ELEMENTS = [
    'cooldown_violations',  # FRC #1
    'par_quad',             # FRC #2
    'opp_quad',             # FRC #3
    'surrogate_count',      # FRC #4
    'rb_metric',            # FRC #5
    'station_pen',          # FRC #6
    'surrogate_spread',     # P11 (#7)
    'match_equity',         # P5 (#8)
]


def _run_one_trial(args):
    fixture_path, n_sa, seed, rb_pass, station_pass = args
    f = Fixture.load(fixture_path)
    t0 = time.monotonic()
    result = generate_matches(
        num_teams=f.num_teams,
        matches_per_team=f.matches_per_team,
        ideal_gap=3,
        seed=seed,
        team_numbers=list(f.teams),
        n_sa_iterations=n_sa,
        rb_post_pass=rb_pass,
        station_post_pass=station_pass,
    )
    elapsed = time.monotonic() - t0
    tup = score_tuple_for_schedule(result.matches, f.num_teams)
    return {
        'seed':    seed,
        'tuple':   list(tup),
        'elapsed': elapsed,
    }


def _stats(values):
    """Return mean, stdev, min, max, p25, p50, p75 of a list."""
    if not values:
        return {'mean': 0, 'stdev': 0, 'min': 0, 'max': 0,
                'p25': 0, 'p50': 0, 'p75': 0}
    s = sorted(values)
    n = len(s)
    if n == 1:
        return {'mean': s[0], 'stdev': 0, 'min': s[0], 'max': s[0],
                'p25': s[0], 'p50': s[0], 'p75': s[0]}
    quartiles = statistics.quantiles(s, n=4)
    return {
        'mean':  statistics.mean(s),
        'stdev': statistics.stdev(s),
        'min':   s[0],
        'max':   s[-1],
        'p25':   quartiles[0],
        'p50':   statistics.median(s),
        'p75':   quartiles[2],
    }


def _identify_bottleneck(per_level_stats: dict, levels: list[int]) -> int:
    """Find which lex element is currently the active optimization target.

    For each lex index, find the smallest level where mean equals the
    floor (i.e., the SA has already converged on that criterion). The
    bottleneck is the smallest index that hasn't converged at the
    largest tested level.
    """
    largest_level = str(levels[-1])
    largest = per_level_stats[largest_level]
    smallest_level = str(levels[0])
    smallest = per_level_stats[smallest_level]
    for idx, name in enumerate(LEX_ELEMENTS):
        # If this element's mean dropped from smallest level to largest level,
        # it's still being optimized.
        if largest[name]['mean'] < smallest[name]['mean']:
            return idx
        # If this element has nonzero stdev at largest level, it's varying
        # — also "active."
        if largest[name]['stdev'] > 0.5:
            return idx
    # All elements converged. Bottleneck is the first non-zero one.
    for idx, name in enumerate(LEX_ELEMENTS):
        if largest[name]['mean'] > 0:
            return idx
    return 0


def _find_k_star(per_level_stats: dict, levels: list[int],
                 bottleneck_idx: int) -> tuple[int | None, str]:
    """Find K* per tight criterion on the bottleneck lex element.

    Tight criterion: smallest K where mean improvement at next level
    is less than stdev at K.

    Returns (K*, bottleneck_name). K* may be None if no level satisfies
    the criterion within the tested range.
    """
    bn = LEX_ELEMENTS[bottleneck_idx]
    for i in range(len(levels) - 1):
        cur_level = levels[i]
        next_level = levels[i + 1]
        cur = per_level_stats[str(cur_level)][bn]
        nxt = per_level_stats[str(next_level)][bn]
        improvement = cur['mean'] - nxt['mean']  # lower mean = better
        stdev_here = cur['stdev']
        if improvement < stdev_here:
            return cur_level, bn
    return None, bn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fixture', default='2026mnst', help='fixture name (without .json)')
    ap.add_argument('--trials', type=int, default=30, help='trials per iteration level')
    ap.add_argument('--levels', default='10000,50000,200000,500000,1000000,2000000,5000000',
                    help='comma-separated iteration levels')
    ap.add_argument('--workers', type=int, default=mp.cpu_count(), help='parallel workers')
    ap.add_argument('--rb-pass', action='store_true', default=True,
                    help='run R/B post-pass (Phase 1)')
    ap.add_argument('--no-rb-pass', action='store_false', dest='rb_pass')
    ap.add_argument('--station-pass', action='store_true', default=True,
                    help='run station post-pass (Phase 2)')
    ap.add_argument('--no-station-pass', action='store_false', dest='station_pass')
    ap.add_argument('--out', default='iteration_sweep_results.json', help='output JSON path')
    args = ap.parse_args()

    fixture_path = _REPO_ROOT / 'scripts' / 'scheduler_eval' / 'fixtures' / f'{args.fixture}.json'
    if not fixture_path.exists():
        print(f"ERROR: fixture not found: {fixture_path}", file=sys.stderr)
        sys.exit(1)

    levels = [int(x.strip()) for x in args.levels.split(',')]

    print(f"Fixture: {args.fixture}")
    print(f"Trials per level: {args.trials}")
    print(f"Levels: {levels}")
    print(f"Workers: {args.workers}")
    print(f"R/B post-pass: {args.rb_pass}")
    print(f"Station post-pass: {args.station_pass}")
    print(f"All phases on: 0a (lex score) + 0b (hard cooldown) + 0c (targeted moves) "
          f"+ 1 (R/B) + 2 (station)")
    print()

    work_units = []
    for n_sa in levels:
        for trial in range(args.trials):
            # Per-trial seed: ensure different trials get different seeds
            # but keep deterministic given level + trial.
            seed = (n_sa * 7919 + trial * 31337 + 42) & 0x7FFFFFFF
            work_units.append((str(fixture_path), n_sa, seed,
                              args.rb_pass, args.station_pass))

    n_units = len(work_units)
    print(f"Total work units: {n_units}")
    t_start = time.time()
    with mp.Pool(args.workers) as pool:
        results = pool.map(_run_one_trial, work_units)
    elapsed = time.time() - t_start
    print(f"Wall-clock: {elapsed:.1f}s ({elapsed/60:.1f}m)")
    print()

    # Aggregate per level
    by_level = {}
    for r, (_, n_sa, _, _, _) in zip(results, work_units):
        by_level.setdefault(n_sa, []).append(r)

    # Per-level stats per lex element
    per_level_stats = {}
    for level in sorted(by_level.keys()):
        rows = by_level[level]
        elapsed_seconds = [r['elapsed'] for r in rows]
        level_stats = {
            'trials': len(rows),
            'time_seconds': _stats(elapsed_seconds),
            'tuples': [r['tuple'] for r in rows],  # raw tuples for inspection
        }
        for idx, name in enumerate(LEX_ELEMENTS):
            vals = [r['tuple'][idx] for r in rows]
            level_stats[name] = _stats(vals)
        per_level_stats[str(level)] = level_stats

    # Find bottleneck and K*
    bottleneck_idx = _identify_bottleneck(per_level_stats, levels)
    bottleneck_name = LEX_ELEMENTS[bottleneck_idx]
    k_star, _ = _find_k_star(per_level_stats, levels, bottleneck_idx)

    summary = {
        'fixture':         args.fixture,
        'trials':          args.trials,
        'rb_post_pass':    args.rb_pass,
        'station_post_pass': args.station_pass,
        'phases_enabled':  ['0a_lex', '0b_cooldown_filter', '0c_targeted_moves',
                           '1_rb_post_pass', '2_station_post_pass'],
        'levels':          per_level_stats,
        'bottleneck':      bottleneck_name,
        'bottleneck_idx':  bottleneck_idx,
        'k_star':          k_star,
        'wall_clock_seconds': elapsed,
        'generated_at':    datetime.now(timezone.utc).isoformat(),
    }

    out_path = Path(args.out)
    with out_path.open('w') as f:
        json.dump(summary, f, indent=2)
    print(f"Saved: {out_path}\n")

    # ── Summary table ─────────────────────────────────────────────────
    print(f"Bottleneck criterion: {bottleneck_name} (lex index {bottleneck_idx})")
    print(f"K* (tight criterion): {k_star if k_star else 'NOT FOUND in tested range'}")
    print()
    print(f"{'level':>10} {'mean':>10} {'stdev':>10} {'min':>10} {'p50':>10} "
          f"{'best':>10} {'time(s)':>10}")
    print("-" * 76)
    for level in sorted(by_level.keys()):
        s = per_level_stats[str(level)]
        bn = s[bottleneck_name]
        ts = s['time_seconds']
        print(f"{level:>10} {bn['mean']:>10.1f} {bn['stdev']:>10.1f} "
              f"{bn['min']:>10.0f} {bn['p50']:>10.0f} {bn['min']:>10.0f} "
              f"{ts['mean']:>10.2f}")

    # Show the best tuple seen at each level
    print()
    print("Best lex tuple at each level (lower = better):")
    for level in sorted(by_level.keys()):
        rows = by_level[level]
        tuples = [tuple(r['tuple']) for r in rows]
        best = min(tuples)
        print(f"  {level:>10}: {best}")

    # If we have a comparison schedule (MatchMaker), show win rate
    print()
    print("Done.")


if __name__ == '__main__':
    main()
