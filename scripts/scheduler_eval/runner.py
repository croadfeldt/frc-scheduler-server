"""Runner — runs every (fixture × adapter) combination and produces
a Markdown report.

Usage:

    python -m scripts.scheduler_eval.runner \
        --fixtures 2026mnst \
        --adapters frc-scheduler-server,actual \
        --trials 50 \
        --out-dir scripts/scheduler_eval/reports

The runner is parallelism-aware. With Stark's 36 physical cores / 72
threads, the default --workers is 36 (use physical cores; hyperthreads
hurt CPU-bound search). Override with --workers if you want.

Each (fixture, adapter, trial) triple is independent; we use a
multiprocessing pool to spread them across cores. Results are
analyzed serially in the parent process — the analysis is fast.

The output directory contains:

    reports/
      <run-id>/
        report.md              — human-readable summary
        full_report.json       — complete metrics for every schedule
        schedules/             — every generated Schedule, one JSON per
        fixtures.json          — copy of input fixtures used in the run

A run-id is yyyymmdd-hhmmss-<short-hash> for chronological listing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Allow running with `python -m scripts.scheduler_eval.runner` AND
# directly as a script
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.scheduler_eval.adapters import (
    ActualScheduleAdapter,
    MatchMakerAdapter,
    FrcSchedulerServerAdapter,
)
from scripts.scheduler_eval.harness_types import Fixture, Schedule
from scripts.scheduler_eval.metrics import analyze, AnalysisReport, THRESHOLDS


HERE         = Path(__file__).parent
FIXTURES_DIR = HERE / "fixtures"
REPORTS_DIR  = HERE / "reports"


def _pre_pulled_actual_path(fixture_id: str) -> Path:
    """Convention: '{fixture_id}__actual.json' alongside the fixture JSON
    holds a pre-pulled played schedule (from TBA via pull_tba_fixtures.py).
    The runner uses it directly when present, avoiding re-fetch."""
    return FIXTURES_DIR / f"{fixture_id}__actual.json"


def _run_one(args: tuple) -> dict:
    """Worker function for the multiprocessing pool.

    Returns a dict so we can pass it across process boundaries without
    pickling the adapter (which may hold non-picklable state like
    subprocess paths).
    """
    fixture_dict, adapter_name, adapter_kwargs, seed, trial = args
    fixture = Fixture.from_json_dict(fixture_dict)

    # Special-case the 'actual' adapter: if a pre-pulled schedule JSON
    # is on disk for this fixture, load it directly. This lets the
    # harness scale to many fixtures without per-fixture --actual-csv
    # arguments. Falls through to the live adapter only when no
    # pre-pulled file exists.
    if adapter_name == "actual" and not adapter_kwargs:
        pre_pulled = _pre_pulled_actual_path(fixture.fixture_id)
        if pre_pulled.exists():
            try:
                schedule = Schedule.load(pre_pulled)
                report   = analyze(schedule, fixture)
                return {
                    "ok":       True,
                    "fixture":  fixture.fixture_id,
                    "adapter":  adapter_name,
                    "trial":    trial,
                    "schedule": schedule.to_json_dict(),
                    "report":   report.to_dict(),
                }
            except Exception as e:
                return {
                    "ok":      False,
                    "fixture": fixture.fixture_id,
                    "adapter": adapter_name,
                    "trial":   trial,
                    "error":   f"failed to load pre-pulled schedule: {type(e).__name__}: {e}",
                }

    if adapter_name == "actual":
        adapter = ActualScheduleAdapter(**adapter_kwargs)
    elif adapter_name == "matchmaker":
        adapter = MatchMakerAdapter(**adapter_kwargs)
    elif adapter_name == "frc-scheduler-server":
        adapter = FrcSchedulerServerAdapter(**adapter_kwargs)
    else:
        raise ValueError(f"unknown adapter: {adapter_name}")

    try:
        schedule = adapter.generate(fixture, seed=seed, trial=trial)
        report   = analyze(schedule, fixture)
        return {
            "ok":       True,
            "fixture":  fixture.fixture_id,
            "adapter":  adapter_name,
            "trial":    trial,
            "schedule": schedule.to_json_dict(),
            "report":   report.to_dict(),
        }
    except Exception as e:
        return {
            "ok":      False,
            "fixture": fixture.fixture_id,
            "adapter": adapter_name,
            "trial":   trial,
            "error":   f"{type(e).__name__}: {e}",
        }


def _select_best(results: list[dict]) -> dict | None:
    """Of N trial results for one (fixture, adapter), return the best.

    "Best" = lowest count of 'poor' classifications, then highest count
    of 'near_optimal' classifications. Ties broken by lower
    repeat_partners count, then lower max_color_imbalance.
    """
    successful = [r for r in results if r.get("ok")]
    if not successful:
        return results[0] if results else None

    def rank(r):
        rep = r["report"]
        counts = rep.get("counts", {})
        metrics = rep.get("metrics", {})
        return (
            counts.get("poor", 0),                  # fewer poor → better
            -counts.get("near_optimal", 0),         # more near-optimal → better
            metrics.get("repeat_partners", {}).get("value", 9999),
            metrics.get("max_color_imbalance", {}).get("value", 9999),
        )
    return min(successful, key=rank)


def _format_value(v):
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def _classification_marker(c: str) -> str:
    return {
        "near_optimal": "✓",
        "acceptable":   "·",
        "poor":         "✗",
        "descriptive":  "—",
    }.get(c, "?")


def write_markdown_report(out_path: Path, run_id: str, fixtures: list[Fixture],
                          best_results: dict[tuple[str, str], dict],
                          all_results: list[dict]):
    """Write the human-facing summary report."""
    lines = []
    lines.append(f"# Scheduler eval — {run_id}")
    lines.append("")
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Fixtures: {len(fixtures)}")
    lines.append(f"- Adapters per fixture: varies (see per-fixture sections)")
    lines.append(f"- Total runs: {len(all_results)} ({sum(1 for r in all_results if r.get('ok'))} successful)")
    lines.append("")
    lines.append("Markers: ✓ near-optimal · acceptable · ✗ poor · — descriptive")
    lines.append("")

    # ── Per-fixture sections ────────────────────────────────────────
    for fix in fixtures:
        lines.append(f"## {fix.fixture_id} — {fix.name}")
        lines.append("")
        lines.append(f"- {fix.num_teams} teams, {fix.matches_per_team} matches each, "
                     f"{fix.teams_per_alliance}v{fix.teams_per_alliance}")
        lines.append(f"- Expected total matches: {fix.total_matches}")
        if fix.notes:
            lines.append(f"- Notes: {fix.notes}")
        lines.append("")

        # Find every adapter that ran on this fixture
        adapter_results = {ak: best_results[(fix.fixture_id, ak)]
                           for (fid, ak) in best_results.keys()
                           if fid == fix.fixture_id}
        if not adapter_results:
            lines.append("_(no adapter runs)_")
            lines.append("")
            continue

        # Build the comparison table
        adapter_names = list(adapter_results.keys())
        metric_names = []
        for r in adapter_results.values():
            if r.get("ok"):
                metric_names = list(r["report"]["metrics"].keys())
                break

        lines.append(f"| Metric | Threshold (good / accept) | "
                     + " | ".join(adapter_names) + " |")
        lines.append("|---" + "|---" * (1 + len(adapter_names)) + "|")

        for mname in metric_names:
            t = THRESHOLDS.get(mname)
            if t:
                thresh = f"≤{t.near_optimal} / ≤{t.acceptable}" if t.lower_is_better else f"≥{t.near_optimal} / ≥{t.acceptable}"
            else:
                thresh = "—"

            row = [mname, thresh]
            for an in adapter_names:
                r = adapter_results[an]
                if r.get("ok"):
                    m = r["report"]["metrics"].get(mname, {})
                    val = _format_value(m.get("value", "?"))
                    cls = m.get("classification", "")
                    row.append(f"{_classification_marker(cls)} {val}")
                else:
                    row.append("ERROR")
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")

        # Overall classification + speed
        lines.append("**Overall + diagnostics**")
        lines.append("")
        lines.append("| Adapter | Overall | Generation time | Notes |")
        lines.append("|---|---|---|---|")
        for an in adapter_names:
            r = adapter_results[an]
            if r.get("ok"):
                rep = r["report"]
                sched = r["schedule"]
                overall = rep.get("overall", "?")
                t_sec = sched.get("generation_seconds", 0)
                notes_list = []
                diag = sched.get("adapter_diagnostics", {})
                if "stage1_score" in diag:
                    notes_list.append(f"score={diag['stage1_score']:.0f}")
                if diag.get("source"):
                    notes_list.append(f"source={diag['source']}")
                lines.append(f"| {an} | {_classification_marker(overall)} {overall} | "
                             f"{t_sec:.2f}s | {', '.join(notes_list)} |")
            else:
                lines.append(f"| {an} | ERROR | — | {r.get('error', 'unknown')} |")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Methodology")
    lines.append("")
    lines.append("- For stochastic adapters, the harness runs N trials per fixture and reports the BEST.")
    lines.append("  'Best' = fewest 'poor' metrics, then most 'near_optimal', then lowest repeat-partner count.")
    lines.append("- Thresholds in the metric table are calibrated from FRC community norms and the")
    lines.append("  reviewer's MatchMaker analysis (800 trials on 36-team field).")
    lines.append("- Surrogate slot-fills count toward color/station balance (team is physically there)")
    lines.append("  but not toward repeat-partner / repeat-opponent counts (team is filling in,")
    lines.append("  not playing competitively).")
    lines.append("")

    out_path.write_text("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", default="all",
                    help="comma-separated fixture IDs, or 'all' for every fixture in fixtures/")
    ap.add_argument("--adapters", default="frc-scheduler-server,actual",
                    help="comma-separated adapter names")
    ap.add_argument("--trials", type=int, default=1,
                    help="trials per (fixture, stochastic adapter); 'actual' always runs once")
    ap.add_argument("--workers", type=int, default=max(1, os.cpu_count() // 2),
                    help="parallel workers; default is half the CPU count")
    ap.add_argument("--seed", type=int, default=None,
                    help="base seed for stochastic adapters; trial index modifies it")
    ap.add_argument("--matchmaker-binary", default=None,
                    help="path to MatchMaker binary (only needed if --adapters includes matchmaker)")
    ap.add_argument("--out-dir", default=str(REPORTS_DIR))
    ap.add_argument("--actual-csv", default=None,
                    help="path to a CSV for the 'actual' adapter (single-fixture mode)")
    args = ap.parse_args()

    # ── Load fixtures ───────────────────────────────────────────────
    if args.fixtures == "all":
        # Skip the '__actual.json' sibling files written by
        # pull_tba_fixtures.py — those are pre-pulled schedules,
        # not fixture inputs.
        fixture_paths = sorted(
            p for p in FIXTURES_DIR.glob("*.json")
            if not p.name.endswith("__actual.json")
        )
    else:
        ids = [s.strip() for s in args.fixtures.split(",")]
        fixture_paths = [FIXTURES_DIR / f"{i}.json" for i in ids]
    fixtures = [Fixture.load(p) for p in fixture_paths]
    if not fixtures:
        print("No fixtures matched. See scripts/scheduler_eval/fixtures/.")
        sys.exit(2)

    adapter_names = [s.strip() for s in args.adapters.split(",") if s.strip()]
    print(f"Fixtures: {[f.fixture_id for f in fixtures]}")
    print(f"Adapters: {adapter_names}")
    print(f"Trials:   {args.trials}")
    print(f"Workers:  {args.workers}")
    print()

    # ── Build the work list ─────────────────────────────────────────
    # 'actual' is deterministic; trial=0 only.
    # Stochastic adapters get N trials.
    work = []
    for fix in fixtures:
        for an in adapter_names:
            kwargs = {}
            if an == "actual":
                if args.actual_csv:
                    kwargs["csv_path"] = args.actual_csv
                trials = 1
            elif an == "matchmaker":
                if args.matchmaker_binary:
                    kwargs["binary"] = args.matchmaker_binary
                trials = args.trials
            elif an == "frc-scheduler-server":
                trials = args.trials
            else:
                trials = args.trials

            for trial in range(trials):
                work.append((fix.to_json_dict(), an, kwargs, args.seed, trial))

    # ── Run ──────────────────────────────────────────────────────────
    t0 = time.monotonic()
    results: list[dict] = []
    if args.workers <= 1:
        for w in work:
            results.append(_run_one(w))
    else:
        with mp.Pool(args.workers) as pool:
            results = pool.map(_run_one, work)
    elapsed = time.monotonic() - t0
    print(f"Completed {len(results)} runs in {elapsed:.1f}s")

    # ── Pick the best per (fixture, adapter) ────────────────────────
    best: dict[tuple[str, str], dict] = {}
    by_pair: dict[tuple[str, str], list[dict]] = {}
    for r in results:
        key = (r["fixture"], r["adapter"])
        by_pair.setdefault(key, []).append(r)
    for key, rs in by_pair.items():
        b = _select_best(rs)
        if b:
            best[key] = b

    # ── Write outputs ───────────────────────────────────────────────
    run_hash = hashlib.sha1(json.dumps(
        {"fixtures": [f.fixture_id for f in fixtures],
         "adapters": adapter_names,
         "trials":   args.trials,
         "seed":     args.seed},
        sort_keys=True).encode()).hexdigest()[:6]
    run_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{run_hash}"
    out_root = Path(args.out_dir) / run_id
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "schedules").mkdir(exist_ok=True)

    # Save every individual schedule
    for r in results:
        if r.get("ok"):
            fname = f"{r['fixture']}__{r['adapter']}__t{r['trial']:03d}.json"
            with open(out_root / "schedules" / fname, "w") as f:
                json.dump(r["schedule"], f, indent=2)

    # Save fixtures used
    with open(out_root / "fixtures.json", "w") as f:
        json.dump([fix.to_json_dict() for fix in fixtures], f, indent=2)

    # Save full machine-readable report
    with open(out_root / "full_report.json", "w") as f:
        json.dump({
            "run_id":   run_id,
            "args":     vars(args),
            "fixtures": [fix.to_json_dict() for fix in fixtures],
            "results":  results,
            "best":     {f"{k[0]}__{k[1]}": v for k, v in best.items()},
        }, f, indent=2)

    # Write the human-readable Markdown
    write_markdown_report(
        out_root / "report.md", run_id, fixtures, best, results
    )
    print()
    print(f"Output: {out_root}")
    print(f"        report.md       — human-readable summary")
    print(f"        full_report.json — complete metrics + diagnostics")
    print(f"        schedules/       — {sum(1 for r in results if r.get('ok'))} schedule JSONs")


if __name__ == "__main__":
    main()
