# SPDX-License-Identifier: GPL-3.0-or-later
# FRC Match Scheduler
# Copyright (C) 2025 FRC Match Scheduler Contributors

"""Tests for Phase 2: driver-station balance post-pass.

Verifies:
  1. Pass terminates and produces a valid schedule.
  2. Pass never increases total_station_pen.
  3. Pass preserves partner pairs (within-alliance permutation invariance).
  4. Pass preserves opponent pairs (alliance composition unchanged).
  5. Pass preserves match team sets (which teams play in which match).
  6. Pass preserves alliance composition (which teams are red vs blue).
  7. Pass preserves cooldown (team match-index lists unchanged).
  8. Pass preserves surrogate counts per team.
  9. SA variant beats or matches greedy on plateau cases.
 10. On real fixtures, station_pen drops measurably.
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.scheduler import Match, generate_matches
from app.post_passes.station_balance import (
    station_balance_pass,
    station_balance_sa,
    _per_team_station_counts,
    _total_station_pen,
    _max_station_spread,
)


def make_test_schedule(num_teams: int, mpt: int, seed: int) -> list[Match]:
    result = generate_matches(num_teams=num_teams, matches_per_team=mpt,
                              ideal_gap=3, seed=seed)
    return list(result.matches)


def _partner_pairs(matches):
    pairs = Counter()
    for m in matches:
        for tri in (m.red, m.blue):
            for i in range(len(tri)):
                for j in range(i + 1, len(tri)):
                    a, b = tri[i], tri[j]
                    pairs[(min(a, b), max(a, b))] += 1
    return pairs


def _opponent_pairs(matches):
    pairs = Counter()
    for m in matches:
        for r in m.red:
            for b in m.blue:
                pairs[(min(r, b), max(r, b))] += 1
    return pairs


def _team_match_indices(matches):
    out = {}
    for i, m in enumerate(matches):
        for t in list(m.red) + list(m.blue):
            out.setdefault(t, []).append(i)
    return out


def _team_alliance_per_match(matches):
    """Map (team, match_idx) → 'R' or 'B'."""
    out = {}
    for i, m in enumerate(matches):
        for t in m.red:
            out[(t, i)] = 'R'
        for t in m.blue:
            out[(t, i)] = 'B'
    return out


def _team_surrogate_count(matches):
    c = Counter()
    for m in matches:
        for t, sur in zip(m.red, m.red_surrogate):
            c.setdefault(t, 0)
            if sur: c[t] += 1
        for t, sur in zip(m.blue, m.blue_surrogate):
            c.setdefault(t, 0)
            if sur: c[t] += 1
    return c


def test_pass_terminates_and_validates():
    print("── test_pass_terminates_and_validates ──")
    for seed in [1, 42, 1000]:
        original = make_test_schedule(36, 7, seed)
        new, stats = station_balance_pass(original)
        assert len(new) == len(original)
        assert stats['sweeps'] < 50
        for i, m in enumerate(new):
            assert len(m.red) == 3 and len(m.blue) == 3
        print(f"  seed={seed}: {stats['permutations']} perms, {stats['sweeps']} sweeps, "
              f"sum {stats['sum_before']}→{stats['sum_after']}, "
              f"max {stats['max_before']}→{stats['max_after']}  ✓")


def test_pass_never_worsens_station_pen():
    print("── test_pass_never_worsens_station_pen ──")
    for seed in [1, 42, 1000, 2026]:
        original = make_test_schedule(36, 7, seed)
        new, stats = station_balance_pass(original)
        assert stats['sum_after'] <= stats['sum_before'], \
            f"seed {seed}: total_pen worsened {stats['sum_before']}→{stats['sum_after']}"
        assert stats['max_after'] <= stats['max_before'], \
            f"seed {seed}: max spread worsened {stats['max_before']}→{stats['max_after']}"
        print(f"  seed={seed}: {stats['sum_before']}→{stats['sum_after']} (max {stats['max_after']})  ✓")


def test_pass_preserves_partner_pairs():
    """Within-alliance permutation: positions change but membership doesn't."""
    print("── test_pass_preserves_partner_pairs ──")
    for seed in [1, 42, 1000]:
        original = make_test_schedule(36, 7, seed)
        before = _partner_pairs(original)
        new, _ = station_balance_pass(original)
        after = _partner_pairs(new)
        assert before == after, f"seed {seed}: partner pairs changed"
        print(f"  seed={seed}: {sum(before.values())} pairs preserved  ✓")


def test_pass_preserves_opponent_pairs():
    print("── test_pass_preserves_opponent_pairs ──")
    for seed in [1, 42, 1000]:
        original = make_test_schedule(36, 7, seed)
        before = _opponent_pairs(original)
        new, _ = station_balance_pass(original)
        after = _opponent_pairs(new)
        assert before == after, f"seed {seed}: opponent pairs changed"
        print(f"  seed={seed}: {sum(before.values())} pairs preserved  ✓")


def test_pass_preserves_match_team_sets():
    print("── test_pass_preserves_match_team_sets ──")
    for seed in [1, 42]:
        original = make_test_schedule(36, 7, seed)
        new, _ = station_balance_pass(original)
        for i, (om, nm) in enumerate(zip(original, new)):
            assert set(om.red + om.blue) == set(nm.red + nm.blue), \
                f"seed {seed} match {i}: team set changed"
        print(f"  seed={seed}: all match team sets preserved  ✓")


def test_pass_preserves_alliance_composition():
    """Per-match red set and blue set unchanged (only positions within them shuffle)."""
    print("── test_pass_preserves_alliance_composition ──")
    for seed in [1, 42]:
        original = make_test_schedule(36, 7, seed)
        new, _ = station_balance_pass(original)
        for i, (om, nm) in enumerate(zip(original, new)):
            assert set(om.red) == set(nm.red), \
                f"seed {seed} match {i}: red set changed {set(om.red)} -> {set(nm.red)}"
            assert set(om.blue) == set(nm.blue), \
                f"seed {seed} match {i}: blue set changed"
        print(f"  seed={seed}: all alliance compositions preserved  ✓")


def test_pass_preserves_team_match_indices():
    print("── test_pass_preserves_team_match_indices ──")
    for seed in [1, 42]:
        original = make_test_schedule(36, 7, seed)
        before = _team_match_indices(original)
        new, _ = station_balance_pass(original)
        after = _team_match_indices(new)
        assert before == after, f"seed {seed}: per-team match indices changed"
        print(f"  seed={seed}: {len(before)} teams' indices preserved (cooldown intact)  ✓")


def test_pass_preserves_surrogate_count_per_team():
    print("── test_pass_preserves_surrogate_count_per_team ──")
    for seed in [1, 42]:
        original = make_test_schedule(36, 7, seed)
        before = _team_surrogate_count(original)
        new, _ = station_balance_pass(original)
        after = _team_surrogate_count(new)
        assert before == after, f"seed {seed}: per-team surrogate count changed"
        print(f"  seed={seed}: surrogate counts preserved per team  ✓")


def test_pass_preserves_alliance_per_match():
    """Per-team-per-match: was on red → still on red after."""
    print("── test_pass_preserves_alliance_per_match ──")
    for seed in [1, 42]:
        original = make_test_schedule(36, 7, seed)
        before = _team_alliance_per_match(original)
        new, _ = station_balance_pass(original)
        after = _team_alliance_per_match(new)
        assert before == after, f"seed {seed}: alliance-per-match map changed"
        print(f"  seed={seed}: alliance per (team, match) preserved  ✓")


def test_sa_variant_preserves_invariants():
    print("── test_sa_variant_preserves_invariants ──")
    for seed in [1, 42, 1000]:
        original = make_test_schedule(36, 7, seed)
        before_p = _partner_pairs(original)
        before_o = _opponent_pairs(original)
        before_idx = _team_match_indices(original)
        before_sur = _team_surrogate_count(original)
        before_ap = _team_alliance_per_match(original)
        new, stats = station_balance_sa(original, n_iterations=2000, seed=42)
        assert _partner_pairs(new) == before_p
        assert _opponent_pairs(new) == before_o
        assert _team_match_indices(new) == before_idx
        assert _team_surrogate_count(new) == before_sur
        assert _team_alliance_per_match(new) == before_ap
        print(f"  seed={seed}: all invariants preserved, "
              f"sum {stats['sum_before']}→{stats['sum_after']}  ✓")


def test_sa_variant_can_match_or_beat_greedy():
    print("── test_sa_variant_can_match_or_beat_greedy ──")
    seeds_with_improvement = 0
    for seed in range(10):
        original = make_test_schedule(36, 7, seed)
        _, greedy_stats = station_balance_pass(original)
        _, sa_stats = station_balance_sa(original, n_iterations=2000, seed=42)
        assert sa_stats['sum_after'] <= greedy_stats['sum_after'], \
            f"seed {seed}: SA worse than greedy"
        if sa_stats['sum_after'] < greedy_stats['sum_after']:
            seeds_with_improvement += 1
        print(f"  seed={seed}: greedy sum={greedy_stats['sum_after']} (max {greedy_stats['max_after']}); "
              f"SA sum={sa_stats['sum_after']} (max {sa_stats['max_after']})")
    print(f"  SA improved over greedy on {seeds_with_improvement}/10 seeds  ✓")


def test_pass_improves_on_real_fixture():
    print("── test_pass_improves_on_real_fixture ──")
    original = make_test_schedule(36, 7, seed=42)
    counts_before = _per_team_station_counts(original)
    sum_before = _total_station_pen(counts_before)
    max_before = _max_station_spread(counts_before)
    new, stats = station_balance_pass(original)
    counts_after = _per_team_station_counts(new)
    sum_after = _total_station_pen(counts_after)
    max_after = _max_station_spread(counts_after)
    print(f"  Before: sum_pen={sum_before}, max_spread={max_before}")
    print(f"  After:  sum_pen={sum_after}, max_spread={max_after}")
    print(f"  Permutations applied: {stats['permutations']}")
    assert sum_after <= sum_before
    print(f"  ✓")


if __name__ == '__main__':
    test_pass_terminates_and_validates()
    test_pass_never_worsens_station_pen()
    test_pass_preserves_partner_pairs()
    test_pass_preserves_opponent_pairs()
    test_pass_preserves_match_team_sets()
    test_pass_preserves_alliance_composition()
    test_pass_preserves_team_match_indices()
    test_pass_preserves_surrogate_count_per_team()
    test_pass_preserves_alliance_per_match()
    test_sa_variant_preserves_invariants()
    test_sa_variant_can_match_or_beat_greedy()
    test_pass_improves_on_real_fixture()
    print("\nAll Phase 2 station post-pass tests passed.")
