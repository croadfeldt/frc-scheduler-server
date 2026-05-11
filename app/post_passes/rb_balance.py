# SPDX-License-Identifier: GPL-3.0-or-later
# FRC Match Scheduler
# Copyright (C) 2025 FRC Match Scheduler Contributors
#
# Implements an independent post-pass for Red/Blue alliance balancing
# inspired by the technique described by the algorithm's published authors in the
# external references at the published algorithm description. Not a port of
# the reference scheduler code; not a wrapper around the external reference binary.

"""Red/Blue balance post-pass.

For each match, decide whether to flip its R/B alliances (Red↔Blue swap of
all 6 teams). Greedy: pick the match whose flip most reduces total
imbalance; flip it; repeat until no flip helps.

Provably commutative with all other criteria:
  - Partner pairs: red-triangle teammates remain red-triangle, blue-triangle
    remain blue-triangle. The relationships are intact; only the alliance
    color label changes.
  - Opponent pairs: cross-alliance pairs are unchanged (red↔blue is
    symmetric).
  - Match separation/cooldown: same matches, same teams, same order.
  - Surrogate flags: stay attached to teams when they swap colors.
  - b2b: the team set per match doesn't change; b2b status doesn't either.

The one cross-effect is per-team station distribution: a team at R1 becomes
B1 after a match flip, which permutes which stations get the count for that
team. We accept this — Phase 2's station post-pass runs after Phase 1 and
rebalances stations across matches. The R/B post-pass operates on red-vs-blue
balance only; station optimization is a separate concern.

The pass terminates in O(N × n_matches) flips at worst (each flip strictly
improves a bounded-integer objective), typically finishes in 1-2 sweeps.
"""

from __future__ import annotations

from app.scheduler import Match


def _team_color_counts(matches: list[Match]) -> tuple[dict[int, int], dict[int, int]]:
    """Return (red_count, blue_count) dicts indexed by team."""
    rc: dict[int, int] = {}
    bc: dict[int, int] = {}
    for m in matches:
        for t in m.red:
            rc[t] = rc.get(t, 0) + 1
            bc.setdefault(t, 0)
        for t in m.blue:
            bc[t] = bc.get(t, 0) + 1
            rc.setdefault(t, 0)
    return rc, bc


def _max_imbalance(rc: dict[int, int], bc: dict[int, int]) -> int:
    return max(abs(rc[t] - bc[t]) for t in rc) if rc else 0


def _imbalance_sum(rc: dict[int, int], bc: dict[int, int]) -> int:
    """Sum of |rc-bc| across all teams. Lower is better."""
    return sum(abs(rc[t] - bc[t]) for t in rc)


def _flip_match(matches: list[Match], idx: int) -> None:
    """Flip match[idx]'s R/B alliances in place. Surrogate flags follow teams."""
    m = matches[idx]
    matches[idx] = Match(
        red=m.blue,
        blue=m.red,
        red_surrogate=m.blue_surrogate,
        blue_surrogate=m.red_surrogate,
    )


def _delta_for_flip(matches: list[Match], idx: int,
                    rc: dict[int, int], bc: dict[int, int]) -> int:
    """How much would imbalance_sum change if we flipped matches[idx]?

    A team at red in this match contributes |rc-bc|; after the flip it's at
    blue, so the new contribution is |rc - bc - 2| (since this team's red
    count drops by 1 and blue count rises by 1, net |rc-1 - (bc+1)| =
    |rc - bc - 2|). Symmetrically for blue→red teams.

    Returns delta = new_imbalance_sum - old_imbalance_sum. Negative = better.
    """
    delta = 0
    m = matches[idx]
    for t in m.red:
        old = abs(rc[t] - bc[t])
        new = abs((rc[t] - 1) - (bc[t] + 1))
        delta += new - old
    for t in m.blue:
        old = abs(rc[t] - bc[t])
        new = abs((rc[t] + 1) - (bc[t] - 1))
        delta += new - old
    return delta


def _apply_flip_to_counts(matches: list[Match], idx: int,
                          rc: dict[int, int], bc: dict[int, int]) -> None:
    """Update rc/bc as if matches[idx] is being flipped (then we'll flip it)."""
    m = matches[idx]
    for t in m.red:
        rc[t] -= 1
        bc[t] += 1
    for t in m.blue:
        rc[t] += 1
        bc[t] -= 1


def rb_balance_pass(matches: list[Match],
                    max_sweeps: int = 50) -> tuple[list[Match], dict]:
    """Apply Red/Blue balance post-pass.

    Greedy: each sweep examines every match and flips the one whose flip
    most reduces imbalance_sum (= sum over teams of |rc - bc|). Repeats
    until no flip strictly helps.

    Whole-match R/B flip is the **only** move used here. It's provably
    commutative with all other criteria (see module docstring): partner
    pairs, opponent pairs, station-within-alliance distribution, cooldown,
    b2b, surrogate counts are all invariant. Finer-grained moves (e.g.
    within-match team swap between R and B) DO change those things and
    are the SA's job, not the post-pass's.

    Convergence is guaranteed: max_sweeps × n_matches steps total, each
    strictly decreasing a bounded-integer objective.

    Args:
        matches: input schedule (not mutated; new list returned)
        max_sweeps: safety cap on outer iterations.

    Returns:
        (new_matches, stats): the optimized schedule and a stats dict.
    """
    work = list(matches)
    rc, bc = _team_color_counts(work)
    max_before = _max_imbalance(rc, bc)
    sum_before = _imbalance_sum(rc, bc)

    n_flips = 0
    sweeps = 0
    while sweeps < max_sweeps:
        sweeps += 1
        best_idx = -1
        best_delta = 0
        for i in range(len(work)):
            d = _delta_for_flip(work, i, rc, bc)
            if d < best_delta:
                best_delta = d
                best_idx = i
        if best_idx < 0:
            break
        _apply_flip_to_counts(work, best_idx, rc, bc)
        _flip_match(work, best_idx)
        n_flips += 1

    max_after = _max_imbalance(rc, bc)
    sum_after = _imbalance_sum(rc, bc)

    return work, {
        'flips':      n_flips,
        'sweeps':     sweeps,
        'max_before': max_before,
        'max_after':  max_after,
        'sum_before': sum_before,
        'sum_after':  sum_after,
    }


def rb_balance_sa(matches: list[Match], n_iterations: int = 5000,
                  seed: int | None = None) -> tuple[list[Match], dict]:
    """Apply Red/Blue balance post-pass using simulated annealing.

    Same operation set as ``rb_balance_pass`` (whole-match R/B flip — provably
    commutative with all other criteria), but uses SA to escape local optima
    that greedy hill-climbing can't break.

    The greedy ``rb_balance_pass`` reaches local optima quickly but can plateau
    well above the global optimum: e.g. when only individual matches' flips
    are zero-delta but a sequence of flips would together reduce imbalance.
    SA accepts uphill moves with cooling probability, allowing the search to
    cross plateaus.

    Args:
        matches: input schedule (not mutated)
        n_iterations: SA budget
        seed: RNG seed for reproducibility

    Returns:
        (new_matches, stats): the optimized schedule and a stats dict.
    """
    import math
    import random as _random
    rng = _random.Random(seed)

    work = list(matches)
    rc, bc = _team_color_counts(work)
    max_before = _max_imbalance(rc, bc)
    sum_before = _imbalance_sum(rc, bc)

    best_sum = sum_before
    best_snapshot = list(work)
    best_rc = dict(rc)
    best_bc = dict(bc)

    n = len(work)
    if n == 0:
        return work, {
            'iterations': 0, 'accepts_pos': 0, 'accepts_neg': 0,
            'rejects': 0, 'max_before': max_before, 'max_after': max_before,
            'sum_before': sum_before, 'sum_after': sum_before,
        }

    cur_sum = sum_before
    T0 = 4.0  # imbalance_sum is small integer-valued; small T appropriate
    accepts_pos = 0
    accepts_neg = 0
    rejects = 0

    for step in range(n_iterations):
        T = T0 * (1.0 - step / n_iterations)
        idx = rng.randrange(n)
        delta = _delta_for_flip(work, idx, rc, bc)

        accept = (delta <= 0) or (T > 0 and rng.random() < math.exp(-delta / T))
        if accept:
            _apply_flip_to_counts(work, idx, rc, bc)
            _flip_match(work, idx)
            cur_sum += delta
            if delta <= 0:
                accepts_pos += 1
            else:
                accepts_neg += 1
            if cur_sum < best_sum:
                best_sum = cur_sum
                best_snapshot = list(work)
                best_rc = dict(rc)
                best_bc = dict(bc)
        else:
            rejects += 1

    max_after = _max_imbalance(best_rc, best_bc)
    return best_snapshot, {
        'iterations':  n_iterations,
        'accepts_pos': accepts_pos,
        'accepts_neg': accepts_neg,
        'rejects':     rejects,
        'max_before':  max_before,
        'max_after':   max_after,
        'sum_before':  sum_before,
        'sum_after':   best_sum,
    }
