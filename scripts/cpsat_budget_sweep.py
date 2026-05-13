#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Empirical sweep: characterize CP-SAT post-pass budget vs quality.

For each fixture in the standards inventory and each budget in
BUDGETS, run:
  1. SA construction + SA optimization (production path) WITHOUT
     the SA post-passes — get the "raw SA" baseline matches.
  2. Apply CP-SAT R/B + station post-passes at the given budget.
  3. Score the result via the Phase D framework (compute_metrics +
     apply_scores) → composite + per-criterion.
  4. Compare to: a parallel run with the SA post-passes (today's
     production behavior).

Output:
  - Per-fixture × per-budget table: composite, rb score, station
    score, solver wall time, solver status.
  - Summary: budget at which each fixture reliably hits the target
    composite (98 by default).

Usage:
  python3 scripts/cpsat_budget_sweep.py
  python3 scripts/cpsat_budget_sweep.py --budgets 10,60,300 --fixtures 12x6,24x8
  python3 scripts/cpsat_budget_sweep.py --seeds 3   # repeat per fixture for noise

The script writes a JSON report to
scripts/scheduler_eval/reports/cpsat_sweep_{timestamp}.json and prints
a Markdown summary to stdout.

Wall-clock budget for the full default sweep:
  - 5 fixtures × 5 budgets × 1 seed × (CP-SAT solve time + SA upstream)
  - Worst case 60×12 at 900s budget: ~15 min + ~5 min SA upstream
  - Total expected: ~1-2 hours
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.scheduler import generate_matches, score_tuple_for_schedule  # noqa: E402
from app.post_passes.cpsat_post_passes import (  # noqa: E402
    rb_balance_cpsat, station_balance_cpsat,
)
from app.post_passes.rb_balance import rb_balance_sa  # noqa: E402
from app.post_passes.station_balance import station_balance_sa  # noqa: E402
from app.quality_report import build_quality_report  # noqa: E402


def _matches_to_dicts(matches):
    """Convert Match namedtuples to dicts for quality_report consumption."""
    return [
        {
            'red':            list(m.red),
            'blue':           list(m.blue),
            'red_surrogate':  list(m.red_surrogate),
            'blue_surrogate': list(m.blue_surrogate),
        }
        for m in matches
    ]


def _score(matches, n, mpt, cooldown):
    """Return composite + per-criterion under default weights."""
    qr = build_quality_report(
        matches=_matches_to_dicts(matches),
        n_teams=n, matches_per_team=mpt,
        teams_per_alliance=3, cooldown=cooldown,
    )
    return {
        'composite': qr['scores']['composite'],
        'per_criterion': {
            k: v['score'] for k, v in qr['scores']['per_criterion'].items()
        },
        'metrics': {
            k: v['value'] for k, v in qr['metrics'].items()
        },
        'is_valid_paramount': qr['is_valid_paramount'],
    }


def run_one(fixture: dict, budget_s: float, seed: int,
            sa_iterations: int) -> dict[str, Any]:
    """Run one fixture × budget × seed combination.

    Returns a dict with the full per-run record. The SA upstream is
    run ONCE per (fixture, seed) and the same construction is fed
    through both the CP-SAT pipeline (for this budget) and the SA
    pipeline (for comparison). This way budget variation isolates
    post-pass behavior from upstream SA noise.
    """
    n, mpt, cd = fixture['n'], fixture['mpt'], fixture['cd']
    label = fixture['label']

    print(f"  [{label}] seed={seed} budget={budget_s}s SA upstream...")
    t0 = time.time()
    # Run upstream WITHOUT the SA post-passes — we'll apply both
    # post-pass variants separately and compare. Some seeds trigger
    # ConstructionMalformedError on tight fixtures; bump seed and retry.
    from app.scheduler import ConstructionMalformedError
    attempt_seed = seed
    while True:
        try:
            sa_result = generate_matches(
                num_teams=n, matches_per_team=mpt, ideal_gap=cd,
                seed=attempt_seed, n_sa_iterations=sa_iterations,
                rb_post_pass=False, station_post_pass=False,
            )
            break
        except ConstructionMalformedError as e:
            print(f"    seed {attempt_seed} malformed: {e}; bumping seed")
            attempt_seed += 1000
            if attempt_seed - seed > 5000:
                raise RuntimeError(f"5+ retries failed for {label} seed={seed}")
    sa_upstream_s = time.time() - t0
    print(f"    SA upstream done in {sa_upstream_s:.1f}s")

    raw_score = _score(sa_result.matches, n, mpt, cd)
    print(f"    raw (no post-pass) composite: {raw_score['composite']:.1f}")

    # Pipeline A: SA post-passes (today's production behavior).
    t0 = time.time()
    after_sa_rb, sa_rb_stats = rb_balance_sa(sa_result.matches,
                                              n_iterations=5000, seed=seed)
    after_sa_full, sa_st_stats = station_balance_sa(after_sa_rb,
                                                     n_iterations=5000, seed=seed)
    sa_post_pass_s = time.time() - t0
    sa_score = _score(after_sa_full, n, mpt, cd)

    # Pipeline B: CP-SAT post-passes at the given budget.
    # Split budget: ~10% to R/B (fast subproblem), ~90% to station (larger).
    rb_budget = max(1.0, min(budget_s * 0.10, 60.0))
    station_budget = max(1.0, budget_s - rb_budget)

    t0 = time.time()
    after_cpsat_rb, cpsat_rb_stats = rb_balance_cpsat(sa_result.matches,
                                                       time_budget_s=rb_budget)
    after_cpsat_full, cpsat_st_stats = station_balance_cpsat(after_cpsat_rb,
                                                              time_budget_s=station_budget)
    cpsat_post_pass_s = time.time() - t0
    cpsat_score = _score(after_cpsat_full, n, mpt, cd)

    return {
        'fixture':       label,
        'n':             n, 'mpt': mpt, 'cd': cd,
        'seed':          seed,
        'budget_s':      budget_s,
        'sa_iterations': sa_iterations,
        'sa_upstream_s': sa_upstream_s,

        'raw':   raw_score,

        'sa_post_pass': {
            **sa_score,
            'wall_time_s': sa_post_pass_s,
            'rb_stats':    {k: v for k, v in sa_rb_stats.items() if k in
                            ('max_before', 'max_after', 'sum_before', 'sum_after')},
            'station_stats': {k: v for k, v in sa_st_stats.items() if k in
                              ('max_before', 'max_after', 'sum_before', 'sum_after')},
        },

        'cpsat_post_pass': {
            **cpsat_score,
            'wall_time_s': cpsat_post_pass_s,
            'rb_budget_s': rb_budget,
            'station_budget_s': station_budget,
            'rb_status':   cpsat_rb_stats['status'],
            'rb_solver_s': cpsat_rb_stats['wall_time_s'],
            'station_status':   cpsat_st_stats['status'],
            'station_solver_s': cpsat_st_stats['wall_time_s'],
            'rb_max_before':    cpsat_rb_stats['max_before'],
            'rb_max_after':     cpsat_rb_stats['max_after'],
            'station_max_before': cpsat_st_stats['max_before'],
            'station_max_after':  cpsat_st_stats['max_after'],
        },
    }


def print_summary(records: list[dict]):
    """Render a Markdown-style table of results."""
    print()
    print("## Per-run results")
    print()
    print("| fixture | seed | budget | raw comp | SA comp | CPSAT comp | Δ(CPSAT-SA) | SA wall | CPSAT wall | rb status | st status |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in records:
        delta = r['cpsat_post_pass']['composite'] - r['sa_post_pass']['composite']
        print(f"| {r['fixture']} | {r['seed']} | {r['budget_s']:.0f}s "
              f"| {r['raw']['composite']:.1f} "
              f"| {r['sa_post_pass']['composite']:.1f} "
              f"| {r['cpsat_post_pass']['composite']:.1f} "
              f"| {delta:+.1f} "
              f"| {r['sa_post_pass']['wall_time_s']:.1f}s "
              f"| {r['cpsat_post_pass']['wall_time_s']:.1f}s "
              f"| {r['cpsat_post_pass']['rb_status']} "
              f"| {r['cpsat_post_pass']['station_status']} |")

    print()
    print("## Best CP-SAT composite per fixture")
    print()
    by_fixture: dict[str, list[dict]] = {}
    for r in records:
        by_fixture.setdefault(r['fixture'], []).append(r)
    print("| fixture | best CPSAT composite | budget | wall | rb score | station score | meets ≥98 |")
    print("|---|---|---|---|---|---|---|")
    for fx, rs in by_fixture.items():
        best = max(rs, key=lambda r: r['cpsat_post_pass']['composite'])
        c = best['cpsat_post_pass']
        meets_98 = '✓' if c['composite'] >= 98 else '✗'
        print(f"| {fx} | {c['composite']:.1f} | {best['budget_s']:.0f}s | {c['wall_time_s']:.1f}s "
              f"| {c['per_criterion'].get('color', 0):.1f} "
              f"| {c['per_criterion'].get('station', 0):.1f} "
              f"| {meets_98} |")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--budgets', default='10,60,300,900',
                    help="Comma-separated CP-SAT total budgets in seconds")
    ap.add_argument('--fixtures', default='12x6,20x8,24x8,36x7,60x12',
                    help="Comma-separated fixture labels NxMPT (cd=2 always)")
    ap.add_argument('--seeds', type=int, default=1,
                    help="Number of seeds to run per (fixture, budget); >1 averages noise")
    ap.add_argument('--sa-iterations', type=int, default=500_000,
                    help="Upstream SA iteration count (production-realistic)")
    ap.add_argument('--no-report', action='store_true',
                    help="Skip writing the JSON report")
    args = ap.parse_args()

    budgets = [float(b) for b in args.budgets.split(',') if b.strip()]
    fixture_labels = [s.strip() for s in args.fixtures.split(',') if s.strip()]

    # Resolve fixture labels into specs.
    all_fixtures = {
        '12x6':  {'label': '12x6',  'n': 12, 'mpt': 6,  'cd': 2},
        '20x8':  {'label': '20x8',  'n': 20, 'mpt': 8,  'cd': 2},
        '24x8':  {'label': '24x8',  'n': 24, 'mpt': 8,  'cd': 2},
        '36x7':  {'label': '36x7',  'n': 36, 'mpt': 7,  'cd': 2},
        '60x12': {'label': '60x12', 'n': 60, 'mpt': 12, 'cd': 2},
    }
    fixtures = []
    for lbl in fixture_labels:
        if lbl not in all_fixtures:
            raise SystemExit(f"Unknown fixture: {lbl}")
        fixtures.append(all_fixtures[lbl])

    print(f"Running sweep: {len(fixtures)} fixtures × {len(budgets)} budgets × {args.seeds} seeds")
    print(f"SA upstream iterations: {args.sa_iterations}")
    print(f"Budgets: {budgets}")
    print()

    records = []
    seeds = list(range(args.seeds))
    t_total = time.time()
    for fx in fixtures:
        print(f"\n=== {fx['label']} ===")
        for seed in seeds:
            for budget in budgets:
                rec = run_one(fx, budget_s=budget, seed=seed,
                               sa_iterations=args.sa_iterations)
                records.append(rec)
                print(f"    -> raw={rec['raw']['composite']:.1f} "
                      f"sa={rec['sa_post_pass']['composite']:.1f} "
                      f"cpsat={rec['cpsat_post_pass']['composite']:.1f} "
                      f"(rb={rec['cpsat_post_pass']['rb_status']}, "
                      f"st={rec['cpsat_post_pass']['station_status']})")

    print(f"\nTotal sweep time: {time.time() - t_total:.0f}s")
    print_summary(records)

    if not args.no_report:
        outdir = _REPO_ROOT / "scripts" / "scheduler_eval" / "reports"
        outdir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        outpath = outdir / f"cpsat_sweep_{ts}.json"
        with open(outpath, 'w') as f:
            json.dump({
                'timestamp': ts,
                'args': vars(args),
                'records': records,
            }, f, indent=2)
        print(f"\nReport written to: {outpath}")


if __name__ == '__main__':
    main()
