"""Pull fixtures and actual schedules from The Blue Alliance.

Usage:
    # Pull a single event
    python -m scripts.scheduler_eval.pull_tba_fixtures 2024mnst

    # Pull a list (one event key per line in a file)
    python -m scripts.scheduler_eval.pull_tba_fixtures --keys-file events.txt

    # Pull every MN event for a year
    python -m scripts.scheduler_eval.pull_tba_fixtures --year 2024 --state MN

For each event, writes two files into scripts/scheduler_eval/fixtures/:

    {event_key}.json                — the Fixture (input description)
    {event_key}__actual.json        — the played schedule (Schedule object)

The Fixture is what gets fed to scheduling adapters. The actual schedule
is what the runner can compare against without re-fetching.

Requires TBA_API_KEY in the environment. The script fails fast if it's
not set.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow `python -m scripts.scheduler_eval.pull_tba_fixtures` from repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.scheduler_eval.adapters.actual import (
    _team_key_to_num,
    _qual_match_number,
    _surrogate_flags,
)
from scripts.scheduler_eval.harness_types import Fixture, Match, Schedule


HERE         = Path(__file__).parent
FIXTURES_DIR = HERE / "fixtures"


def _check_api_key():
    if not os.environ.get("TBA_API_KEY", "").strip():
        print("ERROR: TBA_API_KEY env var is not set.", file=sys.stderr)
        print("Get one from https://www.thebluealliance.com/account and export:", file=sys.stderr)
        print("    export TBA_API_KEY=your_key_here", file=sys.stderr)
        sys.exit(2)


async def _fetch_event(event_key: str) -> tuple[Fixture, Schedule] | None:
    """Pull event metadata, team list, and matches from TBA.

    Returns (Fixture, Schedule) on success. Returns None and prints a
    warning on any of the per-event failure cases:
      - Event has no quals (cancelled, future event, off-season w/o data)
      - Team count differs from quals × 6 / matches_per_team (data
        inconsistent — usually means the event used a non-standard
        scheduling structure)
      - TBA returns nothing (event key wrong, or pre-data)
    """
    from app import tba as tba_client

    try:
        evt   = await tba_client.get_event(event_key)
    except Exception as e:
        print(f"  [{event_key}] event fetch failed: {e}")
        return None
    if not evt or not evt.get("name"):
        print(f"  [{event_key}] no event data on TBA")
        return None

    try:
        teams = await tba_client.get_event_teams(event_key)
    except Exception as e:
        print(f"  [{event_key}] teams fetch failed: {e}")
        return None
    team_numbers = sorted({_team_key_to_num(t["key"]) for t in teams})
    if len(team_numbers) < 6:
        print(f"  [{event_key}] only {len(team_numbers)} teams; skipping (need ≥6)")
        return None

    try:
        all_matches = await tba_client.get_event_matches(event_key)
    except Exception as e:
        print(f"  [{event_key}] matches fetch failed: {e}")
        return None
    quals = [m for m in all_matches if m.get("comp_level") == "qm"]
    if not quals:
        print(f"  [{event_key}] no qual matches on TBA; skipping")
        return None

    # Build the played-schedule (Match objects) and infer matches_per_team
    # from the actual data — TBA doesn't expose a "matches per team"
    # field directly, so we count.
    parsed_matches: list[Match] = []
    team_appearance_count: dict[int, int] = {}
    surrogate_total = 0
    for m in quals:
        alliances = m.get("alliances") or {}
        red  = alliances.get("red")  or {}
        blue = alliances.get("blue") or {}
        red_teams  = [_team_key_to_num(k) for k in (red.get("team_keys")  or [])]
        blue_teams = [_team_key_to_num(k) for k in (blue.get("team_keys") or [])]
        if not red_teams or not blue_teams:
            print(f"  [{event_key}] match {m.get('key')} missing alliance data; skipping event")
            return None
        if len(red_teams) != len(blue_teams):
            print(f"  [{event_key}] match {m.get('key')} alliance size mismatch; skipping event")
            return None
        red_surr  = _surrogate_flags(red_teams,  red.get("surrogate_team_keys"))
        blue_surr = _surrogate_flags(blue_teams, blue.get("surrogate_team_keys"))
        for t in red_teams + blue_teams:
            team_appearance_count[t] = team_appearance_count.get(t, 0) + 1
        surrogate_total += sum(red_surr) + sum(blue_surr)

        parsed_matches.append(Match(
            match_num=_qual_match_number(m["key"]),
            blue=blue_teams, red=red_teams,
            blue_surrogate=blue_surr, red_surrogate=red_surr,
        ))
    parsed_matches.sort(key=lambda mm: mm.match_num)

    teams_per_alliance = len(parsed_matches[0].red)

    # Some teams attend events but never play (alternate, dropped, etc.)
    # Use the playing teams as the canonical roster — the absent ones
    # would just clutter the fixture with teams that have no matches.
    playing_teams = sorted(team_appearance_count.keys())
    if len(playing_teams) < 6:
        print(f"  [{event_key}] only {len(playing_teams)} playing teams; skipping")
        return None

    # Subtract surrogate slots from the appearance count to get "real"
    # matches-per-team: surrogate participation pads counts above the
    # team's regular schedule.
    surrogate_appearances: dict[int, int] = {}
    for m in parsed_matches:
        for i, t in enumerate(m.red):
            if m.red_surrogate[i]:
                surrogate_appearances[t] = surrogate_appearances.get(t, 0) + 1
        for i, t in enumerate(m.blue):
            if m.blue_surrogate[i]:
                surrogate_appearances[t] = surrogate_appearances.get(t, 0) + 1

    real_appearances = {
        t: team_appearance_count[t] - surrogate_appearances.get(t, 0)
        for t in playing_teams
    }
    appearance_distribution = sorted(set(real_appearances.values()))
    if len(appearance_distribution) > 1:
        # Rare: at some events different teams play different counts.
        # We use the modal count as matches_per_team; teams with other
        # counts are noted in the fixture's notes field.
        from collections import Counter
        modal_count, _ = Counter(real_appearances.values()).most_common(1)[0]
        matches_per_team = modal_count
        outliers = [t for t, c in real_appearances.items() if c != modal_count]
        outlier_note = (f"NOTE: {len(outliers)} teams played a non-modal "
                        f"count ({outliers[:5]}{'...' if len(outliers) > 5 else ''})")
    else:
        matches_per_team = appearance_distribution[0]
        outlier_note = ""

    # Detect surrogate round if surrogates were used
    surrogate_round = None
    if surrogate_total > 0:
        # The round in which surrogates appear — first match where any
        # surrogate flag is true. TBA's "surrogate round" is 1-indexed
        # in matchmaker terminology, but here we just record the match
        # number for descriptive purposes.
        for m in parsed_matches:
            if any(m.red_surrogate) or any(m.blue_surrogate):
                surrogate_round = m.match_num
                break

    fixture_id = event_key  # use the TBA event key as the fixture ID
    fixture = Fixture(
        fixture_id=fixture_id,
        name=evt.get("name") or event_key,
        teams=playing_teams,
        matches_per_team=matches_per_team,
        teams_per_alliance=teams_per_alliance,
        surrogate_round=surrogate_round,
        source="tba",
        year=evt.get("year"),
        event_key=event_key,
        notes=(
            f"Pulled from TBA on {datetime.now(timezone.utc).date().isoformat()}. "
            f"{len(playing_teams)} teams, {len(parsed_matches)} qual matches."
            + (f" {outlier_note}" if outlier_note else "")
        ).strip(),
    )

    schedule = Schedule(
        fixture_id=fixture_id,
        adapter_name="actual",
        matches=parsed_matches,
        generation_seconds=0.0,
        adapter_diagnostics={
            "source":           "tba",
            "tba_event_key":    event_key,
            "surrogate_total":  surrogate_total,
            "fetched_at":       datetime.now(timezone.utc).isoformat(),
        },
        generated_at=datetime.now(timezone.utc).isoformat(),
    )

    return fixture, schedule


def _resolve_event_keys(args) -> list[str]:
    keys: list[str] = []
    if args.event_keys:
        keys.extend(args.event_keys)
    if args.keys_file:
        with open(args.keys_file) as f:
            for line in f:
                # Strip inline comments first ('#' anywhere on the line),
                # then trim whitespace. Take only the first whitespace-
                # separated token so trailing notes like "2024mnst extra
                # context" don't end up in the key.
                line = line.split("#", 1)[0].strip()
                if not line:
                    continue
                key = line.split()[0]
                keys.append(key)
    if args.year:
        keys.extend(_keys_for_year(args.year, state_filter=args.state))
    # Dedupe preserving order
    seen = set()
    out = []
    for k in keys:
        if k not in seen:
            out.append(k); seen.add(k)
    return out


def _keys_for_year(year: int, *, state_filter: str | None = None) -> list[str]:
    """Get every TBA event key for a year, optionally filtered by state.

    state_filter is a 2-letter state code (e.g. "MN"); matched against
    the event's `state_prov` field.
    """
    from app import tba as tba_client

    async def _go():
        events = await tba_client.get_events(year)
        out = []
        for e in events:
            if state_filter and e.get("state_prov") != state_filter:
                continue
            out.append(e["key"])
        return out
    return asyncio.run(_go())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("event_keys", nargs="*",
                    help="TBA event keys, e.g. '2024mnst'. Can also be supplied via --keys-file.")
    ap.add_argument("--keys-file", default=None,
                    help="path to a text file with one event key per line; '#' for comments")
    ap.add_argument("--year", type=int, default=None,
                    help="pull every event for a year (combine with --state to filter)")
    ap.add_argument("--state", default=None,
                    help="2-letter state filter for --year")
    ap.add_argument("--out-dir", default=str(FIXTURES_DIR),
                    help="where to write fixture+schedule JSONs")
    ap.add_argument("--overwrite", action="store_true",
                    help="re-fetch and overwrite existing fixtures (default: skip existing)")
    args = ap.parse_args()

    _check_api_key()

    keys = _resolve_event_keys(args)
    if not keys:
        print("No event keys provided. Pass keys as args, --keys-file, or --year.")
        sys.exit(2)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Pulling {len(keys)} event(s) from TBA...")
    summary = {"ok": 0, "skipped": 0, "failed": 0}

    for key in keys:
        fixture_path  = out_dir / f"{key}.json"
        schedule_path = out_dir / f"{key}__actual.json"
        if fixture_path.exists() and schedule_path.exists() and not args.overwrite:
            print(f"  [{key}] already pulled; skipping (use --overwrite to refresh)")
            summary["skipped"] += 1
            continue

        print(f"  [{key}] fetching...")
        try:
            result = asyncio.run(_fetch_event(key))
        except Exception as e:
            print(f"  [{key}] FAILED: {type(e).__name__}: {e}")
            summary["failed"] += 1
            continue
        if result is None:
            summary["failed"] += 1
            continue
        fixture, schedule = result
        fixture.save(fixture_path)
        schedule.save(schedule_path)
        print(f"  [{key}] OK — {fixture.num_teams} teams, "
              f"{fixture.matches_per_team} matches each, "
              f"{schedule.num_matches} qual matches")
        summary["ok"] += 1

    print()
    print(f"Done. Successful: {summary['ok']}  "
          f"Skipped: {summary['skipped']}  Failed: {summary['failed']}")


if __name__ == "__main__":
    main()
