# docs/

Living specification documents for FRC Match Scheduler. Source of
truth for what the system does, what it should do, and how we get
from here to there.

## Top-of-stack reading

| Document                                                  | What it covers                                |
|-----------------------------------------------------------|-----------------------------------------------|
| [ROADMAP.md](ROADMAP.md)                                  | Where the project is going. v1.0/1.1/1.2/2.0 buckets, with each item pointing at its design doc. |
| [HANDOFF.md](HANDOFF.md)                                  | Per-session log of recent work. What just shipped, what's in flight. Read after ROADMAP. |
| [ARCHITECTURE.md](ARCHITECTURE.md)                        | High-level system design — backend, frontend, deploy.       |
| [REPRODUCTION_PROMPT.md](REPRODUCTION_PROMPT.md)          | Stub redirecting to the canonical root copy at `../REPRODUCTION_PROMPT.md`. |

For project conventions (commit style, test requirements,
session-deliverable protocol), see `../CONTRIBUTING.md` at the repo
root.

## Architectural decisions

[`decisions/`](decisions/) — Architecture Decision Records. Each
captures a significant design choice with context, alternatives,
and consequences. Immutable once accepted.

| ADR | Topic |
|---|---|
| [001](decisions/001-lex-tuple-design.md) | Lex tuple as the canonical schedule score |
| [002](decisions/002-frc-paramount-priority.md) | FRC §10.5.2 paramount cooldown via hard filter |
| [003](decisions/003-three-layer-architecture.md) | Day-config / abstract / assigned three-layer pipeline |
| [004](decisions/004-no-reproducibility-guarantee.md) | Schedule is the artifact; bit-exact replay not guaranteed |
| [005](decisions/005-matchmaker-as-peer.md) | MatchMaker as peer reference, not competitor |
| [006](decisions/006-server-only-construction.md) | Server-only construction; retire the browser scheduler |

## Workstreams

[`workstreams/`](workstreams/) — design docs for individual
planned workstreams. Some are active, some paused, some long-term.
The ROADMAP says when each one will be picked up.

| Document                                                       | Status                       | What it covers                                                                                                |
|----------------------------------------------------------------|------------------------------|---------------------------------------------------------------------------------------------------------------|
| [scheduler-quality.md](workstreams/scheduler-quality.md)       | Phases 0-4 shipped; Phase 5 active | The six-phase plan to evolve the team-placement scheduler. Quality presets, post-passes, decision point. Becomes the curation pipeline for the abstract library. |
| [abstract-library.md](workstreams/abstract-library.md)         | Designed; targeted at v1.1   | Pre-computed best-known abstracts per FRC fixture shape. Lookup first, generate-and-cache on miss. The library is what users get; the SA populates it. |
| [schedule-quality-reporting.md](workstreams/schedule-quality-reporting.md) | Designed; targeted at v1.1 | Unified quality scoring framework callable everywhere (server, CLI, UI). Consolidates today's four overlapping quality systems. Includes tiered UI exposure. |
| [schedule-lifecycle.md](workstreams/schedule-lifecycle.md)     | A/B/C/E shipped; D/F/G open  | Lifecycle, locking, freeze, audit-trail. Auth-mandatory, fork model, admin role, full audit table.            |
| [rbac.md](workstreams/rbac.md)                                 | Designed; paused             | Role-based access control proposal — roles, delegation, notifications, role requests. Replaces interim `is_admin` flag and supersedes the EventManager section of AUTH_DESIGN.md. |
| [ui-quality-exposure.md](workstreams/ui-quality-exposure.md)   | Superseded                   | Earlier four-tier plan for surfacing harness data in the UI. Folded into `schedule-quality-reporting.md`. Kept for history. |
| [schedule-comparison.md](workstreams/schedule-comparison.md)   | Designed; paused             | Schedule diff between schedules or history snapshots, plus user-supplied labels on history rows.              |

## Algorithm deep-dives

[`scheduler/`](scheduler/) — algorithm-specific reference and
investigation docs. These are deeper than ADRs; they're how-and-why
for the SA / post-passes / lex tuple internals.

| Document                                                          | What it covers                                                       |
|-------------------------------------------------------------------|----------------------------------------------------------------------|
| [scheduler/EVAL_FINDINGS.md](scheduler/EVAL_FINDINGS.md)          | Per-run eval results, including the post-Phase-4 baseline (2026-05-10). |
| [scheduler/ITERATION_CEILING.md](scheduler/ITERATION_CEILING.md)  | SA iteration sweep findings; tight-criterion analysis.               |
| [scheduler/FRC_COMPLIANCE.md](scheduler/FRC_COMPLIANCE.md)        | Mapping FRC §10.5.2 to test invariants.                              |
| [scheduler/THREE_LAYER_ARCHITECTURE_DESIGN.md](scheduler/THREE_LAYER_ARCHITECTURE_DESIGN.md) | Implementation framing for the three-layer pipeline (see ADR 003). |
| [scheduler/PHASE_0_HARD_COOLDOWN_BRIEF.md](scheduler/PHASE_0_HARD_COOLDOWN_BRIEF.md) | Phase 0 implementation brief — hard-cooldown rejection. |
| [scheduler/MATCHMAKER_ALIGNMENT_ROADMAP.md](scheduler/MATCHMAKER_ALIGNMENT_ROADMAP.md) | Historical: which MatchMaker behaviors we deliberately match vs. diverge from. |
| [scheduler/MATCHMAKER_LICENSING_BRIEF.md](scheduler/MATCHMAKER_LICENSING_BRIEF.md) | Licensing analysis for using MatchMaker as a peer reference (see ADR 005). |
| [scheduler/SCHEDULER_QUALITY_ROADMAP.md](scheduler/SCHEDULER_QUALITY_ROADMAP.md) | Historical: original 6-phase plan that became `workstreams/scheduler-quality.md`. |

## V2 day_config

| Document                                  | What it covers                                                                       |
|-------------------------------------------|---------------------------------------------------------------------------------------|
| [V2_SPEC.md](V2_SPEC.md)                  | The canonical V2 day_config model — data shape, tier rules, validation, materialization. |
| [V1_RETIREMENT.md](V1_RETIREMENT.md)      | Inventory of V1-coupled sites with replacements and kill order.                       |
| [DB_V2_MIGRATION.md](DB_V2_MIGRATION.md)  | Schema state, target state, migration SQL, rollback procedure.                        |
| [V2_ROADMAP.md](V2_ROADMAP.md)            | Phased rollout plan from current state to V1-free codebase.                           |

## Operational + integration

| Document                                          | What it covers                                |
|---------------------------------------------------|-----------------------------------------------|
| [AUTH_DESIGN.md](AUTH_DESIGN.md)                  | Authentication and authorization model.       |
| [OAUTH_SETUP.md](OAUTH_SETUP.md)                  | Operator runbook: Google + Apple sign-in setup. |
| [INTEGRATIONS.md](INTEGRATIONS.md)                | TBA / Nexus / Statbotics / FMS integrations.  |
| [PRACTICE_DAY.md](PRACTICE_DAY.md)                | Practice day handling specifics.              |
| [PRIORITIES.md](PRIORITIES.md)                    | Algorithmic deep-dive (Stage 1/2 details). The root [`PRIORITIES.md`](../PRIORITIES.md) is the principles + lex-tuple spec; this one is the implementation reference. |

## Conventions

- **Living documents.** When code changes that affects spec, update
  spec in the same commit.
- **Anchor in code.** Practical, terse, references actual function
  names and line numbers wherever possible. If a doc reads
  aspirational instead of operational, sharpen it.
- **Don't conflate roadmap with handoff.** ROADMAP captures *what's
  planned*; HANDOFF captures *what shipped*. Per-workstream design
  detail goes in `workstreams/`; significant decisions go in
  `decisions/`.
- **Don't write a doc for trivial things.** Bug fixes are commit
  messages + HANDOFF entries. Variable naming is inline comments.
- **ADRs are immutable.** If a decision changes, write a new ADR
  that supersedes the old one.
