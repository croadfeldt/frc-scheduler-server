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

# 2. Verify the metrics module is correct (compares against the
#    reviewer's hand-verified numbers for 2026mnst):
python3 scripts/scheduler_eval/smoke_test.py
# Expected: "All checked metrics match the reviewer's numbers."

# 3. Pull the curated fixture inventory from TBA:
python3 -m scripts.scheduler_eval.pull_tba_fixtures \
    --keys-file scripts/scheduler_eval/event_keys.txt
# This pulls ~16 events from 2023-2026, varied team counts and
# event tiers. Skips events already on disk; pass --overwrite to
# re-fetch.

# 4. Recommended: run our scheduler against the actual played
#    schedules from TBA. This is the primary validation surface
#    for ongoing scheduler-improvement work — license-clean,
#    suitable for CI:
python3 -m scripts.scheduler_eval.runner \
    --fixtures all \
    --adapters frc-scheduler-server,actual \
    --trials 50 \
    --workers 36
```

### Optional: occasional manual MatchMaker evaluation

For one-off ceiling-calibration runs (a few times a year as needed),
you can invoke the matchmaker adapter to characterize the absolute
quality ceiling. **Do not run this in CI** — see `NOTICE.md` for
the licensing posture.

```bash
# Install MatchMaker manually, under your own evaluation license
# with Idle Loop. Three ways for the harness to find it:
#   a. Drop the binary on $PATH (e.g. /usr/local/bin/matchmaker)
#   b. export MATCHMAKER_BINARY=/path/to/matchmaker
#   c. pass --matchmaker-binary /path/to/matchmaker per-run
which matchmaker

# Run the three-way comparison
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

| Adapter                | Status | Recommended use |
|---|---|---|
| actual (CSV / TBA)     | ✓ working | **Primary validation surface.** Use for ongoing scheduler-improvement validation, regression detection, and CI. TBA fetcher uses `app.tba` client; needs `TBA_API_KEY` env var. |
| frc-scheduler-server   | ✓ working | Our scheduler under test. Wraps `app/scheduler.py`. |
| matchmaker             | ✓ working, **evaluation-only** | Wraps Idle Loop's externally-installed MatchMaker binary. **Do not use in CI or automated pipelines** — see `NOTICE.md`. Appropriate for occasional manual evaluation runs to recalibrate the absolute quality ceiling. |
| cp-sat                 | ⏸ Phase 3 | not built yet |

**Validation strategy:** for ongoing scheduler-improvement work, prefer
the `actual` adapter alone. It compares our scheduler against publicly-
available played FRC schedules (which were generated by MatchMaker via
FMS for most events), giving us a license-clean continuous validation
surface. The `matchmaker` adapter is for occasional manual evaluation
to characterize the absolute quality ceiling — run it a few times a
year as needed, not on every commit.

See `NOTICE.md` in this directory for the full licensing posture.

## Fixture format

Each fixture is a JSON file in `fixtures/`:

```json
{
  "fixture_id": "2026mnst",
  "name": "2026 MN State Tournament",
  "teams": [4674, 11283, 2530, ...],
  "matches_per_team": 7,
  "teams_per_alliance": 3,
  "surrogate_first_match": null,
  "surrogate_count": 0,
  "source": "live",
  "year": 2026,
  "event_key": "2026mnst",
  "notes": "..."
}
```

Add a fixture by writing a new JSON file, or pull from TBA via
`pull_tba_fixtures.py`.

The two surrogate fields are descriptive metadata about the actual
played schedule — they don't influence what gets passed to scheduling
adapters. MatchMaker handles surrogate placement itself (default
round 3 since 2008 per FIRST's convention).

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
