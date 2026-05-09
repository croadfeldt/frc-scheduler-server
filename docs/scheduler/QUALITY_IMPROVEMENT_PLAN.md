# Scheduler Quality Improvement Plan

**Repository:** `github.com/croadfeldt/frc-scheduler-server`
**Document type:** Active workstream plan
**Status:** **Active.** Scheduler change-freeze lifted (post-2026mnst). Plan ready for execution. Each phase ships independently with comparison artifacts.

**Companion docs:**
- [`EVAL_FINDINGS.md`](EVAL_FINDINGS.md) — empirical results that motivate this work
- [`MATCHMAKER_LICENSING_BRIEF.md`](MATCHMAKER_LICENSING_BRIEF.md) — licensing constraints binding this work
- [`SCHEDULER_QUALITY_ROADMAP.md`](SCHEDULER_QUALITY_ROADMAP.md) — original tactical roadmap (superseded by this doc; retained for historical context)
- [`MATCHMAKER_ALIGNMENT_ROADMAP.md`](MATCHMAKER_ALIGNMENT_ROADMAP.md) — pre-licensing-brief roadmap (superseded; retained)
- [`PHASE_0_HARD_COOLDOWN_BRIEF.md`](PHASE_0_HARD_COOLDOWN_BRIEF.md) — implementation-ready brief for cooldown (still valid; reused as a sub-step in Phase 3 here)
- [`THREE_LAYER_ARCHITECTURE_DESIGN.md`](THREE_LAYER_ARCHITECTURE_DESIGN.md) — destination architecture (deferred until quality work is done)

---

## TL;DR

Eval data showed our scheduler is significantly worse than MatchMaker (mean composite 49.29 vs. 16.65) and worse than FRC's actually-played schedules (25.77). Investigation of `app/scheduler.py` revealed why: the simulated annealing is steered only by red/blue balance — three different score formulas in the file disagree with each other, and the inner-loop `delta_swap` ignores partner, opponent, station, b2b, and surrogate deltas entirely. Phases 1–2 of the original roadmap (post-passes) cannot help until this is fixed; they would leave the SA with nothing to steer on.

This plan re-prioritizes around the eval data and the licensing constraints (MatchMaker is benchmark only, never bundled). Goal: get our scheduler within striking distance of MatchMaker's quality (mean composite ≤ 25) as fast as possible, validated against TBA-actual and occasionally cross-checked against MatchMaker for ceiling calibration.

| Phase | What | Effort | Expected impact |
|---|---|---|---|
| 0 (NEW) | Score function consistency: fix delta_swap and reconcile the three formulas | 2-3 days | Largest single win; baseline jump expected |
| 1 | Sykes-style station post-pass | 2-3 days | Eliminates max_station_spread as a poor metric |
| 2 | Red/Blue post-pass | 1 day | Eliminates max_color_imbalance as a poor metric |
| 3 | Hard cooldown + final score-function cleanup | 0.5 day | Truthfulness fix + final inner-loop simplification |
| 4 | Quality presets (Fair / Good / Best) | 1 day | Closes remaining partner/opponent diversity gap |
| 5 | Decision point | 0.5 day | Decide whether plugin model / Stage 1 SA is needed |

**Total: ~7-8 days of work for Phases 0-4.** After Phase 4 we re-run the eval; if our composite is ≤ 25 (matching actual's mean), the work is done. If still > 30, Phase 5 (Stage 1 SA / plugin model) becomes the next move.

---

## Critical finding: score function inconsistency

This was discovered while reading `app/scheduler.py` for plan-shaping research. It's the prerequisite to everything else.

### The three score formulas

`app/scheduler.py` contains three score formulas that are supposed to evaluate the same thing but disagree substantively:

**1. `score_schedule()` (line 669-743) — best-of-N picker**
```
penalty = b2b × 1000
        + max_imbal × 500
        + surrogates × 200
        + opp_repeats² × W_OPPONENT (60)   ← quadratic
        + par_repeats² × W_PARTNER (80)    ← quadratic
        + station_imbalance × W_STATION (30)
```

**2. `build_score_state()` (line 807-840) — full rescore inside SA loop**
```
penalty = b2b × 1000
        + max_imbal × 500
        + surrogates × 200
        + ro × 15        ← linear, hardcoded; should be W_OPPONENT?
        + rp × 12        ← linear, hardcoded; should be W_PARTNER?
                         ← NO station term at all
```

**3. `delta_swap()` (line 842-865) — the only thing that actually steers SA decisions**
```
delta = -(w_imbal_change × 500)
                         ← ONLY balance is steered
                         ← partner, opponent, station, b2b, surrogate, gap all ignored
```

### Why this matters

The simulated annealing's accept/reject decisions are based on `delta_swap` (the only delta-tracking function called inside the inner loop's hot path). Since `delta_swap` only reflects R/B balance changes, the SA effectively performs random search constrained only by R/B balance.

After each accept, `build_score_state` does a full rescore — but with a different formula than `score_schedule`. The build_score_state result is used for the "best score" tracking, which influences which iteration gets picked at the end. So the SA's *guidance* and its *evaluation* and its *final selection* all use different criteria.

**Effects on eval results:**
- Partner/opponent diversity is whatever falls out of unguided search → poor on most fixtures
- Station spread is whatever falls out of unguided search → poor on most fixtures
- Color imbalance is the *only* thing actually being optimized → still poor because the only steering is via differential moves and the search space is huge
- Cooldown is a soft penalty in `score_schedule` only, with W_COOLDOWN=1000 deficit, so violations are rare — but it's not consistently enforced across all three score functions

### Why post-passes alone wouldn't help

The original roadmap planned to extract W_BALANCE and W_STATION from the score function into separable post-passes. But `delta_swap` only uses W_BALANCE — so removing it would leave delta_swap returning 0 for every move. The SA would accept every move (since 0 ≥ 0), turning the inner loop into pure random shuffling.

We have to fix the score function consistency *before* the post-passes, not as a side effect of them.

---

## Phase plan

### Phase 0 (NEW) — Score function consistency

**Goal:** Make the SA actually optimize for partner/opponent diversity, station balance, and red/blue balance — not just R/B balance.

**Mechanism:**

1. **Define one canonical score function.** Use the formula from `score_schedule()` (quadratic partner/opponent, station term included) since it's the most carefully thought through. Document the formula explicitly with weights and rationale.

2. **Make `delta_swap` compute the full delta** for the canonical score. A 2-swap of teams between two slots affects:
   - Red/blue counts of the two teams across all matches they appear in
   - Station counts of the two teams
   - Partner pairs in matches both teams appear in (and their squares since penalty is quadratic)
   - Opponent pairs across matches both teams appear in
   - b2b status if the swapped teams were in adjacent matches
   - The set of affected matches is `slot_matches[sa] | slot_matches[sb]`, typically O(MPT) matches
   
   Per-swap delta cost: O(MPT × num_teams_per_match) for partner/opponent recomputation in affected matches. For a typical 60-team event with MPT=12, that's ~144 operations per swap — very fast.

3. **Reconcile `build_score_state` with the canonical formula.** Either:
   - Make build_score_state use the canonical formula (slow path; only called on accept and at iteration start)
   - Or compute the canonical score from delta tracking only (no full rescore; verify equivalence with build_score_state once before deleting the latter)
   
   The former is simpler and validates correctness; the latter is faster. Start with former, optimize if profiling shows build_score_state in the hot path.

4. **Verify `score_schedule` and `build_score_state` produce identical scores** for a corpus of seeds. If they don't agree, fix until they do.

5. **Verify SA actually converges with the new delta function.** This may need temperature schedule tuning since the per-step delta magnitudes change.

**Scope:**
- `app/scheduler.py`: rewrite `delta_swap`, reconcile `build_score_state` with `score_schedule`
- `tests/scheduler/`: add unit tests verifying delta_swap matches full-rescore difference for randomized swaps
- `tests/phase0_consistency/`: comparison artifacts (before/after schedules at fixed seeds)

**Acceptance:**
- `delta_swap(slot_map, sa, sb, ...)` equals `score(swap_applied) - score(slot_map)` for 100 random seeds × 100 random swaps. (Must be exact, not approximate.)
- `build_score_state` and `score_schedule` produce identical scores on 50 random schedules.
- Wall-clock at default settings (60 teams, MPT=12, 100 iterations) within 2× of current. (Slower is acceptable since we're now doing real optimization; >2× signals delta_swap is too expensive and needs algorithmic improvement.)
- Eval composite drops measurably. Target: from 49.29 to under 35 just from this fix, before any post-passes.

**Why first:** Everything else assumes the SA is actually optimizing. If it isn't (current state), Phases 1-4 layered on top produce smaller wins than they should.

**Risk:** The performance of fully-correct delta_swap may surprise us. If it's too slow (>5× current), we may need to fall back to "full rescore per accept" rather than incremental delta tracking, which is O(N × M) per accept rather than O(M) per swap. Acceptable for short SA runs but would require Phase 4's iteration budget to be re-tuned.

### Phase 1 — Sykes-style station-balance post-pass

**Goal:** Replace the `W_STATION × station_imbalance` term in the inner loop with a separable post-pass that produces near-optimal station distribution per team.

**Mechanism:** After Phase 0's SA converges with stations as a soft term, run a post-pass that operates on within-match station position assignments. For each match, the 6 team slots can be permuted (subject to keeping Red and Blue alliance assignments intact, or with R/B swap if Phase 2 follows). Greedy or assignment-problem-based: for each team, compute current station distribution; for each match the team is in, evaluate whether station permutations within that match move the team toward a more balanced distribution; pick the swap that produces the largest aggregate improvement; repeat until no improvement available.

The Sykes algorithm itself isn't published as pseudocode (Idle Loop's site describes the result, not the implementation). What I'll implement is in the same algorithm class — within-match station permutations to balance per-team distributions — derived from first principles. Sykes's contribution is credited as the motivating work.

**Scope:**
- `app/post_passes/station_balance.py` (new module)
- Remove `W_STATION` term from canonical score function
- `station_post_pass` config flag (default: on after one release cycle)
- Integration in `assign_teams()` after SA terminates
- `tests/phase1_station/`: comparison artifacts

**Acceptance:**
- For (N, MPT) where perfect station balance is mathematically achievable (MPT divisible by 3), 100% of teams get optimal distribution.
- For others, max imbalance per team ≤ ⌈MPT/3⌉ − ⌊MPT/3⌋.
- No regression in pairing, alliance balance, or cooldown metrics.
- Eval composite drops further. Target: max_station_spread metric at "near_optimal" on every fixture.

**Why second:** Biggest single quality win after Phase 0. Eval shows 75% of fixtures are "poor" on max_station_spread; this should drop to 0%.

**Dependencies:** Phase 0 must land first (otherwise station term is removed before delta_swap is fixed and the SA has nothing to optimize).

### Phase 2 — Red/Blue balance post-pass

**Goal:** Replace `W_BALANCE × max_imbalance` term with a separable post-pass that flips entire alliances per match to optimize R/B distribution.

**Mechanism:** For each match, compute the imbalance reduction from flipping all 6 teams between Red and Blue (Red↔Blue swap). Greedy: flip the match with largest reduction; repeat until no flip helps. Provably commutative with all other criteria — flipping alliances within a match doesn't change partners, opponents, separation, or station-within-alliance distribution (which Phase 1 has already balanced).

**Scope:**
- `app/post_passes/rb_balance.py` (new module)
- Remove `W_BALANCE` term from canonical score function
- Note: by this point, removing W_BALANCE leaves delta_swap with only the other terms — so this also tests that Phase 0's delta_swap fix is actually correct end-to-end
- `rb_post_pass` config flag
- `tests/phase2_rb/`: comparison artifacts

**Acceptance:**
- max_color_imbalance ≤ baseline on all eval fixtures.
- SA convergence time drops measurably (one fewer term in inner loop).
- No regression in pairing or station metrics.
- Eval composite drops further.

**Why third:** Smallest of the three remaining cleanups; cleanest separability proof; validates that Phase 0's delta_swap correctly handles a term being removed.

**Dependencies:** Phase 1 (so station is already a separable pass; Sykes-style passes preserve R/B balance, so running R/B after station is simpler than the reverse).

### Phase 3 — Hard cooldown + final inner-loop cleanup

**Goal:** Convert cooldown from soft penalty to hard rejection in move generator and initial-state generators. Bring `docs/PRIORITIES.md` into truthful alignment with the code.

**Mechanism:** As described in [`PHASE_0_HARD_COOLDOWN_BRIEF.md`](PHASE_0_HARD_COOLDOWN_BRIEF.md):
- `delta_swap` returns sentinel (e.g. `-inf` or `None`) for moves that violate cooldown, before computing other deltas
- Initial-state generators reject violating placements during construction
- Cooldown term removed from canonical score function (now structurally unreachable)

By this point, after Phase 1 removed station and Phase 2 removed R/B, the inner-loop score function reduces to just:
- partner repeats² × W_PARTNER
- opponent repeats² × W_OPPONENT
- surrogate count × W_SURROGATE
- match-equity penalties (P5)
- gap maximization (P7)

This is the final shape — focused on the criteria that benefit most from optimization, with everything else handled either structurally (cooldown) or as post-passes (R/B, station).

**Scope:** Everything in [`PHASE_0_HARD_COOLDOWN_BRIEF.md`](PHASE_0_HARD_COOLDOWN_BRIEF.md), with:
- `tests/phase3_cooldown/`: 4-scenario comparison harness as in original brief
- `docs/PRIORITIES.md` updated for cooldown truthfulness
- Final canonical score function documented

**Acceptance:** Per the cooldown brief — zero violations across 200-run fuzz corpus, pathological-weights case produces zero violations, default-config equivalence (post-Phases 0-2) within ±1 metric.

**Why fourth:** By this point the post-passes have reshaped the score function. Cooldown is the last soft penalty in the inner loop. Converting it to hard now is a small cleanup; doing it earlier (per original Phase 0 plan) would have been validating the pattern, but we now have three other phases that also validate that pattern.

**Dependencies:** Phases 0-2.

### Phase 4 — Quality presets (Fair / Good / Best)

**Goal:** Give Stage 2 SA a configurable iteration budget so users can trade wall-clock for schedule quality.

**Mechanism:** Replace hardcoded 100-iteration default with three presets:
- Fair: 500 iterations (sub-second, suitable for templates and what-if)
- Good: 5,000 iterations (under 10s for typical events; default)
- Best: 50,000 iterations (under 90s for 60-team events; for important schedules)

Expose as UI dropdown next to "Generate" and as `&q=fair|good|best` URL parameter. Default to Good.

**Scope:**
- `app/scheduler.py`: iteration count parameterization
- Frontend UI (`static/index.html`, `static/view.html`)
- URL parameter wiring
- Diversity Report displays wall-clock so users see the trade-off

**Acceptance:**
- Best preset's headline metrics ≤ Good's on the same seed across the eval corpus.
- Wall-clock at Best for 60 teams stays under 90 seconds.
- URL reproducibility preserved (same seed + preset → same schedule).
- Eval composite at Best preset within striking distance of MatchMaker. Target: ≤ 25.

**Why fifth:** Phases 0-3 made each iteration cheaper (fewer terms in inner loop) and more focused (delta_swap correctly steers). Adding more iterations now compounds those gains.

**Dependencies:** Phases 0-3.

### Phase 5 — Decision point (formerly "plugin model")

After Phase 4, run the eval harness and assess the result:

| Eval result | Decision |
|---|---|
| Mean composite ≤ 20 (within ~3 of MatchMaker) | Done. Ship the work. Phase 5 plugin model is optional future work. |
| Mean composite 20-30 (between MatchMaker and actual) | Acceptable. Ship and reassess. Plugin model becomes lower-priority; targeted improvements (e.g. tune iteration scheduling, refine post-pass orderings) may close remaining gap. |
| Mean composite > 30 (still significantly worse) | Phase 5 work needed. Two paths: (a) convert greedy Stage 1 to SA optimizer (per `MATCHMAKER_ALIGNMENT_ROADMAP.md`'s old Phase 5); (b) build the algorithm plugin model and add CP-SAT (per `SCHEDULER_QUALITY_ROADMAP.md`'s old Phase 5). Path (a) is faster and lower-risk; path (b) is more general and unlocks the three-layer architecture. |

The decision is made on data, not in advance. Reserve 0.5 day for the assessment.

---

## Validation strategy

Per [`MATCHMAKER_LICENSING_BRIEF.md`](MATCHMAKER_LICENSING_BRIEF.md):

**Primary surface: TBA-actual.** Every phase ends with a re-run of the eval harness using `--adapters frc-scheduler-server,actual`. License-clean, runnable in CI, gives us "is our scheduler getting better?" answer.

**Secondary surface: occasional manual MatchMaker check.** A few times across the project (after Phase 0, Phase 2, Phase 4) we run with `--adapters matchmaker` added to recalibrate the absolute quality ceiling. Personal evaluation use only — not in CI, not in any production pipeline.

**Tertiary surface: per-phase comparison artifacts.** Each phase commits before/after artifacts under `tests/phase{N}_*/` so the reviewer can see tangible benefit per the established pattern from the original Phase 0 brief.

### Eval baselines (current, from 2026-05-09 run)

| Adapter | Mean composite | Wins vs ours | Wins vs actual |
|---|---|---|---|
| matchmaker | 16.65 | 13W-0L | 5W-1L-7T |
| actual | 25.77 | 14W-2L | — |
| frc-scheduler-server | 49.29 | — | 2W-14L |

### Per-phase quality targets

| After phase | Target frc-scheduler-server mean composite | Rationale |
|---|---|---|
| Phase 0 | ≤ 35 | Score function actually steers SA; should jump significantly |
| Phase 1 | ≤ 30 | max_station_spread metric goes from 75% poor to 0% poor |
| Phase 2 | ≤ 28 | max_color_imbalance improves; small additional drop |
| Phase 3 | ≤ 28 | Cooldown is structural; no quality change expected (truthfulness only) |
| Phase 4 | ≤ 25 | More iterations on faster, focused inner loop closes the diversity gap |

If a phase doesn't hit its target, we pause and investigate before continuing. The quality targets are committed before each phase ships; ship-or-investigate is decided on data.

---

## Implementation conventions

These carry over from the existing roadmap and apply uniformly to all phases.

**Opt-in flag pattern.** Every behavior change ships with a config flag (e.g. `consistent_score: true`, `station_post_pass: true`) defaulting to *on*. Previous behavior remains accessible via flag-off for one release cycle, then the old code path is removed in the following phase's PR. Anyone running an event mid-roadmap can pin a stable version.

**Comparison artifact pattern.** Per phase, commit to `tests/phase{N}_*/`:
- `schedule.csv` per branch (full match list)
- `diversity_report.json` per branch
- `metrics.json` per branch (headline numbers)
- `wall_clock.txt` (median over 5 runs)
- `SUMMARY.md` (side-by-side tables, verdict)

**Score function audit.** Each phase that pulls a term out of the score function must include a statement of which terms remain. By end of Phase 3, the inner loop should score only:
- partner diversity² × W_PARTNER (=80)
- opponent diversity² × W_OPPONENT (=60)
- surrogate fairness × W_SURROGATE (=200)
- match equity (P5)
- gap maximization (P7)

Everything else lives in post-passes (Phase 1 station, Phase 2 R/B) or hard constraints (Phase 3 cooldown).

**Documentation alignment.** `docs/PRIORITIES.md` is the source of truth for what the algorithm does. Every phase that changes algorithm behavior updates `PRIORITIES.md` *in the same PR* — not as follow-up. Drift between docs and code is the truthfulness issue Phase 3 exists to fix; future phases must not reintroduce it.

**Algorithm attribution.** Per [`MATCHMAKER_LICENSING_BRIEF.md`](MATCHMAKER_LICENSING_BRIEF.md), the resulting algorithm suite uses the name `sa-saxton-sykes-extended` in code and "Saxton-Sykes SA + Decomposed Cleanups" in user-facing UI. Each post-pass module includes a header crediting the inspiration:

> Implements an independent post-pass for [station balancing | R/B balancing] derived from the published descriptions by [Caleb Sykes | Tom and Cathy Saxton] in the MatchMaker references at `idleloop.com/matchmaker/`. Not a port of MatchMaker code; not a wrapper around the MatchMaker binary.

---

## Out of scope

Items deliberately not covered by this plan:

- **Three-layer architecture refactor** — destination shape but doesn't directly improve schedules. Defer until quality work is done. Phase 5's plugin model is the entry point for that work if it lands.
- **Practice match scheduling** — a distinct optimization concern; separate work item.
- **Playoff scheduling** — different problem entirely.
- **Stage 1 SA optimizer** — listed as old Phase 5 in `MATCHMAKER_ALIGNMENT_ROADMAP.md`. May become Phase 5 here depending on Phase 4 results.
- **CP-SAT plugin** — listed as old Phase 5 in `SCHEDULER_QUALITY_ROADMAP.md`. Same as above.
- **User-supplied MatchMaker schedule import** — flagged as future feature in licensing brief; not blocking quality work.
- **Frontend visual redesign** — UI is fine.
- **Auth / OAuth changes** — orthogonal.
- **Database schema migrations** — none required.

---

## Decision points before each phase

Per the original roadmap convention, each phase's PR includes a decision gate:

- **Before Phase 0:** Confirm the score-function-inconsistency diagnosis. Read `app/scheduler.py` lines 669-865 with this plan in hand; verify the three formulas disagree as described. Greenlight the rewrite.
- **Before Phase 1:** Phase 0 eval results in. Did composite drop to ≤ 35? If yes, proceed. If no, investigate before adding more changes on top.
- **Before Phase 2:** Phase 1 eval. Did station_spread go to 0% poor? If yes, proceed. If no, investigate.
- **Before Phase 3:** Phase 2 eval. Quality work is done after this phase per the targets — Phase 3 is a structural cleanup, not quality work.
- **Before Phase 4:** Phase 3 truthfulness fix is in. Do quality presets still make sense? (Almost certainly yes.)
- **At Phase 5:** Decision based on Phase 4 eval results, per the table above.

---

## Reference material

For implementation context:

- **Eval data:** [`EVAL_FINDINGS.md`](EVAL_FINDINGS.md) — the empirical baseline this work improves
- **Licensing constraints:** [`MATCHMAKER_LICENSING_BRIEF.md`](MATCHMAKER_LICENSING_BRIEF.md) — what's permitted and what isn't
- **FRC manual §13.6.2 (current) / §10.5.2 (historical):** the six-criterion authoritative source for FRC scheduling
- **Saxton MatchMaker white paper:** https://idleloop.com/matchmaker/ — the SA approach we credit and independently implement
- **Sykes station-balancing:** https://idleloop.com/matchmaker/stations.php — the station-balance class of algorithms we credit and independently implement
- **Surrogate-as-3rd-match rule:** in place since 2008, current FRC manual restates it
- **This tool's PRIORITIES.md:** `docs/PRIORITIES.md` — source of truth for criteria alignment

---

*Plan ready for execution. Phase 0 begins next; eval re-run after each phase. The ordering is committed; quality targets per phase are committed; the validation strategy uses TBA-actual primarily and MatchMaker as occasional ceiling-calibration only.*
