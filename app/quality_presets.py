# SPDX-License-Identifier: GPL-3.0-or-later
# FRC Match Scheduler
# Copyright (C) 2025 FRC Match Scheduler Contributors
"""Quality preset levels for the lex SA optimizer.

Maps user-friendly names to SA iteration counts. These are the
production knobs surfaced in the UI; backend can also accept explicit
iteration counts up to MAX_ITERATIONS.

Tuned per the iteration ceiling investigation (see
``docs/scheduler/ITERATION_CEILING.md``):

- Tight criterion (mean improvement < stdev at K) was NOT met within
  the tested range up to 5M. K* is documented as "> 5M, not found".
- Practical ceiling chosen at 5,000,000 — beyond that, single-trial
  wall-clock exceeds 3 minutes, impractical for interactive use.
- "Best" preset set to 2M rather than 5M because best-of-N at 2M
  with N=30 produces lex tuples comparable to the reference fixture
  (2026mnst MatchMaker output). 5M is reserved as "Maximum" for cases
  where additional compute is justified.

To revisit these levels (e.g., if compute budget changes or quality
expectations shift), see ``docs/scheduler/ITERATION_CEILING.md``
"Future work" section.
"""

# ── Preset levels ──────────────────────────────────────────────────────────
# Single source of truth. UI dropdown values, API validation, and the
# competition-approved-checkbox default all reference these.

QUALITY_PRESETS: dict[str, int] = {
    'fair':    50_000,      # Quick previews, ~2s per trial
    'good':    500_000,     # Default for interactive editing, ~20s per trial
    'best':    2_000_000,   # Production / state events, ~75s per trial
    'maximum': 5_000_000,   # Compute-budget-permitting, ~180s per trial
}

DEFAULT_PRESET = 'good'
COMPETITION_APPROVED_PRESET = 'best'  # FRC competition default

# Hard cap on the iterations field. Anything above this is rejected.
MAX_ITERATIONS = 5_000_000


def iterations_for_preset(name: str) -> int:
    """Resolve a preset name to its iteration count.

    Raises ValueError if the name isn't recognized."""
    if name not in QUALITY_PRESETS:
        raise ValueError(
            f"Unknown quality preset: {name!r}. "
            f"Valid options: {sorted(QUALITY_PRESETS.keys())}"
        )
    return QUALITY_PRESETS[name]


def preset_for_iterations(n: int) -> str | None:
    """Reverse lookup: which preset (if any) does this iteration count match?

    Returns None if n doesn't exactly match a preset (e.g., custom value).
    Used for displaying "this schedule was generated with the 'Best' preset"
    in the audit trail.
    """
    for name, count in QUALITY_PRESETS.items():
        if count == n:
            return name
    return None
