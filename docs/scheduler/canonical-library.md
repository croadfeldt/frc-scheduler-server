# Canonical Schedule Library — Phase B of the Schedule Quality Framework

**Module:** `app/canonical_library.py`
**Producer:** `scripts/scheduler_eval/build_canonical.py`
**Storage:** `app/canonical_schedules/*.json`
**Tests:** `tests/test_canonical_library.py`

## What this is

A library of pre-computed best-known schedules for common FRC fixture
shapes. When an organizer requests a schedule for a covered shape,
they get the canonical schedule instead of waiting for the SA to
generate one fresh. Quality is deterministic per shape — the same
shape always returns the same schedule.

This is **Phase B** of the Schedule Quality Framework v1.0
(`docs/workstreams/schedule-quality-framework.md`). Phase A
(theoretical floors) is in `app/quality_floors.py`. Phase C
(per-criterion 1-100 scoring) and Phase D (standing eval suite)
follow.

## How it fits

```
                    ┌───────────────────────────────────┐
                    │  POST /api/schedules              │
                    │  (new unified endpoint, Phase B)  │
                    └───────────────┬───────────────────┘
                                    │
                  ┌─────────────────┼─────────────────────┐
                  │                 │                     │
        ┌─────────▼────────┐  ┌─────▼───────┐   ┌─────────▼──────┐
        │ canonical_library│  │  generated  │   │   imported     │
        │  (lookup by      │  │  (SA-fresh) │   │ (caller-       │
        │   fixture shape) │  │             │   │  supplied      │
        │                  │  │             │   │  matches +     │
        │                  │  │             │   │  source_url)   │
        └─────────┬────────┘  └─────┬───────┘   └──────┬─────────┘
                  │                 │                   │
                  │  source field   │                   │
                  └────────┬────────┴───────────────────┘
                           │
                  ┌────────▼─────────┐
                  │  abstract_schedules │
                  │  row with:          │
                  │   source            │
                  │   source_url        │
                  │   quality_report    │
                  └──────────────────┘
```

The existing `POST /api/generate-abstract` (SSE-streaming, used by
the UI's Generate button) is preserved for now; eventually it'll be
replaced by the unified endpoint or be a thin wrapper around it.

## File format

Each canonical lives in `app/canonical_schedules/` as a JSON file
named `{n}x{mpt}x{tpa}_cd{cooldown}.json`. For example,
`36x7x3_cd2.json` is the canonical for 36-team × 7-MPT × 3-per-alliance
× cooldown=2.

Structure:

```json
{
  "n_teams": 36,
  "matches_per_team": 7,
  "teams_per_alliance": 3,
  "cooldown": 2,
  "confidence": "best_known",
  "matches": [
    {"red": [...], "blue": [...],
     "red_surrogate": [...], "blue_surrogate": [...]},
    ...
  ],
  "achieved_lex_tuple": [0, 252, 462, 0, 36, 36, 0, 0],
  "quality_report": { ... full report ... },
  "provenance": {
    "method": "sa_best_of_n",
    "sa_iterations": 100000,
    "n_seeds": 3,
    "successes": 3,
    "failures": 0,
    "best_seed": 30000,
    "wall_clock_s": 13.4,
    "generated_at": "2026-05-13T03:37:00-05:00",
    "git_commit": "abc1234"
  }
}
```

The `quality_report` is the same structure built by
`app.quality_report.build_quality_report()` — per-metric value,
floor, distance-from-floor, floor confidence, and matches_floor flag.

## Confidence labels

Each canonical entry has a `confidence` field (separate from the
floor confidence on individual metrics):

- **`proven_optimal`**: schedule was produced by an exhaustive
  solver (CP-SAT optimality proof). Reserved for future use — the
  current producer uses SA-best-of-N, which doesn't produce
  optimality proofs.

- **`matches_floor`**: the schedule matches the theoretical floor
  on *every* metric (including the `proven_lower_bound` floors for
  par_quad and opp_quad). Even without a CP-SAT proof, we know the
  schedule is mathematically optimal under the known lower bounds.

- **`best_known`**: the schedule is the best found via the producer's
  search budget. The true mathematical minimum may be lower; future
  re-curation with bigger budgets may find better.

## Current library contents (v1.0 proving inventory)

5 canonicals built at SA × 100,000 iterations × 3 seeds:

| File | Confidence | Achieved par_quad | Floor | Notes |
|---|---|---:|---:|---|
| `12x6x3_cd2.json`  | best_known | 192 | 84   | Cooldown=2 forces two-track structure; floor not achievable |
| `16x6x3_cd2.json`  | (not built) | — | — | Phase B follow-up |
| `20x8x3_cd2.json`  | best_known | 198 | 160  | Surrogate-required (2 slots) |
| `24x8x3_cd2.json`  | best_known | 198 | 192  | Close but doesn't hit floor at 100K iter |
| `36x7x3_cd2.json`  | best_known | 252 | 252  | par_quad floor matched; opp_quad still above |
| `60x12x3_cd2.json` | best_known | 720 | 720  | par_quad floor matched; large fixture |

## Building canonicals

```
python3 scripts/scheduler_eval/build_canonical.py \\
    --shape 36x7 --cooldown 2 \\
    --sa-iterations 500000 --n-seeds 5
```

For higher quality (Stark territory), increase `--sa-iterations` and
`--n-seeds`. Production-quality target is 500K-2M iterations × 20+
seeds per shape. The current v1.0 build is at lower budgets to fit
the prototyping session; future re-curation on Stark will replace
these.

## Future work

- **Higher-budget re-curation**: re-build each canonical at Stark
  with 2M-5M iterations × 100+ seeds. Most current `best_known`
  entries will become `matches_floor` (or stay `best_known` if the
  floor is structurally unachievable, e.g. 12×6 cd=2).

- **CP-SAT producer mode**: for small fixtures where CP-SAT can
  prove optimality at reasonable budget. Would let us upgrade
  matching entries to `proven_optimal`.

- **Tighter floors for cooldown-constrained shapes**: 12×6 cd=2 has
  par_quad floor=84 but achievable=192 due to structural constraints.
  A tighter floor derivation would let the canonical report
  `matches_floor` correctly.

- **DB-backed library**: per `docs/workstreams/abstract-library.md`,
  the long-term home for these is a Postgres table. The JSON-file
  storage here is the prototype/seed for that migration; the file
  format maps cleanly onto the table schema.

- **More shapes**: v1.0 covers 5 shapes (the proving inventory).
  v1.1 expands to the full ~27-shape FRC plausible-shape inventory
  (12×6, 16×6, 20×8, 24×6, 24×8, 24×12, 32×12, 36×7, 36×10, 36×12,
  40×12, 42×11, 48×12, 50×12, 51×9, 54×12, 60×12, 72×10, 72×12,
  80×10, 80×12, plus variants).

## Endpoints

- `POST /api/schedules` — unified entry. Body specifies fixture
  shape and source_preference; returns a stored abstract schedule
  with source/quality_report fields populated. See module docstring
  in `app/main.py` for the full contract.

- `GET /api/canonical-schedules` — list shapes for which a canonical
  is available. Returns shape + confidence + achieved lex tuple +
  matches_floor flag for each.

- `GET /api/abstract-schedules/{id}` (existing, extended) — now
  returns `source`, `source_url`, `quality_report` fields alongside
  the schedule. NULL on legacy rows.

## UI integration

The Quality card in the editor now renders:

- **Source banner** at the top of the card, showing where the
  schedule came from (canonical_library / generated / imported)
  with optional source URL link.

- **Theoretical floor comparison** as a collapsible section: per-metric
  table with achieved value, floor, distance-from-floor, and
  confidence label. Summary banner indicates how many metrics are
  at-floor.
