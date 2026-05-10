# FRC Match Scheduler — Placement Priorities & Technical Reference

**Authoritative ordering: FRC §10.5.2 lexicographic, paramount cooldown.**

Cooldown is paramount and never traded against any other criterion. The
remaining priorities are compared lexicographically — if a candidate
schedule is strictly better at a higher-priority criterion, it wins
regardless of lower-priority differences.

> **See also:** `docs/PRIORITIES.md` for the construction/SA-phase/post-pass
> architectural deep-dive. This document is the principles + lex-tuple
> spec; the docs/ version is the implementation reference.

---

## The Lex Tuple

Every schedule has an 8-element score tuple. Lower is better at every
position; comparison is lexicographic.

```
(cooldown_violations,    # paramount — count of swap moves that worsen it: 0 always
 par_quad,               # partner-pair sum-of-squares (penalizes repeats hard)
 opp_quad,               # opponent-pair sum-of-squares
 surrogate_count,        # total surrogates required
 rb_metric,              # R/B imbalance — variant by num_teams
 station_pen,            # station distribution penalty (FRC #6)
 surrogate_spread,       # secondary fairness on surrogate placement (P11)
 match_equity)           # secondary fairness on appearance distribution (P5)
```

The first six map directly to FRC §10.5.2 priorities #1–#6. Positions 7
and 8 are local refinements that don't conflict with the FRC priorities;
they only break ties among schedules already optimal at the first six.

### `rb_metric` variant

The R/B (red/blue alliance) balance criterion is computed differently
depending on team count, since the achievable optimum changes:

- **≥24 teams**: `rb_metric = max_team_imbalance`. The maximum across
  teams of `abs(red_count - blue_count)`. With 24+ teams there's enough
  schedule depth that minimizing the worst case is the right objective.
- **<24 teams**: `rb_metric = swap_count`. The number of red/blue swaps
  needed to balance the schedule. With small fields there's not enough
  depth to drive the worst case to zero, so we minimize the cost of
  reaching balance instead.

Both variants are compared by the same lex semantics; only the formula
changes.

---

## Authoritative ordering

1. **Cooldown** (paramount, FRC §10.5.2 #1) — minimum matches between
   appearances of the same team. SA never accepts a swap that worsens
   this. `_swap_preserves_cooldown` filters violations BEFORE the state
   mutation that would create them.
2. **Partner repeats** (FRC §10.5.2 #2) — minimize teams partnering
   with the same teammate more than necessary. Score: `par_quad`
   (sum of pair-count²).
3. **Opponent repeats** (FRC §10.5.2 #3) — minimize teams facing the
   same opponent more than necessary. Score: `opp_quad`.
4. **Surrogate count** (FRC §10.5.2 #4) — minimize total surrogates.
5. **R/B distribution** (FRC §10.5.2 #5) — minimize red/blue alliance
   imbalance. Variant by team count (above).
6. **Station distribution** (FRC §10.5.2 #6) — minimize variance in how
   often each team plays each station (R1/R2/R3/B1/B2/B3).
7. **Surrogate spread (P11)** — secondary fairness on surrogate
   placement. Doesn't conflict with #4; refines among equally-good
   surrogate counts.
8. **Match equity (P5)** — secondary fairness on appearance
   distribution. Doesn't conflict with the FRC priorities; refines among
   equally-good schedules.

---

## Implementation

### Construction phase
`generate_matches()` in `app/scheduler.py`. Produces a feasible schedule
using best-of-60 greedy with diversity-aware match-by-match scoring.
Output: an abstract schedule with slot indices 1..N and surrogate flags.

### SA optimization phase
`_sa_optimize()` in `app/scheduler.py`. Runs random 2-swaps over
`Match[]`. Acceptance is by lex-tuple compare with stochastic uphill
on lower-priority criteria only. Cooldown worsening is rejected
unconditionally. Targeted moves (`_propose_targeted_move`) bias 2/3
of moves toward duplicate partner/opponent pairs, which substantially
improves convergence on criterion #3.

### Post-passes (commutative)

Post-passes change exactly one criterion without disturbing others.
Both have property tests verifying the commutativity claims:

- **R/B post-pass** (Phase 1): `app/post_passes/rb_balance.py`. Whole-match
  red↔blue flip. Preserves partner pairs, opponent pairs, station-
  within-alliance distribution, cooldown, surrogate counts. Changes
  only `rb_metric`. SA-driven to escape greedy local optima.
- **Station post-pass** (Phase 2): `app/post_passes/station_balance.py`.
  Within-alliance permutation of the 3 stations. Preserves everything
  except `station_pen`. SA-from-greedy to ensure the result is never
  worse than greedy alone.

---

## How it gets used end-to-end

**On `/api/abstract-schedules/{id}/assign`:**

1. Load the saved abstract schedule (slot indices)
2. Build initial `Match[]` by relabeling slots → real team numbers
3. Run lex SA for `iterations` steps (resolved from quality preset)
4. Run R/B post-pass if `rb_post_pass=True` (FRC default)
5. Run station post-pass if `station_post_pass=True` (FRC default)
6. Return slot_map + matches + score_tuple

Each `/assign` request runs N=30 trials in parallel (capped by available
cores). Best-of-N comparison uses the lex tuple, not the legacy summary
float.

---

## Quality presets

`app/quality_presets.py` defines four levels for the SA iteration count.
Iteration count doesn't affect FRC compliance — it controls how
thoroughly the SA explores. Higher = better convergence but slower.

| Preset    | Iterations  | Wall-clock (Stark, 36 cores, best-of-30) |
|-----------|-------------|------------------------------------------|
| fair      | 50,000      | ~2s                                      |
| good      | 500,000     | ~20s                                     |
| best      | 2,000,000   | ~75s                                     |
| maximum   | 5,000,000   | ~3min                                    |

The "best" preset (2M iters × best-of-30) consistently produces tuples
in the same range as the MatchMaker reference output on the 2026mnst
fixture. Documented in `docs/scheduler/ITERATION_CEILING.md`.

`MAX_ITERATIONS = 5_000_000`. K* (the iteration count where mean
improvement < stdev) was not met within 10K–5M tested range and is
documented as "above 5M, not found." Practical ceiling is 5M because
single-trial wall-clock above that is impractical for interactive use.

---

## Competition-approved compliance

A schedule is **competition-approved** if and only if it was generated
with the FRC §10.5.2 default algorithm settings:

```python
FRC_DEFAULTS = {
    "rb_post_pass":      True,
    "station_post_pass": True,
    # ... see app/frc_compliance.py for the full list
}
```

Cooldown is intentionally NOT a deviation. Per FRC, cooldown varies by
event size, so it's editable but logged in the audit trail.

The Generate form has a green checkbox "Competition Approved (FRC §10.5.2
defaults)". Editing any algorithm toggle automatically unchecks the box
and turns the banner yellow with a deviation list. Re-checking the box
opens a confirmation modal that resets all toggles to defaults.

The audit trail (stored in `assigned_schedules.audit_trail` JSONB) records:
- Settings actually used
- FRC defaults at generation time (snapshot — defaults can evolve)
- Deviations (human-readable strings)
- Cooldown audit (value used, FRC default, note about variance by event size)
- Iteration count + preset used
- Schema version

The badge in the saved-schedules list and the banner on `/view/{id}`
both reflect this state and link to the audit modal showing full
forensics.

---

## What this replaced

Earlier versions of this document used a P1–P10 priority numbering with
weighted-sum scoring. That ordering predates the FRC §10.5.2 paramount
work. It's been retired — the lex tuple is now the single source of
truth.

The legacy weighted-sum scorer (`score_schedule` returning a float) is
preserved for UI/CSV/DB display where a single number is convenient,
but **all SA accept-reject decisions and all best-of-N comparisons use
the lex tuple**. The summary float should not be trusted to compare two
schedules — it can disagree with the lex compare in trade-off cases.

The browser-side scheduler in `static/index.html:8689` still uses the
old weighted-sum. It builds the abstract; the Python SA on `/assign`
fixes what the weighted-sum left suboptimal. Eventual cleanup to retire
the browser scheduler is tracked in `docs/HANDOFF.md` §5.1.

---

## References

- `docs/scheduler/FRC_COMPLIANCE.md` — full audit trail spec
- `docs/scheduler/ITERATION_CEILING.md` — iteration sweep + K* analysis
- `docs/scheduler/QUALITY_IMPROVEMENT_PLAN.md` — phase-by-phase plan
- `tests/phase0a_lex/SUMMARY.md` — lex score conversion
- `tests/phase0b_cooldown/SUMMARY.md` — hard cooldown filter
- `tests/phase0c_targeted/SUMMARY.md` — targeted move generator
- `tests/phase1_rb/SUMMARY.md` — R/B post-pass
- `tests/phase2_station/SUMMARY.md` — Sykes station post-pass
- `tests/iteration_sweep/2026mnst_30trials_analysis.txt` — sweep data
