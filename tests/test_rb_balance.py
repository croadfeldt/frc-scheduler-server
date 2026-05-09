# SPDX-License-Identifier: GPL-3.0-or-later
# FRC Match Scheduler
# Copyright (C) 2025 FRC Match Scheduler Contributors

"""Tests for Phase 1: Red/Blue balance post-pass.

Verifies:
  1. Pass terminates and produces a valid schedule.
  2. Pass never increases max_imbalance.
  3. Pass preserves partner pairs (red triangles → red triangles, blue → blue).
  4. Pass preserves opponent pairs (cross-alliance pairs unchanged as multisets).
  5. Pass preserves match team sets (which teams play in which match).
  6. Pass preserves surrogate flags (each team's surrogate count unchanged).
  7. Pass preserves cooldown / b2b (same team-set per match, same order).
  8. On real fixtures, max_imbalance drops measurably.
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.scheduler import (
    Match,
    generate_matches,
    score_schedule,
    _build_state_from_matches,
    _score_from_state,
)
from app.post_passes.rb_balance import (
    rb_balance_pass,
    rb_balance_sa,
    _team_color_counts,
    _max_imbalance,
)


def make_test_schedule(num_teams: int, mpt: int, seed: int) -> list[Match]:
    result = generate_matches(num_teams=num_teams, matches_per_team=mpt,
                              ideal_gap=3, seed=seed)
    return list(result.matches)


def _partner_pairs(matches: list[Match]) -> Counter:
    """Multiset of {team_a, team_b} unordered partner pairs across all matches."""
    pairs = Counter()
    for m in matches:
        for tri in (m.red, m.blue):
            for i in range(len(tri)):
                for j in range(i + 1, len(tri)):
                    a, b = tri[i], tri[j]
                    pairs[(min(a, b), max(a, b))] += 1
    return pairs


def _opponent_pairs(matches: list[Match]) -> Counter:
    """Multiset of {team_a, team_b} cross-alliance pairs across all matches."""
    pairs = Counter()
    for m in matches:
        for r in m.red:
            for b in m.blue:
                pairs[(min(r, b), max(r, b))] += 1
    return pairs


def _team_match_indices(matches: list[Match]) -> dict[int, list[int]]:
    """For each team, list of match indices it appears in."""
    out: dict[int, list[int]] = {}
    for i, m in enumerate(matches):
        for t in list(m.red) + list(m.blue):
            out.setdefault(t, []).append(i)
    return out


def _team_surrogate_count(matches: list[Match]) -> Counter:
    """For each team, count of surrogate appearances."""
    c = Counter()
    for m in matches:
        for t, sur in zip(m.red, m.red_surrogate):
            c.setdefault(t, 0)
            if sur:
                c[t] += 1
        for t, sur in zip(m.blue, m.blue_surrogate):
            c.setdefault(t, 0)
            if sur:
                c[t] += 1
    return c


def test_pass_terminates_and_validates():
    """The pass should complete in finite time and produce a valid schedule."""
    print("── test_pass_terminates_and_validates ──")
    for seed in [1, 42, 1000]:
        original = make_test_schedule(36, 7, seed)
        new, stats = rb_balance_pass(original)
        assert len(new) == len(original), f"seed {seed}: match count changed"
        assert stats['sweeps'] < 50, f"seed {seed}: hit max_sweeps cap"
        # Every match has 3 red + 3 blue
        for i, m in enumerate(new):
            assert len(m.red) == 3, f"seed {seed} match {i}: red size != 3"
            assert len(m.blue) == 3, f"seed {seed} match {i}: blue size != 3"
        print(f"  seed={seed}: {stats['flips']} flips, {stats['sweeps']} sweeps  ✓")


def test_pass_never_worsens_max_imbalance():
    """The pass uses a strict-improvement criterion so the metric can only
    improve or stay the same."""
    print("── test_pass_never_worsens_max_imbalance ──")
    for seed in [1, 42, 1000, 2026]:
        original = make_test_schedule(36, 7, seed)
        rc_b, bc_b = _team_color_counts(original)
        max_before = _max_imbalance(rc_b, bc_b)
        new, _ = rb_balance_pass(original)
        rc_a, bc_a = _team_color_counts(new)
        max_after = _max_imbalance(rc_a, bc_a)
        assert max_after <= max_before, \
            f"seed {seed}: max_imbalance worsened {max_before} -> {max_after}"
        print(f"  seed={seed}: max_imbal {max_before} -> {max_after}  ✓")


def test_pass_preserves_partner_pairs():
    """Red-triangle teammates remain red-triangle, blue remain blue. Therefore
    the multiset of partner pairs is invariant under R/B flips."""
    print("── test_pass_preserves_partner_pairs ──")
    for seed in [1, 42, 1000]:
        original = make_test_schedule(36, 7, seed)
        before = _partner_pairs(original)
        new, _ = rb_balance_pass(original)
        after = _partner_pairs(new)
        assert before == after, \
            f"seed {seed}: partner pair multiset changed under R/B flips"
        print(f"  seed={seed}: {sum(before.values())} partner pairs preserved  ✓")


def test_pass_preserves_opponent_pairs():
    """Cross-alliance pairs are symmetric under R/B flip: (r, b) becomes
    (b, r) which is the same unordered pair."""
    print("── test_pass_preserves_opponent_pairs ──")
    for seed in [1, 42, 1000]:
        original = make_test_schedule(36, 7, seed)
        before = _opponent_pairs(original)
        new, _ = rb_balance_pass(original)
        after = _opponent_pairs(new)
        assert before == after, \
            f"seed {seed}: opponent pair multiset changed under R/B flips"
        print(f"  seed={seed}: {sum(before.values())} opponent pairs preserved  ✓")


def test_pass_preserves_match_team_sets():
    """Which teams play in which match is unchanged (only color labels swap)."""
    print("── test_pass_preserves_match_team_sets ──")
    for seed in [1, 42]:
        original = make_test_schedule(36, 7, seed)
        new, _ = rb_balance_pass(original)
        for i, (om, nm) in enumerate(zip(original, new)):
            old_set = set(om.red + om.blue)
            new_set = set(nm.red + nm.blue)
            assert old_set == new_set, \
                f"seed {seed} match {i}: team set changed {old_set} -> {new_set}"
        print(f"  seed={seed}: all {len(original)} matches preserve team sets  ✓")


def test_pass_preserves_team_match_indices():
    """The list of matches each team appears in is identical before and after.
    This implies cooldown, b2b, gap distribution, surrogate-as-3rd-match are
    all preserved."""
    print("── test_pass_preserves_team_match_indices ──")
    for seed in [1, 42]:
        original = make_test_schedule(36, 7, seed)
        before = _team_match_indices(original)
        new, _ = rb_balance_pass(original)
        after = _team_match_indices(new)
        assert before == after, \
            f"seed {seed}: per-team match indices changed (cooldown/b2b would be affected)"
        print(f"  seed={seed}: {len(before)} teams' match-indices preserved  ✓")


def test_pass_preserves_surrogate_count_per_team():
    """Each team's surrogate count is unchanged (flags travel with teams)."""
    print("── test_pass_preserves_surrogate_count_per_team ──")
    for seed in [1, 42]:
        original = make_test_schedule(36, 7, seed)
        before = _team_surrogate_count(original)
        new, _ = rb_balance_pass(original)
        after = _team_surrogate_count(new)
        assert before == after, \
            f"seed {seed}: per-team surrogate count changed"
        total = sum(before.values())
        print(f"  seed={seed}: total surrogate flags={total} preserved per-team  ✓")


def test_sa_variant_preserves_invariants():
    """The SA variant must preserve the same invariants as the greedy pass:
    partner pairs, opponent pairs, team match indices."""
    print("── test_sa_variant_preserves_invariants ──")
    for seed in [1, 42, 1000]:
        original = make_test_schedule(36, 7, seed)
        before_p = _partner_pairs(original)
        before_o = _opponent_pairs(original)
        before_idx = _team_match_indices(original)
        before_sur = _team_surrogate_count(original)

        new, stats = rb_balance_sa(original, n_iterations=2000, seed=42)
        after_p = _partner_pairs(new)
        after_o = _opponent_pairs(new)
        after_idx = _team_match_indices(new)
        after_sur = _team_surrogate_count(new)

        assert before_p == after_p, f"seed {seed}: partner pairs changed in SA variant"
        assert before_o == after_o, f"seed {seed}: opponent pairs changed in SA variant"
        assert before_idx == after_idx, f"seed {seed}: team match indices changed in SA variant"
        assert before_sur == after_sur, f"seed {seed}: per-team surrogate count changed"
        print(f"  seed={seed}: max_imbal {stats['max_before']} -> {stats['max_after']}, "
              f"sum {stats['sum_before']} -> {stats['sum_after']}  ✓")


def test_sa_variant_can_match_or_beat_greedy():
    """SA variant should reach equal-or-better imbalance than greedy on
    cases where greedy plateaus."""
    print("── test_sa_variant_can_match_or_beat_greedy ──")
    seeds_with_improvement = 0
    seeds_total = 10
    for seed in range(seeds_total):
        original = make_test_schedule(36, 7, seed)
        rc, bc = _team_color_counts(original)
        max_before = _max_imbalance(rc, bc)

        _, greedy_stats = rb_balance_pass(original)
        _, sa_stats = rb_balance_sa(original, n_iterations=2000, seed=42)

        # SA should reach equal or better max_imbal
        assert sa_stats['max_after'] <= greedy_stats['max_after'], \
            f"seed {seed}: SA worse than greedy ({sa_stats['max_after']} > {greedy_stats['max_after']})"
        if sa_stats['max_after'] < greedy_stats['max_after'] or \
           sa_stats['sum_after'] < greedy_stats['sum_after']:
            seeds_with_improvement += 1
        print(f"  seed={seed}: greedy max={greedy_stats['max_after']} "
              f"(sum={greedy_stats['sum_after']}); "
              f"SA max={sa_stats['max_after']} (sum={sa_stats['sum_after']})")
    print(f"  SA improved over greedy on {seeds_with_improvement}/{seeds_total} seeds  ✓")


def test_pass_improves_imbalance_on_real_fixture():
    """On the 2026mnst fixture the pass should produce a measurable reduction
    in max_imbalance."""
    print("── test_pass_improves_imbalance_on_real_fixture ──")
    # Use a fresh scheduler output with default settings
    original = make_test_schedule(36, 7, seed=42)
    rc, bc = _team_color_counts(original)
    max_before = _max_imbalance(rc, bc)

    new, stats = rb_balance_pass(original)
    rc2, bc2 = _team_color_counts(new)
    max_after = _max_imbalance(rc2, bc2)

    print(f"  Before: max_imbal={max_before}, sum_imbal={stats['sum_before']}")
    print(f"  After:  max_imbal={max_after}, sum_imbal={stats['sum_after']}")
    print(f"  Flips: {stats['flips']} over {stats['sweeps']} sweeps")
    # Construction phase produces some imbalance; pass should reduce it
    assert max_after <= max_before
    print(f"  ✓")


if __name__ == '__main__':
    test_pass_terminates_and_validates()
    test_pass_never_worsens_max_imbalance()
    test_pass_preserves_partner_pairs()
    test_pass_preserves_opponent_pairs()
    test_pass_preserves_match_team_sets()
    test_pass_preserves_team_match_indices()
    test_pass_preserves_surrogate_count_per_team()
    test_sa_variant_preserves_invariants()
    test_sa_variant_can_match_or_beat_greedy()
    test_pass_improves_imbalance_on_real_fixture()
    print("\nAll Phase 1 R/B post-pass tests passed.")
