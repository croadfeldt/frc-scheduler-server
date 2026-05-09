# Scheduler Quality Improvement Plan

**Repository:** `github.com/croadfeldt/frc-scheduler-server`
**Document type:** Active workstream plan
**Status:** **Active.** Scheduler change-freeze lifted (post-2026mnst). **Phase 0 and Phase 1 complete and ready to ship.** Each phase ships independently with comparison artifacts.

**Progress:**
- ✅ **Phase 0** (Unified Stage 2 with true SA): complete. See `tests/phase0_unified/SUMMARY.md`. Eval shows mean composite drops from 65.80 → 58.27 (best 53.80 → 49.40) at SA=50000.
- ✅ **Phase 1** (R/B balance post-pass): complete. See `tests/phase1_rb/SUMMARY.md`. Best composite 29.20 (target ≤30), mean 51.20.
- ⏳ **Phase 2** (Sykes station post-pass): next.
- ⏳ **Phase 3** (hard cooldown): pending.
- ⏳ **Phase 4** (quality presets): pending.
- ⏳ **Phase 5** (decision point): pending.

**Companion docs:**
- [`EVAL_FINDINGS.md`](EVAL_FINDINGS.md) — empirical results that motivate this work
- [`MATCHMAKER_LICENSING_BRIEF.md`](MATCHMAKER_LICENSING_BRIEF.md) — licensing constraints binding this work
- [`SCHEDULER_QUALITY_ROADMAP.md`](SCHEDULER_QUALITY_ROADMAP.md) — original tactical roadmap (superseded by this doc; retained for historical context)
- [`MATCHMAKER_ALIGNMENT_ROADMAP.md`](MATCHMAKER_ALIGNMENT_ROADMAP.md) — pre-licensing-brief roadmap (superseded; retained)
- [`PHASE_0_HARD_COOLDOWN_BRIEF.md`](PHASE_0_HARD_COOLDOWN_BRIEF.md) — implementation-ready brief for cooldown (still valid; reused as Phase 3 here)
- [`THREE_LAYER_ARCHITECTURE_DESIGN.md`](THREE_LAYER_ARCHITECTURE_DESIGN.md) — destination architecture (deferred until quality work is done)

---

## TL;DR

Eval data showed our scheduler is significantly worse than MatchMaker (mean composite 49.29 vs. 16.65) and worse than FRC's actually-played schedules (25.77).

**Two findings shape this plan:**

1. **The score function was inconsistent across three places in `app/scheduler.py`.** The SA in `assign_teams` was steering only on R/B balance because `delta_swap` ignored the other terms. *(Fixed in the Phase 0 work already in /tmp; tested and ready.)*

2. **`assign_teams` is mathematically a no-op for the canonical score.** Verified empirically: 1000 random team-to-slot permutations on the same abstract schedule all produce *identical* scores. Stage 2 as it exists today only relabels which team wears which slot's number; it cannot change partnership/opponent/station/balance counts. **All structural quality decisions are made in `generate_matches`.**

**Architectural reframe (Chris's call, 2026-05-09):**

| Conceptually | Code today | Reframed code |
|---|---|---|
| Stage 1: when do matches happen? | day_config layer (already separate) | day_config layer (unchanged) |
| Stage 2: who plays where, with whom, against whom, in which color, at which station, on which surrogate slot? | `generate_matches` (calls itself "Stage 1") + `assign_teams` (calls itself "Stage 2", does nothing of substance) | One unified `assign_schedule` that takes real teams and produces real matches directly |

The naming has been backwards. `generate_matches` does the structural work; `assign_teams` is a vestigial relabeling layer. **Phase 0 expands to: rewrite `generate_matches` as a true SA over the canonical score, accepting real team numbers directly, and remove `assign_teams`.**

| Phase | What | Effort | Expected impact |
|---|---|---|---|
| 0 (REFRAMED) | Convert `generate_matches` to true SA over canonical score; accept real teams; remove `assign_teams` | 4-5 days | Largest single quality win; closes ~half the gap to MatchMaker |
| 1 | R/B post-pass on slot-level structure (flip whole-match R/B) | 1 day | Eliminates max_color_imbalance as a poor metric |
| 2 | Sykes-style station post-pass (within-match station permutation) | 2-3 days | Eliminates max_station_spread as a poor metric |
| 3 | Hard cooldown enforcement (per Phase 0 cooldown brief) | 0.5 day | Truthfulness fix; pathological-weights robustness |
| 4 | Quality presets (Fair / Good / Best) | 1 day | More iterations on a faster, focused inner loop |
| 5 | Decision point | 0.5 day | Decide on CP-SAT, BIBD, or further SA tuning |

**Total: ~9-11 days for Phases 0-4.** After Phase 4 we re-run the eval; if our composite is ≤ 25 (matching actual's mean), the work is done. If still > 30, Phase 5 explores additional approaches.

---

## Critical findings

### Finding 1: Score function inconsistency (already fixed in /tmp Phase 0 work)

`app/scheduler.py` contained three score formulas that disagreed substantively:

- `score_schedule()` (best-of-N picker): quadratic partner/opponent × W_PARTNER/W_OPPONENT, station × W_STATION
- `build_score_state()` (full rescore): linear partner/opponent with hardcoded × 12, × 15, NO station term
- `delta_swap()` (steers SA accept/reject): ONLY computed `max_imbalance × 500`, ignored all other terms

The SA's accept/reject was driven only by R/B balance because `delta_swap` was the hot-path arbiter. This was the proximate cause of "we're 3× worse than MatchMaker" — the SA was effectively performing R/B-balance-guided random search.

**Fix shipped to /tmp:** unified canonical score in `_score_from_state(state)`, full delta tracking in `_assign_apply_swap_delta(state, slot_map, sa, sb, topo)`. Property tests verify delta exactly equals `score_after - score_before` for 300 random swaps × 3 fixture sizes; self-inverse property verified across 50 swap-and-revert pairs.

### Finding 2: assign_teams is mathematically a no-op

**Empirical proof:** 1000 different random team-to-slot permutations on the same Stage 1 abstract schedule all produce identical canonical scores (verified at multiple fixture sizes). Different abstract schedules produce different scores.

**Mathematical reason:** Every component of the canonical score (partner counts, opponent counts, station distributions, R/B balance, b2b, surrogates) is determined by **which slots co-appear in matches and at which stations** — i.e., by `generate_matches`'s output. A team-to-slot permutation π just relabels: `opp_team[(a,b)] = opp_slot[(π⁻¹(a), π⁻¹(b))]`. Sums of squares, max, multisets are all invariant under bijective relabeling of team identifiers.

**Consequence:** Even with the Phase 0 score-consistency fix in place, `assign_teams`'s SA cannot improve the canonical score by any number of iterations. The SA on `slot_map` permutations is searching over an equivalence class. The bug-fix-only Phase 0 was correct but useless.

### Finding 3: Architectural reframe (Chris)

Stage 1 should be match *timing* (already in day_config layer). Stage 2 should be everything structural — placement, R/B, station, partner/opponent, surrogate selection, and team identity. There's no separate "abstract schedule" step; the abstract schedule is just Stage 2 producing all-but-team-identity, and the team identity should be folded into the same step.

This is the right architecture. It eliminates the no-op layer, makes the code do what its labels suggest, and brings all quality optimization into one well-tested SA loop where future improvements (post-passes, hard constraints, CP-SAT) compose cleanly.

---

## Phase plan

### Phase 0 (REFRAMED) — Unify Stage 2 as true SA over canonical score, with real team identities

**Goal:** Rewrite the team-placement code so that one SA loop, operating on real team numbers from the start, optimizes the full canonical score (partner diversity, opponent diversity, station balance, R/B balance, b2b avoidance, surrogate count). Eliminate `assign_teams` as a separate step.

**Mechanism:**

1. **Rewrite `generate_matches` to accept real team numbers** (or a `team_numbers` list) and produce real `Match` objects with real teams. Today it produces matches with slot indices 1..N; tomorrow it produces matches with whatever team numbers were passed in.

2. **Convert the placement loop to a true SA.** Today `generate_matches` is greedy with random candidates: for each match in sequence, generate 60 random 6-team candidate sets, pick the best, commit, move on. This is locally good but globally myopic — a bad early decision locks in repeats that later matches can't undo.

   The replacement is a two-phase placement:
   - **Construction phase:** keep the greedy round-1-then-best-of-N constructor as the *initial state* for the SA. It produces a feasible schedule (covers all teams, respects MPT, respects surrogate model) that may not be optimal.
   - **Optimization phase:** run SA on the constructed schedule. Move generator: random 2-swap of teams between two match slots (i.e., move team T_i out of match M_a's red[k] and move team T_j out of match M_b's blue[m] and swap them). The SA's accept/reject is driven by the canonical-score delta (the helpers I've already built — `_score_from_state`, `_assign_apply_swap_delta`, `_assign_topology` — transfer directly).
   - The SA optimizes over the *full structural space* including which teams are in which match, not just team-to-slot relabeling.

3. **Hard constraints stay hard.** Constraints that should never be violated by construction:
   - Each non-surrogate team plays exactly MPT matches; surrogate teams play MPT+1
   - No team appears twice in the same match
   - No team violates cooldown (Phase 3 makes this structural; for now it's a soft penalty)
   - Surrogate placement follows FRC §10.5.2 (3rd appearance for pre-picked surrogate teams)

   Move generator filters: a 2-swap is rejected if it would put the same team in both alliances of a match, or would change a team's appearance count, or (post-Phase 3) would violate cooldown.

4. **Remove `assign_teams` entirely.** The `slot_map` API contract is preserved as a backward-compatibility shim:
   - `slot_map = {1: team_1, 2: team_2, ..., N: team_N}` for any consistent labeling (the natural choice: `slot i = team_numbers[i-1]` after sorting by team number)
   - Stored in `AssignedSchedule.slot_map` for DB compatibility
   - Frontend reads it as before
   
   **Why a shim instead of removing `slot_map` from the DB schema:** `AssignedSchedule.slot_map` and `AssignedScheduleHistory.slot_map` are persistent JSON columns with downstream consumers (frontend code, V2 URL encoding, FMS export, named history restore). Removing them is a separate migration that touches the DB, the URL encoding spec, and the UI. Keeping the shim isolates Phase 0 to scheduler internals; the schema cleanup is a follow-up if/when worth doing.

5. **Endpoint consolidation.** Today there are two endpoints: `POST /api/abstract-schedules/generate` (Stage 1) and `POST /api/abstract-schedules/{id}/assign` (Stage 2). Under the reframe these merge conceptually, but for backward compatibility:
   - `/generate` continues to exist; its output is the Stage 2 result with team numbers stripped (slots filled from `range(1, N+1)`). This gives the existing UI's "preview a schedule before committing teams" UX.
   - `/assign` continues to exist; it just runs the same code with real teams instead.
   - Both endpoints share the same internal `_assign_schedule(num_teams, matches_per_team, ideal_gap, team_numbers, weights, n_iterations, seed)` function.
   - In a follow-up phase, the UI can be reorganized to make this unification visible (e.g., one "Generate Schedule" button that knows which event's teams to use). That's UX work, separate from this scheduler change.

**Scope:**

- **`app/scheduler.py`:**
  - Refactor the canonical score helpers from /tmp (`_score_from_state`, `_build_state_from_matches`, `_assign_topology`, `_assign_build_state`, `_assign_apply_swap_delta`) — they apply directly; just need to be wired into the new placement loop instead of `assign_teams`'s SA loop
  - Rewrite `generate_matches` to:
    - Accept `team_numbers: list[int]` (default to `list(range(1, num_teams+1))` if not given, preserving existing slot-index behavior for the "abstract schedule" preview)
    - Run the construction phase (greedy, as today, but with team_numbers in place from the start)
    - Run the new SA optimization phase using the canonical-score delta machinery
  - Remove `assign_teams`, `run_assignment_worker`, `run_assignment_chunk`
  - Remove `build_score_state` (orphaned after Phase 0)
  - Keep `score_schedule` as the public scoring entrypoint (now a wrapper around `_build_state_from_matches` + `_score_from_state`)

- **`app/main.py`:**
  - Update the `/api/abstract-schedules/{id}/assign` endpoint to call the unified placement function with real team numbers
  - Update its progress streaming to reflect the construction-phase + SA-phase split (or keep one combined progress bar; minor UX choice)
  - Keep returning `{slot_map, score}` for compatibility

- **`tests/`:**
  - `test_scheduler_score_consistency.py` already validates the canonical-score machinery; tests for `assign_teams` get rewritten to test the unified function
  - Add a new test: a small fixture run end-to-end that asserts the eval composite improves measurably with the new SA loop (regression guard for Phase 0's actual quality benefit)

- **Documentation:**
  - `docs/PRIORITIES.md`: update the Stage 1/Stage 2 section to reflect the architectural reframe. Stage 1 = day_config (timing); Stage 2 = unified placement (everything structural, including teams)
  - Inline docstrings throughout `scheduler.py`

**Acceptance:**

- All existing tests still pass: V2 URL (36), three-up (23), day_config_v2, smoke test against reviewer numbers
- `_assign_apply_swap_delta` correctness property still holds (delta == full-rescore difference for 300+ randomized swaps × 3 fixture sizes)
- Self-inverse property still holds (50 swap-revert pairs)
- New end-to-end test: 2026mnst 50-trial eval with new placement code shows **mean composite drops from 49.29 to ≤ 35**. *This is the real Phase 0 quality target — the original Phase 0 (just fix the bugs) wouldn't have moved this number; the reframed Phase 0 should move it substantially because the SA now optimizes a search space where it can actually win.*
- `/assign` endpoint contract unchanged: returns `{slot_map, score}` with same semantics
- Wall-clock at default settings (60 teams, MPT=12) within 5× of current. The new SA does real work where the old one did random shuffling, so an increase is expected; 5× is the upper bound before we look at performance.

**Why first:** This is the architectural correction that makes everything else possible. Phases 1-2 are post-passes that operate on the slot-level structure produced by Phase 0; their effectiveness depends on Phase 0 producing a good baseline. Phase 3 (hard cooldown) operates inside Phase 0's move generator. Phase 4 (quality presets) is an iteration-budget tuning of Phase 0's SA loop.

**Risk:**

- **Risk: SA performance with full-delta tracking is too slow.** Per-swap cost is O(MPT × num_teams_per_match) ≈ 144 ops for typical events; should be sub-millisecond. If profiling shows otherwise, fall back to "full rescore on accept" (O(N × M) per accept) which is acceptable for shorter SA runs.
- **Risk: SA gets stuck in local optima from bad construction.** Mitigation: random-restart pattern (multiple iterations from different greedy initial states, take the best), which is what the existing `run_iterations_worker` already does. Phase 0 keeps that pattern.
- **Risk: Removing `assign_teams` breaks something not caught in audit.** Mitigation: comprehensive grep of repo + frontend; UI tests; the slot_map shim preserves the API contract.
- **Risk: 4-5 day estimate is too aggressive.** Mitigation: the canonical-score helpers are already written and tested; the new work is wiring them into a different control flow + writing the construction-then-SA pattern. If it stretches to a week, that's still bounded.

**Salvage from /tmp work:** All five canonical-score helpers (`_build_state_from_matches`, `_score_from_state`, `_assign_topology`, `_assign_build_state`, `_assign_apply_swap_delta`) and four of five property tests (the fifth — `test_assign_teams_runs_and_improves_score` — was tautologically passing because the SA was a no-op; replace with the real composite-improvement check). The refactored `score_schedule` is shipped. The /tmp Phase 0 work is ~30% of reframed Phase 0; the remaining 70% is wiring it into `generate_matches` and removing `assign_teams`.

### Phase 1 — Red/Blue balance post-pass on slot-level structure

**Goal:** Replace the `W_BALANCE × max_imbalance` term in the canonical score with a separable post-pass that flips entire alliances per match to optimize R/B distribution.

**Mechanism:** For each match in the Phase 0 output, compute the imbalance reduction from flipping all 6 teams between Red and Blue (Red↔Blue swap of the whole match). Greedy: flip the match with largest reduction; repeat until no flip helps. Provably commutative with all other criteria — flipping a whole alliance within a match doesn't change partners (red triangle stays red, blue stays blue, just relabeled), opponents (cross-alliance pairs unchanged), separation (same matches), or station-within-alliance distribution (Phase 2 balances stations; running Phase 1 first or last gives the same result on average since R/B flip preserves which alliance each team is in within their own balance).

**Scope:**
- `app/post_passes/rb_balance.py` (new module)
- Remove `W_BALANCE` term from canonical score
- `rb_post_pass` config flag (default: on after one release cycle)
- Integration after Phase 0's SA terminates
- `tests/phase1_rb/`: comparison artifacts

**Acceptance:**
- max_color_imbalance ≤ baseline on all eval fixtures
- No regression in pairing or station metrics
- Eval composite drops further. Target: ≤ 30.

**Why second:** Smallest of the post-passes; cleanest separability proof. Operates on whole-match flips rather than within-match permutations. Fast to implement; sets up the post-pass pattern for Phase 2.

**Dependencies:** Phase 0.

### Phase 2 — Sykes-style station-balance post-pass

**Goal:** Replace the `W_STATION × station_imbalance` term in the canonical score with a separable post-pass that produces near-optimal station distribution per team.

**Mechanism:** After Phase 0+1, run a post-pass that operates on within-match station position assignments. For each team, compute current station distribution; for each match the team is in, evaluate whether station permutations within that match (without flipping R/B alliances — Phase 1 already balanced those) move the team toward a more balanced distribution; pick the swap that produces the largest aggregate improvement; repeat until no improvement available.

The Sykes algorithm itself isn't published as pseudocode (Idle Loop's site describes the result, not the implementation). What I'll implement is in the same algorithm class — within-match station permutations to balance per-team distributions — derived from first principles. Sykes's contribution is credited as the motivating work.

**Scope:**
- `app/post_passes/station_balance.py` (new module)
- Remove `W_STATION` term from canonical score
- `station_post_pass` config flag
- `tests/phase2_station/`: comparison artifacts

**Acceptance:**
- For (N, MPT) where perfect station balance is mathematically achievable (MPT divisible by 3), 100% of teams get optimal distribution
- For others, max imbalance per team ≤ ⌈MPT/3⌉ − ⌊MPT/3⌋
- No regression in pairing or alliance balance
- Eval composite drops further. Target: ≤ 28.

**Why third:** Largest of the post-passes; uses the pattern established by Phase 1.

**Dependencies:** Phase 0, Phase 1.

### Phase 3 — Hard cooldown enforcement

**Goal:** Convert cooldown from soft penalty to hard rejection in the move generator and initial-state generators. Bring `docs/PRIORITIES.md` into truthful alignment.

**Mechanism:** As described in [`PHASE_0_HARD_COOLDOWN_BRIEF.md`](PHASE_0_HARD_COOLDOWN_BRIEF.md), but applied to Phase 0's unified placement code:
- Move generator's 2-swap filter rejects any swap that would push a team's match-to-match gap below `cooldown`
- Construction phase rejects violating placements during initial schedule build
- `cooldown_deficit × −1000` term removed from canonical score (now structurally unreachable)

**Scope:** Per the cooldown brief, with paths updated to the post-Phase-0 code structure. `tests/phase3_cooldown/`: 4-scenario comparison harness from the original brief.

**Acceptance:** Per the cooldown brief — zero violations across 200-run fuzz corpus, pathological-weights case (W_PARTNER=10000) produces zero violations, default-config equivalence within ±1 metric.

**Why fourth:** The hard-cooldown work is well-specified in the existing brief and depends on Phase 0's move generator existing. By this point R/B and station are post-passes, leaving the inner-loop score function focused on partner/opponent diversity + cooldown + b2b — and Phase 3 makes cooldown structural so the inner loop only steers partner/opponent.

**Dependencies:** Phases 0-2.

### Phase 4 — Quality presets (Fair / Good / Best)

**Goal:** Give the SA a configurable iteration budget so users can trade wall-clock for schedule quality.

**Mechanism:** Replace hardcoded iteration count with three presets:
- Fair: 500 iterations of the SA optimization phase (sub-second on typical events)
- Good: 5,000 iterations (under 10s for typical events; default)
- Best: 50,000 iterations (under 90s for 60-team events)

Expose as UI dropdown next to "Generate" and as `&q=fair|good|best` URL parameter. Default to Good.

**Scope:**
- `app/scheduler.py`: iteration count parameterization
- Frontend (`static/index.html`, `static/view.html`)
- URL parameter wiring
- Diversity Report displays wall-clock so users see the trade-off

**Acceptance:**
- Best preset's headline metrics ≤ Good's on the same seed across the eval corpus
- Wall-clock at Best for 60 teams stays under 90 seconds
- URL reproducibility preserved (same seed + preset → same schedule)
- Eval composite at Best preset within striking distance of MatchMaker. Target: ≤ 25.

**Why fifth:** Phases 0-3 make each iteration cheaper (fewer terms in inner loop) and more focused (delta steers correctly). Adding more iterations now compounds those gains.

**Dependencies:** Phases 0-3.

### Phase 5 — Decision point

After Phase 4, run the eval harness and assess:

| Eval result | Decision |
|---|---|
| Mean composite ≤ 20 | Done. Ship it. |
| Mean composite 20-30 | Acceptable. Ship and reassess. Targeted improvements only. |
| Mean composite > 30 | Investigate further. Options: Stage 1 BIBD seeding (deterministic-first phase before SA), CP-SAT plugin for small events, smarter SA temperature schedules. |

The decision is made on data, not in advance. Reserve 0.5 day for the assessment.

---

## Validation strategy

Per [`MATCHMAKER_LICENSING_BRIEF.md`](MATCHMAKER_LICENSING_BRIEF.md):

**Primary surface: TBA-actual.** Every phase ends with a re-run of `scripts/scheduler_eval/runner.py --adapters frc-scheduler-server,actual`. License-clean, runnable in CI.

**Secondary surface: occasional MatchMaker check.** A few times across the project (after Phase 0, Phase 2, Phase 4) for ceiling calibration only. Personal evaluation use, not in CI.

**Tertiary surface: per-phase comparison artifacts** under `tests/phase{N}_*/`.

### Eval baselines (current, from 2026-05-09 run)

| Adapter | Mean composite | Wins vs ours | Wins vs actual |
|---|---|---|---|
| matchmaker | 16.65 | 13W-0L | 5W-1L-7T |
| actual | 25.77 | 14W-2L | — |
| frc-scheduler-server | 49.29 | — | 2W-14L |

### Per-phase quality targets

| After phase | Target frc-scheduler-server mean composite | Rationale |
|---|---|---|
| Phase 0 | ≤ 35 | Real SA optimizing the canonical score over the full structural space |
| Phase 1 | ≤ 30 | max_color_imbalance metric drops to near-optimal |
| Phase 2 | ≤ 28 | max_station_spread metric goes from 75% poor to 0% poor |
| Phase 3 | ≤ 28 | Cooldown is structural; no quality change expected (truthfulness) |
| Phase 4 | ≤ 25 | More iterations on faster, focused inner loop closes diversity gap |

If a phase doesn't hit its target, work pauses and investigates before continuing.

---

## Implementation conventions

**Opt-in flag pattern.** Every behavior change ships with a config flag defaulting to *on*. Previous behavior accessible via flag-off for one release cycle, then removed. Anyone running an event mid-roadmap can pin a stable version.

**Comparison artifact pattern.** Per phase, commit to `tests/phase{N}_*/`:
- `schedule.csv` per branch (full match list)
- `diversity_report.json` per branch
- `metrics.json` per branch (headline numbers)
- `wall_clock.txt` (median over 5 runs)
- `SUMMARY.md` (side-by-side tables, verdict)

**Score function audit.** Each phase pulling a term out of the inner loop must include a statement of which terms remain. By end of Phase 3, the inner loop scores only:
- partner diversity² × W_PARTNER (=80)
- opponent diversity² × W_OPPONENT (=60)
- surrogate fairness × W_SURROGATE (=200)

Everything else lives in post-passes (Phase 1 R/B, Phase 2 station) or hard constraints (Phase 3 cooldown).

**Documentation alignment.** `docs/PRIORITIES.md` is the source of truth for what the algorithm does. Every phase that changes algorithm behavior updates `PRIORITIES.md` *in the same PR* — not as follow-up.

**Algorithm attribution.** Per [`MATCHMAKER_LICENSING_BRIEF.md`](MATCHMAKER_LICENSING_BRIEF.md), the resulting algorithm uses the name `sa-saxton-sykes-extended` in code and "Saxton-Sykes SA + Decomposed Cleanups" in user UI. Each post-pass module credits the inspiration.

---

## Out of scope

- Three-layer architecture refactor (deferred until quality work is done)
- Practice match scheduling
- Playoff scheduling
- BIBD/CP-SAT plugins (Phase 5 candidates)
- User-supplied MatchMaker schedule import (future feature; not blocking quality work)
- Frontend visual redesign
- Auth / OAuth changes
- DB schema migration to remove `slot_map` columns (separate follow-up; preserved as shim during Phase 0)

---

## Decision points before each phase

- **Before Phase 0:** Phase 0 brief is approved (this doc). Architectural reframe confirmed. Begin implementation.
- **Before Phase 1:** Phase 0 eval. Composite ≤ 35? If yes, proceed. If no, investigate before adding more changes.
- **Before Phase 2:** Phase 1 eval. max_color_imbalance fixed? If yes, proceed.
- **Before Phase 3:** Phase 2 eval. max_station_spread fixed? Quality work substantively done after Phase 2; Phase 3 is structural cleanup.
- **Before Phase 4:** Phase 3 truthfulness fix in. Quality presets still make sense? (Almost certainly yes.)
- **At Phase 5:** Decision based on Phase 4 eval results.

---

## Reference material

- **Eval data:** [`EVAL_FINDINGS.md`](EVAL_FINDINGS.md)
- **Licensing constraints:** [`MATCHMAKER_LICENSING_BRIEF.md`](MATCHMAKER_LICENSING_BRIEF.md)
- **FRC manual §13.6.2 (current) / §10.5.2 (historical):** authoritative criterion list
- **Saxton MatchMaker white paper:** https://idleloop.com/matchmaker/
- **Sykes station-balancing:** https://idleloop.com/matchmaker/stations.php
- **This tool's PRIORITIES.md:** `docs/PRIORITIES.md`

---

*Plan ready for execution. Phase 0 begins next; eval re-run after each phase. The architectural reframe is committed; quality targets per phase are committed; the validation strategy uses TBA-actual primarily and MatchMaker as occasional ceiling-calibration only.*
