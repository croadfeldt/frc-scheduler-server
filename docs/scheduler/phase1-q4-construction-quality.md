# Phase 1 — Q4 first-cut: Construction quality on tight fixtures

**Date:** 2026-05-12
**Status:** Empirical finding from F2 (SA bug investigation). Bug
is fixed defensively (raise `ConstructionMalformedError` + caller-
side retry); root cause is architectural and feeds into Q4.

**Source:** `docs/workstreams/best-possible-schedule.md` Q4

---

## What Q4 asks

> *Should the two-stage architecture (greedy construction → SA
> optimization) stay, or fold to single-stage CP-SAT for small
> fixtures? At what fixture-size threshold does each approach win?*

This first cut answers a related but narrower question: **does the
current greedy construction phase produce valid schedules on all
fixture shapes?** The answer is no — and that's Q4 data.

---

## The finding

The greedy construction in `app/scheduler.py:generate_matches` paints
itself into corners on tight fixtures. It produces a "valid" partial
schedule, then runs out of teams to fill the last match's alliances,
producing a final match with fewer than `teams_per_alliance` (3)
teams on one side.

Measured malformation rate across 30 seeds per fixture, at the
largest feasible `ideal_gap` (cooldown_max from Q5):

| Fixture | ideal_gap | Malformed rate |
|---|---:|---:|
| 8t × 6MPT | 1 | 0/30 (0%) |
| 10t × 6MPT | 1 | 4/30 (13%) |
| 12t × 6MPT | 2 | 1/30 (3%) |
| 12t × 7MPT | 2 | 5/30 (17%) |
| 16t × 6MPT | 3 | 1/30 (3%) |
| 18t × 6MPT | 3 | 0/30 (0%) |
| 24t × 6MPT | 3 | 0/30 (0%) |
| 36t × 7MPT | 3 | 0/30 (0%) |

**Pattern:** small fixtures (10-12 teams) with high MPT-relative-to-N
fail noticeably. Fixtures at or above 16 teams are fine.

Production fixtures (≥36 teams, state events) are unaffected. This
is a small-event-specific issue.

---

## What we did about it (defensive fix)

Added `ConstructionMalformedError` exception class in
`app/scheduler.py`. The construction phase now checks all generated
matches for short alliances and raises immediately if any are found.
Callers can retry with a different seed.

The test helper `tests/test_match_sa.py:make_test_schedule` retries
up to 20 times on this exception (with deterministic seed
progression: `seed + attempt * 7919`). All 13 test suites continue
to pass.

This is a **defensive fix, not a root-cause fix**. The construction
phase still has the underlying quality issue; we just now fail
visibly instead of silently producing malformed output that crashes
the SA later.

---

## What this means for Q4

The two-stage architecture (greedy construction → SA refinement) has
a known failure mode on tight fixtures. The construction is greedy
and doesn't backtrack; once it paints itself into a corner, the SA
inherits broken input.

Three architectural responses are possible:

**Response A: Improve the construction algorithm.** Add backtracking
or constraint-propagation logic to construction so it can recover
from dead-end choices. Substantial engineering work. Doesn't change
the architecture.

**Response B: Replace construction with CP-SAT for tight fixtures.**
CP-SAT can solve construction-as-constraint-satisfaction directly
(no greedy choices, no dead-ends). For small fixtures CP-SAT
terminates fast. The two-stage architecture becomes "CP-SAT
construction → SA refinement" for tight fixtures, "greedy
construction → SA refinement" for the rest. This is the natural
Q4 direction.

**Response C: Accept the failure rate and retry.** The defensive fix
we shipped today, formalized as production behavior. Callers retry
on `ConstructionMalformedError` and eventually get a valid schedule.
Wastes compute but is simple and correct.

**My read:** Response B is the right Q4 answer when combined with
Phase 1 Q2's finding that CP-SAT is viable on small fixtures. The
size at which CP-SAT runs out of steam (~12 teams in the first-cut
encoding, possibly higher with encoding refinement) overlaps
exactly with the fixture sizes where greedy construction fails.
CP-SAT's strength is the small-fixture regime where greedy is
brittle.

This isn't a Phase 1 conclusion yet — it depends on whether F1
(CP-SAT encoding refinement) succeeds at expanding CP-SAT's
reach. But it's a strong candidate hypothesis.

---

## Open follow-ups

- **F-Q4-a.** Once F1 lands (refined CP-SAT encoding), measure
  whether CP-SAT can solve the construction problem for the tight
  fixtures where greedy fails (10t × 6MPT, 12t × 7MPT, etc.). If
  yes, the architectural answer (Response B) is supported by data.
- **F-Q4-b.** Document construction-quality dependency on (n, MPT,
  cooldown) more thoroughly. The 30-seed sample here is small;
  larger samples might surface other failure modes.
- **F-Q4-c.** Consider whether the construction-quality issue
  affects schedule quality even when it doesn't outright crash. A
  construction that *almost* paints itself into a corner may
  produce poor pairing distributions that the SA can't recover
  from in reasonable time.

---

## Code reference

- `app/scheduler.py:88` — `ConstructionMalformedError` class
- `app/scheduler.py` (line ~770) — malformation detection block
- `tests/test_match_sa.py:make_test_schedule` — retry helper

---

*F2 was scoped as "fix the SA IndexError at 12t × 6MPT." It turned
out the SA was correct; the construction phase was producing
malformed input. The cooldown-feasibility validation (Q5) fixed
one half of the issue; the construction-malformation check + retry
fixes the other half defensively. The root-cause architectural
answer is part of Q4.*
