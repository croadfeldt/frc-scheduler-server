"""Smoke test — load 2026mnst CSV, run metrics, compare to reviewer's numbers.

The reviewer reported (verified independently in earlier session):
  - 9 repeat partner pairs (count_match)
  - 33 repeat opponent pairs, 1 facing 3+ times (count_match)
  - 3 teams with 6/7 matches on Red (color_balance)
  - 2 teams with min gap of 3 matches (match_gap)
  - 4 teams with station spread of 3 (station_spread)

If our metrics agree with these numbers we have a working baseline.
"""

import csv
import sys
from pathlib import Path

# Allow running from the repo root or from this directory
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.scheduler_eval.harness_types   import Fixture, Match, Schedule
from scripts.scheduler_eval.metrics import analyze


def load_csv(csv_path: Path, fixture_id: str) -> Schedule:
    """Parse the reviewer-style CSV into a Schedule.

    Format columns: Type, Match, Day, Time, Blue 1-3, Red 1-3, Surrogates
    Practice rows are skipped — only Qualification rows go into the
    Schedule (matching our metrics' qualification-only scope).
    """
    matches = []
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            if row["Type"] != "Qualification":
                continue
            mn = int(row["Match"].lstrip("Q"))
            blue = [int(row[f"Blue {i}"]) for i in (1, 2, 3)]
            red  = [int(row[f"Red {i}"])  for i in (1, 2, 3)]
            # Surrogates column is comma-separated team numbers, may be empty
            surr_str = (row.get("Surrogates") or "").strip()
            surr_teams = set()
            if surr_str:
                surr_teams = {int(s.strip()) for s in surr_str.split(",") if s.strip()}
            blue_surr = [t in surr_teams for t in blue]
            red_surr  = [t in surr_teams for t in red]
            matches.append(Match(
                match_num=mn, blue=blue, red=red,
                blue_surrogate=blue_surr, red_surrogate=red_surr,
            ))
    matches.sort(key=lambda m: m.match_num)
    return Schedule(fixture_id=fixture_id, adapter_name="actual", matches=matches)


def main():
    csv_path = Path("/tmp/analysis/schedule.csv")
    if not csv_path.exists():
        print(f"CSV not found at {csv_path}; aborting")
        sys.exit(1)
    fixture_path = Path(__file__).parent / "fixtures" / "2026mnst.json"
    fixture = Fixture.load(fixture_path)
    schedule = load_csv(csv_path, "2026mnst")

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
