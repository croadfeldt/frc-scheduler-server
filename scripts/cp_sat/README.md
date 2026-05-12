# CP-SAT research scripts

Research scripts for the Phase 1 investigation of CP-SAT applicability
to FRC qualification match scheduling. Captured in
[`docs/workstreams/best-possible-schedule.md`](../../docs/workstreams/best-possible-schedule.md)
Q2.

These are **research scripts, not production code**. They don't run in
the production container; they don't have integration with `app/`'s
runtime; they're not tested as part of the regular suite. They exist
to answer specific investigation questions.

## Setup

```bash
pip install -r requirements-research.txt
```

This installs `ortools` (Apache 2.0, ~80MB). Production doesn't need
it.

## Scripts

### `pairing_optimum.py`

CP-SAT formulation for the Stage 1 pairing problem on small fixtures.
Finds provably-optimal `par_quad` (sum of squared partner counts) for
fixture shapes where the solver can terminate.

```bash
python3 scripts/cp_sat/pairing_optimum.py --teams 6 --mpt 4 --cooldown 1 --time-limit 60
```

Use `--time-limit` to bound the solver's wall-clock. `--workers` sets
parallelism (default 8).

First-cut findings: [`docs/scheduler/phase1-q2-first-cut.md`](../../docs/scheduler/phase1-q2-first-cut.md).

## Provenance

All algorithmic ideas implemented here are derived from publicly
documented sources (FRC manual, Saxton white paper, OR-Tools
documentation, CP-SAT modeling literature). No code is copied from
external schedulers. See
[`docs/scheduler/REFERENCE_SCHEDULER_LICENSING.md`](../../docs/scheduler/REFERENCE_SCHEDULER_LICENSING.md)
for the project's broader provenance posture.
