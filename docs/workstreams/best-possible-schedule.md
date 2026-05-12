# Workstream — Best Possible Schedule

**Status:** Phase 1 (investigation) — design captured, no implementation yet.
Subsequent phases gate on Phase 1's conclusions.

**Goal:** Produce the best possible FRC qualification schedule for any
fixture shape, full stop. "Best" means lex-min lex tuple where
computable; minimum composite score over many trials where not. The
algorithm and architecture should be of a quality and provenance that
FIRST could plausibly adopt as an alternative to the current reference
scheduler. The cost of producing such a schedule is a measurement, not
a constraint — once we know what "best" costs, we decide how to
deliver it (generate-on-demand, library curation, or hybrid).

**Posture target:** FIRST-adoption-ready. This raises the bar beyond
"good for our users" to "good enough that an organization with FIRST's
risk tolerance could adopt." Implications captured below.

**Related:**
- `workstreams/scheduler-quality.md` — Phases 0-4 complete; Phase 5 closed out
- `workstreams/phase5-plan-c.md` — Plan C-1, C-2, C-3 captured; this doc supersedes the sequencing there
- `workstreams/abstract-library.md` — library curation gates on Phase 4's results
- `workstreams/schedule-quality-reporting.md` — quality measurement framework
- `scheduler/quality-metrics.md` — the metric catalog
- `scheduler/REFERENCE_SCHEDULER_LICENSING.md` — provenance constraints (binding)
- `scheduler/REFERENCE_SCHEDULER_ALIGNMENT.md` — historical alignment posture
- ADR 001 — lex tuple shape (likely superseded by Phase 2)
- ADR 002 — paramount cooldown
- ADR 003 — three-layer architecture (potentially affected by Phase 2)
- ADR 004 — no reproducibility guarantee (revisit per FIRST posture)
- ADR 005 — reference scheduler as peer

---

## Why this exists

The Phase 5 diagnostic (2026-05-10) confirmed two things:

1. The current SA implementation has a quality ceiling we can describe
   (mean composite 30.64 across 16 fixtures at SA=2M × best-of-100).
2. The ceiling isn't budget-limited — it's structural. The station
   post-pass is move-set-limited; the lex tuple's `opp_quad` slot is
   satisfied while the human-facing `repeat_opponents` metric is still
   poor.

Plan C (captured in `phase5-plan-c.md`) identifies the *immediate*
interventions to push past today's ceiling. But "push past today's
ceiling" isn't the same as "best possible." Several decisions are
worth re-examining before committing to Plan C as designed:

- Is the lex tuple's shape correct, or are we adding slots to a tuple
  that should be reshaped entirely?
- Can exact (provably-optimal) algorithms replace some or all of the
  SA pipeline for tractable fixture sizes?
- Is the two-stage architecture (abstract construction → assignment)
  still right when "best possible" is the goal, or does a single-stage
  formulation produce strictly better schedules for small fixtures?
- Are there reproducibility guarantees a FIRST-adoption posture would
  require that ADR 004 currently waives?

Phase 1 answers these. Phase 2 onward depends on the answers.

---

## FIRST-adoption-ready posture — what changes

You named the door open to "potential FIRST usage." If that's a real
target, the bar rises in specific ways:

1. **Open-source provenance is now critical, not aspirational.**
   GPL-3 stays. Apache-2.0 dependencies (CP-SAT, OR-Tools) stay
   compatible (one-way compatible with GPL). No proprietary algorithms,
   no licensing entanglement. Already where we are, but the standard
   for what counts as "clean" is higher.

2. **Algorithmic provenance must be airtight.** Every algorithm is
   independently implemented from publicly documented descriptions.
   No code copied from any external scheduler. No ambiguous lineage.
   The `REFERENCE_SCHEDULER_LICENSING.md` brief covers this; FIRST
   adoption would mean an actual examination by their lawyers.

3. **Reproducibility deserves a re-think.** ADR 004 said "schedule is
   the artifact" (no bit-exact replay guarantee, just the
   schedule itself in the DB). That's defensible for our current use,
   but FIRST's posture is stronger — the current FMS is deterministic
   given inputs+seed. We should consider whether to offer the same
   guarantee, even if we don't make it the default. **This is an
   ADR-level question** (see Q4 below).

4. **Team-agnostic stays load-bearing.** You already named it. SoS-
   based metrics are out as scheduling inputs. They can be reported
   post-assignment as observations but never enter the scheduling
   pipeline. Captured in `quality-metrics.md` and confirmed here.

5. **Robustness at edges.** Our current focus has been ~36-team
   regional fixtures because those are what MSHSL runs. FIRST runs
   events from 6 teams to 75+. Last-minute team additions/withdrawals
   are routine. The algorithm has to handle the full range with the
   same quality posture. Some of this is already there; some isn't.

6. **Standards-quality documentation.** Not just code that works —
   a paper-quality description of the algorithm equivalent to the
   Saxton white paper but for ours. This becomes a Phase 6 deliverable.

These don't all need to be solved in Phase 1. They need to be
acknowledged in Phase 1 as constraints that shape Phase 2+.

---

## Phase 1 — the investigation questions

This phase is research, not code. The output is a set of ADR drafts
and a decision document. Subsequent phases depend on the answers.

### Q1. Is the lex tuple shape right?

**Background:** The current 8-slot tuple uses sum-of-squares for
partner and opponent diversity (positions 1 and 2). The Phase 5
diagnostic showed `opp_quad` at floor while `repeat_opponents` is
still poor — proof that sum-of-squares alone doesn't drive the
distribution flattening the FRC community considers a quality
schedule.

**Three candidate reshapings:**

- **C-2a (the simple addition):** Append `repeat_opp_count` after
  `opp_quad`. Also `repeat_par_count` after `par_quad` for symmetry.
  10-slot tuple. Sum-of-squares stays as primary objective; count
  becomes tiebreaker.
- **C-2b (the inversion):** Replace `*_quad` with count formulations.
  The count of pairs above floor is the primary objective; the
  sum-of-squares becomes either the tiebreaker or drops entirely.
  This is a bigger change but possibly the more direct expression
  of the FRC community's notion of "diversity."
- **C-2c (Saxton's role-imbalance insight, formerly Plan C-3):**
  Add a slot that penalizes role-imbalance per pair. A pair seen
  twice as partner + zero as opponent is worse than twice partner +
  once opponent. This is a separate concern from the count vs sum-of-
  squares question; could be added to either C-2a or C-2b.

**What we need to know to choose:**

- How does each tuple rank the 16-fixture eval inventory?
- Which tuple ranking best matches FRC community quality judgment
  (as expressed in published feedback like the MSHSL revision thread)?
- Is the role-imbalance term measurably important, or does flattening
  pair counts implicitly achieve it?

**Phase 1 output:** ADR 007 draft proposing the new tuple shape, with
empirical justification. May supersede ADR 001.

### Q2. Where does CP-SAT become impractical?

**Background:** CP-SAT (Google OR-Tools' constraint programming
solver) can prove optimality for problems within its tractability
range. We don't currently know where that range ends for our problem.

**Investigation:**

- Formulate the Stage 1 pairing problem as a CP-SAT model. Run it on
  the small end of the inventory (8t×7MPT, 12t×7MPT, 24t×6MPT) and
  measure: does it terminate? How long? Does it prove optimal?
- Scale up until CP-SAT no longer terminates in reasonable time
  (~1 hour ceiling). Record the boundary.
- For fixtures where CP-SAT terminates, compare its output's lex
  tuple to our SA's best-of-1000 lex tuple. If CP-SAT proves a
  better tuple exists, SA is leaving quality on the table even at
  max budget; if CP-SAT confirms SA's tuple is optimal, SA is at the
  achievable ceiling for that fixture.

**What we learn:**

- The fixture-size frontier where exact methods are practical.
- The SA's actual quality ceiling vs the provable optimum.
- Where to use SA vs CP-SAT in production.

**Phase 1 output:** A measurement report describing the frontier. No
code commitment yet, but the report informs Phase 2's architectural
decisions.

### Q3. What's the methodology for declaring "best possible reached"?

**Background:** "Best possible" needs a definition we can measure
against. Two cases:

- **Where CP-SAT proves optimal** (small fixtures, per Q2): the
  provable lex-min tuple is the ceiling.
- **Where CP-SAT can't terminate** (large fixtures): we need a
  practical proxy. The candidates are:
  - **Convergence stability.** N independent SA runs at maximum
    budget; if the best lex tuple converges (multiple runs hit the
    same minimum) and further runs don't improve, declare convergence.
  - **Diminishing returns.** Plot composite vs trials; if the curve
    flattens at trial N, treat that as the practical ceiling.
  - **Cross-validation against reference.** If our best lex tuple
    matches or beats the FRC-published schedule for that fixture
    shape (where comparable), accept as "near best possible."

**Phase 1 output:** A documented methodology for each fixture size
range. Likely a hybrid: CP-SAT-proved-optimal where feasible;
convergence-stability with reference cross-validation where not.

### Q4. Should the two-stage architecture stay?

**Background:** ADR 003 codified the two-stage architecture
(day-config + abstract + assigned). The abstract layer is
team-agnostic (slot numbers 1..N); the assigned layer maps real
teams to slots. This is the team-agnostic foundation; it should
not change in spirit.

**The question is whether Stage 1's *construction* should be
two-step itself.** Currently:

- Greedy construction produces an initial abstract.
- SA refines it.

For small fixtures (per Q2's frontier), a single-stage CP-SAT
formulation could produce the abstract directly with optimality
guarantees. The two-stage architecture (abstract → assigned)
stays; only Stage 1's *internal* construction would change.

**Investigation:**

- Compare CP-SAT-direct vs greedy+SA on the small-fixture inventory.
- Measure quality (lex tuple) and wall-clock for each approach.
- Determine the fixture-size threshold where each approach wins.

**Phase 1 output:** Updated ADR 003 — possibly superseded; possibly
amended to note that Stage 1's construction can be either CP-SAT
direct or greedy+SA depending on fixture size. The team-agnostic
abstract-vs-assigned distinction stays.

### Q5. What's the cooldown's role in shaping the solution space?

**Background:** Cooldown is paramount per ADR 002 (FRC §10.5.2). It's
enforced as a hard filter — no SA move that would violate cooldown
is ever generated. This is correct, but it may be over-constraining
in some fixture shapes.

**Investigation:**

- For each fixture shape in the inventory, what's the minimum
  cooldown the FRC §10.5.2 minimum table allows?
- Does running with the minimum allowable cooldown produce
  measurably better other metrics (par_quad, opp_quad) vs running
  with a higher default?
- Is there a fixture shape where reducing cooldown by 1 unlocks a
  meaningful quality improvement?

**Phase 1 output:** A small data report. Cooldown likely stays
paramount and per-fixture-prescribed. The interesting case is
whether we should expose cooldown as a user-tunable lever for events
that want to push quality further at the cost of shorter team gaps.

### Q6. Do high-MPT fixtures have a structurally lower quality ceiling?

**Background:** The Phase 5 diagnostic showed the 40×12 fixture is
where we lose the most ground to reference output. High MPT increases
the pair-encounter density (each team plays more partner-slots and
more opponent-slots), which makes pair diversity harder.

**Investigation:**

- For each (n, MPT) shape in the FRC-common space, compute the
  theoretical pair-encounter floors.
- Run CP-SAT on the small-MPT end (4-6 MPT) to confirm the
  achievable optimum matches the theoretical floor.
- For high-MPT fixtures, use Q3's methodology to determine the
  practical ceiling and compare to the theoretical floor.

**Phase 1 output:** A "quality ceiling by fixture shape" table. This
informs library curation priorities (high-MPT fixtures need more
compute investment) and tells us where the "best possible" really is
across the inventory.

### Q7. What reproducibility guarantee should we offer?

**Background:** ADR 004 said the schedule is the artifact; no bit-
exact replay guarantee. For FIRST-adoption posture, this might be
under-strong.

**The question is:**

- Is there value in offering bit-exact replay given (inputs, seed,
  algorithm version)?
- If yes, what's the contract? Seed-based determinism only? Or
  algorithm-version-pinned determinism?
- What's the cost — does pinning determinism limit our ability to
  parallelize SA or use non-deterministic optimizers?

**Phase 1 output:** Either ADR 008 (reproducibility guarantee
spec) or a documented reaffirmation of ADR 004. The "reaffirm"
case is fine if the existing posture is defensible against FIRST's
needs; the "new ADR" case is needed if FIRST adoption would require
stronger guarantees.

---

## Phase 1 deliverables

Final package (planned, ship together for review):

- `decisions/007-lex-tuple-shape.md` — draft ADR per Q1 conclusion
- `decisions/008-reproducibility.md` — draft ADR or "reaffirm ADR 004" memo per Q7
- `decisions/003-three-layer-architecture.md` — possibly amended per Q4
- `scheduler/best-possible-investigation.md` — consolidated measurement report covering Q2, Q3, Q5, Q6
- Updated `scheduler/quality-metrics.md` if the tuple shape changes

These ship together as a package. No code, just decisions. **You
review and approve the package before Phase 2 begins.**

### In-progress sub-deliverables (2026-05-11 / 2026-05-12 sessions)

- ✓ `scripts/cp_sat/pairing_optimum.py` — first-cut CP-SAT model for
  Stage 1 pairing. Proves OPTIMAL on 6t×4MPT; finds feasible on
  12t×6MPT but doesn't prove optimal in 180s.
- ✓ `scripts/cp_sat/pairing_optimum_v2.py` — F1 refinement with
  tighter linear-reified indicator encoding, linear histogram
  objective, and anchor-based symmetry breaking. ~2× speedup on
  easy cases; no improvement on hard cases.
- ✓ `requirements-research.txt` — separate research-deps file (ortools)
  to keep production container lean.
- ✓ `scheduler/phase1-q2-first-cut.md` — Q2 first-cut findings; flags
  F1-F4 follow-ups (encoding refinement, SA bug fix, R/B+station
  CP-SAT formulation, feasibility-boundary documentation).
- ✓ `scheduler/phase1-f1-cpsat-refinement.md` — F1 follow-up
  findings. Encoding refinement modest. **Bigger finding: SA cannot
  satisfy paramount-cooldown on 12×6×2 even at SA=2M × multiple
  trials. CP-SAT can.** Direct Q4 architectural data: CP-SAT
  feasibility frontier (24+ teams at 30s) is large enough to serve
  as construction primitive for fixtures where SA fails. Also
  refines Q5: the cooldown_max formula is necessary but not
  sufficient at the boundary (16×6×3 counter-example).
- ✓ `scheduler/phase1-f1a-sa-audit.md` — F1-a audit closed. **No
  bug**: SA's `_lex_compare` and `_sa_optimize` accept/reject
  logic correctly enforce paramount-cooldown per ADR 002. The
  failure mode is **move-set-limited**: 2-swap neighborhood
  cannot reduce cooldown below ~2 on 12×6×2 from typical greedy
  construction starts. Empirically: 500K iterations drove cd
  from 11→2 in the first 25K, then stuck at 2. Pattern matches
  Phase 5 station post-pass diagnostic. Production fixtures (≥36
  teams) reach cd=0 trivially. **Q4 architectural finding now
  empirically airtight**: SA-on-greedy structurally cannot
  satisfy FRC §10.5.2's paramount criterion on tight fixtures;
  CP-SAT can. No code changes needed.
- ✓ `scheduler/phase1-q5-cooldown-feasibility.md` — Q5 first-cut:
  closed-form feasibility formula; full FRC-common space table;
  finding F5-1 (no infeasibility at typical cooldown in
  FRC-common space); identifies follow-up Stark job F5-a
  (quality-vs-cooldown sweep). Updated with boundary-infeasibility
  caveat from F1 work.
- ✓ `scheduler/phase1-q4-construction-quality.md` — Q4 first-cut
  finding: greedy construction has 0-17% malformation rate on tight
  fixtures (10t × 6MPT, 12t × 7MPT highest). Defensive fix shipped
  (`ConstructionMalformedError` + caller-side retry). Suggests Q4
  architectural answer: CP-SAT for tight fixtures, greedy+SA for
  larger ones — corroborated by F1's SA-cooldown-failure finding.

These ship piecemeal during the investigation and consolidate into the
final review package when Phase 1 concludes.

---

## Phase 2 onward — gated on Phase 1

The phase plan below is the *current best guess*. Each phase's scope
depends on Phase 1's conclusions. Estimates are wider than usual
because we don't know which sub-questions will need their own
investigation.

### Phase 2 — Lex tuple shape lands

Implement the new tuple per Q1's conclusion. ADR 007 supersedes ADR
001. Eval methodology adjusted. Re-baseline the 16 fixtures against
the new tuple. ~2-3 days plus eval re-run.

### Phase 3 — Algorithm overhaul

Two parallel tracks:

- **SA track:** Expand move set (cross-match station swaps, cross-
  match pairing swaps), retune cooling schedule, increase best-of-N
  ceiling. ~3-5 days.
- **CP-SAT track:** Build exact post-passes for station and R/B
  balance. For small fixtures (per Q2 frontier), build the CP-SAT
  direct construction path. ~4-7 days.

Both land before Phase 4's measurement.

### Phase 4 — Maximum-effort measurement

Stark run. Each fixture in the inventory plus an expanded TBA-pulled
set (covering more shapes) runs at maximum effort. Per-fixture wall-
clock, per-fixture composite, time-quality curves. Bucketing into
fast / medium / library-required.

Expected wall-clock: significant. Days, not hours, depending on
inventory size and the per-fixture max budget.

### Phase 5 — Feasibility analysis

Given Phase 4's data, decide:

- Which FRC-common shapes can generate on-demand at maximum effort?
- Which need library curation as the production path?
- What's the practical "fair / good / best / maximum" preset structure
  for production? Are the current presets right? Should there be more
  presets? Fewer?

This phase produces v1.1 sequencing recommendations.

### Phase 6 — Standards-quality documentation

A Saxton-equivalent description of our algorithm. This is a
deliverable in its own right, not just internal docs. It's what
gets handed to anyone (FIRST or otherwise) evaluating the work.
Probably ~1-2 weeks of focused writing.

### Phase 7 — Library curation (per `abstract-library.md` Phase 2)

Gates on Phase 5's bucketing. Curate the library for FRC-common
shapes that landed in the library-required bucket. Stark compute.

---

## What we explicitly do NOT do

Captured here so it's unambiguous:

- **No team-strength inputs to the scheduling algorithm.** EPA, OPR,
  prior-season rank — all out. The schedule is team-agnostic at its
  core. SoS-style metrics can be reported post-assignment as
  observations.
- **No code, schedule data, or specific implementation influence from
  any third-party FRC tool whose license doesn't explicitly permit
  it.** Algorithmic ideas from public documentation (FRC manual,
  Saxton white paper, Chief Delphi community discussions) are fair
  use; specific implementations from elsewhere are not.
- **No premature optimization of production paths.** Phase 1's
  conclusions might change the architecture; Phase 4's measurement
  might change the production strategy. We don't ship production
  changes ahead of those answers.

---

## Decisions locked in (2026-05-11)

Four questions resolved by user direction before Phase 1 begins:

**D1. FIRST-adoption-ready posture: aspirational, but treated as a
constraint.** Phase 1 is designed around it as a real constraint —
Q4 (two-stage architecture) and Q7 (reproducibility) get full weight.
The "aspirational" framing means we don't pursue FIRST adoption
actively; we make decisions that would *permit* it without
foreclosing other paths. The bar is "good enough that FIRST could
plausibly adopt," not "we're submitting for FIRST adoption."

**D2. Phase 1 budget: ~1-2 weeks of focused work accepted.** No
budget pressure to cut scope. The investigation gets the time it
needs to be thorough.

**D3. Phase 4 Stark budget: days-not-hours accepted; don't budget
down.** We're trying to find the ceiling. Truncating the budget
defeats the purpose of the measurement. Full max-effort runs.

**D4. Phase 6 (standards-quality documentation): real deliverable.**
A paper-quality description of the algorithm, equivalent in
character to the Saxton white paper but for ours. This is what
gets handed to anyone evaluating the work (FIRST or otherwise).
Ships as part of v1.1 completion.

---

## What this commits to

This workstream is committed to Phase 1 specifically: the seven
investigation questions, the deliverable package, and the methodology
documentation. Phase 2 onward is a current-best-guess plan; Phase 1
review will refine or replace it.

The principle: **research before commitment.** We don't ship code
that we'll just replace once the investigation lands.

---

*Workstream drafted 2026-05-11 in response to "develop an algorithm
that gets us to the best possible schedule period." FIRST-adoption-
ready posture treated as a constraint per D1. Phase 1 is research-
only, no code. Subsequent phases gate on Phase 1 review.*
