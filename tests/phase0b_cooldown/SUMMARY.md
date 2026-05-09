# Phase 0b: Hard Cooldown Filter

**Status:** Complete.

## What changed

Added `_swap_preserves_cooldown(state, matches, ...)` — a pre-filter for the SA move generator. Before applying a swap, the SA checks whether it would create new cooldown violations. If so, the swap is skipped without mutating state. Saves the cost of apply+score+revert on dead-end moves.

## Self-healing for construction-phase bugs

If the construction phase produces a schedule with cooldown violations (the 24×8 small-event bug we found earlier), the filter still permits swaps that *don't worsen* cooldown — including swaps that improve it. So the SA self-heals to cooldown_violations = 0 even when the construction phase outputs a violation.

The filter logic: `post_violations <= pre_violations`. Strict-improvement and equality both pass; only worsening is rejected.

## Performance impact

Measured on 2026mnst:
- SA=200K, no cooldown filter: 100s
- SA=200K, with cooldown filter: 22s

**~5x speedup** because random 2-swap proposals frequently violate cooldown (the move generator picks any two positions; cooldown-violating combinations are a substantial fraction). Skipping these before mutating state saves the apply+score+revert cycle.

## Same-output guarantee

The filter doesn't change the SA's optimization behavior because cooldown-violating swaps were always rejected at the lex-tuple compare stage anyway (worsening criterion #1 is never accepted under FRC paramount). The filter just rejects them earlier in the loop.
