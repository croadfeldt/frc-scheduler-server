# ADR 002 — FRC §10.5.2 paramount priority

**Status:** Accepted
**Date:** Project inception
**Context:** FRC's official rulebook §10.5.2 specifies a priority
order for schedule criteria. The rulebook describes "paramount"
priority for cooldown — a violation in cooldown can never be
traded for any improvement in any other criterion, no matter how
large. The scheduler must respect this.

## Decision

Cooldown violations sit at index 0 of the lex tuple (ADR 001) and
the SA hard-filters any move that would create a cooldown violation
where none existed. Specifically:

1. The construction phase produces a cooldown-clean schedule by
   construction (greedy match insertion respects the cooldown).
2. The SA's `_swap_preserves_cooldown()` check at
   `app/scheduler.py:1654` rejects any candidate move that would
   introduce a violation. This is a HARD filter, not a soft
   penalty.
3. Best-of-N comparison uses the lex tuple, so a non-zero
   cooldown_violations always loses to a zero — paramount priority
   is enforced at the comparison layer too.
4. The post-passes (R/B and station) are provably commutative
   with cooldown; they can't introduce violations.

The remaining seven priorities (par_quad, opp_quad, surrogate,
rb_metric, station_pen, surrogate_spread, match_equity) are
compared lexicographically — strictly better at a higher slot
beats any improvement at a lower slot.

## Alternatives considered

**Soft penalty with very large weight.** Weighted score where
cooldown gets weight ≥ sum of all other max contributions.
Rejected because the SA can still propose moves that violate
cooldown, accept them transiently if the rest of the schedule
improves enough, and never recover. Lex compare's hard separation
prevents this.

**Reject all cooldown-violating starting schedules, then optimize
freely.** Rejected because importing schedules from other tools
(MatchMaker, PDF, CSV) might bring in cooldown violations that
should be reported, not silently violated. The scheduler tolerates
violations in input but never *produces* them. (This still leaves
a known gap: imported schedules can land in the DB with violations.
Tracked in HANDOFF as future work — add a cooldown verifier on
import.)

**Treat cooldown as a soft criterion with a very steep convex
penalty.** Rejected because no convex function makes
"any-violation always loses to no-violation" without
discontinuity, and discontinuities defeat SA's accept/reject math.

## Consequences

**Good:**
- Matches FRC's rulebook semantics precisely.
- Hard filter prevents the SA from getting stuck in a basin that
  requires a cooldown violation as a stepping stone.
- The single keyword "paramount" is enough vocabulary for users to
  understand the design — they don't need to know about lex tuples.

**Bad:**
- The hard filter slightly restricts SA's move set on already-good
  schedules where violation-then-fix would be a faster path. In
  practice this hasn't been a quality issue because the cooldown
  basin is wide enough that the constructive build always lands in
  it.
- Imported schedules with cooldown violations don't get caught
  yet (no verifier on import). When that lands, it's a clear error
  message, not a silent fix-up.

## References

- FRC §10.5.2 (FIRST Robotics Competition rulebook, qualification
  schedule generation).
- `app/scheduler.py:1654` (`_swap_preserves_cooldown`).
- `docs/PRIORITIES.md` — the user-facing version of these rules.
- `docs/scheduler/PHASE_0_HARD_COOLDOWN_BRIEF.md` — the design
  brief for the hard-filter implementation.
- ADR 001 — lex tuple, of which this is the highest-priority slot.
