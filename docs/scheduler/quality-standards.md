# Quality Standards — Phase D of the Schedule Quality Framework

**Module:** `scripts/scheduler_eval/standards.py`
**Config:** `scripts/scheduler_eval/standards_config.py`
**Smoke test:** `tests/test_standards_smoke.py`
**Workstream:** Schedule Quality Framework v1.0 — Phase D of A→B→C→D.

This is the **standing eval suite**: a runnable script that asserts the
production scheduler meets per-fixture quality bars across the proving
inventory. It catches regressions and provides a uniform comparison
framework for any candidate scheduling methodology.

---

## How it composes

```
┌─────────────────────────────────────────────────────────────┐
│ Phase A: theoretical floors                                  │
│ Phase B: canonical library + quality_report                  │
│ Phase C: per-criterion scoring + composite                   │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│ Phase D: standing eval                                       │
│   - Runs production scheduler on each fixture, N seeds       │
│   - Scores via Phase C, aggregates to medians                │
│   - Compares to per-fixture bars                             │
│   - Asserts hard requirements, warns on soft thresholds      │
│   - Writes JSON + Markdown reports                           │
└─────────────────────────────────────────────────────────────┘
```

Phases A/B/C built the data. Phase D operationalizes it: the framework
now has a **gate** that says "this scheduler shipping is acceptable
quality" with concrete numerical justification.

---

## The bars

Each fixture has two kinds of bars:

- **Hard requirements** — failures = test fails (exit code 1)
- **Soft thresholds** — failures = warning (exit code 0; promotable to
  hard via `--strict`)

### Default hard requirements (apply to every fixture)

- `is_valid_paramount = True` — cooldown_violations must be 0 across
  all seeds. FRC §10.5.2 paramount; non-negotiable.
- `cooldown_score = 100` — the cooldown criterion score (binary) must
  be 100 across all seeds. Mirrors the paramount requirement.

### Default soft thresholds (apply unless overridden per-fixture)

- `composite_min = 80` — median composite ≥ 80/100
- `per_criterion_min = 50` — each per-criterion median ≥ 50/100

### Per-fixture overrides

Defined in `scripts/scheduler_eval/standards_config.py:PER_FIXTURE_OVERRIDES`.
Each fixture can override soft thresholds (and add notes explaining why).

Example: 12×6 cd=2 has a structural gap on par_quad (count-floor 84 is
unachievable; best-known 192). With best-known floor scoring (the default
in the eval), the bar can stay high since the canonical is its own
best-known. Override sets `composite_min = 85`.

---

## Running

### Full eval (proving inventory, 3 seeds, default iterations)

```
python3 scripts/scheduler_eval/standards.py
```

Wall-clock: depends on iteration count and fixture size. At default
100K iter × 3 seeds × 5 fixtures:
- 12×6: ~3s total
- 20×8: ~8s total
- 24×8: ~10s total
- 36×7: ~50s total
- 60×12: ~3min total

So ~5min for the full default eval.

### Subset of fixtures

```
python3 scripts/scheduler_eval/standards.py --fixtures 12x6_cd2,36x7_cd2
```

### Production-quality iteration budget

```
python3 scripts/scheduler_eval/standards.py --sa-iterations 500000 --seeds 5
```

Mirrors what production runs at (the "best" preset uses 2M iter; 500K
is a reasonable Phase D approximation that still catches regressions
without taking 30+ minutes).

### Strict mode (CI / pre-deploy)

```
python3 scripts/scheduler_eval/standards.py --strict
```

Soft thresholds become hard failures. Use this when integrating with
CI gates.

### Smoke test (quick CI sanity)

```
python3 scripts/scheduler_eval/standards.py --smoke
```

Single fixture, single seed, 5K iter. Fails by design (too few
iterations) but verifies the framework wiring works. Used by
`tests/test_standards_smoke.py`.

---

## Outputs

Each run writes two files to `scripts/scheduler_eval/reports/`:

- **`standards_<timestamp>.json`** — full machine-readable report with
  per-fixture results, per-seed details, bars, verdicts. Suitable for
  CI logging and trend analysis.
- **`standards_<timestamp>.md`** — human-readable summary table +
  detail sections. Suitable for review.

Both contain:
- Overall verdict (pass / warn / fail)
- Per-fixture verdict, median composite, per-criterion medians
- Comparison to canonical (when canonical exists for the shape)
- Hard failures and soft warnings, itemized

---

## Interpreting results

### `pass`
All hard requirements met; all soft thresholds met. Ship it.

### `warn`
All hard requirements met but at least one soft threshold missed.
Production-acceptable but flagged for follow-up. Common at lower
iteration budgets where rb_per_team / station_per_team_spread
post-passes don't reach their proven_optimal floors.

### `fail`
At least one hard requirement missed. Do not ship without
investigation. Likely causes:
- The SA isn't reaching paramount-valid output (cooldown_violations
  > 0). Indicates either insufficient iterations or a bug.
- Canonical comparison shows large drift (production output far
  worse than canonical for the same shape).

---

## Inventory

The proving inventory is the 5 shapes from Phase B's canonical library:

| Fixture | Shape | Notes |
|---|---|---|
| `12x6_cd2`  | 12×6×3 cd=2  | Tight cooldown; structural par_quad gap |
| `20x8_cd2`  | 20×8×3 cd=2  | Surrogate-required (2 slots) |
| `24x8_cd2`  | 24×8×3 cd=2  | Medium fixture |
| `36x7_cd2`  | 36×7×3 cd=2  | 2026mnst production shape |
| `60x12_cd2` | 60×12×3 cd=2 | Largest fixture; SA-only territory |

v1.1+ adds more shapes (full ~27-shape FRC plausible inventory).

---

## Updating bars

Bars are set conservatively based on Phase C observations at 100K SA
iter × 3 seeds. As production scheduling improves (higher iteration
budgets, post-pass tuning, etc.), bars should tighten.

**Workflow for raising bars**:
1. Run the eval at production iteration budget (500K-2M) on Stark
2. Observe median composite + per-criterion medians
3. Update `standards_config.py:PER_FIXTURE_OVERRIDES` with tighter
   bars (e.g., composite_min from 80 to 90)
4. Re-run eval to verify production stays comfortable above the new
   bars
5. Commit the config change

**Workflow for loosening bars** (rare):
Only if a structural finding shows the previous bar was unrealistic.
Document the reason in the per-fixture `notes` field.

---

## Real findings to-date

The eval at 100K iter × 3 seeds surfaces these issues:

1. **rb_per_team post-pass underconverges on large fixtures.** 24×8
   canonical (and freshly-generated) has rb_per_team=4 where the
   proven_optimal floor is 0. Score drops to 0 on that criterion.
   The R/B post-pass runs at fixed 5000 iterations regardless of
   fixture size — scaling that up should fix.

2. **station_per_team_spread similar pattern.** 24×8 has spread=2
   (floor=1, target=1). Same root cause.

These are Phase D's value: it caught what Phase C's scoring identified
in a now-actionable form. The fix is its own piece of work (post-pass
tuning workstream).

---

## Code references

- `scripts/scheduler_eval/standards.py` — runner
- `scripts/scheduler_eval/standards_config.py` — bars + inventory
- `tests/test_standards_smoke.py` — framework wiring smoke test
- `app/quality_report.py:build_quality_report` — Phase B/C entry
- `app/quality_scoring.py` — Phase C scoring (the bar source)
- `app/canonical_library.py` — best-known floor source

---

## What this completes

Phase D was the last piece of Schedule Quality Framework v1.0. The
framework is now operationally useful:

- **Phase A** defined the mathematical bar (theoretical floors)
- **Phase B** captured per-schedule data (canonical library + quality_report)
- **Phase C** turned data into scores (per-criterion 0-100 + composite)
- **Phase D** turned scores into a gate (standing eval with bars)

Any future scheduling methodology — production tuning, prototype, new
algorithm — runs through this framework and gets compared on the
same terms.

**v1.1+ roadmap** (already outlined in workstream):
- Higher-budget canonical re-curation on Stark
- CP-SAT producer mode for proven_optimal upgrades
- Expanded inventory (full ~27-shape FRC plausible set)
- DB-backed library (per `abstract-library.md` workstream)
- Post-pass tuning (the rb/station finding above)
- CI integration of `standards.py --strict`
