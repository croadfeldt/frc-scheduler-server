# docs/

Living specification documents for the FRC scheduler. These are the
source of truth for what the system does, what it should do, and how
we get from here to there.

## V2 day_config workstream *(active)*

| Document                                  | What it covers                                     |
|-------------------------------------------|----------------------------------------------------|
| [V2_SPEC.md](V2_SPEC.md)                  | The canonical V2 day_config model — data shape, tier rules, validation, materialization. |
| [V1_RETIREMENT.md](V1_RETIREMENT.md)      | Inventory of every V1-coupled site in the codebase, with replacements and kill order. |
| [DB_V2_MIGRATION.md](DB_V2_MIGRATION.md)  | Schema state, target state, migration SQL, rollback procedure. |
| [V2_ROADMAP.md](V2_ROADMAP.md)            | Phased rollout plan from current state to V1-free codebase. |

## Existing project docs

| Document                                          | What it covers                                |
|---------------------------------------------------|-----------------------------------------------|
| [ARCHITECTURE.md](ARCHITECTURE.md)                | Design principles and structural decisions.   |
| [PRIORITIES.md](PRIORITIES.md)                    | Team-placement scheduling algorithm.          |
| [AUTH_DESIGN.md](AUTH_DESIGN.md)                  | Authentication and authorization model.       |
| [INTEGRATIONS.md](INTEGRATIONS.md)                | TBA / Nexus / Statbotics / FMS integrations.  |
| [PRACTICE_DAY.md](PRACTICE_DAY.md)                | Practice day handling specifics.              |

## How the V2 docs are used

1. **Building a feature:** read [V2_SPEC.md](V2_SPEC.md) first. If
   the feature requires a new block type or model change, the spec
   gets updated *before* the code is written.

2. **Fixing a bug:** if the bug is "V2 edit doesn't reflect somewhere,"
   check [V1_RETIREMENT.md](V1_RETIREMENT.md) — there's likely a V1-
   coupled read site to migrate. Fix the site AND check it off in
   the retirement doc.

3. **Reviewing the plan:** [V2_ROADMAP.md](V2_ROADMAP.md) phase
   tracker tells you where we are and what's next.

## Convention

These are *living* documents. They drift out of sync only at the
project's peril, so:

- When code changes that affects spec, update spec in the same commit.
- When a retirement item is completed, mark it ✓ with a one-line note.
- When a phase exits, update [V2_ROADMAP.md](V2_ROADMAP.md) status.

Doc style: practical, terse, anchored in actual code references (line
numbers, function names). If a doc reads as aspirational instead of
operational, it needs to be sharpened.
