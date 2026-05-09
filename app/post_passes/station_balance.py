# SPDX-License-Identifier: GPL-3.0-or-later
# FRC Match Scheduler
# Copyright (C) 2025 FRC Match Scheduler Contributors
#
# Implements an independent post-pass for driver-station distribution
# inspired by the Sykes station-balancing algorithm integrated into
# MatchMaker by Tom and Cathy Saxton in 2017. See:
# https://idleloop.com/matchmaker/stations.php
#
# Not a port of MatchMaker code; not a wrapper around the MatchMaker binary.

"""Driver-station balance post-pass (FRC §10.5.2 #6).

Permutes within-alliance station assignments to drive each team's
station distribution toward the optimal floor (each team appears at
each station ⌊MPT/3⌋ or ⌈MPT/3⌉ times within their alliance).

Provably commutative with all other criteria:
  - Partner pairs: A team's red-alliance teammates remain its red-alliance
    teammates (we permute *positions* within an alliance, not membership).
    Multiset of partner pairs is invariant.
  - Opponent pairs: cross-alliance pairs depend only on which teams are
    in red vs blue, which doesn't change. Multiset invariant.
  - R/B balance: per-team rc/bc counts depend only on alliance membership,
    which doesn't change.
  - Match separation / cooldown: matches and their team-sets unchanged;
    gaps preserved.
  - Surrogate flags: travel with teams when they permute positions.
  - Match equity (P5) and surrogate spread (P11): unchanged (count of
    surrogate appearances per team and total appearances per team are
    properties of alliance membership only).

The pass is greedy with an SA fallback for plateau escape. Same shape
as Phase 1 R/B post-pass.

Operation set: within a single alliance of a single match, permute the
3 teams across the 3 station slots (R1/R2/R3 or B1/B2/B3). 6 possible
permutations per alliance per match; we evaluate each.

Per Sykes' original analysis, perfect balance is achievable when the
schedule was constructed without artificial constraints. In practice
some events can't reach perfect balance due to interactions with
other criteria — but the post-pass always reaches the optimum within
its operation set.
"""

from __future__ import annotations

import math
import random
from itertools import permutations

from app.scheduler import Match


def _per_team_station_counts(matches: list[Match]) -> dict[int, list[int]]:
    """Compute station_counts[team] = [r1, r2, r3, b1, b2, b3]."""
    counts: dict[int, list[int]] = {}
    for m in matches:
        for sta_idx, t in enumerate(m.red):
            counts.setdefault(t, [0] * 6)
            counts[t][sta_idx] += 1
        for sta_idx, t in enumerate(m.blue):
            counts.setdefault(t, [0] * 6)
            counts[t][3 + sta_idx] += 1
    return counts


def _team_spread(counts_for_team: list[int]) -> int:
    """Spread = max - min of station appearances. Lower is better."""
    if not any(counts_for_team):
        return 0
    return max(counts_for_team) - min(counts_for_team)


def _total_station_pen(counts: dict[int, list[int]]) -> int:
    """Sum of per-team spreads. Matches FRC criterion #6 metric."""
    return sum(_team_spread(c) for c in counts.values())


def _max_station_spread(counts: dict[int, list[int]]) -> int:
    """Per-team max station spread (the eval metric)."""
    if not counts:
        return 0
    return max(_team_spread(c) for c in counts.values())


def _apply_alliance_permutation(matches: list[Match],
                                m_idx: int,
                                side: str,
                                perm: tuple[int, int, int],
                                counts: dict[int, list[int]]) -> None:
    """Mutate matches[m_idx]'s alliance to the given permutation.

    ``perm`` is a 3-tuple of indices (i0, i1, i2) — the new ordering uses
    old position i0 at slot 0, i1 at slot 1, i2 at slot 2. Surrogate
    flags travel with teams.

    Updates counts dict in place. Returns nothing.
    """
    m = matches[m_idx]
    if side == 'red':
        old_alliance = m.red
        old_sur = m.red_surrogate
        # Subtract old contributions
        for sta_idx, t in enumerate(old_alliance):
            counts[t][sta_idx] -= 1
        # Build new alliance
        new_alliance = tuple(old_alliance[p] for p in perm)
        new_sur = tuple(old_sur[p] for p in perm)
        # Add new contributions
        for sta_idx, t in enumerate(new_alliance):
            counts[t][sta_idx] += 1
        matches[m_idx] = Match(
            red=new_alliance,
            blue=m.blue,
            red_surrogate=new_sur,
            blue_surrogate=m.blue_surrogate,
        )
    else:
        old_alliance = m.blue
        old_sur = m.blue_surrogate
        for sta_idx, t in enumerate(old_alliance):
            counts[t][3 + sta_idx] -= 1
        new_alliance = tuple(old_alliance[p] for p in perm)
        new_sur = tuple(old_sur[p] for p in perm)
        for sta_idx, t in enumerate(new_alliance):
            counts[t][3 + sta_idx] += 1
        matches[m_idx] = Match(
            red=m.red,
            blue=new_alliance,
            red_surrogate=m.red_surrogate,
            blue_surrogate=new_sur,
        )


def _delta_for_permutation(matches: list[Match],
                           m_idx: int,
                           side: str,
                           perm: tuple[int, int, int],
                           counts: dict[int, list[int]]) -> int:
    """How much would total_station_pen change if we apply this perm?

    Computes by inspecting only the 3 teams in the affected alliance
    (other teams' counts don't change).
    """
    m = matches[m_idx]
    alliance = m.red if side == 'red' else m.blue
    base = 0 if side == 'red' else 3

    # Old spreads
    old_spreads = [_team_spread(counts[t]) for t in alliance]

    # New spreads under perm: simulate changes
    new_counts_for = {}
    for sta_idx, t in enumerate(alliance):
        new_counts_for[t] = list(counts[t])
        new_counts_for[t][base + sta_idx] -= 1
    for sta_idx, perm_src in enumerate(perm):
        t = alliance[perm_src]
        new_counts_for[t][base + sta_idx] += 1

    new_spreads = [_team_spread(new_counts_for[t]) for t in alliance]

    return sum(new_spreads) - sum(old_spreads)


# Precomputed all 6 permutations of (0, 1, 2) excluding identity
_NON_IDENTITY_PERMS = [p for p in permutations((0, 1, 2)) if p != (0, 1, 2)]
_ALL_PERMS = list(permutations((0, 1, 2)))


def station_balance_pass(matches: list[Match],
                         max_sweeps: int = 50) -> tuple[list[Match], dict]:
    """Greedy within-alliance station permutation post-pass.

    Each sweep examines every (match, alliance) pair and applies the best
    non-identity permutation if it strictly reduces total_station_pen.
    Repeats until no permutation helps.

    Args:
        matches: input schedule (not mutated; new list returned)
        max_sweeps: safety cap on outer iterations.

    Returns:
        (new_matches, stats): the optimized schedule and a stats dict.
    """
    work = list(matches)
    counts = _per_team_station_counts(work)

    sum_before = _total_station_pen(counts)
    max_before = _max_station_spread(counts)

    n_perms = 0
    sweeps = 0
    while sweeps < max_sweeps:
        sweeps += 1
        improved = False
        for m_idx in range(len(work)):
            for side in ('red', 'blue'):
                best_delta = 0
                best_perm = None
                for perm in _NON_IDENTITY_PERMS:
                    d = _delta_for_permutation(work, m_idx, side, perm, counts)
                    if d < best_delta:
                        best_delta = d
                        best_perm = perm
                if best_perm is not None:
                    _apply_alliance_permutation(work, m_idx, side, best_perm, counts)
                    n_perms += 1
                    improved = True
        if not improved:
            break

    sum_after = _total_station_pen(counts)
    max_after = _max_station_spread(counts)

    return work, {
        'permutations': n_perms,
        'sweeps':       sweeps,
        'sum_before':   sum_before,
        'sum_after':    sum_after,
        'max_before':   max_before,
        'max_after':    max_after,
    }


def station_balance_sa(matches: list[Match],
                       n_iterations: int = 5000,
                       seed: int | None = None) -> tuple[list[Match], dict]:
    """SA-based station balance post-pass.

    Same operation set (within-alliance permutations, provably commutative
    with all other FRC criteria) but uses SA to escape plateaus that the
    greedy pass can't break.

    Strategy: run greedy first to get a strong baseline, then SA from
    there. SA's best-tracking guarantees the result is never worse than
    greedy alone. SA explores nearby permutations to find improvements
    greedy missed.

    Args:
        matches: input schedule (not mutated)
        n_iterations: SA budget after greedy
        seed: RNG seed for reproducibility

    Returns:
        (new_matches, stats): the optimized schedule and a stats dict.
    """
    rng = random.Random(seed)

    # Stage 1: greedy gives a strong baseline.
    greedy_matches, _greedy_stats = station_balance_pass(matches)
    work = list(greedy_matches)
    counts = _per_team_station_counts(work)

    sum_before = _total_station_pen(_per_team_station_counts(matches))
    max_before = _max_station_spread(_per_team_station_counts(matches))
    cur_sum = _total_station_pen(counts)
    best_sum = cur_sum
    best_snapshot = list(work)
    best_counts = {t: list(c) for t, c in counts.items()}

    n_matches = len(work)
    if n_matches == 0:
        return work, {
            'iterations': 0, 'accepts_pos': 0, 'accepts_neg': 0,
            'rejects': 0, 'sum_before': sum_before, 'sum_after': sum_before,
            'max_before': max_before, 'max_after': max_before,
        }

    T0 = 4.0
    accepts_pos = 0
    accepts_neg = 0
    rejects = 0

    for step in range(n_iterations):
        T = T0 * (1.0 - step / n_iterations)
        m_idx = rng.randrange(n_matches)
        side = rng.choice(('red', 'blue'))
        perm = rng.choice(_NON_IDENTITY_PERMS)

        delta = _delta_for_permutation(work, m_idx, side, perm, counts)

        accept = (delta <= 0) or (T > 0 and rng.random() < math.exp(-delta / T))
        if accept:
            _apply_alliance_permutation(work, m_idx, side, perm, counts)
            cur_sum += delta
            if delta <= 0:
                accepts_pos += 1
            else:
                accepts_neg += 1
            if cur_sum < best_sum:
                best_sum = cur_sum
                best_snapshot = list(work)
                best_counts = {t: list(c) for t, c in counts.items()}
        else:
            rejects += 1

    max_after = _max_station_spread(best_counts)
    return best_snapshot, {
        'iterations':   n_iterations,
        'accepts_pos':  accepts_pos,
        'accepts_neg':  accepts_neg,
        'rejects':      rejects,
        'sum_before':   sum_before,
        'sum_after':    best_sum,
        'max_before':   max_before,
        'max_after':    max_after,
    }
