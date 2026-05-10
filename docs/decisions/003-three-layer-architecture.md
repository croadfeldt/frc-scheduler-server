# ADR 003 — Three-layer architecture

**Status:** Accepted
**Date:** Pre-Phase-0 refactor (the refactor that produced the
current architecture)
**Context:** The scheduler needed to separate concerns that had
been entangled: when matches happen (scheduling layer), what
matches are played (placement layer), and which real teams play in
which slots (assignment layer). Conflating these made every
algorithm change risky and made the API surface noisy.

## Decision

The pipeline has three explicit layers:

**Layer 1 — Day Config (timing).** When matches happen on a
calendar — match start times, breaks, cycle changes, day
boundaries, practice day. Lives in `day_config_v2.py` and the
front-end day-builder UI. Does NOT touch which teams are in
which match.

**Layer 2 — Abstract Schedule (placement).** Slot-labeled matches
that determine *which slots* play each other. Slots are
1..num_teams. The lex tuple's structural criteria (par_quad,
opp_quad, rb_metric, station_pen, surrogate_*) are computed at
this layer because they depend only on slot identity, not on
which real team is in each slot. Abstract schedules are
immutable artifacts that can be reused across multiple events
with the same fixture shape (same num_teams × matches_per_team).

**Layer 3 — Assigned Schedule (team identity).** Maps slots →
real team numbers. The lex tuple is preserved across this
mapping (relabeling doesn't change structural counts), so
assignment is a labeling problem, not a re-optimization. Phase 0
of the scheduler quality plan unified this with the SA so the
construction-phase output and the SA-optimized output share an
authoritative scoring path; assignment happens inside `_assign_unified`
in `app/scheduler.py`.

User-facing language uses "schedule" for the assigned form (Layer
3); the abstract form (Layer 2) is internal to the algorithm and
reuse machinery.

## Alternatives considered

**Single monolithic scheduler.** One function that takes config +
team list and returns a full schedule. Rejected because it makes
abstract reuse impossible (every event regenerates from scratch
even if the fixture shape is identical), and because it conflates
the structural problem with the labeling problem in a way that
made the SA's score function wrong before Phase 0 (slot SA was a
no-op because slot identity is permutation-invariant for every
metric except station/surrogate).

**Two layers (timing + scheduling).** Drop the abstract/assigned
distinction. Rejected because we want to reuse abstract structures
across events (the same 36-team × 7-MPT abstract works for any
36-team event) and because the lex-tuple computation is
substantially cheaper at the abstract layer (no team-identity
hashing).

**Four+ layers.** E.g., split assignment into "team selection"
+ "slot mapping." Rejected because no real concern requires it —
team selection is the input, slot mapping is the output.

## Consequences

**Good:**
- Each layer has a clear responsibility and a clear input/output
  contract.
- Abstract schedules can be reused, audited, and version-tagged
  separately from the assigned schedules they spawn.
- Changes to Layer 1 (day config V2) don't risk breaking Layers
  2-3.
- The bug that "slot SA was a no-op" is impossible to reintroduce
  because the layer separation makes slot-permutation-invariance
  obvious.
- The eval harness consumes Layer 3 outputs only, so improvements
  to construction (Layer 2) and identity (Layer 3) get measured
  end-to-end.

**Bad:**
- Three layers means three mental models, three sets of tests,
  and three places to look when debugging. A simple bug
  ("schedule is wrong") might require tracing through all three.
- The Layer 2 → Layer 3 boundary is subtle: the lex tuple is
  preserved by relabeling, but only if the relabeling is a
  bijection. The codebase enforces this via type contracts in
  `_assign_unified`, but it's a load-bearing invariant that a
  future contributor could break.
- Documentation has to explain which layer each concern lives at.
  ADRs and `THREE_LAYER_ARCHITECTURE_DESIGN.md` exist precisely to
  prevent this from becoming tribal knowledge.

## References

- `docs/scheduler/THREE_LAYER_ARCHITECTURE_DESIGN.md` — the full
  design with diagrams and pipeline traces.
- `app/scheduler.py` — `generate_matches` (entry point),
  `_assign_unified` (Layer 2 → 3), `score_tuple_for_schedule`
  (computes at Layer 2, preserved at Layer 3).
- `app/day_config_v2.py` — Layer 1.
- ADR 001 — the lex tuple, computed at Layer 2.
