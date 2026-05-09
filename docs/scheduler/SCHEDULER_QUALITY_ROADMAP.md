# Scheduler Quality Roadmap

**Repository:** `github.com/croadfeldt/frc-scheduler-server`
**Document type:** Strategic plan / phase planning
**Status:** **Superseded** by [`QUALITY_IMPROVEMENT_PLAN.md`](QUALITY_IMPROVEMENT_PLAN.md). Retained for historical context. The structural ideas (decompose-then-budget, post-pass pattern, opt-in flags, comparison artifacts) carry forward; the phase ordering and content have been re-prioritized in the active plan based on eval data and a critical finding about the score function consistency in `app/scheduler.py`.

**Companion docs:**
- `PHASE_0_HARD_COOLDOWN_BRIEF.md` — implementation-ready brief for Phase 0 (already drafted; layer-independent and remains valid under any future architectural direction)
- `THREE_LAYER_ARCHITECTURE_DESIGN.md` — broader architectural proposal that this roadmap can slot under
- Future phase briefs will be issued in the same format once each prior phase lands

---

## Executive summary

The scheduler in this repo is an FRC qualification match generator with a two-stage architecture (abstract structure → team assignment) and FIRST-aligned defaults. Independent review of the current implementation against the FRC manual's six §13.6.2 criteria confirmed that **the tool satisfies all six criteria at default settings**, but identified six concrete opportunities to strengthen guarantees, broaden the search space, and clean up architectural coupling.

This roadmap proposes a six-phase plan to act on those opportunities without abandoning the two-stage architecture that makes this tool distinctively useful for templates, off-season events, and tooling work. The strategy is **decompose-then-budget, not rewrite**: extract coupled concerns from the SA score function into separable post-passes (Phases 0–2), give the simplified inner loop more iterations (Phase 3), measure the result against external schedule sources with an explicit harness (Phase 4), then open the algorithm layer to alternative search strategies via a plugin model (Phase 5).

The phases are ordered so that early work compounds the effect of later work. Each phase ships as an independent PR with an opt-in flag for one release cycle.

---

## Background: the gap analysis

### Six opportunities

| # | Opportunity | What it would unlock |
|---|---|---|
| 1 | Larger Stage 2 search space | More candidate schedules considered before convergence; better pairing diversity at the same wall-clock budget |
| 2 | Provably-near-optimal station balance | Strong claim about station-position fairness; eliminates a soft tradeoff in the score function |
| 3 | Cleanly separated Red/Blue alliance balance | Same — extracts a concern from the inner loop into a deterministic post-pass |
| 4 | Hard match-separation enforcement | Documentation truthfulness: P4 is documented as "Hard" but currently implemented as a heavy soft penalty. Also closes a pathological-weights edge case. |
| 5 | Stage 1 as an optimizer rather than a constructive heuristic | More globally-coherent abstract schedules; reduces lock-in of suboptimal pairing structure that Stage 2 cannot fully unwind |
| 6 | Pluggable algorithm layer | Future-proofing: lets us add alternative search strategies (CP-SAT, BIBD, etc.) without forking the codebase |

### Why each gap exists in the current implementation

| Gap | Current state | Why it's there |
|---|---|---|
| Search space | ~500 default Stage 2 iterations | Default tuned for fast template generation |
| Station balance | Soft penalty `W_STATION=30` inside SA score | Coupled with everything else in the inner loop |
| R/B balance | Soft penalty `W_BALANCE=30` inside SA score | Same |
| Cooldown | Soft penalty `−1000 × deficit` in SA score | Documentation claims "Hard" but implementation is soft |
| Stage 1 quality | Greedy "60 candidates per match, pick best" | Constructive heuristic; never globally optimizes structure |
| Algorithm coupling | Only one search strategy (SA) is implemented | No plugin interface exists; alternatives would require forking |

### Strategic insight

Three of the six gaps (R/B, station, cooldown) are *cleanly decomposable* — they extract concerns from the SA score function into separable cleanup passes. Two more (search space, Stage 1 quality) are about budget and method. The last (algorithm coupling) is about extensibility.

The decomposable cleanups are a **prerequisite multiplier**: once W_BALANCE, W_STATION, and the cooldown term are pulled out of the inner SA loop, every iteration becomes cheaper *and* more focused on the criteria that actually need optimization (pairing diversity, surrogate fairness, gap maximization, equity). Doing the cleanups first makes the budget changes (Phase 3) compound, and makes the algorithm plugin model (Phase 5) operate on a simpler optimization surface.

---

## Phase plan

### Summary table

| Phase | Title | Type | Branch | Time | Risk |
|---|---|---|---|---|---|
| 0 | Hard cooldown constraint | Truthfulness + cleanup | `cooldown-hard` | 2–4 hours | Low |
| 1 | R/B balance post-pass | Decomposable cleanup | `rb-post-pass` | ~1 day | Low |
| 2 | Sykes-style station post-pass | Decomposable cleanup | `station-post-pass` | 2–3 days | Medium |
| 3 | Quality presets (Fair/Good/Best) | Budget | `quality-presets` | ~1 day | Low |
| 4 | External comparison harness | Validation infrastructure | `comparison-harness` | ~2 days | Low |
| 5 | Algorithm plugin model + CP-SAT plugin | Architecture inflection point | `algo-plugins` | ~1–2 weeks | High |

### Phase 0 — Hard cooldown constraint

**Goal:** Convert match-separation cooldown from a heavily-weighted soft penalty (`−1000 × deficit`) to a true hard constraint enforced in the move generator and initial-state generator. Bring `PRIORITIES.md` into truthful alignment with the code.

**Mechanism:** `delta_swap` checks each proposed swap before scoring; rejects violators with a sentinel. Initial-state constructors filter violating placements during construction. Cooldown term removed from score function once it is structurally unreachable.

**Acceptance:** Zero violations across a 200-run fuzz corpus. Pathological-weight scenarios (e.g., `W_PARTNER=10000`) produce zero violations (where the soft-penalty implementation could potentially leak through). Default-config schedules within ±1 on all headline metrics. No wall-clock regression.

**Detailed brief:** `PHASE_0_HARD_COOLDOWN_BRIEF.md` (already drafted)

**Why first:** Two-line-class change, near-zero risk, settles a documentation honesty issue. Validates the "pull a term out of the score function" pattern that Phases 1 and 2 depend on.

**Note on adjacent code:** during scoping it surfaced that the current `delta_swap` only computes `-(w_imbal * 500)` — it ignores partner / opponent / station / cooldown deltas entirely, then the SA does a full rescore on accept. That's a pre-existing inconsistency, not in scope for Phase 0, but worth flagging now because Phase 1 removes `W_BALANCE` from the score (the only term `delta_swap` currently uses). The Phase 1 brief, when written, will need to address what `delta_swap` becomes.

---

### Phase 1 — Red/Blue balance post-pass

**Goal:** Replace inline `W_BALANCE=30` with a separable post-process that flips entire alliances per match to optimize R/B distribution. Return the W_BALANCE optimization budget to pairing diversity.

**Mechanism:** After Stage 2 SA terminates, iterate: for each match, compute imbalance reduction from flipping all six teams between Red and Blue; greedily flip the match with the largest reduction; repeat until no flip helps. O(M²) for typical M≈88. Provably commutative with all other criteria — flipping alliances within a match doesn't change partners, opponents, separation, or station-within-alliance distribution.

**Scope:** New module `app/post_passes/rb_balance.py`. Remove `W_BALANCE` term from Stage 2 score. Add `rb_post_pass: true` config flag, opt-in for one release.

**Acceptance:** Diversity Report alliance imbalance ≤ existing baseline on a corpus of seeds. SA convergence time drops measurably (one fewer term in inner loop). No regression in pairing metrics.

**Why second:** Smallest of the three decomposable cleanups. The flip operation is the cleanest possible separable optimization — provably zero coupling with any other criterion. Validates the post-pass architectural pattern with low complexity before tackling the harder Sykes problem.

**Dependencies:** None blocking, but Phase 0's score-function-simplification pattern is reusable here.

---

### Phase 2 — Sykes-style station-balance post-pass

**Goal:** Replace inline `W_STATION=30` with a separable pass that produces provably-near-optimal station distribution.

**Mechanism:** Implement the Sykes 2021 algorithm (a published station-balancing algorithm for round-robin tournament structures). Operates on (team, station) assignments after R/B is fixed: for each team, compute current vs. theoretical-best station distribution; identify station-position swaps within a match that move teams toward best distribution without disturbing R/B balance.

**Scope:** New module `app/post_passes/station_balance.py`. Remove `W_STATION` term from Stage 2 score. Add `station_post_pass: true` config flag.

**Acceptance:** For every (N, MPT) combination where perfect station balance is mathematically achievable, the pass produces it. For others (e.g., 10 rounds with 3 stations per side), max imbalance per team ≤ ⌈MPT/3⌉ − ⌊MPT/3⌋. Report in Diversity Report headline numbers. No regression in pairing metrics.

**Why third:** Biggest single quality win available. Architecturally identical pattern to Phase 1, so the validation harness from Phase 1 carries over. Unblocks the credible "near-optimal station balance" claim in `PRIORITIES.md`.

**Dependencies:** Phase 1 should land first so R/B is already a separable pass — running Sykes after R/B (rather than before) is cleaner because Sykes is known to preserve R/B balance, but the reverse is not as clean to verify.

---

### Phase 3 — Quality presets (Fair / Good / Best)

**Goal:** Give Stage 2 SA a configurable iteration budget so users can trade wall-clock for schedule quality.

**Mechanism:** Replace hardcoded 500-iteration default with three presets — Fair=500, Good=5,000, Best=50,000 (Best ceiling tuned empirically). Expose as UI dropdown next to "Generate" and as `&q=fair|good|best` URL parameter. Default to Good.

**Scope:** Backend SA loop config, frontend UI, URL parameter wiring, Diversity Report should display wall-clock so users see the trade-off.

**Acceptance:** Best preset's headline metrics (over-floor pairs, surrogate variance) ≤ Good's on the same seed. Wall-clock for Best at 60 teams stays under 90 seconds with `_gen_concurrency = 4`. URL reproducibility preserved.

**Why fourth:** Phases 1 and 2 made each iteration cheaper by removing two terms from the score function. This is where that compounds. Doing presets *before* the cleanups would mean Best inherits the slower per-iteration cost.

**Dependencies:** Phases 1 and 2 should land first to maximize per-iteration speedup before scaling iteration count.

---

### Phase 4 — External comparison harness

**Goal:** Build infrastructure to compare schedules generated by this tool against schedules from external sources, on identical inputs. Used both for validation (does our tool produce reasonable schedules?) and for informing future algorithm work.

**Mechanism:** Pluggable harness that accepts a corpus of (event_key, num_teams, MPT, cooldown, seed) tuples. For each tuple, generates a schedule with this tool and pulls/imports a reference schedule from an external source. Compares headline metrics: over-floor partner pairs, over-floor opponent pairs, station imbalance, alliance imbalance, surrogate distribution, gap statistics. Emits a per-tuple diff and a corpus-wide summary.

**External sources are treated as pluggable inputs:** TBA-archived schedules from past events, schedules generated by other open-source schedulers, hand-built reference schedules for known-good test cases. The harness doesn't privilege any one source — it's the comparison infrastructure, and the corpus is configuration.

**Scope:** New module `tests/comparison_harness/`. Reference schedule importers (TBA fetch, file-based, etc.). Metrics computation reused from Diversity Report. Output: HTML + JSON summary per corpus run.

**Acceptance:** Harness runs against a 20-tuple corpus end-to-end without manual intervention. Headline metrics computed correctly (verified against a hand-checked subset). Diff output is human-readable enough to triage findings without re-running anything.

**Why fifth:** Phase 5 is the riskiest change — it opens up alternative algorithms. Without this harness, "did the new algorithm help?" is a vibe check, not a verdict.

**Dependencies:** Phase 3 (Best preset is the apples-to-apples comparison point against external schedules optimized at full quality).

---

### Phase 5 — Algorithm plugin model (inflection point)

**Goal:** Phase 5 is where the scheduler's plugin model gets built. CP-SAT is the first plugin that uses it, but the architectural commitment is "schedulers are plugins to a common interface" — not "build CP-SAT specifically." This is the inflection point where the tool's algorithm layer opens up.

**Why this is an inflection point and not a single feature:** earlier phases extract coupled concerns from the SA score function into separable post-passes. By the end of Phase 4 the inner loop is simpler, the post-passes are independent modules, and the comparison harness can measure outcomes against external references. At that point the question stops being "how do we improve our SA?" and starts being "what algorithms should we offer, and how do we add them?"

The plugin model is the answer to the second question. Once it exists, adding CP-SAT is concrete progress, and adding future algorithms (BIBD-hybrid, live re-optimizer, anything else) is additive — new modules conforming to the existing interface, no core changes.

**Mechanism:**

1. **Define the plugin interface.** Minimum viable contract: `(problem_inputs, parameters) -> (schedule, diagnostics)`. Diagnostics include any per-algorithm provenance (e.g., CP-SAT can emit an optimality certificate; SA emits iteration count + acceptance rate). The interface is defined as a small stable shape — premature abstraction here would cost more than it saves; the contract grows as the second and third plugins reveal what's actually needed.

2. **Refactor the existing SA through the plugin interface.** Every algorithm goes through the same door. The current SA becomes one plugin alongside the new CP-SAT plugin. This is more work than leaving SA as the in-tree default and adding CP-SAT as the only "plugin," but it's architecturally honest and exercises the contract from day one. (Lower-risk alternative: leave SA in-tree, add CP-SAT as a one-direction extension point. Defer the SA refactor. Acceptable if scope becomes a concern.)

3. **Implement the CP-SAT plugin.** Constraint programming via OR-Tools. Native support for hard constraints, lex-ordered objectives, and proven-optimal claims with optimality gap reporting. Quality dial = time budget rather than iteration count.

4. **Algorithm-selection UI.** User-facing choice of algorithm, with sensible auto-selection ("auto" picks based on problem size and goals). Provenance metadata records which algorithm produced each schedule.

**Scope:** Major refactor of `app/scheduler.py` into a thin compositor + plugin registry. New `app/algorithms/` directory with `sa.py`, `cpsat.py`, and `__init__.py` registering both. New dependency: `ortools >= 9.8`. Frontend UI for algorithm selection. URL parameter wiring (`&algo=auto|sa|cpsat`).

**Acceptance:**

- The current SA, refactored through the plugin interface, produces schedules within ±1 metric of the pre-refactor SA on a fixed-seed corpus. (Architectural change preserves behavior.)
- The CP-SAT plugin produces valid schedules for representative event sizes (N=24, 36, 60).
- For at least one (N, MPT, cooldown) tuple where CP-SAT can prove optimality within budget, the optimality certificate is captured in provenance metadata.
- The Phase 4 comparison harness runs against both plugins, producing a side-by-side report. The data informs whether CP-SAT becomes the recommended default for any class of problems.
- Wall-clock at "Best" preset for SA stays at or below current performance. CP-SAT wall-clock at "Standard" budget completes for N=60 within a documented time bound (target: under 5 minutes).

**Why last:** Largest blast radius, highest risk. Phases 1–4 reduce the score function complexity any algorithm has to optimize, making both the SA refactor and the CP-SAT integration simpler. Phase 4's harness gives the measurement ground to tell whether the new plugin actually helps for a given class of problems.

**Dependencies:** All prior phases. Especially Phase 4 — without the harness, evaluating whether the plugin model is delivering value reduces to anecdote.

**What this opens up downstream (out of scope for Phase 5 itself, but enabled by it):**

- BIBD-hybrid plugin for event sizes where balanced incomplete block designs are mathematically achievable
- Live re-optimizer plugin for in-event schedule rebuilds after disruptions
- Goal-suite layer (per the three-layer architecture proposal) — once algorithms are plugins, structuring optimization objectives as separately-pluggable goal suites is a natural next step
- Criteria-suite layer — same direction, for sanctioning-body rules

---

## Sequencing rationale

The phase order is constrained by three dependency types:

1. **Architectural prerequisite.** Phases 1 and 2 pull terms out of the SA score function. Phase 5 wants algorithms to operate on a simple score function. So Phases 1 and 2 must precede Phase 5. Phase 0 is a smaller version of the same pattern and is cheap, so it goes first to validate the approach.

2. **Compounding effect.** Phase 3 increases iteration counts; iteration cost was reduced by Phases 1 and 2. Doing Phase 3 first wastes some of its budget on per-iteration cost that's about to disappear.

3. **Measurement before risk.** Phase 5 is the riskiest change. Phase 4 is the measurement infrastructure. Phase 4 must precede Phase 5 so success or failure is decidable.

Visually, the dependencies form a clean pipeline:

```
Phase 0 (truth/validate pattern)
    ↓
Phase 1 (R/B post-pass)
    ↓
Phase 2 (station post-pass)
    ↓
Phase 3 (quality presets — exploits Phases 1+2)
    ↓
Phase 4 (comparison harness — needs Best preset from Phase 3)
    ↓
Phase 5 (algorithm plugin model + CP-SAT — needs Phase 4 to validate, Phases 1–2 to simplify)
```

There's no productive parallelization between phases — each one's work is small enough that handoff overhead would dominate. Sequential is correct.

---

## Cross-cutting conventions

These apply uniformly across all phase PRs. Documenting once here so each phase brief can reference instead of redefining.

### Opt-in flag pattern

Every behavior change ships with a config flag (e.g., `rb_post_pass: true`) defaulting to *on*. The previous behavior remains accessible by setting the flag to *false*. After one release cycle of stability, the flag and the old code path are removed in the following phase's PR. This means:

- Anyone running an event mid-roadmap can pin a version with stable behavior
- Each phase's PR is reviewable in isolation — the flag scopes the diff
- Rollback is a config change, not a revert

### Comparison artifact pattern

Every phase commits before/after comparison artifacts under `tests/phase{N}_comparison/`. Format established by Phase 0:

- `schedule.csv` — full match list per branch
- `diversity_report.json` — diversity report output
- `metrics.json` — headline numbers
- `wall_clock.txt` — median over 5 runs
- `SUMMARY.md` — side-by-side tables and verdict

This gives Chris a consistent diff format across phases and makes it easy to review tangible benefit without re-running anything.

### Score function audit

After each phase that pulls a term out of the score function (0, 1, 2), the PR description must include a statement of which terms remain in the score function. By end of Phase 2, the inner SA loop should be scoring only:

- P8 (opponent diversity, quadratic)
- P9 (partner diversity, quadratic)
- P11 (surrogate fairness)
- P5 (match equity)
- P7 (gap maximization)

Everything else lives in post-passes or hard constraints.

### Documentation alignment

`docs/PRIORITIES.md` is the source of truth for what the algorithm does. Every phase that changes algorithm behavior must update `PRIORITIES.md` *in the same PR* — not as follow-up. Drift between docs and code is the thing Phase 0 exists to fix; future phases must not reintroduce it.

---

## Out of scope

Items deliberately not covered by this roadmap:

- **Practice match scheduling** — referenced in `PRIORITIES.md` but a distinct optimization concern
- **Playoff scheduling** — different problem entirely
- **Frontend visual redesign** — the existing UI is fine
- **Database schema migrations** — none required by this roadmap
- **Auth / OAuth changes** — orthogonal to scheduler quality
- **Removing user-tunable weights** — explicitly contrary to this tool's value proposition
- **Submission to FIRST for official sanctioning** — a different conversation entirely; technical alignment is necessary but nowhere near sufficient for that

If any of these become priorities, they get their own roadmap.

---

## Decision points

Before each phase, review the prior phase's comparison artifacts and verdict, then:

1. Decide whether tangible benefit was demonstrated
2. Greenlight the next phase, or pause/redirect based on findings

Specific decisions to make at each gate:

- **After Phase 0:** If pathological-weights scenarios produce zero violations on `main`, was the truthfulness fix alone worth the effort? (Probably yes, but worth confirming.)
- **After Phase 2:** If post-passes deliver as expected, is it worth pursuing Phase 5's plugin-model work, or is the tool good enough at template work without alternative algorithms? (The post-passes alone may resolve most of the original quality concerns.)
- **After Phase 4:** Does the comparison harness data show the SA-based pipeline is competitive on the workloads we care about? If yes, Phase 5 may be deferred indefinitely — the plugin model becomes optional rather than required.
- **At Phase 5:** Path (b) full SA-through-plugin-interface refactor, or path (a) lower-risk SA-stays-in-tree + CP-SAT-as-extension-point? Decide based on team capacity and risk tolerance at the time.

---

## Reference material

For implementation context:

- **FRC manual §13.6.2 (current) / §10.5.2 (historical):** the six-criterion authoritative source
- **Surrogate-as-3rd-match rule:** in place since 2008, current FRC manual restates it
- **This tool's PRIORITIES.md:** `docs/PRIORITIES.md` in the repo
- **Sykes station-balancing algorithm (2021):** a published reference algorithm for station-position balance in round-robin tournament structures; cited as one approach for Phase 2's post-pass
- **Three-layer architecture proposal:** `THREE_LAYER_ARCHITECTURE_DESIGN.md` — broader framing under which Phase 5's plugin model becomes the algorithm-suite layer

---

*Roadmap drafted from review of the current `main` branch. Phase 0 brief is implementation-ready; Phases 1–5 will be issued as detailed briefs once the prior phase has landed and its comparison artifacts have been reviewed. Status: paused during live-event change-freeze; technical content remains valid for when work resumes.*
