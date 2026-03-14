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


def generate_matches(num_teams: int, matches_per_team: int, ideal_gap: int) -> ScheduleResult:
    """
    Run one iteration of the two-phase greedy scheduler.
    Returns a ScheduleResult with the schedule and its composite score.
    """
    ideal_gap = max(1, ideal_gap)

    # ── Step 1: Determine match count (pure math) ────────────────────────────
    # total_matches = ceil(N * MPT / 6) — minimum 6-team matches to give every
    # team exactly MPT plays. Any remainder is structural surplus (surrogates).
    # matches_per_round = ceil(N/6) — Phase 1 size and cosmetic marker only.
    total_matches     = math.ceil(num_teams * matches_per_team / 6)
    matches_per_round = math.ceil(num_teams / 6)
    total_sur_slots   = total_matches * 6 - num_teams * matches_per_team
    phase1_surplus    = matches_per_round * 6 - num_teams
    fair_sur_cap      = math.ceil(total_sur_slots / num_teams) + 1 if num_teams > 0 else 1

    # Shuffle team order — each call is a new random iteration
    teams = list(range(1, num_teams + 1))
    random.shuffle(teams)

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
            key=lambda t: (-team_score(t, now), random.random())
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
            key=lambda t: (-team_score(t, now), random.random())
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
    Receives (num_teams, matches_per_team, ideal_gap, n_iterations, worker_id).
    Returns best result as a JSON-serialisable dict.
    """
    num_teams, matches_per_team, ideal_gap, n_iterations, worker_id = args
    best: ScheduleResult | None = None

    for _ in range(n_iterations):
        result = generate_matches(num_teams, matches_per_team, ideal_gap)
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
) -> dict:
    """
    Stage 2: Given an abstract slot-based schedule, find the best mapping of
    real team numbers onto slot indices 1..N.

    The abstract schedule defines WHEN each slot plays and on which alliance.
    This function finds the optimal permutation of team numbers → slots such
    that the placement criteria (P5-P10) are best satisfied.

    Strategy: run n_iterations random shuffles of team_numbers, evaluate each
    permutation's score against the placement criteria, return the best.

    args:
      abstract_matches — list of {red:[s1,s2,s3], blue:[s4,s5,s6],
                                   red_surrogate:[...], blue_surrogate:[...]}
      num_teams        — N (must equal len(team_numbers))
      team_numbers     — list of real team numbers, length N
      ideal_gap        — cooldown parameter
      n_iterations     — how many random assignments to try
    """
    if len(team_numbers) != num_teams:
        raise ValueError(f"team_numbers length {len(team_numbers)} != num_teams {num_teams}")

    ideal_gap = max(1, ideal_gap)

    def score_assignment(slot_map: dict[int, int]) -> float:
        """Score a slot→team mapping against P5-P10 criteria."""
        b2b = 0
        surrogates = 0
        repeat_opp = 0
        repeat_part = 0
        red_counts  = {}
        blue_counts = {}
        opp  = {}
        par  = {}

        def get_team(slot: int) -> int:
            return slot_map[slot]

        prev_teams: set[int] = set()
        for i, m in enumerate(abstract_matches):
            red_teams  = [get_team(s) for s in m['red']]
            blue_teams = [get_team(s) for s in m['blue']]
            all_teams  = red_teams + blue_teams

            if i > 0 and any(t in prev_teams for t in all_teams):
                b2b += 1
            prev_teams = set(all_teams)

            sur = sum(m['red_surrogate']) + sum(m['blue_surrogate'])
            surrogates += sur

            for t in red_teams:
                red_counts[t] = red_counts.get(t, 0) + 1
            for t in blue_teams:
                blue_counts[t] = blue_counts.get(t, 0) + 1

            for r in red_teams:
                for b in blue_teams:
                    key = (min(r,b), max(r,b))
                    if opp.get(key, 0) > 0:
                        repeat_opp += 1
                    opp[key] = opp.get(key, 0) + 1

            for lst in (red_teams, blue_teams):
                for a in range(len(lst)):
                    for b in range(a+1, len(lst)):
                        key = (min(lst[a],lst[b]), max(lst[a],lst[b]))
                        if par.get(key, 0) > 0:
                            repeat_part += 1
                        par[key] = par.get(key, 0) + 1

        all_t = set(red_counts) | set(blue_counts)
        max_imbalance = max(
            abs(red_counts.get(t, 0) - blue_counts.get(t, 0))
            for t in all_t
        ) if all_t else 0

        return -(b2b * 1000 + max_imbalance * 500 + surrogates * 200 +
                 repeat_opp * 15 + repeat_part * 12)

    best_score = -float('inf')
    best_slot_map: dict[int, int] = {}

    slots = list(range(1, num_teams + 1))

    for _ in range(n_iterations):
        shuffled = team_numbers[:]
        random.shuffle(shuffled)
        slot_map = {slot: team for slot, team in zip(slots, shuffled)}
        score = score_assignment(slot_map)
        if score > best_score:
            best_score = score
            best_slot_map = slot_map

    return {
        'slot_map': {str(k): v for k, v in best_slot_map.items()},
        'score':    best_score,
    }


def run_assignment_worker(args: tuple) -> dict:
    """
    Worker for Stage 2 ProcessPoolExecutor.
    Receives (abstract_matches, num_teams, team_numbers, ideal_gap, n_iterations, worker_id).
    Returns best slot_map and score.
    """
    abstract_matches, num_teams, team_numbers, ideal_gap, n_iterations, worker_id = args
    result = assign_teams(abstract_matches, num_teams, team_numbers, ideal_gap, n_iterations)
    result['worker_id'] = worker_id
    return result
