# ADR 004 — No bit-exact reproducibility guarantee

**Status:** Accepted
**Date:** 2026-05-10
**Context:** The README has historically claimed "same `assign_seed`
always produces identical output. Seeds are auto-generated, stored in
the database, and encoded in the share URL so any schedule can be
exactly reproduced." Several near-future planned changes break this
guarantee — Phase 5 Plan C (lex-tuple expansion), any quality-preset
iteration count change, post-pass redesign, or smarter SA cooling
schedules. A decision is needed about whether to commit to maintaining
bit-exact replay across versions, accept controlled divergence, or
drop the guarantee entirely.

## Decision

**The schedule itself is the artifact.** Bit-exact replay from a seed
is no longer a guarantee.

- Schedules are saved in the database. The DB row is the source of
  truth for what the schedule is.
- Share URLs fetch the saved schedule from the DB; they do not
  regenerate it from a seed.
- The `assign_seed` field is informational metadata. It records what
  RNG state produced this schedule under the algorithm version that
  was running at the time. It can be used to regenerate *a similar
  schedule* under a current algorithm version, but the result may
  not match the stored schedule bit-for-bit.
- Algorithm version is recorded in stored schedules so audit and
  debugging tools can know what produced a given output.

## What this enables

The reproducibility constraint was a hidden tax on every algorithm
change. Lifting it removes that tax:

- Quality preset iteration counts can be tuned without breaking
  past schedules.
- The lex tuple can be extended (Phase 5 Plan C) without a
  versioning escape hatch.
- Post-pass move sets can be refactored.
- SA cooling schedules can be smarter.
- The construction phase can change.
- Workers can be added or removed (`BEST_OF_N_TARGET`,
  `CPU_WORKERS`) without breaking past schedules.

None of these required complex versioning machinery to ship — the
guarantee was the constraint, and dropping it is the unlock.

## What this loses

Three use cases that bit-exact replay would have served:

1. **Disaster recovery (DB lost, share URL survived).** Replay
   seed → recover schedule. **Backups address this more directly**
   and cover more failure modes (tampering, schema migration). Not
   a real loss.

2. **Audit / dispute ("did this schedule come from the algorithm
   or was it edited?").** The `assigned_schedule_history` table
   already records edits. Re-running the seed and diffing tells
   you the same thing the history table does. Not a real loss.

3. **Algorithm debugging ("why did SA produce this output?").**
   A developer wants to step through. This has real value, but
   only at the time of debugging, only across small algorithm-
   version deltas, and only when the developer has access to the
   exact code that produced the schedule. The seed is still
   useful here as informational metadata, just not as a
   guarantee.

In exchange, the project gets unconstrained algorithm evolution.
That's a clear trade for the current scale and stage of the
project.

## Alternatives considered

**Strict reproducibility** — store algorithm version with each
schedule; new algorithm version = new schedules; old schedules
replay only against the frozen old code path. Rejected because
the old code paths can never be deleted, complexity grows with
every version, and the use cases that benefit are rare.

**Versioned best-effort** — schedules carry version tags; replays
may diverge with a "regenerated under newer algorithm" warning UX.
Rejected because the warning UX is non-trivial to design, the
diverged-output case is the common case (any algorithm change
likely diverges), and the value to the user of "here's a
similar-but-not-identical schedule" is unclear.

**Best-effort, with seed as informational metadata.** Accepted.
Simplest, matches what the system actually does (DB is the source
of truth), no UX changes needed beyond updating the README.

## Consequences

**Good:**
- Algorithm evolution is no longer gated on a versioning policy.
- README claim now matches implementation reality.
- The codebase doesn't have to carry frozen old algorithm paths
  for replay support.
- Future algorithm-quality work (Phase 5 Plan B/C and beyond) has
  no reproducibility blockers.

**Bad:**
- A user who happens to rely on bit-exact replay (e.g., they've
  scripted something around it) will be surprised. Mitigation:
  update the README explicitly, surface the policy in the share-URL
  UX if a re-generation feature is ever built.
- "Same seed produces different output across versions" can feel
  unprincipled to users coming from systems where seed-determinism
  is sacred (random-number generators, reproducible builds). The
  framing matters: this is a *scheduling* tool, not an RNG; the
  schedule itself is the artifact, the seed is just how we got
  there once.

## Action items

- [x] Update `README.md` to remove the bit-exact replay claim and
      replace it with the schedule-is-the-artifact framing.
      *(Done 2026-05-10 alongside this ADR.)*
- [x] Update `docs/REPRODUCTION_PROMPT.md` if it makes claims about
      reproducibility (it does, in passing).
      *(The doc's reading-order section was rewritten in the
      structural reorg; the seed-related claim is gone.)*
- [x] Remove the user-facing seed UI: the "seed:" / "assign seed:"
      copy-able displays in the share bar of `static/index.html`,
      the `copySeed()` / `copyAssignSeed()` helpers, the
      `?seed=` / `?aseed=` URL emitters, and the legacy autoload-
      from-seed-only path. Schedule ID and Assignment ID stay
      (they're DB primary keys, useful as canonical share
      pointers). *(Done 2026-05-10.)*
- [ ] Surface algorithm version in stored schedules. Could be as
      simple as the git commit short-hash recorded at generation
      time. Useful for audit/debug workflows; doesn't promise
      anything. *(Deferred — not gating any current work.)*

## References

- README.md (current bit-exact replay claim — to be removed).
- `app/db.py` — `assigned_schedules.assign_seed` field.
- ADR 001 — the lex tuple, which Phase 5 Plan C might extend.
- HANDOFF §5.x — Phase 5 work (the proximal driver of this
  decision).
- A "Speed-Proposals review" doc from a separate session that
  raised reproducibility as a constraint on five separate proposals.
