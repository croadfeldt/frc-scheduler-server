# Schedule Quality Metrics

**Status:** Living document. Reflects the metrics implemented or
planned as of 2026-05-11. More will be added over time as the
algorithm evolves and as the FRC community surfaces new framings.

**Calibration status:** Threshold values for several metrics in this
catalog are **currently being recalibrated**. The values shown today
are inherited from the project's initial implementation; recalibration
work is tracked in `workstreams/schedule-quality-reporting.md` Phase E.
This document will be updated with the recalibrated values when that
work completes. Where a threshold's current value is known to be
miscalibrated, that's called out inline.

**Related:**
- ADR 001 — lex tuple as the canonical schedule score
- ADR 002 — FRC §10.5.2 paramount cooldown priority
- `workstreams/schedule-quality-reporting.md` — the unified scoring
  framework that produces and exposes these metrics
- `app/quality.py` — the canonical computation module
- `scripts/scheduler_eval/metrics.py` — the harness-side metric
  primitives that `app/quality.py` builds on

## Why this document exists

The codebase has multiple consumers of "is this schedule any good?"
— the editor's Quality card, the eval harness, the abstract-library
curation pipeline, future audit-log UIs. They all need to agree on
what's being measured, why it's being measured, and what counts as
good vs poor.

This document is the catalog: every metric we compute, its
definition, its theoretical floor when one exists, its threshold
bands for classification, the rationale for measuring it at all, and
the source (FRC manual, established FRC scheduling practice, our own
work).

If a metric isn't here, we don't compute it. If a metric is here but
flagged "not yet implemented," it's a tracked future addition.

## Reference sources

The metrics below are drawn from these published sources, plus
empirical work in this project:

- **FRC §10.5.2 MATCH Assignment** (game manual, 2026 edition).
  The 6 priority criteria the official FMS algorithm uses, in
  rank order. This is the authoritative source.
- **Established FRC scheduling practice.** The simulated-annealing
  approach used by the FRC reference scheduler since 2008, with
  separable post-passes for red/blue balance and station balance,
  and the 2021 station-balance refinement. The algorithmic
  ideas are publicly documented; our implementation is independent.
- **Statbotics SoS framework** ([statbotics.io/blog/sos](https://www.statbotics.io/blog/sos)).
  Three Strength-of-Schedule metrics — Δ EPA, Δ Rank, Composite —
  measured as percentile against random schedules. Not yet
  implemented in this project; planned addition.
- **Chief Delphi community discussion** (e.g.
  [Match Scheduler Criteria thread](https://www.chiefdelphi.com/t/match-scheduler-criteria/386813)).
  Surfaces additional concerns beyond §10.5.2: partner-vs-opponent
  difference balance, match gap *distribution* (not just minimum),
  community priorities on what matters.
- **Project-internal:** the eval harness (`scripts/scheduler_eval/`),
  the 16-fixture TBA inventory, and `EVAL_FINDINGS.md`'s analysis
  of which metrics actually distinguish good from poor schedules
  empirically.

## How thresholds work

Each measurable metric carries two thresholds: **acceptable** and
**near-optimal**. These map to a 3-level classification:

| Classification | Meaning |
|---|---|
| **Near-optimal** | At or near the theoretical floor / best achievable. Established FRC schedulers routinely hit this band. |
| **Acceptable** | Above near-optimal but not problematic. FRC community would not complain. |
| **Poor** | Below the acceptability bar. Worth investigating; would draw complaints. |

Some metrics are **descriptive** rather than classified — counted
and reported but not pass/fail (e.g. total surrogate count, which is
a function of the math, not a quality measure).

**Calibration is in progress.** Today's thresholds are mostly
inherited from initial implementation and have not been validated
against a wide enough corpus of real FRC schedules to be fully
trusted. `EVAL_FINDINGS.md` documents some specific cases where
current thresholds misclassify established FRC scheduler output as
"poor," which is wrong by definition. The recalibration uses
percentile-based bands against a large TBA-pulled inventory of real
FRC events; that work is in progress and the values in this catalog
will be updated when it's complete.

**Community input wanted.** If you have framings or metrics that
matter to you and aren't captured below, file an issue or open a
discussion. Several metrics in the "Planned" section came from
community discussion. The catalog is meant to grow.

## The lex tuple — algorithm-side authoritative score

This is the score the SA optimizer uses internally. It's a
lexicographic 8-tuple, compared element-by-element. Strictly better
on a higher-priority element beats any improvement on a
lower-priority element. See ADR 001 for the design and ADR 002 for
the paramount-cooldown enforcement.

| Position | Slot | Description | Floor | Reference |
|---|---|---|---|---|
| 0 | `cooldown_violations` | Count of (team, match) pairs where the team appears at a smaller gap than the configured cooldown. **Paramount** — hard-filtered by the SA, never allowed to occur in algorithm output. | 0 | FRC §10.5.2 criterion 1 |
| 1 | `par_quad` | Sum of `partner_count[i][j]²` across all unordered team pairs (i, j). Measures partnership concentration. Sum-of-squares formulation penalizes high-repeat pairs disproportionately. | `n × (ceil(2·MPT / (n-1)))²` approximately | FRC §10.5.2 criterion 2 + established pairing-uniformity practice |
| 2 | `opp_quad` | Sum of `opponent_count[i][j]²` across all unordered team pairs. Same formulation, opponent side. | `n × (ceil(3·MPT / (n-1)))²` approximately | FRC §10.5.2 criterion 3 + established pairing-uniformity practice |
| 3 | `surrogate_count` | Total surrogate slot-fills across the schedule. Driven by (teams × matches) mod 6; deterministic for a given fixture shape. | (`(n × MPT) mod 6`, if non-zero) | FRC §10.5.2 criterion 4 |
| 4 | `rb_metric` | Red/blue imbalance. For ≥24 teams: max abs(red_count − blue_count) per team. For <24 teams: count of within-team red↔blue swaps (criterion 5 small-event variant). | 0 (achievable when MPT is even) | FRC §10.5.2 criterion 5 |
| 5 | `station_pen` | Driver-station-distribution penalty. Sum across teams of (max − min) of per-station counts. With the 2021 station-balance algorithm, achievable floor is 0 when MPT is divisible by `teams_per_alliance`, else 1. | 0 or 1 (depending on MPT mod tpa) | FRC §10.5.2 criterion 6 + established station-balance practice |
| 6 | `surrogate_spread` | Variance in surrogate placement — discourages concentrating surrogates on the same teams or matches. | 0 | Internal: avoids surrogate clustering |
| 7 | `match_equity` | **Currently inert (always 0).** Reserved slot. Either implement (open question Q2 in `schedule-quality-reporting.md`) or drop in a future ADR. | 0 | Project-internal placeholder |

Lex comparison semantics: `A < B` means A's tuple is strictly lower
at the highest-priority element where they differ. The two
schedules tie if every element is equal. Position 0 (cooldown)
beats every other position; position 1 (par_quad) beats positions
2-7; and so on.

## The threshold-classified metrics — eval harness + UI

These are the metrics the eval harness reports per-fixture and the
editor's Quality card surfaces. They overlap with the lex tuple
(measuring some of the same underlying phenomena) but use different
formulations — count-of-pairs rather than sum-of-squares, max
rather than sum, etc. The two views are intentionally complementary:

- The lex tuple is what the algorithm optimizes.
- The threshold metrics are what humans use to assess quality.

If a schedule has good lex tuple but poor threshold metric, that's
useful information about a mismatch between the optimizer and the
human framing — and a signal that the lex tuple may need
extending (Phase 5 Plan C in `workstreams/scheduler-quality.md`).

### Pairing — partner side

| Metric | Definition | Threshold (acc / near-opt) | Floor | Source |
|---|---|---|---|---|
| `repeat_partners` | Count of distinct team pairs that partner ≥2 times. Surrogate slot-fills excluded — a team filling in for capacity isn't a competitive partnership. | ≤2 / 0 pairs | 0 when `2·MPT < n-1`; `> 0` and forced otherwise — see floors below | FRC §10.5.2 criterion 2 |
| `max_partner_repeats` | Max times any single pair partners across the schedule. | ≤2 / ≤1 times | 1 in typical fixtures (≥1 in forced-repeat fixtures) | Established pairing-uniformity practice |

**Partner-floor formula:**
```
partner_slots_per_team = MPT × (teams_per_alliance − 1)
floor = ceil(partner_slots_per_team / (n − 1))
```
The floor is what every team would have if its partnerships were
perfectly distributed across the other teams. For a 24-team × 6-MPT
event: 6 × 2 = 12 partner-slots / 23 other teams = ceil(0.52) = 1.
For an 8-team × 7-MPT event: 7 × 2 = 14 / 7 = 2 — every pair *must*
partner at least twice; the schedule can't avoid it.

### Pairing — opponent side

| Metric | Definition | Threshold (acc / near-opt) | Floor | Source |
|---|---|---|---|---|
| `repeat_opponents` | Count of distinct team pairs that face each other ≥2 times. Surrogate slot-fills excluded. | ≤27 / ≤20 pairs | calculated per shape — see formula | FRC §10.5.2 criterion 3 |
| `max_opponent_repeats` | Max times any single pair faces each other. | ≤2 / ≤2 times | 2 in typical fixtures | Established pairing-uniformity practice |

**Opponent-floor formula:**
```
opponent_slots_per_team = MPT × teams_per_alliance
floor = ceil(opponent_slots_per_team / (n − 1))
```

**Known issue:** the eval shows we lose ground on
`repeat_opponents` specifically on 40-team × 12-MPT fixtures
(2024micmp* family). We hit `opp_quad` at floor but have ~20% more
pairs above floor than the reference. This is the sum-of-squares vs
count-above-one mismatch flagged in `EVAL_FINDINGS.md` — same
underlying schedule but the two ways of measuring "diversity"
rank schedules differently. Phase 5 Plan C diagnostic running on
Stark addresses this.

### Color balance

| Metric | Definition | Threshold (acc / near-opt) | Source |
|---|---|---|---|
| `max_color_imbalance` | Max abs(blue_count − red_count) across all teams. | ≤2 / ≤1 matches | FRC §10.5.2 criterion 5 |
| `teams_with_5_2_color` | Count of teams with `≥5` matches on one color (for MPT=7) or proportionally scaled. A team playing 5 on one color and 2 on the other is unusual and worth flagging. | 0 / 0 teams | Established R/B-balance practice |

For small events (<24 teams), criterion 5 changes per FRC manual:
minimize R↔B swaps within a team's schedule rather than count.
Currently the implementation handles this via the `rb_metric` slot's
small-event variant; the threshold metric here doesn't yet branch
on event size.

### Station balance

| Metric | Definition | Threshold (acc / near-opt) | Source |
|---|---|---|---|
| `max_station_spread` | Per-team max(station_count) − min(station_count). 0 means a team appears at every driver station equally; large values mean concentration in fewer stations. | ≤1 / ≤1 positions | The 2021 station-balance algorithm — perfect balance is achievable |

**Known issue:** the reference scheduler routinely achieves 0 on
this metric for the vast majority of fixtures. We hit ≥2 on every
fixture in the 16-fixture inventory. This is the dominant gap in
the post-Phase-4 eval baseline. Phase 5 Plan A diagnostic running
on Stark addresses whether the Phase 2 post-pass is
iteration-limited (raise budget) or move-set-limited (redesign).

### Match timing

| Metric | Definition | Threshold (acc / near-opt) | Source |
|---|---|---|---|
| `min_match_gap` | Minimum gap (in match numbers) between any team's consecutive matches. Larger is better — teams need time for queueing and maintenance. | ≥4 / ≥4 matches | Established match-separation practice + §10.5.2 criterion 1 (configurable per event) |
| `back_to_back_matches` | Count of instances where a team plays in consecutive matches (gap == 1). On normal events (24+ teams) this should be impossible by construction. | 0 / 0 instances | Small events only |

**Note on `min_match_gap`:** Established practice treats this as a
hard construction constraint, not a soft objective. We do the same
via the cooldown hard-filter (ADR 002). The threshold here is for
visibility: if it's ever below the configured cooldown, something
has gone wrong in scheduling.

### Surrogate

| Metric | Definition | Threshold (acc / near-opt) | Source |
|---|---|---|---|
| `surrogate_count` | Total surrogate slot-fills. **Descriptive only — not pass/fail.** A function of `(n × MPT) mod 6`; the same value for every schedule with the same fixture shape. | descriptive | FRC §10.5.2 criterion 4 |
| `matches_per_team` | Distribution of matches-per-team across all teams. **Descriptive sanity-check** — every team should play `MPT` matches; surrogates add 1 each to a small subset. | descriptive | FRC §10.5.2 + invariant |

The historical surrogate placement convention (always the 3rd qual
match for surrogate teams, per FRC manual) is a constraint not
currently enforced or measured separately. Tracked as planned work.

## Aggregate score — composite

A single number ranking the schedule. Used for sorting library
entries (when the same fixture shape has multiple candidates),
ranking the best-of-N output of a single Generate call, and giving
users a headline summary.

**Formula:** for each threshold-classified metric, contribute:
- `near_optimal` → 0.5
- `acceptable` → 3.0
- `poor` → 10.0
- `descriptive` → 0 (informational only)

**Range:** 0 (every metric near-optimal) to ~110 (every metric poor).

**Composite bands** (from `EVAL_FINDINGS.md` Phase 5 cutoffs):

| Composite | Verdict |
|---|---|
| ≤20 | Excellent. Ship. |
| 20–25 | Acceptable. Ship and reassess. |
| 25–30 | Marginal. Targeted improvements warranted. |
| >30 | Investigate further. Structural work likely needed. |

**Current state (2026-05-10 baseline):** mean composite 30.64
across the 16-fixture inventory at `--quality-preset best`. Just
into "investigate further" territory; the failure is narrowly
concentrated on `max_station_spread` and `repeat_opponents` per
the data above.

The composite is intentionally simple. It is *not* the lex tuple
and is *not* used by the SA optimizer. It's a human-facing
ranking number. Two schedules with the same composite may have
materially different lex tuples; the lex tuple is the
authoritative ordering, the composite is the headline.

Composite bands are also affected by ongoing calibration. The
current bands reflect what the eval data showed at Phase 5 baseline;
they may shift as recalibration completes.

## Planned additions

These will be added as plugin metrics on top of the unified
quality framework once the framework supports it. Each is a
recognized FRC community concern; tracking here so they're
captured even though not yet computed.

### Strength of Schedule (SoS)

**What:** Per-team measure of how difficult their schedule was,
in terms of partner strength vs opponent strength. The Statbotics
framework defines three variants — Δ EPA, Δ Rank, Composite — as
percentiles against random schedules.

**Why:** The community talks about schedule "luck" as a real
phenomenon. A team with strong partners and weak opponents has
an easier path; one with the reverse has a harder path. The
algorithm currently treats every schedule the same regardless;
two structurally-equivalent schedules can differ wildly in SoS.

**Gating:** SoS is forward-looking but requires team-strength
data (EPA, OPR, prior-season rank). The project doesn't yet
integrate that data. Future scope; tracked.

### Pair distribution beyond pair-counts

**What:** Beyond "how many pairs partner ≥2 times" (a count),
expose the full *distribution* — how many pairs see each other
0/1/2/3/4 times. This is already computed (the partner_hist and
opponent_hist fields in `compute_diversity_report`'s output) but
not classified or thresholded.

**Why:** Two schedules with the same `repeat_partners` count can
have very different shapes (one pair at 4× vs four pairs at 2×).
Distribution shape matters to perceived fairness.

**Gating:** Implemented as raw data; not classified. Adding
classification requires the recalibration mentioned above.

### Partner-vs-opponent difference

**What:** For each team pair, the difference between
`partner_count` and `opponent_count`. A pair partnered twice
and opposed once has difference 1. Community feedback suggests
this is *more* important than raw repeat counts.

**Why:** Established pairing-uniformity practice weights partner
repeats higher than opponent repeats because there are 2 partners
vs 3 opponents per match. But the *combination* — when a pair is
also unbalanced between roles — is what teams actually experience.

**Gating:** Not yet measured. The data is in the pair tables;
adding the metric is straightforward but requires calibration.

### Match-gap distribution

**What:** Beyond `min_match_gap` (a single minimum), expose the
distribution of gaps across all teams — how many gaps at each
length. Some teams may have one short gap; others may have
many.

**Why:** From the Chief Delphi thread: "Each team will have at
most one turnaround with a 2 match gap, and at most 30% of their
turnarounds will have a 3 match gap" is a more nuanced framing
than "minimum gap is N."

**Gating:** Not yet measured. Straightforward addition once
the schedule-quality-reporting Phase B endpoint lands.

### Surrogate scheduling constraint

**What:** Surrogates are always supposed to be in the 3rd qual
match per FRC manual. Currently the count is reported but the
placement is not validated.

**Why:** A schedule with surrogates in the wrong rounds is
technically non-compliant. Worth checking, even if rare.

**Gating:** Construction respects it implicitly; explicit
validation hasn't been added.

## Community input wanted

If you have framings or metrics you care about that aren't
captured above, please open a GitHub issue. The catalog is meant
to grow over time; the planned-additions section was sourced
largely from community discussion, and we'd rather capture a
concern early than miss it.

Concrete examples of useful input:
- "Metric X matters to me because Y; here's how I'd measure it."
- "The threshold for Z seems wrong against schedules I've seen."
- "Schedule property W bothers teams in my region; we should track it."
- "Here's a TBA-published schedule that scores well under your
  metrics but is bad for reason V."

## Versioning and stability

Metric *definitions* in this document are stable; metric
*thresholds* and *weights* are not. Threshold recalibration is in
progress; this document is updated as values change.

The composite formula (the per-classification weights of 0.5 /
3.0 / 10.0) is intended to stay stable so historical composite
scores remain comparable across algorithm versions. If the
formula changes, that's a change worth an ADR.

The lex tuple definition is governed by ADR 001. Changes to the
lex tuple shape (adding the `match_equity` slot, or extending with
new slots per Phase 5 Plan C) require a superseding ADR.

## Cross-references

- **For implementation:** `app/quality.py` is the canonical computation; `scripts/scheduler_eval/metrics.py` is the underlying primitive layer.
- **For surfacing:** `static/index.html renderDiversityCard()` and the future `/api/schedules/{id}/quality-report` endpoint (Phase B of `workstreams/schedule-quality-reporting.md`).
- **For curation use:** `workstreams/abstract-library.md` ranks library entries by composite.
- **For eval methodology:** `scheduler/EVAL_FINDINGS.md` describes how these metrics are aggregated across the 16-fixture inventory.
- **For threshold calibration history:** `scheduler/SCHEDULER_QUALITY_ROADMAP.md` (historical) and `workstreams/scheduler-quality.md` (active Phase 5 work).
