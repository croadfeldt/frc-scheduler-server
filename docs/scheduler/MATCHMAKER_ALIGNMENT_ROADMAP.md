# FRC Scheduler Server — MatchMaker Alignment Roadmap

> ⚠ **Superseded** by [`../workstreams/scheduler-quality.md`](../workstreams/scheduler-quality.md). Retained for historical context. The licensing brief at [`MATCHMAKER_LICENSING_BRIEF.md`](MATCHMAKER_LICENSING_BRIEF.md) constrains all work in this direction; the active plan reflects those constraints plus eval-data-driven re-prioritization.

**Repository:** `github.com/croadfeldt/frc-scheduler-server`
**Document type:** Strategic plan / phase planning
**Companion docs:**
- `PHASE_0_HARD_COOLDOWN_BRIEF.md` — implementation-ready brief for Phase 0 (already drafted)
- Future phase briefs will be issued in the same format once each prior phase lands

---

## Executive summary

The scheduler in this repo is an FRC qualification match generator with two-stage architecture (abstract structure → team assignment) and FIRST-aligned defaults. Independent analysis comparing it against MatchMaker (the official Saxton/Idle Loop algorithm used by FMS) confirmed that **both tools satisfy the FRC manual's six §13.6.2 criteria at their respective defaults**, but identified six specific areas where MatchMaker has stronger guarantees, more search coverage, or cleaner architecture.

This roadmap proposes a six-phase plan to close the gaps without abandoning the two-stage architecture that makes this tool distinctively useful for templates, off-season events, and tooling work. The strategy is **decompose-then-budget, not rewrite-as-MM**: extract coupled concerns from the SA score function into separable post-passes (Phases 0–2), give the simplified inner loop more iterations (Phase 3), measure the delta to MM with an explicit harness (Phase 4), then upgrade Stage 1 from greedy to optimizing (Phase 5).

The phases are ordered so that early work compounds the effect of later work. Each phase ships as an independent PR with an opt-in flag for one release cycle.

---

## Background: the gap analysis

### MatchMaker's six advantages

| # | Advantage | Mechanism |
|---|---|---|
| 1 | Larger search space (~5M candidates at "Best") | Pure SA over full schedule, single-stage |
| 2 | Provably-optimal station balance | Sykes 2021 algorithm as separable pass |
| 3 | Clean Red/Blue alliance balance | Post-process side-swap that preserves all other criteria |
| 4 | Hard match-separation enforcement | Permutation generator structurally cannot emit violators |
| 5 | Pure SA on whole schedule | No greedy lock-in of suboptimal pairing structure |
| 6 | Battle-tested over ~20 years of events | Implicit validation by deployment |

### Why each gap exists in the current implementation

| Gap | Current state | Why it's there |
|---|---|---|
| Search space | ~500 default Stage 2 iterations | Default tuned for fast template generation |
| Station balance | Soft penalty `W_STATION=30` inside SA score | Coupled with everything else in the inner loop |
| R/B balance | Soft penalty `W_BALANCE=30` inside SA score | Same |
| Cooldown | Soft penalty `−1000 × deficit` in SA score | Documentation claims "Hard" but implementation is soft |
| Stage 1 quality | Greedy "60 candidates per match, pick best" | Constructive heuristic; never globally optimizes structure |
| Validation | Asserted by design intent in `PRIORITIES.md` | No measurement against MM ground truth |

### Strategic insight

Three of the six gaps (R/B, station, cooldown) are *cleanly decomposable* — they extract concerns from the SA score function into separable cleanup passes, the way MM does. Two more (search space, Stage 1 quality) are about budget and method. The last (battle-testing) requires either time or an explicit comparison substitute.

The decomposable cleanups are a **prerequisite multiplier**: once W_BALANCE, W_STATION, and the cooldown term are pulled out of the inner SA loop, every iteration becomes cheaper *and* more focused on the criteria that actually need optimization (pairing diversity, surrogate fairness, gap maximization, equity). Doing the cleanups first makes the budget changes (Phase 3) compound, and makes Stage 1 SA (Phase 5) operate on a simpler optimization surface.

---

## Phase plan

### Summary table

| Phase | Title | Type | Branch | Time | Risk |
|---|---|---|---|---|---|
| 0 | Hard cooldown constraint | Truthfulness + cleanup | `cooldown-hard` | 2–4 hours | Low |
| 1 | R/B balance post-pass | Decomposable cleanup | `rb-post-pass` | ~1 day | Low |
| 2 | Sykes-style station post-pass | Decomposable cleanup | `station-post-pass` | 2–3 days | Medium |
| 3 | Quality presets (Fair/Good/Best) | Budget | `quality-presets` | ~1 day | Low |
| 4 | MM comparison harness | Validation infrastructure | `mm-harness` | ~2 days | Low |
| 5 | Stage 1 as SA optimizer | Architecture | `stage1-sa` | ~1 week | High |

### Phase 0 — Hard cooldown constraint

**Goal:** Convert match-separation cooldown from heavily-weighted soft penalty (`−1000 × deficit`) to true hard rejection in move generator and initial-state generator. Bring `PRIORITIES.md` into truthful alignment with code.

**Mechanism:** `delta_swap` checks each proposed swap before scoring; rejects violators with a sentinel. Initial-state constructors filter violating placements during build. Cooldown term removed from score function once unreachable.

**Acceptance:** Zero violations across 200-run fuzz corpus. Pathological-weight scenarios (W_PARTNER=10000) produce zero violations (vs. potentially nonzero on `main`). Default-config schedules within ±1 on all headline metrics. No wall-clock regression.

**Detailed brief:** `PHASE_0_HARD_COOLDOWN_BRIEF.md` (already drafted)

**Why first:** Two-line-class change, near-zero risk, settles a documentation honesty issue. Validates the "pull a term out of the score function" pattern that Phases 1 and 2 depend on.

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

**Goal:** Replace inline `W_STATION=30` with a separable pass that produces provably-near-optimal station distribution, matching MatchMaker's behavior since 2021.

**Mechanism:** Port the Sykes 2021 algorithm (or reimplement from the Idle Loop description at `idleloop.com/matchmaker/stations.php`). Operates on (team, station) assignments after R/B is fixed: for each team, compute current vs. theoretical-best station distribution; identify station-position swaps within a match that move teams toward best distribution without disturbing R/B balance.

**Scope:** New module `app/post_passes/station_balance.py`. Remove `W_STATION` term from Stage 2 score. Add `station_post_pass: true` config flag.

**Acceptance:** For every (N, MPT) combination where perfect station balance is mathematically achievable, the pass produces it. For others (e.g., 10 rounds with 3 stations per side), max imbalance per team ≤ ⌈MPT/3⌉ − ⌊MPT/3⌋. Report in Diversity Report headline numbers. No regression in pairing metrics.

**Why third:** Biggest single quality win available. Architecturally identical pattern to Phase 1, so the validation harness from Phase 1 carries over. Unblocks the credible "matches MM on station balance" claim in `PRIORITIES.md`.

**Dependencies:** Phase 1 should land first so R/B is already a separable pass — running Sykes after R/B (rather than before) is cleaner because Sykes is known to preserve R/B balance, but the reverse is not as clean to verify.

---

### Phase 3 — Quality presets (Fair / Good / Best)

**Goal:** Match MM's user-facing quality dial. Give Stage 2 SA a configurable iteration budget.

**Mechanism:** Replace hardcoded 500-iteration default with three presets — Fair=500, Good=5,000, Best=50,000 (Best ceiling tuned empirically). Expose as UI dropdown next to "Generate" and as `&q=fair|good|best` URL parameter. Default to Good.

**Scope:** Backend SA loop config, frontend UI, URL parameter wiring, Diversity Report should display wall-clock so users see the trade-off.

**Acceptance:** Best preset's headline metrics (over-floor pairs, surrogate variance) ≤ Good's on the same seed. Wall-clock for Best at 60 teams stays under 90 seconds with `_gen_concurrency = 4`. URL reproducibility preserved.

**Why fourth:** Phases 1 and 2 made each iteration cheaper by removing two terms from the score function. This is where that compounds. Doing presets *before* the cleanups would mean Best inherits the slower per-iteration cost.

**Dependencies:** Phases 1 and 2 should land first to maximize per-iteration speedup before scaling iteration count.

---

### Phase 4 — MatchMaker comparison harness

**Goal:** Make the gap to MatchMaker measurable rather than asserted. Give `PRIORITIES.md`'s "✅ Match" claims evidence-backed standing.

**Mechanism:** New `tests/mm_comparison/` directory. Build corpus of 20–30 reference schedules from past TBA events at varied (N, MPT) — pull qualification schedules via TBA API, treat them as MM ground truth (they were generated by it). For each, run this tool with matching parameters at Best preset and compute identical diversity metrics on both. Commit deltas as a markdown summary alongside the corpus. CI runs the harness nightly; regression alerts if any metric drifts > 5% from baseline.

**Scope:** New test module, TBA-fetch script for corpus seeding, metrics extractor that produces identical output format for both MM ground-truth and this tool's output, summary generator.

**Acceptance:** First run produces a published baseline showing where this tool is at-MM, where it's below-MM, and by how much. Each criterion in `PRIORITIES.md`'s alignment table gets a measured number rather than a checkmark.

**Why fifth:** Before Phase 5. Stage 1 SA is the most ambitious change in the roadmap, and "did it actually improve quality?" needs a yardstick. Without this harness, Phase 5 is unfalsifiable.

**Dependencies:** Phase 3 (need Best preset to run a fair comparison against MM's Best).

---

### Phase 5 — Stage 1 as SA optimizer

**Goal:** Replace greedy Stage 1 ("60 random candidates per match, pick best") with SA over slot-level swaps within rounds. Match MM's structural quality without abandoning the two-stage architecture.

**Mechanism:** Keep the current 60-candidate greedy as the *seed* (initialization). After seed is built, run SA: temperature schedule similar to Stage 2, neighborhood = swap two slots within the same round (preserves round uniformity by construction). Score function = pairing diversity (P8/P9 quadratic) + surrogate fairness (P11) only — station and R/B are handled by Phases 1–2 post-passes after Stage 2, so Stage 1 SA doesn't need to optimize them. Iteration budget tied to the same Fair/Good/Best preset from Phase 3.

**Scope:** Major refactor of `generate_matches` in `app/scheduler.py`. New SA loop for Stage 1. Reproducibility-preserving: same `seed` produces the same abstract schedule (the SA's RNG is seeded from `seed`).

**Acceptance:** On the Phase 4 corpus, partner-repeat-over-floor count drops vs. current greedy at matched preset levels. Stage 1 wall-clock at Best stays under 30 seconds for 60 teams. Reproducibility unchanged.

**Why last:** Largest blast radius — touches the core of Stage 1, where any bug shows up in every downstream Stage 2 run. Phase 4's harness gives the measurement ground to tell whether the change actually helps. Phases 1–3 reduce the score function complexity Stage 1 has to optimize, making the SA simpler.

**Dependencies:** All prior phases. Especially Phase 4 — without the harness, "did Stage 1 SA help?" is a vibe check, not a verdict.

---

## Sequencing rationale

The phase order is constrained by three dependency types:

1. **Architectural prerequisite.** Phases 1 and 2 pull terms out of the SA score function. Phase 5 wants Stage 1 SA to operate on a simple score function. So Phases 1 and 2 must precede Phase 5. Phase 0 is a smaller version of the same pattern and is cheap, so it goes first to validate the approach.

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
Phase 4 (MM harness — needs Best preset from Phase 3)
    ↓
Phase 5 (Stage 1 SA — needs Phase 4 to validate, Phases 1–2 to simplify)
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

- **Practice match scheduling** — referenced in `PRIORITIES.md` but distinct optimization concern
- **Playoff scheduling** — different problem entirely
- **Frontend visual redesign** — the existing UI is fine
- **Database schema migrations** — none required by this roadmap
- **Auth / OAuth changes** — orthogonal to scheduler quality
- **MM-strict mode that disables tunable weights** — explicitly contrary to this tool's value proposition
- **Submission to FIRST for official sanctioning** — a different conversation entirely; technical alignment is necessary but nowhere near sufficient for that

If any of these become priorities, they get their own roadmap.

---

## Decision points for Chris

The other session can begin Phase 0 work immediately using the existing brief. Before each subsequent phase, Chris will:

1. Review the prior phase's comparison artifacts and verdict
2. Decide whether tangible benefit was demonstrated
3. Greenlight the next phase, or pause/redirect based on findings

Specific decisions Chris controls:

- **After Phase 0:** If pathological-weights scenario produces zero violations on `main`, was the truthfulness fix alone worth the effort? (Probably yes, but worth confirming.)
- **After Phase 2:** If post-passes deliver as expected, is it worth pursuing Phase 5's bigger architectural change, or is the tool good enough at template work without Stage 1 SA?
- **After Phase 4:** If the MM harness shows this tool is within ~5% on all metrics at Best preset, Phase 5 may not be worth the risk. The harness data will tell.

---

## Reference material

For the implementing session's context:

- **MatchMaker algorithm description:** `https://idleloop.com/matchmaker/index.php`
- **Sykes station-balancing algorithm:** `https://idleloop.com/matchmaker/stations.php`
- **FRC manual §13.6.2 (current) / §10.5.2 (historical):** the six-criterion authoritative source
- **Surrogate-as-3rd-match rule:** in place since 2008, current FRC manual restates it
- **This tool's PRIORITIES.md:** `docs/PRIORITIES.md` in the repo

---

*Roadmap drafted from analysis of the current `main` branch. Phase 0 brief is implementation-ready; Phases 1–5 will be issued as detailed briefs once the prior phase has landed and its comparison artifacts have been reviewed.*
