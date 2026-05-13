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
                    verbose: bool = True) -> CanonicalEntry:
    """Build a canonical library entry for the given shape.

    Method dispatch:
      - 'auto': pick based on shape. Small fixtures might use CP-SAT
        but for v1.0 we default to SA-best-of-N which works on all
        shapes including surrogate-required ones.
      - 'sa': SA-best-of-N
      - 'cpsat': CP-SAT optimality (not yet implemented for surrogates)

    Returns the CanonicalEntry; caller saves it.
    """
    if verbose:
        print(f"Building canonical for {n_teams}×{mpt}×{tpa} cooldown={cooldown}")
        print(f"  method={method}, sa_iterations={sa_iterations}, n_seeds={n_seeds}")

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
        verbose=not args.quiet,
    )
    path = save_canonical(entry)
    print(f"\nCanonical written to: {path}")


if __name__ == '__main__':
    main()
