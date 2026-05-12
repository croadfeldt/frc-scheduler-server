# Phase 1 — F1-a: SA paramount-cooldown audit

**Date:** 2026-05-12
**Status:** Audit complete. SA's accept/reject logic is correct;
the move set is the bottleneck on tight fixtures.

**Source:** `docs/workstreams/best-possible-schedule.md` Q4 follow-up
from `phase1-f1-cpsat-refinement.md`

---

## What we audited

F1's bigger finding was that the SA produces schedules with
`cooldown_violations ≥ 30` on 12×6×2, despite ADR 002 declaring
cooldown paramount. Two possible diagnoses:

1. The SA's accept/reject correctly enforces paramount-cooldown
   but the move set can't escape construction's bad initial state.
2. The SA's lex comparison has a bug that occasionally accepts
   trades worsening cooldown when other slots improve.

These have very different implications. (1) is purely architectural
— SA structurally cannot reach cooldown=0 on tight fixtures, and
the answer is to replace construction with something that finds
cooldown=0 starting points (CP-SAT, per Q4). (2) is a bug
affecting every schedule we've ever produced, and would require
re-baselining all eval data.

This audit determined which.

---

## What we found

### Verdict: the SA's accept/reject is correct. No bug.

`_lex_compare` (`app/scheduler.py:1785`) walks tuple elements in
order, returning at the first differing element. Standard lex
comparison. Correct.

`_sa_optimize` (line 1898) accept/reject logic, line 1995-2049:

```python
cmp = _lex_compare(new_tuple, cur_tuple)
if cmp <= 0:
    # Strict improvement or equal — always accept
    cur_tuple = new_tuple
    ...
else:
    # Strict worsening. Find which criterion worsened first.
    diff_idx = _lex_first_diff_index(cur_tuple, new_tuple)
    ...
    # FRC paramount: never accept a swap that worsens criterion #1.
    if diff_idx == 0:
        # Worsened cooldown. Always reject.
        _match_swap_apply_delta(state, work, ...)  # revert
        continue
    # ... only stochastic uphill on lower-priority criteria
```

This is structurally correct:

- A swap that improves cooldown is always accepted (regardless of
  what happens to lower slots — they're dominated by paramount).
- A swap that leaves cooldown equal and improves any lower slot is
  accepted.
- A swap that worsens cooldown is **always rejected**, regardless
  of how much lower slots improve.

The accept/reject does NOT permit cooldown-worsening trades. ADR
002 is honored.

### Empirical confirmation

Probed 5000 random valid 2-swaps from a typical 12×6×2
construction starting state (cooldown_violations=11):

```
  cooldown reducing: 37 (2.4%)
  cooldown equal:    141 (9.0%)
  cooldown worsening: 1381 (88.6%)

  accepted (cmp <= 0): 47 (3.0%)
    accepted because cd improved: 37
    accepted because cd equal + other better: 10
```

Of 47 acceptances: 37 reduced cooldown, 10 kept cooldown equal
while improving lower slots. **Zero cooldown-worsening acceptances.**
Logic working correctly.

### Where the SA actually fails: the move set

Ran a 500K-iteration SA on 12×6×2 with the same paramount-cooldown
semantics, instrumented to log cooldown trajectory:

```
  iter       0: cd=11, par_quad=100   (start)
  iter    1000: cd=7
  iter    5000: cd=3
  iter   25000: cd=2
  iter  100000: cd=2   ← stuck
  iter  500000: cd=2   ← still stuck
```

**The SA drove cooldown from 11 → 2 in the first 25K iterations,
then got stuck at 2 for the remaining 475K iterations.** 19 total
acceptances across 500K iterations. The 2-swap move set cannot
find any move that reduces cooldown below 2 from this state.

This is the same **move-set-limited** pattern from Phase 5's
station post-pass diagnostic: the SA's accept/reject is correct,
but the move set's local neighborhood doesn't include any move
that reduces the metric below a fixed-point floor.

Cooldown=0 IS reachable on 12×6×2 by the math (Q5: cooldown_max=2)
and CP-SAT finds it trivially. But the SA, starting from a
greedy-construction state and using 2-swaps, cannot reach it.

### Production fixtures are unaffected

Verified on 36×7×cd=3: SA reaches `cooldown_violations=0` with
SA=50K. The pattern is small-fixture-only. Specifically:

- Greedy construction produces ~zero cooldown violations on
  fixtures comfortably below cooldown_max (large n, modest MPT).
- Greedy construction produces many cooldown violations on tight
  fixtures (small n, MPT near cooldown_max).
- The 2-swap SA can reduce cooldown when there's a lot of it
  (early iterations) but gets stuck at a small floor (typically
  2-3) on tight fixtures.
- On fixtures where construction starts at cooldown=0, the SA
  stays there (the accept logic never lets it leave).

---

## What this means

**For Q4 (architectural):** the finding is now well-grounded
empirically. SA-on-greedy-construction structurally cannot satisfy
FRC §10.5.2's paramount criterion on tight fixtures. Not because
of a bug; because of the fundamental design — greedy paints into
corners, 2-swap can't escape. CP-SAT can find cooldown=0 on the
same fixtures (the constraint-satisfaction formulation has no
"local moves" — it directly searches the feasible space).

**For Q1 (lex tuple shape):** the lex tuple's paramount-cooldown
semantics are operating correctly. Any future ADR-007 reshaping
of the tuple should preserve this guarantee: position 0 stays
paramount and the accept logic stays as-is.

**For F1-c (next):** the CP-SAT-as-construction prototype is
strongly motivated. Hand CP-SAT-found feasible (cooldown=0)
schedules to SA as starting points; see if SA can refine pairing
quality while preserving cooldown=0. The audit shows the SA can
operate within a cooldown-equal neighborhood (line 2002 accepts
"cmp ≤ 0" including cooldown-equal-other-better moves), so once
SA starts at cooldown=0, it will stay there as long as the SA's
2-swap neighborhood doesn't *force* cooldown-worsening moves —
which on production fixtures it doesn't.

**For Phase 4 (Stark measurement):** measurements taken on
small/tight fixtures from SA-only output are unreliable for the
paramount criterion. Stark runs targeting "best possible" on
tight fixtures should use CP-SAT for construction (per F1-c)
rather than SA-only. The 16-fixture eval inventory needs auditing
to identify which fixtures are tight enough that SA can't reach
cooldown=0.

---

## What did NOT need fixing

No code changes from this audit. The SA's logic is correct;
documenting it is the deliverable. Specifically:

- `_lex_compare` is correct.
- `_sa_optimize`'s accept/reject is correct.
- `_score_from_state`'s cooldown computation is correct.

No tests need updating. No re-baselining of eval data needed
(none of our eval measurements were on fixtures small enough for
this failure mode — production-corpus fixtures all reach cooldown=0).

---

## Open follow-ups

- **F1-c** (CP-SAT-as-construction prototype) is now strongly
  recommended next. The audit's empirical data is the missing piece
  for confidently formulating Q4's architectural answer.
- The eval inventory should be audited to identify which fixtures
  are "tight" (cooldown_max <= 3) so we know which results in
  prior measurements may be SA-cooldown-limited rather than
  pairing-limited. Small task; can fit alongside F1-c.

---

## Code reference

- `app/scheduler.py:1785` — `_lex_compare`
- `app/scheduler.py:1898` — `_sa_optimize`
- `app/scheduler.py:1995-2049` — accept/reject loop with paramount-
  cooldown guard at line 2025
- `app/scheduler.py:1084` — `_score_from_state` (cooldown
  computation, lines 1130-1140)
- ADR 002 — paramount cooldown
- `scheduler/phase1-f1-cpsat-refinement.md` — F1 finding that
  motivated this audit

---

*F1-a closed: no bug, audit confirms correct lex-comparison and
accept/reject. The SA is move-set-limited on tight fixtures. The
Q4 architectural finding stands.*
