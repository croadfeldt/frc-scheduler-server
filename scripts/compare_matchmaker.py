#!/usr/bin/env python3
"""Parse MatchMaker text output, compute lex tuple, compare against our scheduler.

MatchMaker text format (per match line):
    match_num  t1 s1  t2 s2  t3 s3  t4 s4  t5 s5  t6 s6
where t1-t3 are the red alliance, t4-t6 are the blue alliance, and
sN is the surrogate flag for team tN (0 or 1).

(Per Saxton: MatchMaker outputs red first, then blue, in the standard
text dump.)
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from app.scheduler import (
    Match, generate_matches, score_tuple_for_schedule,
    _build_state_from_matches, _score_from_state,
)


def parse_matchmaker(path: str) -> list[Match]:
    """Parse a MatchMaker text dump into a list of Match objects."""
    matches = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 13:
                raise ValueError(f"Expected 13 tokens, got {len(parts)}: {line!r}")
            mn = int(parts[0])
            t = [int(x) for x in parts[1:]]
            # t = [t1, s1, t2, s2, t3, s3, t4, s4, t5, s5, t6, s6]
            red       = (t[0], t[2], t[4])
            red_sur   = (bool(t[1]), bool(t[3]), bool(t[5]))
            blue      = (t[6], t[8], t[10])
            blue_sur  = (bool(t[7]), bool(t[9]), bool(t[11]))
            matches.append(Match(red=red, blue=blue,
                                 red_surrogate=red_sur,
                                 blue_surrogate=blue_sur))
    return matches


def per_criterion_breakdown(matches: list[Match], num_teams: int, label: str):
    """Print FRC §10.5.2 criterion-by-criterion analysis."""
    state = _build_state_from_matches(matches, num_teams)
    tup = _score_from_state(state)

    rc = state['rc']; bc = state['bc']
    par = state['par']; opp = state['opp']
    sta = state['station_counts']

    # Cooldown details
    team_matches = state['team_matches']
    bad_gaps = []
    for t, ms in team_matches.items():
        for j in range(1, len(ms)):
            gap = ms[j] - ms[j-1]
            if gap < 3:
                bad_gaps.append((t, ms[j-1], ms[j], gap))

    # Partner repeats
    par_dist = {1: 0, 2: 0, 3: 0, 4: 0}
    for v in par.values():
        if v >= 4:
            par_dist[4] += 1
        else:
            par_dist[v] += 1
    par_max = max(par.values()) if par else 0
    par_repeats = sum(1 for v in par.values() if v >= 2)

    # Opponent repeats
    opp_dist = {1: 0, 2: 0, 3: 0, 4: 0}
    for v in opp.values():
        if v >= 4:
            opp_dist[4] += 1
        else:
            opp_dist[v] += 1
    opp_max = max(opp.values()) if opp else 0
    opp_repeats = sum(1 for v in opp.values() if v >= 2)

    # R/B
    rb_diffs = sorted([(t, rc[t] - bc[t]) for t in rc], key=lambda x: -abs(x[1]))
    max_rb = max(abs(d) for _, d in rb_diffs) if rb_diffs else 0
    teams_5_2 = sum(1 for t in rc if max(rc[t], bc[t]) >= 5)

    # Station spread
    spreads = []
    for t in rc:
        spreads.append((t, max(sta[t]) - min(sta[t])))
    spreads.sort(key=lambda x: -x[1])
    max_sp = spreads[0][1] if spreads else 0

    print(f"=== {label} ===")
    print(f"Lex tuple: {tup}")
    print(f"  cooldown_violations  = {tup[0]}")
    if bad_gaps:
        print(f"     details: {bad_gaps[:5]}{'...' if len(bad_gaps) > 5 else ''}")
    print(f"  par_quad             = {tup[1]}  (max repeat={par_max}, "
          f"{par_repeats} pairs repeat ≥1, dist by repeat-count: {par_dist})")
    print(f"  opp_quad             = {tup[2]}  (max repeat={opp_max}, "
          f"{opp_repeats} pairs repeat ≥1, dist: {opp_dist})")
    print(f"  surrogate_count      = {tup[3]}")
    print(f"  rb_metric            = {tup[4]}  (max |R-B| = {max_rb}; "
          f"teams with 5+ on one color: {teams_5_2})")
    print(f"  station_pen          = {tup[5]}  (max spread = {max_sp})")
    print(f"  surrogate_spread     = {tup[6]}")
    print(f"  match_equity         = {tup[7]}")
    print()
    return tup, state


def main():
    mm_path = sys.argv[1] if len(sys.argv) > 1 else '/mnt/user-data/uploads/state_qual_schedule.txt'

    mm_matches = parse_matchmaker(mm_path)
    teams = set()
    for m in mm_matches:
        teams.update(m.red); teams.update(m.blue)
    n_teams = len(teams)
    print(f"Parsed {len(mm_matches)} matches; {n_teams} unique teams")
    print(f"Total team appearances: {sum(len(m.red) + len(m.blue) for m in mm_matches)}")
    print(f"Implied MPT: {sum(len(m.red) + len(m.blue) for m in mm_matches) / n_teams:.2f}")
    print()

    mm_tuple, mm_state = per_criterion_breakdown(mm_matches, n_teams, "MatchMaker (state qual)")

    # Generate ours at multiple iteration levels with the SAME team list,
    # so the comparison is apples-to-apples.
    team_list = sorted(teams)
    print(f"Now generating ours with team list: {team_list[:6]}...")
    print()

    import time
    for label, n_sa in [("Ours SA=0",        0),
                        ("Ours SA=10000",    10_000),
                        ("Ours SA=100000",   100_000),
                        ("Ours SA=1000000",  1_000_000)]:
        # Best of 5 trials so we don't get unlucky
        best_tup = None
        best_matches = None
        t0 = time.time()
        for trial in range(5):
            r = generate_matches(
                num_teams=n_teams, matches_per_team=7, ideal_gap=3,
                seed=trial * 7919 + 42,
                team_numbers=team_list,
                n_sa_iterations=n_sa,
                rb_post_pass=True,
            )
            t = score_tuple_for_schedule(r.matches, n_teams)
            if best_tup is None or t < best_tup:
                best_tup = t
                best_matches = r.matches
        elapsed = time.time() - t0
        per_criterion_breakdown(best_matches, n_teams,
                                f"{label} (best of 5 trials, total {elapsed:.1f}s)")

    # Final lex comparison — who's better?
    print("=" * 72)
    print("LEX COMPARISON SUMMARY (lower tuple = better):")
    print(f"  MatchMaker:     {mm_tuple}")


if __name__ == '__main__':
    main()
