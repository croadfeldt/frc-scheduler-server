# Phase 1 — F1-e: Eval methodology audit (paramount-cooldown invalidity)

**Date:** 2026-05-12
**Status:** Audit complete; methodology fix shipped.

**Source:** `docs/workstreams/best-possible-schedule.md` Q4
follow-up; F1-a finding (`phase1-f1a-sa-cooldown-audit.md`)
identified that the eval pipeline aggregates cd>0 schedules as
comparable to cd=0 ones.

---

## Why F1-e existed

F1-a discovered the SA cannot satisfy paramount-cooldown on tight
fixtures (12×6×2 produces cooldown_violations~30-50 reliably).
That raised the methodology concern: **the eval harness has been
treating schedules with cooldown violations as comparable data
points alongside valid ones.** Per ADR 002, cd>0 schedules are
*invalid output*, not low-quality output. If the eval pipeline
ranks an SA result of `(31, 116, 268, ...)` alongside a CP-SAT
result of `(0, 192, 408, ...)` and reports the SA as "better
pairing," it's giving misleading data.

F1-e audited every eval-pipeline cooldown handling point to
characterize the gap, then shipped a minimal fix to close it.

---

## What the audit found

### Gap #1: harness has no concept of per-fixture cooldown

`scripts/scheduler_eval/harness_types.py:Fixture` carries
`teams_per_alliance` and other metadata, but **no `cooldown` field**.
The harness measures schedules in isolation against universal
thresholds — `min_match_gap ≥ 4` for "acceptable", `back_to_back ==
0` for "no violations." There's no notion of "what cooldown was
this schedule built for."

For a 36-team state event running with whatever cooldown the
organizer requires (FRC §10.5.2 leaves this to per-event judgment),
a schedule satisfying that cooldown is valid; the universal
threshold check on `min_match_gap` doesn't know what the event's
own rule was. For 12-team events using cooldown=1 (FRC §10.6.6
back-to-back exception, when scheduling math forces it), a schedule
with min_gap=1 is valid; the threshold check classifies it as
"poor." Same problem — the universal threshold doesn't track what
the event's own rule permits.

### Gap #2: no "invalid output" category in classification

`metrics.py:THRESHOLDS` has a three-tier classification —
`near_optimal`, `acceptable`, `poor`. Schedules that violate
paramount cooldown get classified as "poor" on `min_match_gap` or
`back_to_back_matches`, then rolled up alongside merely-low-
quality schedules. **There's no separate "invalid" tier.**

`AnalysisReport.overall` is the worst-of-many classification. A
schedule with cd=50 on a 12×6 fixture is "poor" overall; a
schedule with cd=0 but mediocre pairing might also be "poor"
overall. **Indistinguishable in aggregate.**

### Gap #3: composite_score doesn't penalize cooldown violations

`scripts/scheduler_eval/runner.py:_composite_score` weights:

  - 10 × poor count
  - 3 × acceptable count
  - 0.1 × repeat_partners
  - 0.1 × max_color_imbalance

A schedule with cd=50 produces (at most) one "poor" classification
on `min_match_gap` — contributing 10 to composite. Pairing
quality contributes 0.1 × repeat_partners. **A cd=50 schedule with
excellent pairing (RP=0) scores composite=10; a cd=0 schedule with
mediocre pairing (RP=100) scores composite=10.1.** The cd=50
schedule wins.

This was happening silently across all eval runs on tight fixtures.

### Gap #4: _select_best ranks invalid schedules alongside valid ones

`_select_best` uses the same threshold-classification trichotomy. A
cd=50 schedule with 1 poor / 5 acceptable / 5 near_optimal
classifications could outrank a cd=0 schedule with 2 poor / 4
acceptable / 5 near_optimal. **Invalid output could be selected as
"best."**

### Gap #5: app/quality.py mirrors all of the above

`app/quality.py:composite_score` has the same gap. The production-
side quality module (consumed by the diversity-report endpoint and
abstract-library curation when it lands) doesn't reject
paramount-invalid schedules either.

### Scope of contamination in past data

Past eval reports on disk: only `phase5_diagnose_20260510-183721`
on 40-team / 36-team fixtures. Both fixtures' construction
trivially produces cd=0 starting states, so neither contains
contaminated data points. **The methodology gap exists but hasn't
contaminated past eval data** because we hadn't run the harness
on tight fixtures yet.

The gap matters now because F1-c (CP-SAT-as-construction
prototype) will *deliberately* run comparisons on tight fixtures
where the contamination would otherwise be active. F1-e closes
the gap before F1-c needs it.

---

## What was shipped (minimal-invasive fix)

Five surgical changes, no large refactors:

### 1. `Fixture.cooldown: int | None = None`

`scripts/scheduler_eval/harness_types.py`. New optional field. `None`
preserves legacy behavior (existing fixtures don't trigger the
paramount check). Explicit `int` activates the check.

### 2. `AnalysisReport.is_valid_paramount: bool | None` + `cooldown_violations: int`

`scripts/scheduler_eval/metrics.py`. Two new fields on the report.
`is_valid_paramount` is `None` when the fixture has no cooldown set
(legacy), `True` when all gaps satisfy cooldown, `False` when any
gap is below cooldown. `cooldown_violations` is the count of
violating (team, gap) pairs.

### 3. `analyze()` computes these fields

Walks each team's match index, counts gaps below `fixture.cooldown`.
Adds the result to the report. ~12 lines of additional logic.

### 4. `_composite_score` returns `inf` for paramount-invalid

`scripts/scheduler_eval/runner.py`. One line added: when
`report.is_valid_paramount is False`, return `float("inf")`. Same
pattern as the existing `ok: False` handling — invalid output is
disqualified from aggregation.

### 5. `_select_best` prefers valid over invalid

`scripts/scheduler_eval/runner.py`. Added invalid_flag (0/1) as the
first element of the rank tuple, so valid schedules always rank
before invalid ones regardless of other metrics.

### 6. `app/quality.py:composite_score` mirrors the inf-on-invalid behavior

Same one-line addition: `inf` when `is_valid_paramount` is False.

### 7. `app/quality.py:analyze_against_thresholds` accepts a `cooldown` kwarg

Threads the cooldown through to the constructed Fixture. Optional
parameter; defaults to `None` to preserve callers that don't pass
cooldown.

### 8. Tests

`tests/test_quality.py` — 11 new assertions covering:
- no-cooldown fixture: `is_valid_paramount is None`, composite finite
- cooldown=3 fixture: fields populated correctly
- cooldown=100 (impossible): `is_valid_paramount is False`,
  composite is inf
- `to_dict()` exposes both new fields

All 13 test suites pass.

---

## What this changes about future runs

When the F1-c prototype runs:

- Fixtures with cooldown declared will produce reports flagging
  invalid output (`is_valid_paramount: False`) for any adapter that
  produces cd>0 schedules.
- `_composite_score` returns `inf` for those — they aggregate as
  "this trial failed" rather than blending into the trial mean.
- `_select_best` always picks a valid schedule over an invalid one,
  if any valid schedule exists in the trial set.
- The reports' `to_dict()` exposes `is_valid_paramount` and
  `cooldown_violations` for downstream consumers (cross-adapter
  comparison reports, library curation if it consumes harness output).

Legacy fixtures without `cooldown` set continue to behave as before
— `is_valid_paramount` is `None`, composite scoring uses the old
formula. No back-compat break.

---

## How fixtures opt in

Existing fixtures: add `"cooldown": N` to the JSON for the event's
required minimum gap between a team's consecutive matches.

> **Project policy (2026-05-12): paramount cooldown = 2.**
>
> FRC §10.5.2 establishes "minimum required time between MATCHES
> (varies by event size)" as the paramount scheduling criterion but
> does **not** publish a specific value or per-size table. The
> phrasing "**at least** the minimum required time" makes cooldown
> a **floor** that must be satisfied, not a maximization target.
> Once met, the lower-priority criteria (criteria 2-6 in the manual:
> partner diversity, opponent diversity, surrogate minimization,
> color balance, station distribution) optimize freely above it.
>
> Our project commits to **cooldown=2 as the default value** —
> i.e., the minimum acceptable gap is 2 match-indices (no team
> plays two consecutive matches; one-play-per-round is structurally
> always honored). This leaves the most search space for the
> higher-quality work on criteria 2-6. Setting cooldown higher
> (e.g. 3 or 4) is a constraint on the SA's neighborhood that
> forces worse pairing/balance distributions for marginal
> additional rest time.
>
> **Cooldown remains user-tunable** in the API (`app/main.py`
> request models accept cooldown 1-20) and UI (`static/index.html`
> cooldown input field). Event organizers who require a value
> different from 2 can override per schedule generation request.
> The default of 2 reflects the project's "best possible schedule"
> goal where cooldown is paramount-as-a-floor, not maximized.
>
> **For F1-c and future fixtures**, set `cooldown: 2` in the
> fixture JSON unless the event organizer has documented a
> different requirement.

The 2026mnst fixture (36 teams) is updated to `cooldown: 2`
matching the project default. Per-fixture override only when an
event organizer has explicitly documented a different requirement.

---

## Open follow-ups (cleared)

F1-e is fully closed. No additional follow-ups.

The Phase 1 follow-up tree now stands:

- **F1-a.** ✓ DONE
- **F1-b.** Warm-start CP-SAT with SA output (low priority).
- **F1-c.** Build CP-SAT-as-construction prototype. **Recommended
  next.** Now methodology-clean per F1-e.
- **F1-d.** ✓ DONE
- **F1-e.** ✓ DONE — this document.

---

## Code references

- `scripts/scheduler_eval/harness_types.py` — `Fixture.cooldown`
- `scripts/scheduler_eval/metrics.py` — `AnalysisReport.is_valid_paramount`, `cooldown_violations`; `analyze()` logic
- `scripts/scheduler_eval/runner.py` — `_composite_score` inf handling; `_select_best` valid-first rank
- `app/quality.py` — `composite_score` mirror; `analyze_against_thresholds` cooldown kwarg
- `tests/test_quality.py` — 11 new F1-e assertions

---

*F1-e methodology fix complete. The harness now distinguishes
paramount-invalid output from low-quality output per ADR 002 /
FRC §10.5.2. Prior eval data (Phase 5 diagnostic) is uncontaminated
because the tight fixtures where the gap matters weren't run.
Future eval runs on tight fixtures (including F1-c) will produce
methodology-clean comparisons.*
