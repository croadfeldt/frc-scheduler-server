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

Scheduling priorities (P1-P10) are identical to the browser version.
"""

import math
import random
from typing import NamedTuple

# ── Weights (mirror JS constants) ────────────────────────────────────────────
W_BALANCE  = 50
W_GAP      = 10
W_COUNT    = 5
W_OPPONENT = 15
W_PARTNER  = 12
W_SUR_RPT  = 200


class Match(NamedTuple):
    red:           tuple[int, ...]   # 3 team numbers
    blue:          tuple[int, ...]   # 3 team numbers
    red_surrogate: tuple[bool, ...]
    blue_surrogate: tuple[bool, ...]


class ScheduleResult(NamedTuple):
    matches:          list[Match]
    surrogate_count:  list[int]        # index 0 unused; [1..numTeams]
    round_boundaries: dict[int, int]   # round_number -> match_index (0-based)
    score:            float


# ── Bits for C(6,3) mask enumeration ─────────────────────────────────────────
_MASKS_3_OF_6 = [m for m in range(64) if bin(m).count('1') == 3]


def _popcount3(mask: int) -> list[int]:
    """Return indices of the 3 set bits in a 6-bit mask."""
    return [i for i in range(6) if (mask >> i) & 1]


# Pre-compute all valid (red_indices, blue_indices) pairs
_SPLITS = [
    ([i for i in range(6) if (m >> i) & 1],
     [i for i in range(6) if not (m >> i) & 1])
    for m in _MASKS_3_OF_6
]


def generate_matches(num_teams: int, matches_per_team: int, ideal_gap: int,
                     seed: int | None = None) -> ScheduleResult:
    """
    Run one iteration of the two-phase greedy scheduler.
    If seed is provided, the schedule is fully deterministic and reproducible.
    """
    ideal_gap = max(1, ideal_gap)
    rng = random.Random(seed)

    # ── Step 1: Determine match count (pure math) ────────────────────────────
    # total_matches = ceil(N * MPT / 6) — minimum 6-team matches to give every
    # team exactly MPT plays. Any remainder is structural surplus (surrogates).
    # matches_per_round = ceil(N/6) — Phase 1 size and cosmetic marker only.
    total_matches     = math.ceil(num_teams * matches_per_team / 6)
    matches_per_round = math.ceil(num_teams / 6)
    total_sur_slots   = total_matches * 6 - num_teams * matches_per_team
    phase1_surplus    = matches_per_round * 6 - num_teams
    fair_sur_cap      = math.ceil(total_sur_slots / num_teams) + 1 if num_teams > 0 else 1

    # Shuffle team order — deterministic if seed provided
    teams = list(range(1, num_teams + 1))
    rng.shuffle(teams)

    # Per-team state (1-indexed; index 0 unused)
    mc  = [0] * (num_teams + 1)   # match counts
    lp  = [-999] * (num_teams + 1) # last played (match index)
    sc  = [0] * (num_teams + 1)   # surrogate count
    rc  = [0] * (num_teams + 1)   # red count
    bc  = [0] * (num_teams + 1)   # blue count

    opp = [[0] * (num_teams + 1) for _ in range(num_teams + 1)]  # opponents[a][b]
    par = [[0] * (num_teams + 1) for _ in range(num_teams + 1)]  # partners[a][b]

    matches: list[Match] = []

    # Round boundaries are cosmetic markers every matches_per_round matches
    total_rounds = math.ceil(total_matches / matches_per_round)
    round_boundaries: dict[int, int] = {
        r: (r - 1) * matches_per_round
        for r in range(1, total_rounds + 1)
    }

    # ── Scoring helpers ───────────────────────────────────────────────────────
    def team_score(t: int, now: int) -> float:
        gap = now - lp[t]
        if gap < ideal_gap:
            return -1000 * (ideal_gap - gap)
        return gap * W_GAP - mc[t] * W_COUNT

    def surrogate_score(t: int, now: int) -> float:
        return -sc[t] * W_SUR_RPT + (now - lp[t]) * 2

    def diversity_score(red: list[int], blue: list[int]) -> float:
        s = 0.0
        for r in red:
            for b in blue:
                s -= opp[r][b] * W_OPPONENT
        for i in range(len(red)):
            for j in range(i + 1, len(red)):
                s -= par[red[i]][red[j]] * W_PARTNER
        for i in range(len(blue)):
            for j in range(i + 1, len(blue)):
                s -= par[blue[i]][blue[j]] * W_PARTNER
        return s

    def assign_alliances(six: list[int]) -> tuple[list[int], list[int]] | None:
        if len(six) != 6 or len(set(six)) != 6:
            return None
        best_score = -float('inf')
        best_r, best_b = None, None
        for ri, bi in _SPLITS:
            r = [six[i] for i in ri]
            b = [six[i] for i in bi]
            bal = -W_BALANCE * (
                sum(abs((rc[t] + 1) - bc[t]) for t in r) +
                sum(abs(rc[t] - (bc[t] + 1)) for t in b)
            )
            total = bal + diversity_score(r, b)
            if total > best_score:
                best_score = total
                best_r, best_b = r, b
        return (best_r, best_b) if best_r is not None else None

    def assign_alliances_r1(six: list[int]) -> tuple[list[int], list[int]] | None:
        """Round-1 last match: also penalise imbalanced second-timer distribution."""
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
            bal = -W_BALANCE * (
                sum(abs((rc[t] + 1) - bc[t]) for t in r) +
                sum(abs(rc[t] - (bc[t] + 1)) for t in b)
            )
            total = sec_penalty + bal + diversity_score(r, b)
            if total > best_score:
                best_score = total
                best_r, best_b = r, b
        return (best_r, best_b) if best_r is not None else None

    def commit_match(red: list[int], blue: list[int], now: int) -> None:
        for t in red + blue:
            if mc[t] >= matches_per_team:
                sc[t] += 1
            mc[t] += 1
            lp[t] = now
        for t in red:
            rc[t] += 1
        for t in blue:
            bc[t] += 1
        for r in red:
            for b in blue:
                opp[r][b] += 1
                opp[b][r] += 1
        for i in range(len(red)):
            for j in range(i + 1, len(red)):
                par[red[i]][red[j]] += 1
                par[red[j]][red[i]] += 1
        for i in range(len(blue)):
            for j in range(i + 1, len(blue)):
                par[blue[i]][blue[j]] += 1
                par[blue[j]][blue[i]] += 1

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
        # Fallback
        six = first_pool[:first_slots] + second_pool[:extra_slots]
        res = assign_alliances_r1(six) if is_last else assign_alliances(six)
        if res:
            return res
        return six[:3], six[3:6]

    # ── Phase 1: Round 1 ──────────────────────────────────────────────────────
    for m in range(matches_per_round):
        now      = len(matches)
        is_last  = (m == matches_per_round - 1)
        phase1_surplus = matches_per_round * 6 - num_teams
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

    # ── Phase 2: Open scheduling — quota-driven, no round constraints ────────
    # Pick the 6 best-scoring eligible teams per match.
    # W_COUNT in team_score penalises higher mc, so under-played teams naturally
    # score higher and get picked first — keeping play counts balanced.
    # Surrogates only appear when structurally unavoidable (< 6 under-quota teams left).
    for i in range(total_matches - matches_per_round):
        now = len(matches)

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

    # ── Post-generation sweeps ────────────────────────────────────────────────────
    # Rule 1: No surrogate in last match (swap block below)
    # Rule 2: No surrogate as a team's first appearance (guard in swap search)
    # Rule 3: No surrogate as a team's last appearance (flag reassignment sweep)

    def build_appearance_map():
        """Return {team: first_match_idx} and {team: last_match_idx}."""
        first: dict[int, int] = {}
        last_a: dict[int, int] = {}
        for idx, m in enumerate(matches):
            for t in list(m.red) + list(m.blue):
                if t not in first:
                    first[t] = idx
                last_a[t] = idx
        return first, last_a

    # ── Rule 1+2: move last-match surrogates to earlier matches ──────────────────
    if matches:
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
                # Rule 2 guard: skip if this is sur_team's first appearance
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
            else:                  eb[early_p]  = swap_t; ebs[early_p]  = False

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

    # ── Rule 3: no surrogate as a team's last appearance ─────────────────────────
    # Move the surrogate flag to an earlier appearance — no teams change matches.
    for _pass in range(3):
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

            # Find an earlier non-first appearance to receive the flag
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

    return ScheduleResult(
        matches=matches,
        surrogate_count=sc,
        round_boundaries=round_boundaries,
        score=score_schedule(matches, num_teams),
    )


def score_schedule(matches: list[Match], num_teams: int) -> float:
    """Composite score — higher is better (all terms are penalties subtracted)."""
    if not matches:
        return -float('inf')

    b2b = 0
    surrogates = 0
    repeat_opp = 0
    repeat_part = 0
    red_counts  = [0] * (num_teams + 1)
    blue_counts = [0] * (num_teams + 1)
    opp  = [[0] * (num_teams + 1) for _ in range(num_teams + 1)]
    par  = [[0] * (num_teams + 1) for _ in range(num_teams + 1)]

    for i, m in enumerate(matches):
        if i > 0:
            prev = set(matches[i-1].red + matches[i-1].blue)
            if any(t in prev for t in m.red + m.blue):
                b2b += 1
        surrogates += sum(m.red_surrogate) + sum(m.blue_surrogate)
        for t in m.red:
            red_counts[t] += 1
        for t in m.blue:
            blue_counts[t] += 1
        for r in m.red:
            for b in m.blue:
                if opp[r][b] > 0:
                    repeat_opp += 1
                opp[r][b] += 1; opp[b][r] += 1
        rl = list(m.red); bl = list(m.blue)
        for a in range(len(rl)):
            for b in range(a + 1, len(rl)):
                if par[rl[a]][rl[b]] > 0:
                    repeat_part += 1
                par[rl[a]][rl[b]] += 1; par[rl[b]][rl[a]] += 1
        for a in range(len(bl)):
            for b in range(a + 1, len(bl)):
                if par[bl[a]][bl[b]] > 0:
                    repeat_part += 1
                par[bl[a]][bl[b]] += 1; par[bl[b]][bl[a]] += 1

    max_imbalance = max(abs(red_counts[t] - blue_counts[t]) for t in range(1, num_teams + 1))
    # Priority: P1 back-to-backs, P2 alliance balance, P3 surrogates, P4/P5 diversity
    return -(b2b * 1000 + max_imbalance * 500 + surrogates * 200 +
             repeat_opp * 15 + repeat_part * 12)


def run_iterations_worker(args: tuple) -> dict:
    """
    Worker function for ProcessPoolExecutor.
    Receives (num_teams, matches_per_team, ideal_gap, n_iterations, worker_id, seed).
    If seed is provided and n_iterations==1, uses it directly for reproducibility.
    For multiple iterations, each uses seed+iteration_index so results are still
    deterministic given the same seed.
    """
    num_teams, matches_per_team, ideal_gap, n_iterations, worker_id, seed = args
    best: ScheduleResult | None = None

    for i in range(n_iterations):
        # Each iteration gets a derived seed: seed XOR (worker_id * 1000 + i)
        iter_seed = (seed ^ (worker_id * 1000 + i)) if seed is not None else None
        result = generate_matches(num_teams, matches_per_team, ideal_gap, iter_seed)
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
                'red':           list(m.red),
                'blue':          list(m.blue),
                'red_surrogate': list(m.red_surrogate),
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
    """
    Stage 2: find the best mapping of real team numbers onto slot indices 1..N.

    Uses simulated annealing with INCREMENTAL scoring — only affected matches
    are rescored on each swap, giving ~10x speedup over full rescore per step.
    """
    if len(team_numbers) != num_teams:
        raise ValueError(f"team_numbers length {len(team_numbers)} != num_teams {num_teams}")

    ideal_gap = max(1, ideal_gap)
    slots = list(range(1, num_teams + 1))

    # ── Precompute per-slot match index lists ──────────────────────────────────
    # slot_matches[s] = sorted list of match indices containing slot s
    slot_matches: dict[int, list[int]] = {s: [] for s in slots}
    for i, m in enumerate(abstract_matches):
        for s in m['red']:  slot_matches[s].append(i)
        for s in m['blue']: slot_matches[s].append(i)

    # Surrogates are fixed regardless of assignment — precompute once
    total_surrogates = sum(
        sum(m['red_surrogate']) + sum(m['blue_surrogate'])
        for m in abstract_matches
    )

    # ── Full score build (called once per iteration start) ────────────────────
    def build_score_state(slot_map: dict[int, int]) -> tuple:
        """
        Returns (score, b2b, opp, par, red_counts, blue_counts, prev_teams_list).
        opp/par are Counter-like dicts of pair → count.
        prev_teams_list[i] = frozenset of teams in match i (for B2B lookup).
        """
        b2b = 0
        repeat_opp = 0
        repeat_part = 0
        red_counts: dict[int, int] = {}
        blue_counts: dict[int, int] = {}
        opp:  dict[tuple, int] = {}
        par:  dict[tuple, int] = {}
        teams_by_match: list[frozenset] = []

        prev: frozenset = frozenset()
        for m in abstract_matches:
            rt = tuple(slot_map[s] for s in m['red'])
            bt = tuple(slot_map[s] for s in m['blue'])
            at = frozenset(rt + bt)
            if prev and (at & prev):
                b2b += 1
            prev = at
            teams_by_match.append(at)

            for t in rt: red_counts[t]  = red_counts.get(t, 0)  + 1
            for t in bt: blue_counts[t] = blue_counts.get(t, 0) + 1

            for r in rt:
                for b_t in bt:
                    k = (min(r, b_t), max(r, b_t))
                    old = opp.get(k, 0)
                    if old > 0: repeat_opp += 1
                    opp[k] = old + 1

            for lst in (rt, bt):
                for i in range(3):
                    for j in range(i + 1, 3):
                        k = (min(lst[i], lst[j]), max(lst[i], lst[j]))
                        old = par.get(k, 0)
                        if old > 0: repeat_part += 1
                        par[k] = old + 1

        all_t = set(red_counts) | set(blue_counts)
        max_imbalance = max(
            abs(red_counts.get(t, 0) - blue_counts.get(t, 0)) for t in all_t
        ) if all_t else 0

        score = -(b2b * 1000 + max_imbalance * 500 + total_surrogates * 200 +
                  repeat_opp * 15 + repeat_part * 12)
        return score, b2b, opp, par, red_counts, blue_counts, teams_by_match

    # ── Incremental delta score for a 2-swap ──────────────────────────────────
    def delta_swap(slot_map, sa, sb, b2b, opp, par, rc, bc, tbm) -> float:
        """
        Compute the score change if we swap slot_map[sa] ↔ slot_map[sb].
        Only rescores the union of matches containing sa or sb.
        Returns new_score - old_score (positive = improvement).
        """
        ta = slot_map[sa]
        tb = slot_map[sb]
        if ta == tb:
            return 0.0

        affected = sorted(set(slot_matches[sa]) | set(slot_matches[sb]))
        if not affected:
            return 0.0

        # For imbalance: only ta and tb's red/blue counts change
        old_imbal = max(abs(rc.get(t, 0) - bc.get(t, 0)) for t in (ta, tb))

        # Simulate the swap temporarily
        slot_map[sa], slot_map[sb] = slot_map[sb], slot_map[sa]

        d_b2b = 0
        d_ro  = 0
        d_rp  = 0
        d_rc: dict[int, int] = {}
        d_bc: dict[int, int] = {}

        for idx in affected:
            m = abstract_matches[idx]
            # Old teams at this match
            old_rt = tuple(slot_map[s] if s != sa and s != sb else (tb if slot_map[s] == ta else ta)
                           for s in m['red'])
            old_bt = tuple(slot_map[s] if s != sa and s != sb else (tb if slot_map[s] == ta else ta)
                           for s in m['blue'])
            # New teams (swap already applied)
            new_rt = tuple(slot_map[s] for s in m['red'])
            new_bt = tuple(slot_map[s] for s in m['blue'])

            # B2B delta: check prev and next match
            for sign, rt, bt in ((-1, old_rt, old_bt), (+1, new_rt, new_bt)):
                at_f = frozenset(rt + bt)
                if idx > 0 and (at_f & tbm[idx - 1]): d_b2b += sign
                if idx < len(abstract_matches) - 1 and (at_f & tbm[idx + 1]): d_b2b += sign

            # opp/par delta
            for sign, rt, bt in ((-1, old_rt, old_bt), (+1, new_rt, new_bt)):
                for r in rt:
                    for b_t in bt:
                        k = (min(r, b_t), max(r, b_t))
                        cur = opp.get(k, 0) + d_ro  # rough — fine for delta direction
                        if sign == -1 and cur > 1: d_ro -= 1
                        elif sign == +1 and cur > 0: d_ro += 1
                for lst in (rt, bt):
                    for i in range(3):
                        for j in range(i + 1, 3):
                            k = (min(lst[i], lst[j]), max(lst[i], lst[j]))
                            cur = par.get(k, 0)
                            if sign == -1 and cur > 1: d_rp -= 1
                            elif sign == +1 and cur > 0: d_rp += 1

            # red/blue count delta
            for t in old_rt: d_rc[t] = d_rc.get(t, 0) - 1
            for t in new_rt: d_rc[t] = d_rc.get(t, 0) + 1
            for t in old_bt: d_bc[t] = d_bc.get(t, 0) - 1
            for t in new_bt: d_bc[t] = d_bc.get(t, 0) + 1

        # Undo the temporary swap
        slot_map[sa], slot_map[sb] = slot_map[sb], slot_map[sa]

        # Imbalance delta for ta and tb only
        new_rc_ta = rc.get(ta, 0) + d_rc.get(ta, 0)
        new_bc_ta = bc.get(ta, 0) + d_bc.get(ta, 0)
        new_rc_tb = rc.get(tb, 0) + d_rc.get(tb, 0)
        new_bc_tb = bc.get(tb, 0) + d_bc.get(tb, 0)
        new_imbal = max(abs(new_rc_ta - new_bc_ta), abs(new_rc_tb - new_bc_tb))
        d_imbal = new_imbal - old_imbal

        return -(d_b2b * 1000 + d_imbal * 500 + d_ro * 15 + d_rp * 12)

    # ── SA loop ────────────────────────────────────────────────────────────────
    best_score = -float('inf')
    best_slot_map: dict[int, int] = {}
    _rng = random.Random(seed)

    # Budget: num_teams swap attempts — reduced from *2 since incremental is cheaper
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
                # Accept — apply swap and rebuild full state for accuracy
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
    """
    Worker for Stage 2 ProcessPoolExecutor.
    Receives (abstract_matches, num_teams, team_numbers, ideal_gap, n_iterations, worker_id, seed).
    Returns best slot_map and score.
    """
    abstract_matches, num_teams, team_numbers, ideal_gap, n_iterations, worker_id, seed = args
    result = assign_teams(abstract_matches, num_teams, team_numbers, ideal_gap, n_iterations, seed)
    result['worker_id'] = worker_id
    return result


def run_assignment_chunk(args: tuple) -> dict:
    """
    Like run_assignment_worker but runs a small chunk of iterations.
    Used for incremental progress reporting in Stage 2.
    args: (abstract_matches, num_teams, team_numbers, ideal_gap, chunk_size, worker_id, seed)
    Returns best slot_map, score, and iterations_done for this chunk.
    """
    abstract_matches, num_teams, team_numbers, ideal_gap, chunk_size, worker_id, seed = args
    result = assign_teams(abstract_matches, num_teams, team_numbers, ideal_gap, chunk_size, seed)
    result['worker_id'] = worker_id
    result['iterations_done'] = chunk_size
    return result
