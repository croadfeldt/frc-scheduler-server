# SPDX-License-Identifier: GPL-3.0-or-later
# FRC Match Scheduler
# Copyright (C) 2025 FRC Match Scheduler Contributors
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.
#
# NOTE: This file was substantially generated with the assistance of Claude,
# an AI assistant by Anthropic, and reviewed/modified by human contributors.
# See LICENSE for full terms.

"""
FRC Qualification Match Scheduler
Pure Python port of the JS algorithm — no I/O, no dependencies beyond stdlib.
Safe to run in a ProcessPoolExecutor worker.
"""

import math
import random
from typing import NamedTuple

# ── Weights ───────────────────────────────────────────────────────────────────
# Defaults aligned with the FIRST official MatchMaker algorithm (Idle Loop /
# Saxton, used by FMS at all official events). Notes on each:
#
#   W_BALANCE   — penalty for red/blue imbalance per team. FIRST: balanced.
#                 Lowered from 50 → 30 since we now also balance per-station
#                 (W_STATION) which subsumes much of the red/blue balance.
#   W_GAP       — bonus for longer gaps between a team's appearances.
#   W_COUNT     — penalty for over-scheduling a team. (Within-iteration tie
#                 breaker; quotas are enforced as a hard constraint.)
#   W_OPPONENT  — penalty per repeat cross-alliance opponent.
#   W_PARTNER   — penalty per repeat same-alliance partner. NOTE: now > W_OPPONENT
#                 to align with FIRST's documented stance ("partner duplication
#                 weighted slightly heavier than opponent — only 2 partners but
#                 3 opponents per round, so a partner repeat is more impactful").
#   W_STATION   — NEW. Penalty for uneven station appearances per team.
#                 FIRST balances all 6 stations (R1/R2/R3/B1/B2/B3) since 2017.
#                 Different stations have different field sightlines.
#   W_SUR_RPT   — penalty for surrogate concentration on the same teams.
#
# Penalties on opponent/partner/station are applied QUADRATICALLY in the
# diversity scorer. This means the second repeat of a pair costs 4× the first,
# the third costs 9×, etc. — which strongly pushes the scheduler to spread
# repeats evenly rather than concentrate them on a few unlucky pairs.
#
# These constants are runtime-overridable via the `weights` parameter on
# generate_matches(); the editor surfaces these as "Advanced criteria" in the
# UI with a "Match FIRST defaults" reset button.
W_BALANCE  = 30
W_GAP      = 10
W_COUNT    = 5
W_OPPONENT = 60
W_PARTNER  = 80
W_STATION  = 30
W_SUR_RPT  = 200

# Default weight bundle exposed for callers (UI + URL params).
DEFAULT_WEIGHTS = {
    "balance":  W_BALANCE,
    "gap":      W_GAP,
    "count":    W_COUNT,
    "opponent": W_OPPONENT,
    "partner":  W_PARTNER,
    "station":  W_STATION,
    "sur_rpt":  W_SUR_RPT,
}

# "FIRST strict" preset: matches the canonical MatchMaker algorithm as
# documented at https://idleloop.com/matchmaker/. The weights here reflect
# our best read of FIRST's relative priorities. Not literally the same
# numbers (FIRST uses simulated annealing, not weighted scoring), but the
# RELATIVE ordering matches what FMS produces:
#   round uniformity (hard) >> match separation (hard) >> pairing uniformity
#   >> minimize surrogates >> red/blue balance >> station balance.
FIRST_STRICT_WEIGHTS = dict(DEFAULT_WEIGHTS)  # currently identical to defaults


class Match(NamedTuple):
    red:            tuple[int, ...]
    blue:           tuple[int, ...]
    red_surrogate:  tuple[bool, ...]
    blue_surrogate: tuple[bool, ...]


class ScheduleResult(NamedTuple):
    matches:          list[Match]
    surrogate_count:  list[int]
    round_boundaries: dict[int, int]
    score:            float


_MASKS_3_OF_6 = [m for m in range(64) if bin(m).count('1') == 3]

_SPLITS = [
    ([i for i in range(6) if (m >> i) & 1],
     [i for i in range(6) if not (m >> i) & 1])
    for m in _MASKS_3_OF_6
]

# All 6 permutations of (0, 1, 2) — used to enumerate within-alliance station
# orderings when picking the best red/blue split. With 6 perms × 6 perms × 20
# splits = 720 candidates per match, which is fast.
_PERM3 = [
    (0, 1, 2), (0, 2, 1), (1, 0, 2),
    (1, 2, 0), (2, 0, 1), (2, 1, 0),
]


def generate_matches(num_teams: int, matches_per_team: int, ideal_gap: int,
                     seed: int | None = None,
                     weights: dict | None = None,
                     team_numbers: list[int] | None = None,
                     n_sa_iterations: int = 0,
                     rb_post_pass: bool = True) -> ScheduleResult:
    """Generate one schedule iteration.

    Args:
        num_teams: Number of teams.
        matches_per_team: How many matches each team plays (their MPT).
        ideal_gap: Soft target for match-to-match separation.
        seed: RNG seed for reproducibility.
        weights: Optional override for the W_* constants. Pass DEFAULT_WEIGHTS
            or FIRST_STRICT_WEIGHTS, or a custom dict with any subset of:
                balance, gap, count, opponent, partner, station, sur_rpt
            Missing keys fall back to module defaults.
        team_numbers: Optional list of real team numbers. If provided, the
            generated Match objects will contain these team numbers directly.
            If omitted, slots are labeled 1..N (preserving the legacy
            "abstract schedule" behavior). Must have length num_teams.
        n_sa_iterations: Number of simulated-annealing optimization passes
            to run after the construction phase. 0 = construction only
            (legacy behavior). Higher = better quality at higher wall-clock
            cost. The SA optimizes the canonical score (see
            ``_score_from_state``) via random 2-swap moves.
        rb_post_pass: When True (default), run the Phase 1 Red/Blue balance
            post-pass after SA optimization. Provably commutative with
            other criteria (see app/post_passes/rb_balance.py).

    Returns:
        ScheduleResult with matches labeled by team_numbers (or 1..N if
        team_numbers omitted) and a final canonical score.
    """
    # ── Validate team_numbers ─────────────────────────────────────────────
    if team_numbers is not None:
        if len(team_numbers) != num_teams:
            raise ValueError(
                f"team_numbers length {len(team_numbers)} != num_teams {num_teams}"
            )
        if len(set(team_numbers)) != num_teams:
            raise ValueError("team_numbers must be unique")
    # construction phase uses slot indices 1..N; if team_numbers provided, we
    # relabel before the SA phase

    ideal_gap = max(1, ideal_gap)
    rng = random.Random(seed)

    # Pull weights — runtime-overridable so the editor's "Advanced criteria"
    # panel can experiment without touching code.
    w = dict(DEFAULT_WEIGHTS)
    if weights: w.update({k: v for k, v in weights.items() if k in DEFAULT_WEIGHTS})
    w_balance, w_gap, w_count = w["balance"], w["gap"], w["count"]
    w_opponent, w_partner, w_station = w["opponent"], w["partner"], w["station"]
    w_sur_rpt = w["sur_rpt"]

    total_matches     = math.ceil(num_teams * matches_per_team / 6)
    matches_per_round = math.ceil(num_teams / 6)
    total_sur_slots   = total_matches * 6 - num_teams * matches_per_team
    phase1_surplus    = matches_per_round * 6 - num_teams
    # Strict surrogate cap — drops the +1 buffer that was here historically.
    # Math: total_sur_slots distributed across N teams → ceil(slots/N) is the
    # minimum-possible max per team. No team should exceed this except when
    # mathematically unavoidable.
    fair_sur_cap      = max(1, math.ceil(total_sur_slots / num_teams)) if num_teams > 0 and total_sur_slots > 0 else 0

    teams = list(range(1, num_teams + 1))
    rng.shuffle(teams)

    # ── Pre-pick surrogate teams (FIRST manual §10.5.2) ─────────────────────
    # The FRC manual specifies: "If a team plays a MATCH as a SURROGATE, it
    # is always their third Qualification MATCH." This requires deciding
    # upfront which teams will have an extra appearance — rather than letting
    # surrogates emerge from end-of-schedule quota math (the older "fill
    # missing slots from at-quota teams" approach, which puts surrogates in
    # the last round and contradicts FIRST's rule).
    #
    # Only used when MPT >= 3 (the rule has no meaningful interpretation when
    # teams play fewer than 3 matches). For MPT < 3 events, fall back to the
    # legacy model — they're tiny demo/scrimmage cases anyway.
    #
    # rng.sample is seeded so the surrogate set is fully reproducible from
    # the same seed.
    USE_FIRST_SURROGATE_MODEL = matches_per_team >= 3 and total_sur_slots > 0
    if USE_FIRST_SURROGATE_MODEL:
        surrogate_team_set = set(rng.sample(teams, total_sur_slots))
    else:
        surrogate_team_set = set()

    # Per-team appearance target. Non-surrogate teams play MPT matches.
    # Surrogate teams play MPT+1 (one extra; their 3rd is the surrogate).
    target_count = [matches_per_team] * (num_teams + 1)
    for t in surrogate_team_set:
        target_count[t] = matches_per_team + 1

    mc  = [0] * (num_teams + 1)
    lp  = [-999] * (num_teams + 1)
    sc  = [0] * (num_teams + 1)
    rc  = [0] * (num_teams + 1)
    bc  = [0] * (num_teams + 1)

    # Station counts per team — 6 stations indexed 0..5 (R1, R2, R3, B1, B2, B3).
    # Tracked separately from rc/bc (red/blue counts) to support FIRST's
    # station-balance criterion: each team should appear roughly equally at
    # each of the 6 station positions, not just balanced red vs blue overall.
    station_counts = [[0] * 6 for _ in range(num_teams + 1)]

    opp = [[0] * (num_teams + 1) for _ in range(num_teams + 1)]
    par = [[0] * (num_teams + 1) for _ in range(num_teams + 1)]

    matches: list[Match] = []

    total_rounds = math.ceil(total_matches / matches_per_round)
    round_boundaries: dict[int, int] = {
        r: (r - 1) * matches_per_round
        for r in range(1, total_rounds + 1)
    }

    def team_score(t: int, now: int) -> float:
        gap = now - lp[t]
        if gap < ideal_gap:
            return -1000 * (ideal_gap - gap)
        return gap * w_gap - mc[t] * w_count

    def surrogate_score(t: int, now: int) -> float:
        return -sc[t] * w_sur_rpt + (now - lp[t]) * 2

    def diversity_score(red: list[int], blue: list[int]) -> float:
        """Score the diversity (anti-repeat) cost of pairing these 6 teams.
        Quadratic in repeat count: a 2nd encounter costs 4× the 1st, a 3rd
        costs 9×, etc. This pushes the scheduler to spread repeats evenly
        across all pairs rather than concentrate them on a few unlucky ones."""
        s = 0.0
        for r in red:
            for b in blue:
                # Cost of the NEW (post-commit) repeat count, minus the cost
                # of the current state. opp[r][b] going from k to k+1 adds
                # ((k+1)² - k²) × W = (2k+1) × W to the penalty.
                s -= (2 * opp[r][b] + 1) * w_opponent
        for i in range(len(red)):
            for j in range(i + 1, len(red)):
                s -= (2 * par[red[i]][red[j]] + 1) * w_partner
        for i in range(len(blue)):
            for j in range(i + 1, len(blue)):
                s -= (2 * par[blue[i]][blue[j]] + 1) * w_partner
        return s

    def precompute_station_costs(six: list[int]) -> list[list[float]]:
        """For each team in `six` and each of the 6 stations, return the
        MARGINAL increase in (max - min) station-count spread that would
        result from placing that team at that station.

        Computed ONCE per assign_alliances call, then reused across all 20
        splits × 12 within-alliance perms. Replaces the old approach of
        re-running station_imbalance_penalty inside the inner loop, which
        did 36 list copies + 36 max/min calls per evaluation.

        Result indexing: cost[team_idx_in_six][station] where team_idx is
        the position in `six` (0..5) and station is 0..5 (R1, R2, R3, B1, B2, B3).
        """
        cost = [[0.0] * 6 for _ in range(6)]
        for ti, t in enumerate(six):
            sc = station_counts[t]
            cur_max = sc[0]; cur_min = sc[0]
            for v in sc[1:]:
                if v > cur_max: cur_max = v
                if v < cur_min: cur_min = v
            cur_imb = cur_max - cur_min
            for s in range(6):
                new_at_s = sc[s] + 1
                # New max: either old max or the incremented station
                new_max = cur_max if new_at_s <= cur_max else new_at_s
                # New min: only changes if we incremented THE unique min station
                if sc[s] == cur_min:
                    # Find the second-lowest by scanning the other 5 stations
                    rest_min = sc[(s + 1) % 6] if s != 0 else sc[1]
                    for k in range(6):
                        if k != s and sc[k] < rest_min:
                            rest_min = sc[k]
                    new_min = rest_min if rest_min < new_at_s else new_at_s
                else:
                    new_min = cur_min
                cost[ti][s] = (new_max - new_min) - cur_imb
        return cost

    def best_alliance_perm(team_indices: tuple, station_offset: int,
                          sta_cost: list[list[float]]) -> tuple[float, tuple[int, int, int]]:
        """For the 3 teams referenced by `team_indices` (indices into `six`),
        find the within-alliance ordering that minimizes total station-imbalance
        cost. Stations are `station_offset` + (0, 1, 2) — i.e., 0/1/2 for red
        and 3/4/5 for blue. Returns (total_cost, best_perm).

        Red and blue alliances optimize independently because each team's
        imbalance contribution depends only on which station THEY land at;
        the other alliance's choices don't affect it. So we can solve red and
        blue separately, dropping from 36 combined perms to 6+6=12.
        """
        i0, i1, i2 = team_indices
        s0 = station_offset
        s1 = station_offset + 1
        s2 = station_offset + 2
        # Inline all 6 perms with direct lookups — fastest path
        c0 = sta_cost[i0][s0] + sta_cost[i1][s1] + sta_cost[i2][s2]
        c1 = sta_cost[i0][s0] + sta_cost[i2][s1] + sta_cost[i1][s2]
        c2 = sta_cost[i1][s0] + sta_cost[i0][s1] + sta_cost[i2][s2]
        c3 = sta_cost[i1][s0] + sta_cost[i2][s1] + sta_cost[i0][s2]
        c4 = sta_cost[i2][s0] + sta_cost[i0][s1] + sta_cost[i1][s2]
        c5 = sta_cost[i2][s0] + sta_cost[i1][s1] + sta_cost[i0][s2]
        best = c0; perm = (i0, i1, i2)
        if c1 < best: best = c1; perm = (i0, i2, i1)
        if c2 < best: best = c2; perm = (i1, i0, i2)
        if c3 < best: best = c3; perm = (i1, i2, i0)
        if c4 < best: best = c4; perm = (i2, i0, i1)
        if c5 < best: best = c5; perm = (i2, i1, i0)
        return best, perm

    def assign_alliances(six: list[int]) -> tuple[list[int], list[int]] | None:
        """Pick the best 3-red / 3-blue split AND best within-alliance ordering
        for these 6 teams.

        Performance: 20 splits × 12 perms (6 red + 6 blue, decoupled) with
        precomputed station-cost matrix. Previously enumerated all 36 red×blue
        combinations per split with per-call list copies and max/min — that
        was ~30× slower for no benefit, since the two alliances' imbalance
        contributions are independent.
        """
        if len(six) != 6 or len(set(six)) != 6:
            return None
        sta_cost = precompute_station_costs(six)
        best_score = -float('inf')
        best_r, best_b = None, None
        for ri, bi in _SPLITS:
            r = [six[i] for i in ri]
            b = [six[i] for i in bi]
            bal = -w_balance * (
                sum(abs((rc[t] + 1) - bc[t]) for t in r) +
                sum(abs(rc[t] - (bc[t] + 1)) for t in b)
            )
            div = diversity_score(r, b)
            # Solve red and blue station orderings independently — each
            # alliance's contribution is independent of the other's choice.
            red_cost, red_perm = best_alliance_perm((ri[0], ri[1], ri[2]), 0, sta_cost)
            blue_cost, blue_perm = best_alliance_perm((bi[0], bi[1], bi[2]), 3, sta_cost)
            sta = -w_station * (red_cost + blue_cost)
            total = bal + div + sta
            if total > best_score:
                best_score = total
                best_r = [six[red_perm[0]], six[red_perm[1]], six[red_perm[2]]]
                best_b = [six[blue_perm[0]], six[blue_perm[1]], six[blue_perm[2]]]
        return (best_r, best_b) if best_r is not None else None

    def assign_alliances_r1(six: list[int]) -> tuple[list[int], list[int]] | None:
        """Round-1-aware variant: also penalizes uneven distribution of
        second-time players across the two alliances in the round-1 boundary
        match. Used only at the round-1/round-2 transition.

        Same performance optimization as assign_alliances — precomputed
        station-cost matrix + decoupled red/blue ordering.
        """
        if len(six) != 6 or len(set(six)) != 6:
            return None
        sta_cost = precompute_station_costs(six)
        best_score = -float('inf')
        best_r, best_b = None, None
        for ri, bi in _SPLITS:
            r = [six[i] for i in ri]
            b = [six[i] for i in bi]
            r_second = sum(1 for t in r if mc[t] >= 1)
            b_second = sum(1 for t in b if mc[t] >= 1)
            sec_penalty = -500 * abs(r_second - b_second)
            bal = -w_balance * (
                sum(abs((rc[t] + 1) - bc[t]) for t in r) +
                sum(abs(rc[t] - (bc[t] + 1)) for t in b)
            )
            div = diversity_score(r, b)
            red_cost, red_perm = best_alliance_perm((ri[0], ri[1], ri[2]), 0, sta_cost)
            blue_cost, blue_perm = best_alliance_perm((bi[0], bi[1], bi[2]), 3, sta_cost)
            sta = -w_station * (red_cost + blue_cost)
            total = sec_penalty + bal + div + sta
            if total > best_score:
                best_score = total
                best_r = [six[red_perm[0]], six[red_perm[1]], six[red_perm[2]]]
                best_b = [six[blue_perm[0]], six[blue_perm[1]], six[blue_perm[2]]]
        return (best_r, best_b) if best_r is not None else None

    def commit_match(red: list[int], blue: list[int], now: int) -> None:
        for t in red + blue:
            # Surrogate count tracking. Two models, picked at function entry:
            #
            # FIRST-aligned (USE_FIRST_SURROGATE_MODEL): increment only when
            #   this match is the team's 3rd appearance AND the team is in
            #   the pre-picked surrogate set. mc[t] is the appearance count
            #   BEFORE this commit, so trigger on mc[t] + 1 == 3 (i.e. this
            #   commit makes mc[t] == 3).
            #
            # Legacy: increment whenever the team has already met their MPT
            #   quota (an "extra" appearance). Used for MPT < 3 events.
            if USE_FIRST_SURROGATE_MODEL:
                if t in surrogate_team_set and mc[t] + 1 == 3:
                    sc[t] += 1
            else:
                if mc[t] >= matches_per_team:
                    sc[t] += 1
            mc[t] += 1
            lp[t] = now
        for i, t in enumerate(red):
            rc[t] += 1
            station_counts[t][i] += 1   # stations 0,1,2 = R1, R2, R3
        for i, t in enumerate(blue):
            bc[t] += 1
            station_counts[t][3 + i] += 1   # stations 3,4,5 = B1, B2, B3
        for r in red:
            for b in blue:
                opp[r][b] += 1; opp[b][r] += 1
        for i in range(len(red)):
            for j in range(i + 1, len(red)):
                par[red[i]][red[j]] += 1; par[red[j]][red[i]] += 1
        for i in range(len(blue)):
            for j in range(i + 1, len(blue)):
                par[blue[i]][blue[j]] += 1; par[blue[j]][blue[i]] += 1

    def best_of_attempts(
        first_pool: list[int], first_slots: int,
        second_pool: list[int], extra_slots: int,
        is_last: bool, now: int, n_attempts: int = 60
    ) -> tuple[list[int], list[int]]:
        cands = []
        for _ in range(n_attempts):
            # Use the seeded `rng` (not global `random`) so the same seed
            # always produces the same schedule. Previously this used
            # global random.sample, which made same-seed reruns within a
            # single process produce different results — bug fixed here.
            fp = rng.sample(first_pool, min(first_slots, len(first_pool)))
            sp = rng.sample(second_pool, min(extra_slots, len(second_pool))) if extra_slots else []
            six = fp + sp
            if len(six) == 6 and len(set(six)) == 6:
                res = assign_alliances_r1(six) if is_last else assign_alliances(six)
                if res:
                    r, b = res
                    score = diversity_score(r, b) + sum(team_score(t, now) for t in six) * 0.5
                    cands.append((score, r, b))
        if cands:
            cands.sort(key=lambda x: -x[0])
            return cands[0][1], cands[0][2]
        six = first_pool[:first_slots] + second_pool[:extra_slots]
        res = assign_alliances_r1(six) if is_last else assign_alliances(six)
        if res:
            return res
        return six[:3], six[3:6]

    # ── Phase 1: Round 1 ──────────────────────────────────────────────────────
    for m in range(matches_per_round):
        now      = len(matches)
        is_last  = (m == matches_per_round - 1)
        extra    = phase1_surplus if is_last else 0
        first_s  = 6 - extra

        first_timers = sorted(
            [t for t in teams if mc[t] == 0],
            key=lambda t: (-team_score(t, now), rng.random())
        )
        second_timers = sorted(
            [t for t in teams if mc[t] == 1],
            key=lambda t: -team_score(t, now)
        ) if extra > 0 else []

        fp = first_timers[:max(first_s + 6, 12)]
        sp = second_timers[:extra + 2]

        red, blue = best_of_attempts(fp, first_s, sp, extra, is_last, now)
        matches.append(Match(
            red=tuple(red), blue=tuple(blue),
            red_surrogate=tuple(False for _ in red),
            blue_surrogate=tuple(False for _ in blue),
        ))
        commit_match(red, blue, now)

    # ── Phase 2: Open scheduling ──────────────────────────────────────────────
    for i in range(total_matches - matches_per_round):
        now = len(matches)

        if USE_FIRST_SURROGATE_MODEL:
            # FIRST-aligned: per-team target_count drives eligibility. Surrogate
            # teams have target MPT+1 so they remain in the pool until their
            # extra appearance is scheduled. Their 3rd appearance (mc[t] == 2
            # → 3 after this commit) is automatically marked as the surrogate
            # match. No special end-of-schedule "draft surrogate teams from
            # at-quota pool" handling — surrogate placement is uniform with
            # everyone else's, just with a different target count.
            under_quota = sorted(
                [t for t in teams if mc[t] < target_count[t]],
                key=lambda t: (-team_score(t, now), rng.random())
            )
            reg_pool = under_quota[:max(12, 6)]
            red, blue = best_of_attempts(reg_pool, 6, [], 0, False, now)

            # Surrogate flag: this match is t's surrogate iff t is pre-picked
            # AND this is t's 3rd appearance (mc[t] before commit is 2).
            red_sur = tuple(
                (t in surrogate_team_set and mc[t] + 1 == 3)
                for t in red
            )
            blue_sur = tuple(
                (t in surrogate_team_set and mc[t] + 1 == 3)
                for t in blue
            )
        else:
            # Legacy: surrogates emerge organically when under_quota dries up
            # near end of schedule. Used for MPT < 3 where FIRST's "3rd match"
            # rule has no meaningful interpretation.
            under_quota = sorted(
                [t for t in teams if mc[t] < matches_per_team],
                key=lambda t: (-team_score(t, now), rng.random())
            )
            at_quota = sorted(
                [t for t in teams if mc[t] == matches_per_team and sc[t] < fair_sur_cap],
                key=lambda t: -surrogate_score(t, now)
            )

            sur_needed = max(0, 6 - len(under_quota))
            reg_slots  = 6 - sur_needed

            reg_pool = under_quota[:max(reg_slots + 6, 12)]
            sur_pool = at_quota[:sur_needed + 2]

            red, blue = best_of_attempts(reg_pool, reg_slots, sur_pool, sur_needed, False, now)

            red_sur  = tuple(mc[t] >= matches_per_team for t in red)
            blue_sur = tuple(mc[t] >= matches_per_team for t in blue)

        matches.append(Match(red=tuple(red), blue=tuple(blue),
                             red_surrogate=red_sur, blue_surrogate=blue_sur))
        commit_match(red, blue, now)

    # ── Post-generation sweeps ────────────────────────────────────────────────
    #
    # Designed for the legacy model where surrogates emerge from end-of-
    # schedule quota math. They fix three problems with that placement:
    # surrogate in last match (R1), surrogate as first appearance (R2),
    # surrogate as last appearance (R3).
    #
    # SKIPPED when USE_FIRST_SURROGATE_MODEL is active — pre-picked
    # surrogates are placed at the team's 3rd appearance per FRC manual
    # §10.5.2. That placement is correct by construction; running the
    # legacy sweeps would only move flags away from where the manual says
    # they belong (e.g. R1 would move a flag if a team's 3rd match
    # happens to fall in the last calendar match).

    def build_appearance_map():
        first: dict[int, int] = {}
        last_a: dict[int, int] = {}
        for idx, m in enumerate(matches):
            for t in list(m.red) + list(m.blue):
                if t not in first:
                    first[t] = idx
                last_a[t] = idx
        return first, last_a

    # Rule 1+2: move last-match surrogates earlier
    if matches and not USE_FIRST_SURROGATE_MODEL:
        last_idx = len(matches) - 1
        last = matches[last_idx]
        last_red  = list(last.red);  last_rs = list(last.red_surrogate)
        last_blue = list(last.blue); last_bs = list(last.blue_surrogate)

        sur_slots = []
        for i, t in enumerate(last_red):
            if last_rs[i]: sur_slots.append(('red', i, t))
        for i, t in enumerate(last_blue):
            if last_bs[i]: sur_slots.append(('blue', i, t))

        for alliance, pos, sur_team in sur_slots:
            first_app, _ = build_appearance_map()
            swap_a, swap_p, swap_t = None, -1, -1
            for i, t in enumerate(last_red):
                if not last_rs[i] and t != sur_team:
                    swap_a, swap_p, swap_t = 'red', i, t; break
            if swap_t == -1:
                for i, t in enumerate(last_blue):
                    if not last_bs[i] and t != sur_team:
                        swap_a, swap_p, swap_t = 'blue', i, t; break
            if swap_t == -1:
                continue

            early_idx, early_a, early_p = -1, None, -1
            for m_idx in range(last_idx):
                m = matches[m_idx]
                all_t = list(m.red) + list(m.blue)
                if swap_t in all_t:
                    continue
                if m_idx <= first_app.get(sur_team, -1):
                    continue
                if sur_team in m.red:
                    early_idx, early_a, early_p = m_idx, 'red', list(m.red).index(sur_team); break
                if sur_team in m.blue:
                    early_idx, early_a, early_p = m_idx, 'blue', list(m.blue).index(sur_team); break
            if early_idx == -1:
                continue

            em = matches[early_idx]
            er = list(em.red);  ers = list(em.red_surrogate)
            eb = list(em.blue); ebs = list(em.blue_surrogate)

            if early_a == 'red':   er[early_p]  = swap_t; ers[early_p]  = False
            else:                  eb[early_p]   = swap_t; ebs[early_p]  = False

            if alliance == 'red':  last_red[pos]  = swap_t; last_rs[pos]  = False
            else:                  last_blue[pos] = swap_t; last_bs[pos]  = False

            if swap_a == 'red':    last_red[swap_p]  = sur_team; last_rs[swap_p]  = False
            else:                  last_blue[swap_p] = sur_team; last_bs[swap_p]  = False

            if early_a == 'red':   ers[early_p]  = True
            else:                  ebs[early_p]  = True

            matches[early_idx] = Match(
                red=tuple(er), blue=tuple(eb),
                red_surrogate=tuple(ers), blue_surrogate=tuple(ebs)
            )
            matches[last_idx] = Match(
                red=tuple(last_red), blue=tuple(last_blue),
                red_surrogate=tuple(last_rs), blue_surrogate=tuple(last_bs)
            )
            last = matches[last_idx]
            last_red  = list(last.red);  last_rs = list(last.red_surrogate)
            last_blue = list(last.blue); last_bs = list(last.blue_surrogate)

    # Rule 3: no surrogate as last appearance — legacy only
    for _pass in (range(3) if not USE_FIRST_SURROGATE_MODEL else range(0)):
        first_app, last_app = build_appearance_map()
        changed = False
        all_teams = list({t for m in matches for t in list(m.red) + list(m.blue)})
        for team in all_teams:
            last_m_idx = last_app.get(team)
            if last_m_idx is None:
                continue
            lm = matches[last_m_idx]
            r_pos = list(lm.red).index(team)  if team in lm.red  else -1
            b_pos = list(lm.blue).index(team) if team in lm.blue else -1
            is_sur = (r_pos != -1 and lm.red_surrogate[r_pos]) or \
                     (b_pos != -1 and lm.blue_surrogate[b_pos])
            if not is_sur:
                continue
            for m_idx in range(last_m_idx - 1, first_app.get(team, -1), -1):
                em = matches[m_idx]
                er_idx = list(em.red).index(team)  if team in em.red  else -1
                eb_idx = list(em.blue).index(team) if team in em.blue else -1
                if er_idx != -1 and not em.red_surrogate[er_idx]:
                    nrs = list(em.red_surrogate); nrs[er_idx] = True
                    matches[m_idx] = Match(em.red, em.blue, tuple(nrs), em.blue_surrogate)
                    if r_pos != -1:
                        nlrs = list(lm.red_surrogate); nlrs[r_pos] = False
                        matches[last_m_idx] = Match(lm.red, lm.blue, tuple(nlrs), lm.blue_surrogate)
                    else:
                        nlbs = list(lm.blue_surrogate); nlbs[b_pos] = False
                        matches[last_m_idx] = Match(lm.red, lm.blue, lm.red_surrogate, tuple(nlbs))
                    changed = True; break
                if eb_idx != -1 and not em.blue_surrogate[eb_idx]:
                    nbs = list(em.blue_surrogate); nbs[eb_idx] = True
                    matches[m_idx] = Match(em.red, em.blue, em.red_surrogate, tuple(nbs))
                    if r_pos != -1:
                        nlrs = list(lm.red_surrogate); nlrs[r_pos] = False
                        matches[last_m_idx] = Match(lm.red, lm.blue, tuple(nlrs), lm.blue_surrogate)
                    else:
                        nlbs = list(lm.blue_surrogate); nlbs[b_pos] = False
                        matches[last_m_idx] = Match(lm.red, lm.blue, lm.red_surrogate, tuple(nlbs))
                    changed = True; break
        if not changed:
            break

    # ── Post-generation sweeps ────────────────────────────────────────────────
    #
    # These sweeps were designed for the legacy model where surrogates emerge
    # from end-of-schedule quota math. They fix three known problems with that
    # placement: surrogate in last match (R1), surrogate as first appearance
    # (R2), surrogate as last appearance (R3).
    #
    # In the FIRST-aligned model (USE_FIRST_SURROGATE_MODEL), surrogates are
    # placed at the team's 3rd appearance per FRC manual §10.5.2. That
    # placement is correct by construction, so these sweeps would only HARM
    # correct placement (e.g. R1 would move a flag from a team's 3rd match
    # if it happens to be in the last calendar match overall, contradicting
    # the manual). The inline sweep code below runs only in legacy mode.

    # ── Optional team relabel ──────────────────────────────────────────────
    # If real team_numbers were provided, swap them in. Construction used
    # slot indices 1..N; this is a pure relabeling that preserves all
    # structural properties. Done here (before SA) so the SA can operate on
    # real teams from the start, matching what the canonical score expects.
    if team_numbers is not None:
        # Map slot index 1..N to team_numbers[0..N-1]
        slot_to_team = {i + 1: team_numbers[i] for i in range(num_teams)}
        relabeled: list[Match] = []
        for m in matches:
            relabeled.append(Match(
                red=tuple(slot_to_team[s] for s in m.red),
                blue=tuple(slot_to_team[s] for s in m.blue),
                red_surrogate=m.red_surrogate,
                blue_surrogate=m.blue_surrogate,
            ))
        matches = relabeled
        # `sc` (surrogate count) is indexed by slot index 1..N; rebuild it for
        # the real team numbers so the returned ScheduleResult is consistent.
        new_sc = [0] * (num_teams + 1)
        # sc[slot] -> sc[real team]: since slot_to_team[slot] = team_numbers[slot-1],
        # we just reorder sc by team_numbers. But sc has length num_teams+1 and
        # is indexed by slot index 1..N. The new_sc dict-as-list mapping isn't
        # well-defined when team_numbers may be arbitrary integers (e.g. 1234).
        # For backward compat, return the original slot-indexed sc; consumers
        # of surrogate_count read it as "ith team's surrogate count."
        # We keep `sc` as-is (slot-indexed) since surrogate_count is documented
        # as such. Real-team consumers should derive surrogate count from the
        # red_surrogate / blue_surrogate flags on Match objects.

    # ── SA optimization phase ──────────────────────────────────────────────
    # The construction phase produced a feasible schedule. Now optimize it
    # globally via simulated annealing on the canonical score. Each move is
    # a 2-swap of teams between two match positions; the SA accept/reject
    # is driven by full canonical-score deltas.
    #
    # Skip when n_sa_iterations == 0 (legacy behavior).
    if n_sa_iterations > 0 and len(matches) > 0:
        matches = _sa_optimize(matches, n_sa_iterations, rng)

    # ── Phase 1: Red/Blue balance post-pass ─────────────────────────────────
    # After the SA settles, run a separable pass that flips whole-match R/B
    # alliances to optimize per-team color balance. Provably preserves
    # partner pairs, opponent pairs, station-within-alliance distribution,
    # cooldown, b2b, and surrogate counts (see app/post_passes/rb_balance.py
    # for the commutativity proof).
    #
    # Uses SA over flip moves (rather than greedy) because the greedy pass
    # plateaus at non-optimal local minima ~95% of the time on real fixtures.
    # SA at low temperature accepts uphill moves to escape plateaus.
    if rb_post_pass and len(matches) > 0:
        from app.post_passes.rb_balance import rb_balance_sa
        # 5000 iterations is plenty — each iteration is one whole-match flip
        # check (sub-millisecond per iteration). Total cost <100ms typical.
        matches, _rb_stats = rb_balance_sa(matches, n_iterations=5000, seed=seed)

    return ScheduleResult(
        matches=matches,
        surrogate_count=sc,
        round_boundaries=round_boundaries,
        score=score_schedule(matches, num_teams),
    )


def score_schedule(matches: list[Match], num_teams: int) -> float:
    """Score a complete schedule — used to pick the best of N iterations.

    This is the canonical score formula for the project. ``assign_teams``'s
    inner SA loop tracks the same components incrementally and computes
    deltas matching this formula exactly.

    Penalties (negative score):
      - back-to-back appearances: 1000 per occurrence (effectively hard)
      - max red/blue imbalance per team: 500 per imbalance unit
      - surrogate count: 200 per surrogate (constant per abstract schedule)
      - opponent repeats: sum of count² × W_OPPONENT — quadratic, so a 2nd
        repeat for the same pair is 4× as costly as the 1st
      - partner repeats: sum of count² × W_PARTNER — same shape, weighted
        higher (FIRST: partner duplication is more costly than opponent
        because there are only 2 partners but 3 opponents per match)
      - station imbalance: sum across teams of (max_station - min_station)
        × W_STATION — pushes each team to appear roughly equally at all 6
        positions (R1, R2, R3, B1, B2, B3)
    """
    if not matches:
        return -float('inf')

    state = _build_state_from_matches(matches, num_teams)
    return _score_from_state(state)


def _build_state_from_matches(matches: list[Match], num_teams: int,
                              ideal_gap: int = 3) -> dict:
    """Build the canonical score state from a Match list.

    Used by ``score_schedule`` and as a verification helper in tests.
    Mirrors the live state maintained inside ``assign_teams``'s SA loop.

    Team numbers are discovered from the matches themselves rather than
    assumed to be 1..num_teams, so this works whether the input uses
    slot indices (Stage 1) or real team numbers (Stage 2 results).
    The ``num_teams`` argument is retained for callsite compatibility
    but the count is also derived from the discovered team set.

    Args:
        matches: schedule to score
        num_teams: nominal team count (consistency-checked but the actual
            team set is discovered from matches)
        ideal_gap: minimum desired gap between a team's appearances; gaps
            below this contribute to the cooldown_deficit term.
    """
    # Discover team numbers from the matches
    team_set: set[int] = set()
    for m in matches:
        team_set.update(m.red)
        team_set.update(m.blue)

    b2b = 0
    surrogates = 0
    rc = {t: 0 for t in team_set}
    bc = {t: 0 for t in team_set}
    station_counts = {t: [0] * 6 for t in team_set}
    opp: dict[tuple[int, int], int] = {}
    par: dict[tuple[int, int], int] = {}
    team_matches: dict[int, list[int]] = {t: [] for t in team_set}

    def pair(a: int, b: int) -> tuple[int, int]:
        return (a, b) if a < b else (b, a)

    for i, m in enumerate(matches):
        if i > 0:
            prev = set(matches[i - 1].red + matches[i - 1].blue)
            if any(t in prev for t in m.red + m.blue):
                b2b += 1
        surrogates += sum(m.red_surrogate) + sum(m.blue_surrogate)
        for sta_idx, t in enumerate(m.red):
            rc[t] += 1
            station_counts[t][sta_idx] += 1
            team_matches[t].append(i)
        for sta_idx, t in enumerate(m.blue):
            bc[t] += 1
            station_counts[t][3 + sta_idx] += 1
            team_matches[t].append(i)
        for r in m.red:
            for b in m.blue:
                p = pair(r, b)
                opp[p] = opp.get(p, 0) + 1
        rl = list(m.red); bl = list(m.blue)
        for a in range(len(rl)):
            for b in range(a + 1, len(rl)):
                p = pair(rl[a], rl[b])
                par[p] = par.get(p, 0) + 1
        for a in range(len(bl)):
            for b in range(a + 1, len(bl)):
                p = pair(bl[a], bl[b])
                par[p] = par.get(p, 0) + 1

    # Cooldown deficit: sum of (ideal_gap - actual_gap) for all team appearances
    # where the gap is less than ideal_gap.
    cooldown_deficit = 0
    for t, ms in team_matches.items():
        # ms is in match-order since we appended during iteration
        for j in range(1, len(ms)):
            gap = ms[j] - ms[j - 1]
            if gap < ideal_gap:
                cooldown_deficit += ideal_gap - gap

    return {
        'b2b':              b2b,
        'surrogates':       surrogates,
        'rc':               rc,
        'bc':               bc,
        'station_counts':   station_counts,
        'opp':              opp,
        'par':              par,
        'num_teams':        num_teams,
        'cooldown_deficit': cooldown_deficit,
        'ideal_gap':        ideal_gap,
    }


def _score_from_state(state: dict) -> float:
    """Canonical score formula — single source of truth.

    Both ``score_schedule`` and ``assign_teams``'s SA loop use this. The
    incremental delta computation in ``assign_teams`` is derived from
    this exact formula; deltas match ``_score_from_state(state_after) -
    _score_from_state(state_before)`` exactly for any swap (verified
    by the property tests in ``tests/test_scheduler_score_consistency.py``).
    """
    rc = state['rc']
    bc = state['bc']
    station_counts = state['station_counts']
    if not rc:
        return -float('inf')

    max_imbalance = max(abs(rc[t] - bc[t]) for t in rc)

    # Quadratic penalty for repeats — encourages spreading repeats across
    # many pairs rather than concentrating them on a few unlucky pairs.
    opp_quad = sum(v * v for v in state['opp'].values())
    par_quad = sum(v * v for v in state['par'].values())

    # Station imbalance — sum across teams of (max - min) station counts.
    station_pen = 0
    for t in rc:
        sc_t = station_counts[t]
        if any(sc_t):
            station_pen += max(sc_t) - min(sc_t)

    # Cooldown deficit (P4 in PRIORITIES.md) — sum of (ideal_gap - actual_gap)
    # for all gap < ideal_gap across all team appearances. Reads from state
    # if present (Match-based SA), else computes from team_matches.
    # Hardcoded to ideal_gap=3 since that's what production uses; if events
    # need to vary this, plumb through.
    cooldown_deficit = state.get('cooldown_deficit', 0)

    return -(state['b2b']        * 1000
             + max_imbalance     *  500
             + state['surrogates'] * 200
             + opp_quad          * W_OPPONENT
             + par_quad          * W_PARTNER
             + station_pen       * W_STATION
             + cooldown_deficit  * 1000)


def run_iterations_worker(args: tuple) -> dict:
    # Unpack with backwards-compatible weights tuple (old callers send 6-tuple)
    if len(args) == 7:
        num_teams, matches_per_team, ideal_gap, n_iterations, worker_id, seed, weights = args
    else:
        num_teams, matches_per_team, ideal_gap, n_iterations, worker_id, seed = args
        weights = None
    best: ScheduleResult | None = None

    for i in range(n_iterations):
        iter_seed = (seed ^ (worker_id * 1000 + i)) if seed is not None else None
        result = generate_matches(num_teams, matches_per_team, ideal_gap, iter_seed, weights)
        if best is None or result.score > best.score:
            best = result

    if best is None:
        return {'worker_id': worker_id, 'score': -1e18, 'matches': [], 'surrogate_count': [], 'round_boundaries': {}}

    return {
        'worker_id':        worker_id,
        'score':            best.score,
        'surrogate_count':  best.surrogate_count,
        'round_boundaries': best.round_boundaries,
        'matches': [
            {
                'red':            list(m.red),
                'blue':           list(m.blue),
                'red_surrogate':  list(m.red_surrogate),
                'blue_surrogate': list(m.blue_surrogate),
            }
            for m in best.matches
        ],
    }


# ── Match-based SA optimization (Phase 0 reframed) ─────────────────────────
# These helpers operate on Match objects directly, so they're usable by
# generate_matches's optimization phase. The SA move generator picks two
# matches, picks one team in each, and swaps them. This changes which slots
# co-appear in matches — meaning it changes the structural quantities the
# canonical score depends on (partner pairs, opponent pairs, station
# distributions, R/B counts).
#
# Contrast with the slot-based SA in assign_teams: that one only relabels
# which team wears which slot's identity, which is provably a no-op for the
# canonical score (verified empirically — see QUALITY_IMPROVEMENT_PLAN.md
# Finding 2). The Match-based SA below is the real optimization.

def _build_match_state(matches: list[Match], ideal_gap: int = 3) -> dict:
    """Build canonical-score state from a Match list, with per-match indexing
    needed for incremental delta tracking.

    Same fields as ``_build_state_from_matches`` plus ``team_matches``
    (which match indices each team appears in) and ``tbm`` (team set per
    match, for b2b tracking).
    """
    team_set: set[int] = set()
    for m in matches:
        team_set.update(m.red)
        team_set.update(m.blue)

    n = len(matches)
    b2b = 0
    surrogates = 0
    rc = {t: 0 for t in team_set}
    bc = {t: 0 for t in team_set}
    station_counts = {t: [0] * 6 for t in team_set}
    opp: dict[tuple[int, int], int] = {}
    par: dict[tuple[int, int], int] = {}
    team_matches: dict[int, list[int]] = {t: [] for t in team_set}
    tbm: list[set[int]] = []

    def pair(a: int, b: int) -> tuple[int, int]:
        return (a, b) if a < b else (b, a)

    for i, m in enumerate(matches):
        cur = set(m.red + m.blue)
        tbm.append(cur)
        if i > 0 and cur & tbm[i - 1]:
            b2b += 1
        surrogates += sum(m.red_surrogate) + sum(m.blue_surrogate)
        for sta_idx, t in enumerate(m.red):
            rc[t] += 1
            station_counts[t][sta_idx] += 1
            team_matches[t].append(i)
        for sta_idx, t in enumerate(m.blue):
            bc[t] += 1
            station_counts[t][3 + sta_idx] += 1
            team_matches[t].append(i)
        for r in m.red:
            for b in m.blue:
                p = pair(r, b)
                opp[p] = opp.get(p, 0) + 1
        rl = list(m.red); bl = list(m.blue)
        for a in range(len(rl)):
            for b in range(a + 1, len(rl)):
                p = pair(rl[a], rl[b])
                par[p] = par.get(p, 0) + 1
        for a in range(len(bl)):
            for b in range(a + 1, len(bl)):
                p = pair(bl[a], bl[b])
                par[p] = par.get(p, 0) + 1

    # Cooldown deficit: sum of (ideal_gap - actual_gap) for gap < ideal_gap.
    # team_matches is sorted by match index since we append in order.
    cooldown_deficit = 0
    for t, ms in team_matches.items():
        for j in range(1, len(ms)):
            gap = ms[j] - ms[j - 1]
            if gap < ideal_gap:
                cooldown_deficit += ideal_gap - gap

    return {
        'b2b':              b2b,
        'surrogates':       surrogates,
        'rc':               rc,
        'bc':               bc,
        'station_counts':   station_counts,
        'opp':              opp,
        'par':              par,
        'team_matches':     team_matches,
        'tbm':              tbm,
        'n_matches':        n,
        'cooldown_deficit': cooldown_deficit,
        'ideal_gap':        ideal_gap,
    }


def _match_swap_apply_delta(state: dict, matches: list[Match],
                            m_a: int, idx_a: int, side_a: str,
                            m_b: int, idx_b: int, side_b: str) -> float:
    """Swap team in matches[m_a].{side_a}[idx_a] with team in matches[m_b].{side_b}[idx_b].

    side_a, side_b ∈ {"red", "blue"}.

    Mutates ``state`` and ``matches`` in place. Returns the canonical-score
    delta (positive = improvement). Self-inverse: calling again with the
    same arguments reverts.

    Constraint check is the caller's responsibility — this function assumes
    the swap is valid (no team appears twice in the same match after).

    Self-swap (m_a == m_b and idx_a == idx_b and side_a == side_b) returns 0.
    Same-match swap that just permutes within the match is supported.
    """
    ma = matches[m_a]
    mb = matches[m_b]

    ta = ma.red[idx_a] if side_a == "red" else ma.blue[idx_a]
    tb = mb.red[idx_b] if side_b == "red" else mb.blue[idx_b]

    if ta == tb:
        return 0.0  # swapping a team with itself is a no-op

    rc = state['rc']; bc = state['bc']
    station_counts = state['station_counts']
    opp = state['opp']; par = state['par']
    tbm = state['tbm']
    team_matches = state['team_matches']
    n_matches = state['n_matches']
    ideal_gap = state.get('ideal_gap', 3)

    def pair(a: int, b: int) -> tuple[int, int]:
        return (a, b) if a < b else (b, a)

    def team_cooldown_deficit(t: int) -> int:
        """Compute cooldown deficit for team t from its current match list."""
        ms = team_matches[t]
        # team_matches isn't always sorted (cross-match swaps may break order);
        # sort here to be safe. Cost is O(MPT log MPT) per swap, negligible.
        ms_sorted = sorted(ms)
        d = 0
        for j in range(1, len(ms_sorted)):
            gap = ms_sorted[j] - ms_sorted[j - 1]
            if gap < ideal_gap:
                d += ideal_gap - gap
        return d

    # ── Capture pre-swap component values for delta computation ──────────
    old_max_imbal = max(abs(rc[t] - bc[t]) for t in rc)
    old_sta_pen_a = max(station_counts[ta]) - min(station_counts[ta])
    old_sta_pen_b = max(station_counts[tb]) - min(station_counts[tb])
    # Cooldown: compute pre-swap deficit for ta and tb only (others don't change)
    old_cd_a = team_cooldown_deficit(ta)
    old_cd_b = team_cooldown_deficit(tb)

    opp_quad_delta = 0
    par_quad_delta = 0

    # ── Set up which matches are affected ──────────────────────────────
    affected_matches = {m_a, m_b}

    # b2b tracks edges (i-1, i); affected if either match is at i-1 or i
    affected_edges: set[int] = set()
    for i in affected_matches:
        if i > 0:
            affected_edges.add(i)
        if i + 1 < n_matches:
            affected_edges.add(i + 1)
    old_b2b_for_edges = {
        edge: (1 if (tbm[edge] & tbm[edge - 1]) else 0)
        for edge in affected_edges
    }

    # ── Process each affected match: subtract old contributions, add new ──
    # We iterate over each affected match exactly once, computing its old
    # opp/par/rc/bc/station contributions, removing them, then computing
    # the new contributions after the swap and adding them.
    #
    # When m_a == m_b, both teams are in the same match and we process it
    # once (the swap is internal to that match — typically a station/colour
    # permutation rather than a team-set change). When m_a != m_b, we
    # process each match independently.

    def process_match(m_idx: int, swaps_in_this_match: list[tuple[str, int, int]]):
        """Process one match's contribution changes.

        swaps_in_this_match: list of (side, idx, new_team) — positions in
        this match that are receiving a new team, and what the new team is.
        """
        nonlocal opp_quad_delta, par_quad_delta
        m = matches[m_idx]
        old_red  = list(m.red)
        old_blue = list(m.blue)
        old_red_sur = list(m.red_surrogate)
        old_blue_sur = list(m.blue_surrogate)

        # Compute new lineup
        new_red = list(old_red)
        new_blue = list(old_blue)
        new_red_sur = list(old_red_sur)
        new_blue_sur = list(old_blue_sur)
        for side, idx, new_t in swaps_in_this_match:
            if side == "red":
                new_red[idx] = new_t
            else:
                new_blue[idx] = new_t

        # Surrogate flags: each team carries its own flag from where it came.
        # We need to know the source flag for each new team. The caller
        # passes only (side, idx, new_t); we look up the source flag from
        # the OTHER match's old state in the parent function and pass it
        # through swaps_in_this_match[i] = (side, idx, new_t, new_sur).
        # For brevity here, surrogate handling is done by the parent caller
        # which sets new_red_sur / new_blue_sur explicitly.

        # ── Subtract old opp/par contributions for this match ───────────
        for r in old_red:
            for b in old_blue:
                p = pair(r, b)
                old_v = opp[p]
                opp_quad_delta -= old_v * old_v
                new_v = old_v - 1
                if new_v == 0:
                    del opp[p]
                else:
                    opp[p] = new_v
                opp_quad_delta += new_v * new_v
        for ai in range(len(old_red)):
            for bi in range(ai + 1, len(old_red)):
                p = pair(old_red[ai], old_red[bi])
                old_v = par[p]
                par_quad_delta -= old_v * old_v
                new_v = old_v - 1
                if new_v == 0:
                    del par[p]
                else:
                    par[p] = new_v
                par_quad_delta += new_v * new_v
        for ai in range(len(old_blue)):
            for bi in range(ai + 1, len(old_blue)):
                p = pair(old_blue[ai], old_blue[bi])
                old_v = par[p]
                par_quad_delta -= old_v * old_v
                new_v = old_v - 1
                if new_v == 0:
                    del par[p]
                else:
                    par[p] = new_v
                par_quad_delta += new_v * new_v

        # ── Subtract rc/bc/station for old teams in this match ──────────
        for sta, t in enumerate(old_red):
            rc[t] -= 1
            station_counts[t][sta] -= 1
        for sta, t in enumerate(old_blue):
            bc[t] -= 1
            station_counts[t][3 + sta] -= 1

        # ── Add new opp/par contributions for this match ───────────────
        for r in new_red:
            for b in new_blue:
                p = pair(r, b)
                old_v = opp.get(p, 0)
                opp_quad_delta -= old_v * old_v
                new_v = old_v + 1
                opp[p] = new_v
                opp_quad_delta += new_v * new_v
        for ai in range(len(new_red)):
            for bi in range(ai + 1, len(new_red)):
                p = pair(new_red[ai], new_red[bi])
                old_v = par.get(p, 0)
                par_quad_delta -= old_v * old_v
                new_v = old_v + 1
                par[p] = new_v
                par_quad_delta += new_v * new_v
        for ai in range(len(new_blue)):
            for bi in range(ai + 1, len(new_blue)):
                p = pair(new_blue[ai], new_blue[bi])
                old_v = par.get(p, 0)
                par_quad_delta -= old_v * old_v
                new_v = old_v + 1
                par[p] = new_v
                par_quad_delta += new_v * new_v

        # ── Add rc/bc/station for new teams in this match ──────────────
        for sta, t in enumerate(new_red):
            rc[t] += 1
            station_counts[t][sta] += 1
        for sta, t in enumerate(new_blue):
            bc[t] += 1
            station_counts[t][3 + sta] += 1

        return new_red, new_blue, new_red_sur, new_blue_sur

    # Set up swap descriptors and surrogate flags
    src_sur_a = ma.red_surrogate[idx_a] if side_a == "red" else ma.blue_surrogate[idx_a]
    src_sur_b = mb.red_surrogate[idx_b] if side_b == "red" else mb.blue_surrogate[idx_b]

    if m_a == m_b:
        # Single-match swap: ta and tb swap positions within the match
        new_red, new_blue, new_red_sur, new_blue_sur = process_match(
            m_a, [(side_a, idx_a, tb), (side_b, idx_b, ta)]
        )
        # Surrogate flags swap with their teams
        if side_a == "red":
            new_red_sur[idx_a] = src_sur_b
        else:
            new_blue_sur[idx_a] = src_sur_b
        if side_b == "red":
            new_red_sur[idx_b] = src_sur_a
        else:
            new_blue_sur[idx_b] = src_sur_a

        matches[m_a] = Match(
            red=tuple(new_red), blue=tuple(new_blue),
            red_surrogate=tuple(new_red_sur),
            blue_surrogate=tuple(new_blue_sur),
        )
        # tbm is unchanged for single-match swap (same team set)
    else:
        # Cross-match swap: ta moves to match B (taking its surrogate flag),
        # tb moves to match A (taking its surrogate flag)
        new_red_a, new_blue_a, new_red_sur_a, new_blue_sur_a = process_match(
            m_a, [(side_a, idx_a, tb)]
        )
        # ta's surrogate flag at its old position is GONE; tb's flag goes there
        if side_a == "red":
            new_red_sur_a[idx_a] = src_sur_b
        else:
            new_blue_sur_a[idx_a] = src_sur_b
        matches[m_a] = Match(
            red=tuple(new_red_a), blue=tuple(new_blue_a),
            red_surrogate=tuple(new_red_sur_a),
            blue_surrogate=tuple(new_blue_sur_a),
        )
        new_red_b, new_blue_b, new_red_sur_b, new_blue_sur_b = process_match(
            m_b, [(side_b, idx_b, ta)]
        )
        if side_b == "red":
            new_red_sur_b[idx_b] = src_sur_a
        else:
            new_blue_sur_b[idx_b] = src_sur_a
        matches[m_b] = Match(
            red=tuple(new_red_b), blue=tuple(new_blue_b),
            red_surrogate=tuple(new_red_sur_b),
            blue_surrogate=tuple(new_blue_sur_b),
        )

        # Update tbm and team_matches for the affected matches
        tbm[m_a] = set(matches[m_a].red + matches[m_a].blue)
        tbm[m_b] = set(matches[m_b].red + matches[m_b].blue)
        # ta's match list: remove m_a, add m_b. tb's: remove m_b, add m_a.
        # Matches are ordered arbitrarily in team_matches, so just rebuild.
        # We could be cleverer, but team_matches is rebuilt every move when
        # cross-match swap happens, which is rare; the cost is O(MPT) per swap.
        ta_ml = team_matches[ta]
        ta_ml.remove(m_a)
        ta_ml.append(m_b)
        tb_ml = team_matches[tb]
        tb_ml.remove(m_b)
        tb_ml.append(m_a)

    # ── Compute b2b delta from affected edges ────────────────────────────
    b2b_delta = 0
    for edge in affected_edges:
        new_status = 1 if (tbm[edge] & tbm[edge - 1]) else 0
        b2b_delta += new_status - old_b2b_for_edges[edge]
    state['b2b'] += b2b_delta

    # ── station_pen delta (only ta and tb's stations changed) ───────────
    new_sta_pen_a = max(station_counts[ta]) - min(station_counts[ta])
    new_sta_pen_b = max(station_counts[tb]) - min(station_counts[tb])
    station_pen_delta = (new_sta_pen_a - old_sta_pen_a) + (new_sta_pen_b - old_sta_pen_b)

    # ── max_imbal delta ─────────────────────────────────────────────────
    new_max_imbal = max(abs(rc[t] - bc[t]) for t in rc)
    max_imbal_delta = new_max_imbal - old_max_imbal

    # ── cooldown_deficit delta (only ta and tb's gap patterns changed) ──
    # For within-match swaps (m_a == m_b), team_matches doesn't change, so
    # no cooldown delta. For cross-match swaps, ta moved from m_a to m_b
    # and tb moved from m_b to m_a, changing both teams' gap patterns.
    if m_a == m_b:
        cooldown_delta = 0
    else:
        new_cd_a = team_cooldown_deficit(ta)
        new_cd_b = team_cooldown_deficit(tb)
        cooldown_delta = (new_cd_a - old_cd_a) + (new_cd_b - old_cd_b)
        state['cooldown_deficit'] = state.get('cooldown_deficit', 0) + cooldown_delta

    # ── Assemble total delta ─────────────────────────────────────────────
    # Score = -penalty. Delta_score = -delta_penalty.
    penalty_delta = (b2b_delta            * 1000
                     + max_imbal_delta    *  500
                     + opp_quad_delta    * W_OPPONENT
                     + par_quad_delta    * W_PARTNER
                     + station_pen_delta * W_STATION
                     + cooldown_delta    * 1000)
    return -penalty_delta


def _is_valid_swap(matches: list[Match],
                   m_a: int, idx_a: int, side_a: str,
                   m_b: int, idx_b: int, side_b: str) -> bool:
    """Check whether swapping these two team positions would produce a
    valid schedule (no team appears twice in the same match).

    Cooldown is NOT checked here — that's added in Phase 3.
    """
    if m_a == m_b:
        # Within-match swap: always valid (just rearranging existing teams)
        return True
    ma = matches[m_a]
    mb = matches[m_b]
    ta = ma.red[idx_a] if side_a == "red" else ma.blue[idx_a]
    tb = mb.red[idx_b] if side_b == "red" else mb.blue[idx_b]
    if ta == tb:
        return False  # same team, not a real swap
    # If ta is already in match B, swapping in another ta would dupe
    if ta in mb.red or ta in mb.blue:
        return False
    if tb in ma.red or tb in ma.blue:
        return False
    return True


def _sa_optimize(matches: list[Match], n_iterations: int,
                 rng: random.Random) -> list[Match]:
    """Run simulated annealing on a feasible Match list.

    Move generator: pick two random match positions (each is a (match, side, idx)
    triple); attempt to swap the teams at those positions. Reject swap if it
    would produce an invalid schedule (team duplicated within a match).

    The full canonical-score delta is computed for each accepted move; the
    SA's accept/reject is driven by that delta.

    Returns the best-scoring schedule encountered (best may be the input if
    no improvement was found).
    """
    if not matches or n_iterations <= 0:
        return matches[:]

    # Operate on a working copy
    work = list(matches)
    state = _build_match_state(work)
    score = _score_from_state(state)
    best_score = score
    best_snapshot = list(work)

    n = len(work)
    # Each match has 6 positions. Generate (match, side, idx) tuples.
    # Pre-allocate the position list to avoid recomputing each step.
    positions: list[tuple[int, str, int]] = []
    for mi in range(n):
        for k in range(3):
            positions.append((mi, "red",  k))
            positions.append((mi, "blue", k))
    n_positions = len(positions)

    if n_positions < 2:
        return matches[:]

    T0 = 500.0
    for step in range(n_iterations):
        T = T0 * (1.0 - step / n_iterations)

        # Pick two random distinct positions
        i, j = rng.sample(range(n_positions), 2)
        m_a, side_a, idx_a = positions[i]
        m_b, side_b, idx_b = positions[j]

        if not _is_valid_swap(work, m_a, idx_a, side_a, m_b, idx_b, side_b):
            continue

        delta = _match_swap_apply_delta(state, work,
                                        m_a, idx_a, side_a,
                                        m_b, idx_b, side_b)
        accept = (delta >= 0) or (T > 0 and (delta / T) > -10
                                  and rng.random() < math.exp(delta / T))
        if accept:
            score += delta
            if score > best_score:
                best_score = score
                best_snapshot = list(work)
        else:
            # Revert: same swap call is self-inverse
            _match_swap_apply_delta(state, work,
                                    m_a, idx_a, side_a,
                                    m_b, idx_b, side_b)

    return best_snapshot


# ── Backward-compat assignment workers (Phase 0) ──────────────────────────
# These preserve the (abstract_matches, num_teams, team_numbers, ...) tuple
# signature that app/main.py's /assign endpoint uses, while internally
# running the unified Phase 0 pipeline:
#   1. Apply slot_map relabeling (slot index → team_numbers[slot-1])
#   2. Run SA optimization on the relabeled Match list
# This is the bridge from the legacy "abstract → assign" two-step UX to
# the unified placement model. The DB-persisted abstract_matches are
# preserved as the SA's initial state so the user's "preview" still
# corresponds to the assigned schedule (modulo SA improvements).

def _abstract_to_matches(abstract_matches: list[dict],
                         team_numbers: list[int],
                         num_teams: int) -> list[Match]:
    """Apply slot→team relabeling to an abstract schedule.

    Slot index i (1..N) becomes team_numbers[i-1]. Returns a Match list
    suitable for SA optimization or scoring."""
    slot_to_team = {i + 1: team_numbers[i] for i in range(num_teams)}
    out: list[Match] = []
    for am in abstract_matches:
        out.append(Match(
            red=tuple(slot_to_team[s] for s in am['red']),
            blue=tuple(slot_to_team[s] for s in am['blue']),
            red_surrogate=tuple(am['red_surrogate']),
            blue_surrogate=tuple(am['blue_surrogate']),
        ))
    return out


def _matches_to_slot_map(matches: list[Match],
                         team_numbers: list[int],
                         num_teams: int) -> dict[str, int]:
    """Build a slot_map shim from a Match list.

    The slot_map field in AssignedSchedule.slot_map is a JSON column with
    downstream consumers (frontend, V2 URL encoding, FMS export, named
    history). Phase 0 preserves it as the trivial identity-shaped shim:
        slot_map[str(i)] = team_numbers[i-1]  for i in 1..N
    Real team numbers live directly in the matches; the slot_map is just
    the index→team mapping that the frontend uses for various lookups.
    """
    return {str(i + 1): team_numbers[i] for i in range(num_teams)}


def _assign_unified(abstract_matches: list[dict],
                    num_teams: int,
                    team_numbers: list[int],
                    ideal_gap: int,
                    sa_iterations: int,
                    seed: int | None,
                    rb_post_pass: bool = True) -> dict:
    """Run Phase 0+1 unified assignment.

    Takes a saved abstract schedule (slot indices), relabels with real
    teams, runs SA optimization, runs the Phase 1 R/B post-pass. Returns
    a dict with the same shape as the legacy assign_teams output:
    {'slot_map': {...}, 'score': float, 'matches': [...]}.
    """
    if len(team_numbers) != num_teams:
        raise ValueError(
            f"team_numbers length {len(team_numbers)} != num_teams {num_teams}"
        )
    if len(set(team_numbers)) != num_teams:
        raise ValueError("team_numbers must be unique")

    rng = random.Random(seed)
    matches = _abstract_to_matches(abstract_matches, team_numbers, num_teams)
    if sa_iterations > 0:
        matches = _sa_optimize(matches, sa_iterations, rng)

    # Phase 1: R/B balance post-pass (commutative with all other criteria)
    if rb_post_pass and len(matches) > 0:
        from app.post_passes.rb_balance import rb_balance_sa
        matches, _stats = rb_balance_sa(matches, n_iterations=5000, seed=seed)

    score = score_schedule(matches, num_teams)
    slot_map = _matches_to_slot_map(matches, team_numbers, num_teams)

    return {
        'slot_map': slot_map,
        'score':    score,
        'matches':  [
            {
                'red':            list(m.red),
                'blue':           list(m.blue),
                'red_surrogate':  list(m.red_surrogate),
                'blue_surrogate': list(m.blue_surrogate),
            }
            for m in matches
        ],
    }


def run_assignment_chunk(args: tuple) -> dict:
    """Worker entry point for the /assign endpoint.

    Phase 0: preserves the legacy tuple signature but calls the unified
    Phase 0 pipeline. ``chunk_size`` is reinterpreted as the SA iteration
    budget for this chunk; the worker runs one trial (no inner loop)
    because the SA itself is the optimization, not best-of-N.
    """
    abstract_matches, num_teams, team_numbers, ideal_gap, chunk_size, worker_id, seed = args
    result = _assign_unified(
        abstract_matches=abstract_matches,
        num_teams=num_teams,
        team_numbers=team_numbers,
        ideal_gap=ideal_gap,
        sa_iterations=chunk_size,
        seed=seed,
    )
    result['worker_id'] = worker_id
    result['iterations_done'] = chunk_size
    return result


def run_assignment_worker(args: tuple) -> dict:
    """Worker entry point — backwards-compat alias for run_assignment_chunk
    that doesn't include iterations_done in the output (legacy callers
    that don't expect that field)."""
    abstract_matches, num_teams, team_numbers, ideal_gap, n_iterations, worker_id, seed = args
    result = _assign_unified(
        abstract_matches=abstract_matches,
        num_teams=num_teams,
        team_numbers=team_numbers,
        ideal_gap=ideal_gap,
        sa_iterations=n_iterations,
        seed=seed,
    )
    result['worker_id'] = worker_id
    return result
