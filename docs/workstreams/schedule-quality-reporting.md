# Workstream — Schedule Quality Scoring & Reporting

**Status:** Proposed; design captured for follow-up. Targeted at v1.1, sequenced after `abstract-library.md` infrastructure lands. No implementation yet.

**Supersedes:** `workstreams/ui-quality-exposure.md` (the four-tier UI plan from that doc is folded in as the UI-exposure portion of this larger workstream).

**Related:**
- ADR 001 — lex tuple as canonical schedule score (this workstream builds on it)
- `scheduler/quality-metrics.md` — catalog of every metric this workstream surfaces; definitions, thresholds, sources
- `workstreams/scheduler-quality.md` — Phase 5 of the scheduler-quality plan; this workstream productizes the eval-harness work
- `workstreams/abstract-library.md` — library quality is measured by the framework defined here
- `scheduler/EVAL_FINDINGS.md` — current eval methodology that becomes UI-accessible

---

## What this is

A unified scoring and reporting framework for *every* schedule — generated, imported, library-served, or hand-edited. The same canonical quality signal applies regardless of source. The framework lives in three places:

1. **Algorithm core** — `score_tuple_for_schedule()` and the count-based metrics from `scripts/scheduler_eval/metrics.py` become the single source of truth, callable on any schedule by any caller (server, CLI, UI).
2. **Server API** — schedule responses include the quality report. Existing endpoints get enriched; one new endpoint (`/api/schedules/{id}/quality-report`) is the canonical "analyze this schedule" entry point.
3. **UI surfaces** — the Schedule Quality card in the editor (today's `#diversityReportCard`) becomes the rendering layer. Tiered exposure (per-pair detail → lex tuple → reference comparison → public `/view` surfacing) covers progressively deeper use cases.

The framework is the same for: a freshly-generated schedule, a reference scheduler xlsx the user imported, a library entry being audited, two schedules being compared side-by-side, the eval harness running against TBA fixtures.

## Why this is the right shape

Today the project has at least four overlapping quality systems:

- The **lex tuple** in `score_tuple_for_schedule()` — authoritative for FRC §10.5.2, used by SA accept/reject and best-of-N, but mostly invisible to users.
- The **legacy summary float** in `score_schedule()` — stored on `assigned_schedules.score` column and exported in CSV, but NOT lex-monotone (see ADR 001's "Bad consequences"). Misleading as an authoritative number.
- The **diversity-report endpoint** `/api/abstract-schedules/{id}/diversity-report` — pair histograms + per-slot detail. Used by the editor's Quality card but limited to abstract schedules.
- The **eval-harness metrics** in `scripts/scheduler_eval/metrics.py` — independent count-based measurements + threshold classification. Not accessible from the UI; only runs in the CLI harness.

Four implementations of "is this schedule any good?", three of which disagree subtly:
- Lex tuple is sum-of-squares (`par_quad`, `opp_quad`) — what the SA optimizes.
- Diversity-report counts pairs by repeat-count — what the editor displays.
- Eval metrics count pairs above floor — what the harness reports.

The 30.64 mean composite from the Phase 5 eval re-run is from the third. The Schedule Quality card shows the second. They use different units, different framings, and silently drift. **Users have no canonical way to ask "is my schedule good?"** because there's no canonical answer.

This workstream consolidates. One scoring framework, callable everywhere. Three layers (computation, API, UI), one source of truth.

## Six properties we want

1. **Same answer everywhere.** A schedule's quality report is identical whether asked from the editor, the eval harness, the API, a CLI tool, or a future audit job. No surface-specific divergence.

2. **Works on any schedule.** Generated, imported, library-served, hand-edited, reference output. The framework doesn't care where the schedule came from.

3. **Multi-level detail.** Headline ("how good?") for the user wanting a glance. Per-metric breakdown for someone investigating. Per-pair and per-team detail for debugging or coaching. Lex tuple for algorithm authors.

4. **Reference comparison.** A schedule's quality lands in context: "this schedule's `repeat_partners` is at the 70th percentile of comparable FRC events." Today users have to guess whether "12 repeat partners" is good or bad.

5. **Cross-schedule comparison.** Two saved schedules side-by-side. Per-criterion deltas. Lex compare visualized — first differing criterion highlighted.

6. **Visible everywhere a schedule is.** Today only the editor shows quality info. The public `/view` page, library audit views, comparison views, audit-log views — all should surface quality at appropriate detail levels.

## Architecture

### Layer 1 — Computation (unified scoring module)

A new module: `app/quality.py`. Single source of truth for all schedule-quality computation. Functions return plain data structures (dataclasses, not service objects) so any caller can use them.

```python
# app/quality.py — sketch

@dataclass(frozen=True)
class LexTuple:
    cooldown_violations: int
    par_quad: int
    opp_quad: int
    surrogate_count: int
    rb_metric: int
    station_pen: int
    surrogate_spread: int
    match_equity: int  # currently inert per ADR 001 — kept for slot stability
    
    def __lt__(self, other): ...  # lex compare
    def to_tuple(self) -> tuple: ...

@dataclass(frozen=True)
class MetricResult:
    name: str
    value: int | float
    floor: int | float  # theoretical floor for this fixture
    threshold_acceptable: int | float
    threshold_near_optimal: int | float
    classification: Literal["near_optimal", "acceptable", "poor", "descriptive"]
    
@dataclass(frozen=True)
class PairDetail:
    teams: tuple[int, int]
    encounter_count: int
    floor_for_pair: int  # 1 for most pairs in most fixtures
    slots: list[int]  # slot positions where this pair encountered

@dataclass(frozen=True)
class TeamDetail:
    team_number: int
    slot: int
    distinct_partners: int
    distinct_opponents: int
    station_distribution: list[int]  # 6 stations, count each
    surrogate_count: int
    
@dataclass(frozen=True)
class QualityReport:
    schedule_id: str | None       # nullable — works on un-saved schedules too
    fixture_shape: tuple[int, int, int]   # (num_teams, matches_per_team, teams_per_alliance)
    lex_tuple: LexTuple
    metrics: dict[str, MetricResult]      # 'repeat_partners', 'max_station_spread', etc.
    composite: float                      # the eval-harness composite, computed identically
    overall_classification: Literal["near_optimal", "acceptable", "poor"]
    worst_partner_pairs: list[PairDetail] # top-N pairs above floor
    worst_opponent_pairs: list[PairDetail]
    team_details: list[TeamDetail]        # one per slot
    reference: ReferenceComparison | None # nullable — only present if calibration data exists
    
@dataclass(frozen=True)
class ReferenceComparison:
    """Compares this schedule's metrics against the distribution of comparable
    real-world schedules pulled from TBA. Calibration data lives in
    scripts/scheduler_eval/calibration_data.json and is regenerated as part
    of the curation pipeline."""
    fixture_size_bucket: str   # e.g., "36-40 teams, 7-8 MPT"
    percentile_per_metric: dict[str, float]   # 'repeat_partners' -> 0.7 (70th percentile)
    sample_size: int           # how many real schedules contributed to this bucket
    calibration_date: str

def analyze(matches: list[Match],
            fixture_shape: tuple[int, int, int],
            schedule_id: str | None = None) -> QualityReport:
    """Compute the full quality report for a schedule. Used everywhere."""
    ...
```

This module **replaces** the duplicate logic that today lives in:
- `app/scheduler.py:score_tuple_for_schedule()` and `_score_from_state()` — keep as-is, but `app/quality.py` imports and uses them; they become the lex-tuple-computation primitives, not the whole quality system.
- `app/main.py:/diversity-report endpoint` — the endpoint becomes a thin wrapper around `app.quality.analyze()`.
- `scripts/scheduler_eval/metrics.py` — the metrics computations stay where they are (the harness keeps its CLI focus) but `app/quality.py` either imports them or vendors the canonical versions. **Open question**: which is the right consolidation direction?

The legacy `score_schedule()` float **stays** because `assigned_schedules.score` column and CSV exports depend on it for backwards-compat. New code should not use it. The DB column may eventually be deprecated, but that's a separate concern.

### Layer 2 — Server API

One new endpoint plus enrichment of existing schedule responses.

**`GET /api/schedules/{schedule_id}/quality-report`** — canonical analyze endpoint.

Returns the full `QualityReport` as JSON. Works on any kind of schedule:
- Assigned schedules (today's primary case)
- Abstract schedules (no team detail; metrics-only)
- Library entries (audit view)
- Imported schedules (PDF/xlsx/CSV)

For schedules with team identity, includes `team_details`. For abstract-only, omits that section but includes everything else.

**Existing endpoints get enriched:**
- `POST /api/generate-abstract` response — already includes the lex tuple; gains the full report as an optional field.
- `POST /api/assign-teams` response — same.
- `GET /api/assigned-schedules/{id}` — gains optional `?include_quality=true` query param that bundles the report.
- `GET /api/abstract-schedules/{id}/diversity-report` (existing) — kept for backwards-compat; renamed in code to point at `app.quality.analyze()` so the implementation is unified.

The new endpoint is the single canonical entry point. The enrichment of existing endpoints is for callers who want quality data in the same round-trip as the schedule fetch (the editor, primarily).

### Layer 3 — UI surfacing

The editor's Schedule Quality card (`#diversityReportCard` at `static/index.html:2757`) becomes the rendering layer. The card's render function (`renderDiversityCard()` at `:4220`) is rewritten to consume the new `QualityReport` shape from `app.quality`. Today's render gets richer at every detail level.

Four tiers of exposure, ordered by implementation effort. The first two are v1.1; the last two are v1.2 or later (gated on the reference-calibration work and a product decision about `/view`).

#### Tier 1 — Surface what's already on the wire

The diversity-report endpoint already returns `worst_pairs` and `slot_table`; the card uses only their counts. With the new framework, the equivalent fields are `worst_partner_pairs`, `worst_opponent_pairs`, and `team_details`. Render the detail.

Specifically:
- **Worst pairs with team numbers.** Top 5–10 in the Notable section: "Team 2169 × Team 4728 — partnered 3× (floor: 1)." Slot → team mapping is already known by render time.
- **Per-team breakdown.** A `<details>` toggle inside the Quality card. Each row: team, distinct partners, distinct opponents, station distribution as a 6-cell mini-bar, surrogate count. Sortable.
- **Concentrated surrogate slots** when more than one surrogate appears at the same slot.

No backend work beyond Layer 1 + 2. Pure render-side enrichment. ~3-4 hours of work. Closes the biggest gap (no per-pair specifics) and gives the user actionable information they currently lack.

#### Tier 2 — Surface the lex tuple

The lex tuple is the algorithm's authoritative quality measure but currently invisible to users. Worth surfacing because:
- Users comparing two saved schedules can see *which* criterion differs.
- The cooldown-paramount semantic (always 0 in algorithm output, "structurally minimum") becomes visible as a positive guarantee, not a hidden invariant.
- Algorithm authors and curated-library auditors need this view.

**New section in the Quality card: "Quality breakdown."** One row per lex tuple element with value, brief description, and status. For elements at the structural minimum (cooldown_violations always 0, surrogate_spread and match_equity typically 0), show "✓ at structural minimum" rather than just "0."

**Schedule comparison view.** When the user is comparing two saved schedules (e.g., before/after an edit, or two trial outputs), show the per-element lex tuple side-by-side. Lex compare visualized — first differing element highlighted. Clear ordering: "Schedule A wins on `opp_quad` (404 vs 416); rest equal."

Pre-work: **fix the `match_equity` placeholder.** Currently hardcoded to 0 in `_score_from_state:1101`. Either implement it (after Phase 5 lands, with a clear definition) or drop the slot from the lex tuple. Surfacing a permanently-zero value labeled as if it varied is confusing.

#### Tier 3 — Reference comparison via recalibrated thresholds

Today's `metrics.py` thresholds (acceptable ≤ N, near-optimal ≤ M) are mis-calibrated — the reference scheduler's output classifies as "poor" on most metrics. The thresholds were set against an idealized floor, not against real-world reference schedules. (See `EVAL_FINDINGS.md` "Known issues" #2.)

This tier fixes the calibration and surfaces percentile-based context in the UI:

- **Recalibrate thresholds** against TBA-pulled played schedules. Infrastructure exists (`scripts/scheduler_eval/pull_tba_fixtures.py`, `event_keys.txt`). Pull each event's played schedule, compute per-metric distributions per fixture-size bucket. Set `acceptable` to the 80th percentile of real schedules, `near_optimal` to the 50th. The "the reference scheduler = poor" embarrassment goes away as a side effect.
- **Bake calibration data into a JSON file** shipped with the server (`scripts/scheduler_eval/calibration_data.json`). Versioned in git.
- **`ReferenceComparison` data** in `QualityReport`. For each metric, a percentile rank against the calibration distribution.
- **UI: percentile badges** next to each headline tile in the Quality card. "Avg partner repeats: 0.4 — 70th percentile" with hover for the underlying comparison.

Substantial effort: calibration takes judgment (bucket boundaries, sample size adequacy, drift over time). Sample size with current `event_keys.txt` (~20 events) may be too small; expand the inventory first.

This tier interacts with `abstract-library.md`. Calibration data also tells us "is this curated library entry better than typical FRC events?" which feeds the curation pipeline's "improve existing" path.

#### Tier 4 — Surface to the viewer

Today's `/view` (public spectator surface) has zero quality info. Tier 4 changes that, gated on a product question:

- Do public spectators benefit from seeing schedule-quality detail?
- Or does it invite litigation of mathematically-forced edge cases ("why does my team have 2 repeat partners when others have 0?") that don't have satisfying answers?

Options (pick after the product decision):
- **Minimal:** single header badge ("Schedule quality: X% pairs at floor, station balance: even, no back-to-backs"). One line.
- **Coach-focused:** a `<details>` panel showing a selected team's row from `team_details`. Requires team-selection UI in the viewer.
- **Lex-tuple summary:** compact rendering of Tier 2's breakdown.

Independent of tier choice — any of T1/T2/T3 can ship to view.html as well as index.html.

## Three uses the framework enables

Beyond the editor's quality card, the unified framework enables three new things:

### 1. "Best library entries" view

Once `abstract-library.md` ships, an admin view of library entries with their quality reports. Sortable by lex tuple, by composite, by hit count. Identifies entries that should be re-curated at higher budget (heavily hit + composite > target). This is the entry into the curation pipeline's "improve existing" mode.

### 2. Import quality assessment

When a user imports a reference scheduler xlsx / PDF / CSV, the same quality report runs against the imported schedule. The user sees "this imported schedule has composite 17 — comparable to typical FRC events" or "composite 45 — significantly worse than typical." Users get an objective answer to "is the schedule we got from organization X any good?"

### 3. Schedule comparison

Two saved schedules side-by-side with per-criterion deltas. Use cases:
- Comparing pre/post-edit (user manually swapped teams; did quality drop?)
- Comparing two trial outputs (which best-of-N candidate to commit?)
- Comparing imported MM output with our generated alternative
- Comparing two library entries during curation review

The lex compare from Tier 2 is the rendering primitive; this view is the use case.

## Open questions

### Q1 — Where do `app.quality` and `scripts/scheduler_eval/metrics.py` consolidate?

Two valid directions:

- **`app.quality` imports `scripts/scheduler_eval/metrics.py`.** Eval harness stays the canonical source; server reuses it. Risk: the harness is a `scripts/` folder, conceptually separate from `app/`.
- **`scripts/scheduler_eval/metrics.py` imports `app.quality`.** Server is the canonical source; harness consumes it. Cleaner package hierarchy but moves stuff around.

The second is cleaner long-term. Risk: ~1 day of careful migration to ensure the harness's eval reports stay byte-identical across the refactor.

### Q2 — `match_equity` fate

Tier 2 can't ship a UI surface for a permanently-zero value. Three options:

- **Drop it from the lex tuple.** 7 slots instead of 8. Cleaner, but breaks any external code that knows about position indexes.
- **Implement it.** Define what it means (e.g., variance in team strength of schedule difficulty), implement and validate. Substantial side-work.
- **Keep the slot but rename to `reserved_v2` or similar.** Stays at 0; user-facing label makes its inert-ness explicit.

Recommended: option 1, with explicit changelog entry. Slot indexes are an internal detail; external code (eval harness, UI) goes through named field access on `LexTuple`, not positional tuple indexing.

### Q3 — Calibration data freshness

Tier 3 calibration data has drift risk: as reference schedulers improve and FRC field sizes shift, the reference distribution changes. Three policies:

- **Manual refresh, infrequent.** Recalibrate annually as part of season prep. Cost: percentile claims drift slowly.
- **Continuous calibration via TBA fetch.** Every N days, pull recent events, append to the dataset, recompute distributions. Cost: more moving parts.
- **Versioned calibration, append-only.** Each schedule's quality report records which calibration version it was scored against. New schedules use the latest; old reports stay reproducible.

Recommended: option 1 to start (annual or per-season). Option 3 if we later need historical comparability.

### Q4 — Per-fixture-size bucketing for reference comparison

A 24-team event has structurally different repeat statistics than a 72-team event. Calibration needs bucketing. Bucket boundaries are a judgment call:

- By team count alone (`24-30`, `30-36`, `36-42`, etc.)
- By team count and matches-per-team
- By fully-canonical shape `(num_teams, matches_per_team, teams_per_alliance)`

The third is most accurate but requires the most calibration data per bucket. The first is broadest. Recommended start: bucket by team count alone with explicit caveat in the percentile display; refine when calibration sample size justifies it.

### Q5 — What happens to the legacy summary float?

`assigned_schedules.score` column stores a non-lex-monotone weighted-sum float (see ADR 001). Today it's exported in CSV. Three options:

- **Keep it.** Backwards-compat. Cost: misleading number persists.
- **Replace its value with the composite from `QualityReport`.** Same column, more useful number. Cost: the float-vs-composite scales differ; consumers of the CSV would see numeric drift.
- **Add `quality_composite` as a new column; deprecate `score`.** Path forward without breaking existing consumers. Cost: schema change.

Recommended: third. The migration is one column, additive, no rollback required.

## Shipping order

Four phases, sequenced after `abstract-library.md` lands (so the library's quality is one of the first things the new framework reports on):

**Phase A — Unified scoring module** (~2 days)
- New `app/quality.py` with `QualityReport`, `LexTuple`, `MetricResult`, etc.
- Tests asserting the new module returns identical values to today's `score_tuple_for_schedule()` and diversity-report endpoint.
- Existing endpoints unchanged at this point — `app/quality.py` is internally available but not yet wired up.

**Phase B — Server API** (~1 day)
- New `/api/schedules/{id}/quality-report` endpoint.
- Existing endpoints enriched with the report when `?include_quality=true`.
- The diversity-report endpoint reimplemented as a thin wrapper around `app/quality.analyze()` (same output, different impl).
- Q5: add `quality_composite` column to `assigned_schedules`; populate going forward; legacy `score` column kept.

**Phase C — UI Tier 1** (~3-4 hours)
- Render `worst_partner_pairs`, `worst_opponent_pairs`, `team_details`, surrogate detail in the existing Quality card.

**Phase D — UI Tier 2** (~1 day)
- Quality breakdown section showing the lex tuple per element.
- Pre-work: Q2 (`match_equity` fate decision and execution).
- Schedule comparison view (side-by-side, per-criterion delta).

**Phase E — Calibration + Tier 3** (~3-5 days, separable from above)
- Threshold recalibration against TBA dataset (extend `pull_tba_fixtures.py`).
- `calibration_data.json` shipped with the server.
- `ReferenceComparison` populated when calibration exists for a fixture's bucket.
- UI percentile badges.

**Phase F — Tier 4** (gated on product decision; size depends on chosen option)
- Surface in `/view` based on the decision about public-audience exposure.

## How this changes the project

Today: four overlapping quality systems, three of which disagree, none directly visible to users in their authoritative form.

With this workstream: one framework, one source of truth, visible everywhere a schedule lives, comparable across schedule sources (generated/imported/library), with reference comparison putting numbers in context.

Combined with `abstract-library.md`, this gives the project two things that genuinely don't exist elsewhere in the FRC-tooling space:

1. A curated library of best-known schedules (`abstract-library.md`)
2. Honest, comparable, version-controlled quality measurement (this workstream)

Together they're the v1.1 quality story. Not "we ran a bigger SA" but "we built infrastructure that makes schedule quality a first-class concern across the project."
