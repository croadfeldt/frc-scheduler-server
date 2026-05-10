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

# Quality-preset resolver — maps friendly names ('good', 'best', etc.)
# to SA iteration counts. Single source of truth for both UI and
# harness so the adapter, the API endpoint, and this runner agree.
from app.quality_presets import (
    QUALITY_PRESETS,
    iterations_for_preset,
    preset_for_iterations,
)


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


def _composite_score(result: dict) -> float:
    """Single-number summary of a result's overall quality. Lower = better.

    The classification rank in `_select_best` is a tuple comparison; useful
    for picking a winner but not for averaging across fixtures or
    showing a distribution. This collapses the same signal into one
    float so the cross-fixture aggregate and trial distribution can use
    it.

    Composition (chosen so each component is roughly comparable):
      - 10 × poor count       (dominant — every poor metric counts heavily)
      -  3 × acceptable count (acceptable still costs something vs near-optimal)
      -  0.1 × repeat_partners (fine-grained tiebreaker for tight cases)
      -  0.1 × max_color_imbalance

    A schedule with all near-optimal metrics scores 0; one with everything
    poor scores ~110. The middle band 5-25 is "mixed."
    """
    if not result or not result.get("ok"):
        return float("inf")
    rep = result.get("report", {})
    counts = rep.get("counts", {})
    metrics = rep.get("metrics", {})
    return (
        10.0 * counts.get("poor", 0)
        + 3.0 * counts.get("acceptable", 0)
        + 0.1 * metrics.get("repeat_partners", {}).get("value", 0)
        + 0.1 * metrics.get("max_color_imbalance", {}).get("value", 0)
    )


def _team_burden_scores(schedule_dict: dict, fixture: Fixture) -> list[dict]:
    """Per-team burden analysis on a single schedule.

    Returns a list of {team, burden, color, station, min_gap, partner_rep,
    opponent_rep, day_lopsidedness} dicts, sorted by burden descending.

    The composition mirrors the analysis used on 2026mnst:
      - color imbalance (red vs blue count delta)
      - station spread (max station count - min station count)
      - min gap below 5 (gap of 4 = 0.2 cost, gap of 3 = 0.4, etc.)
      - partner repeats (how many distinct partners played 2+ times)
      - opponent repeats (same, for opponents)
      - day lopsidedness (how concentrated the team's matches are
        in one half of the day)

    Each component is normalized to [0, 1] across teams in this fixture
    so the burden score is comparable across fixtures of different
    sizes. A score of 0 = least burdened in this fixture; the highest
    score gets ~1.0 per axis it tops, summing to up to 6.
    """
    from collections import Counter, defaultdict

    matches = schedule_dict.get("matches", []) or []
    if not matches:
        return []

    # Build per-team profiles
    team_data: dict[int, dict] = defaultdict(lambda: {
        "match_nums": [], "colors": [], "stations": [],
        "partners": [], "opponents": [],
    })

    total_matches = max(m.get("match_num", 0) for m in matches)
    midpoint = total_matches // 2 if total_matches > 0 else 0

    for m in matches:
        match_num = m.get("match_num", 0)
        for color in ("red", "blue"):
            alliance = m.get(color, []) or []
            opp_color = "blue" if color == "red" else "red"
            opponents = m.get(opp_color, []) or []
            for pos, team in enumerate(alliance, start=1):
                d = team_data[team]
                d["match_nums"].append(match_num)
                d["colors"].append(color)
                d["stations"].append(pos)
                # Same-alliance partners (excluding self)
                d["partners"].extend(t for t in alliance if t != team)
                d["opponents"].extend(opponents)

    teams = sorted(team_data.keys())
    if not teams:
        return []

    # Per-team raw metrics
    raw = []
    for t in teams:
        d = team_data[t]
        nums = sorted(d["match_nums"])
        color_counts = Counter(d["colors"])
        station_counts = Counter(d["stations"])
        color_imbalance = abs(color_counts.get("blue", 0) - color_counts.get("red", 0))
        station_vals = [station_counts.get(p, 0) for p in (1, 2, 3)]
        station_spread = max(station_vals) - min(station_vals)
        gaps = [nums[i+1] - nums[i] for i in range(len(nums) - 1)]
        min_gap = min(gaps) if gaps else 0
        partner_rep = sum(1 for c in Counter(d["partners"]).values() if c >= 2)
        opponent_rep = sum(1 for c in Counter(d["opponents"]).values() if c >= 2)
        # Day lopsidedness: |first-half count - second-half count|
        first_half = sum(1 for n in nums if n <= midpoint)
        second_half = len(nums) - first_half
        day_lops = abs(first_half - second_half)

        raw.append({
            "team": t, "color": color_imbalance, "station": station_spread,
            "min_gap": min_gap, "partner_rep": partner_rep,
            "opponent_rep": opponent_rep, "day_lops": day_lops,
        })

    # Normalize each axis across teams in this schedule, then sum
    def norm_axis(values: list[float]) -> list[float]:
        if not values:
            return []
        lo, hi = min(values), max(values)
        if hi == lo:
            return [0.0] * len(values)
        return [(v - lo) / (hi - lo) for v in values]

    color_norm   = norm_axis([r["color"]        for r in raw])
    station_norm = norm_axis([r["station"]      for r in raw])
    # min_gap: lower is worse, so invert
    gap_floor = min(r["min_gap"] for r in raw)
    gap_ceil  = max(r["min_gap"] for r in raw)
    if gap_ceil == gap_floor:
        gap_norm = [0.0] * len(raw)
    else:
        gap_norm = [(gap_ceil - r["min_gap"]) / (gap_ceil - gap_floor) for r in raw]
    prep_norm    = norm_axis([r["partner_rep"]  for r in raw])
    orep_norm    = norm_axis([r["opponent_rep"] for r in raw])
    lops_norm    = norm_axis([r["day_lops"]     for r in raw])

    out = []
    for i, r in enumerate(raw):
        burden = (color_norm[i] + station_norm[i] + gap_norm[i]
                  + prep_norm[i] + orep_norm[i] + lops_norm[i])
        out.append({**r, "burden": burden})
    out.sort(key=lambda x: -x["burden"])
    return out


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

    # ── Cross-fixture aggregate ─────────────────────────────────────
    # Single-table summary across all fixtures so a multi-fixture run
    # produces a verdict at the top rather than buried in 20 per-fixture
    # tables. For each adapter: classification roll-up across fixtures,
    # and head-to-head against every other adapter on the composite.
    all_adapter_names: list[str] = []
    for (fid, an) in best_results.keys():
        if an not in all_adapter_names:
            all_adapter_names.append(an)

    if all_adapter_names and len(fixtures) > 1:
        lines.append("## Cross-fixture aggregate")
        lines.append("")
        lines.append("Composite score: lower is better. 0 = all metrics near-optimal; "
                     "~110 = all metrics poor. The 5-25 band is mixed.")
        lines.append("")
        lines.append("| Adapter | Fixtures | Near-optimal | Acceptable | Poor | Mean composite |")
        lines.append("|---|---|---|---|---|---|")
        for an in all_adapter_names:
            classifications = []
            composites = []
            for fix in fixtures:
                r = best_results.get((fix.fixture_id, an))
                if r and r.get("ok"):
                    overall = r["report"].get("overall", "?")
                    classifications.append(overall)
                    composites.append(_composite_score(r))
            n = len(classifications)
            n_near = sum(1 for c in classifications if c == "near_optimal")
            n_acc  = sum(1 for c in classifications if c == "acceptable")
            n_poor = sum(1 for c in classifications if c == "poor")
            mean_comp = (sum(composites) / len(composites)) if composites else float("nan")
            lines.append(f"| {an} | {n} | {n_near} | {n_acc} | {n_poor} | {mean_comp:.2f} |")
        lines.append("")

        # Head-to-head: pairwise W-L-T per fixture on composite. T = composites
        # within 0.01 of each other (functionally identical).
        if len(all_adapter_names) >= 2:
            lines.append("### Head-to-head")
            lines.append("")
            lines.append("Per-fixture wins on composite score. T = within 0.01.")
            lines.append("")
            header = "| | " + " | ".join(all_adapter_names) + " |"
            lines.append(header)
            lines.append("|---" + "|---" * len(all_adapter_names) + "|")
            for an_row in all_adapter_names:
                cells = [f"**{an_row}**"]
                for an_col in all_adapter_names:
                    if an_row == an_col:
                        cells.append("—")
                        continue
                    wins = losses = ties = 0
                    for fix in fixtures:
                        r_row = best_results.get((fix.fixture_id, an_row))
                        r_col = best_results.get((fix.fixture_id, an_col))
                        if not (r_row and r_row.get("ok") and r_col and r_col.get("ok")):
                            continue
                        s_row = _composite_score(r_row)
                        s_col = _composite_score(r_col)
                        if abs(s_row - s_col) < 0.01:
                            ties += 1
                        elif s_row < s_col:
                            wins += 1
                        else:
                            losses += 1
                    cells.append(f"{wins}W-{losses}L-{ties}T")
                lines.append("| " + " | ".join(cells) + " |")
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
        lines.append("| Adapter | Overall | Composite | Generation time | Notes |")
        lines.append("|---|---|---|---|---|")
        for an in adapter_names:
            r = adapter_results[an]
            if r.get("ok"):
                rep = r["report"]
                sched = r["schedule"]
                overall = rep.get("overall", "?")
                composite = _composite_score(r)
                t_sec = sched.get("generation_seconds", 0)
                notes_list = []
                diag = sched.get("adapter_diagnostics", {})
                if "stage1_score" in diag:
                    notes_list.append(f"score={diag['stage1_score']:.0f}")
                if diag.get("source"):
                    notes_list.append(f"source={diag['source']}")
                # Surface the SA iteration count for frc-scheduler-server
                # so reports are self-describing — a reader looking at an
                # old report can see whether SA was running and at what
                # budget. Hides the field when the adapter doesn't expose
                # it (actual, matchmaker) so the column stays clean.
                if "sa_iterations" in diag:
                    sa = diag["sa_iterations"]
                    preset = preset_for_iterations(sa)
                    if preset:
                        notes_list.append(f"sa_iters={sa:,} ({preset})")
                    else:
                        notes_list.append(f"sa_iters={sa:,}")
                lines.append(f"| {an} | {_classification_marker(overall)} {overall} | "
                             f"{composite:.2f} | {t_sec:.2f}s | {', '.join(notes_list)} |")
            else:
                lines.append(f"| {an} | ERROR | — | — | {r.get('error', 'unknown')} |")
        lines.append("")

        # ── Trial distribution ──────────────────────────────────────
        # For each adapter that ran multiple trials, show the spread of
        # composite + key metric values. Catches "best is fine but
        # median is poor" — i.e., high-variance adapters that need many
        # retries to be production-deployable.
        per_adapter_trials: dict[str, list[dict]] = {}
        for r in all_results:
            if r.get("fixture") == fix.fixture_id:
                per_adapter_trials.setdefault(r["adapter"], []).append(r)

        any_distribution_shown = False
        distribution_lines: list[str] = []
        for an in adapter_names:
            trials = per_adapter_trials.get(an, [])
            successful_trials = [t for t in trials if t.get("ok")]
            if len(successful_trials) <= 1:
                continue  # deterministic adapter or single-trial; skip
            any_distribution_shown = True
            composites = sorted(_composite_score(t) for t in successful_trials)
            n = len(composites)
            best = composites[0]
            worst = composites[-1]
            median = composites[n // 2]
            mean = sum(composites) / n
            std = (sum((c - mean) ** 2 for c in composites) / n) ** 0.5

            # Repeat partners + color imbalance distribution — the two most
            # commonly cited fairness metrics. Show best/median/worst for each.
            def _metric_distribution(metric_name: str) -> str:
                vals = sorted(
                    t["report"]["metrics"].get(metric_name, {}).get("value", 0)
                    for t in successful_trials
                )
                m = len(vals)
                return f"best {vals[0]:g}, median {vals[m//2]:g}, worst {vals[-1]:g}"

            distribution_lines.append(
                f"- **{an}** ({n} trials): composite "
                f"best {best:.2f}, median {median:.2f}, worst {worst:.2f}, "
                f"std {std:.2f}"
            )
            distribution_lines.append(
                f"  - repeat_partners: { _metric_distribution('repeat_partners') }"
            )
            distribution_lines.append(
                f"  - max_color_imbalance: { _metric_distribution('max_color_imbalance') }"
            )

        if any_distribution_shown:
            lines.append("**Trial distribution**")
            lines.append("")
            lines.extend(distribution_lines)
            lines.append("")

        # ── Per-team burden in worst-case schedules ─────────────────
        # When the best schedule is "poor" overall, surface which teams
        # are most affected. The same fairness analysis applied manually
        # on 2026mnst, now automatic.
        for an in adapter_names:
            r = adapter_results[an]
            if not r.get("ok"):
                continue
            overall = r["report"].get("overall", "")
            if overall != "poor":
                continue
            burden_rows = _team_burden_scores(r["schedule"], fix)
            if not burden_rows:
                continue
            lines.append(f"**Most-affected teams in {an}'s best schedule**")
            lines.append("")
            lines.append("| # | Team | Burden | Color | Station | Min gap | Partner rep | Opp rep | Day lops |")
            lines.append("|---|---|---|---|---|---|---|---|---|")
            for i, br in enumerate(burden_rows[:5], start=1):
                lines.append(
                    f"| {i} | {br['team']} | {br['burden']:.2f} | "
                    f"{br['color']} | {br['station']} | {br['min_gap']} | "
                    f"{br['partner_rep']} | {br['opponent_rep']} | {br['day_lops']} |"
                )
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Methodology")
    lines.append("")
    lines.append("- For stochastic adapters, the harness runs N trials per fixture and reports the BEST.")
    lines.append("  'Best' = fewest 'poor' metrics, then most 'near_optimal', then lowest repeat-partner count.")
    lines.append("- Composite score collapses classifications into a single float for ranking and head-to-head:")
    lines.append("  `10 × poor + 3 × acceptable + 0.1 × repeat_partners + 0.1 × max_color_imbalance`. Lower = better.")
    lines.append("- Trial distribution shows variance across all N trials, not just the best — catches")
    lines.append("  high-variance adapters whose median output isn't production-deployable.")
    lines.append("- Per-team burden normalizes color, station, gap, repeats, and day rhythm across teams")
    lines.append("  in a single schedule, so the most-affected teams surface automatically.")
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
    # SA iteration knobs for the frc-scheduler-server adapter. Either flag
    # may be passed; --quality-preset is the friendly form, --sa-iterations
    # is the explicit override. If both are passed, --sa-iterations wins
    # (explicit beats friendly). If neither is passed, the adapter falls
    # through to its DEFAULT_SA_ITERATIONS (the UI's default preset).
    # Historical note: prior to 2026-05-10 the runner had no way to set
    # this; the adapter defaulted to 0 (construction-only). The 49.29 and
    # 40.12 baselines in EVAL_FINDINGS.md were both run with no SA. Use
    # --sa-iterations 0 to reproduce those construction-only baselines.
    ap.add_argument("--sa-iterations", type=int, default=None,
                    help="explicit SA iteration count for frc-scheduler-server "
                         "(overrides --quality-preset). 0 = construction only.")
    ap.add_argument("--quality-preset", default=None,
                    choices=sorted(QUALITY_PRESETS.keys()),
                    help="UI-friendly preset name for frc-scheduler-server. "
                         "Resolves to an iteration count via app/quality_presets.py.")
    args = ap.parse_args()

    # Resolve the SA iteration count. Explicit --sa-iterations wins. If
    # only --quality-preset is given, look it up. If neither, leave as
    # None and let the adapter's DEFAULT_SA_ITERATIONS apply.
    resolved_sa: int | None = None
    if args.sa_iterations is not None:
        resolved_sa = args.sa_iterations
    elif args.quality_preset is not None:
        resolved_sa = iterations_for_preset(args.quality_preset)

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
    # Surface the SA iteration count so the run banner reflects exactly
    # what the harness is testing. Without this it's easy to run with
    # default settings and not realize the SA isn't running (this hid
    # the 0-iteration default until 2026-05-10).
    if "frc-scheduler-server" in adapter_names:
        if resolved_sa is not None:
            preset_name = preset_for_iterations(resolved_sa) or "custom"
            print(f"SA iters: {resolved_sa:,} ({preset_name}) — frc-scheduler-server")
        else:
            from scripts.scheduler_eval.adapters.frc_scheduler_server import (
                DEFAULT_SA_ITERATIONS,
            )
            preset_name = preset_for_iterations(DEFAULT_SA_ITERATIONS) or "custom"
            print(f"SA iters: {DEFAULT_SA_ITERATIONS:,} ({preset_name}, "
                  f"adapter default) — frc-scheduler-server")
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
                # Pass the resolved SA budget through to the adapter. If
                # nothing was specified on the CLI, leave kwargs empty
                # and let the adapter's DEFAULT_SA_ITERATIONS apply —
                # that way "no flag" means "what the UI's default users
                # get," not "construction-only."
                if resolved_sa is not None:
                    kwargs["sa_iterations"] = resolved_sa
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
