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
W_BALANCE  = 50
W_GAP      = 10
W_COUNT    = 5
W_OPPONENT = 15
W_PARTNER  = 12
W_SUR_RPT  = 200


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


def generate_matches(num_teams: int, matches_per_team: int, ideal_gap: int,
                     seed: int | None = None) -> ScheduleResult:
    ideal_gap = max(1, ideal_gap)
    rng = random.Random(seed)

    total_matches     = math.ceil(num_teams * matches_per_team / 6)
    matches_per_round = math.ceil(num_teams / 6)
    total_sur_slots   = total_matches * 6 - num_teams * matches_per_team
    phase1_surplus    = matches_per_round * 6 - num_teams
    fair_sur_cap      = math.ceil(total_sur_slots / num_teams) + 1 if num_teams > 0 else 1

    teams = list(range(1, num_teams + 1))
    rng.shuffle(teams)

    mc  = [0] * (num_teams + 1)
    lp  = [-999] * (num_teams + 1)
    sc  = [0] * (num_teams + 1)
    rc  = [0] * (num_teams + 1)
    bc  = [0] * (num_teams + 1)

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

    # Rule 3: no surrogate as last appearance
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
                if opp[r][b] > 0: repeat_opp += 1
                opp[r][b] += 1; opp[b][r] += 1
        rl = list(m.red); bl = list(m.blue)
        for a in range(len(rl)):
            for b in range(a + 1, len(rl)):
                if par[rl[a]][rl[b]] > 0: repeat_part += 1
                par[rl[a]][rl[b]] += 1; par[rl[b]][rl[a]] += 1
        for a in range(len(bl)):
            for b in range(a + 1, len(bl)):
                if par[bl[a]][bl[b]] > 0: repeat_part += 1
                par[bl[a]][bl[b]] += 1; par[bl[b]][bl[a]] += 1

    max_imbalance = max(abs(red_counts[t] - blue_counts[t]) for t in range(1, num_teams + 1))
    return -(b2b * 1000 + max_imbalance * 500 + surrogates * 200 +
             repeat_opp * 15 + repeat_part * 12)


def run_iterations_worker(args: tuple) -> dict:
    num_teams, matches_per_team, ideal_gap, n_iterations, worker_id, seed = args
    best: ScheduleResult | None = None

    for i in range(n_iterations):
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
