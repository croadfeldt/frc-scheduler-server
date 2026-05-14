# Exact CP-SAT Post-Passes

**Module:** `app/post_passes/cpsat_post_passes.py`
**Producer integration:** `scripts/scheduler_eval/build_canonical.py --cpsat-post-pass-budget`
**Experiment harness:** `scripts/cpsat_budget_sweep.py`
**Tests:** `tests/test_cpsat_post_passes.py`

---

## Why exact post-passes

The R/B balance and station balance post-passes operate on tightly
constrained subspaces:

- **R/B**: only varies which alliance is "red" vs "blue" per match
  (1 bit per match, M bits total). Provably preserves partner pairs,
  opponent pairs, station-within-alliance distribution, cooldown,
  B2B, and surrogate counts.

- **Station**: only varies the within-alliance permutation of teams
  (one of 6 permutations of S_3 per alliance, 2M alliances total).
  Provably preserves partner pairs, opponent pairs, cooldown, B2B,
  surrogate counts.

Both subproblems are small ILPs that CP-SAT handles well: R/B in
seconds even on 60×12, station in 5-60 seconds depending on fixture
size.

The SA-based versions of these post-passes (`rb_balance_sa`,
`station_balance_sa`) work well most of the time but plateau on a
meaningful fraction of seeds. Empirical sweep at 100K SA upstream
iterations:

| Fixture | Runs where CP-SAT beats SA | Notable gap |
|---|---|---|
| 12×6  | 0 / 5 | none |
| 20×8  | 2 / 5 | +2.8, +5.6 composite points |
| 24×8  | 0 / 5 | none |
| 36×7  | 3 / 5 | +5.6 × 3 |
| 60×12 | 1 / 5 | +2.8 |

CP-SAT never loses. It strictly improves on SA in ~25% of runs at
modest upstream SA budgets.

## API

```python
from app.post_passes.cpsat_post_passes import (
    rb_balance_cpsat, station_balance_cpsat,
)

# R/B: ~10% of total budget is reasonable (small subproblem)
new_matches, rb_stats = rb_balance_cpsat(matches, time_budget_s=30)

# Station: ~90% of total budget (larger subproblem)
final, st_stats = station_balance_cpsat(new_matches, time_budget_s=270)
```

Both functions return `(matches, stats)` where `stats` includes:

- `status`: `OPTIMAL` / `FEASIBLE` / `UNKNOWN` / etc
- `wall_time_s`: actual solver wall time (≤ budget)
- `max_before` / `max_after`: pre- and post-solver max imbalance/spread
- `sum_before` / `sum_after`: same for L1 sum (tiebreak objective)
- `n_flips` (R/B) or `n_permutations` (station): how much was applied

### Safe fallback on UNKNOWN

If the solver times out without finding any feasible solution (status
UNKNOWN), the input is returned unchanged. The "identity" assignment
(no flips, no permutations) is always feasible, so UNKNOWN is rare —
usually a sign the budget is too tight for the fixture.

Callers should treat UNKNOWN as "use the SA result instead" rather
than failing the generation.

## Budget guidance

The empirical sweep (`scripts/cpsat_budget_sweep.py`) tested 5
fixtures × 5 budgets. Findings:

- **All five standards-inventory fixtures reach composite=100 at a
  60-second total CP-SAT budget** (R/B 6s + station 54s).
- **60×12 needs ~12-17 seconds of CP-SAT solver time** at 60-second
  budget; the budget cap means 12-17s actual.
- Longer budgets (300s, 900s) don't improve quality — they just let
  CP-SAT prove OPTIMAL where it currently returns FEASIBLE.

| Total budget | Coverage |
|---|---|
| 10 sec   | OK on small (12×6, 20×8, 24×8) |
| 60 sec   | OK on all 5 inventory fixtures; composite=100 |
| 300 sec  | Reaches OPTIMAL status on 60×12 R/B |
| 900-3600 sec | Reserved for larger fixtures (e.g. 80+ teams) |

The maximum allowed budget is `MAX_BUDGET_SECONDS = 3600` (1 hour).
Larger requests are clamped with a warning.

### Default budgets

- `DEFAULT_BUDGET_SECONDS = 300` — used when callers don't specify
- Canonical producer (`build_canonical.py`): `--cpsat-post-pass-budget`
  defaults to 600s, split 10% R/B + 90% station
- Experiment harness: pass `--budgets 10,60,300,900` to characterize

## Where this gets used

### Production: canonical library curation

```bash
python3 scripts/scheduler_eval/build_canonical.py \
    --shape 36x7 --cooldown 2 \
    --sa-iterations 200000 --n-seeds 3 \
    --cpsat-post-pass-budget 300
```

The SA-best-of-N runs first (each seed gets cheap SA post-passes
for selection signal). The chosen winner then gets CP-SAT polish at
the given budget. The polished result is what ends up in the
canonical JSON file in `app/canonical_schedules/`.

Every cache hit in production serves a CP-SAT-polished canonical.

### Live interactive generation

`generate_matches()` accepts `cpsat_post_pass_budget_s: float = 0.0`
(default off for backwards compatibility). When positive, the function
runs SA construction + SA optimization + SA post-passes as usual, then
applies CP-SAT polish on the result. Budget split: 10% R/B, 90%
station.

The API request bodies for the live-generation endpoints carry the
field:

- `POST /api/generate-abstract` (legacy, SSE): `cpsat_post_pass_budget_s`
- `POST /api/schedules` (unified): `cpsat_post_pass_budget_s`

Pydantic validates `0 ≤ budget ≤ 3600`. The worker dispatches both
SA and CP-SAT phases; SSE `phase` event is emitted before the worker
starts so the UI can show appropriate progress copy:

```
data: {"type":"phase","phase":"sa+cpsat_polish","cpsat_budget_s":300}
```

The progress label updates: "Generating schedule, then CP-SAT polish
(up to 5 min)…" so the user knows the wait is expected.

The UI's Generate panel includes a "Quality polish" picker:

- **Off (default)** — SA only. Fastest. Use this for quick iteration.
- **Quick polish (~60s)** — Reliable composite=100 on most fixtures.
- **Thorough (~5 min)** — Recommended for 30+ team fixtures.
- **Deep (~15 min)** — Gives CP-SAT room to prove optimal on large fixtures.
- **Maximum (~60 min)** — For results that will be cached and shared.
- **Custom…** — 1-3600 seconds.

The hint text under the picker updates as the user selects, surfacing
the expected wall-time impact.

### Operational consideration: OpenShift route timeout

`openshift/05-route.yaml` carries `haproxy.router.openshift.io/timeout:
4000s`. This MUST exceed the maximum CP-SAT budget (3600s) plus
upstream SA wall time, otherwise haproxy will kill the SSE stream
mid-solve. The SSE keep-alive pings keep TCP alive but haproxy's
timeout is wall-clock-based, not idle-based.

If you bump `MAX_BUDGET_SECONDS` above 3600 in the future, bump the
route timeout correspondingly. Headroom of 5-10% over the budget
cap is sufficient.

### Auditability

Schedules generated with CP-SAT polish have the budget recorded in
their `creation_provenance` JSONB column:

```json
{
  "method": "sa_generated",
  "sa_iterations": 500000,
  "sa_weights": null,
  "seed": "abc123",
  "cpsat_post_pass_budget_s": 300,
  "created_via": "POST /api/schedules (generate)"
}
```

Canonical library entries built via the producer have the more
detailed `cpsat_post_pass` block (status, wall time, before/after
imbalances) — see the producer integration section above.

### Experiment harness

```bash
python3 scripts/cpsat_budget_sweep.py \
    --fixtures 12x6,20x8,24x8,36x7,60x12 \
    --budgets 10,60,300,900 \
    --seeds 5 \
    --sa-iterations 100000
```

Writes a JSON report to `scripts/scheduler_eval/reports/cpsat_sweep_*.json`
with full per-run data. Useful for re-baselining when scoring curves
change or new fixtures are added to the inventory.

## Model details

### R/B model

Variables: `flip[m]` ∈ {0, 1} for m ∈ [0, M).

For each team t:
- `red_after_t = base_t + Σ_m (is_blue[t][m] - is_red[t][m]) * flip[m]`
- `delta_t = 2 * red_after_t - MPT_t`
- `abs_delta_t = |delta_t|`

Objective: `minimize W * max_t(abs_delta_t) + Σ_t(abs_delta_t)`
where W exceeds the maximum possible sum. This is a lex-tuple
(max, sum) minimization — the max term dominates, sum is a tiebreak.

Solver: CP-SAT with `max_time_in_seconds = budget`,
`num_search_workers = 8`. Parallelism helps prove optimality faster.

### Station model

Variables: for each alliance a ∈ [0, 2M), one of 6 binary `perm[a][k]`
with `AddExactlyOne` constraint.

For each (team t, position p):
- `cnt[t][p] = Σ (perm[a][k] for all (a, k) where σ_k places t at p)`

For each team:
- `spread_t = max_p(cnt[t][p]) - min_p(cnt[t][p])`

Objective: `minimize W * max_t(spread_t) + Σ_t(spread_t)`

Position indexing: 0/1/2 = R1/R2/R3, 3/4/5 = B1/B2/B3. Permutations
within an alliance only move teams among the 3 positions of that
alliance's color — never across red↔blue.

## Outcome

The five canonicals in `app/canonical_schedules/` were rebuilt with
CP-SAT polish (2026-05-13). All five now score composite=100 under
the framework. Cache hits in production serve these polished entries.

Future work:

1. **Larger fixtures** — 80+ teams may need >60s budgets to reach
   OPTIMAL; characterize on Stark.
2. **Upstream SA improvements** — the post-pass solvers can't help
   with par_quad/opp_quad gaps. The 20×8 fixture's 99.4 ceiling at
   100K SA suggests upstream optimization is the next bottleneck.
3. **Cancellation** — currently if the browser closes mid-solve,
   the worker thread keeps running until done (result discarded).
   CP-SAT supports interruption via `StopSearch()`; wiring this is
   straightforward but requires a way to signal from the async
   request handler to the executor thread (e.g., a shared
   threading.Event).
