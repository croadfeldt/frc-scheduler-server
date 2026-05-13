# HANDOFF

State of the world for the next person picking up the FRC Match Scheduler
project. Practical, terse, code-anchored — same convention as the rest of
`docs/`. Read this first if you're new to the codebase or coming back
after a gap.

Last updated: 2026-05-11. Continued multi-thread session that, in
addition to the work already summarized below, captured two new v1.1
workstreams: `workstreams/abstract-library.md` (pre-computed
best-known abstracts per FRC fixture shape, lookup-first / cache-on-
miss) and `workstreams/schedule-quality-reporting.md` (unified quality
framework, consolidating the four overlapping scoring systems and
exposing them in the UI). The latter supersedes
`workstreams/ui-quality-exposure.md` (kept for history). v1.1 in
ROADMAP rewritten around these two; the browser scheduler retirement
(ADR 006) is now ~half a day instead of 2-3 days because of the
library work simplifying it.

Then **shipped Phase A of `workstreams/schedule-quality-reporting.md`**:
`app/quality.py` is the new canonical entry point that the four
quality systems route through. Re-exports the harness primitives,
adds application-friendly entry points (`compute_diversity_report`,
`analyze_against_thresholds`, `composite_score`), and the
`/api/abstract-schedules/{id}/diversity-report` endpoint shrinks from
~145 lines of inline computation to a 13-line wrapper. Frontend
response shape preserved exactly; `renderDiversityCard()` untouched.
13 test suites green (12 existing + new `tests/test_quality.py`).

Then **scrubbed third-party-product name references from user-facing
prose** to limit legal exposure and ill will toward the upstream
authors of the established FRC reference scheduler. Four files
renamed and rewritten generically (the licensing brief, ADR 005, the
alignment doc, and the compare script); ~245 prose substitutions
across 35 files turning comparative-product framings into
empirical-distribution framings. Legitimate technical references kept
(the eval adapter that runs the binary, the xlsx-format parser,
NOTICE attributions, historical test summaries). Cross-references
updated.

Finally **landed `docs/scheduler/quality-metrics.md`**: a living
catalog of every metric we measure or plan to measure, with
definitions, theoretical floors, threshold bands, sources, and an
explicit "calibration in progress" caveat for current threshold
values. Five planned-but-not-implemented metrics (SoS, pair
distribution thresholds, partner-vs-opponent difference, match-gap
distribution, surrogate placement validation) called out as plugin
extensions to be added after the quality framework matures.

Finally **closed out Phase 5 with Plan C**. The diagnostic that had
been running on Stark completed in 30 minutes. Plan B (raise
iteration budget) is ruled out — the station post-pass budget was
scaled 10,000× and `max_station_spread` didn't move, so it's
move-set-limited not budget-limited. The 40×12 fixture experiment
confirmed the sum-of-squares-vs-pair-count framing mismatch: the
lex tuple is at floor but `repeat_opponents` is still poor. Two
Plan C interventions captured in `workstreams/phase5-plan-c.md`:
station post-pass redesign (Plan C-1) and lex tuple extension with
explicit count slot (Plan C-2). Recommended sequencing: Plan C-1
first (smaller change, faster validation), then Plan C-2 (ADR-
governed change, larger blast radius). Total ~2-3 days plus eval
re-runs. Library Phase 2 curation gates on these landing.

Then **direction-changed to long-term "best possible schedule"
investigation** per user request. The time-bound "ship Plan C-1
first" framing was set aside in favor of an upper-bound feasibility
study targeting FIRST-adoption-ready quality posture. New workstream
`workstreams/best-possible-schedule.md` captures the Phase 1
research questions: is the lex tuple shape right (count vs sum-of-
squares vs Saxton role-imbalance); where does CP-SAT become
impractical (frontier of provable optimality); methodology for
declaring "best possible reached"; should the two-stage
architecture stay or fold to single-stage CP-SAT for small
fixtures; plus cooldown/MPT/reproducibility questions. Phase 1 is
research-only; ADR 007 + ADR 008 drafts plus a measurement report
ship as a single review package before any Phase 2 code lands. CP-
SAT (Google OR-Tools, Apache 2.0) approved as a project dependency.
Phase 5 Plan C doc marked historical (sequencing superseded);
Plan C-3 (Saxton role-imbalance) added to that doc and folded into
Best Possible Schedule Q1. ROADMAP v1.1 line items rewritten:
Plan C-1/C-2/C-3 superseded by Best Possible Schedule Phases 2-3;
Schedule Quality Reporting Phase B/C and Abstract Library Phase 1
remain safe-to-ship independently as measurement and infrastructure
work.

Then **kicked off Phase 1 investigation work**. Installed OR-Tools
9.15 (Apache 2.0, ~80MB) via separate `requirements-research.txt` to
keep production container lean. Built first-cut CP-SAT model for
Stage 1 pairing in `scripts/cp_sat/pairing_optimum.py`: decision
variables for `in_match[m,t]` and `on_side[m,t]`, derived
partner/opponent indicators per match-pair, objective minimizes
`par_quad`. Pairing-only formulation deliberately ignoring R/B color
and station position (commutative with pairing per existing post-
pass architecture). Five measurement runs across small fixtures:
6t×4MPT proves OPTIMAL in 6.4s (correctness confirmed); 6t×6MPT
finds feasible at 60s but LP bound loose (62 vs achievable ~90);
8t×6MPT × cd=2 mathematically infeasible (confirmed by formula);
12t×6MPT × cd=2 finds feasible=192 in 60s, no improvement at 180s
(solver stuck). Findings captured in
`scheduler/phase1-q2-first-cut.md` with F1-F4 follow-ups: refine
encoding (symmetry-breaking, reified constraints, warm-start),
fix SA `IndexError` at 12t×6MPT, build CP-SAT for R/B+station
post-passes, document feasibility boundary. Conclusion: with
current encoding the CP-SAT frontier may be smaller than initially
hoped (~12 teams ceiling); encoding refinement is the next step.

While CP-SAT was running, derived **closed-form cooldown
feasibility formula** for Q5: `cooldown_max = floor((M-1)/(MPT-1))`
where `M = ceil(n·MPT/(2·tpa))`. Generated the full FRC-common
space table. F5-1: no infeasibility at typical cooldown across all
FRC-common shapes — §10.6.6 back-to-back exception correctly
handles the genuinely-tight cases (n≤8 with high MPT). F5-2:
substantial cooldown headroom in most fixtures (36t×7MPT has
cooldown_max=6 vs typical=3) suggests quality-vs-cooldown is worth
empirically testing. F5-a follow-up captured: Stark job to measure
whether tightening cooldown beyond default improves pairing
quality, ~3-5 hours wall-clock. Captured in
`scheduler/phase1-q5-cooldown-feasibility.md`.

No Stark job kicked off this session — not yet in position to do
so meaningfully. CP-SAT model needs encoding refinement first; SA
has the 12×6 bug. The natural Stark candidate is F5-a (quality-vs-
cooldown sweep) but that runs after F2 (SA bug fix). Tracked.

Then in the **2026-05-12 session** picked up F2 (the SA bug fix at
12×6). Reproduced the bug — but it turned out the SA was correct;
the construction phase was producing malformed matches with short
alliances (e.g. blue=(11, 9) — only 2 teams instead of 3) on tight
fixtures. Two issues identified:

1. **Cooldown infeasibility wasn't validated.** Requesting
   ideal_gap=3 on 12×6 exceeds cooldown_max=2 (per the Q5 formula);
   the construction phase tried anyway and produced garbage. Fixed
   with a feasibility check at the top of `generate_matches` that
   raises ValueError with the Q5 formula's explanation.
2. **Construction can paint itself into a corner on tight
   fixtures even at feasible cooldown.** Empirical malformation
   rates measured (30 seeds per fixture): 10t×6 13%, 12t×7 17%,
   12t×6 3%, 16t+ 0%. Production fixtures (≥36 teams) unaffected.
   Added `ConstructionMalformedError` exception class; construction
   now detects malformed output and raises clearly so callers can
   retry. Test helper `make_test_schedule` retries up to 20 times
   with deterministic seed progression.

Captured as Phase 1 Q4 first-cut data point:
`scheduler/phase1-q4-construction-quality.md`. The architectural
implication is that **CP-SAT's small-fixture optimality regime
(Q2) overlaps exactly with where greedy construction fails (Q4)**
— suggesting a possible Q4 answer of "CP-SAT for tight fixtures,
greedy+SA for the rest." Contingent on F1 (CP-SAT encoding
refinement) succeeding. 13 test suites pass.

Then in the same session picked up **F1** (refining the CP-SAT
encoding). Built `pairing_optimum_v2.py` with three improvements:
(1) tighter linear-reified indicator encoding (replacing
`AddBoolAnd(...).OnlyEnforceIf(...)`); (2) linear histogram
objective `Σ k² × count_at_k` (replacing
`AddMultiplicationEquality`); (3) anchor-based symmetry breaking
(team 1 plays in match 0 on side A). Tried a full lex-ordering
symmetry break first, removed it after it returned INFEASIBLE on
cases known to be feasible.

**F1 encoding refinement was modest:** ~2× speedup on the easy
6×4×1 case; no improvement on the hard 12×6×2 case (same par_quad
= 192). Mapped CP-SAT's feasibility frontier: finds valid schedules
on 14t/18t/20t/24t × 6MPT in 30s; correctly identifies 16t × 6MPT
× cd=3 as INFEASIBLE (a Q5 boundary case the formula didn't catch).

**The bigger F1 finding came from comparing against SA on
12×6×2.** Across 18 SA=500K trials and 5 SA=2M trials, the SA
**never** produced a schedule with cooldown_violations=0 on this
fixture. Best SA result: par_quad=116 with cooldown_violations=31
(invalid by paramount-cooldown). CP-SAT result: par_quad=192 with
cooldown_violations=0 (valid). Per the lex tuple's paramount-
cooldown rule, CP-SAT wins decisively even though its pairing is
worse.

This is direct Q4 architectural data: **on tight fixtures, our SA
cannot satisfy the FRC §10.5.2 paramount cooldown criterion. CP-
SAT can — even with sub-optimal pairing.** The architectural shape
is becoming clear: CP-SAT construction for tight fixtures (where
SA fails), SA refinement on top. New `scheduler/phase1-f1-cpsat-
refinement.md` captures findings with F1-a (audit SA's accept/
reject for paramount cooldown), F1-b (warm-start CP-SAT
sequentially), F1-c (CP-SAT-construction prototype), and F1-d (Q5
boundary-infeasibility caveat — landed). Q5 doc updated with the
16×6×3 counter-example.

Then ran **F1-a** (SA paramount-cooldown audit). **Verdict: no
bug.** Audited four functions in `app/scheduler.py`: `_lex_compare`
(line 1785), `_swap_preserves_cooldown` (line 1728), `_sa_optimize`
(line 1898), `_score_from_state` (line 1084). All correctly
implement ADR 002's paramount-cooldown semantics: pre-apply filter
rejects cooldown-worsening swaps; defense-in-depth lex-compare
reject at line 2025 prevents any cooldown-worsening trade; stochastic
uphill never fires on index 0 (cooldown).

Empirical confirmation on 12×6×2 with a cd=50 starting state (50,000
random swap attempts):

  invalid_swap rejects:       31,565 (63.1%)
  cooldown-filter rejects:    13,759 (27.5%)
  cooldown-neutral accepts:    4,659 (9.3%)
  cooldown-IMPROVING accepts:     17 (0.034%)
  cooldown-worsening accepts:      0 (filter never bypassed)

At 0.034% improvement rate, reducing cd=50→0 needs ~300M attempts;
SA runs 2M. **The 2-swap neighborhood doesn't contain enough
cooldown-improving moves to escape construction's bad starts.**

A second experiment characterized construction quality directly:
200 construction attempts on 12×6×2 with `n_sa_iterations=0`:

  malformed (caught by F2's check):  24 (12%)
  well-formed schedules:            176
  cooldown_violations distribution: cd∈[49,54], clustered tightly
  schedules with cd=0:                0

**Construction doesn't even attempt to satisfy paramount-cooldown on
tight fixtures.** The system relies on SA self-heal which can't work
in the 2-swap neighborhood. Both halves of the system are
individually doing what they were designed to do; together they
produce broken output on tight fixtures.

**Q4 architectural finding now empirically airtight:** SA-on-greedy-
construction structurally cannot satisfy FRC §10.5.2's paramount
criterion on tight fixtures. CP-SAT finds cd=0 trivially on the same
fixtures. No code changes from the audit — code is correct.
Production fixtures (≥36 teams) reach cd=0 from construction
trivially; the pattern is small-fixture-only. Captured in
`scheduler/phase1-f1a-sa-cooldown-audit.md`. F1-c (CP-SAT-as-
construction prototype) is now strongly motivated and is the natural
next code-and-measure task. New follow-up F1-e captured: audit eval
methodology — schedules with cd>0 should be flagged as invalid
output, not aggregated alongside valid ones (affects past eval data
on tight fixtures).

Then ran **F1-e** (eval methodology audit). Identified five gaps in
the eval pipeline's paramount-cooldown handling:

  1. `Fixture` had no `cooldown` field; harness used universal
     `min_match_gap ≥ 4` threshold regardless of fixture size.
  2. `THRESHOLDS` had no "invalid" tier — paramount violations
     classified as merely "poor".
  3. `_composite_score` weighted poor=10, so cd=50 schedules with
     good pairing could outrank cd=0 schedules with mediocre
     pairing.
  4. `_select_best` could pick invalid output as winner.
  5. `app/quality.py` mirrored gaps 3 and 4.

**Scope of contamination in past data: zero.** Phase 5's eval
(36-40 team fixtures) trivially produces cd=0 schedules; the gap
matters only on tight fixtures where we hadn't yet run the
harness.

**Fix shipped** (minimal-invasive, fully backward-compatible):
`Fixture.cooldown: int | None = None`, `AnalysisReport.is_valid_paramount`
+ `cooldown_violations` fields, `analyze()` computes them when
fixture cooldown is set, `_composite_score` returns `inf` for
paramount-invalid, `_select_best` ranks valid-first, `app/quality.py`
mirrors with new `cooldown` kwarg on `analyze_against_thresholds`.
11 new test assertions in `tests/test_quality.py`. Legacy fixtures
without cooldown declared behave identically to before. New
`docs/scheduler/phase1-f1e-eval-methodology.md` captures the audit
findings and fix. F1-c is now methodology-clean to run.

Then locked in **D5** (paramount cooldown = 2 project-wide,
user-tunable) per user direction. Verified actual FRC §10.5.2
text by fetching the 2026 Game Manual: cooldown IS priority #1
but phrased as "at least the minimum required time between
MATCHES (varies by event size)" — a **floor**, not a target.
No specific value or per-size table published anywhere in the
rules. Project commits to **cooldown=2** as default value:
high enough to forbid back-to-back; low enough that one-play-
per-round is structurally always honored; leaves maximum
search-space budget for criteria 2-6 (partner diversity,
opponent diversity, surrogates, color balance, station
distribution). **Cooldown remains user-tunable** in API
(`AbstractGenerateRequest`/`AssignRequest.cooldown` 1-20) and
UI (cooldown + assignCooldown inputs). Updated across the
project: `app/main.py` API defaults, `static/index.html` 5 UI
sites, `app/schedule_derive.py` derivation fallback,
`app/frc_compliance.py` (`DEFAULT_COOLDOWN=2`; audit-trail key
renamed `frc_default`→`project_default`),
`docs/scheduler/FRC_COMPLIANCE.md` examples,
`tests/test_match_sa.py` helper cap, `scripts/cp_sat/pairing_optimum.py`
function/CLI defaults, `scripts/scheduler_eval/fixtures/2026mnst.json`
adds `cooldown: 2`. `tests/test_frc_compliance.py` updated:
hard-coded `cooldown_used=3` replaced with `DEFAULT_COOLDOWN`;
key assertion updated to `project_default`. D5 added to
workstream's "Decisions locked in" alongside D1-D4. Note: a
schedule we produce that satisfies cooldown=2 might not satisfy
a particular event's higher organizer-supplied cooldown — that's
the FIRST-adoption-ready posture (D1) consideration, recorded
but not constraining for current work. 13 test suites pass.

---

## 1 · Where we are

The scheduler operates under **FRC §10.5.2 paramount lexicographic semantics**.
Cooldown is paramount; the remaining criteria are compared lexicographically.
The Python SA + post-passes implement this; the import + assign + view paths
all surface FRC compliance state to the user.

| Workstream | Status | Notes |
|------------|--------|-------|
| V2 day_config (phases 0–5c)                                     | ✓ | Complete from prior sessions. |
| View UX overhaul                                                 | ✓ | Status pills, field-position alliance, source-aware tints. |
| **Phase 0a — Lex score**                                         | ✓ | `score_tuple_for_schedule` returns 8-element tuple; SA accept/reject lex-compare. |
| **Phase 0b — Hard cooldown filter**                              | ✓ | `_swap_preserves_cooldown` filters violations BEFORE state mutation. ~5x SA speedup. |
| **Phase 0c — Targeted move generator**                           | ✓ | Biases SA toward duplicate-pair bottlenecks. 1/3 partner-targeted, 1/3 opponent-targeted, 1/3 random. |
| **Phase 1 — R/B post-pass**                                      | ✓ | `app/post_passes/rb_balance.py`. Whole-match flip + SA. 8 commutativity tests. |
| **Phase 2 — station post-pass**                            | ✓ | `app/post_passes/station_balance.py`. Within-alliance permutation + SA-from-greedy. 12 commutativity tests. |
| Iteration sweep + K* analysis                                    | ✓ | K* > 5M; practical ceiling at 5M. See `docs/scheduler/ITERATION_CEILING.md`. |
| Quality presets (fair/good/best/maximum)                         | ✓ | `app/quality_presets.py`. |
| Competition-approved checkbox + audit trail                      | ✓ | DB columns + `app/frc_compliance.py` + UI surfaces in index + view. |
| /assign chunking fix                                             | ✓ | Each worker runs full SA budget; best-of-N over independent trials. |
| /assign auth-header bug fix                                      | ✓ | `assignTeams()` was sending raw fetch with no Authorization. |
| EventTeam.team_number bug fix                                    | ✓ | Seven sites in main.py; replaced with proper join through `Team.number`. |
| reference schedule import path                                           | ✓ | `state_qual_schedule.txt` → FMS xlsx → import flow. Practice sheet supported. |
| Practice-import wiring (storage + UI + commit)                   | ✓ | XLSX/CSV cache stores practice; preview UI renders it; commit body sends it. |
| Import flow event-id resolution                                  | ✓ | `ensureEventLoadedForImport` helper used by 3 import call sites. |
| reference comparison language softened                          | ✓ | Removed all "improves over the reference" / "improvement over reference" framing across UI + tests + docs. |
| **Practice-from-the reference scheduler-xlsx** (this session)                 | ✓ | Stale-cache invalidation + datetime time-cell handling + derived practiceDay. §4.7. |
| **Print + export unauthenticated** (this session)                | ✓ | `render-pdf` no longer requires auth; matches `/teams/export` posture. §4.8. |
| **Session-deliverable protocol documented** (this session)       | ✓ | Two-tarball + commit-ready-commands + commit-message-style convention canonicalised in `REPRODUCTION_PROMPT.md`. §4.9. |
| **Cycle-change off-by-one regression** (this session)            | ✓ | `afterMatch=N` now correctly applies new ct to gap N→N+1 per V2_SPEC §7 (was N+1→N+2). Six application sites fixed. §4.10. |
| **Eval-harness SA path measurement** (this session)              | ✓ | Adapter was defaulting `sa_iterations=0` since Phase 0; both historical baselines reflected SA-disabled config. Default corrected, CLI flags added, regression test landed. **Re-run completed: mean composite 30.64** (vs 40.12 SA-disabled baseline). Phase 5 active; failure narrowed to `max_station_spread` + `repeat_opponents` on high-MPT fixtures. §5.9. |
| **Doc structure reorganization** (this session)                  | ✓ | New `docs/ROADMAP.md` as single source of truth for "where we're going"; new `docs/decisions/` with ADRs 001–005 capturing lex tuple, FRC paramount, three-layer architecture, no-reproducibility-guarantee, and reference-as-peer; renamed `docs/RBAC_MODEL.md` → `docs/workstreams/rbac.md`, `docs/SCHEDULE_LIFECYCLE.md` → `docs/workstreams/schedule-lifecycle.md`, `docs/UI_QUALITY_EXPOSURE.md` → `docs/workstreams/ui-quality-exposure.md`, `docs/scheduler/QUALITY_IMPROVEMENT_PLAN.md` → `docs/workstreams/scheduler-quality.md`, `docs/SCHEDULE_COMPARISON_AND_NAMED_HISTORY.md` → `docs/workstreams/schedule-comparison.md`. New `CONTRIBUTING.md` extracts the session-deliverable protocol. README updated to reflect the no-reproducibility-guarantee policy. All cross-references updated. |
| **Seed UI removal** (this session, follow-up to ADR 004)         | ✓ | The "seed:" and "assign seed:" copy-able displays removed from the share bar in `static/index.html`. `copySeed()` / `copyAssignSeed()` helpers deleted. `?seed=` and `?aseed=` no longer emitted in URLs. Autoload-from-seed-only path dropped (sid/aid is the canonical share pointer). Schedule ID and Assignment ID kept — those are DB primary keys, useful. README's URL-parameter table updated. ADR 004 action items marked done. |
| **Browser scheduler retirement** (this session) — promoted       | ☐ | Was a Backlog one-liner; now a v1.1 line item with ADR 006 capturing the Option A decision (server-only construction, browser becomes presentation). Code work not yet started. §5.1 rewritten to reference the ADR. |
| **Abstract library cache-always policy** (this session)          | ✓ | `workstreams/abstract-library.md` clarified to make cache-hit-below-preset-quality explicit. Added Case 3 policy: a user paying for higher preset than the cached entry's budget regenerates and supersedes if better. Every `best`-preset Generate is now an implicit curation run. ROADMAP v1.1 gains a "suggested sequencing when work starts" block making the order explicit. |
| **Schedule Quality Reporting — Phase A** (this session)          | ✓ | `app/quality.py` consolidates the four overlapping quality systems behind one canonical entry point. Re-exports `THRESHOLDS`/`MetricResult`/`AnalysisReport` from `scripts/scheduler_eval/metrics.py`; adds `compute_diversity_report()` (the structures the editor's Quality card needs — pair histograms, theoretical floors, per-slot tables, worst-pair callouts), `analyze_against_thresholds()` (app-friendly wrapper around the harness analyzer), and `composite_score()` (single-number ranking, matches the harness's runner formula). Shape-agnostic input: accepts DB dicts, `app.scheduler.Match` NamedTuples, and `harness_types.Match` dataclasses interchangeably. The `/api/abstract-schedules/{id}/diversity-report` endpoint shrinks from ~145 lines of inline computation to a 13-line thin wrapper; response JSON shape preserved exactly for `renderDiversityCard()` compatibility. New `tests/test_quality.py` (47 assertions across 6 sections) covers shape-agnostic input, frontend-shape contract, harness-equivalence, composite score, theoretical floors, pair-table sanity. First step of `workstreams/schedule-quality-reporting.md` per the v1.1 sequencing in ROADMAP. |
| **Reference-scheduler name scrub** (this session)                | ✓ | Limited legal exposure and ill-will toward the upstream authors of the established FRC reference scheduler by rewriting user-facing prose generically. Four files renamed: `MATCHMAKER_LICENSING_BRIEF.md` → `REFERENCE_SCHEDULER_LICENSING.md`, ADR 005 (`005-matchmaker-as-peer.md` → `005-reference-scheduler-as-peer.md`), `MATCHMAKER_ALIGNMENT_ROADMAP.md` → `REFERENCE_SCHEDULER_ALIGNMENT.md`, `scripts/compare_matchmaker.py` → `compare_reference.py`. ~245 prose substitutions across 35 files. Comparative claims ("competitive with MatchMaker," "beats MM on...") became empirical framings ("at this fixture size, published FRC schedules show..."). Class names (`MatchMakerAdapter`) and adapter identifiers (`"matchmaker"` as CLI flag, `matchmaker.py` adapter file, `MATCHMAKER_BINARY` env var) preserved — the technical machinery that actually runs the external binary keeps its literal name. NOTICE attributions and historical test SUMMARY.md artifacts left alone. ADR 005 reframed: peer-not-competitor framing kept, but applied to "the established FRC reference scheduler" rather than naming a specific tool. 13 test suites green. |
| **Quality metrics catalog** (this session)                       | ✓ | New `docs/scheduler/quality-metrics.md` documents every metric we measure or plan to measure, with definitions, theoretical floors, threshold bands, and sources. Calibration-in-progress note up front: today's threshold values are inherited from initial implementation and not yet validated against a wide corpus of real FRC schedules; recalibration is tracked in Phase E of `schedule-quality-reporting.md`. Five planned-but-not-implemented metrics called out as plugin extensions: Strength of Schedule (Statbotics framework, gated on EPA/rank data integration), pair distribution thresholds, partner-vs-opponent difference per pair, match-gap distribution beyond minimum, surrogate placement validation. Invites community input. Cross-referenced from `docs/README.md`, `app/quality.py` docstring, and `workstreams/schedule-quality-reporting.md` Related section. |
| **Phase 5 diagnostic complete; Plan C is the path** (this session) | ✓ | Stark diagnostic finished 2026-05-10, 30 min wall-clock. Experiment 1: station post-pass scaled 10,000× in budget (5K → 50M iterations); `max_station_spread` did not move from 2; the post-pass's internal SA converged at 50K iters and is move-set-limited. Plan B (more budget) is definitively ruled out. Experiment 2: best-of-10 SA=2M on 40×12 fixture shows `opp_quad`=1060 (at floor by tuple measure) but `repeat_opponents`=148 (poor by count measure) and `max_opponent_repeats`=3 — sum-of-squares vs count framings rank different schedules as "best." New `docs/workstreams/phase5-plan-c.md` captures both interventions: Plan C-1 (station post-pass redesign — cross-match move set first, exact assignment if needed) and Plan C-2 (lex tuple extension with explicit `repeat_opp_count` and `repeat_par_count` slots; requires ADR 007 superseding ADR 001). Recommended sequencing: C-1 first, then C-2. Total ~2-3 days plus eval re-runs. `workstreams/scheduler-quality.md` Phase 5 marked complete; ROADMAP v1.1 line items rewritten to reflect Plan C as the actionable path. |
| **Direction change → Best Possible Schedule workstream** (this session) | ✓ | User redirected from time-bound "ship Plan C-1 first" toward long-term upper-bound feasibility study with FIRST-adoption-ready posture. New `docs/workstreams/best-possible-schedule.md` captures Phase 1 (research-only): 7 investigation questions covering lex tuple shape (count vs sum-of-squares vs Saxton role-imbalance), CP-SAT applicability frontier (Apache 2.0; approved as project dependency), methodology for declaring "best possible reached," two-stage architecture re-evaluation, cooldown's solution-space role, MPT vs quality ceiling, reproducibility guarantee. Phase 1 deliverable: ADR 007 (lex tuple shape) + ADR 008 (reproducibility) drafts plus a measurement report, ship as a single review package before any code lands. Phase 2-7 (lex tuple lands, algorithm overhaul with SA + CP-SAT tracks, max-effort Stark measurement, feasibility analysis, standards-quality documentation, library curation) all gate on Phase 1 review. Phase 5 Plan C doc marked historical (sequencing superseded); Plan C-3 (Saxton role-imbalance) added to that doc and folded into Best Possible Schedule Q1. ROADMAP v1.1 line items rewritten. Independent ship work preserved (Abstract Library Phase 1 infrastructure, Schedule Quality Reporting Phases B/C measurement). Principle: research before commitment — no code that we'll just replace once the investigation lands. **Four decisions locked in (D1-D4):** FIRST-adoption-ready treated as constraint (aspirational target); ~1-2 week Phase 1 budget accepted; days-not-hours Stark run for Phase 4 accepted; Phase 6 standards-quality documentation is a real deliverable (Saxton-equivalent paper for our algorithm). |
| **Phase 1 kickoff — Q2 first-cut CP-SAT + Q5 cooldown formula** (this session) | ✓ | OR-Tools 9.15 installed via new `requirements-research.txt` (kept separate from production `requirements.txt` to avoid bloating the container with an 80MB research dep). First-cut CP-SAT model in `scripts/cp_sat/pairing_optimum.py` proves OPTIMAL on 6t×4MPT in 6.4s (model correctness confirmed); finds feasible on 12t×6MPT but doesn't prove optimal in 180s (encoding likely needs symmetry-breaking + reified constraints + warm-start). Five fixture runs measured; findings in `scheduler/phase1-q2-first-cut.md` with F1-F4 follow-ups. Closed-form Q5 cooldown feasibility formula derived: `cooldown_max = floor((M-1)/(MPT-1))`. Full FRC-common space tabulated; finding F5-1: no infeasibility at typical cooldown anywhere in FRC-common space (§10.6.6 handles the genuinely-tight small-event cases). F5-2: substantial headroom suggests quality-vs-cooldown is worth empirically testing (Stark candidate F5-a, ~3-5 hours). Captured in `scheduler/phase1-q5-cooldown-feasibility.md`. Workstream doc updated with in-progress sub-deliverables section. **No Stark job kicked off** — CP-SAT needs encoding refinement first; SA needs 12×6 bug fix first. Stark stays idle until F1 or F2 lands. |
| **F2 → Q4 finding: construction-quality issue on tight fixtures** (this session) | ✓ | Picked up F2 (SA bug fix at 12×6). Discovered: SA was correct; **construction** was producing malformed matches with short alliances (e.g. blue=(11,9) — 2 teams instead of 3). Two fixes shipped: (1) cooldown feasibility validation at the top of `generate_matches` — raises ValueError if ideal_gap > cooldown_max with Q5's formula in the error message; (2) `ConstructionMalformedError` exception class — construction phase now detects malformed output and raises immediately so callers can retry with a different seed. Test helper `make_test_schedule` retries up to 20 times. Production fixtures (≥36 teams) unaffected; small fixtures (10t×6, 12t×7) have 13-17% malformation rate but tests + SA work end-to-end after the retry helper. New `docs/scheduler/phase1-q4-construction-quality.md` captures this as Phase 1 Q4 first-cut data: the SA-on-greedy-construction architecture has a known failure mode on tight fixtures. Architectural implication: **CP-SAT's small-fixture optimality regime (from Q2) overlaps exactly with where greedy construction fails (Q4)** — Q4's answer likely points to "CP-SAT for tight fixtures, greedy+SA for the rest," contingent on F1 (CP-SAT encoding refinement) succeeding. 13 test suites pass. |
| **F1 → bigger Q4 finding: SA fails paramount cooldown on tight fixtures** (this session) | ✓ | Built `pairing_optimum_v2.py` with tighter linear-reified indicators, linear histogram objective `Σ k² × count_at_k`, and anchor-based symmetry breaking. Encoding refinement was modest (~2× speedup on 6×4×1, none on 12×6×2). **The bigger finding:** while comparing against SA on 12×6×2, discovered the SA cannot achieve `cooldown_violations=0` on this fixture — across 18 SA=500K trials + 5 SA=2M trials, every trial produced cooldown_violations≥30. CP-SAT achieves cooldown=0 trivially. Per paramount-cooldown rule (ADR 002), CP-SAT's `(0, 192, ...)` strictly beats SA's `(31, 116, ...)` even though SA wins on pairing. **Direct Q4 data: SA cannot satisfy FRC §10.5.2's paramount criterion on tight fixtures; CP-SAT can.** Also surfaced Q5 boundary-infeasibility refinement: cooldown_max formula is necessary but not sufficient at the boundary (16×6×3 counter-example — formula says feasible at cd=3 but only one play pattern yields 6 plays, so all 16 teams would need the same pattern → infeasibility). Q5 doc updated. CP-SAT feasibility frontier mapped (14-24 teams × 6MPT all find feasible in 30s). New `scheduler/phase1-f1-cpsat-refinement.md` captures findings + F1-a/b/c/d follow-ups. 13 test suites pass. |
| **F1-a audit: SA paramount-cooldown is correctly implemented; failure is move-set reachability** (this session) | ✓ | Audited `_lex_compare`, `_swap_preserves_cooldown`, `_sa_optimize`, `_score_from_state` to determine whether SA's cooldown failure on 12×6×2 was diagnosis (1) "correct logic, bad starting state, can't escape" or diagnosis (2) "lex-compare bug." **Verdict: diagnosis (1).** Code review found all four functions correctly implement ADR 002's paramount-cooldown semantics: pre-apply filter rejects cooldown-worsening swaps, defense-in-depth lex-compare reject prevents accepting any cooldown-worsening trade, stochastic uphill never fires on index 0. Instrumented experiment confirmed: 50,000 random swaps from a cd=50 starting state — 31,565 invalid-swap rejects, 13,759 filter rejects, 4,659 cd-neutral accepts, **17 cd-improving accepts (0.034%)**, ZERO swaps slipped past filter. At this rate, reducing cd=50→0 needs ~300M attempts; SA runs 2M. **The move-set neighborhood doesn't contain enough cooldown-improving moves to escape construction's bad starts.** Second experiment: 200 construction attempts on 12×6×2 produced ZERO schedules with cd=0 (distribution clustered cd∈[49,54]). Construction doesn't try to satisfy paramount-cooldown on tight fixtures; system relies on SA self-heal which can't work in the 2-swap neighborhood. **Q4 architectural answer empirically airtight: CP-SAT-as-construction for tight fixtures, SA-refinement on top.** New follow-up F1-e captured: audit eval methodology — schedules with cd>0 should be flagged as invalid output, not aggregated alongside valid ones (affects past eval data on tight fixtures). No code changes needed — code is correct. New `docs/scheduler/phase1-f1a-sa-cooldown-audit.md`. Workstream + HANDOFF updated. F1-c (CP-SAT-as-construction prototype) is the natural next step. 13 test suites pass. |
| **F1-e: eval methodology fix — paramount-invalid output is no longer aggregated as comparable** (this session) | ✓ | Audited the eval pipeline's paramount-cooldown handling. Found 5 gaps: (1) `Fixture` had no cooldown field; (2) `THRESHOLDS` had no "invalid" tier; (3) `_composite_score` could rank cd=50 schedules above cd=0 schedules with mediocre pairing; (4) `_select_best` could pick invalid output as winner; (5) `app/quality.py` mirrored gaps 3-4. **Scope of contamination: zero** — Phase 5 data on disk is 36-40t fixtures where construction trivially achieves cd=0; tight-fixture eval hadn't happened yet. **Fix shipped (minimal-invasive, fully backward-compatible)**: `Fixture.cooldown: int|None=None`; `AnalysisReport.is_valid_paramount` + `cooldown_violations` fields; `analyze()` computes them when cooldown set; `_composite_score` returns `inf` for paramount-invalid; `_select_best` ranks valid-first via leading invalid_flag in rank tuple; `app/quality.py:composite_score` mirrors; `analyze_against_thresholds` gets new `cooldown` kwarg. Legacy fixtures (no cooldown declared) behave identically to before — no back-compat break. 11 new test assertions in `tests/test_quality.py` covering no-cd legacy, cd=3 typical, cd=100 force-invalid, to_dict exposure. New `docs/scheduler/phase1-f1e-eval-methodology.md`. F1-c is now methodology-clean to run. 13 test suites pass. |
| **D5 decision: paramount cooldown = 2 project-wide, user-tunable** (this session) | ✓ | Verified actual FRC §10.5.2 text by fetching the 2026 Game Manual. Manual confirms cooldown is the #1 priority criterion, phrased as "at least the minimum required time between MATCHES (varies by event size)" — a **floor**, not a maximization target. No specific value or per-size table is published anywhere. Project commits to **cooldown=2** as our default value (high enough to forbid back-to-back; low enough that one-play-per-round is structurally always honored; leaves maximum search-space for criteria 2-6). **Cooldown remains user-tunable** in the API (`AbstractGenerateRequest`/`AssignRequest.cooldown`, range 1-20) and UI (cooldown + assignCooldown inputs). Updated 10 sites: `docs/scheduler/phase1-f1e-eval-methodology.md` (full project-policy section + caveat), `app/main.py:354,414` (API defaults), `static/index.html` (5 UI sites: input defaults, hint text, JS reset + parsing fallbacks), `app/schedule_derive.py:220` (derivation fallback), `app/frc_compliance.py` (`DEFAULT_COOLDOWN=2`; audit-trail key renamed `frc_default`→`project_default`), `docs/scheduler/FRC_COMPLIANCE.md` (request example + audit example + criteria mentions), `tests/test_match_sa.py:make_test_schedule` cap, `scripts/cp_sat/pairing_optimum.py` (function-sig + CLI default), `scripts/scheduler_eval/fixtures/2026mnst.json` (added `"cooldown": 2`). `tests/test_frc_compliance.py` updated: assertions converted from hard-coded `cooldown_used=3` to `DEFAULT_COOLDOWN`; key reference updated to `project_default`. D5 added to workstream `Decisions locked in` section alongside D1-D4. 13 test suites pass. |
| **Schedule Quality Reporting Phase A** (this session)            | ✓ | `app/quality.py` created — unified scoring module consolidating today's four overlapping quality systems. Re-exports from `scripts/scheduler_eval/metrics.py` (THRESHOLDS, MetricResult, AnalysisReport, harness analyze). Adds shape-agnostic input (`_normalize_match` accepts dict/NamedTuple/dataclass), `DiversityReport` with `to_dict()` producing the legacy endpoint JSON shape exactly, `compute_diversity_report` and `analyze_against_thresholds` as application-friendly entry points, `composite_score` matching the runner's formula. `/api/abstract-schedules/{id}/diversity-report` refactored from 145 inline lines down to a 5-line `compute_diversity_report` call. New `tests/test_quality.py` (45+ checks) covers shape-agnostic inputs, frontend JSON contract preservation, threshold-analysis equivalence with direct harness call, theoretical floors, and pair-table sanity. All 13 test suites pass. |
| **v1.1 architecture confirmed** (this session)                   | ✓ | Confirmed the two foundational workstreams for v1.1: abstract schedule library (lookup-first, cache-always-on-miss) and unified schedule-quality scoring (one canonical framework consumed by API, UI, eval harness, and library). Both docs already existed from a prior session; this session re-verified the structure, sharpened the "always cache" emphasis in `workstreams/abstract-library.md`, and confirmed both are referenced from v1.1 of ROADMAP. ADR 006's retirement work simplifies to ~half a day once the library lands. |
| **Abstract library + quality reporting** (this session)          | ☐ | Two new v1.1 workstreams captured. `workstreams/abstract-library.md` defines a lookup-first/cache-on-miss library of pre-computed best-known abstracts per FRC fixture shape; `workstreams/schedule-quality-reporting.md` defines a unified quality framework consolidating today's four overlapping scoring systems with tiered UI exposure. Latter supersedes `ui-quality-exposure.md`. ROADMAP v1.1 rewritten around them. Code work not yet started; design captured for follow-up. |
| Schedule lifecycle (Phases A/B/C/E shipped; D/F/G open)          | ◐ | Auth-mandatory + fork + structural-immutability + is_admin shipped. `event_audit_events` table, lock TTL/heartbeat, lifecycle response field deferred. See `docs/workstreams/schedule-lifecycle.md` and §5.7. |
| RBAC (proper roles + permissions)                                | ☐ | Designed in `docs/workstreams/rbac.md` (5 roles, 7 phases R-1..R-7); zero implementation. Current model is interim `is_admin` flag. Paused pending change-freeze lift + open-question decisions. §5.6. |
| UI exposure of `scheduler_eval` quality data                     | ☐ | Designed in `docs/workstreams/ui-quality-exposure.md` — 4-tier plan to surface per-pair / per-team / lex-tuple / reference-comparison detail in the editor + viewer. Today only the headline diversity card is shown. §5.8. |

---

## 2 · FRC §10.5.2 lex tuple — the canonical scoring model

```
(cooldown_violations,    # paramount — never traded against anything else
 par_quad,               # partner-pair sum-of-squares (penalizes repeats hard)
 opp_quad,               # opponent-pair sum-of-squares
 surrogate_count,
 rb_metric,              # R/B imbalance — variant by num_teams (max-imbalance ≥24, swap-count <24)
 station_pen,            # station distribution penalty (FRC #6)
 surrogate_spread,       # P11
 match_equity)           # P5
```

Comparison: lexicographic, lower = better. Cooldown is paramount —
never accept any swap that worsens it. SA accept-reject uses lex
compare with stochastic uphill on lower-priority criteria only.

Reference fixture (2026mnst, 36 teams × 7 MPT):

| Source                                         | Tuple                          |
|------------------------------------------------|--------------------------------|
| external reference                           | `(0, 252, 416, 0, 3, 65, 0, 0)` |
| Best-of-30 at SA=2M (sweep)                    | `(0, 252, 404, 0, 1, 39, 0, 0)` |
| Best-of-30 at SA=5M (sweep)                    | `(0, 252, 386, 0, 1, 44, 0, 0)` |
| par_quad floor (theoretical optimum)           | 252                             |
| opp_quad floor (theoretical optimum)           | 378                             |

established FRC scheduling is the long-standing community baseline used by
event organizers. Comparing against it is sanity-check, not competition.

---

## 3 · Architecture snapshot

```
            ┌──────────────────────────┐
            │ Browser (static/index.html) │
            │ • Generate (browser SA)     │  ← still client-side, weighted-sum
            │ • Assign Teams              │──┐
            │ • Import (xlsx/csv/pdf)     │  │
            └──────────────────────────┘  │
                                          ▼
           ┌────────────────────────────────────────────┐
           │ FastAPI (app/main.py)                      │
           │ /api/abstract-schedules/{id}/assign        │ ← Python lex SA
           │ /api/schedules/import-{xlsx,csv,pdf}       │
           │ /api/schedules/import-pdf/commit           │
           │ PATCH /api/assigned-schedules/{id}         │ ← accepts day_config + practice_matches
           └────────────────────────────────────────────┘
                                          ▼
           ┌────────────────────────────────────────────┐
           │ app/scheduler.py                           │
           │ • generate_matches() — fresh abstract+SA   │
           │ • _assign_unified() — relabel + SA + posts │
           │ • _sa_optimize() — lex SA over Match[]     │
           │ • Phase 1 (R/B) + Phase 2 (station)        │
           └────────────────────────────────────────────┘
                                          ▼
                            PostgreSQL (asyncpg/SQLAlchemy)
```

**Two-stage data model:**
- `AbstractSchedule` (slot indices 1..N, no team numbers) → reusable across rosters
- `AssignedSchedule` (`slot_map: {1: 3276, 2: 7797, ...}`) → real teams + day_config + practice_matches + competition_approved + audit_trail

**Browser scheduler still exists.** `generateMatches()` at static/index.html:8689 (~500 lines) is a complete client-side scheduler with old weighted-sum scoring. It builds the abstract that the server then takes through `/assign`. The browser uses simpler weighted-sum scoring; the server's lex SA fixes whatever it can on the assign step. **Eventual cleanup**: retire the browser scheduler entirely or update it to match Python lex semantics. Tracked in §5.

---

## 4 · This session's bug fixes

### 4.1 /assign chunking
Pre-fix: 720 chunks × ~694 iters each. Each chunk barely warmed up
before stopping. Result: par_quad ~262 vs floor 252; opp_quad ~470
(construction-quality). Confirmed by user uploading buggy output:
`(0, 260, 462, 0, 3, 45, 0, 0)`.

Fix: each worker runs the FULL iteration budget on its own seed.
Best-of-N over independent SA trials, capped at 30 trials. Wall-clock
≈ single-trial time (workers in parallel). Best-of-N comparison uses
the lex tuple, not the legacy summary float.

`app/main.py:1131-1175` (worker dispatch). `app/scheduler.py:run_assignment_chunk` returns `score_tuple` + `worker_elapsed_s` + `us_per_iter` for diagnostics.

### 4.2 /assign auth header
`assignTeams()` was using raw fetch with `Content-Type` only —
no `Authorization`. Pre-existing bug surfaced by tightened auth dep.
Fix: standard `getToken()` + Bearer token pattern.

### 4.3 EventTeam.team_number
Seven SQL queries referenced `EventTeam.team_number` — column doesn't
exist. Team number lives on `Team.number`, joined via `team_id`.
Fixed all sites: `select(Team.number).join(EventTeam, EventTeam.team_id == Team.id).where(EventTeam.event_id == event_id)`.

### 4.4 Practice matches dropped on import
Three concurrent bugs:
- **Storage:** `pdf_import.parsed = {"matches": ..., "notes": ...}` — practice stripped at write time. Fixed at 4 sites (XLSX + CSV, initial + upsert).
- **Display:** `renderPdfImportPreview` only rendered `d.matches`. Fixed: parameterized `renderPdfImportTable(matches, opts)` with target table id + state path; new practice section in modal HTML.
- **Commit:** `confirmPdfImport` body had only `matches`. Fixed: added `practice` field; backend `PdfImportCommitRequest.practice` accepts it; commit handler prefers body over cached parse.

### 4.5 Import flow event-id resolution
Three import call sites silently created an ad-hoc event whenever
`_currentEventId` was null. Common case: post page-reload from
`/view` link sets `_currentEventInfo` but not `_currentEventId`.

Fix: `ensureEventLoadedForImport(label)` helper. Tries
`_currentEventId`, then typed event code in `eventCodeInput`,
then `_currentEventInfo`, then asks the user before falling back to
ad-hoc. Also: `restoreFromFile` now preserves event across `fullReset`
(was wiping `_currentEventId` before the helper could run).

### 4.6 PATCH endpoint accepts practice_matches
For post-import grafting of practice onto an existing schedule.
Same snapshot-history pattern as day_config edits.

`app/main.py:patch_assigned_schedule`.

### 4.7 Practice-from-the reference scheduler-xlsx — three layered bugs (2026-05-10)

User report: restoring a reference scheduler xlsx with a Practice sheet
landed 42 quals but silently dropped the 6 practice matches, even though
the import preview's `format_detected` line said "FMS xlsx (42 qual,
6 practice)". The string came from the parser; the data was gone.

Three bugs on the `xlsx → /view` path, layered such that each fix is
needed to surface the next:

**Bug A — stale cache poisoning.** `pdf_imports` is content-hash keyed.
Entries written before §4.4's storage fix have `parsed = {"matches",
"notes"}` — no `practice` key. Cache hit returns `practice: []`, the
preview hides the practice section, commit body sends `practice: []`.
`format_detected` was set at parse time so it still mentions the practice
count even though the data is missing — that's the user-visible "it
sees 6 [practice] but doesn't import them."

Fix: in `import_xlsx` and `import_csv` cache-hit branches, check
`"practice" not in cached_parsed` and fall through to a fresh parse.
Cheap (no LLM call), self-healing for any similar future schema bumps.
The dedicated PDF import path has a `?nocache=1` toggle; the restore
path doesn't, so users couldn't bypass this manually.

**Bug B — datetime time-cells.** openpyxl returns Python `datetime`
objects for date/time-formatted cells (typical for the reference scheduler exports).
The parser was doing `str(time_val).strip()`, producing
`"2026-05-15 19:00:00"`. Downstream `_hhmm_to_min` rejects this; cycle
and start/end derivation falls back to defaults (8.0 min cycle,
08:30–17:00). Pre-existing; also affects the app's own xlsx export
which writes `"8:30:00 AM"` strings.

Fix: `xlsx_extract._normalize_time(value)` handles `datetime` /
`time` / `"08:30"` / `"8:30 AM"` / `"8:30:00 AM"` / Excel float serial
→ `"HH:MM"`. Unparseable strings pass through (display still works,
only derivation degrades). Six unit tests in `tests/test_day_config_v2.py
TestXlsxTimeNormalization`.

**Bug C — no derived practiceDay.** Even with practice matches in the
DB, `view.html:3648` requires `cfg.practiceDay && cfg.practiceDay.enabled
!== false` to render the practice tab. `derive_parameters` only
inspected qual matches; the V2 day_config it emitted had one qual day
and no practice block, so the V2→V1 downgrade in `_v2DowngradeToV1ForView`
never produced an `out.practiceDay`.

Fix: `derive_parameters(matches, practice_matches=None)`. New
`_derive_practice_block` helper builds a V2 `practice` block (start =
earliest practice time, end = latest + cycle, cycleTime = modal delta
between consecutive practice matches, with `guaranteed=3` and
`maxFiller=99` per `docs/PRACTICE_DAY.md`). When practice is supplied,
a practice-only V2 day is prepended to `days[]` before the qual day.

`_safe_derive(matches, practice_matches)` updated at all 4 call sites
(xlsx hit + miss, csv hit + miss). Argument is optional and defaults
to `None`, so the existing `test_schedule_derive_emits_v2` test keeps
working with single-arg calls.

End-to-end on the user's `2026mnst-matchmaker-with-practice.xlsx`:
- format_detected: `FMS xlsx (42 qual, 6 practice)` (unchanged)
- `practice.length: 6` (was 0)
- num_days: 2, with practice as day[0] (label "Practice", 19:00–20:00, 10-min cycle) and qual as day[1]
- All confidence flags high

`app/xlsx_extract.py`, `app/main.py`, `app/schedule_derive.py`,
`tests/test_day_config_v2.py`.

### 4.8 Print + export unauthenticated (2026-05-10)

User-visible: clicking Print or Export PDF from `/view` failed with 401
because `view.html` (public spectator/kiosk page) doesn't send an
Authorization header, but `POST /api/schedules/render-pdf` was gated
behind `Depends(require_auth)`. The data those endpoints render is
already exposed publicly via `GET /api/assigned-schedules/{id}` and
the `/view` page itself, so requiring auth on the render path was
inconsistent.

Fix: removed the `user: dict = Depends(require_auth)` param from
`render_schedule_pdf_endpoint`. Mirrors the existing posture of
`GET /api/events/{id}/teams/export` (no auth dep at all). Editor's
`assignTeams`-style auth-bearing fetches from `index.html` continue
to work — the server just ignores the token.

Audit of all print/export-flavoured routes (`@app.get|post(...)`
matching `export|render|print|download|snapshot`):
- `GET /api/events/{event_id}/teams/export` — already unauth
- `POST /api/schedules/render-pdf` — unauth as of this session

Browser-only export paths (`downloadXLSX`, `downloadCSV`,
`downloadJSON` in `static/index.html`) build files in the browser
via SheetJS and don't hit any server endpoint, so they were
already auth-free.

`app/main.py:render_schedule_pdf_endpoint`.

### 4.9 Session-deliverable protocol canonicalised (2026-05-10)

Until this session there was no documented expectation about what a
Claude session should produce when it ends. Each handoff was bespoke.
Result: occasional dropped tarballs, inconsistent commit-message
style, and one stale `REPRODUCTION_PROMPT.md` exclusion in the §9
tarball pattern (which would have silently swallowed any doc updates
to that file — bugged for unknown duration).

Fix: `REPRODUCTION_PROMPT.md` now has a "Session deliverables
(standard process)" section that's the single source of truth for:
- Two-tarball convention (full + changes-only) with the corrected
  exclusion list (no longer drops `REPRODUCTION_PROMPT.md`)
- Commit-ready command sequence (with `apply.sh --build` omitted
  for doc-only commits)
- Commit-message style + canonical example

This handoff's §9 is now a brief operator-cheat-sheet that points
forward to that section. Future Claude sessions read
`REPRODUCTION_PROMPT.md` as part of onboarding, so the convention
propagates without per-session re-explanation.

`REPRODUCTION_PROMPT.md`, `docs/HANDOFF.md`.

### 4.10 Cycle-time-change off-by-one regression (2026-05-10)

User report: cycle-time changes were applying one match late. A change
with `afterMatch=N` was changing the cycle for the gap from match N+1
to match N+2 instead of the gap from match N to match N+1. Direct
contradiction of `docs/V2_SPEC.md` §7, which specifies a worked
example: `block.cycleTime=9, changes=[{afterMatch: 4, cycleTime: 8}]`
should produce match starts at 0, 9, 18, 27, **35**, 43 — match 5
arriving 8 min after match 4 (the new ct), not 9 min.

Root cause: every cycle-change application site used `>` where it
should have used `>=` against `(matchIdx + 1)` (or equivalently in the
capacity counter, fired one iter too late). Six sites:

  1. `static/view.html:3819` — display walker (the user-visible one)
  2. `static/index.html:15210` — practice-day walker `_pracEffectiveCt`
  3. `static/index.html:15560` — qual-day walker `dayCt`
  4. `static/index.html:15612` — `prevDayCt` (used to detect when
     to emit a cycle-change marker; bare `matchIdx >` since matchIdx
     is post-increment / 1-based here)
  5. `static/index.html:15621` — `nextDayCt` (same emitter)
  6. `static/index.html:8425` — `calcMaxMatches` capacity counter,
     where the equivalent fix is `<= matchCount + 1` instead of
     `<= matchCount` (apply change one iter earlier in the loop)

Fix: changed each comparison. The 1-based match index `matchIdx + 1`
must be `>=` the change's `afterMatch` for the change to apply at
this iter — match N's own slot is the first to use the new ct, per
spec.

New regression test `tests/test_cycle_change_walker.js` runs in two
modes: substring guards on the production source pin the `>=` (and
`<= matchCount + 1`) at every site, and a faithful walker re-
implementation reproduces V2_SPEC §7's worked example exactly. An
explicit anti-test runs the buggy `>` walker to confirm the two
semantics are actually distinguishable (buggy walker puts match 5
at 36 instead of 35; new test catches that).

`static/view.html`, `static/index.html`,
`tests/test_cycle_change_walker.js`.

---

## 5 · Open items

### 5.1 Browser scheduler retirement

**Status:** Promoted to v1.1 in ROADMAP. Architectural decision
captured in ADR 006: Option A (server-only construction).

The client-side `generateMatches()` in `static/index.html` runs
the original weighted-sum scoring with construction-only logic
(no SA pass). The server's `generate_matches()` runs the
Phase 0+1+2 lex SA pipeline that the eval measures. Users who
click "Generate" in the editor without subsequently clicking
"Assign Teams" get the JS path output, which is materially worse
than the project's quality measurements suggest the algorithm
produces.

ADR 006 commits to retiring the browser path entirely:
construction becomes server-only via `/api/generate-abstract`,
the browser becomes presentation, the duplicate
`generateMatches()` definitions in `static/index.html` are
removed, the practice-match call site gets a server analog, and
the "Placement Criteria" panel (which lets users tweak weights
for the now-removed JS path) is removed or reframed as
informational.

Estimated 2-3 days of focused work. Action items detailed in
ADR 006.

### 5.2 Container parallelism investigation
User reported 2m 48s wall-clock for "Best" preset (2M iters × best-of-30)
on the OpenShift container. Math says 30 × 2M iters at ~37μs/iter on
12 effective cores = ~187 seconds minimum. 168 actual is *faster* than
that — suggests trials may not all be running their full budget, OR
container per-iter cost is shorter than the test environment.

`app/scheduler.py:run_assignment_chunk` now logs `worker_elapsed_s` +
`us_per_iter` per worker. After the next "Best" run, check:
```bash
oc logs deploy/<app-pod> --since=10m | grep "Stage 2 worker"
```

If all 30 workers report `iters=2000000` with `elapsed≈75s`, we're
fine — the schedule quality just reflects best-of-30-at-2M variance.
If many show truncated iterations or excessive elapsed, investigate
further (CPU contention, broken pool, FastAPI cancellation).

### 5.3 par_quad=256 outlier on container vs Stark sweep stdev=0
Stark sweep at SA=2M had stdev 0.0 across 30 trials — every trial hit
floor 252. User's 2m48s "Best" run produced par_quad=256. With the
chunking fix landed and quality presets correctly resolving 2M, the
likely cause is the container's worker timing (5.2). Re-running an
additional 2M-iter SA pass on top of the user's output drops to floor
in 75s, proving the schedule wasn't structurally stuck.

### 5.4 Best-of-N production runner (deferred)
`/assign` currently caps at `BEST_OF_N_TARGET=30`. Could expose a
top-level "Generate Best Schedule" workflow for state events that
explicitly runs N-trial SA at high iteration budgets, with progress
reporting and cancellation. Stark recommended.

### 5.5 Extended iteration sweep (deferred)
Find K* per the tight-criterion definition. Levels 10M, 20M, 50M.
~5 hours wall-clock on Stark. Documented in
`docs/scheduler/ITERATION_CEILING.md` "Future work".

### 5.9 Eval-harness SA path measurement — corrected; rerun complete; Phase 5 active

**Status (2026-05-10, end of day):** Harness fix shipped this morning;
corrected re-run completed in afternoon at `--quality-preset best`.
Phase 5 of the scheduler-quality plan is now **active** with real data
in hand for the first time.

**Headline result:** mean composite 30.64 (down from the SA-disabled
40.12), 16/16 fixtures comparable. Just over the 30-cutoff that
triggers "investigate further" per `workstreams/scheduler-quality.md`,
but the failure has narrowed to two specific phenomena rather than
broad poor performance.

**The narrow signature:**
- ✓ `repeat_partners` and `max_partner_repeats` at floor on every
  fixture. SA + Phase 1 R/B post-pass work as designed.
- ✓ We *beat* the reference scheduler on `max_color_imbalance`,
  `max_opponent_repeats`, `min_match_gap`.
- ✗ `max_station_spread`: 13/13 we're worse, mean 3.54 vs MM's 0.38.
  The Phase 2 (the station-balance technique) post-pass works on synthetic small-team inputs
  but hits a 2–3 floor on real 36+ team fixtures while the reference scheduler
  reaches 0.
- ✗ `repeat_opponents` on 40-team × 12-MPT fixtures (the 2024micmp*
  family): we have ~20% more 2-encounter pairs than MM. `opp_quad`
  is at floor on these — the issue is sum-of-squares vs count-above-
  one rewarding different distributions.

**Next concrete action: Phase 5 Plan A (diagnose first).** Two
experiments documented in `EVAL_FINDINGS.md` "Diagnostic questions
for Phase 5" — both ≤30 minutes of compute, both designed to
distinguish iteration-limited from move-set-limited / objective-
limited hypotheses. Result determines whether Plan B (post-pass
budget bump, 2-3 days) or Plan C (lex tuple expansion, 1 week)
is the right next investment.

**What this changes for the project as a whole:**

The story has flipped from "broadly poor scheduler" to "two specific
metrics drag the composite, with diagnostic plan in hand." That's a
genuine strategic shift — the scheduler-quality work is no longer
indefinite ("keep improving everything") but bounded ("close the
station-spread gap; decide on lex-tuple objective vs metric").

Given how narrow the remaining failure is, the previously-deferred
quality-tooling roadmap (5.8 UI exposure of harness work) becomes
more sensible to take up sooner — once the user can see per-pair
detail and lex-tuple breakdowns in the editor, debugging
fixture-specific issues becomes part of the user workflow rather
than a CLI exercise.

Re-run command (for reproducibility — will land different results
each time due to different RNG seeds, but the methodology is fixed):

```bash
python3 -m scripts.scheduler_eval.runner \
    --fixtures all \
    --adapters frc-scheduler-server,actual,matchmaker \
    --trials 100 \
    --workers 36 \
    --quality-preset best
```

~55 minutes wall-clock on Stark.

### 5.6 RBAC (proper roles + permissions) — designed, paused

Full design lives in `docs/workstreams/rbac.md` (~935 lines, status:
"Proposal — paused"). Five roles: Admin / Support (global) and
Owner / Manager / Viewer (event-scoped), with implicit Public for
read-only `/view`. Capability matrix, delegation rules ("you can
only delegate what you have"), expiration model, in-app
notifications, and a request mechanism for users to seek elevated
access are all spec'd out.

**Status: zero phases implemented.** Current authorization model
is the `is_admin` interim flag (see §5.7). No `role_grants` /
`role_requests` / `notifications` tables exist; no `can(user,
capability)` checker. The doc is explicit that all 7 phases (R-1..
R-7) are paused pending change-freeze lift + decisions on the seven
open design questions in `workstreams/rbac.md` "Open design questions."

R-1 is the foundation everything else builds on (schema +
authorization checker, replacing `is_admin` references). Doc
recommends shipping R-1 + R-2 (back-end enforcement) before any
UI work begins.

Trigger to revisit: when the live-event change-freeze lifts and
the tool starts being shared beyond a single team's internal use.

### 5.7 Schedule-lifecycle phases D / F / G — partially shipped

Full design lives in `docs/workstreams/schedule-lifecycle.md` (~1019 lines,
status: "Draft for implementation"). 7 phases (A–G) plus Part 13's
layered authorization rules.

**Shipped:**
- A — Auth mandatory on writes (see §4.8)
- B — `forked_from_id` schema (`db.py:193`) + fork via
  `/api/assigned-schedules/{id}/duplicate` (`main.py:2499`)
- C — Structural immutability check (`_was_ever_official` at
  `main.py:1656`, gate at `:1760`)
- E — `is_admin` flag (`db.py:342`) + admin-gated `freeze` /
  `unfreeze` / `unmark-official` / force-unlock-by-admin

**Open:**
- **D — Consolidated `event_audit_events` table.** Partial today:
  `assigned_schedule_history` and `assigned_schedule_lock_events`
  capture the most-active event types, but the unified table the
  spec defines (one row per meaningful action across all event
  surfaces) doesn't exist. Until it does, `event_audit_events`
  is implicit — readers reconstruct it by joining the per-table
  histories, which is why an audit-log UI hasn't shipped.
- **F — Lock TTL + heartbeat.** Basic locks ship; lock acquisition
  sets `locked_at` and `locked_by_user_id`. No TTL check (locks
  don't expire on their own), no heartbeat endpoint to refresh
  while editing, no client-side ping. Result: a closed-tab editor
  leaves the lock pinned until someone manually unlocks. Schema
  changes: none required (`locked_at` already exists).
- **G — Lifecycle response field.** Schedule GET responses don't
  include the `lifecycle` block (`structural_frozen`, `lock_state`,
  `freeze_state`) the spec defines. Frontend reproduces the
  layering check ad-hoc against `is_official` / `locked_at` /
  the event freeze flag. Schema changes: none required; pure
  read-side enrichment.

Each is independently shippable per `workstreams/schedule-lifecycle.md` Part 11.
F is the highest-immediate-UX-value (kills the "dead lock from
closed tab" papercut); G removes a class of frontend bugs by
centralising the layering check; D unblocks the audit-log UI
workstream.

### 5.8 Schedule quality scoring & reporting — superseded into a v1.1 workstream

**Status (2026-05-10, end of day):** Promoted from a parked roadmap
item to an active v1.1 workstream. Captured in
`workstreams/schedule-quality-reporting.md`. The prior four-tier UI
exposure plan (`workstreams/ui-quality-exposure.md`) is folded in as
the UI-layer portion (Tiers 1-4 unchanged in shape) of a larger
unified scoring + reporting framework.

The reframe: today the project has four overlapping quality systems
(lex tuple, legacy summary float, diversity-report endpoint, eval-
harness metrics), three of which disagree subtly. Users have no
canonical way to ask "is my schedule good?" because there's no
canonical answer. The new workstream consolidates into one
framework (`app/quality.py`) callable everywhere, with the existing
Schedule Quality card becoming the rendering layer.

Ships in six phases:
- A. Unified scoring module (~2 days)
- B. Server API + `quality_composite` column (~1 day)
- C. UI Tier 1 — per-pair / per-team detail (~3-4 hours)
- D. UI Tier 2 — lex tuple + schedule comparison (~1 day; pre-work: `match_equity` decision)
- E. Calibration + UI Tier 3 — reference comparison (~3-5 days, v1.2)
- F. UI Tier 4 — public `/view` surfacing (gated on product decision, v2.0)

Three uses the unified framework enables beyond the editor:
- "Best library entries" view (admin/curator view of the abstract library)
- Import quality assessment (run the same report on imported xlsx/PDF/CSV)
- Schedule comparison (per-criterion delta between any two schedules)

See `workstreams/schedule-quality-reporting.md` for full design,
open questions (Q1-Q5), and shipping order. Companion workstream:
`workstreams/abstract-library.md` (§5.10 below) — they ship as a
pair in v1.1.

### 5.10 Abstract schedule library — designed; v1.1

**Status (2026-05-10):** Captured in
`workstreams/abstract-library.md`. New v1.1 workstream.

Pre-computed best-known abstracts per FRC fixture shape, looked up
at Generate time. Cache-on-miss for uncovered shapes: first user
of a shape pays the SA cost; subsequent users get the cached
result. The library is curated offline at maximum compute budgets
(SA=50M × best-of-1000, ~24 hours per shape) — quality budgets
that are impossible per-Generate. Result: quality becomes
deterministic per fixture shape; the quality ceiling is raised
dramatically.

Three behaviors at lookup time:
- Library hit → fast + best-known quality.
- Library miss + cache-on-miss enabled (default) → SA generation,
  result inserted into library as `source='cached-on-miss'`.
- Library miss + lookup-only mode → 404 with list of covered
  shapes.

Schema sketch:
- `abstract_library` (id, num_teams, MPT, TPA, abstract_blob,
  lex_tuple, curated_at, curation_method, source, superseded_by_id)
- `abstract_library_lookups` (audit + analytics on hit/miss/cache)
- `assigned_schedules.library_entry_id` (new optional column —
  which library entry produced this schedule)

Ships in four phases:
- 1. Infrastructure (schema, API, curation script). ~2 days.
- 2. Curate FRC-common shapes at maximum budget. ~1 weekend of
  Stark compute + ~1 day review.
- 3. Browser scheduler retirement via library lookup. ~half a
  day (was 2-3 days in ADR 006).
- 4. UI surfacing via the reporting workstream (§5.8 →
  schedule-quality-reporting.md).

Five open questions captured in the workstream doc: coverage
estimate (Q1), quality ceiling estimate (Q2 — partly addressed by
Phase 5 Plan A results), single vs multiple entries per shape
(Q3), the reference scheduler as source (Q4), cache invalidation when curation
improves (Q5).

This changes the project's character: from "high-quality schedule
generator" to "curated library of known-good schedules with a
generator for uncovered cases." Worth being explicit when this
ships — README and project pitch shift accordingly.

---

## 6 · Code locations (verbatim)

### `app/main.py` (~4400 lines)

| Line   | Symbol                                                | What it does                              |
|--------|-------------------------------------------------------|-------------------------------------------|
| ~371   | `AssignRequest` Pydantic model                        | quality_preset, competition_approved, rb_post_pass, station_post_pass, cooldown |
| ~1131  | `assign_teams_endpoint` worker dispatch               | best-of-N parallel SA trials              |
| ~1701  | `patch_assigned_schedule`                              | accepts day_config + practice_matches     |
| ~2768  | `_resolve_practice_matches`                            | slot→team translation; identity fallback   |
| ~3330  | `PdfImportCommitRequest`                               | matches + practice + day_config           |
| ~3815  | XLSX import storage (4 sites)                          | preserves practice in pdf_import.parsed   |
| ~4096  | `commit_pdf_import`                                    | reads body.practice OR cached parse       |

### `app/scheduler.py` (~2120 lines)

| Symbol                          | What it does                                      |
|---------------------------------|---------------------------------------------------|
| `generate_matches`              | construction + SA + post-passes (one process)     |
| `_assign_unified`               | relabel slot→team + SA + post-passes              |
| `_sa_optimize`                  | lex-compare SA over Match[]                       |
| `score_tuple_for_schedule`      | 8-element FRC §10.5.2 lex tuple                   |
| `score_schedule`                | legacy float (UI/CSV/DB display only)             |
| `_swap_preserves_cooldown`      | hard filter — paramount preserved before mutation |
| `_propose_targeted_move`        | duplicate-pair-aware move generator               |
| `run_assignment_chunk`          | worker entry; logs elapsed + μs/iter              |

### `app/post_passes/`

- `rb_balance.py` — Phase 1, whole-match R/B flip + SA, 8 property tests
- `station_balance.py` — Phase 2, the station-balance technique-style within-alliance permutation + SA-from-greedy, 12 property tests

### `app/frc_compliance.py`

- `FRC_DEFAULTS` — `{"rb_post_pass": True, "station_post_pass": True, ...}`
- `compute_deviations(settings)` — list of human-readable deviation strings
- `build_audit_record(settings, cooldown, preset, iterations)` — full audit JSON

### `app/quality_presets.py`

- `QUALITY_PRESETS` — `fair=50K, good=500K, best=2M, maximum=5M`
- `MAX_ITERATIONS = 5_000_000`
- `iterations_for_preset(name)`, `preset_for_iterations(n)`

### `static/index.html` (~17,700 lines)

| Line   | Symbol                                  | What it does                                       |
|--------|-----------------------------------------|----------------------------------------------------|
| ~2645  | FRC compliance section in Generate form | checkbox + deviation banner + algorithm toggles    |
| ~3099  | `restoreFromFile`                       | preserves event across fullReset                   |
| ~3315  | `_restoreMatchListFile` (xlsx/csv)      | uses `ensureEventLoadedForImport`                  |
| ~3406  | `openPdfImportModal`                    | uses `ensureEventLoadedForImport`                  |
| ~3553  | `renderPdfImportPreview`                | renders qual + practice tables                     |
| ~3872  | `renderPdfImportTable(matches, opts)`   | parameterized for qual or practice rendering       |
| ~5050  | `recomputeFrcCompliance` + handlers     | live banner update on algorithm-toggle change      |
| ~8689  | `generateMatches` (browser SA)          | client-side abstract construction (legacy weighted-sum) |
| ~9861  | `ensureEventLoadedForImport`            | shared event-resolution helper                      |
| ~14000 | `assignTeams`                           | sends quality_preset, competition_approved, etc.   |

### `static/view.html` (~8200 lines)

| Symbol                  | What it does                                          |
|-------------------------|-------------------------------------------------------|
| `renderFrcBanner`       | top-of-page green/yellow/gray banner from audit_trail |
| `_renderFrcAudit`       | audit modal — deviations + settings table             |
| `_applyLoadedSchedule`  | calls renderFrcBanner on every load                   |

---

## 7 · Test status

All green:
- Smoke test (canonical metrics)
- V2 URL (36 tests)
- Three-up (23 tests)
- day_config_v2
- Phase 0 lex SA + targeted moves
- Phase 1 R/B (8 commutativity)
- Phase 2 station (12 commutativity)
- FRC compliance (11 tests in `tests/test_frc_compliance.py`)
- Cycle-change walker (`tests/test_cycle_change_walker.js`) — V2_SPEC §7 semantic + source-guards on all 6 application sites
- Inline JS in static/index.html and static/view.html parses cleanly

---

## 8 · Operational knowledge

### Production
- Hostname: `frc-scheduler.roadfeldt.com`
- Pod label: `app=frc-scheduler-server-git`
- Postgres: pod label `app=frc-postgres`, db `frc_scheduler`
- Container: 12 effective cores via cgroup quota (1.2 CPU = 12 effective). `os.cpu_count()` reports 16 (host) but cpu.max limits to 12.
- Event for state: `2026mnst`, event_id `4`, 36 teams (MSHSL)
- HAProxy timeout: 120s (`openshift/05-route.yaml`) — SSE keep-alive resets idle timer

### Stark (eval machine)
- 36 cores
- Used for iteration sweeps + production-quality state schedules
- `CPU_WORKERS=36` env

### DB migration applied
```bash
oc cp migrate_competition_approved.sql frc-postgres-XXXXX:/tmp/
oc rsh pod/frc-postgres-XXXXX
psql -U postgres -d frc_scheduler -f /tmp/migrate_competition_approved.sql
```

Verify columns:
```bash
psql -U postgres -d frc_scheduler -c "\d assigned_schedules" | grep -E 'competition_approved|audit_trail'
```

---

## 9 · Deploy

Standard flow:
```bash
cd ~/git/frc-scheduler-server
git pull && git add -A
git commit -m "<message>"
git push
./openshift/apply.sh --build       # omit for doc-only commits
```

Hard-refresh Safari/Chrome after deploy (`⌘⇧R` / `Ctrl+Shift+R`) — UI
changes from this session won't appear without it.

For the canonical Claude-session deliverable convention — two
tarballs (full + changes-only), commit-ready commands, and the
commit-message style — see `REPRODUCTION_PROMPT.md` "Session
deliverables (standard process)". That's the source of truth;
this section is just the operator-side cheat sheet.

---

## 10 · Reproduction prompt

`REPRODUCTION_PROMPT.md` (root) is the canonical AI onboarding doc.
Pair it with this handoff for current state. They're complementary,
not redundant — the prompt covers project goals + structure + constraints,
this doc covers what's done + what's pending.

`docs/REPRODUCTION_PROMPT.md` is a stub redirecting to the root copy
(used to be diverged; consolidated this session).

---

## 11 · TL;DR

If you're picking this up:

1. **Read in order:** `README.md` → `PRIORITIES.md` (algorithm spec) → `docs/ROADMAP.md` (where this is going) → this HANDOFF (recent session log) → `docs/decisions/` (architectural decisions) → `docs/workstreams/` (per-workstream design docs as needed).
2. **Open items** live in `docs/ROADMAP.md`, not in this handoff. HANDOFF's §5 is a per-session view of in-flight work; ROADMAP is the canonical "where we're going."
3. **For state events**, recommend Stark via best-of-30 at SA=2M (~75s wall-clock). Container "Best" works but with the caveat in §5.2.
4. **Never silently bypass FRC §10.5.2 paramount.** The lex tuple is the contract. Cooldown comes first, always. See ADR 002.
5. **the reference scheduler is a peer**, not a competitor. See ADR 005.
6. **The schedule itself is the artifact.** Bit-exact replay from seed isn't guaranteed across algorithm versions. See ADR 004.

The scheduler core is in good shape; quality is narrowly poor (mean composite 30.64 across 16 fixtures) with two specific phenomena driving the gap; Phase 5 diagnostics running on Stark as of 2026-05-10 will determine whether the next investment is Plan B (post-pass budget) or Plan C (lex-tuple expansion).
