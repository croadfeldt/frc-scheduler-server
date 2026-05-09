# SPDX-License-Identifier: GPL-3.0-or-later
# FRC Match Scheduler
# Copyright (C) 2025 FRC Match Scheduler Contributors
"""FRC §10.5.2 compliance — single source of truth.

A schedule is "competition-approved" if and only if it was generated
using settings that match FRC §10.5.2 defaults. This module defines
the authoritative defaults and computes deviations from them.

Per user direction: cooldown (ideal_gap) is editable per FRC's "varies
by event size" guidance, but ANY deviation is recorded in the audit
trail. The competition-approved bit reflects whether the algorithm
used FRC's stated priorities; cooldown variations don't unset it.

Quality preset (iteration count) does NOT affect approval — it
controls how thoroughly we search, not which criteria we optimize.
A "fair" preset finds a possibly-worse schedule but optimizes for
the same FRC priorities.

What DOES unset competition-approved:
- Disabling rb_post_pass (Phase 1)
- Disabling station_post_pass (Phase 2)
- Custom partner/opponent/station weights (legacy weights parameter)
- Non-default surrogate handling

What's audited but doesn't unset:
- Cooldown != 3
- Iteration count (any value)
- Non-default quality preset
"""

from __future__ import annotations

from typing import Any

# ── FRC §10.5.2 defaults ──────────────────────────────────────────────────
# These are the algorithm-level settings that define a "competition-approved"
# schedule. Quality preset (iterations) is NOT included — it's about search
# thoroughness, not algorithm choice.

FRC_DEFAULTS: dict[str, Any] = {
    'rb_post_pass':       True,    # Phase 1 R/B balance post-pass
    'station_post_pass':  True,    # Phase 2 Sykes-style station balance
    'lex_score':          True,    # FRC §10.5.2 lex priority order (Phase 0a)
    'hard_cooldown':      True,    # Phase 0b — never accept cooldown-violating swap
    'targeted_moves':     True,    # Phase 0c — bias SA toward duplicate pairs
    'weights':            None,    # No custom weights (lex score is authoritative)
    'surrogate_handling': '3rd_match_as_surrogate',  # FRC standard
}

# Cooldown (ideal_gap) is FRC-editable but audited.
DEFAULT_COOLDOWN = 3

# Schema version for the audit JSON. Bump when settings_used shape changes.
AUDIT_SCHEMA_VERSION = 1


def compute_deviations(settings: dict[str, Any]) -> list[str]:
    """Return human-readable list of departures from FRC §10.5.2 defaults.

    Empty list means competition-approved. Any non-empty list means the
    schedule deviates from FRC's stated algorithm. Cooldown changes are
    NOT included — those are audited separately and don't unset approval.

    Args:
        settings: Dict of settings used to generate this schedule. Should
                  be a superset of FRC_DEFAULTS keys.

    Returns:
        List of strings like ["R/B post-pass disabled",
        "custom partner weight 5.0 (FRC default: lex tuple)"]
    """
    deviations = []

    if settings.get('rb_post_pass') is False:
        deviations.append(
            "R/B balance post-pass (Phase 1) disabled — "
            "FRC #5 (red/blue distribution) not optimized"
        )
    if settings.get('station_post_pass') is False:
        deviations.append(
            "Station balance post-pass (Phase 2) disabled — "
            "FRC #6 (driver station distribution) not optimized"
        )
    if settings.get('lex_score') is False:
        deviations.append(
            "Lex score disabled — FRC §10.5.2 priority order not enforced"
        )
    if settings.get('hard_cooldown') is False:
        deviations.append(
            "Hard cooldown filter disabled — FRC #1 cooldown not paramount"
        )
    if settings.get('targeted_moves') is False:
        deviations.append(
            "Targeted moves disabled — SA may be slower to converge"
        )

    weights = settings.get('weights')
    if weights is not None:
        deviations.append(
            f"Custom weights specified — FRC §10.5.2 lex tuple is "
            f"authoritative; weights only useful for non-FRC scenarios. "
            f"Weights: {weights}"
        )

    surrogate = settings.get('surrogate_handling')
    if surrogate is not None and surrogate != FRC_DEFAULTS['surrogate_handling']:
        deviations.append(
            f"Non-default surrogate handling: {surrogate!r} "
            f"(FRC default: {FRC_DEFAULTS['surrogate_handling']!r})"
        )

    return deviations


def is_competition_approved(settings: dict[str, Any]) -> bool:
    """True iff the schedule meets FRC §10.5.2 algorithm requirements."""
    return len(compute_deviations(settings)) == 0


def build_audit_record(settings_used: dict[str, Any],
                       cooldown_used: int = DEFAULT_COOLDOWN,
                       iterations_used: int | None = None,
                       preset_used: str | None = None) -> dict[str, Any]:
    """Build the per-schedule audit record stored in the DB.

    Args:
        settings_used: Algorithm settings (FRC-defaults compatible keys).
        cooldown_used: ideal_gap value passed to the scheduler.
        iterations_used: SA iteration count actually used.
        preset_used: Quality preset name if the request used one.

    Returns:
        Audit record JSON. Stored in AssignedSchedule.audit_trail.
    """
    deviations = compute_deviations(settings_used)
    cooldown_audit = None
    if cooldown_used != DEFAULT_COOLDOWN:
        cooldown_audit = {
            'value':       cooldown_used,
            'frc_default': DEFAULT_COOLDOWN,
            'note':        ("Cooldown editable per FRC's 'varies by event size' "
                            "guidance; not a deviation but recorded for audit"),
        }
    return {
        'schema_version':                  AUDIT_SCHEMA_VERSION,
        'competition_approved':            len(deviations) == 0,
        'settings_used':                   dict(settings_used),
        'frc_defaults_at_time_of_generation': dict(FRC_DEFAULTS),
        'deviations':                      deviations,
        'cooldown':                        cooldown_audit,
        'iterations_used':                 iterations_used,
        'preset_used':                     preset_used,
    }
