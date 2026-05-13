# Per-Criterion Scoring + Organizer-Tunable Weights — Phase C

**Module:** `app/quality_scoring.py`
**Tests:** `tests/test_quality_scoring.py`
**Workstream:** Schedule Quality Framework v1.0 — Phase C of A→B→C→D.

This is the framework that turns the per-metric value/floor data
(Phase B's `quality_report`) into a single human-interpretable
0-100 score, with organizer-tunable weights so events can decide
which criteria matter most.

---

## How it composes with Phases A and B

```
┌─────────────────────────────────────────────────────────────┐
│ Phase A: theoretical floors (app/quality_floors.py)         │
│   per fixture shape, per metric — proven lower bounds        │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│ Phase B: quality_report dict (app/quality_report.py)        │
│   per metric: value, floor, distance, confidence,            │
│   matches_floor                                              │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│ Phase C: 0-100 scoring (app/quality_scoring.py)             │
│   per metric: 0-100 score via per-metric curve              │
│   weights: organizer-tunable, FRC-priority-derived defaults │
│   composite: weighted average, paramount-gated              │
└─────────────────────────────────────────────────────────────┘
```

Phase A defines what's mathematically possible. Phase B measures
what was achieved against that. Phase C converts the achievement
into a single number organizers can compare across schedules and
fixtures.

---

## Per-metric scoring curves

Each metric has its own curve, justified by the metric's nature.

### Cooldown violations — BINARY

```
score = 100 if value == 0 (paramount-valid)
        0   otherwise (paramount-invalid; FRC §10.5.2)
```

A schedule with even one cooldown violation is invalid per FRC
§10.5.2. There's no "partial credit" for low-violation schedules
— they don't ship.

### par_quad and opp_quad — QUADRATIC DECAY

```
score = 100 × max(0, 1 - (distance / floor)²)
where distance = value - floor
```

Matches the metric's own quadratic nature. Behavior:

| value vs floor | distance ratio | score |
|---|---:|---:|
| matches floor | 0%   | 100 |
| 10% above     | 0.10 | 99.0 |
| 25% above     | 0.25 | 93.75 |
| 50% above     | 0.50 | 75.0 |
| 100% above (2×) | 1.00 | 0 |
| beyond 2×     | >1.0 | 0 (clamped) |

Rewards getting close to the floor heavily; bottom-out at 2× floor
sets a meaningful "this is bad" threshold without going negative.

**Floor=0 edge case**: any value > 0 scores 0. (You can't be a
fraction of the way to a floor of 0.)

### rb_per_team, station_per_team_spread, surrogate_count — LINEAR-BOUNDED

```
score = max(0, 100 - distance × 25)
```

Each "+1 above floor" costs 25 points; +4 above = 0. Floors for
these metrics are small integers (0, 1, or 2 typically), so even
"+1 above" is a meaningful regression worth flagging.

### Unknown metrics

For metrics not in the curve dispatch table, the score is binary:
100 if value ≤ floor, 0 otherwise. This is the safe default — a
metric that doesn't have a specific curve gets pass/fail treatment
based on whether it hit the floor.

---

## Weights

```python
DEFAULT_QUALITY_WEIGHTS = {
    "cooldown":  1.0,   # FRC #1 paramount
    "partner":   1.0,   # FRC #2
    "opponent":  1.0,   # FRC #3
    "surrogate": 0.5,   # FRC #4
    "color":     0.5,   # FRC #5
    "station":   0.5,   # FRC #6
}
```

Defaults are FRC §10.5.2 priority-derived: the top three criteria
get unit weight; the lower three get half. The composite is a
weighted average — weights don't need to sum to anything specific
because they're normalized at composite time.

**Organizer overrides**: any caller can supply a `quality_weights`
dict to override these. Examples:

- Event that doesn't care about station: `{"station": 0}` — that
  criterion is dropped from the composite. Per-criterion score still
  computed and shown.
- Event that emphasizes partner diversity: `{"partner": 2.0}` —
  partner score counts double in the composite.
- Combined: `{"partner": 2.0, "opponent": 1.5, "station": 0}` — boost
  the diversity criteria, ignore station.

**Clamping**:
- Each weight is clamped to `[0, 5]` (negative weights are nonsense;
  very large weights would let one criterion drown out everything else).
- `cooldown` is **always** clamped to ≥ 1. The paramount criterion
  can't be tuned away — FRC §10.5.2 makes it non-negotiable, and
  the framework encodes that.
- Unknown keys (e.g. `quality_weights = {"foobar": 99}`) are silently
  ignored.

---

## Paramount gate

When `is_valid_paramount = False` (i.e., cooldown_violations > 0),
the composite is **0 regardless of other scores**. Per-criterion
scores are still computed and displayed so organizers can see what
was achieved on non-paramount metrics — but the headline is
"invalid."

`composite_uncapped` is reported alongside for transparency: it's
what the composite would have been if the gate weren't applied. The
two should differ only on invalid schedules.

This matches the F1-e methodology: paramount-invalid output is
never comparable to paramount-valid output (the lex tuple says so,
and the composite score says so too).

---

## Best-known floor scoring (per-shape adaptation)

Some fixture shapes have **structural gaps** where the count-distribution
floor (Phase A) isn't mathematically achievable. Example: 12×6 cooldown=2.
The count-floor for par_quad is 84, but the cooldown=2 constraint forces
teams into two non-interacting groups, pushing the achievable minimum
to 192. Scoring against the count-floor, a 192-achieved schedule scores
0 — which is misleading because it's the best any scheduler can do.

The fix: **best-known floor scoring**. When a canonical library entry
exists for the fixture shape, the canonical's achieved values are
used as the floor for scoring. Schedules matching the canonical score
100, schedules worse than the canonical score lower.

```python
# Pass best_known_floors override
bk = best_known_floors_from_canonical(12, 6, 3, 2)
scores = compute_scores(report, best_known_floors=bk)
```

`build_quality_report()` calls this automatically when `use_best_known_floors=True`
(default). The returned scores dict has `best_known_floors_used`
flagged so the UI can show "scored vs best-known floor" vs "scored
vs theoretical floor."

**Tradeoff**: best-known scoring is meaningful but rewards matching
*current* effort, not the *true* mathematical minimum. As we run
deeper search on Stark and find better canonicals, the bar rises
automatically — old "100"-scored schedules become "lower than the
new best." This is the right behavior for an iterative library.

---

## Composite math

```
composite = Σ(score_i × weight_i) / Σ(weight_i)   for valid schedules
composite = 0                                       for invalid schedules
```

Weights are normalized at composite time; the sum doesn't need to
equal 1.0. Setting a weight to 0 drops the criterion entirely from
the sum.

The composite is rounded to 1 decimal place in the API response.

---

## API surface

### Schedule creation: `quality_weights` parameter

Both `POST /api/schedules` (Phase B unified) and `POST /api/generate-abstract`
(legacy) accept an optional `quality_weights` field in the request body.
When supplied, scoring uses those weights. When NULL, DEFAULT_QUALITY_WEIGHTS
are used.

The weights are stored on the row (new `quality_weights` JSONB column)
so the stored composite score is reproducible.

### `POST /api/abstract-schedules/{id}/rescore`

Re-score an existing schedule under different weights without
regenerating. Body: `{"quality_weights": {...}}`. Returns the
updated scores. Schedule itself is unchanged.

Useful for "what does this schedule look like if I emphasize
partner diversity?" — organizers can try weight combinations
without paying generation cost.

### `GET /api/abstract-schedules/{id}` extended response

Returns `quality_weights` field alongside the existing `quality_report`,
`source`, `source_url` fields from Phase B.

---

## UI surface

The Quality card in the editor renders:

1. **Source banner** (Phase B): canonical / generated / imported.
2. **Composite score badge** (NEW Phase C): big "78/100" with color
   grading (green / amber / orange / red) and a "Weights" button.
3. **Weights editor panel** (NEW Phase C): hidden by default, toggled
   by the Weights button. Six per-criterion sliders (range 0-5, step
   0.1), reset-to-defaults button, "Re-score" button that calls the
   `/rescore` endpoint and updates the displayed scores in place.
4. **Theoretical floor comparison** (extended from Phase B): added
   a "Score" column showing per-criterion 0-100. Color-coded the
   same way as the composite badge.

Cooldown slider is min=1 (matches the paramount-clamp on the server).
All other sliders are min=0.

---

## Future work

- **Persist user-preferred weights**: organizers could save their
  preferred weights to local-storage and have them auto-apply to new
  schedules. v1.1 scope.
- **Per-event weight presets**: an event organizer could set "for
  this event, use these weights" as part of the event configuration.
- **Weight-aware SA**: currently `quality_weights` only affects
  scoring; the SA still optimizes against the lex tuple. A future
  workstream could make the SA respect quality weights during
  generation (separate from FRC §10.5.2 lex priority — would need
  careful design to preserve paramount semantics).
- **Phase D**: standing eval suite — `scripts/scheduler_eval/standards.py`
  asserts production scheduler meets per-fixture composite thresholds
  (default: every fixture ≥ 80/100 composite). Catches regressions.

---

## Code references

- `app/quality_scoring.py` — main module
- `app/quality_report.py` — Phase B + C integration (scores embedded)
- `app/canonical_library.py` — best-known floor source
- `tests/test_quality_scoring.py` — 60+ assertions
- `app/main.py:UnifiedScheduleRequest` — request shape with
  `quality_weights`
- `app/main.py:create_schedule` — POST /api/schedules
- `app/main.py:rescore_abstract_schedule` — POST /api/abstract-schedules/{id}/rescore
- `static/index.html:renderDiversityCard` — UI rendering
- `static/index.html:toggleQualityWeightsPanel` etc. — UI helpers

---

## Worked examples

### Example 1: 36×7 canonical with default weights

```
Metrics:
  cooldown_violations: 0   (floor 0)
  par_quad:            252 (floor 252)
  opp_quad:            462 (floor 378)
  surrogate_count:     0   (floor 0)
  rb_per_team:         3   (floor 1)
  station_per_team_spread: 2 (floor 1)

Per-criterion scores (count-floor scoring):
  cooldown:  100.0  (binary, at floor)
  partner:   100.0  (quadratic, at floor)
  opponent:   95.1  (quadratic, 22% above floor)
  surrogate: 100.0  (linear, at floor)
  color:      50.0  (linear, +2 above floor)
  station:    75.0  (linear, +1 above floor)

Composite (default weights 1/1/1/0.5/0.5/0.5):
  weighted: 100 + 100 + 95.1 + 50 + 25 + 37.5 = 407.6
  sum_weights: 1 + 1 + 1 + 0.5 + 0.5 + 0.5 = 4.5
  composite: 407.6 / 4.5 = 90.6
```

A "good" schedule, but the color/station post-passes are weak
(rb_per_team should be 1, not 3; that's a Phase D finding).

### Example 2: same schedule, organizer ignores color and station

```
weights: {"color": 0, "station": 0}
After normalization: {cooldown: 1, partner: 1, opponent: 1,
                      surrogate: 0.5, color: 0, station: 0}

Composite:
  weighted: 100 + 100 + 95.1 + 50 + 0 + 0 = 345.1
  sum_weights: 1 + 1 + 1 + 0.5 + 0 + 0 = 3.5
  composite: 345.1 / 3.5 = 98.6
```

Score went up because we removed the dragging-down criteria.
Organizer sees "if I don't care about color/station, this schedule
is excellent."

### Example 3: 12×6 canonical with best-known scoring

```
Metrics (par_quad has structural gap):
  par_quad: 192 (count-floor 84, best-known 192)

Count-floor scoring:
  partner: criterion_score("par_quad", 192, 84)
         = 100 × max(0, 1 - (108/84)²)
         = 100 × max(0, 1 - 1.65)
         = 0

Best-known scoring (using canonical's 192 as floor):
  partner: criterion_score("par_quad", 192, 192) = 100
```

Without best-known scoring, this canonical would always score
poorly on partner. With it, the score reflects "you matched the
best anyone has found" — which is the right framing for organizers.
