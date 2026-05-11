# Workstream — Phase 5 Plan C

**Status:** Diagnostic complete (2026-05-10). Plan C-1, C-2, C-3
candidate interventions identified.

> **Sequencing superseded by [`best-possible-schedule.md`](best-possible-schedule.md)**
> (2026-05-11). The "ship Plan C-1 first, then C-2" sequencing this
> doc proposed was time-bound thinking. The user redirected toward
> long-term "best possible schedule" investigation; Plan C is now
> downstream of Phase 1 research questions, not the next action.
> This doc is retained as historical context for the diagnostic
> findings and the candidate interventions; the actual Phase 2+
> implementation work happens per `best-possible-schedule.md`.

**Supersedes:** the open Phase 5 Plan A/B/C question in
`workstreams/scheduler-quality.md`. Plan A (diagnostic) is done;
Plan B (more iteration budget) is ruled out by the data; Plan C
(structural change) is the direction. This doc captures the
diagnostic findings and candidate interventions; the final
intervention shape is gated on the investigation in
`best-possible-schedule.md`.

**Related:**
- `workstreams/best-possible-schedule.md` — the active workstream that supersedes this one's sequencing
- `workstreams/scheduler-quality.md` — the Phase 5 plan this doc closes out
- `scheduler/EVAL_FINDINGS.md` — the eval data that motivated the diagnostic
- `scheduler/quality-metrics.md` — the metric catalog; Plan C interventions affect entries there
- `scripts/scheduler_eval/phase5_diagnose.py` — the diagnostic script
- `scripts/scheduler_eval/reports/phase5_diagnose_20260510-183721.json` — the raw diagnostic output
- ADR 001 — lex tuple as canonical score (Plan C-2 amends or supersedes this)
- `workstreams/abstract-library.md` — library curation depends on knowing the answer here

---

## What we already know

The 16-fixture eval at `--quality-preset best` (SA=2M iterations,
best-of-N=100 trials per fixture) shows two metrics dominate the
gap to reference quality:

1. **`max_station_spread`** — every fixture lands at ≥2; reference
   output reaches 0 on 10 of 13 comparable fixtures. This single
   metric is most of the composite-score gap.
2. **`repeat_opponents`** — high-MPT fixtures (40×12 in the
   2024micmp* family) sit at ~148 pairs above-floor against the
   reference's ~134. About 20% worse.

Phase A (R/B post-pass), Phase B (station post-pass), and Phase 4
(eval methodology corrections) all shipped. The question this
diagnostic addressed: **is the residual gap fixable by raising
iteration budget (Plan B), or does it require structural changes
to the algorithm (Plan C)?**

## What the diagnostic ran

`phase5_diagnose.py` ran two experiments on Stark, 30 minutes
wall-clock total:

**Experiment 1** — station post-pass iteration scaling on 2023mndu
(60 teams × 9 MPT, the fixture where we hit station_spread=5 vs
reference 0). Built a baseline at SA=2M + post-passes, then ran the
`station_balance_sa` post-pass at five iteration budgets: 5K, 50K,
500K, 5M, 50M.

**Experiment 2** — best-of-10 SA=2M trials on 2024micmp1 (40 × 12,
the fixture where `repeat_opponents` lags). Recorded the lex tuple
and full threshold metrics for the best trial.

## What the diagnostic found

### Experiment 1 — station spread is move-set-limited

| Budget | Elapsed | max_station_spread | composite |
|---|---:|---:|---:|
| 5,000 | 0.04s | 2 | 33.5 |
| 50,000 | 0.32s | 2 | 33.5 |
| 500,000 | 3.1s | 2 | 33.5 |
| 5,000,000 | 30.8s | 2 | 33.5 |
| 50,000,000 | 307.9s | 2 | 33.5 |

**Budget scaled 10,000×. The headline metric did not move.**

The internal counters tell the rest of the story:

| Budget | sum_before | sum_after | max_before | max_after |
|---|---:|---:|---:|---:|
| 5K | 135 | 65 | 4 | 3 |
| 50K | 135 | 60 | 4 | 1 |
| 500K | 135 | 60 | 4 | 1 |
| 5M | 135 | 60 | 4 | 1 |
| 50M | 135 | 60 | 4 | 1 |

The post-pass IS doing work — sum drops 135→60 within the first
50K iterations, and `max_after` drops 4→1. But once converged, no
amount of additional iteration moves the headline metric.
`max_station_spread=2` is a *fixed point* of the post-pass's
neighborhood; no single move in the SA's move set can reduce it.

**Conclusion: move-set-limited.** The post-pass converges to a
local optimum that the move set cannot escape. Plan B (more
budget) is ruled out definitively.

### Experiment 2 — opp_quad is at floor; the lex tuple is measuring the wrong thing

10 best-of-N trials at SA=2M:

```
Best lex tuple: (0, 480, 1060, 0, 2, 43, 0, 0)
  cooldown_violations    0    (paramount, at floor)
  par_quad               480  (≈ par_quad_floor 960 — actually below!)
  opp_quad               1060 (≈ opp_quad_floor 1440 — also below!)
  surrogate_count        0    (at floor)
  rb_metric              2    (acceptable)
  station_pen            43   (post-pass converged)
  surrogate_spread       0    (at floor)
  match_equity           0    (inert slot)
```

The lex tuple looks great. But the threshold metrics tell a
different story:

| Metric | Value | Classification |
|---|---:|---|
| repeat_partners | 0 | near_optimal |
| max_partner_repeats | 1 | near_optimal |
| **repeat_opponents** | **148** | **poor** |
| **max_opponent_repeats** | **3** | **poor** |
| max_color_imbalance | 2 | acceptable |
| max_station_spread | 4 | poor |
| min_match_gap | 3 | poor |

The `repeat_opponents` detail shows 11 pairs at count=3 and
~50+ pairs at count=2.

**The lex tuple is satisfied. The schedule is still bad on
opponent diversity.** This is the sum-of-squares-vs-count framing
mismatch flagged in EVAL_FINDINGS:

- `opp_quad` = Σ count². Driving a pair from 3 to 2 changes its
  contribution 9→4 (saves 5). Another pair has to absorb that
  encounter, raising it from 2 to 3 (4→9, costs 5). Net zero;
  the SA is indifferent.
- `repeat_opponents` = count of pairs with ≥2 encounters. The
  same swap doesn't help — it reduces one pair's count from 3
  to 2 (still ≥2) but raises another from 2 to 3 (still ≥2).

The SA is optimizing the right thing for what it's told to
optimize, but what it's told to optimize is incomplete.

**Conclusion: lex-tuple expansion is required.** The sum-of-squares
formulation alone doesn't capture "minimize pairs above floor"
which is what the threshold metric measures and what the FRC
community cares about.

### A side observation worth flagging

Both `par_quad` and `opp_quad` came in *below* what the diagnostic
script labeled as their theoretical floors:

- par_quad: 480 vs labeled floor 960 (−480)
- opp_quad: 1060 vs labeled floor 1440 (−380)

This means either the floor formula in the diagnostic is wrong, or
the lex tuple is summing something the floor formula doesn't model.
The diagnostic's floor formula uses `n × ceil(k·MPT / (n-1))²` — a
per-team approximation, summed across teams. The actual lex tuple
is summed over unordered pairs. The two aren't directly
comparable; the "below floor" result is a measurement artifact, not
a bug in the SA.

This still needs cleanup in `quality-metrics.md` — the floor
formulas there should be revisited so they match what `opp_quad`
actually measures. Tracked separately.

---

## The two Plan C interventions

Each is independent of the other; they can be done in either order
or in parallel.

### Plan C-1 — Station post-pass redesign

**Goal:** drive `max_station_spread` to 0 (where the math allows)
or 1 (where it doesn't), matching reference output.

**Options for redesign:**

**Option C-1-a: Expand the SA's move set.** Currently the
station-balance SA operates on within-alliance permutations only.
Add cross-match station swaps: pick two matches m1 and m2; for one
team that appears in both at different stations, swap its station
in m1 with another team's station in m2. This preserves alliance
membership (still in red/blue), preserves match composition (same
six teams), but redistributes station positions.

- **Why it might work:** the fixed-point at spread=2 likely
  reflects "no within-match permutation helps" but cross-match
  swaps unlock new neighborhood. Standard SA-design principle.
- **Risk:** larger move set = slower per-iteration. Need to
  re-tune the cooling schedule. The post-pass currently runs in
  <0.5s at typical budgets; if redesign slows it to 5-10s, that's
  still fine, but worth measuring.
- **Implementation cost:** ~1 day. Add the cross-match move, run
  the diagnostic again to see if spread drops.

**Option C-1-b: Replace SA with exact assignment.** The station-
balance algorithm is publicly described; the technique is a
network-flow / bipartite-matching formulation that produces optimal
station distribution for any (n, MPT, tpa). This is what reference
output uses to hit 0/1 on every fixture.

- **Why it might work:** by definition. Exact solutions don't get
  stuck at local optima.
- **Risk:** larger implementation effort. Network-flow code from
  scratch is 2-3 days; using a library (networkx) shrinks that
  but adds a dependency. Also, this is a more invasive change to
  the post-pass architecture.
- **Implementation cost:** ~2-3 days. Higher confidence of
  success than C-1-a, but more code.

**Option C-1-c: Hybrid — exact for small fixtures, SA for large.**
Run the exact solver up to some fixture size where it's tractable;
fall back to SA-with-better-move-set above that.

- **Why it might work:** lowest risk; ships incrementally.
- **Risk:** complexity; two code paths to maintain.

**Recommendation:** start with C-1-a (1 day, lower-risk, validates
the move-set hypothesis). If the diagnostic re-run still shows
spread stuck at 2 on this fixture, escalate to C-1-b. This is the
"cheap experiment first, then escalate if needed" approach.

### Plan C-2 — Lex tuple extension

**Goal:** add explicit `repeat_opponents` count to the lex tuple
so the SA optimizes the metric the FRC community actually cares
about.

**Options for extension:**

**Option C-2-a: Append `repeat_opp_count` after `opp_quad`.** The
new tuple becomes:

```
(cooldown_violations,
 par_quad, par_repeat_count,           # new par slot
 opp_quad, opp_repeat_count,           # new opp slot
 surrogate_count,
 rb_metric, station_pen, surrogate_spread, match_equity)
```

10 elements instead of 8. Lex semantics: the SA still optimizes
sum-of-squares first (which keeps the "no one pair too high"
property) but breaks ties by minimizing the number of pairs above
floor.

- **Why it might work:** addresses Experiment 2's finding
  directly. The SA gets an explicit incentive to flatten the
  distribution rather than just minimize its second moment.
- **Risk:** ADR 001 governs the lex tuple shape; this requires a
  superseding ADR. Existing eval baselines (composite numbers)
  become incomparable — schedules that were "best by old tuple"
  may not be "best by new tuple." This is a versioning
  consideration but not a correctness issue.
- **Implementation cost:** ~1 day. The score function in
  `app/scheduler.py` already computes both quantities; the
  change is in the tuple construction and the SA's accept/reject
  comparison. Then re-run the full eval against the new tuple.

**Option C-2-b: Replace `par_quad`/`opp_quad` with count
formulations entirely.** Drop sum-of-squares; use count-above-floor
as the primary objective.

- **Why it might NOT work:** sum-of-squares is the standard
  formulation for FRC pairing uniformity precisely because it
  prevents the "many pairs at exactly the threshold" pathology
  that pure count framings allow. Switching entirely would lose
  important convergence properties. Not recommended.

**Option C-2-c: Add a `max_repeat` term (max count across all
pairs).** This captures the worst-case pair specifically.

- **Why it might work:** addresses the `max_opponent_repeats=3`
  finding in Experiment 2. A pair at 3× shouldn't exist if
  another configuration has all pairs at ≤2.
- **Risk:** Plan C-2-a likely subsumes this (driving the count
  down naturally pushes the max down too).

**Recommendation:** Plan C-2-a. Single targeted addition; preserves
sum-of-squares as primary; adds the count framing as a tiebreaker.
The 10-element tuple is still tractable. ADR 007 supersedes ADR 001
with the rationale captured here.

### Plan C-3 — Role-imbalance penalty (added 2026-05-11)

**Goal:** Encode Saxton's published insight that *"if match
duplication does occur, it's preferable that a team that is seen
twice is seen once as a partner and once as an opponent, rather
than twice in either role."* Currently the lex tuple measures
partner and opponent diversity independently; a pair seen 2× as
partner + 0× as opponent and a pair seen 1× as partner + 1× as
opponent score the same overall but the latter is community-
preferred.

**Options:**

- **C-3-a:** Add a `role_imbalance` slot to the tuple. For each
  pair, compute `|partner_count − opponent_count|`; sum across
  pairs; add as a new lex element after `repeat_opp_count`.
- **C-3-b:** Fold into a combined "pair-encounter quality" metric
  that incorporates both repeat count and role balance.

**Why it might NOT measurably help:** if Plan C-2-a already drives
all pair counts toward 1 or 0, the role-balance question may not
arise frequently enough to matter empirically. Worth measuring
before committing to implementation.

**Recommendation:** Include in Q1 of `best-possible-schedule.md` —
the lex-tuple shape investigation should evaluate whether role-
imbalance is measurably important alongside the count-vs-sum-of-
squares question. Don't pre-commit to implementing.

---

## Sequencing

> **Sequencing below is now historical.** Per
> `best-possible-schedule.md` (2026-05-11), Plan C is downstream
> of Phase 1 investigation, not the next action. The orderings
> below describe how Plan C *would* sequence if it were the next
> action — retained for context, not as a current plan.

These two interventions are independent. Either can ship first.
Three plausible orderings:

**Order A: Plan C-1 first, then Plan C-2.** Fix the station post-
pass; re-run the eval; confirm station spread improves; then
extend the lex tuple. Lower risk because each change is validated
in isolation.

**Order B: Plan C-2 first, then Plan C-1.** Extend the lex tuple
first; re-run the eval; confirm repeat_opponents drops; then fix
the station post-pass. Less natural because the lex tuple
extension is a smaller, more surgical change.

**Order C: Both in parallel.** Plan C-1-a (the move-set change) and
Plan C-2-a (the tuple extension) are non-interacting changes — they
affect different post-passes. Could ship simultaneously.

**Historical recommendation: Order A.** Reasons:

- The station post-pass affects every fixture; the eval baseline
  improves immediately and visibly. Faster validation.
- The lex tuple extension is the more disruptive change (ADR
  supersession, eval baseline incomparable). Better to land it
  with the station improvement already in the baseline so the
  combined improvement is clear in eval reports.
- Plan C-1 doesn't depend on Plan C-2 in any way; the reverse is
  also true but the visible improvement from C-1 lands faster.

Estimated total: ~2-3 days for both interventions, plus eval
re-runs after each on Stark.

---

## What this means for v1.1

Three things:

1. **Mark Phase 5 diagnostic complete in ROADMAP.** The
   Plan A/B/C decision is settled. Both Plan C interventions are
   ahead.

2. **Reprioritize Library Phase 2.** The library curation pipeline
   ranks entries by composite. Plan C-1 and Plan C-2 both improve
   composite. Curating *now* would freeze pre-improvement composite
   scores in the library; curating *after* gets better entries.

   So: Library Phase 1 (infrastructure, schema, lookup-first/cache-
   on-miss) can ship first as planned. Library Phase 2 (the actual
   compute-heavy curation run on Stark) should wait until Plan C-1
   and Plan C-2 are merged.

3. **Update `scheduler/quality-metrics.md`** when Plan C-2 lands —
   the lex tuple's documented shape changes; the new
   `repeat_opp_count` and `repeat_par_count` slots get documented;
   the par_quad / opp_quad floor formulas get revised based on the
   side observation above.

---

## Open questions

These don't block starting Plan C; they're things to resolve along
the way.

**Q1 — Is the diagnostic's "floor below the tuple value" a real
issue or a measurement artifact?** Almost certainly artifact (the
floor formula and the lex tuple sum over different things), but
worth double-checking. If it's an artifact, fix the floor formula
in `quality-metrics.md`. If it's a real issue, that's a separate
investigation.

**Q2 — Should we also add `max_partner_repeats` and
`max_opponent_repeats` as explicit lex slots?** The diagnostic
shows `max_opponent_repeats=3` on the failing fixture. If C-2-a
doesn't drive this to 2 organically, C-2-c (the max term) becomes
worth implementing.

**Q3 — Cross-match station swaps need a coupling check.** The
existing post-pass has a "preserves alliance membership" invariant
that the cross-match move must also preserve. Worth a property
test before merge.

**Q4 — Does the station-balance algorithm in fact produce 0 or 1
spread on every fixture, or are there genuine geometric
impossibilities at certain (n, MPT, tpa) combinations?** For
example, the published station-balance description likely has
known cases where perfect balance is mathematically impossible.
Knowing those cases up front would tell us where to expect
spread=1 (and consider it near-optimal) vs spread=0.

---

*Phase 5 closed out. Plan A/B confirmed not the path; Plan C-1
and Plan C-2 are the work ahead. ~2-3 days plus eval re-runs.
Library Phase 2 curation gates on these two landing.*
