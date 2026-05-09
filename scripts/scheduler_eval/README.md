# Scheduler Evaluation Harness

A framework for comparing scheduling algorithms across FRC event
configurations. Runs every `(fixture × adapter × trial)` combination
and produces a Markdown report with the metrics that matter.

## What this is

Phase 1 of a scheduler evaluation effort to answer: **does our
in-house scheduler produce schedules that are competitive with the
established FRC scheduling tools?** If not, we replace it with one
that does — possibly by simply importing MatchMaker output, possibly
by writing a CP-SAT-based replacement, possibly by keeping ours but
fixing what's wrong.

Decisions are data-driven. The harness produces the data.

## What's in here

```
scripts/scheduler_eval/
├── README.md                 ← this file
├── harness_types.py          ← Fixture, Match, Schedule definitions
├── metrics.py                ← all quality metrics + thresholds
├── runner.py                 ← orchestrator
├── smoke_test.py             ← validates metrics against reviewer's numbers
├── adapters/
│   ├── base.py               ← Adapter abstract class
│   ├── actual.py             ← reads CSV / pulls TBA
│   ├── matchmaker.py         ← wraps Idle Loop's matchmaker binary
│   └── frc_scheduler_server.py  ← wraps app/scheduler.py
├── fixtures/
│   └── 2026mnst.json         ← the live event (reviewer's baseline)
└── reports/
    └── <run-id>/             ← outputs
```

## Quickstart on Stark

```bash
# 1. Set TBA API key (needed for fixture fetching)
export TBA_API_KEY=your_key_here

# 2. Install MatchMaker. Three ways for the harness to find it
#    (any one is sufficient):
#      a. Drop the binary on $PATH (e.g. /usr/local/bin/matchmaker) — preferred
#      b. export MATCHMAKER_BINARY=/path/to/matchmaker
#      c. pass --matchmaker-binary /path/to/matchmaker per-run
which matchmaker      # confirms (a); silent fail is fine if using (b) or (c)

# 3. Verify the metrics module is correct (compares against the
#    reviewer's hand-verified numbers for 2026mnst):
python3 scripts/scheduler_eval/smoke_test.py
# Expected: "All checked metrics match the reviewer's numbers."

# 4. Pull the curated fixture inventory from TBA:
python3 -m scripts.scheduler_eval.pull_tba_fixtures \
    --keys-file scripts/scheduler_eval/event_keys.txt
# This pulls 15-20 events from 2023-2026, varied team counts and
# event tiers. Skips events already on disk; pass --overwrite to
# re-fetch.

# 5. Run our scheduler against the actual played schedules across
#    every fixture you've pulled:
python3 -m scripts.scheduler_eval.runner \
    --fixtures all \
    --adapters frc-scheduler-server,actual \
    --trials 50 \
    --workers 36

# 6. Once MatchMaker is verified working, add it to the comparison.
#    If the binary is on $PATH or pointed at via MATCHMAKER_BINARY,
#    no --matchmaker-binary flag is needed:
python3 -m scripts.scheduler_eval.runner \
    --fixtures all \
    --adapters frc-scheduler-server,matchmaker,actual \
    --trials 100 \
    --workers 36
```

Reports land in `scripts/scheduler_eval/reports/<run-id>/report.md`.

## Pulling fixtures from TBA

The `pull_tba_fixtures.py` script handles fixture import:

```bash
# Single event
python3 -m scripts.scheduler_eval.pull_tba_fixtures 2024mnst

# Multiple events from a file (one key per line, '#' for comments)
python3 -m scripts.scheduler_eval.pull_tba_fixtures \
    --keys-file scripts/scheduler_eval/event_keys.txt

# Every event in a year, optionally filtered by state
python3 -m scripts.scheduler_eval.pull_tba_fixtures --year 2024 --state MN

# Force re-fetch of existing fixtures
python3 -m scripts.scheduler_eval.pull_tba_fixtures 2024mnst --overwrite
```

For each event, two files land in `fixtures/`:

- `{event_key}.json` — the Fixture (input description: teams, matches per team)
- `{event_key}__actual.json` — the played schedule (what FRC actually ran)

The runner detects pre-pulled actual schedules automatically — when
you run `--adapters actual` on a fixture with a sibling `__actual.json`,
the runner loads it from disk rather than re-fetching from TBA.

The `event_keys.txt` file in this directory has a curated list of
events worth pulling: MN events 2023-2026, mid-size FRC regionals,
larger fields, district championships, and small offseason events.
About 20 events covering a wide range of team counts (24-100+) and
event tiers.

## Adapter status

| Adapter                | Status | Notes |
|---|---|---|
| actual (CSV)           | ✓ working | reviewer-format CSV import |
| actual (TBA)           | ✓ working | uses app.tba client; needs TBA_API_KEY env var |
| frc-scheduler-server   | ✓ working | wraps app/scheduler.py; tested on 2026mnst |
| matchmaker             | ⚠ untested on real binary | CLI flags + parser are best-guess from release notes; will need adjustment on first run |
| cp-sat                 | ⏸ Phase 3 | not built yet |

The MatchMaker adapter should work but the exact CLI flag names and
output format are inferred from the 1.6.1 release notes rather than
from running the binary. First run on Stark will require:

1. Run `matchmaker --help` and check the actual flag names match
   what `_build_command` in `adapters/matchmaker.py` produces.
2. Run a single fixture and verify the parser handles the output
   format. If it doesn't, capture a sample of stdout and update
   `_parse_output` in the adapter.

The adapter has a `probe_help()` method for the first step. Once
MatchMaker output is captured for one run, fixing the parser is
mechanical.

## Fixture format

Each fixture is a JSON file in `fixtures/`:

```json
{
  "fixture_id": "2026mnst",
  "name": "2026 MN State Tournament",
  "teams": [4674, 11283, 2530, ...],
  "matches_per_team": 7,
  "teams_per_alliance": 3,
  "surrogate_round": null,
  "source": "live",
  "year": 2026,
  "event_key": "2026mnst",
  "notes": "..."
}
```

Add a fixture by writing a new JSON file. Fixtures pulled from TBA
will be auto-generated when the TBA fetcher is implemented (Phase 2).

## Metrics

All metrics are in `metrics.py`. Each is a standalone function — easy
to test in isolation, easy to extend.

The threshold dictionary in `metrics.py` has two tiers per metric:
**near-optimal** (what good FRC schedules achieve) and **acceptable**
(what FRC standards consider minimum-acceptable). Schedules that fall
below acceptable on any metric are flagged "poor" overall.

Thresholds are calibrated from:
- The reviewer's MatchMaker baseline (800 trials, 36-team field)
- FRC community norms (station spread of 1, no back-to-backs)
- The 2026mnst reference — our metrics module is verified to produce
  the reviewer's exact numbers on that schedule

## Methodology

### Stochastic adapters and best-of-N

MatchMaker, our scheduler, and CP-SAT are all stochastic — different
seeds produce different schedules. The harness runs N trials per
adapter per fixture and reports the BEST.

"Best" is defined as: fewest `poor` metrics, breaking ties by most
`near_optimal` metrics, then by repeat-partner count, then by color
imbalance.

For honest comparisons, set `--trials` consistently across adapters.
Comparing "best of 1000 MatchMaker runs" to "best of 5 our-scheduler
runs" is unfair to ours.

### Surrogate handling

Surrogate slot-fills are tracked but excluded from repeat-partner /
repeat-opponent statistics. A surrogate is a team filling in for
capacity reasons — they're physically at the alliance station so
color and station balance count them, but they're not playing
competitively so partner / opponent diversity ignores them.

This matches MatchMaker's convention.

### Validation against reviewer's analysis

The smoke test (`smoke_test.py`) loads the 2026mnst CSV and runs every
metric. It compares against the numbers verified independently in
earlier sessions:

- 9 repeat partners ✓
- 33 repeat opponents ✓
- 1 pair facing 3 times (2169 × 4728) ✓
- 3 teams at 6/7 on Red (2052, 5653, 6045) ✓
- max color imbalance 5 ✓
- 10 teams with 5+ on one color ✓
- station spread of 3 across 4 teams ✓
- min gap of 3 across 2 teams (2847, 5348) ✓

If any of these numbers change, the metrics module has a regression.
The smoke test is a guard.

## Phase 2 work

Not yet done; the harness foundation is enough for the immediate
question (does our scheduler produce competitive results on 2026mnst).
Phase 2 expands the fixture inventory:

- TBA fetcher in `adapters/actual.py`
- 15-20 historical FRC events from 2023-2026
- 8-10 synthetic edge-case fixtures (24/48/60/72 teams, multi-day, etc.)
- Cross-fixture aggregate ranking in reports

Phase 3 adds the CP-SAT adapter for "is there a better algorithmic
foundation than the heuristic search both ours and MatchMaker use."

## When to look at this vs the running app

This harness is **completely separate** from the running app. It
shares `app/scheduler.py` (because that's what one of the adapters
wraps) but never modifies it. The change-freeze on the production
scheduler stays in effect.

Running the harness is read-only. Nothing in the database or
production state changes.
