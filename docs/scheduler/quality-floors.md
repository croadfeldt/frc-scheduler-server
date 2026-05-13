# Quality Floors — Theoretical Lower Bounds for Schedule Quality

**Module:** `app/quality_floors.py`
**Tests:** `tests/test_quality_floors.py`
**Workstream:** Schedule Quality / Empirical Validation Framework (v1.0)

This document specifies the mathematical lower bounds for every
schedule-quality metric the project tracks. For any FRC fixture
shape `(n, MPT, tpa, cooldown)`, these floors are the best any
schedule could mathematically achieve. They are the **target** the
scheduler aims for and the **bar** the scoring framework measures
against.

---

## Why floors matter

The original quality framework used universal thresholds — e.g.
`repeat_partners ≤ 2` for "acceptable" regardless of fixture size.
That's the right bar for an 8-team event but the wrong one for a
60-team event. The acceptable bar must scale with the fixture's
structural properties.

Theoretical floors solve this by giving the *mathematically optimal
value* for each metric at each fixture shape. The scoring framework
(separate module, coming in Phase B/C of this workstream) measures
each schedule's distance from its fixture's floors, normalizing
across fixture sizes. "Achieved par_quad = 252 on 36×7" is a
distance-from-floor of 0 (matches the lower bound); "Achieved
par_quad = 252 on 24×8" is a distance of (252 - 192) / floor = 31%
above floor.

---

## Confidence labels

Each floor carries a `confidence` label:

- **`proven_optimal`**: the floor is the achievable minimum. No
  schedule can match or beat it; some schedules will achieve it.
  Proof is given alongside.

- **`proven_lower_bound`**: the floor is a strict lower bound. No
  schedule can beat it, but it may or may not be achievable —
  additional structural constraints (cooldown, station, etc.) can
  push the actual achievable minimum higher.

- **`best_known`**: not used in v1.0 (no metric currently relies on
  best-known floors), but reserved for future use when no closed-
  form proof exists and we use the best empirical observation as
  the floor.

---

## Floor derivations by metric

### Cooldown violations

> **Floor: 0** (proven optimal)

A schedule satisfies the cooldown constraint iff every team-gap is
≥ cooldown. The Q5 cooldown_max formula determines feasibility:

```
cooldown_max = floor((M - 1) / (MPT - 1))
where M = ceil(n * MPT / (2 * tpa)) is the total match count
```

If cooldown ≤ cooldown_max, a schedule with 0 violations is always
achievable. If cooldown > cooldown_max, no feasible schedule exists.

**Proof:** by inspection. A schedule with violations can always be
restructured (or rejected as infeasible) to eliminate them when the
fixture's cooldown_max allows.

See `docs/scheduler/phase1-q5-cooldown-feasibility.md` for the
cooldown_max derivation.

---

### Surrogate count

> **Floor: `M * (2 * tpa) - (n * MPT)`** (proven optimal)

A schedule's match count is `M = ceil(n * MPT / (2 * tpa))`. Each
match has `2 * tpa` slots. If `n * MPT` doesn't divide evenly by
`2 * tpa`, the excess slots are filled by surrogates — teams that
play one extra match each, that match counting only for capacity
not for ranking.

The surrogate count is structurally determined; the schedule has
no choice. Cannot be reduced below this number.

**Proof:** arithmetic. The number of slots in M matches minus the
number of team-matches that need to be scheduled.

**Examples:**

| Fixture | `n × MPT` | `M × 6` | Surrogate count |
|---|---:|---:|---:|
| 12×6 | 72 | 72 | 0 |
| 20×8 | 160 | 162 | 2 |
| 51×9 | 459 | 462 | 3 |

---

### Color balance per team (rb_per_team)

> **Floor: 0 if MPT even; 1 if MPT odd** (proven optimal)

Each team plays MPT matches across two color labels (red, blue).
The closest-to-balanced split is `(floor(MPT/2), ceil(MPT/2))`.
If MPT is even, this is `(MPT/2, MPT/2)` and `|red - blue| = 0`.
If MPT is odd, `|red - blue| = 1` is forced.

**Proof:** by pigeonhole, MPT objects in 2 bins must have bins
differing by at most MPT mod 2.

**Note:** this is per-team optimum. The R/B post-pass can achieve
this for every team simultaneously when the schedule is structurally
free, which is essentially always the case in practice.

---

### Station spread per team (station_per_team_spread)

> **Floor: 0 if MPT divisible by 6; 1 otherwise** (proven optimal)

Each team's appearances distribute across 6 station-color positions:
`{R1, R2, R3, B1, B2, B3}`. If MPT is divisible by 6, the optimum
is `MPT/6` at each position (spread = max − min = 0). Otherwise some
positions get `floor(MPT/6)` and others get `ceil(MPT/6)`, giving
spread = 1.

**Proof:** pigeonhole over 6 positions.

**Important caveat:** this is the **per-team** optimum. Whether
ALL teams can simultaneously achieve their per-team optimum is a
combinatorial design question (Latin squares + design balance). In
practice the station-balance post-pass reaches this for every team
when given a schedule constructed without artificial constraints.

**Examples:**

| MPT | Floor | Optimal per-team distribution |
|---:|---:|---|
| 6   | 0 | (1, 1, 1, 1, 1, 1) across positions |
| 7   | 1 | one position visited twice |
| 8   | 1 | two positions visited twice |
| 12  | 0 | (2, 2, 2, 2, 2, 2) |

---

### Partner pair count (partner_pair_count)

> **Floor: `floor(MPT * (tpa-1) / (n-1))`** (proven optimal)

For any single pair of teams (i, j): the number of times they
partner is in `{0, 1, 2, ..., MPT}`. The average across all pairs is
`MPT * (tpa - 1) / (n - 1)`. At least one pair must have count ≤
floor(average) and at least one must have count ≥ ceil(average).

**Proof:** pigeonhole. Total partner-slots per team is `MPT * (tpa-1)`;
distributed across `n - 1` other teams, at least one other team gets
≤ floor of the average.

This is the "no pair partners more than K times" floor where
K = ceil(average) is the achievable minimum for the max-count
metric.

---

### Partner-pair quadratic sum (par_quad)

> **Floor: `r * (F+1)² + (P - r) * F²`** (proven lower bound)
>
> where:
>   - `P = C(n, 2) = n(n-1)/2` (number of unique pairs)
>   - `T = n * MPT * (tpa - 1) / 2` (total pair-encounters)
>   - `F = floor(T / P)` (basic count floor)
>   - `r = T - F * P` (number of pairs that must be at F+1)

**par_quad** is `Σ x_i²` where `x_i` is how often pair i partners.
The sum of all x_i equals T (each match contributes `C(tpa, 2) = 3`
partner-pairs, multiplied across M matches).

For any fixed T and P, `Σ x_i²` is minimized when the x_i values
are as equal as possible. Specifically:

- `r` pairs at count F+1
- `P - r` pairs at count F

Yields `Σ x_i² = r(F+1)² + (P-r)F²`.

**Proof (convexity argument):**

If we have two pairs at counts (a, b) with a ≥ b+2, swapping to
(a-1, b+1) strictly decreases the sum of their squares:
- before: a² + b²
- after:  (a-1)² + (b+1)² = a² - 2a + 1 + b² + 2b + 1 = a² + b² - 2(a-b) + 2
- diff:   −2(a-b) + 2 ≤ -2 (since a - b ≥ 2)

So any non-minimum-variance distribution can be improved. The
minimum is therefore the as-even-as-possible distribution.

**Confidence: `proven_lower_bound`, not `proven_optimal`.**

The count-distribution lower bound assumes any (r at F+1, P-r at F)
distribution is realizable. In practice the schedule's structural
constraints (cooldown, station, surrogate) can preclude that
distribution. For example, 12×6 at cooldown=2 has par_quad floor =
84 but the F1-c measurement shows the best-achievable is 192 — the
cooldown=2 constraint forces teams into two "tracks" that don't
interact, breaking the even-distribution assumption.

For 36×7 the floor (252) matches what our scheduler achieves —
likely the floor is achievable there.

**Examples:**

| Fixture | T | P | F | r | par_quad floor | F1-c observed |
|---|---:|---:|---:|---:|---:|---:|
| 12×6 | 72 | 66 | 1 | 6 | 84 | 192 (gap of +108) |
| 16×6 | 96 | 120 | 0 | 96 | 96 | 106 (gap of +10) |
| 24×6 | 144 | 276 | 0 | 144 | 144 | 144 (matches!) |
| 24×8 | 192 | 276 | 0 | 192 | 192 | — |
| 36×7 | 252 | 630 | 0 | 252 | 252 | 252 (matches!) |
| 36×12 | 432 | 630 | 0 | 432 | 432 | — |
| 60×12 | 720 | 1770 | 0 | 720 | 720 | — |

Where the floor matches observed (24×6, 36×7), we have strong
evidence that the count-distribution lower bound IS achievable for
those shapes — i.e. our scheduler is at the true optimum.

Where there's a gap (12×6, 16×6), the count-floor is loose. The
true achievable minimum is somewhere in between. Specifically:

- 12×6 cooldown=2: floor=84, achieved=192. The cooldown=2 schedule
  shape forces teams into two non-interacting groups; 36 pairs
  (across-group) have count=0, 30 pairs (within-group) split 5 ways.
- 16×6 cooldown=2: floor=96, achieved=106. Slightly looser than
  the cooldown=2 structure permits; CP-SAT couldn't prove
  optimality even at 240s.

---

### Opponent pair count (opponent_pair_count)

> **Floor: `floor(MPT * tpa / (n-1))`** (proven optimal)

Same shape as partner-pair count, but the per-team opponent slots
count is `MPT * tpa` (each team has `tpa` opponents per match) and
total encounters is `n * MPT * tpa / 2`.

---

### Opponent-pair quadratic sum (opp_quad)

> **Floor: same formula as par_quad with opponent counts** (proven lower bound)

The same convexity argument applies. Confidence is
`proven_lower_bound` because the same structural-constraint
caveat applies.

**Examples:**

| Fixture | T (opp) | P | F | r | opp_quad floor |
|---|---:|---:|---:|---:|---:|
| 12×6 | 108 | 66 | 1 | 42 | 192 |
| 16×6 | 144 | 120 | 1 | 24 | 168 |
| 24×8 | 288 | 276 | 1 | 12 | 312 |
| 36×7 | 378 | 630 | 0 | 378 | 378 |
| 60×12 | 1080 | 1770 | 0 | 1080 | 1080 |

---

## How floors interact with FRC §10.5.2 priorities

FRC §10.5.2 lists six criteria in priority order. Our floor catalog
maps to each:

1. **Cooldown (paramount)** → `cooldown_violations` floor = 0
2. **Partner diversity** → `par_quad` floor; `partner_pair_count` floor
3. **Opponent diversity** → `opp_quad` floor; `opponent_pair_count` floor
4. **Surrogate minimization** → `surrogate_count` floor (structural)
5. **Color (R/B) distribution** → `rb_per_team` floor
6. **Station distribution** → `station_per_team_spread` floor

For a schedule to be at the **theoretical best**, every metric must
hit its floor. In practice some floors are not jointly achievable
(structural constraints between criteria), so the theoretical-best
schedule is an unreachable ideal for some fixtures. The achievable-
best is what canonical-library schedules represent (Phase B).

---

## Caveats and limitations

1. **par_quad and opp_quad floors are proven lower bounds, not
   proven achievable**. Where empirical evidence shows the floor is
   tight (24×6, 36×7), we have high confidence. Where there's a
   gap (12×6, 16×6), the count-floor understates the achievable
   minimum. The scoring framework should treat the count-floor as
   a *target* but not penalize schedules for not reaching it when
   the gap is structural.

2. **Per-team floors for color and station are individual.**
   Whether ALL teams can simultaneously hit their per-team optimum
   is a separate question. The R/B and station post-passes are
   provably commutative with pairing, and in practice they reach
   per-team optimum on essentially every schedule we've measured.

3. **The cooldown_max formula assumes a continuous match schedule
   without breaks.** Long break gaps could change the achievable
   cooldown_max in either direction. Not relevant for our current
   scoring framework.

4. **Surrogate-aware metric definitions**: in the existing harness
   (`scripts/scheduler_eval/metrics.py`), surrogate slots are
   excluded from partner/opponent pair counting per the FRC
   convention that surrogates are filling capacity, not playing
   competitively. The floor calculation in this module uses the
   *full* slot count including surrogates, so the achieved value
   may be slightly higher than the floor on surrogate-requiring
   fixtures. A future refinement could account for this.

---

## Code references

- `app/quality_floors.py:fixture_floors()` — main entry point
- `app/quality_floors.py:_pair_count_floors()` — partner/opponent math
- `app/quality_floors.py:_cooldown_max()` — Q5 formula
- `tests/test_quality_floors.py` — 50+ assertions covering math + serialization
- `docs/scheduler/phase1-q5-cooldown-feasibility.md` — cooldown_max derivation
- `docs/scheduler/EVAL_FINDINGS.md` — empirical observations for comparison

---

## Future work

- **Canonical library** (Phase B): for each shape, run deep CP-SAT
  or SA search to find the best-achievable schedule; cache and
  serve to organizers.
- **Tighter par_quad/opp_quad bounds** (research): for fixtures
  where the count-floor is loose, derive tighter lower bounds from
  the schedule's structural constraints (e.g., the cooldown=2
  two-track partitioning for 12×6).
- **best_known fallback** (Phase B): when CP-SAT can't prove
  optimality, use repeated SA runs to find the best observed
  schedule and treat it as a `best_known` floor.
- **Scoring framework** (Phase C): per-criterion 1-100 distance-
  from-floor; organizer-tunable weights; composite score.
- **Standing eval suite** (Phase D): regression-prevent + production
  bar.
