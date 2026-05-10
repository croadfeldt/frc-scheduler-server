# Contributing to FRC Match Scheduler

This file documents the contribution conventions for both human
and AI-assisted contributors. The session-deliverable protocol
described below is what makes "AI-assisted plus reviewer" workable
as a development model — it produces commit-ready bundles that a
reviewer can verify and ship without re-doing analysis.

For deep technical onboarding (architecture, algorithm,
licensing posture), read `REPRODUCTION_PROMPT.md` at the project
root.

## Reading order for new contributors

1. **README.md** — what is this thing, install, run.
2. **`PRIORITIES.md`** (root) — what the algorithm does, the lex
   tuple semantics.
3. **`docs/ROADMAP.md`** — where the project is going.
4. **`docs/HANDOFF.md`** — recent session log.
5. **`docs/decisions/`** — significant architectural decisions
   with reasoning.
6. **`docs/workstreams/`** — design docs for individual planned
   workstreams.
7. **`docs/scheduler/`** — algorithm-specific deep dives.

## Repository structure

```
.
├── README.md                       project overview, run/install
├── PRIORITIES.md                   FRC §10.5.2 placement priorities
├── REPRODUCTION_PROMPT.md          AI-contributor onboarding doc
├── CONTRIBUTING.md                 this file
├── app/                            backend (FastAPI + scheduler)
├── static/                         frontend (single-file editor + viewer)
├── scripts/scheduler_eval/         eval harness + adapters
├── tests/                          test suite (Python + JS)
├── openshift/                      deploy manifests + apply.sh
└── docs/
    ├── ROADMAP.md                  canonical "where this is going"
    ├── ARCHITECTURE.md             high-level system design
    ├── HANDOFF.md                  per-session log
    ├── decisions/                  ADRs (architecture decision records)
    ├── workstreams/                per-workstream design docs
    │   ├── rbac.md
    │   ├── schedule-lifecycle.md
    │   ├── ui-quality-exposure.md
    │   ├── scheduler-quality.md
    │   └── schedule-comparison.md
    └── scheduler/                  algorithm deep-dives + eval findings
```

## Commit conventions

**Subject line:** terse with an em-dash qualifier
(`<area> — <change>`). No emoji. Imperative mood.

Examples:
- `Day-banner — override replaces kind label, not appends`
- `Cycle-change off-by-one — apply afterMatch=N to gap N→N+1`
- `Eval harness — measure the SA path, not just construction`

**Body:** explain *why*; list *what* with file paths anchored so
a future reader can `grep` for them. Hard-wrap at ~72 columns.
Single-issue sessions get a single concise paragraph. Multi-issue
sessions structure the body by issue with a brief header
paragraph per issue, then a trailing `Files: …` line listing every
touched path.

**No co-author lines, sign-offs, or AI attribution.** The commit
message is about what changed and why. Authorship is captured by
git author/committer.

## Test requirements

Every commit must pass the full test suite. Twelve test suites,
~150 individual tests across Python and JS.

Run before committing:

```bash
# Python
for t in tests/test_day_config_v2.py tests/test_match_sa.py \
         tests/test_rb_balance.py tests/test_station_balance.py \
         tests/test_frc_compliance.py tests/test_migration_script.py \
         tests/test_eval_harness_sa_plumbing.py; do
    python3 "$t" || echo "FAILED: $t"
done

# JS
for t in tests/test_v2_url.js tests/test_field_three_up.js \
         tests/test_v2_scheduler_input.js \
         tests/test_cycle_change_walker.js; do
    node "$t" || echo "FAILED: $t"
done

# Eval harness self-check
python3 scripts/scheduler_eval/smoke_test.py
```

If you add a regression test for a bug fix, prefer pinning the
exact production source (substring guards on production HTML/JS,
property tests on Python) over reproducing the algorithm in the
test. The cycle-change walker test (`tests/test_cycle_change_walker.js`)
is the canonical pattern: substring guards on all six production
sites + a faithful re-implementation against a worked example.

## Deploy

```bash
cd ~/git/frc-scheduler-server
git pull && git add -A
git commit -m "<subject> — <change>

<body>

Files: <space-separated paths>"
git push
./openshift/apply.sh --build       # omit for doc-only sessions
```

`./openshift/apply.sh --build` is omitted when the session
touched only docs / tests / no-deploy-impact files. When in
doubt, include it — a redundant rebuild costs ~2 minutes; a
missed rebuild leaves production stale.

After deploy with UI changes, hard-refresh browsers (`⌘⇧R` /
`Ctrl+Shift+R`).

## Session-deliverable protocol (AI-assisted contributors)

When an AI-assisted session ends with code or doc changes, the
deliverable is **two tarballs + commit-ready commands + a commit
message**, every session.

### 1. Two tarballs

Both written to `/mnt/user-data/outputs/` and presented via
`present_files` at the end of the session:

**Full tree** — `frc-scheduler-server.tgz`. What the reviewer
extracts over their working tree.

```bash
cd /home/claude && tar czf /mnt/user-data/outputs/frc-scheduler-server.tgz \
  --exclude='frc-scheduler-server/.git' \
  --exclude='*/__pycache__' \
  --exclude='frc-scheduler-server/NOTES.md' \
  --exclude='frc-scheduler-server/notes.md' \
  --exclude='frc-scheduler-server/TODO.local.md' \
  frc-scheduler-server/
```

**Changes-only** — `frc-scheduler-changes-only.tgz`. Just the
files modified this session, with paths intact. Speeds up review
and diffing without changing the deploy flow (extracts over the
same top-level dir).

```bash
cd /home/claude && tar czf /mnt/user-data/outputs/frc-scheduler-changes-only.tgz \
  frc-scheduler-server/<modified-file-1> \
  frc-scheduler-server/<modified-file-2> \
  ...
```

The exclusion list deliberately does NOT exclude
`REPRODUCTION_PROMPT.md` or any tracked doc — those are updated
alongside code and the tarball is how those updates reach the
working tree. Local scratch files (`NOTES.md`, `notes.md`,
`TODO.local.md`) stay excluded.

### 2. Commit-ready commands

After the tarballs, output the literal command sequence the
reviewer runs against their working tree (the deploy block
above), with the actual commit message filled in.

### 3. Commit message

Per the conventions in the previous section. Terse, fact-dense,
code-anchored. No emoji. Hard-wrap at ~72 columns.

## When to write a doc

| Doc type | When | Where |
|---|---|---|
| ADR | Significant architectural decision | `docs/decisions/NNN-title.md` |
| Workstream design | New planned workstream that needs scoping | `docs/workstreams/<name>.md` |
| Roadmap entry | Planned work that affects scope | `docs/ROADMAP.md` |
| Session log entry | What just shipped | `docs/HANDOFF.md` |
| Algorithm deep-dive | Implementation detail or analysis | `docs/scheduler/` |
| Code comment | Local intent | inline |

ADRs are immutable once accepted. Workstream design docs evolve
with the workstream. Roadmap entries shift between version
buckets as priorities shift. HANDOFF entries are append-only.

If something doesn't have a design doc, it shouldn't be on the
roadmap yet — write the design first.

## When NOT to write a doc

- Bug fixes — commit message + HANDOFF entry is enough.
- Trivial implementation choices (variable naming, file layout) —
  inline comments suffice.
- Workstream-specific designs that already have a doc in
  `workstreams/` — extend the existing doc, don't write a new one.
- Speculative or aspirational work that hasn't been decided to
  ship — keep these in personal notes until they become real.

## License

GPL-3.0-or-later. All new code files include the standard SPDX
header:

```python
# SPDX-License-Identifier: GPL-3.0-or-later
# FRC Match Scheduler
# Copyright (C) 2025 FRC Match Scheduler Contributors
```

The licensing posture re. MatchMaker (we are an independent
implementation, not a port or wrapper) is documented in
`docs/scheduler/MATCHMAKER_LICENSING_BRIEF.md`. New scheduler-side
work should review that brief before borrowing patterns from
MatchMaker's published documentation.
