# FRC Scheduler — Three-Layer Architecture Design

**Repository:** `github.com/croadfeldt/frc-scheduler-server`
**Document type:** Architecture / design proposal
**Status:** **Proposal — paused.** Scheduler change-freeze in effect during the live event. Broader architectural direction that the quality roadmap can slot under; not an active workstream until the freeze lifts and the architectural decision is made deliberately. See `docs/HANDOFF.md` for current operational guidance.

**Companion docs:**
- `SCHEDULER_QUALITY_ROADMAP.md` — tactical six-phase roadmap; this document reframes that work under a broader architecture
- `PHASE_0_HARD_COOLDOWN_BRIEF.md` — still valid as-is (truthfulness fix is layer-independent)

---

## Vision

Rather than building a tool that produces *one kind of schedule* (FRC-aligned, SA-optimized), build a tool that composes **three independent layers**:

1. **Criteria Suites** — what must be true (sanctioning body requirements)
2. **Goal Suites** — what should be prioritized (event / organizer preferences)
3. **Algorithm Suites** — how to find the schedule (search strategies)

Each layer offers a curated catalog of *suites* — named, coherent bundles of related settings that users select as a unit. Users compose a schedule by picking one suite from each layer (or one pre-bundled "profile" that selects all three). Power users can mix-and-match or override; most users pick named suites and never see individual settings.

The result: one tool that serves official FRC events, off-season league play, championship prep, template work, and entirely different sanctioning bodies (FTC, VEX, custom) — without forks or special-casing.

---

## Why suites, not individual settings

The current tool exposes individual weights (`W_PARTNER`, `W_OPPONENT`, `W_STATION`, etc.) as a power-user surface. That's correct for power users but wrong as the primary UX. Most users don't have a principled basis to set `W_PARTNER=80` vs. `W_PARTNER=100` — and forcing them to think about it produces worse outcomes than guiding them to a curated bundle.

Suites solve this by:

- **Bundling related concerns.** "Drive Team Experience" naturally groups gap variance, no-back-to-back, and surrogate equity. These travel together; users who care about one usually care about all.
- **Encoding intent over mechanism.** Users say "I want fairness" or "I want this to match the FRC manual" — they don't say "set W_PARTNER to 80." The suite translates intent to mechanism.
- **Enabling honest provenance.** A schedule generated with `(FRC 2026, Drive Team Experience, CP-SAT Proven)` carries that triple as metadata. Anyone reviewing the schedule knows exactly what assumptions produced it.
- **Making compatibility explicit.** Some goals don't pair with some algorithms. Suites let the system reason about compatibility at the suite level, not the individual-knob level.

Power users retain access to per-knob overrides through an "Advanced" panel. The suite system is the default, not a constraint.

---

## Architectural model

```
   User picks one of each (or one bundled profile):

   ┌─────────────────────┐  ┌────────────────────┐  ┌──────────────────────┐
   │  Criteria Suite     │  │  Goal Suite        │  │  Algorithm Suite     │
   │  (sanctioning body) │  │  (organizer prefs) │  │  (search strategy)   │
   │                     │  │                    │  │                      │
   │  e.g. FRC 2026,     │  │  e.g. Drive Team,  │  │  e.g. CP-SAT Proven, │
   │       FTC, Custom   │  │  Audience, Fair    │  │  SA Optimized        │
   └──────────┬──────────┘  └──────────┬─────────┘  └──────────┬───────────┘
              │                        │                       │
              ▼                        ▼                       ▼
        Hard + soft           Weighted/lex-ordered          Strategy +
        constraints           goal objectives               capabilities
              │                        │                       │
              └────────────────────────┴───────────────────────┘
                                       │
                                       ▼
                          ┌────────────────────────────┐
                          │  Compositor                │
                          │  • Validates compatibility │
                          │  • Builds problem spec     │
                          │  • Dispatches to algorithm │
                          └─────────────┬──────────────┘
                                        ▼
                          ┌────────────────────────────┐
                          │  Schedule + Provenance     │
                          │  (criteria/goals/algo used,│
                          │   seed, optimality cert)   │
                          └────────────────────────────┘
```

### Composition rules

- **Hard constraints from criteria are absolute.** Cannot be overridden by goals or relaxed by algorithm choice. If an algorithm cannot honor them, the system refuses the run.
- **Soft criteria from sanctioning body take precedence over goals.** Goals shape the schedule *within* the slack the soft criteria allow. A goal can break a tie between schedules that score equally on soft criteria; it cannot win against a soft criterion.
- **Goals compose internally per their suite definition.** Each goal suite specifies how its goals combine (lex order, weighted sum, etc.). This is the suite's responsibility, not the algorithm's.
- **Algorithms must declare what they can honor.** Capabilities are explicit: which constraint types, which composition styles, which provenance claims.
- **The compositor mediates.** It validates that the chosen (criteria, goals, algorithm) triple is mutually satisfiable and dispatches to the algorithm with a normalized problem spec.

---

## Layer 1: Criteria Suites

**Purpose:** Encode sanctioning body requirements. These are externally imposed, version-stamped, and binary (a schedule either conforms or it doesn't).

### Schema

```yaml
criteria_suite:
  id: frc-2026
  name: "FRC 2026 (FIRST Robotics Competition)"
  source: "https://www.frcmanual.com/2026/tournaments-(t)"
  version: "2026 manual, §13.6.2"
  description: "Official FRC qualification scheduling per current FRC game manual."

  hard_constraints:
    - id: round_uniformity
      description: "Each team plays exactly MPT matches"
    - id: match_composition
      description: "Each match has 3 red + 3 blue teams, 6 distinct teams"
    - id: min_match_separation
      description: "Min gap between matches per team, varies by event size"
      formula: "team_count_dependent"
    - id: surrogate_count_minimal
      description: "Surrogates only when N×MPT not divisible by 6"
    - id: surrogate_third_match
      description: "Surrogate appearance is always team's 3rd qualification match"
      applies_when: "MPT >= 3"

  soft_criteria:
    composition: lexicographic
    priorities:
      - lex_1: minimize_partner_repeats
      - lex_2: minimize_opponent_repeats
      - lex_3: minimize_surrogate_use
      - lex_4: even_alliance_distribution
      - lex_5: even_station_distribution

  notes:
    - "Partners weighted higher than opponents reflects 2-vs-3 cardinality"
    - "Lexicographic per manual phrasing 'in order of priority'"
```

### Catalog of Criteria Suites

| Suite ID | Name | When to use |
|---|---|---|
| `frc-2026` | FRC 2026 (current) | Any FRC-format event in current season |
| `frc-2024` | FRC 2024 (archival) | Reproducing or auditing past FRC schedules |
| `ftc-2026` | FTC 2026 | FIRST Tech Challenge — different team count math, fewer station positions |
| `vex-vrc` | VEX Robotics Competition | VEX events; different match structure |
| `off-season-relaxed` | Off-Season (relaxed) | Demo events, scrimmages — fewer hard constraints |
| `league-play` | League Play | Multi-event league with cross-event tracking enabled |
| `none` | None / Ad-hoc | No sanctioning constraints; only structural rules (round uniformity, match composition) |
| `custom` | Custom | User-defined criteria via Advanced panel |

The catalog is data, not code. New manual years update an existing suite or fork it. New sanctioning bodies add new suites without code changes.

---

## Layer 2: Goal Suites

**Purpose:** Encode what the event organizer cares about *beyond* sanctioning body requirements. These are preferences — defensibly chosen, defensibly ignored, never absolute.

### Schema

```yaml
goal_suite:
  id: drive-team-experience
  name: "Drive Team Experience"
  description: "Optimize for the experience of teams competing — even gap distribution, no excessive waits, fair surrogate placement."

  goals:
    - id: gap_variance
      description: "Minimize variance in match-to-match gaps per team"
      objective: "minimize stddev(gaps[t]) for all teams t"
      weight: 1.0

    - id: max_gap_cap
      description: "No team waits more than 2× their average gap"
      objective: "minimize count(team gaps > 2 * mean_gap[t])"
      weight: 0.8
      type: penalty_above_threshold

    - id: surrogate_equity_intra_event
      description: "Distribute surrogate slots evenly across willing teams"
      objective: "maximize entropy(surrogate_assignments)"
      weight: 0.6

    - id: no_back_to_back_beyond_min
      description: "Avoid scheduling at exactly the minimum cooldown when slack exists"
      objective: "maximize sum(gap[t,i] - cooldown) for all (t, i)"
      weight: 0.5

  conflicts:
    - id: schedule_compression
      reason: "Tight schedules cannot maintain even gap distribution"

  recommended_algorithms:
    - cpsat-proven
    - sa-optimized
  unsupported_algorithms:
    - fast-heuristic # cannot honor variance objectives well
```

### Catalog of Goal Suites

| Suite ID | Name | What it optimizes |
|---|---|---|
| `drive-team-experience` | Drive Team Experience | Gap variance, max-gap caps, surrogate equity within event, no unnecessary back-to-back |
| `audience-experience` | Audience Experience | Alliance variety in featured matches, diverse team showcasing across the day, marquee teams in opening/closing matches |
| `operational-smoothness` | Operational Smoothness | First-time teams not in match 1, queue load balancing, inspector-buffer for flagged teams, late-day composition by reliability |
| `fairness-equity` | Fairness & Equity | Even pairing distribution, surrogate cross-event tracking (when criteria suite supports it), pair-meeting maximization |
| `season-balance` | Season Balance | Cross-event partner balancing, surrogate equity across season, opponent diversity over multiple events |
| `speed` | Speed | Fast generation; accepts lower optimization quality for sub-second turnaround |
| `optimal-quality` | Optimal Quality | Maximum search effort, longest acceptable runtime, best achievable schedule |
| `reproducibility` | Reproducibility | Deterministic seeding, full audit trail, zero algorithm randomness beyond declared seed |
| `template-mode` | Template Generation | Abstract structure focus; team-assignment quality secondary; supports rapid what-if exploration |
| `none` | No additional goals | Use only criteria suite's soft criteria |

A user can combine goals from different suites into a custom mix via Advanced panel, but the curated suites cover ~90% of real use cases.

### Important property

Goals never override criteria. If a goal's objective conflicts with a hard criterion, the criterion wins. If it conflicts with a soft criterion, the soft criterion wins. Goals only have effect *within the slack* left by the criteria. This is the crucial separation that prevents goals from compromising sanctioning compliance.

---

## Layer 3: Algorithm Suites

**Purpose:** Encode the search strategy. Algorithms differ in what guarantees they offer, what runtime they require, what (criteria, goals) combinations they can honor.

### Schema

```yaml
algorithm_suite:
  id: cpsat-proven
  name: "CP-SAT (Provable Optimality)"
  description: "Constraint programming with lazy clause generation. Provides certificates of optimality or bounded gap."

  capabilities:
    constraint_types:
      - hard_structural
      - hard_separation
      - soft_lexicographic
      - soft_weighted
    composition_styles:
      - lexicographic
      - weighted_sum
    provenance_claims:
      - proven_optimal
      - bounded_gap_pct

  parameters:
    quality_dial:
      type: time_budget
      values: [fast, standard, thorough, exhaustive]
      defaults:
        fast: 30s
        standard: 5min
        thorough: 30min
        exhaustive: until_proven

  restrictions:
    - reason: "Goals requiring statistical objectives (e.g., variance) need linearization"
      affects: [drive-team-experience]
      mitigation: "Auto-linearization with documented relaxation"

  determinism: seeded
  reproducibility: full

  dependencies:
    - "ortools >= 9.8"
```

### Catalog of Algorithm Suites

| Suite ID | Name | Strengths | Trade-offs |
|---|---|---|---|
| `auto` | Auto-select | System picks best fit for (criteria, goals) | None — recommended default |
| `fast-heuristic` | Fast Heuristic | Sub-second, sufficient for templates | Lowest quality; no optimality claims |
| `sa-optimized` | SA Optimized | Familiar behavior, good with statistical goals | No optimality proofs; quality plateaus |
| `sa-with-postpasses` | SA + Decomposed Cleanups | Better than vanilla SA via separable post-passes | Still no proofs; same family limitations |
| `cpsat-proven` | CP-SAT (Provable) | Optimality certificates; lex order native | Slower; some goals need linearization |
| `bibd-hybrid` | BIBD Hybrid | Mathematically optimal for compatible (N, MPT) | Only applies to specific event sizes |
| `reoptimizer` | Live Re-optimizer | Solves residual schedule after disruption | Requires CP-SAT backend; not for fresh schedules |

### The Auto picker

`auto` is the default and the most-used algorithm. It picks based on rules like:

```
if criteria.requires(proven_optimal_claim):
    return cpsat-proven
if (N, MPT) matches a known BIBD:
    return bibd-hybrid (with cpsat-proven as fallback)
if goals.includes(template-mode) or goals.includes(speed):
    return fast-heuristic
if goals.includes(optimal-quality):
    return cpsat-proven
otherwise:
    return sa-with-postpasses
```

The picker is deterministic, documented, and overridable. If the user picks an explicit algorithm, the picker is bypassed. The picker's selection appears in the schedule's provenance metadata so users can see *why* a given algorithm was chosen.

---

## Profiles: bundling all three layers

Most users don't pick three things; they pick one. A **profile** is a named bundle of (criteria_suite, goal_suite, algorithm_suite).

### Catalog of bundled profiles

| Profile ID | Criteria | Goals | Algorithm | Use case |
|---|---|---|---|---|
| `official-frc-event` | `frc-2026` | `operational-smoothness` | `auto` (→ sa-with-postpasses) | Standard regional / district event |
| `official-frc-best` | `frc-2026` | `operational-smoothness` | `cpsat-proven` (thorough) | Championship; willing to spend compute |
| `championship-prep` | `frc-2026` | `optimal-quality` | `cpsat-proven` (exhaustive) | Practice schedules, alliance prep |
| `off-season` | `off-season-relaxed` | `fairness-equity` | `sa-with-postpasses` | Off-season, demo events |
| `league-season` | `league-play` | `season-balance` | `cpsat-proven` (standard) | Multi-event league with continuity |
| `template-design` | `none` | `template-mode` | `fast-heuristic` | Schedule template work, what-if |
| `reproduce-frc-2024` | `frc-2024` | `reproducibility` | `sa-optimized` | Audit / reproduce a 2024 schedule |
| `ftc-event` | `ftc-2026` | `operational-smoothness` | `auto` | FTC event |
| `custom` | (user-picked) | (user-picked) | (user-picked) | Power users; exposes all three pickers |

Profiles are the primary UX. The three independent pickers are the secondary UX. Individual settings within a suite are the tertiary UX (Advanced panel).

---

## Compatibility matrix

Not every (criteria, goals, algorithm) triple is feasible. The compatibility matrix encodes the feasibility rules.

### Algorithm × Goal compatibility

| Goal Suite | fast-heuristic | sa-optimized | sa-with-postpasses | cpsat-proven | bibd-hybrid |
|---|---|---|---|---|---|
| drive-team-experience | ⚠ degraded | ✓ | ✓ | ✓ (linearized) | ✗ |
| audience-experience | ✗ | ⚠ | ✓ | ✓ | ✗ |
| operational-smoothness | ⚠ | ✓ | ✓ | ✓ | ⚠ |
| fairness-equity | ⚠ | ✓ | ✓ | ✓ | ✓ |
| season-balance | ✗ | ✗ | ⚠ | ✓ | ✗ |
| speed | ✓ | ⚠ | ✗ | ✗ | ✗ |
| optimal-quality | ✗ | ⚠ | ✓ | ✓ | ✓ |
| reproducibility | ✓ | ✓ | ✓ | ✓ | ✓ |
| template-mode | ✓ | ✓ | ⚠ | ⚠ | ✗ |

Legend: ✓ supported · ⚠ supported with caveats · ✗ unsupported

### Algorithm × Criteria compatibility

| Criteria Suite | fast-heuristic | sa-optimized | sa-with-postpasses | cpsat-proven | bibd-hybrid |
|---|---|---|---|---|---|
| frc-2026 | ⚠ defaults only | ✓ | ✓ | ✓ | ⚠ specific (N,MPT) |
| frc-2024 | ⚠ | ✓ | ✓ | ✓ | ⚠ |
| ftc-2026 | ⚠ | ✓ | ✓ | ✓ | ⚠ |
| vex-vrc | ✗ | ⚠ | ⚠ | ✓ | ✗ |
| off-season-relaxed | ✓ | ✓ | ✓ | ✓ | ✓ |
| league-play | ✗ | ✗ | ⚠ | ✓ | ✗ |
| none | ✓ | ✓ | ✓ | ✓ | ✓ |
| custom | depends | depends | depends | ✓ | depends |

The compatibility matrix is computed from suite declarations, not hand-maintained. When the user picks suites, the system computes feasibility live and warns or restricts the algorithm picker accordingly.

---

## Provenance

Every generated schedule is stamped with the triple that produced it, plus enough metadata to reproduce or audit.

### Provenance schema

```yaml
schedule_provenance:
  schedule_id: "abc123..."
  generated_at: "2026-05-08T14:32:01Z"
  generator_version: "frc-scheduler-server@v0.5.0"

  composition:
    profile: official-frc-event           # if applicable; null if custom
    criteria_suite:
      id: frc-2026
      version: "2026 manual, §13.6.2"
    goal_suite:
      id: operational-smoothness
      version: "v1.0"
    algorithm_suite:
      id: sa-with-postpasses
      version: "v1.0"
      auto_selected: true                 # was this auto-picked or user-explicit
      selection_reason: "default for FRC criteria + ops goals"

  parameters:
    seed: "a1b2c3d4"
    iteration_budget: 5000
    quality_preset: standard

  claims:
    - all_hard_constraints_satisfied: true
    - soft_criteria_optimality: "best of 5000 SA iterations"
    - goal_optimality: "best of 5000 SA iterations"
    - proven_optimal: false
    - bounded_gap: null

  diversity_metrics:
    partner_repeats_over_floor: 2
    opponent_repeats_over_floor: 4
    max_station_imbalance: 1
    alliance_imbalance_range: [0, 2]
    surrogate_distribution: even
    gap_variance_avg: 0.34

  user:
    created_by: "google:..."
```

This is what `created_by` and seed already do — the proposal is to richen it with the suite triple, the auto-pick reasoning, and the claims the algorithm makes. Schedules become self-describing.

---

## UI implications

### Primary surface (most users)

Three pickers at the top of the schedule generator:

```
Sanctioning body:    [▼ FRC 2026                    ]
What matters most:   [▼ Operational Smoothness      ]
How to generate:     [▼ Auto (recommended)          ]
```

Or one profile picker that bundles them:

```
Quick start:  [▼ Official FRC Event                 ]   (advanced ▶)
```

### Secondary surface (power users)

Advanced panel exposes:

- Individual suite contents (e.g., toggle individual goals within a goal suite)
- Per-knob overrides (current `W_PARTNER` etc., now framed as overrides on top of the chosen suites)
- Algorithm parameters (iteration budget, time limit, lex vs. weighted)

### Tertiary surface (audit / debug)

Schedule detail view shows full provenance:

- Suite triple selected
- Auto-pick reasoning (if applicable)
- Compatibility warnings honored
- Claims the algorithm made
- Metrics actually achieved

---

## Migration path from current state

The current code is essentially `(frc-2026 criteria, fairness-equity goals, sa-optimized algorithm)` hardcoded. Migration is a careful refactor in three passes:

### Refactor pass 1: extract criteria suite

Pull all FRC-specific rules out of `scheduler.py` and into a `criteria/frc_2026.py` module that conforms to the criteria suite schema. The scheduler reads from the criteria suite rather than hardcoding rules. At this point only one criteria suite exists, but the abstraction is in place.

### Refactor pass 2: extract goal suite

Pull the W_* weights out of the score function and into a `goals/` directory. Each goal becomes a measurable function that produces a score component. Goal suites bundle goals with their composition method (lex or weighted). Existing weight defaults become the `fairness-equity` goal suite. The `score()` function becomes generic — given a goal suite, computes the composite score.

### Refactor pass 3: extract algorithm suite

Pull the SA loop out into `algorithms/sa.py` behind an algorithm strategy interface. Add `algorithms/auto.py` (initially just delegates to SA). Now `scheduler.py` is a thin compositor: it takes a triple, builds a problem spec, dispatches to the algorithm. The current behavior is preserved end-to-end, just structurally rearranged.

After these three passes, adding CP-SAT, BIBD-hybrid, FTC criteria, etc. are *additive* — new modules conforming to the existing schemas. No core changes.

### Phase 0 still ships independently

The hard-cooldown truthfulness fix (`PHASE_0_HARD_COOLDOWN_BRIEF.md`) is layer-independent. It's a correctness fix to the current code, valid before, during, or after the refactor. Ship it on the existing track; don't block on the architectural work.

### Roadmap reframing

The Phases 1–5 in `SCHEDULER_QUALITY_ROADMAP.md` slot naturally under this architecture:

- Phases 1–2 (R/B post-pass, station post-pass) become **`sa-with-postpasses` algorithm suite** internals — implementation details, not user-facing
- Phase 3 (quality presets) becomes a **per-algorithm quality dial** in the algorithm suite schema
- Phase 4 (external comparison harness) becomes the **validation harness for the `frc-2026` criteria suite × `sa-*` algorithms** — still useful, with a properly scoped framing
- Phase 5 (algorithm plugin model + CP-SAT plugin) **becomes the entry point for the algorithm-suite layer of this design** — same direction, more incremental. The plugin interface that Phase 5 ships is the minimum viable shape of an algorithm suite; the full schema in this document grows on top of it as the second and third plugins reveal what's actually needed.

The two documents are aligned: the roadmap delivers the work in tactical phases that produce shippable value at each step; this design describes the destination shape those phases naturally evolve toward.

---

## Open design questions

Flagging the hard parts for the implementing session and for further discussion.

**Goal definition language.** The schema shows objectives as natural-language strings (`"minimize stddev(gaps[t]) for all teams t"`). For real implementation, these need formal mathematical specification — probably as Python functions that take a schedule and return a score component. The question is whether goal definitions are first-class data (loaded from YAML, evaluated by an interpreter) or first-class code (Python modules registered in a goal registry). Code is simpler and more flexible; data is auditable and extensible by non-programmers. Lean toward code with a registration decorator, but worth deciding deliberately.

**Lexicographic vs weighted composition.** FRC criteria are lexicographic. Most goals are naturally weighted. Mixing the two within one optimization run is non-trivial — CP-SAT handles it natively, SA does not. Need to decide whether the composition method is a per-suite property or a top-level choice.

**Cross-event state for season-aware goals.** `season-balance` requires tracking partner/opponent history across events. This requires either (a) cross-schedule queries during optimization, or (b) a precomputed "history vector" passed in as input. (b) is much simpler and doesn't require optimizer changes — just ensure the score functions can accept history input.

**Auto picker as a learnable component.** The rules-based auto picker described above is fine for v1. Eventually it could learn from user overrides — "users who picked X criteria + Y goals tended to override the auto pick to Z" — and update its rules. Out of scope for now but worth knowing it's a possible direction.

**Versioning of suites.** Manual updates (e.g., FRC 2027) version the criteria suite. Reproducing a schedule generated under FRC 2026 requires keeping FRC 2026 available, not silently upgrading it. The schema supports versioning; the storage layer needs to honor it (don't garbage-collect old suite versions referenced by stored schedules).

**Validation of algorithm claims.** When `cpsat-proven` claims "proven optimal," can the system independently verify that claim? CP-SAT itself produces the certificate, which we can store. For SA-family claims like "best of N iterations," verification is just running it and checking the result matches — possible but expensive. Question: do we trust algorithms' self-reported claims, or do we have a verifier? For v1, trust + audit log. For sanctioned use, eventually verifier.

---

## Out of scope

- **Implementing the algorithms themselves.** This document defines the architecture and the suites; algorithm implementations come later.
- **UI mockups.** Wireframes are out of scope; the UI implications section is functional, not visual.
- **Database schema changes.** Mentioned in passing; full migration design is a separate document.
- **Multi-tenant access controls per suite.** All users see all suites for now; gating particular suites (e.g., `cpsat-proven` requires entitlement) is a future concern.
- **Translating sanctioning body manuals into criteria suites at scale.** The first criteria suites are FRC and the obvious nearby ones; expanding to a comprehensive sanctioning catalog is community work, not v1 work.
- **Migration of existing stored schedules to the new provenance schema.** Existing schedules become legacy / unannotated; new schedules are fully annotated. No retroactive migration.

---

## Decision points for Chris

Before this design moves to implementation:

1. **Confirm the three-layer split is the right cut.** Are there concerns this misses? E.g., is "venue-specific constraints" (field hardware, queue geometry) a fourth layer, or does it fit into criteria/goals?
2. **Confirm the suite catalogs are roughly complete.** Especially the goal suites — those are the most subjective. What's missing?
3. **Decide on the goal definition language** (data vs code). Affects implementation effort meaningfully.
4. **Decide on composition default** (lex vs weighted) when the criteria says lex but goals are weighted.
5. **Greenlight the migration sequence** — refactor passes 1–3 in order, with current behavior preserved end-to-end at each pass.

Each decision is reversible with effort, but reversing pass 3 (algorithm extraction) once code is written is much more expensive than picking the right shape now.

---

*Design drafted as foundation for future architectural work. Phase 0 brief (hard cooldown) is independent and remains valid. The scheduler quality roadmap slots naturally under this architecture; the original phases become implementation details of specific algorithm suites or are subsumed by the algorithm-suite layer the roadmap's Phase 5 introduces.*
