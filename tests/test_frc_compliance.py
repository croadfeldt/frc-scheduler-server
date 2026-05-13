# SPDX-License-Identifier: GPL-3.0-or-later
# FRC Match Scheduler
# Copyright (C) 2025 FRC Match Scheduler Contributors

"""Tests for app/frc_compliance.py — FRC §10.5.2 audit trail."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.frc_compliance import (
    FRC_DEFAULTS, DEFAULT_COOLDOWN, AUDIT_SCHEMA_VERSION,
    compute_deviations, is_competition_approved, build_audit_record,
)


def test_frc_defaults_are_competition_approved():
    """An FRC-default settings dict yields zero deviations."""
    print("── test_frc_defaults_are_competition_approved ──")
    deviations = compute_deviations(dict(FRC_DEFAULTS))
    assert deviations == [], f"FRC defaults should be approved, got: {deviations}"
    assert is_competition_approved(dict(FRC_DEFAULTS))
    print(f"  FRC defaults pass with zero deviations  ✓")


def test_disabled_rb_post_pass_creates_deviation():
    print("── test_disabled_rb_post_pass_creates_deviation ──")
    settings = dict(FRC_DEFAULTS)
    settings['rb_post_pass'] = False
    deviations = compute_deviations(settings)
    assert len(deviations) == 1, f"expected 1 deviation, got {len(deviations)}: {deviations}"
    assert 'R/B' in deviations[0]
    assert not is_competition_approved(settings)
    print(f"  '{deviations[0]}' detected  ✓")


def test_disabled_station_post_pass_creates_deviation():
    print("── test_disabled_station_post_pass_creates_deviation ──")
    settings = dict(FRC_DEFAULTS)
    settings['station_post_pass'] = False
    deviations = compute_deviations(settings)
    assert len(deviations) == 1
    assert 'Station' in deviations[0]
    assert not is_competition_approved(settings)
    print(f"  '{deviations[0]}' detected  ✓")


def test_custom_weights_creates_deviation():
    print("── test_custom_weights_creates_deviation ──")
    settings = dict(FRC_DEFAULTS)
    settings['weights'] = {'partner': 5.0, 'opponent': 3.0}
    deviations = compute_deviations(settings)
    assert len(deviations) == 1
    assert 'weights' in deviations[0].lower()
    assert "{'partner': 5.0, 'opponent': 3.0}" in deviations[0]
    assert not is_competition_approved(settings)
    print(f"  '{deviations[0]}' detected  ✓")


def test_multiple_deviations_all_reported():
    print("── test_multiple_deviations_all_reported ──")
    settings = dict(FRC_DEFAULTS)
    settings['rb_post_pass'] = False
    settings['station_post_pass'] = False
    settings['weights'] = {'partner': 2.0}
    deviations = compute_deviations(settings)
    assert len(deviations) == 3, f"expected 3, got {len(deviations)}: {deviations}"
    assert not is_competition_approved(settings)
    print(f"  3 deviations detected  ✓")


def test_cooldown_is_audited_but_not_a_deviation():
    """Cooldown != project default should be in audit record but NOT in deviations list."""
    print("── test_cooldown_is_audited_but_not_a_deviation ──")
    audit = build_audit_record(
        settings_used=dict(FRC_DEFAULTS),
        cooldown_used=5,  # non-default
        iterations_used=500_000,
        preset_used='good',
    )
    assert audit['competition_approved'] is True, \
        "cooldown != project default should NOT unset competition_approved"
    assert audit['cooldown'] is not None, "cooldown record should be present"
    assert audit['cooldown']['value'] == 5
    # The audit-trail key is `project_default` (renamed from `frc_default` per
    # F1-e methodology decision — FRC §10.5.2 doesn't publish a value, so
    # "FRC default" was misleading; we record our project's default instead).
    assert audit['cooldown']['project_default'] == DEFAULT_COOLDOWN
    assert 'editable' in audit['cooldown']['note'].lower()
    assert audit['deviations'] == []
    print(f"  cooldown=5 audited (not a deviation)  ✓")


def test_default_cooldown_no_audit_record():
    """When cooldown == project default (2), audit record's cooldown field is None."""
    print("── test_default_cooldown_no_audit_record ──")
    audit = build_audit_record(
        settings_used=dict(FRC_DEFAULTS),
        cooldown_used=DEFAULT_COOLDOWN,  # project default (2 per F1-e)
        iterations_used=500_000,
    )
    assert audit['cooldown'] is None
    assert audit['competition_approved'] is True
    print(f"  cooldown={DEFAULT_COOLDOWN} (project default) leaves audit.cooldown=None  ✓")


def test_audit_record_shape():
    print("── test_audit_record_shape ──")
    audit = build_audit_record(
        settings_used=dict(FRC_DEFAULTS),
        cooldown_used=DEFAULT_COOLDOWN,
        iterations_used=2_000_000,
        preset_used='best',
    )
    expected_keys = {
        'schema_version', 'competition_approved', 'settings_used',
        'frc_defaults_at_time_of_generation', 'deviations', 'cooldown',
        'iterations_used', 'preset_used',
    }
    assert set(audit.keys()) == expected_keys, \
        f"audit shape mismatch: {set(audit.keys())} vs {expected_keys}"
    assert audit['schema_version'] == AUDIT_SCHEMA_VERSION
    assert audit['preset_used'] == 'best'
    assert audit['iterations_used'] == 2_000_000
    print(f"  audit shape valid  ✓")


def test_audit_record_contains_frc_defaults_snapshot():
    """The audit MUST include the FRC defaults snapshot at generation time
    so a future audit can compare even if FRC §10.5.2 changes."""
    print("── test_audit_record_contains_frc_defaults_snapshot ──")
    audit = build_audit_record(
        settings_used={'rb_post_pass': False, **dict(FRC_DEFAULTS)},
        cooldown_used=DEFAULT_COOLDOWN,
    )
    snapshot = audit['frc_defaults_at_time_of_generation']
    # snapshot should be a deep copy, not a reference
    assert snapshot == FRC_DEFAULTS, "snapshot should match current defaults"
    print(f"  FRC defaults snapshot captured  ✓")


def test_audit_settings_used_is_independent_copy():
    """settings_used should be a copy so caller's mutations don't bleed."""
    print("── test_audit_settings_used_is_independent_copy ──")
    settings = dict(FRC_DEFAULTS)
    audit = build_audit_record(settings_used=settings, cooldown_used=DEFAULT_COOLDOWN)
    settings['rb_post_pass'] = 'mutated'
    assert audit['settings_used']['rb_post_pass'] is True, \
        "audit should not be affected by caller's later mutations"
    print(f"  settings_used independence verified  ✓")


def test_deviations_text_human_readable():
    """Each deviation string should be a sentence a non-developer can read."""
    print("── test_deviations_text_human_readable ──")
    cases = [
        ({'rb_post_pass': False, **{k: v for k, v in FRC_DEFAULTS.items() if k != 'rb_post_pass'}},
         'R/B'),
        ({'station_post_pass': False, **{k: v for k, v in FRC_DEFAULTS.items() if k != 'station_post_pass'}},
         'Station'),
    ]
    for settings, expected_keyword in cases:
        deviations = compute_deviations(settings)
        assert len(deviations) >= 1
        msg = deviations[0]
        assert expected_keyword in msg
        # Check it has a "why this matters" component (mentions FRC criterion)
        assert 'FRC' in msg
        assert len(msg) > 30, f"too terse: {msg!r}"
        print(f"  '{expected_keyword}' deviation: {msg[:70]}...  ✓")


if __name__ == '__main__':
    test_frc_defaults_are_competition_approved()
    test_disabled_rb_post_pass_creates_deviation()
    test_disabled_station_post_pass_creates_deviation()
    test_custom_weights_creates_deviation()
    test_multiple_deviations_all_reported()
    test_cooldown_is_audited_but_not_a_deviation()
    test_default_cooldown_no_audit_record()
    test_audit_record_shape()
    test_audit_record_contains_frc_defaults_snapshot()
    test_audit_settings_used_is_independent_copy()
    test_deviations_text_human_readable()
    print("\nAll FRC compliance tests passed.")
