#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase D: standing schedule-quality eval suite.

Runs the production scheduler on each fixture in the proving inventory,
scores the output against per-fixture bars, reports pass/fail/warnings.

Usage:

    # Full eval on proving inventory, 3 seeds × 100K iter per fixture
    python3 scripts/scheduler_eval/standards.py

    # Subset of fixtures
    python3 scripts/scheduler_eval/standards.py --fixtures 12x6_cd2,36x7_cd2

    # Higher iteration budget (closer to production)
    python3 scripts/scheduler_eval/standards.py --sa-iterations 500000 --seeds 5

    # Strict mode: soft thresholds become hard requirements
    python3 scripts/scheduler_eval/standards.py --strict

    # Smoke test: 1 fixture, 1 seed, low iter — for CI sanity check
    python3 scripts/scheduler_eval/standards.py --smoke

Exit code 0 = all hard requirements passed (+ all soft thresholds in
strict mode). Exit code 1 = at least one hard requirement failed (or
soft threshold failed in strict mode). Soft-threshold failures
otherwise produce warnings but exit 0.

Reports written to scripts/scheduler_eval/reports/standards_<timestamp>.{json,md}.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.scheduler import (   # noqa: E402
    generate_matches,
    score_tuple_for_schedule,
    ConstructionMalformedError,
)
from app.quality_report import build_quality_report   # noqa: E402
from app.canonical_library import load_canonical   # noqa: E402
from scripts.scheduler_eval.standards_config import (   # noqa: E402
    INVENTORY,
    DEFAULT_N_SEEDS,
    DEFAULT_SA_ITERATIONS,
    get_bars,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _matches_to_dicts(matches) -> list[dict[str, Any]]:
    """Convert NamedTuple Match list to dicts (quality_report wants them)."""
    return [
        {
            'red':            list(m.red),
            'blue':           list(m.blue),
            'red_surrogate':  list(m.red_surrogate),
            'blue_surrogate': list(m.blue_surrogate),
        }
        for m in matches
    ]


# ── Per-seed run ─────────────────────────────────────────────────────


def run_one_seed(n: int, mpt: int, tpa: int, cooldown: int,
                  seed: int, sa_iterations: int) -> dict[str, Any]:
    """Run generate_matches for one seed; return the quality_report
    (which includes Phase C scores) plus timing.

    Retries on ConstructionMalformedError up to 10 times with different
    seeds (mirrors the F2 finding's mitigation).
    """
    last_err: str | None = None
    t0 = time.time()
    for attempt in range(10):
        attempt_seed = seed + attempt * 7919
        try:
            result = generate_matches(
                num_teams=n,
                matches_per_team=mpt,
                ideal_gap=cooldown,
                seed=attempt_seed,
                team_numbers=list(range(1, n + 1)),
                n_sa_iterations=sa_iterations,
                rb_post_pass=True,
                station_post_pass=True,
            )
            matches = list(result.matches)
            wall = time.time() - t0
            report = build_quality_report(
                matches=_matches_to_dicts(matches),
                n_teams=n, matches_per_team=mpt,
                teams_per_alliance=tpa, cooldown=cooldown,
            )
            return {
                'seed':             seed,
                'attempt_seed':     attempt_seed,
                'attempts':         attempt + 1,
                'wall_clock_s':     round(wall, 2),
                'quality_report':   report,
                'ok':               True,
            }
        except ConstructionMalformedError as e:
            last_err = f"ConstructionMalformedError: {e}"
            continue
        except Exception as e:
            return {
                'seed': seed, 'attempts': attempt + 1,
                'wall_clock_s': round(time.time() - t0, 2),
                'ok': False,
                'error': f"{type(e).__name__}: {e}",
            }
    return {
        'seed': seed, 'attempts': 10,
        'wall_clock_s': round(time.time() - t0, 2),
        'ok': False,
        'error': f"All 10 attempts malformed: {last_err}",
    }


# ── Per-fixture run ──────────────────────────────────────────────────


def evaluate_fixture(n: int, mpt: int, tpa: int, cooldown: int,
                      name: str, n_seeds: int, sa_iterations: int,
                      verbose: bool = True) -> dict[str, Any]:
    """Run N seeds, aggregate, compare to bars."""
    bars = get_bars(name)
    if verbose:
        print(f"\n── {name} ({n}×{mpt}×{tpa} cd={cooldown}) ──")
        print(f"   {n_seeds} seeds × {sa_iterations} SA iter")
        print(f"   bars: composite≥{bars['soft_thresholds']['composite_min']}, "
              f"per-criterion≥{bars['soft_thresholds']['per_criterion_min']}")
        if bars['notes']:
            print(f"   notes: {bars['notes']}")

    seeds = [(name.__hash__() & 0xFFFF) * 100 + i for i in range(n_seeds)]
    seed_results: list[dict[str, Any]] = []
    for s in seeds:
        r = run_one_seed(n, mpt, tpa, cooldown, s, sa_iterations)
        seed_results.append(r)
        if verbose:
            if r['ok']:
                qr = r['quality_report']
                comp = qr['scores']['composite']
                paramount = qr['is_valid_paramount']
                print(f"   seed {s:6d}: composite={comp:5.1f}, "
                      f"paramount-valid={paramount}, "
                      f"wall={r['wall_clock_s']:.1f}s")
            else:
                print(f"   seed {s:6d}: FAILED — {r['error']}")

    successful = [r for r in seed_results if r.get('ok')]
    if not successful:
        return {
            'fixture': name,
            'shape':   (n, mpt, tpa, cooldown),
            'bars':    bars,
            'n_seeds': n_seeds,
            'successful_seeds': 0,
            'verdict': 'fail',
            'reason':  'No seed produced a valid schedule',
            'seed_results': seed_results,
        }

    # Aggregate over successful seeds. Use median for composite + each
    # per-criterion score; report median + range.
    composites = [r['quality_report']['scores']['composite'] for r in successful]
    cooldowns = [r['quality_report']['scores']['per_criterion']
                 ['cooldown']['score'] for r in successful]
    paramount_flags = [r['quality_report']['is_valid_paramount'] for r in successful]

    per_criterion_medians = {}
    for crit in ['cooldown', 'partner', 'opponent', 'surrogate', 'color', 'station']:
        vals = [r['quality_report']['scores']['per_criterion']
                .get(crit, {}).get('score') for r in successful]
        vals = [v for v in vals if v is not None]
        if vals:
            per_criterion_medians[crit] = {
                'median': round(statistics.median(vals), 1),
                'min':    round(min(vals), 1),
                'max':    round(max(vals), 1),
            }

    median_composite = round(statistics.median(composites), 1)

    # Compare median composite to canonical, if exists
    canonical = load_canonical(n, mpt, tpa, cooldown)
    canonical_composite = None
    canonical_gap = None
    if canonical:
        canonical_composite = canonical.quality_report.get('scores', {}).get('composite')
        if canonical_composite is not None:
            canonical_gap = round(median_composite - canonical_composite, 1)

    # ── Hard requirements ──
    hard_failures = []
    if bars['hard_requirements'].get('is_valid_paramount'):
        if not all(paramount_flags):
            n_invalid = sum(1 for p in paramount_flags if not p)
            hard_failures.append(
                f"is_valid_paramount: {n_invalid}/{len(successful)} seeds invalid"
            )
    min_cd = bars['hard_requirements'].get('cooldown_score_min', 100.0)
    median_cd = statistics.median(cooldowns)
    if median_cd < min_cd:
        hard_failures.append(
            f"cooldown_score median={median_cd} < required {min_cd}"
        )

    # ── Soft thresholds ──
    soft_warnings = []
    comp_min = bars['soft_thresholds'].get('composite_min')
    if comp_min is not None and median_composite < comp_min:
        soft_warnings.append(
            f"composite median={median_composite} < soft threshold {comp_min}"
        )
    per_crit_min = bars['soft_thresholds'].get('per_criterion_min')
    if per_crit_min is not None:
        for crit, stats in per_criterion_medians.items():
            if stats['median'] < per_crit_min:
                soft_warnings.append(
                    f"{crit} score median={stats['median']} < soft threshold {per_crit_min}"
                )

    # Verdict
    if hard_failures:
        verdict = 'fail'
        reason = '; '.join(hard_failures)
    elif soft_warnings:
        verdict = 'warn'
        reason = '; '.join(soft_warnings)
    else:
        verdict = 'pass'
        reason = ''

    if verbose:
        symbol = {'pass': '✓', 'warn': '⚠', 'fail': '✗'}[verdict]
        print(f"   {symbol} {verdict.upper()}: median composite={median_composite}"
              + (f" (vs canonical {canonical_composite}, gap {canonical_gap:+.1f})"
                 if canonical_composite is not None else ""))
        if hard_failures:
            for f in hard_failures:
                print(f"     ✗ HARD: {f}")
        if soft_warnings:
            for w in soft_warnings:
                print(f"     ⚠ SOFT: {w}")

    return {
        'fixture':              name,
        'shape':                (n, mpt, tpa, cooldown),
        'bars':                 bars,
        'n_seeds':              n_seeds,
        'successful_seeds':     len(successful),
        'median_composite':     median_composite,
        'composite_range':      [round(min(composites), 1), round(max(composites), 1)],
        'per_criterion_medians': per_criterion_medians,
        'canonical_composite':  canonical_composite,
        'canonical_gap':        canonical_gap,
        'verdict':              verdict,
        'reason':               reason,
        'hard_failures':        hard_failures,
        'soft_warnings':        soft_warnings,
        'seed_results':         seed_results,
    }


# ── Top-level eval ──────────────────────────────────────────────────


def run_standards_eval(fixture_names: list[str] | None = None,
                        n_seeds: int = DEFAULT_N_SEEDS,
                        sa_iterations: int = DEFAULT_SA_ITERATIONS,
                        strict: bool = False,
                        verbose: bool = True) -> dict[str, Any]:
    """Run the full standing eval. Returns the aggregated report.

    Args:
        fixture_names: subset of names from INVENTORY; None means all.
        n_seeds: per-fixture seed count.
        sa_iterations: SA iteration budget per seed.
        strict: when True, soft-threshold failures become hard failures.
        verbose: print per-fixture progress.

    Returns:
        Report dict including per-fixture results, overall verdict.
    """
    selected = INVENTORY
    if fixture_names:
        selected = [f for f in INVENTORY if f[4] in fixture_names]
        missing = set(fixture_names) - {f[4] for f in selected}
        if missing:
            print(f"warning: unknown fixtures requested: {missing}",
                  file=sys.stderr)

    if verbose:
        print(f"Standing eval starting at {datetime.now().isoformat()}")
        print(f"Fixtures: {[f[4] for f in selected]}")
        print(f"Seeds per fixture: {n_seeds}")
        print(f"SA iterations: {sa_iterations}")
        print(f"Strict mode: {strict}")

    t0 = time.time()
    per_fixture = []
    for (n, mpt, tpa, cooldown, name) in selected:
        result = evaluate_fixture(
            n, mpt, tpa, cooldown, name,
            n_seeds=n_seeds, sa_iterations=sa_iterations,
            verbose=verbose,
        )
        per_fixture.append(result)
    elapsed = time.time() - t0

    # Overall verdict
    n_pass = sum(1 for r in per_fixture if r['verdict'] == 'pass')
    n_warn = sum(1 for r in per_fixture if r['verdict'] == 'warn')
    n_fail = sum(1 for r in per_fixture if r['verdict'] == 'fail')
    if n_fail > 0:
        overall = 'fail'
    elif strict and n_warn > 0:
        overall = 'fail'  # strict promotes warnings to failures
    elif n_warn > 0:
        overall = 'warn'
    else:
        overall = 'pass'

    report = {
        'started':           datetime.now().isoformat(),
        'elapsed_s':         round(elapsed, 1),
        'n_seeds':           n_seeds,
        'sa_iterations':     sa_iterations,
        'strict':            strict,
        'n_fixtures':        len(per_fixture),
        'n_pass':            n_pass,
        'n_warn':            n_warn,
        'n_fail':            n_fail,
        'overall_verdict':   overall,
        'per_fixture':       per_fixture,
    }

    if verbose:
        print(f"\n{'='*60}")
        print(f"Overall: {overall.upper()} — pass {n_pass}, warn {n_warn}, fail {n_fail}")
        print(f"Wall: {elapsed:.1f}s ({elapsed/60:.1f}min)")

    return report


# ── Reporting ────────────────────────────────────────────────────────


def write_markdown_report(report: dict, path: Path) -> None:
    lines = [
        f"# Standing Quality Eval — {report['started']}",
        "",
        f"**Overall verdict**: **{report['overall_verdict'].upper()}**",
        "",
        f"- pass: {report['n_pass']}/{report['n_fixtures']}",
        f"- warn: {report['n_warn']}/{report['n_fixtures']}",
        f"- fail: {report['n_fail']}/{report['n_fixtures']}",
        f"- elapsed: {report['elapsed_s']}s ({report['elapsed_s']/60:.1f}min)",
        f"- seeds per fixture: {report['n_seeds']}",
        f"- SA iterations: {report['sa_iterations']}",
        f"- strict mode: {report['strict']}",
        "",
        "## Per-fixture results",
        "",
        ("| Fixture | Verdict | Composite (median) | vs Canonical | "
         "Partner | Opponent | Color | Station |"),
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for f in report['per_fixture']:
        sym = {'pass': '✓', 'warn': '⚠', 'fail': '✗'}[f['verdict']]
        comp = f.get('median_composite', '—')
        can = f.get('canonical_composite')
        can_str = f"{can:.1f} ({f['canonical_gap']:+.1f})" if can is not None else "—"
        pcm = f.get('per_criterion_medians', {})
        partner = pcm.get('partner', {}).get('median', '—')
        opp = pcm.get('opponent', {}).get('median', '—')
        color = pcm.get('color', {}).get('median', '—')
        station = pcm.get('station', {}).get('median', '—')
        lines.append(
            f"| {f['fixture']} | {sym} {f['verdict']} | {comp} | {can_str} "
            f"| {partner} | {opp} | {color} | {station} |"
        )

    lines.append("")
    lines.append("## Details")
    for f in report['per_fixture']:
        lines.append(f"\n### {f['fixture']} ({f['verdict'].upper()})")
        lines.append("")
        if f['bars'].get('notes'):
            lines.append(f"*{f['bars']['notes']}*")
            lines.append("")
        lines.append(f"- Shape: {f['shape']}")
        lines.append(f"- Successful seeds: {f['successful_seeds']}/{f['n_seeds']}")
        lines.append(f"- Composite range: {f.get('composite_range', '—')}")
        if f.get('hard_failures'):
            lines.append("- **Hard failures**:")
            for h in f['hard_failures']:
                lines.append(f"  - {h}")
        if f.get('soft_warnings'):
            lines.append("- **Soft warnings**:")
            for w in f['soft_warnings']:
                lines.append(f"  - {w}")

    path.write_text('\n'.join(lines))


# ── CLI ──────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--fixtures', type=str, default=None,
                    help="Comma-separated fixture names (e.g. '12x6_cd2,36x7_cd2'). "
                         "Default: all in proving inventory.")
    ap.add_argument('--seeds', type=int, default=DEFAULT_N_SEEDS,
                    help=f"Seeds per fixture (default {DEFAULT_N_SEEDS})")
    ap.add_argument('--sa-iterations', type=int, default=DEFAULT_SA_ITERATIONS,
                    help=f"SA iter per seed (default {DEFAULT_SA_ITERATIONS})")
    ap.add_argument('--strict', action='store_true',
                    help="Soft-threshold failures become hard failures (CI mode)")
    ap.add_argument('--smoke', action='store_true',
                    help="Smoke test: 1 fixture, 1 seed, 5K iter (for CI sanity)")
    ap.add_argument('--quiet', action='store_true',
                    help="Suppress per-fixture progress output")
    ap.add_argument('--no-report', action='store_true',
                    help="Skip JSON/MD report writing")
    args = ap.parse_args()

    if args.smoke:
        fixture_names = ['12x6_cd2']
        n_seeds = 1
        sa_iter = 5_000
    else:
        fixture_names = args.fixtures.split(',') if args.fixtures else None
        n_seeds = args.seeds
        sa_iter = args.sa_iterations

    report = run_standards_eval(
        fixture_names=fixture_names,
        n_seeds=n_seeds,
        sa_iterations=sa_iter,
        strict=args.strict,
        verbose=not args.quiet,
    )

    if not args.no_report:
        out_dir = _REPO_ROOT / "scripts" / "scheduler_eval" / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        json_path = out_dir / f"standards_{stamp}.json"
        md_path   = out_dir / f"standards_{stamp}.md"
        json_path.write_text(json.dumps(report, indent=2, default=str))
        write_markdown_report(report, md_path)
        if not args.quiet:
            print(f"\nReports written:\n  {json_path}\n  {md_path}")

    sys.exit(0 if report['overall_verdict'] != 'fail' else 1)


if __name__ == '__main__':
    main()
