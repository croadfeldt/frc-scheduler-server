"""Round-trip and validation tests for app.day_config_v2.

Run:  python -m pytest tests/test_day_config_v2.py -v
Or:   python tests/test_day_config_v2.py     (manual mode, no pytest)

These tests pin the V2 model behavior. Any change that breaks them
needs an explicit decision (update the test or change the spec).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Make the app package importable when running this file directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.day_config_v2 import (  # noqa: E402
    DayConfigV2, validate_v2, is_v2_shape,
    migrate_v1_to_v2, downgrade_v2_to_v1, normalize_to_v2,
    _detect_subtype, _detect_break_kind, _detect_ceremony_kind,
)
from pydantic import ValidationError  # noqa: E402


# ── Fixtures ─────────────────────────────────────────────────────────────────

# A typical V1 day_config from a saved schedule. Shape mirrors what
# the editor's collectDayConfig() produces for a single-day event with
# a practice day, breaks, and cycle changes.
V1_TYPICAL = {
    "cycleTime":   9,
    "breakBuffer": 5,
    "days": [
        {
            "start": "08:30", "end": "21:30",
            "cycleTime": 9,
            "earlyEnd":  None,
            "breaks": [
                {"name": "Opening ceremony",  "start": "08:30", "end": "09:00"},
                {"name": "Lunch",              "start": "12:00", "end": "13:00"},
                {"name": "Alliance selection", "start": "17:00", "end": "17:30"},
                {"name": "Break",              "start": "20:30", "end": "21:00"},
                {"name": "Closing ceremony",   "start": "21:00", "end": "21:30"},
            ],
            "cycleChanges": [
                {"isStart": False, "afterMatch": 30, "time": 8},
            ],
            "label": "Day 1", "date": "2026-04-04",
        },
        {
            "start": "09:00", "end": "17:00",
            "cycleTime": 9,
            "earlyEnd":  None,
            "breaks":   [{"name": "Lunch", "start": "12:00", "end": "13:00"}],
            "cycleChanges": [],
            "label": "Day 2", "date": "2026-04-05",
        },
    ],
    "practiceDay": {"enabled": False, "start": "", "end": "", "ct": 11, "guaranteed": 1},
    "playoffBlocks": [
        {"dayIndex": 0, "start": "17:30", "end": "20:30", "format": "double_elim", "alliances": 8},
    ],
}


# A V2 day_config — the canonical shape we want to converge on.
V2_CANONICAL = {
    "dayConfigVersion": 2,
    "cycleTime":   9,
    "breakBuffer": 5,
    "days": [
        {
            "label": "Day 1", "date": "2026-04-04",
            "blocks": [
                {"type": "ceremony", "start": "08:30", "end": "09:00",
                 "label": "Opening ceremony", "ceremonyKind": "opening"},
                {"type": "qualification", "start": "09:00", "end": "17:00",
                 "cycleTime": 9,
                 "changes": [{"afterMatch": 30, "cycleTime": 8}],
                 "breaks": [
                     {"type": "break", "start": "12:00", "end": "13:00",
                      "label": "Lunch", "breakKind": "lunch"},
                 ]},
                {"type": "alliance_selection", "start": "17:00", "end": "17:30",
                 "label": "Alliance selection"},
                {"type": "playoff", "start": "17:30", "end": "20:30",
                 "playoffFormat": "double_elim", "playoffAlliances": 8,
                 "cycleTime": 11, "changes": [], "breaks": [],
                 "alliances": [], "matches": []},
                {"type": "break", "start": "20:30", "end": "21:00",
                 "label": "Break", "breakKind": "break"},
                {"type": "ceremony", "start": "21:00", "end": "21:30",
                 "label": "Closing ceremony", "ceremonyKind": "closing"},
            ],
        },
        {
            "label": "Day 2", "date": "2026-04-05",
            "blocks": [
                {"type": "qualification", "start": "09:00", "end": "17:00",
                 "cycleTime": 9, "changes": [],
                 "breaks": [
                     {"type": "break", "start": "12:00", "end": "13:00",
                      "label": "Lunch", "breakKind": "lunch"},
                 ]},
            ],
        },
    ],
}


# ── Tests ────────────────────────────────────────────────────────────────────

class TestValidation:
    def test_canonical_v2_validates(self):
        result = validate_v2(V2_CANONICAL)
        assert isinstance(result, DayConfigV2)
        assert result.dayConfigVersion == 2
        assert len(result.days) == 2

    def test_rejects_bad_time_format(self):
        bad = json.loads(json.dumps(V2_CANONICAL))
        bad["days"][0]["blocks"][0]["start"] = "8:30"  # missing zero pad
        try:
            validate_v2(bad)
            assert False, "should have raised"
        except ValidationError as e:
            assert "HH:MM" in str(e)

    def test_rejects_end_before_start(self):
        bad = json.loads(json.dumps(V2_CANONICAL))
        bad["days"][0]["blocks"][0]["end"] = "08:00"  # before start 08:30
        try:
            validate_v2(bad)
            assert False, "should have raised"
        except ValidationError as e:
            assert "end" in str(e) and "after start" in str(e)

    def test_rejects_tier_violation(self):
        bad = json.loads(json.dumps(V2_CANONICAL))
        # Try to nest a qualification (tier 2) inside another qualification (tier 2)
        qual = bad["days"][0]["blocks"][1]
        qual["breaks"].append({
            "type": "qualification", "start": "10:00", "end": "11:00",
            "cycleTime": 9, "changes": [], "breaks": [],
        })
        try:
            validate_v2(bad)
            assert False, "should have raised"
        except ValidationError as e:
            assert "tier" in str(e).lower()

    def test_rejects_invalid_alliance_count(self):
        bad = json.loads(json.dumps(V2_CANONICAL))
        for blk in bad["days"][0]["blocks"]:
            if blk["type"] == "playoff":
                blk["playoffAlliances"] = 20  # max is 16
                break
        try:
            validate_v2(bad)
            assert False, "should have raised"
        except ValidationError as e:
            assert "playoffAlliances" in str(e)

    def test_accepts_legacy_playoffTeams_alias(self):
        legacy_alias = json.loads(json.dumps(V2_CANONICAL))
        for blk in legacy_alias["days"][0]["blocks"]:
            if blk["type"] == "playoff":
                blk["playoffTeams"] = blk.pop("playoffAlliances")
                break
        result = validate_v2(legacy_alias)
        # Should be normalized to playoffAlliances
        playoff = next(b for b in result.days[0].blocks if b.type == "playoff")
        assert playoff.playoffAlliances == 8


class TestMigrationV1ToV2:
    def test_idempotent_on_v2(self):
        out = migrate_v1_to_v2(V2_CANONICAL)
        assert out is V2_CANONICAL  # passes through unchanged

    def test_typical_v1_migrates(self):
        v2 = migrate_v1_to_v2(V1_TYPICAL)
        assert v2 is not None
        assert v2["dayConfigVersion"] == 2

        # Sanity: Day 1 should have multiple blocks (ceremony hoisted, qual, alliance hoisted, etc.)
        d0 = v2["days"][0]
        types = [b["type"] for b in d0["blocks"]]
        assert "qualification" in types
        assert "ceremony" in types  # Opening + Closing both detected
        assert "alliance_selection" in types
        # Two ceremony blocks (opening + closing)
        assert types.count("ceremony") == 2

    def test_v1_alliance_selection_hoisted_not_absorbed(self):
        """The original bug: 'alliance selection absorbed into qualification'."""
        v2 = migrate_v1_to_v2(V1_TYPICAL)
        d0 = v2["days"][0]
        # Alliance selection should be a top-level block, not nested in qual
        assert any(b["type"] == "alliance_selection" for b in d0["blocks"]), \
            "alliance_selection should be hoisted to day level"
        # And NOT inside the qual block's nested children
        qual = next(b for b in d0["blocks"] if b["type"] == "qualification")
        assert not any(b["type"] == "alliance_selection" for b in qual["breaks"]), \
            "alliance_selection should NOT be nested in qualification"

    def test_lunch_stays_nested_in_qual(self):
        """Generic breaks (lunch, break) stay nested inside qual."""
        v2 = migrate_v1_to_v2(V1_TYPICAL)
        d0 = v2["days"][0]
        qual = next(b for b in d0["blocks"] if b["type"] == "qualification")
        # Lunch (break with breakKind=lunch) should be nested
        assert any(b["type"] == "break" and b.get("breakKind") == "lunch"
                   for b in qual["breaks"])

    def test_v1_playoff_block_hoisted(self):
        """V1 playoffBlocks side-channel → day-level playoff block."""
        v2 = migrate_v1_to_v2(V1_TYPICAL)
        d0 = v2["days"][0]
        playoffs = [b for b in d0["blocks"] if b["type"] == "playoff"]
        assert len(playoffs) == 1
        assert playoffs[0]["playoffAlliances"] == 8
        assert playoffs[0]["playoffFormat"] == "double_elim"

    def test_cycle_change_preserved(self):
        v2 = migrate_v1_to_v2(V1_TYPICAL)
        qual = next(b for b in v2["days"][0]["blocks"] if b["type"] == "qualification")
        assert len(qual["changes"]) == 1
        assert qual["changes"][0]["afterMatch"] == 30
        assert qual["changes"][0]["cycleTime"] == 8

    def test_migrated_v2_validates(self):
        """End-to-end: V1 migrates to a shape that passes V2 validation."""
        v2 = migrate_v1_to_v2(V1_TYPICAL)
        validate_v2(v2)  # Should not raise.

    def test_handles_practice_day(self):
        v1 = json.loads(json.dumps(V1_TYPICAL))
        v1["practiceDay"] = {
            "enabled": True, "start": "12:00", "end": "17:00", "ct": 11,
            "guaranteed": 3, "filler": 5,
            "breaks": [], "cycleChanges": [],
        }
        v2 = migrate_v1_to_v2(v1)
        # Practice day becomes its own V2 day with a practice block.
        practice_days = [d for d in v2["days"]
                         if any(b["type"] == "practice" for b in d["blocks"])]
        assert len(practice_days) == 1
        practice = practice_days[0]["blocks"][0]
        assert practice["start"] == "12:00"
        assert practice["guaranteed"] == 3


class TestDowngradeV2ToV1:
    def test_idempotent_on_v1(self):
        out = downgrade_v2_to_v1(V1_TYPICAL)
        # V1 input passes through (no version=2 marker triggers no migration)
        assert out is V1_TYPICAL

    def test_canonical_v2_downgrades(self):
        v1 = downgrade_v2_to_v1(V2_CANONICAL)
        assert "days" in v1
        assert "playoffBlocks" in v1
        assert len(v1["days"]) == 2
        # Playoff hoisted to side-channel
        assert len(v1["playoffBlocks"]) == 1

    def test_round_trip_v1_to_v2_to_v1(self):
        """Round-trip V1 → V2 → V1 should recover the original (modulo lossless representation)."""
        v2  = migrate_v1_to_v2(V1_TYPICAL)
        v1b = downgrade_v2_to_v1(v2)
        # The recovered V1 should have the same number of days,
        # day windows, and playoff blocks.
        assert len(v1b["days"]) == len(V1_TYPICAL["days"])
        assert v1b["days"][0]["start"] == V1_TYPICAL["days"][0]["start"]
        assert v1b["days"][0]["end"] == V1_TYPICAL["days"][0]["end"]
        assert len(v1b["playoffBlocks"]) == len(V1_TYPICAL["playoffBlocks"])
        # Break count preserved (sum of nested + sibling = original V1's flat list)
        recovered_breaks = v1b["days"][0]["breaks"]
        # Original had 5 entries; some now hoist to playoff side-channel for V2
        # but the playoff's original location was in V1 breaks? No — V1 keeps
        # playoff in playoffBlocks side-channel. So all 5 break entries remain.
        assert len(recovered_breaks) == 5


class TestImporterEmits:
    """Verify the V2 emitters in importers produce valid V2 day_configs."""

    def test_schedule_derive_emits_v2(self):
        """schedule_derive.derive_parameters() emits V2."""
        from app import schedule_derive
        matches = [
            {"match_num": 1, "time": "08:30", "red": [1, 2, 3], "blue": [4, 5, 6]},
            {"match_num": 2, "time": "08:38", "red": [7, 8, 9], "blue": [10, 11, 12]},
            {"match_num": 3, "time": "08:46", "red": [1, 4, 7], "blue": [2, 5, 8]},
            {"match_num": 4, "time": "13:00", "red": [3, 6, 9], "blue": [10, 11, 12]},
        ]
        result = schedule_derive.derive_parameters(matches)
        dc = result["day_config"]
        assert dc["dayConfigVersion"] == 2
        # Should validate against V2 spec
        validate_v2(dc)
        # Single day with one qualification block
        assert len(dc["days"]) == 1
        types = [b["type"] for b in dc["days"][0]["blocks"]]
        assert types == ["qualification"]
        # Lunch break detected from the gap → nested in qual as break with breakKind=lunch
        qual = dc["days"][0]["blocks"][0]
        assert any(b.get("type") == "break" and b.get("breakKind") == "lunch"
                   for b in qual.get("breaks", []))

    def test_pdf_dayplan_v2_emit(self):
        """pdf_dayplan.to_v2_day_config() emits V2 with hoisting."""
        from app import pdf_dayplan
        dayplan = {
            "event_dates": {"start": "2026-04-04", "end": "2026-04-04"},
            "blocks": [
                {"kind": "practice",  "day_index": 0, "start": "12:00", "end": "17:00", "label": "Practice", "details": ""},
                {"kind": "ceremony",  "day_index": 1, "start": "08:30", "end": "09:00", "label": "Opening ceremony"},
                {"kind": "qual",      "day_index": 1, "start": "09:00", "end": "17:00", "label": "Qualification"},
                {"kind": "lunch",     "day_index": 1, "start": "12:00", "end": "13:00", "label": "Lunch"},
                {"kind": "playoff",   "day_index": 1, "start": "17:30", "end": "20:30", "label": "Playoffs"},
                {"kind": "ceremony",  "day_index": 1, "start": "21:00", "end": "21:30", "label": "Closing ceremony"},
            ],
        }
        v2 = pdf_dayplan.to_v2_day_config(dayplan)
        assert v2["dayConfigVersion"] == 2
        validate_v2(v2)
        # Two days: practice (day 0) + qual day (day 1)
        assert len(v2["days"]) == 2

        practice_day = v2["days"][0]
        assert any(b["type"] == "practice" for b in practice_day["blocks"])

        qual_day = v2["days"][1]
        types = [b["type"] for b in qual_day["blocks"]]
        # Hoisted: opening ceremony, qual, playoff, closing ceremony
        assert "ceremony" in types
        assert types.count("ceremony") == 2
        assert "qualification" in types
        assert "playoff" in types

        # Nested: lunch inside qual
        qual = next(b for b in qual_day["blocks"] if b["type"] == "qualification")
        assert any(nb["type"] == "break" and nb.get("breakKind") == "lunch"
                   for nb in qual.get("breaks", []))


class TestNormalizeToV2:
    def test_v2_passes_through(self):
        out = normalize_to_v2(V2_CANONICAL)
        assert out["dayConfigVersion"] == 2

    def test_v1_migrates(self):
        out = normalize_to_v2(V1_TYPICAL)
        assert out["dayConfigVersion"] == 2

    def test_none_returns_none(self):
        assert normalize_to_v2(None) is None

    def test_non_dict_returns_none(self):
        assert normalize_to_v2("garbage") is None
        assert normalize_to_v2(42) is None


class TestDetectors:
    def test_subtype_alliance(self):
        assert _detect_subtype("Alliance selection") == "alliance_selection"
        assert _detect_subtype("Alliance pick") == "alliance_selection"

    def test_subtype_awards(self):
        # "Awards ceremony" → awards because the awards keyword is
        # more specific than the generic "ceremony" suffix. This
        # mirrors how operators describe these in practice.
        assert _detect_subtype("Awards ceremony") == "awards"
        assert _detect_subtype("Awards") == "awards"

    def test_subtype_ceremony(self):
        assert _detect_subtype("Opening ceremony") == "ceremony"
        assert _detect_subtype("Closing ceremony") == "ceremony"

    def test_subtype_break(self):
        assert _detect_subtype("Lunch") == "break"
        assert _detect_subtype("Coffee break") == "break"
        assert _detect_subtype("") == "break"

    def test_break_kind_lunch(self):
        assert _detect_break_kind("Lunch") == "lunch"
        assert _detect_break_kind("Lunch break") == "lunch"

    def test_break_kind_break(self):
        assert _detect_break_kind("Break") == "break"

    def test_ceremony_kind_opening(self):
        assert _detect_ceremony_kind("Opening ceremony") == "opening"
        assert _detect_ceremony_kind("Generic", "first") == "opening"

    def test_ceremony_kind_closing(self):
        assert _detect_ceremony_kind("Closing ceremony") == "closing"
        assert _detect_ceremony_kind("Generic", "last") == "closing"


# ── Manual runner (no pytest required) ───────────────────────────────────────

if __name__ == "__main__":
    import inspect

    failures = []
    test_classes = [TestValidation, TestMigrationV1ToV2, TestDowngradeV2ToV1,
                    TestImporterEmits, TestNormalizeToV2, TestDetectors]

    for cls in test_classes:
        instance = cls()
        for name, method in inspect.getmembers(instance, predicate=inspect.ismethod):
            if not name.startswith("test_"):
                continue
            try:
                method()
                print(f"  PASS  {cls.__name__}.{name}")
            except (AssertionError, ValidationError, Exception) as e:
                failures.append(f"{cls.__name__}.{name}: {e}")
                print(f"  FAIL  {cls.__name__}.{name}: {e}")

    print()
    print(f"{'=' * 60}")
    if failures:
        print(f"{len(failures)} failure(s):")
        for f in failures:
            print(f"  • {f}")
        sys.exit(1)
    else:
        print(f"All tests passed.")
