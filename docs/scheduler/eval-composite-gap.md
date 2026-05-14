# Eval composite gap investigation — frc-scheduler-server vs matchmaker

**Investigation date:** 2026-05-14
**Status:** Adapter fix shipped; two residual algorithmic questions documented
**Relates to:** Bug A resolution (`docs/scheduler/EVAL_FINDINGS.md`)

---

## Summary

After Bug A (`Fixture.total_matches` off-by-one) was resolved, the eval
re-run on three MN regional fixtures showed:

| Adapter | Mean composite |
|---|---|
| frc-scheduler-server | 46.97 |
| matchmaker (the reference scheduler) | **27.00** |
| Gap | 20 |

Investigation reveals the gap is **mostly an adapter configuration
issue**, with two residual algorithmic concerns documented for the
Best Possible Schedule workstream.

## The gap broken down

Per-metric comparison on 2023mnmi (61t × 9 MPT, representative):

| Metric | Ours | MM | Cause |
|---|---|---|---|
| repeat_partners | 0 ✓ | 0 ✓ | tied |
| max_partner_repeats | 1 ✓ | 1 ✓ | tied |
| repeat_opponents | 16 ✓ / 31 ✗ / 44 ✗ | 14 / 20 / 16 ✓ | adapter→algorithm |
| max_opponent_repeats | 2 ✓ | 2 ✓ | tied |
| max_color_imbalance | 3 ✗ | 4 ✗ | both poor |
| max_station_spread | 5/3/4 ✗ | 1 ✓ | adapter + metric def |
| min_match_gap | 3 ✗ | 7/6/5 ✓ | **adapter** |
| back_to_back | 0 ✓ | 0 ✓ | tied |

Three metrics drove the 20-point gap:

1. **min_match_gap (10 points × 3 fixtures)** — adapter passed
   `ideal_gap=3` (hardcoded). MM auto-computes the maximum feasible
   gap from fixture geometry. **Pure adapter issue.**

2. **max_station_spread (10 points × 3 fixtures)** — adapter didn't
   enable the CP-SAT post-pass; the SA-only path leaves max spread
   at 3-5 on these fixtures. **Partially adapter, partially metric
   definition.**

3. **max_color_imbalance (~3 points × 3 fixtures)** — same root
   cause as #2: CP-SAT R/B post-pass closes this from 3 to 1.

## Fixes shipped

`scripts/scheduler_eval/adapters/frc_scheduler_server.py`:

1. **`ideal_gap` becomes fixture-aware.** Default behavior computes
   `cooldown_max - 4` from the fixture (matching MM's empirical
   heuristic exactly: 51×9→5, 55×9→6, 61×9→7). Explicit override
   still supported via the `ideal_gap=` kwarg.

2. **CP-SAT post-pass enabled by default.** The adapter now passes
   `cpsat_post_pass_budget_s=120` to `generate_matches`. This is the
   "Thorough" UI preset — 120 seconds total budget split 10% R/B +
   90% station. Predicted overhead per fixture: 60-120 seconds wall
   time. Override via `cpsat_post_pass_budget_s=` kwarg (pass 0 to
   opt out).

3. **Diagnostic enrichment.** Adapter now records both `ideal_gap`
   and `ideal_gap_source` ("fixture_floors.cooldown_max" or
   "override=N") plus `cpsat_post_pass_budget_s` in
   `Schedule.adapter_diagnostics`. Makes per-run audit cleaner.

## Predicted post-fix metrics (validated locally at 500K SA + 120s CP-SAT)

| Fixture | min_gap | max_station_spread (6-pos) | max_color |
|---|---|---|---|
| 51×9 | 5 (was 3) | 1 (was 4) | 1 (was 3) |
| 55×9 | 6 (was 3) | 1 (was 3) | 1 (was 3) |
| 61×9 | 7 (was 3) | 1 (was 5) | 1 (was 3) |

All three metrics now hit "near-optimal" under the framework's
6-position station metric. Predicted harness composite drop: ~17
points per fixture, closing most of the 20-point gap to MM.

## Residual algorithmic questions

The adapter fix doesn't close the gap entirely. Two issues remain:

### Question 1: Opponent diversity regression with higher gap

When ideal_gap goes from 3 → 5/6/7, opponent diversity gets worse:

| Fixture | repeat_opponents (gap=3) | repeat_opponents (post-fix) |
|---|---|---|
| 51×9 | 44 | **76** |
| 55×9 | 31 | **71** |
| 61×9 | 16 | **92** |

The constrained-er construction trades opponent variety for gap
satisfaction. `max_opponent_repeats` also goes 2 → 3 across all
three fixtures.

Possible causes:
- The SA's weights favor gap over opponent-pair diversity at high
  gap. Weights tuning could rebalance.
- The construction phase's greedy choices become more deterministic
  at high gap, leaving less room for opponent-spread.
- This may be an architecture-level limitation that needs CP-SAT
  construction (not just CP-SAT post-pass) to address.

This is captured for the Best Possible Schedule workstream Phase 1
Q4 (CP-SAT single-stage for tight fixtures).

### Question 2: Harness's station metric differs from framework's

The harness measures `max_station_spread` across **3 positions**
(R1/B1 combined as "position 1", etc.) while the framework measures
**6 positions** (R1/R2/R3/B1/B2/B3 separately):

```python
# Harness (scripts/scheduler_eval/metrics.py:station_spread)
for color in ("blue", "red"):
    for pos, team in enumerate(alliance, start=1):  # 1, 2, 3
        station_counts[team][pos] += 1
# Combines red + blue contributions at same position index

# Framework (app/quality_floors.py + app/quality_report.py)
for i, t in enumerate(m.red):     # R1, R2, R3 → indices 0,1,2
    pos_counts[t][i] += 1
for i, t in enumerate(m.blue):    # B1, B2, B3 → indices 3,4,5
    pos_counts[t][3+i] += 1
# 6 separate positions
```

Our CP-SAT post-pass optimizes the 6-position metric (achieving
spread=1 on all five canonicals). The 3-position metric is a
DIFFERENT objective that we don't directly optimize for.

MM uses Caleb Sykes' station-balancing algorithm
(https://idleloop.com/matchmaker/stations.php) which appears to
optimize the 3-position metric.

Two possible resolutions:
a) Add a 3-position-equivalent CP-SAT post-pass to our scheduler.
b) Argue that the framework's 6-position metric is more
   FRC-compliant (preserves red/blue distinction explicitly per
   §10.5.2 #6) and the harness threshold should switch.

Resolution requires reading the Sykes paper to understand whether
3-position is the canonical FRC interpretation or just MM's choice.

## Action items follow-up

For HANDOFF roadmap:

- [ ] **Investigate Q1 (opponent diversity regression)** via weights
  tuning experiment. Cheap; could fix half the residual gap.
- [ ] **Resolve Q2 (station metric definition)** by reading Sykes
  paper and either patching the harness threshold or adding a
  3-position post-pass.
- [ ] **Phase D standards re-run** at the new defaults to confirm
  the inventory shapes don't regress. The new adapter applies to
  the eval; production behavior (UI Generate) is unchanged because
  it doesn't go through the adapter.
- [ ] **Validate the adapter fix on Stark** with the full 16-fixture
  inventory.

## Files changed

  - `scripts/scheduler_eval/adapters/frc_scheduler_server.py` —
    fixture-aware `ideal_gap`, CP-SAT default-on, diagnostic
    enrichment
  - `docs/scheduler/eval-composite-gap.md` (this file) — investigation
    record
  - `docs/HANDOFF.md` — session row
