#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# FRC Match Scheduler
# Copyright (C) 2025 FRC Match Scheduler Contributors
"""Phase 5 Plan A diagnostics — narrow the cause of the two remaining
metric failures in the post-Phase-4 eval baseline.

Background: the corrected eval (2026-05-10, EVAL_FINDINGS.md
"Post-Phase-4 baseline") shows mean composite 30.64 with the failure
narrowed to two phenomena:
  1. max_station_spread: 13/13 fixtures we're worse than the reference scheduler
     (mean 3.54 vs 0.38). The Phase 2 (the station-balance technique) station post-pass works
     on synthetic small-team inputs but hits a 2-3 floor on real
     36+ team fixtures.
  2. repeat_opponents: on 40-team x 12-MPT fixtures specifically, we
     have ~20% more 2-encounter pairs than the reference scheduler even though
     opp_quad is at floor — sum-of-squares vs count-above-one
     measure different things.

This script runs two experiments designed to distinguish iteration-
limited from structural causes. Both should complete in well under
an hour total on Stark.

  Experiment 1 (station post-pass scaling): take a 60-team fixture
  where MM hit station_spread=0 and we hit 5. Run station_balance_sa
  on top of the same construction+SA output at iteration budgets
  spanning four orders of magnitude (5K, 50K, 500K, 5M). Plot the
  resulting station_spread. If it drops monotonically with budget,
  the post-pass is iteration-limited and Plan B (raise per-pass
  budget at scale) is the right next investment. If it plateaus
  early, the move set or initialization isn't reaching MM's basin
  and Plan C (lex-tuple expansion or different post-pass design) is
  needed.

  Experiment 2 (opp_quad vs repeat_opponents on high-MPT): pick a
  40t x 12-MPT fixture from the 2024micmp* family. Generate one
  best-of-100 schedule (same as the eval). Print the lex tuple
  components alongside the count-based eval metrics. If opp_quad is
  at floor (or close to it) while repeat_opponents is still 158 and
  MM gets 134, then sum-of-squares optimization isn't penalizing
  2-encounter clustering enough — Plan C with a count-clustering
  term is the right answer. If opp_quad is well above floor, the SA
  hasn't converged on these fixtures and the answer is more
  iterations or smarter cooling.

Usage on Stark:

    cd ~/git/frc-scheduler-server
    python3 scripts/scheduler_eval/phase5_diagnose.py 2>&1 \
        | tee scripts/scheduler_eval/reports/phase5_diagnose.log

Total wall-clock estimate: ~40-50 minutes on Stark.

Output: prints two sections to stdout, also writes a JSON summary to
``scripts/scheduler_eval/reports/phase5_diagnose_<timestamp>.json``.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.scheduler import (
    generate_matches,
    score_tuple_for_schedule,
)
from app.post_passes.station_balance import station_balance_sa
from scripts.scheduler_eval.harness_types import Fixture, Match as HarnessMatch
from scripts.scheduler_eval.metrics import analyze
from scripts.scheduler_eval.harness_types import Schedule


HERE = Path(__file__).parent
FIXTURES_DIR = HERE / "fixtures"
REPORTS_DIR = HERE / "reports"
REPORTS_DIR.mkdir(exist_ok=True)


# ── Helper ──────────────────────────────────────────────────────────


def _to_harness_matches(internal_matches) -> list[HarnessMatch]:
    """Convert app.scheduler.Match (NamedTuple, no match_num) into
    harness_types.Match (dataclass, has match_num). Mirrors the
    conversion in scripts/scheduler_eval/adapters/frc_scheduler_server.py.
    """
    out = []
    for i, m in enumerate(internal_matches, start=1):
        out.append(HarnessMatch(
            match_num=i,
            blue=list(m.blue),
            red=list(m.red),
            blue_surrogate=list(m.blue_surrogate),
            red_surrogate=list(m.red_surrogate),
        ))
    return out


def _build_baseline_schedule(fixture: Fixture, *, sa_iterations: int,
                              seed: int) -> tuple[list, tuple]:
    """Generate one full schedule via the production pipeline.

    Returns (matches, lex_tuple) where matches is the list of Match
    objects post-Phase-4 (construction + main SA + R/B + station
    post-passes at default 5K iterations) and lex_tuple is the
    canonical 8-element tuple from score_tuple_for_schedule.

    Phase 5 Experiment 1 then re-runs station_balance_sa on top of
    this output at higher budgets to see if station_pen continues
    to drop.
    """
    result = generate_matches(
        num_teams=fixture.num_teams,
        matches_per_team=fixture.matches_per_team,
        ideal_gap=3,
        seed=seed,
        team_numbers=list(fixture.teams),
        n_sa_iterations=sa_iterations,
        rb_post_pass=True,
        station_post_pass=True,
    )
    lex_tuple = score_tuple_for_schedule(
        result.matches, fixture.num_teams,
        ideal_gap=3,
    )
    return result.matches, lex_tuple


def _eval_schedule(matches: list, fixture: Fixture, *, adapter_name: str,
                   sa_iterations: int) -> dict:
    """Run the harness analyzer on a given schedule.

    Returns a plain dict (the AnalysisReport.to_dict() shape) with
    metric values + classifications. We mostly want
    max_station_spread, repeat_opponents, max_opponent_repeats,
    plus the lex tuple values.
    """
    sched = Schedule(
        fixture_id=fixture.fixture_id,
        adapter_name=adapter_name,
        matches=matches,
        generation_seconds=0.0,
        seed=None,
        adapter_diagnostics={"sa_iterations": sa_iterations},
        generated_at=datetime.utcnow().isoformat(),
    )
    report = analyze(sched, fixture)
    return report.to_dict()


# ── Experiment 1: station post-pass iteration scaling ──────────────


def experiment_1_station_postpass_scaling():
    """Take a 60-team fixture where the eval shows station_spread=5.
    Run station_balance_sa on top of the construction+SA output at
    five iteration budgets. See if station_spread drops monotonically.
    """
    print("=" * 78)
    print("EXPERIMENT 1 — Station post-pass iteration scaling")
    print("=" * 78)
    print()
    print("Fixture: 2023mndu (60 teams x 9 MPT)")
    print("Eval result on this fixture: fss station_spread=5, MM=0")
    print("Question: does station_spread drop with bigger post-pass budget?")
    print()

    fixture = Fixture.load(FIXTURES_DIR / "2023mndu.json")

    # Generate one strong baseline schedule using the production
    # pipeline (construction + SA at "best" preset + default 5K
    # post-passes). All experimental post-pass runs start from the
    # same baseline so the only variable is post-pass budget.
    print("Building baseline (construction + SA=2M + post-passes at 5K)...")
    t0 = time.monotonic()
    baseline_matches, baseline_tuple = _build_baseline_schedule(
        fixture, sa_iterations=2_000_000, seed=42,
    )
    baseline_elapsed = time.monotonic() - t0
    print(f"  Baseline built in {baseline_elapsed:.1f}s")
    print(f"  Baseline lex tuple: {baseline_tuple}")
    baseline_report = _eval_schedule(
        _to_harness_matches(baseline_matches), fixture,
        adapter_name="frc-scheduler-server",
        sa_iterations=2_000_000,
    )
    baseline_station_spread = baseline_report["metrics"]["max_station_spread"]["value"]
    print(f"  Baseline max_station_spread: {baseline_station_spread}")
    print()

    # Now re-run station_balance_sa at progressively higher budgets,
    # always starting from the SAME pre-station-pass schedule. We
    # need to back out the station post-pass that's already been
    # applied — easiest is to regenerate without it.
    print("Re-building baseline WITHOUT station post-pass for clean slate...")
    t0 = time.monotonic()
    # Use generate_matches with station_post_pass=False to get the
    # state the station post-pass would normally consume.
    pre_station_result = generate_matches(
        num_teams=fixture.num_teams,
        matches_per_team=fixture.matches_per_team,
        ideal_gap=3,
        seed=42,
        team_numbers=list(fixture.teams),
        n_sa_iterations=2_000_000,
        rb_post_pass=True,
        station_post_pass=False,
    )
    elapsed = time.monotonic() - t0
    pre_station_matches = pre_station_result.matches  # internal Match (NamedTuple)
    print(f"  Pre-station-pass baseline built in {elapsed:.1f}s")
    pre_station_report = _eval_schedule(
        _to_harness_matches(pre_station_matches), fixture,
        adapter_name="frc-scheduler-server-no-station",
        sa_iterations=2_000_000,
    )
    pre_station_spread = pre_station_report["metrics"]["max_station_spread"]["value"]
    print(f"  Pre-station-pass max_station_spread: {pre_station_spread}")
    print()

    # Iteration budgets to test, log-spaced.
    # 5K is the production default. 50M is way past the lex-SA ceiling
    # of 5M but post-passes are much cheaper per iter so it should
    # complete in reasonable time.
    budgets = [5_000, 50_000, 500_000, 5_000_000, 50_000_000]
    results = []
    for budget in budgets:
        print(f"Running station_balance_sa with n_iterations={budget:,}...")
        t0 = time.monotonic()
        new_matches, stats = station_balance_sa(
            pre_station_matches, n_iterations=budget, seed=12345,
        )
        elapsed = time.monotonic() - t0
        report = _eval_schedule(
            _to_harness_matches(new_matches), fixture,
            adapter_name=f"station-pp-{budget}",
            sa_iterations=2_000_000,
        )
        spread = report["metrics"]["max_station_spread"]["value"]
        composite = sum(
            (1 if m["classification"] == "poor" else
             0.3 if m["classification"] == "acceptable" else
             0.05 if m["classification"] == "near_optimal" else 0) * 10
            for m in report["metrics"].values()
            if m.get("classification")
        )
        results.append({
            "budget": budget,
            "elapsed_seconds": round(elapsed, 2),
            "max_station_spread": spread,
            "composite": round(composite, 2),
            "stats": stats,
        })
        print(f"  budget={budget:>11,}  elapsed={elapsed:>7.1f}s  "
              f"station_spread={spread}  composite~{composite:.1f}")

    print()
    print("INTERPRETATION:")
    spreads = [r["max_station_spread"] for r in results]
    if spreads[-1] < spreads[0] and all(spreads[i+1] <= spreads[i] for i in range(len(spreads)-1)):
        print("  Station spread drops monotonically with budget.")
        print("  -> ITERATION-LIMITED. Plan B (raise per-pass budget at")
        print("     scale) is the appropriate next investment.")
    elif spreads[-1] == spreads[0]:
        print("  Station spread doesn't change with budget at all.")
        print("  -> MOVE-SET-LIMITED or already at SA's reach. Plan C")
        print("     (different post-pass design or expanded lex tuple)")
        print("     is needed.")
    else:
        plateau_at = next(
            (i for i in range(len(spreads)-1) if spreads[i] == spreads[i+1]),
            None,
        )
        if plateau_at is not None:
            print(f"  Station spread plateaus at budget={budgets[plateau_at]:,}.")
            print(f"  Final spread {spreads[-1]} vs MM's 0.")
            print("  -> PARTIALLY iteration-limited but plateaus before")
            print("     reaching MM. Plan B helps somewhat but Plan C is")
            print("     also needed. Consider both.")
        else:
            print("  Mixed signal — non-monotonic. Inspect raw numbers above.")

    return {"experiment": "1_station_postpass_scaling", "results": results,
            "baseline_spread": pre_station_spread,
            "baseline_lex_tuple": list(baseline_tuple)}


# ── Experiment 2: opp_quad vs repeat_opponents on high-MPT ──────────


def experiment_2_oppquad_vs_repeat_opp():
    """Generate one schedule on a 40t x 12-MPT fixture. Print the
    lex tuple alongside the count-based eval metrics. See if opp_quad
    being at floor coexists with repeat_opponents > MM's value.
    """
    print()
    print("=" * 78)
    print("EXPERIMENT 2 — opp_quad vs repeat_opponents on high-MPT fixture")
    print("=" * 78)
    print()
    print("Fixture: 2024micmp1 (40 teams x 12 MPT)")
    print("Eval result on this fixture: fss repeat_opp=158, MM=134, gap=+24")
    print("Question: is our opp_quad at floor while we still have these?")
    print()

    fixture = Fixture.load(FIXTURES_DIR / "2024micmp1.json")

    # Generate best-of-N=10 (lighter than the eval's 100 since this
    # is just diagnostic, but strong enough to land near the SA's
    # asymptote on this fixture).
    print("Generating best-of-10 at SA=2M...")
    best_tuple = None
    best_matches = None
    for trial in range(10):
        t0 = time.monotonic()
        result = generate_matches(
            num_teams=fixture.num_teams,
            matches_per_team=fixture.matches_per_team,
            ideal_gap=3,
            seed=42 ^ (trial * 1_000_003),
            team_numbers=list(fixture.teams),
            n_sa_iterations=2_000_000,
            rb_post_pass=True,
            station_post_pass=True,
        )
        elapsed = time.monotonic() - t0
        lex_tuple = score_tuple_for_schedule(
            result.matches, fixture.num_teams, ideal_gap=3,
        )
        print(f"  trial {trial+1}/10: tuple={lex_tuple} "
              f"elapsed={elapsed:.0f}s")
        if best_tuple is None or lex_tuple < best_tuple:
            best_tuple = lex_tuple
            best_matches = result.matches

    print()
    print(f"Best lex tuple of 10 trials: {best_tuple}")
    # Tuple is (cooldown, par_quad, opp_quad, surrogate, rb_metric,
    # station_pen, surrogate_spread, match_equity)
    labels = [
        "cooldown_violations",
        "par_quad",
        "opp_quad",
        "surrogate_count",
        "rb_metric",
        "station_pen",
        "surrogate_spread",
        "match_equity",
    ]
    for label, value in zip(labels, best_tuple):
        print(f"  {label:<22} {value}")
    print()

    # Now run the harness eval on it
    report = _eval_schedule(
        _to_harness_matches(best_matches), fixture,
        adapter_name="frc-scheduler-server",
        sa_iterations=2_000_000,
    )
    metrics = report["metrics"]
    print("Eval metrics:")
    for name in ["repeat_partners", "max_partner_repeats",
                 "repeat_opponents", "max_opponent_repeats",
                 "max_color_imbalance", "max_station_spread",
                 "min_match_gap", "back_to_back_matches"]:
        m = metrics.get(name, {})
        v = m.get("value", "—")
        c = m.get("classification", "—")
        print(f"  {name:<25} {v} ({c})")
    print()

    # Compute the par_quad floor for comparison.
    # par_quad floor for n teams x mpt matches:
    # each team has 2*mpt partner-slots distributed among n-1 others
    # ideal floor depends on whether 2*mpt is divisible by n-1
    n, mpt = fixture.num_teams, fixture.matches_per_team
    partner_slots = 2 * mpt
    n_others = n - 1
    base = partner_slots // n_others
    extra = partner_slots % n_others
    # Each team contributes sum_j (count_ij)^2 where count_ij is
    # how many times it partners with team j. The floor for one team
    # is (n_others - extra) * base^2 + extra * (base+1)^2.
    per_team_floor = (n_others - extra) * (base ** 2) + extra * ((base + 1) ** 2)
    par_quad_floor = n * per_team_floor
    print(f"par_quad floor for {n}t x {mpt}MPT: {par_quad_floor}")
    print(f"  our par_quad: {best_tuple[1]} "
          f"({'at floor' if best_tuple[1] == par_quad_floor else f'+{best_tuple[1] - par_quad_floor}'})")
    # Same calculation for opp_quad
    opp_slots = 3 * mpt  # each match has 3 opponents from the other alliance
    n_others = n - 1
    base = opp_slots // n_others
    extra = opp_slots % n_others
    per_team_opp_floor = (n_others - extra) * (base ** 2) + extra * ((base + 1) ** 2)
    opp_quad_floor = n * per_team_opp_floor
    print(f"opp_quad floor for {n}t x {mpt}MPT: {opp_quad_floor}")
    print(f"  our opp_quad: {best_tuple[2]} "
          f"({'at floor' if best_tuple[2] == opp_quad_floor else f'+{best_tuple[2] - opp_quad_floor}'})")
    print()

    print("INTERPRETATION:")
    repeat_opp = metrics["repeat_opponents"]["value"]
    if best_tuple[2] == opp_quad_floor:
        print(f"  opp_quad is AT FLOOR ({best_tuple[2]}) while")
        print(f"  repeat_opponents is {repeat_opp} (MM gets 134).")
        print("  -> Sum-of-squares is fully optimized but doesn't penalize")
        print("     2-encounter clustering enough. Plan C (extend the lex")
        print("     tuple with a count-clustering term after opp_quad) is")
        print("     the right structural answer.")
    elif best_tuple[2] - opp_quad_floor < 50:
        print(f"  opp_quad near floor (gap +{best_tuple[2] - opp_quad_floor}).")
        print("  Mixed signal — SA is close but not quite converged. Worth")
        print("  trying SA=5M (maximum preset) on this fixture before")
        print("  committing to lex-tuple expansion.")
    else:
        print(f"  opp_quad WELL ABOVE FLOOR (gap +{best_tuple[2] - opp_quad_floor}).")
        print("  -> SA isn't converging on these fixtures. Plan B variant")
        print("     (raise main-SA budget per fixture-size) or smarter")
        print("     cooling schedule is the right answer, not lex-tuple")
        print("     expansion.")

    return {"experiment": "2_oppquad_vs_repeat_opp",
            "best_lex_tuple": list(best_tuple),
            "metrics": {name: metrics[name] for name in metrics},
            "par_quad_floor": par_quad_floor,
            "opp_quad_floor": opp_quad_floor}


# ── Run both ────────────────────────────────────────────────────────


def main():
    print("Phase 5 Plan A diagnostics")
    print(f"Started: {datetime.utcnow().isoformat()}Z")
    print()

    overall_start = time.monotonic()
    e1 = experiment_1_station_postpass_scaling()
    e2 = experiment_2_oppquad_vs_repeat_opp()
    overall_elapsed = time.monotonic() - overall_start

    print()
    print("=" * 78)
    print(f"Total elapsed: {overall_elapsed:.0f}s ({overall_elapsed/60:.1f} min)")
    print("=" * 78)

    # Save JSON summary
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    out_path = REPORTS_DIR / f"phase5_diagnose_{timestamp}.json"
    out_path.write_text(json.dumps({
        "started": datetime.utcnow().isoformat() + "Z",
        "elapsed_seconds": round(overall_elapsed, 1),
        "experiment_1": e1,
        "experiment_2": e2,
    }, indent=2, default=str))
    print(f"JSON summary: {out_path}")


if __name__ == "__main__":
    main()
