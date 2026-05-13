#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Canonical schedule library producer.

For a fixture shape, run a deep search and cache the result as a
canonical library entry. The shape's confidence label is determined
by the search outcome:

  - CP-SAT proves optimality → 'proven_optimal'
  - Schedule matches the proven_lower_bound floor on par_quad and
    opp_quad → 'matches_floor' (we know the schedule reaches the
    mathematical lower bound, even if CP-SAT can't certify it)
  - Best of N SA seeds, no CP-SAT optimality → 'best_known'

Usage:

    # Build one shape
    python3 scripts/scheduler_eval/build_canonical.py \\
        --shape 36x7 --cooldown 2 \\
        --method auto --sa-iterations 500000 --n-seeds 5

    # The shape arg is "<n>x<mpt>"; tpa defaults to 3 (FRC standard).

Methods:
  - 'cpsat': try CP-SAT only; fail if no feasible solution within time
  - 'sa': SA-best-of-N only
  - 'auto': CP-SAT for shapes where it terminates fast, SA otherwise

After producing, the canonical is written to
`app/canonical_schedules/{n}x{mpt}x{tpa}_cd{cooldown}.json`.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.scheduler import (   # noqa: E402
    Match,
    generate_matches,
    score_tuple_for_schedule,
    _sa_optimize,
    ConstructionMalformedError,
)
from app.canonical_library import (   # noqa: E402
    CanonicalEntry,
    save_canonical,
    SCHEDULE_CONFIDENCE_PROVEN_OPTIMAL,
    SCHEDULE_CONFIDENCE_MATCHES_FLOOR,
    SCHEDULE_CONFIDENCE_BEST_KNOWN,
)
from app.quality_floors import fixture_floors   # noqa: E402
from app.quality_report import compute_metrics  # noqa: E402


def _matches_to_dicts(matches: list[Match]) -> list[dict[str, Any]]:
    """Convert NamedTuple Match list to JSON-serializable dicts."""
    return [
        {
            'red':            list(m.red),
            'blue':           list(m.blue),
            'red_surrogate':  list(m.red_surrogate),
            'blue_surrogate': list(m.blue_surrogate),
        }
        for m in matches
    ]


def _git_commit_short() -> str | None:
    """Best-effort: return the current git commit short-hash for
    provenance. None if not in a git repo or git isn't available.
    """
    import subprocess
    try:
        out = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'],
            cwd=_REPO_ROOT, stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def build_via_sa(n_teams: int, mpt: int, tpa: int, cooldown: int,
                 sa_iterations: int, n_seeds: int,
                 verbose: bool = False) -> tuple[list[Match], dict[str, Any]]:
    """Run SA-best-of-N: generate_matches at multiple seeds, pick the
    best by lex tuple. Returns (matches, methodology_meta).
    """
    best_matches:    list[Match] | None = None
    best_tuple:      tuple | None       = None
    best_seed:       int | None         = None
    successes = 0
    failures  = 0
    t0 = time.time()

    for s in range(n_seeds):
        seed = 30_000 + s * 7919
        try:
            result = generate_matches(
                num_teams=n_teams,
                matches_per_team=mpt,
                ideal_gap=cooldown,
                seed=seed,
                team_numbers=list(range(1, n_teams + 1)),
                n_sa_iterations=sa_iterations,
                rb_post_pass=True,
                station_post_pass=True,
            )
            matches = list(result.matches)
            tup = score_tuple_for_schedule(matches, num_teams=n_teams,
                                            ideal_gap=cooldown)
            successes += 1
            if best_tuple is None or tup < best_tuple:
                best_matches = matches
                best_tuple   = tup
                best_seed    = seed
            if verbose:
                print(f"  seed={seed} → lex={tuple(tup)[:3]}..., "
                      f"best so far={tuple(best_tuple)[:3]}")
        except ConstructionMalformedError as e:
            failures += 1
            if verbose:
                print(f"  seed={seed} → ConstructionMalformedError: {e}")
            continue

    wall = time.time() - t0
    if best_matches is None:
        raise RuntimeError(
            f"All {n_seeds} SA seeds failed for {n_teams}×{mpt} cd={cooldown}"
        )

    return best_matches, {
        'method':          'sa_best_of_n',
        'sa_iterations':   sa_iterations,
        'n_seeds':         n_seeds,
        'successes':       successes,
        'failures':        failures,
        'best_seed':       best_seed,
        'wall_clock_s':    round(wall, 1),
    }


def build_canonical(n_teams: int, mpt: int, tpa: int, cooldown: int,
                    method: str = 'auto',
                    sa_iterations: int = 500_000,
                    n_seeds: int = 5,
                    cpsat_post_pass_budget_s: float = 600.0,
                    skip_cpsat_post_pass: bool = False,
                    verbose: bool = True) -> CanonicalEntry:
    """Build a canonical library entry for the given shape.

    Method dispatch:
      - 'auto': pick based on shape. Small fixtures might use CP-SAT
        but for v1.0 we default to SA-best-of-N which works on all
        shapes including surrogate-required ones.
      - 'sa': SA-best-of-N
      - 'cpsat': CP-SAT optimality (not yet implemented for surrogates)

    After SA-best-of-N selects the winner, the CP-SAT post-passes
    polish the R/B and station distributions to provably optimal
    (within `cpsat_post_pass_budget_s` per subproblem; budget split
    10% R/B + 90% station). Set skip_cpsat_post_pass=True to use
    only SA post-passes (faster but may plateau on 30+ team
    fixtures). Set the budget to 0 for the same effect.

    Returns the CanonicalEntry; caller saves it.
    """
    if verbose:
        print(f"Building canonical for {n_teams}×{mpt}×{tpa} cooldown={cooldown}")
        print(f"  method={method}, sa_iterations={sa_iterations}, n_seeds={n_seeds}")
        if not skip_cpsat_post_pass and cpsat_post_pass_budget_s > 0:
            print(f"  CP-SAT post-pass budget: {cpsat_post_pass_budget_s}s")

    # Compute floors first — they're cheap and we need them to decide
    # confidence labels at the end.
    ff = fixture_floors(n_teams, mpt, tpa, cooldown)
    if verbose:
        print(f"  cooldown_max={ff.cooldown_max}, "
              f"surrogate_count={ff.surrogate_count}, feasible={ff.feasible}")
        print(f"  par_quad floor: {ff.floors['par_quad'].value} "
              f"({ff.floors['par_quad'].confidence})")
        print(f"  opp_quad floor: {ff.floors['opp_quad'].value} "
              f"({ff.floors['opp_quad'].confidence})")

    if not ff.feasible:
        raise ValueError(
            f"Shape {n_teams}×{mpt} cooldown={cooldown} is infeasible "
            f"(cooldown_max={ff.cooldown_max})"
        )

    # For v1.0: always use SA-best-of-N. CP-SAT integration as a
    # producer mode is future work (see F1-c learnings: CP-SAT and
    # SA hit the same lex tuple on every fixture where both terminate,
    # so SA is fine, plus SA handles surrogate-required fixtures.)
    if method not in ('auto', 'sa'):
        raise ValueError(f"method={method!r} not supported in v1.0; use 'auto' or 'sa'")

    matches, methodology = build_via_sa(
        n_teams, mpt, tpa, cooldown,
        sa_iterations=sa_iterations,
        n_seeds=n_seeds,
        verbose=verbose,
    )

    # CP-SAT post-pass polish on the SA winner. The SA post-passes
    # already ran (via generate_matches with rb_post_pass=True,
    # station_post_pass=True); CP-SAT here can only match or improve.
    # Empirical (2026-05-13 sweep): CP-SAT matches SA on most runs,
    # finds composite-improving solutions where SA plateaus (~25% of
    # 36×7 and 20×8 runs at 100K SA budget).
    if not skip_cpsat_post_pass and cpsat_post_pass_budget_s > 0:
        from app.post_passes.cpsat_post_passes import (
            rb_balance_cpsat, station_balance_cpsat,
        )
        # Split budget: ~10% R/B (small subproblem), ~90% station.
        rb_budget      = max(1.0, min(cpsat_post_pass_budget_s * 0.10, 60.0))
        station_budget = max(1.0, cpsat_post_pass_budget_s - rb_budget)
        if verbose:
            print(f"  Applying CP-SAT R/B post-pass (budget={rb_budget:.0f}s)...")
        polished, rb_stats = rb_balance_cpsat(matches, time_budget_s=rb_budget)
        if verbose:
            print(f"    status={rb_stats['status']} wall={rb_stats['wall_time_s']:.1f}s "
                  f"max={rb_stats['max_before']}→{rb_stats['max_after']}")
        if verbose:
            print(f"  Applying CP-SAT station post-pass (budget={station_budget:.0f}s)...")
        polished, st_stats = station_balance_cpsat(polished, time_budget_s=station_budget)
        if verbose:
            print(f"    status={st_stats['status']} wall={st_stats['wall_time_s']:.1f}s "
                  f"max={st_stats['max_before']}→{st_stats['max_after']}")
        matches = polished
        # Record CP-SAT polish in methodology for auditability
        methodology['cpsat_post_pass'] = {
            'budget_s':       cpsat_post_pass_budget_s,
            'rb_budget_s':    rb_budget,
            'station_budget_s': station_budget,
            'rb_status':      rb_stats['status'],
            'rb_wall_s':      rb_stats['wall_time_s'],
            'rb_max_before':  rb_stats['max_before'],
            'rb_max_after':   rb_stats['max_after'],
            'station_status': st_stats['status'],
            'station_wall_s': st_stats['wall_time_s'],
            'station_max_before': st_stats['max_before'],
            'station_max_after':  st_stats['max_after'],
        }
    else:
        methodology['cpsat_post_pass'] = None

    # Compute metrics — observed values vs theoretical floors. The
    # canonical's stored quality_report carries METRICS ONLY; scores
    # are derived at read time so canonical scoring always reflects
    # current scoring curves. See app/quality_report.py for the split.
    quality_metrics = compute_metrics(
        matches=_matches_to_dicts(matches),
        n_teams=n_teams,
        matches_per_team=mpt,
        teams_per_alliance=tpa,
        cooldown=cooldown,
    )

    # Determine schedule-entry confidence based on what we achieved.
    # - 'proven_optimal' requires a CP-SAT optimality proof. We don't
    #   currently produce that, so this label is reserved for future
    #   CP-SAT-based production.
    # - 'matches_floor' applies if every metric with a proven_lower_bound
    #   floor (par_quad, opp_quad) hits its floor value, AND every
    #   proven_optimal-floor metric also hits its floor. That means
    #   the schedule is mathematically optimal under known lower bounds.
    # - 'best_known' otherwise.
    all_matched = quality_metrics['summary']['all_proven_floors_matched']
    par_quad_matched = quality_metrics['metrics']['par_quad']['matches_floor']
    opp_quad_matched = quality_metrics['metrics']['opp_quad']['matches_floor']
    if all_matched and par_quad_matched and opp_quad_matched:
        confidence = SCHEDULE_CONFIDENCE_MATCHES_FLOOR
    else:
        confidence = SCHEDULE_CONFIDENCE_BEST_KNOWN

    if verbose:
        achieved = quality_metrics['achieved_lex_tuple']
        print(f"  achieved lex tuple: {achieved[:3]}...")
        print(f"  par_quad: {quality_metrics['metrics']['par_quad']['value']} "
              f"(floor {quality_metrics['metrics']['par_quad']['floor']}, "
              f"matches: {par_quad_matched})")
        print(f"  opp_quad: {quality_metrics['metrics']['opp_quad']['value']} "
              f"(floor {quality_metrics['metrics']['opp_quad']['floor']}, "
              f"matches: {opp_quad_matched})")
        print(f"  confidence: {confidence}")

    methodology['generated_at'] = datetime.now().astimezone().isoformat()
    methodology['git_commit']   = _git_commit_short()

    entry = CanonicalEntry(
        n_teams            = n_teams,
        matches_per_team   = mpt,
        teams_per_alliance = tpa,
        cooldown           = cooldown,
        confidence         = confidence,
        matches            = _matches_to_dicts(matches),
        achieved_lex_tuple = list(quality_metrics['achieved_lex_tuple']),
        quality_report     = quality_metrics,  # metrics-only; no scores
        provenance         = methodology,
    )
    return entry


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--shape', type=str, required=True,
                    help="Shape as '<n>x<mpt>' (e.g. '36x7'); tpa defaults to 3")
    ap.add_argument('--cooldown', type=int, default=2)
    ap.add_argument('--method', type=str, default='auto',
                    choices=['auto', 'sa', 'cpsat'])
    ap.add_argument('--sa-iterations', type=int, default=500_000)
    ap.add_argument('--n-seeds', type=int, default=5)
    ap.add_argument('--tpa', type=int, default=3)
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--cpsat-post-pass-budget', type=float, default=600.0,
                    help="CP-SAT post-pass total budget (s); applied to "
                         "SA winner. Split 10%% R/B + 90%% station. "
                         "Capped at 3600 by the solver. 0 to skip.")
    ap.add_argument('--skip-cpsat-post-pass', action='store_true',
                    help="Disable CP-SAT post-pass polish (SA only). "
                         "Faster but may plateau on 30+ team fixtures.")
    args = ap.parse_args()

    try:
        n_str, mpt_str = args.shape.lower().split('x')
        n_teams, mpt = int(n_str), int(mpt_str)
    except (ValueError, AttributeError):
        print(f"Bad --shape value {args.shape!r}; expected '<n>x<mpt>' e.g. '36x7'")
        sys.exit(1)

    entry = build_canonical(
        n_teams=n_teams, mpt=mpt, tpa=args.tpa, cooldown=args.cooldown,
        method=args.method,
        sa_iterations=args.sa_iterations, n_seeds=args.n_seeds,
        cpsat_post_pass_budget_s=args.cpsat_post_pass_budget,
        skip_cpsat_post_pass=args.skip_cpsat_post_pass,
        verbose=not args.quiet,
    )
    path = save_canonical(entry)
    print(f"\nCanonical written to: {path}")


if __name__ == '__main__':
    main()
