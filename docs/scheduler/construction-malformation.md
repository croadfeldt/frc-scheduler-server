# Construction-phase malformation on odd-team-count fixtures

**Investigation date:** 2026-05-13
**Status:** Fixed; tests in `tests/test_construction_reliability.py`
**Module:** `app/scheduler.py` (greedy construction phase)

---

## The bug

The greedy construction phase had a 20-37% failure rate on real-world
fixture shapes: 51, 55, 61 teams at MPT=7 or 8 (typical MN regional
and state-event sizes). On these seeds, the construction produced a
malformed last match — one alliance with fewer than 3 teams — and
the malformed-check at the bottom of `generate_matches` raised
`ConstructionMalformedError`.

The error message asked the caller to retry with a different seed,
but with 20-30% per-seed failure, multi-seed runs (Generate panel,
canonical curation, Phase D eval) would hit this with high
probability. Production users with 55- or 61-team events would see
mysterious generation failures on roughly a quarter of attempts.

The original `ConstructionMalformedError` docstring claimed
"production fixtures (≥36 teams) are not affected." That claim was
**incorrect** — the empirical measurement that supported it appears
to have only covered shapes without surrogate-required configurations.

## Reproduction

```python
from app.scheduler import generate_matches, ConstructionMalformedError

failures = 0
for seed in range(100):
    try:
        generate_matches(num_teams=55, matches_per_team=7,
                         ideal_gap=2, seed=seed, n_sa_iterations=0)
    except ConstructionMalformedError:
        failures += 1
print(f"{failures}/100 = {failures}% malformed")
# Pre-fix: 23%
# Post-fix: 0%
```

## Root cause analysis

The construction has two surrogate-handling modes:

- **Legacy mode** (MPT < 3 OR no surrogate slots needed): surrogates
  emerge organically at end-of-schedule when `under_quota` dries up
  and we must draw from `at_quota` teams to fill the last few matches.
  Lines 590-604 of `app/scheduler.py`. Robust on tight fixtures.

- **FIRST surrogate mode** (`USE_FIRST_SURROGATE_MODEL = True`, MPT
  >= 3 with surrogate slots): pre-picks `total_sur_slots` teams
  whose `target_count[t] = MPT+1`. The phase-2 loop only draws from
  `under_quota = [t for t in teams if mc[t] < target_count[t]]`.
  Lines 565-570. Lacks the at-quota fallback that the legacy mode has.

The greedy phase-2 loop ordered the pool by `team_score`:

```python
def team_score(t, now):
    gap = now - lp[t]
    if gap < ideal_gap:
        return -1000 * (ideal_gap - gap)
    return gap * w_gap - mc[t] * w_count
```

The `-mc[t] * w_count` term prefers teams with fewer appearances,
which is reasonable in general. **But it doesn't distinguish surrogate
teams from regular teams.** A surrogate team (target=MPT+1, e.g. 8)
with `mc=3` is read as "less full" than a regular team (target=MPT,
e.g. 7) with `mc=4`, even though the surrogate is 37.5% full while
the regular is 57.1% full.

**Consequence**: surrogate teams advance ahead of schedule. They hit
their target (mc=8) before regular teams hit theirs (mc=7). At the
end of the schedule, `under_quota` consists of only the regular teams
still chasing their last appearance — and if it shrinks below 6
before the final match, the last match can't be completed.

### Concrete example (55×7, seed=1)

Investigation captured the malformed state at the final-match raise:

```
Surrogate team set: [9, 29, 45, 46, 49]  (5 pre-picked surrogates)
At target after match 64:
  - 51 teams hit target=7
  - 4 (not 5!) hit target=8
  - 1 surrogate (team 45) still at mc=7, target=8

Last match: red=[31, 50, 53], blue=[44, 43]
  → blue has 2 teams (43 was reused from match 63!) — MALFORMED

Total appearances: 51*7 + 4*8 = 389
Expected: 65 matches × 6 slots = 390
→ Off by exactly 1
```

The greedy ran out of pool one team short. The fallback path at
line 524 (`return six[:3], six[3:6]`) doesn't enforce 6 unique teams
— it just returned whatever the partial pool contained.

## The fix

Two changes in `app/scheduler.py`:

### Change 1: normalize team_score by target_count

Surrogate teams (target=MPT+1) should advance at the same proportional
rate as regular teams (target=MPT). The fix replaces the raw `mc[t]`
term with `(mc[t] / target_count[t]) * matches_per_team`.

```python
def team_score(t, now):
    gap = now - lp[t]
    if gap < ideal_gap:
        return -1000 * (ideal_gap - gap)
    # Fast path: when target == MPT (no surrogate), keep the bit-
    # identical legacy formula. mc/target*target can drift from mc
    # by FP precision, which would change sort tiebreaks.
    if target_count[t] == matches_per_team:
        return gap * w_gap - mc[t] * w_count
    progress = mc[t] / target_count[t]
    return gap * w_gap - progress * matches_per_team * w_count
```

The `* matches_per_team` multiplier keeps the magnitude of the count
term comparable to the legacy form (average target ≈ MPT, so
`mc/target * MPT ≈ mc`).

The fast-path special case for `target == MPT` is important:
floating-point division then multiplication can drift by a few ulps,
which can change sort tiebreaks and therefore the seed-determined
schedule. For non-surrogate fixtures we want bit-identical behavior
so existing schedule-by-seed reproducibility (canonical library,
tests, etc.) doesn't shift.

### Change 2: fall back to at-quota when under_quota dries up

When `len(under_quota) < 6`, top up the pool with at-quota teams so
`best_of_attempts` has enough candidates. Strictly preserves FIRST
§10.5.2 placement on the common case (pool ≥ 6); only deviates in
the rare emergency.

```python
under_quota = sorted(
    [t for t in teams if mc[t] < target_count[t]],
    key=lambda t: (-team_score(t, now), rng.random())
)
if len(under_quota) < 6:
    at_quota = sorted(
        [t for t in teams if mc[t] >= target_count[t]],
        key=lambda t: (-team_score(t, now), rng.random())
    )
    needed = max(0, 12 - len(under_quota))
    reg_pool = under_quota + at_quota[:needed]
else:
    reg_pool = under_quota[:max(12, 6)]
```

The under-quota teams retain priority (they're listed first), so
`best_of_attempts`'s candidate sampling still prefers them. Only
when there genuinely aren't enough do we draw an at-quota team
into the pool.

**Note**: when the fallback fires, the resulting schedule may have
a team appearing more than `target_count[t]` times (over-quota).
This violates FIRST §10.5.2 surrogate placement (surrogate should
be the team's 3rd match). The SA optimization phase MAY rebalance
this via swaps with another team — but it's not guaranteed. The
tradeoff is: an over-quota appearance is strictly better than a
malformed match (which crashes the generation entirely).

In practice, post-fix measurement shows the fallback rarely fires
for the standard inventory — Change 1 alone closes most of the gap,
and Change 2 is the safety net for the residual cases.

## Post-fix verification

Measured on 30 seeds per fixture (200-300 seeds for noise-sensitive
cases). See `tests/test_construction_reliability.py`.

| Fixture | Pre-fix | Post-fix | Notes |
|---|---|---|---|
| 36×7  | 0%   | 0%   | unchanged |
| 36×8  | 3%   | 3%   | unchanged (small fixture, expected) |
| 51×7  | 20%  | **0%**  | fixed |
| 55×7  | 23%  | **0%**  | fixed |
| 55×8  | 37%  | **0%**  | fixed |
| 61×7  | 30%  | **0%**  | fixed |
| 61×8  | 20%  | **0%**  | fixed |

The tiny-fixture rates (10×6, 12×6, 12×7) are unchanged — they're
limited by the fundamental tightness of the fixture, not the
surrogate-handling logic. The deeper fix for those is captured in
the Best Possible Schedule workstream (CP-SAT single-stage
construction for small fixtures).

## What this doesn't fix

- **Tiny fixtures** (≤16 teams) still have nonzero malformation
  rates from the underlying construction-tightness issue. The
  retry-with-different-seed pattern remains the workaround. The
  deeper fix is captured in
  `docs/workstreams/best-possible-schedule.md` Phase 1 Q4.

- **MatchMaker adapter on 51/55/61-team fixtures** is a separate
  bug — the reference scheduler binary errors out on these shapes
  for unrelated reasons. See `docs/scheduler/EVAL_FINDINGS.md`
  §"Surrogate handling for odd team counts" for the current state.

- **Construction quality** (vs reliability). This investigation
  was about producing _a_ valid schedule on these shapes. The
  resulting schedules still go through SA optimization and post-
  passes; quality on the framework metrics is measured separately
  by the standards eval. Anecdotally the post-fix schedules look
  reasonable in single-seed checks, but a Phase D rerun on the
  expanded inventory would confirm.

## Files changed

  - `app/scheduler.py` — team_score normalization + at-quota fallback;
    ConstructionMalformedError docstring updated with post-fix data
  - `scripts/scheduler_eval/adapters/matchmaker.py` — beefed-up
    error capture (stdout + stderr) for the unrelated MatchMaker bug
  - `tests/test_construction_reliability.py` — new regression guard
  - `docs/scheduler/EVAL_FINDINGS.md` — corrected the "FIXED 2026-05-09"
    claim to reflect persistent error
