# Architecture Decision Records

This directory captures the significant architectural and design
decisions made for FRC Match Scheduler. Each ADR is a short document
explaining what was decided, what the alternatives were, and what
context shaped the choice.

The point of an ADR is to capture **why** something is the way it is
in a place where future contributors (or future-you) can find it
without git-archaeology. Code comments capture local intent; ADRs
capture system-level intent.

## Format

Each ADR is a markdown file with the format:

```
# ADR NNN — Title

**Status:** Accepted | Superseded by ADR NNN | Deprecated
**Date:** YYYY-MM-DD
**Context:** what situation prompted the decision
**Decision:** what we decided
**Alternatives considered:** other options and why they were
                              rejected
**Consequences:** what this means for the codebase, good and bad
**References:** links to design docs, code, prior discussions
```

ADRs are immutable once accepted. If a decision changes, write a new
ADR that supersedes the old one — don't edit the old one (other than
to update its Status field).

## Index

- [001 — Lex tuple design](001-lex-tuple-design.md)
- [002 — FRC §10.5.2 paramount priority](002-frc-paramount-priority.md)
- [003 — Three-layer architecture](003-three-layer-architecture.md)
- [004 — No reproducibility guarantee](004-no-reproducibility-guarantee.md)
- [005 — Reference scheduler as peer, not competitor](005-reference-scheduler-as-peer.md)
- [006 — Server-only construction; retire browser scheduler](006-server-only-construction.md)

## When to write an ADR

Write an ADR when:
- A non-trivial design decision is being made (not a bug fix or a
  refactor)
- The decision will shape future work (other workstreams will have
  to live with it)
- Reasonable engineers could disagree about the choice
- The reasoning isn't obvious from the code alone

Don't write an ADR for:
- Trivial implementation choices (variable naming, file layout)
- Bug fixes (commit message + HANDOFF entry is enough)
- Workstream-specific designs that already have a design doc in
  `docs/workstreams/` (the design doc IS the record)
