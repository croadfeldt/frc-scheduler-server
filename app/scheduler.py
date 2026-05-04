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
                     weights: dict | None = None) -> ScheduleResult:
    """Generate one Stage 1 schedule iteration.

    weights: optional override for the W_* constants. Pass DEFAULT_WEIGHTS
    or FIRST_STRICT_WEIGHTS, or a custom dict with any subset of:
        balance, gap, count, opponent, partner, station, sur_rpt
    Missing keys fall back to module defaults.
    """
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

    def station_imbalance_penalty(red: list[int], blue: list[int]) -> float:
        """Penalize tentatively assigning these 6 teams to stations 0..5
        (R1, R2, R3, B1, B2, B3 in that order). Cost is the marginal increase
        in max-min station spread for each team."""
        s = 0.0
        for i, t in enumerate(red):
            # Station i (0..2 for red 1..3) would gain one appearance
            new_counts = list(station_counts[t])
            new_counts[i] += 1
            s -= w_station * (max(new_counts) - min(new_counts))
        for i, t in enumerate(blue):
            new_counts = list(station_counts[t])
            new_counts[3 + i] += 1
            s -= w_station * (max(new_counts) - min(new_counts))
        return s

    def assign_alliances(six: list[int]) -> tuple[list[int], list[int]] | None:
        """Pick the best 3-red / 3-blue split AND best within-alliance ordering
        for these 6 teams. Tries every combination (20 splits × 36 orderings =
        720 candidates per match). Cheap, runs once per match."""
        if len(six) != 6 or len(set(six)) != 6:
            return None
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
            # Try a few orderings within each alliance to find best station
            # placement. We don't enumerate all 6 (3! × 3! = 36) — that's
            # cheap but we usually find a good one in ~6 tries with the
            # heuristic: prefer placing teams at their LEAST-occupied stations.
            best_ord_score = -float('inf')
            best_ord_r, best_ord_b = r, b
            for r_ord in _PERM3:
                for b_ord in _PERM3:
                    rr = [r[k] for k in r_ord]
                    bb = [b[k] for k in b_ord]
                    sta = station_imbalance_penalty(rr, bb)
                    if sta > best_ord_score:
                        best_ord_score = sta
                        best_ord_r, best_ord_b = rr, bb
            total = bal + div + best_ord_score
            if total > best_score:
                best_score = total
                best_r, best_b = best_ord_r, best_ord_b
        return (best_r, best_b) if best_r is not None else None

    def assign_alliances_r1(six: list[int]) -> tuple[list[int], list[int]] | None:
        """Round-1-aware variant: also penalizes uneven distribution of
        second-time players across the two alliances in the round-1 boundary
        match. Used only at the round-1/round-2 transition."""
        if len(six) != 6 or len(set(six)) != 6:
            return None
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
            best_ord_score = -float('inf')
            best_ord_r, best_ord_b = r, b
            for r_ord in _PERM3:
                for b_ord in _PERM3:
                    rr = [r[k] for k in r_ord]
                    bb = [b[k] for k in b_ord]
                    sta = station_imbalance_penalty(rr, bb)
                    if sta > best_ord_score:
                        best_ord_score = sta
                        best_ord_r, best_ord_b = rr, bb
            total = sec_penalty + bal + div + best_ord_score
            if total > best_score:
                best_score = total
                best_r, best_b = best_ord_r, best_ord_b
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
            fp = random.sample(first_pool, min(first_slots, len(first_pool)))
            sp = random.sample(second_pool, min(extra_slots, len(second_pool))) if extra_slots else []
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

    return ScheduleResult(
        matches=matches,
        surrogate_count=sc,
        round_boundaries=round_boundaries,
        score=score_schedule(matches, num_teams),
    )


def score_schedule(matches: list[Match], num_teams: int) -> float:
    """Score a complete schedule — used to pick the best of N iterations.

    Penalties (negative score):
      - back-to-back appearances: 1000 per occurrence (effectively hard)
      - max red/blue imbalance per team: 500 per imbalance unit
      - surrogate count: 200 per surrogate
      - opponent repeats: sum of count² × 60 — quadratic, so a 2nd repeat
        for the same pair is 4× as costly as the 1st
      - partner repeats: sum of count² × 80 — same shape, weighted higher
        (FIRST: partner duplication is more costly than opponent because
        there are only 2 partners but 3 opponents per match)
      - station imbalance: sum across teams of (max_station - min_station)
        × 30 — pushes each team to appear roughly equally at all 6
        positions (R1, R2, R3, B1, B2, B3)
    """
    if not matches:
        return -float('inf')

    b2b = 0
    surrogates = 0
    red_counts  = [0] * (num_teams + 1)
    blue_counts = [0] * (num_teams + 1)
    station_counts = [[0] * 6 for _ in range(num_teams + 1)]
    opp  = [[0] * (num_teams + 1) for _ in range(num_teams + 1)]
    par  = [[0] * (num_teams + 1) for _ in range(num_teams + 1)]

    for i, m in enumerate(matches):
        if i > 0:
            prev = set(matches[i-1].red + matches[i-1].blue)
            if any(t in prev for t in m.red + m.blue):
                b2b += 1
        surrogates += sum(m.red_surrogate) + sum(m.blue_surrogate)
        for sta_idx, t in enumerate(m.red):
            red_counts[t] += 1
            station_counts[t][sta_idx] += 1
        for sta_idx, t in enumerate(m.blue):
            blue_counts[t] += 1
            station_counts[t][3 + sta_idx] += 1
        for r in m.red:
            for b in m.blue:
                opp[r][b] += 1; opp[b][r] += 1
        rl = list(m.red); bl = list(m.blue)
        for a in range(len(rl)):
            for b in range(a + 1, len(rl)):
                par[rl[a]][rl[b]] += 1; par[rl[b]][rl[a]] += 1
        for a in range(len(bl)):
            for b in range(a + 1, len(bl)):
                par[bl[a]][bl[b]] += 1; par[bl[b]][bl[a]] += 1

    max_imbalance = max(abs(red_counts[t] - blue_counts[t]) for t in range(1, num_teams + 1))

    # Quadratic penalty for repeats — encourages spreading repeats across
    # many pairs rather than concentrating them on a few unlucky pairs.
    # opp/par are symmetric so we only count each (a,b) once with a < b.
    opp_penalty = 0
    par_penalty = 0
    for a in range(1, num_teams + 1):
        for b in range(a + 1, num_teams + 1):
            if opp[a][b] > 0:
                opp_penalty += opp[a][b] ** 2
            if par[a][b] > 0:
                par_penalty += par[a][b] ** 2

    # Station imbalance — sum across teams of (max - min) station counts.
    # 0 means perfectly balanced; higher means some stations get heavier use.
    station_penalty = 0
    for t in range(1, num_teams + 1):
        sc_t = station_counts[t]
        if any(sc_t):
            station_penalty += max(sc_t) - min(sc_t)

    return -(b2b * 1000 + max_imbalance * 500 + surrogates * 200 +
             opp_penalty * W_OPPONENT + par_penalty * W_PARTNER +
             station_penalty * W_STATION)


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


# ── Stage 2: Team Assignment ──────────────────────────────────────────────────

def assign_teams(
    abstract_matches: list[dict],
    num_teams: int,
    team_numbers: list[int],
    ideal_gap: int = 3,
    n_iterations: int = 100,
    seed: int | None = None,
) -> dict:
    if len(team_numbers) != num_teams:
        raise ValueError(f"team_numbers length {len(team_numbers)} != num_teams {num_teams}")

    ideal_gap = max(1, ideal_gap)
    slots = list(range(1, num_teams + 1))

    slot_matches: dict[int, list[int]] = {s: [] for s in slots}
    for i, m in enumerate(abstract_matches):
        for s in m['red']:  slot_matches[s].append(i)
        for s in m['blue']: slot_matches[s].append(i)

    total_surrogates = sum(
        sum(m['red_surrogate']) + sum(m['blue_surrogate'])
        for m in abstract_matches
    )

    def build_score_state(slot_map: dict[int, int]) -> tuple:
        b2b = 0
        opp: dict[tuple[int, int], int] = {}
        par: dict[tuple[int, int], int] = {}
        rc: dict[int, int] = {t: 0 for t in team_numbers}
        bc: dict[int, int] = {t: 0 for t in team_numbers}
        tbm: list[set[int]] = []

        for i, m in enumerate(abstract_matches):
            red  = [slot_map[s] for s in m['red']]
            blue = [slot_map[s] for s in m['blue']]
            cur  = set(red + blue)
            tbm.append(cur)
            if i > 0 and cur & tbm[i - 1]:
                b2b += 1
            for t in red:  rc[t] += 1
            for t in blue: bc[t] += 1
            for r in red:
                for b in blue:
                    opp[(min(r,b), max(r,b))] = opp.get((min(r,b), max(r,b)), 0) + 1
            for j in range(len(red)):
                for k in range(j + 1, len(red)):
                    p = (min(red[j],red[k]), max(red[j],red[k]))
                    par[p] = par.get(p, 0) + 1
            for j in range(len(blue)):
                for k in range(j + 1, len(blue)):
                    p = (min(blue[j],blue[k]), max(blue[j],blue[k]))
                    par[p] = par.get(p, 0) + 1

        max_imbal = max(abs(rc[t] - bc[t]) for t in team_numbers) if team_numbers else 0
        ro = sum(max(0, v - 1) for v in opp.values())
        rp = sum(max(0, v - 1) for v in par.values())
        score = -(b2b * 1000 + max_imbal * 500 + total_surrogates * 200 + ro * 15 + rp * 12)
        return score, b2b, opp, par, rc, bc, tbm

    def delta_swap(slot_map, sa, sb, b2b, opp, par, rc, bc, tbm):
        ta = slot_map[sa]; tb = slot_map[sb]
        affected = set(slot_matches[sa]) | set(slot_matches[sb])

        old_b2b = 0; new_b2b = 0
        old_imbal = max(abs(rc[t] - bc[t]) for t in team_numbers)

        new_rc = dict(rc); new_bc = dict(bc)
        for idx in affected:
            m = abstract_matches[idx]
            red  = [slot_map[s] for s in m['red']]
            blue = [slot_map[s] for s in m['blue']]
            for t in red:  new_rc[t] -= 1
            for t in blue: new_bc[t] -= 1
            new_red  = [tb if t == ta else (ta if t == tb else t) for t in red]
            new_blue = [tb if t == ta else (ta if t == tb else t) for t in blue]
            for t in new_red:  new_rc[t] += 1
            for t in new_blue: new_bc[t] += 1

        new_imbal = max(abs(new_rc[t] - new_bc[t]) for t in team_numbers)

        w_imbal = new_imbal - old_imbal

        return -(w_imbal * 500)

    best_score = -float('inf')
    best_slot_map: dict[int, int] = {}
    _rng = random.Random(seed)

    budget = num_teams
    T0 = 500.0

    for _ in range(n_iterations):
        shuffled = team_numbers[:]
        _rng.shuffle(shuffled)
        slot_map = {slot: team for slot, team in zip(slots, shuffled)}
        score, b2b, opp, par, rc, bc, tbm = build_score_state(slot_map)

        for step in range(budget):
            T = T0 * (1.0 - step / budget)
            sa, sb = _rng.sample(slots, 2)
            delta = delta_swap(slot_map, sa, sb, b2b, opp, par, rc, bc, tbm)

            if delta >= 0 or (T > 0 and (delta / T) > -10 and _rng.random() < (2.718281828 ** (delta / T))):
                slot_map[sa], slot_map[sb] = slot_map[sb], slot_map[sa]
                score, b2b, opp, par, rc, bc, tbm = build_score_state(slot_map)

        if score > best_score:
            best_score = score
            best_slot_map = dict(slot_map)

    return {
        'slot_map': {str(k): v for k, v in best_slot_map.items()},
        'score':    best_score,
    }


def run_assignment_worker(args: tuple) -> dict:
    abstract_matches, num_teams, team_numbers, ideal_gap, n_iterations, worker_id, seed = args
    result = assign_teams(abstract_matches, num_teams, team_numbers, ideal_gap, n_iterations, seed)
    result['worker_id'] = worker_id
    return result


def run_assignment_chunk(args: tuple) -> dict:
    abstract_matches, num_teams, team_numbers, ideal_gap, chunk_size, worker_id, seed = args
    result = assign_teams(abstract_matches, num_teams, team_numbers, ideal_gap, chunk_size, seed)
    result['worker_id'] = worker_id
    result['iterations_done'] = chunk_size
    return result
