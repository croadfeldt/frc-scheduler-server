# Reference Scheduler — Licensing and Interop Brief

**Repository:** `github.com/croadfeldt/frc-scheduler-server`
**Document type:** Legal/architectural constraint brief
**Status:** Decision document — establishes hard boundaries for what
the implementing session can ship
**Audience:** Internal — not a public position statement
**Companion docs:**
- `docs/decisions/003-three-layer-architecture.md` — the architecture this brief constrains
- `docs/decisions/005-reference-scheduler-as-peer.md` — the peer-not-competitor positioning
- `docs/scheduler/REFERENCE_SCHEDULER_ALIGNMENT.md` — historical context for behavioral parity decisions
- `docs/scheduler/EVAL_FINDINGS.md` — empirical evaluation that motivates the work this brief constrains

---

## Why this document exists

The FRC ecosystem has an established reference scheduler — the tool
the official Field Management System uses to generate match
schedules. Its design is publicly documented in a white paper, and
its behavior is what FRC teams expect from any new tool that
schedules qualification matches. Before any code is written that
bundles, calls, or distributes the reference tool, the implementing
session needs to know exactly what's permitted and what isn't. This
brief establishes the hard line so design choices stay on the right
side of it.

**Bottom line up front:** the project will independently reimplement
the algorithmic ideas from publicly documented descriptions, will
not bundle or invoke the reference tool's binary, will not
redistribute its artifacts, and will validate output against
historical FRC event data (via The Blue Alliance API) rather than
against live runs of the reference tool. This is the legally clean
path.

---

## The licensing posture

The reference scheduler is distributed under a proprietary,
evaluation-only license. The key implications for our work:

1. **Non-profit use is not exempted.** The license language draws no
   distinction between commercial and non-profit use. Both require
   explicit permission beyond evaluation.

2. **"Evaluation purposes only" is narrow.** It permits a single
   user running the tool locally to assess whether to license it. It
   does not permit redistribution, bundling, hosting, or making its
   output available as a service to third parties.

3. **Algorithm ideas are not protected; specific code and binaries
   are.** The published algorithm description and the public
   discussion of the station-balancing approach exist so the
   underlying techniques can be discussed, taught, and independently
   implemented. That's separate from copying or wrapping a binary.

---

## Hard rules for implementation

### Do NOT do any of these

These are bright-line prohibitions. If a design proposal requires
any of them, stop and surface it before writing code.

1. **Do not bundle the reference tool's binary** in the repo, in
   container images, in release artifacts, or in any installer.
   This is redistribution and is not permitted.

2. **Do not invoke the reference tool as a subprocess** from any
   code path that runs in production, in a hosted service, in CI,
   or in any user-facing feature. The "evaluation only" language
   excludes use as a service backend.

3. **Do not auto-download the reference tool's binary** at install
   time, build time, or runtime. Hosting elsewhere does not change
   the legal substance — fetching and executing on behalf of a user
   constitutes use beyond evaluation.

4. **Do not use the reference tool's brand name** in our code, UI,
   configuration, marketing copy, or user-facing documentation.
   Trademarks and brand belong to the upstream tool's authors. Use
   descriptive names that credit the *technique* without invoking
   the *brand*.

5. **Do not copy code from the reference tool's binary, decompiled
   output, or any leaked source** even if it appears on community
   forums. Independent implementation from published descriptions
   only.

6. **Do not represent our tool's output as the reference tool's
   output** even when the algorithm is faithfully reimplemented.
   Output provenance must say what it actually is.

### DO these instead

1. **Reimplement independently** from publicly published
   algorithmic descriptions. This path is fully permitted.

2. **Credit the inspiration appropriately** in internal
   documentation and ADRs. Attribution is legally protective and
   reflects the actual lineage of the work. Public-facing copy
   should describe approaches generically (e.g. "simulated
   annealing with separable post-passes") rather than by branded
   tool name.

3. **Use TBA event data as the validation baseline.** Past FRC
   qualification schedules are public record via The Blue Alliance
   API. Comparing our tool's output to TBA-fetched schedules
   compares against public event records, not against a copy of
   any proprietary tool. This is the legally clean way to do the
   comparison harness.

4. **Allow users to compare against their own external runs.** If a
   user has separately downloaded a reference scheduler for
   evaluation, they can run both tools on the same input and
   import both schedules into ours for comparison. The tool can
   accept a CSV import of an externally-generated schedule and
   produce diff metrics. We never run or distribute the external
   tool; the user does, on their own machine, under their own
   evaluation.

---

## Naming guidance

Algorithm suites and user-facing artifacts use descriptive,
technique-credit names:

| Concept | Name |
|---|---|
| The classical simulated-annealing approach for FRC pairing uniformity | "Simulated Annealing (SA)" or "SA-classical" |
| SA with separable post-passes for R/B balance and station balance | "SA + Decomposed Cleanups" |
| The station-balancing approach (credit by technique-author when needed in internal docs) | "Station Balance Pass" |

In algorithm suite metadata (technical documentation only, not
user-facing UI), include attribution to the algorithmic technique
and link to the published source description so the lineage is
clear for anyone reading the implementation. User-facing copy and
UI stay descriptive of *what* the technique does without naming the
upstream tool.

---

## Validation harness — TBA-based design

The validation strategy uses public FRC event data, not live runs
of any external scheduling tool.

### What the harness does

1. **Fetches a corpus** of qualification schedules from past FRC
   events via the TBA API. Target: 20–30 events spanning a range
   of (N, MPT) values. These schedules are public record.

2. **Computes diversity metrics** on each fetched schedule using
   our tool's metrics extractor — partner-repeat distribution,
   opponent-repeat distribution, station balance, alliance balance,
   surrogate distribution, gap statistics. This treats published
   FRC schedules as the reference.

3. **Generates schedules** with our SA-based algorithm at matching
   parameters (N, MPT, cooldown derived from event size) for each
   event in the corpus. Computes the same metrics.

4. **Produces a comparison report** showing per-metric deltas
   between the TBA baseline and our output.

5. **Runs as CI** on a defined schedule. Regression alerts if any
   metric drifts more than 5% from the established baseline.

### What this gives us

- **Empirical validation** that our SA-based suite produces
  schedules of comparable quality to published FRC schedules.
- **A defensible claim** that the project produces FRC-aligned
  output, grounded in measured comparison against the corpus of
  actual FRC events.
- **A regression detector** so future changes don't silently
  degrade quality.
- **Zero licensing exposure.** TBA data is public record. Our
  reimplementation is independent. The comparison is between our
  output and public records.

### What this does NOT give us

- **Optimality claims for individual schedules.** We cannot say
  "an external scheduler would have produced exactly this
  schedule." We can only say "our schedule's metrics fall within
  the distribution of published FRC schedules at this size."
- **Bug-for-bug compatibility.** If an external scheduler has a
  quirk we haven't reproduced, the harness might flag it as a
  difference. We're not aiming for bug compatibility, we're aiming
  for *quality parity*.

---

## User-supplied schedule imports

Permitted and worth supporting as an optional feature.

A user who has independently run an external scheduler (under that
tool's evaluation license, on their own machine) can run it on
their event roster, get a schedule, export it as CSV, and import
it into our tool for comparison or analysis. Our tool's
responsibility:

- Accept a schedule CSV import. Parse it. Compute diversity
  metrics on it. Display side-by-side with our tool's output.
- Never bundle, host, or invoke the external tool ourselves.
- Be clear in the UI that the import is the user's responsibility
  — they are running the external tool under their own license.

This gives power users head-to-head comparison without putting
our project on the wrong side of any license line. The legal
posture is: *our user evaluated the external tool themselves; we
just accept any schedule CSV regardless of source.*

The import path should be **generic** — accept any schedule CSV,
not specifically a single external tool's format. Other schedulers
produce schedules too; we accept them all and don't single out one
in the import UI.

---

## What's NOT being decided in this brief

- **Whether to ever seek a license from the reference tool's
  authors.** That's a future decision. If we ever want to bundle a
  binary or invoke it as a service, we approach the question then.
  For now we don't need to.
- **Sanctioning body submission.** Whether our criteria suites
  ever get reviewed or endorsed by FIRST is a separate, much
  larger conversation.
- **Trademark guidance for the project name itself.** "FRC
  Scheduler" is descriptive and unlikely to conflict with anything.

---

## Quick-reference checklist for implementers

When writing code for any algorithm suite, post-pass, or
validation feature, check:

- [ ] Are we copying any external tool's code, binary, or output? → **STOP, not allowed.**
- [ ] Are we invoking any external tool's process? → **STOP, not allowed.**
- [ ] Are we bundling any external tool's artifact? → **STOP, not allowed.**
- [ ] Are we using an external tool's brand name in user-facing surfaces? → **STOP, rename to a descriptive term.**
- [ ] Are we implementing from a published algorithm description? → **OK, proceed with technique-level attribution in internal docs.**
- [ ] Are we comparing to TBA-fetched event data? → **OK, proceed.**
- [ ] Are we accepting user-imported schedule CSVs? → **OK, proceed; keep the import path generic.**
- [ ] Are we crediting the algorithmic technique in internal documentation? → **Required; verify before merging.**

---

*This brief establishes hard constraints. Subsequent phase briefs
and implementation work are bound by these rules. If a future
feature requires reconsidering them, surface that explicitly and
seek a license from the upstream tool's authors before designing
around the assumption.*
