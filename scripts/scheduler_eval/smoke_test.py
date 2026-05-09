"""Smoke test — load 2026mnst's pre-pulled actual schedule, run metrics,
compare to reviewer's numbers.

The reviewer reported (verified independently in earlier session):
  - 9 repeat partner pairs (count_match)
  - 33 repeat opponent pairs, 1 facing 3+ times (count_match)
  - 3 teams with 6/7 matches on Red (color_balance)
  - 2 teams with min gap of 3 matches (match_gap)
  - 4 teams with station spread of 3 (station_spread)

If our metrics agree with these numbers we have a working baseline.

Reads from scripts/scheduler_eval/fixtures/2026mnst__actual.json which
ships in the repo. No external files or paths required — runs anywhere
the harness is checked out.
"""

import sys
from pathlib import Path

# Allow running from the repo root or from this directory
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.scheduler_eval.harness_types import Fixture, Schedule
from scripts.scheduler_eval.metrics import analyze


def main():
    here = Path(__file__).parent
    fixture_path  = here / "fixtures" / "2026mnst.json"
    schedule_path = here / "fixtures" / "2026mnst__actual.json"

    if not fixture_path.exists():
        print(f"Fixture not found: {fixture_path}", file=sys.stderr)
        sys.exit(1)
    if not schedule_path.exists():
        print(f"Pre-pulled schedule not found: {schedule_path}", file=sys.stderr)
        print("(This file ships in the repo; if it's missing, "
              "your checkout is incomplete.)", file=sys.stderr)
        sys.exit(1)

    fixture  = Fixture.load(fixture_path)
    schedule = Schedule.load(schedule_path)

    print(f"Loaded {len(schedule.matches)} qualification matches")
    print(f"Fixture: {fixture.num_teams} teams, {fixture.matches_per_team} matches each")
    print(f"  expected total matches: {fixture.total_matches}")
    print()

    report = analyze(schedule, fixture)
    print("=" * 70)
    print(f"Analysis: {fixture.fixture_id} via {schedule.adapter_name}")
    print("=" * 70)
    print(f"Overall classification: {report.overall.upper()}")
    print(f"Counts: {report.counts}")
    print()

    expected = {
        "repeat_partners":     9,
        "max_partner_repeats": 2,
        "repeat_opponents":    33,
        "max_opponent_repeats": 3,
        "max_color_imbalance": 5,
        "teams_with_5_2_color": 10,
        "max_station_spread":  3,
        "min_match_gap":       3,
        "back_to_back_matches": 0,
    }

    print(f"{'metric':28s}  {'value':>8s}  {'expected':>8s}  match  classification")
    print("-" * 78)
    all_pass = True
    for name, m in report.metrics.items():
        exp = expected.get(name, "—")
        if isinstance(exp, (int, float)):
            ok = abs(m.value - exp) < 0.001
            mark = "✓" if ok else "✗"
            if not ok:
                all_pass = False
        else:
            mark = "—"
        print(f"{name:28s}  {m.value:>8.0f}  {str(exp):>8s}  {mark:>5s}  {m.classification}")

    print()
    if all_pass:
        print("✓ All checked metrics match the reviewer's numbers. Metrics module is correct.")
    else:
        print("✗ One or more metrics disagree with the reviewer's numbers. Review needed.")
        sys.exit(2)


if __name__ == "__main__":
    main()
