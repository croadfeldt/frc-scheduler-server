# ADR 001 — Lex tuple design

**Status:** Accepted
**Date:** 2026 (Phase 0 of scheduler quality plan)
**Context:** The scheduler needs a single comparable score for
two candidate schedules so simulated annealing can accept/reject
moves and best-of-N can pick a winner. The score must respect FRC
§10.5.2's paramount-priority semantics.

## Decision

Schedule quality is represented as an 8-element **lexicographic tuple**
compared element-by-element from highest to lowest priority. The
authoritative implementation is `score_tuple_for_schedule()` in
`app/scheduler.py`, which returns:

```
(cooldown_violations,
 par_quad,           # sum of (partner_count_ij)^2 across all (i,j)
 opp_quad,           # sum of (opponent_count_ij)^2
 surrogate_count,
 rb_metric,          # max R/B imbalance ≥24t, or swap count <24t
 station_pen,        # driver-station rotation penalty
 surrogate_spread,   # variance in surrogate placement
 match_equity)       # currently inert (always 0)
```

Lex comparison: schedule A beats schedule B if A's tuple is
strictly lower at the highest-priority element where they differ.
Ties at every element mean equivalent schedules.

## Alternatives considered

**Weighted scalar score.** A single float = sum of weighted terms.
Rejected because no fixed weights can represent paramount priority —
any weight on cooldown_violations large enough to dominate par_quad
also makes par_quad differences irrelevant when cooldown_violations
is at floor. Lex compare is the natural representation of "this
criterion always beats that one."

**Multi-objective Pareto frontiers.** Track non-dominated
schedules; let the user pick. Rejected because users want one
schedule, not a list of trade-offs, and FRC's spec gives a clear
priority order anyway.

**Hierarchical filters.** First eliminate cooldown violators, then
sort survivors by par_quad, etc. Rejected because it's lex compare
in disguise but harder to reason about and code consistently across
SA accept/reject, best-of-N comparator, and audit display.

## Consequences

**Good:**
- Faithful to FRC §10.5.2's paramount-priority semantics.
- Single source of truth: `score_tuple_for_schedule()` is called
  from SA accept/reject, best-of-N comparator, and the eval harness.
- Easy to extend by appending new elements at the right priority.
- Easy to debug — print the tuple, see exactly which criterion is
  the bottleneck.

**Bad:**
- The legacy `score_schedule()` float (a weighted sum) is stored
  on `assigned_schedules.score` and exported in CSV. It's NOT
  lex-monotone with the tuple, but it persists for backwards
  compatibility. See HANDOFF prior-session notes; documented as a
  known issue.
- The 8th slot (`match_equity`) is currently inert (always 0).
  Either implement it or drop it from the tuple — see scheduler-quality
  workstream.
- Lex compare is not differentiable, so gradient-based
  optimization is out. SA and best-of-N work fine; CP-SAT would
  too. Rules out heuristics that need a gradient.

## References

- `app/scheduler.py` lines 808 (`score_tuple_for_schedule`),
  1010 (`_score_from_state`).
- `docs/PRIORITIES.md` — full FRC §10.5.2 mapping.
- `docs/scheduler/THREE_LAYER_ARCHITECTURE_DESIGN.md` — broader
  architectural framing this fits into.
- ADR 002 — paramount priority in detail.
