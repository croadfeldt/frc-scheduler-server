"""Smoke-test the migration script logic without an actual DB.

Bypasses SQLAlchemy by directly exercising the per-row migration
logic that the script delegates to. Verifies:
  - V2 rows are correctly classified as already-V2 and skipped
  - V1 rows are migrated to V2
  - Idempotency: running on the migrated output is a no-op
  - Edge cases: None, non-dict, malformed
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.day_config_v2 import migrate_v1_to_v2, is_v2_shape


def classify(dc):
    """Mirror the script's _classify function."""
    if dc is None:
        return "null"
    if not isinstance(dc, dict):
        return "other"
    v = dc.get("dayConfigVersion")
    if v == 2:
        return "v2"
    if v is None or v == 1:
        return "v1"
    return "other"


def simulate_migration(rows):
    """Mirror the script's per-row decision logic, return counts."""
    would_write = 0
    skipped     = 0
    errors      = 0
    output      = []
    for dc in rows:
        if dc is None or not isinstance(dc, dict):
            skipped += 1
            output.append(dc)
            continue
        if is_v2_shape(dc):
            skipped += 1
            output.append(dc)
            continue
        try:
            new_dc = migrate_v1_to_v2(dc)
        except Exception:
            errors += 1
            output.append(dc)
            continue
        if new_dc is None or new_dc is dc or not isinstance(new_dc, dict):
            skipped += 1
            output.append(dc)
            continue
        if not is_v2_shape(new_dc):
            errors += 1
            output.append(dc)
            continue
        would_write += 1
        output.append(new_dc)
    return would_write, skipped, errors, output


# ── Fixtures ─────────────────────────────────────────────────────────────────

V1_ROW = {
    "cycleTime": 9, "breakBuffer": 5,
    "days": [{
        "start": "08:30", "end": "21:30", "cycleTime": 9,
        "breaks": [
            {"name": "Lunch",              "start": "12:00", "end": "13:00"},
            {"name": "Alliance selection", "start": "17:00", "end": "17:30"},
        ],
        "cycleChanges": [], "earlyEnd": None,
    }],
    "practiceDay": {"enabled": False, "start": "", "end": "", "ct": 11, "guaranteed": 1},
    "playoffBlocks": [{"dayIndex": 0, "start": "17:30", "end": "20:30", "format": "double_elim", "alliances": 8}],
}

V2_ROW = {
    "dayConfigVersion": 2, "cycleTime": 9, "breakBuffer": 5,
    "days": [{
        "label": "Day 1", "date": "",
        "blocks": [{"type": "qualification", "start": "09:00", "end": "17:00",
                    "cycleTime": 9, "changes": [], "breaks": []}],
    }],
}


# ── Tests ────────────────────────────────────────────────────────────────────

def test_v1_row_migrates():
    ww, sk, er, _ = simulate_migration([V1_ROW])
    assert (ww, sk, er) == (1, 0, 0), f"got ({ww}, {sk}, {er})"


def test_v2_row_skipped():
    ww, sk, er, _ = simulate_migration([V2_ROW])
    assert (ww, sk, er) == (0, 1, 0), f"got ({ww}, {sk}, {er})"


def test_null_skipped():
    ww, sk, er, _ = simulate_migration([None])
    assert (ww, sk, er) == (0, 1, 0), f"got ({ww}, {sk}, {er})"


def test_non_dict_skipped():
    ww, sk, er, _ = simulate_migration(["garbage", 42, [1, 2, 3]])
    assert (ww, sk, er) == (0, 3, 0), f"got ({ww}, {sk}, {er})"


def test_idempotent_after_migration():
    """Running migrate-then-migrate should produce no further writes."""
    ww1, sk1, er1, output = simulate_migration([V1_ROW])
    assert ww1 == 1
    ww2, sk2, er2, _ = simulate_migration(output)
    assert ww2 == 0, f"second run wrote {ww2} (expected 0)"
    assert sk2 == 1, f"second run skipped {sk2} (expected 1)"


def test_mixed_batch():
    """Realistic case: some V1, some V2, some null."""
    rows = [V1_ROW, V2_ROW, None, V1_ROW, V2_ROW]
    ww, sk, er, _ = simulate_migration(rows)
    assert (ww, sk, er) == (2, 3, 0), f"got ({ww}, {sk}, {er})"


def test_classify():
    assert classify(None) == "null"
    assert classify("garbage") == "other"
    assert classify(V2_ROW) == "v2"
    assert classify(V1_ROW) == "v1"
    assert classify({"dayConfigVersion": 99}) == "other"


if __name__ == "__main__":
    import inspect
    failures = []
    fns = [(name, fn) for name, fn in globals().items() if name.startswith("test_") and callable(fn)]
    for name, fn in fns:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception as e:
            failures.append(f"{name}: {e}")
            print(f"  FAIL  {name}: {e}")
    print()
    if failures:
        print(f"{len(failures)} failure(s)")
        sys.exit(1)
    print(f"All {len(fns)} migration smoke tests passed.")
