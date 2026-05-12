# Phase 1 — F1-a audit: SA paramount-cooldown behavior

**Date:** 2026-05-12
**Status:** Audit complete. Diagnosis: SA's accept/reject logic is
**correct** — there is no bug. The cooldown-failure observation on
tight fixtures is **move-set reachability**, not lex-comparison
violation. Construction-quality is part of the same problem.

**Source:** `docs/workstreams/best-possible-schedule.md` Q4; F1 follow-up
captured in `phase1-f1-cpsat-refinement.md`.

---

## Why the audit existed

F1's findings showed the SA produced schedules with
`cooldown_violations=31` on 12×6×2, while CP-SAT produced
`cooldown_violations=0` on the same fixture. Two diagnoses were
possible:

1. **The SA's accept/reject correctly enforces paramount-cooldown,
   but the construction phase produces a starting state with
   violations the SA can't escape.** Architectural — fixed by
   replacing construction with CP-SAT.

2. **The SA's accept/reject has a bug** that lets it accept swaps
   worsening cooldown when other criteria improve, in violation of
   ADR 002. Code-level — fixed by patching the lex comparison.

The two have completely different implications. F1-a resolves which.

---

## What the audit covered

Read and traced four functions in `app/scheduler.py`:

- `_lex_compare` (line 1785) — pure-Python lexicographic compare
- `_swap_preserves_cooldown` (line 1728) — pre-apply cooldown filter
- `_sa_optimize` (line 1898) — main SA loop with accept/reject
- `_score_from_state` (line 1084) — produces the lex tuple

Then ran an instrumented experiment: 50,000 random swap attempts
starting from a construction-produced state on 12×6×2 with
`cooldown_violations=50`, tallying swap outcomes by category.

---

## Code audit findings

### `_lex_compare` is correct

Strict lexicographic compare, first differing element wins. Position
0 (cooldown_violations) dominates correctly. No bug.

### `_swap_preserves_cooldown` is locally correct

The filter at line 1728 computes pre/post violation counts for the
two affected teams (ta and tb only) and rejects if `post_v > pre_v`.

This is *locally* correct (a 2-swap only changes ta and tb's match
indices), but the docstring at line 1735-1736 is precise about this:
*"team_matches doesn't change so cooldown can't change"* for within-
match swaps. For cross-match swaps, only ta and tb's `team_matches`
entries change, so checking those two teams is sufficient. No bug.

### `_sa_optimize`'s accept/reject is correct

Two layers of cooldown protection:

1. **Pre-apply filter** (line 1989): rejects swaps that would worsen
   *any* team's cooldown count.
2. **Defense-in-depth** (line 2025): if the first differing tuple
   element is index 0 (cooldown) and the swap worsens it, always
   reject. (This shouldn't fire if layer 1 works — and the experiment
   confirms it never fires.)

The stochastic uphill acceptance at line 2032-2042 only fires when
all higher-priority criteria are equal (`higher_match`), AND the
worsening is not at index 0 (cooldown). The lex ordering is fully
respected.

**Conclusion: The SA's accept/reject is correctly implementing ADR
002's paramount-cooldown semantics.** No code-level bug.

---

## Experimental findings

50,000 random swap attempts from a 12×6×2 starting state with
`cooldown_violations=50`, with reject-then-revert on failures:

| Outcome | Count | % |
|---|---:|---:|
| invalid_swap (team duplicated in match) | 31,565 | 63.1% |
| rejected_by_cooldown_filter | 13,759 | 27.5% |
| cooldown_improved (post-filter, post-apply) | 17 | **0.034%** |
| cooldown_neutral (post-filter, post-apply) | 4,659 | 9.3% |
| cooldown_worsened (post-filter, post-apply) | 0 | 0% |

Key numbers:

- **Cooldown-improving swaps are vanishingly rare** in the random
  2-swap neighborhood from this starting state. 17 in 50K = ~1 per
  3,000 attempts.
- **Zero swaps slipped past the filter**. The filter is doing its
  job correctly.
- After 50K attempts, cooldown went from 50 → 33. Reducing the
  remaining 33 to 0 at the observed rate would require ~100K more
  successful improvements, or about **300 million random swap
  attempts**. At our default SA=2M iterations, we'd see ~70
  improvements. **The SA cannot reach cooldown=0 on this fixture
  in any reasonable budget.**

---

## Construction-phase quality on tight fixtures

A separate experiment to characterize what construction produces on
12×6×2 (without SA):

200 construction attempts, all with `n_sa_iterations=0`:

- 24 produced `ConstructionMalformedError` (12% rate, consistent
  with the F2 finding for this fixture)
- 176 produced well-formed schedules with the following
  cooldown_violations distribution:

| cd_viol | Count |
|---:|---:|
| 49 | 15 |
| 50 | 51 |
| 51 | 61 |
| 52 | 31 |
| 53 | 16 |
| 54 | 2 |

**Zero out of 200 attempts produced a schedule with cooldown=0.**
The distribution is tightly clustered at 49-54 — construction
isn't even trying to satisfy cooldown on this fixture; it's just
producing well-formed matches that happen to violate cooldown
massively.

The system architecture relies on the SA to "self-heal" cooldown
violations via the move set. The audit shows that doesn't work on
tight fixtures because the move-set neighborhood doesn't contain
enough cooldown-improving moves.

---

## Diagnosis

**The F1 observation was diagnosis #1: construction produces
unsalvageable starting states; SA's correct logic can't escape them
via the available move set.**

There is no SA bug. The lex compare is correct. The filter is
correct. ADR 002 is being honored: SA never accepts a cooldown-
worsening move. But:

1. **Construction never produces cooldown=0 on tight fixtures.**
2. **The SA's 2-swap neighborhood contains too few cooldown-
   improving moves** to drive 50 violations to 0 in reasonable time.

The combination renders the system effectively broken on tight
fixtures, despite each component being individually correct.

---

## What this means for Q4

The audit closes the F1 ambiguity. Q4's architectural answer is
**strongly supported** by the data:

- **For tight fixtures (where construction can't satisfy
  cooldown):** replace construction with CP-SAT, which finds
  cooldown=0 starting states. SA refines pairing from there.
- **For larger fixtures (where construction succeeds at cooldown):**
  keep the existing two-stage (greedy construction + SA
  refinement); CP-SAT may not terminate at this scale anyway.

The threshold for "tight" needs empirical mapping, but the F1
measurements already give a useful first estimate: fixtures where
the construction-cooldown-violation rate is high (≥1 per team) are
candidates for CP-SAT construction. Larger fixtures where
construction succeeds at cooldown can stay on greedy.

This also reframes F1-c (CP-SAT-as-construction prototype) as the
natural next step. The hypothesis to validate: CP-SAT finds a
cooldown=0 starting state on 12×6×2 (already proven during F1),
hand it to the SA, see whether the SA can drive `par_quad` down
toward optimum while preserving cooldown=0. If yes, the Q4
architectural answer is validated end-to-end.

---

## What this means for the lex tuple shape question (Q1)

The audit also has implications for Q1. The current lex tuple has
`cooldown_violations` at position 0 as paramount. That's structurally
correct per ADR 002. **But it means the SA's "best" output on tight
fixtures is fundamentally meaningless** — it's optimizing pairing
under a paramount cooldown that's been failed at construction.

The diagnostic schedules we've been comparing (par_quad=116 vs CP-
SAT's 192) are not comparable in the meaningful sense — one violates
paramount-cooldown and the other doesn't. Treating both as "schedules
with some quality" was misleading.

**Q1 needs to factor this in.** A revised lex tuple should still have
cooldown paramount (no change there), but the *eval methodology*
should treat schedules with `cooldown_violations > 0` as **invalid
output to be discarded**, not as data points to compare. The current
eval harness implicitly treats them as comparable, which inflates
SA's apparent quality on tight fixtures.

---

## Open follow-ups (updated from F1)

- **F1-a.** ✓ DONE — this document.
- **F1-b.** Warm-start CP-SAT with SA output for fixtures where
  CP-SAT and SA can both run. Still worth doing but lower priority
  than F1-c now.
- **F1-c.** Build CP-SAT-as-construction prototype: solve to
  feasibility with CP-SAT (cooldown=0), hand off to SA for pairing
  refinement, measure end-to-end quality. **Recommended next.**
- **F1-d.** ✓ DONE (Q5 caveat landed previous session).
- **F1-e.** (new) **Audit eval methodology**: confirm that schedules
  with `cooldown_violations > 0` are flagged as invalid in the
  diversity/composite reporting and not aggregated alongside valid
  ones. This affects all prior eval data on tight fixtures.

---

## Code references (no changes needed — code is correct)

- `app/scheduler.py:1785` — `_lex_compare` (correct)
- `app/scheduler.py:1728` — `_swap_preserves_cooldown` (correct)
- `app/scheduler.py:1898` — `_sa_optimize` (correct)
- `app/scheduler.py:2025` — defense-in-depth cooldown reject (correct)

---

*F1-a audit complete. No code changes. The SA is correctly
implementing paramount-cooldown semantics; the failure observed on
tight fixtures is a construction-vs-move-set mismatch, not a bug.
F1-c (CP-SAT-as-construction prototype) is the recommended next
step to validate the Q4 architectural answer end-to-end.*
