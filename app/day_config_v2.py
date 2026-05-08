"""V2 day_config — Pydantic models, validation, V1↔V2 migration.

This module is the server-side authority on V2 day_config shape. All
backend code that touches day_config goes through here:

* POST/PATCH endpoints (`main.py`) validate incoming day_configs
  against `DayConfigV2` and reject malformed input with 400.
* GET endpoints normalize stored day_configs to V2 shape on read,
  using `migrate_v1_to_v2()` for legacy rows.
* Importers (`pdf_dayplan.py`, `schedule_derive.py`,
  `_synthesize_day_config_from_tba`) emit V2 shape directly via
  the helper builders here.

See `docs/V2_SPEC.md` for the canonical model description. This
module's structure mirrors the spec section by section so a
spec-vs-code diff stays tractable.

The Pydantic models use `extra="allow"` deliberately: the editor's
side-channel state (the `autoPopulate`, `autoMaxCycles`, `autoAssign`
flags, `timeline_blocks`, `_frcPreservedDayDates`-derived fields)
piggybacks on day_config in some legacy paths and we want
forward-tolerance until those side channels get their own homes.
Validation focuses on the canonical V2 fields; unknown fields are
preserved through the round-trip but not validated.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

log = logging.getLogger(__name__)


# ── Constants ────────────────────────────────────────────────────────────────

# Block types per V2_SPEC §5. Tier number derived from V2_BLOCK_TYPES in
# the editor; mirrored here so server-side validation enforces nesting.
TIER_2_TYPES = ("practice", "qualification", "playoff")
TIER_3_TYPES = ("break", "awards", "alliance_selection", "ceremony")
ALL_BLOCK_TYPES = TIER_2_TYPES + TIER_3_TYPES

# Per V2_SPEC §5 — playoff format options. Kept loose here (str) to avoid
# duplicating the editor's V2_PLAYOFF_FORMATS list in two places. The
# editor enforces the exact set; the backend accepts any non-empty
# string and trusts the editor.
DEFAULT_CYCLE_TIME       = 9.0
DEFAULT_BREAK_BUFFER     = 5.0
DEFAULT_PLAYOFF_CT       = 11.0
DEFAULT_PRACTICE_CT      = 11.0
DEFAULT_PRACTICE_GUARAN  = 1
DEFAULT_PRACTICE_FILLER  = 99

HHMM_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_hhmm(v: str | None) -> str | None:
    """Pass through valid HH:MM, normalize empty, raise ValueError on bad."""
    if v is None or v == "":
        return None
    if not isinstance(v, str):
        raise ValueError(f"time must be a string, got {type(v).__name__}")
    s = v.strip()
    if s == "":
        return None
    if not HHMM_RE.match(s):
        raise ValueError(f"time must be HH:MM 24-hour zero-padded, got {s!r}")
    return s


def _validate_iso_date(v: str | None) -> str | None:
    """Pass through valid yyyy-mm-dd or empty, raise on malformed."""
    if v is None or v == "":
        return ""
    if not isinstance(v, str):
        raise ValueError(f"date must be a string, got {type(v).__name__}")
    s = v.strip()
    if s == "":
        return ""
    if not ISO_DATE_RE.match(s):
        raise ValueError(f"date must be yyyy-mm-dd, got {s!r}")
    return s


def _hhmm_to_min(s: str | None) -> int | None:
    if s is None or not isinstance(s, str) or not HHMM_RE.match(s.strip()):
        return None
    h, m = s.strip().split(":")
    return int(h) * 60 + int(m)


# ── Pydantic models ──────────────────────────────────────────────────────────

class CycleChangeV2(BaseModel):
    """Per V2_SPEC §7. afterMatch is 1-based and block-local.

    Semantics: the new cycleTime applies to the interval *after* match N.
    See V2_SPEC §7 for the worked example.
    """
    model_config = ConfigDict(extra="allow")

    afterMatch: int   = Field(..., ge=1, description="1-based match index, block-local")
    cycleTime:  float = Field(..., gt=0, description="cycle time in minutes")


class BlockV2(BaseModel):
    """Generic V2 block — fields are a union of all block types' shapes.

    Type-specific validation runs in `_validate_type_specific`. This
    union-style model is simpler than discriminated subclasses for our
    JSON storage path; see V2_SPEC §5 for the per-type field reference.
    """
    model_config = ConfigDict(extra="allow")

    type:  Literal["practice", "qualification", "playoff",
                   "break", "awards", "alliance_selection", "ceremony"]
    start: str
    end:   str
    label: str | None = None

    # tier-2 schedulable fields
    cycleTime:  float | None         = None
    changes:    list[CycleChangeV2]  = Field(default_factory=list)
    breaks:     list["BlockV2"]      = Field(default_factory=list)

    # practice-only
    guaranteed: int | None = None
    maxFiller:  int | None = None

    # playoff-only
    playoffFormat:    str | None = None
    playoffAlliances: int | None = None
    # Reserved fields per V2_SPEC §5.3 — populated when playoff scheduling lands.
    alliances: list[Any] = Field(default_factory=list)
    matches:   list[Any] = Field(default_factory=list)
    # Legacy alias readback per V2_SPEC §5.3.
    playoffTeams: int | None = None

    # break-only
    breakKind: Literal["lunch", "break", "other"] | None = None

    # ceremony-only
    ceremonyKind: Literal["opening", "closing"] | None = None

    @field_validator("start", "end")
    @classmethod
    def _check_time(cls, v: str) -> str:
        out = _validate_hhmm(v)
        if out is None:
            raise ValueError("start/end are required HH:MM strings")
        return out

    @model_validator(mode="after")
    def _validate_window_and_type(self) -> "BlockV2":
        # Window check: end strictly after start. Day-wrap not yet
        # supported (Q-04 in V2_ROADMAP) — enforce strict ordering.
        s = _hhmm_to_min(self.start)
        e = _hhmm_to_min(self.end)
        if s is None or e is None:
            raise ValueError("start/end must be HH:MM")
        if e <= s:
            raise ValueError(f"block end ({self.end}) must be strictly after start ({self.start})")

        # Type-specific validation. Keeping this in one place keeps the
        # cross-field rules readable; using discriminated subclasses
        # would scatter these checks across five classes.
        t = self.type
        if t == "playoff":
            # Tolerate legacy playoffTeams field; surface as
            # playoffAlliances if the canonical field is missing.
            if self.playoffAlliances is None and self.playoffTeams is not None:
                self.playoffAlliances = self.playoffTeams
            if self.playoffAlliances is None:
                self.playoffAlliances = 8  # editor default
            if not (2 <= self.playoffAlliances <= 16):
                raise ValueError(f"playoffAlliances must be in [2,16], got {self.playoffAlliances}")
            if self.cycleTime is None:
                self.cycleTime = DEFAULT_PLAYOFF_CT
            if self.playoffFormat is None or not str(self.playoffFormat).strip():
                self.playoffFormat = "double_elim"

        elif t == "practice":
            if self.cycleTime is None:
                self.cycleTime = DEFAULT_PRACTICE_CT
            if self.guaranteed is None:
                self.guaranteed = DEFAULT_PRACTICE_GUARAN
            elif self.guaranteed < 1:
                raise ValueError(f"practice.guaranteed must be ≥1, got {self.guaranteed}")
            if self.maxFiller is None:
                self.maxFiller = DEFAULT_PRACTICE_FILLER
            elif self.maxFiller < 0:
                raise ValueError(f"practice.maxFiller must be ≥0, got {self.maxFiller}")

        elif t == "qualification":
            if self.cycleTime is None:
                self.cycleTime = DEFAULT_CYCLE_TIME

        elif t == "break":
            if self.breakKind is None:
                self.breakKind = "break"
            if self.breakKind == "other" and not (self.label and self.label.strip()):
                # Per V2_SPEC §5.4 — kind=other requires a label.
                # Auto-populate with a generic label rather than rejecting,
                # to keep imports tolerant of partial data. Strict mode
                # could be added behind a flag if tightening is needed.
                self.label = "Other"

        elif t == "ceremony":
            if self.ceremonyKind is None:
                self.ceremonyKind = "opening"

        # Tier rule: nested children must be strictly higher tier.
        # Tier-3 (leaves) cannot have children at all.
        parent_tier = 2 if t in TIER_2_TYPES else 3
        for child in self.breaks:
            child_tier = 2 if child.type in TIER_2_TYPES else 3
            if child_tier <= parent_tier:
                raise ValueError(
                    f"tier rule: {t}(tier {parent_tier}) cannot contain "
                    f"{child.type}(tier {child_tier}); children must be strictly higher tier"
                )

        return self


# Forward reference resolution for self-referential `breaks: list[BlockV2]`.
BlockV2.model_rebuild()


class DayV2(BaseModel):
    """Per V2_SPEC §3."""
    model_config = ConfigDict(extra="allow")

    label:         str = "Day"
    labelOverride: str | None = None
    date:          str = ""
    blocks:        list[BlockV2] = Field(default_factory=list)

    @field_validator("date")
    @classmethod
    def _check_date(cls, v: str | None) -> str:
        return _validate_iso_date(v) or ""


class DayConfigV2(BaseModel):
    """Top-level V2 day_config per V2_SPEC §2."""
    model_config = ConfigDict(extra="allow")

    dayConfigVersion: Literal[2]   = 2
    cycleTime:        float        = DEFAULT_CYCLE_TIME
    breakBuffer:      float        = DEFAULT_BREAK_BUFFER
    days:             list[DayV2]  = Field(default_factory=list)


# ── Validation entry points ──────────────────────────────────────────────────

def validate_v2(dc: dict) -> DayConfigV2:
    """Validate a dict against the V2 schema. Raises ValidationError on bad shape."""
    return DayConfigV2.model_validate(dc)


def is_v2_shape(dc: Any) -> bool:
    """Cheap pre-check: does this look like V2? Doesn't validate fully."""
    return (
        isinstance(dc, dict)
        and dc.get("dayConfigVersion") == 2
    )


# ── V1 → V2 migration (server-side) ──────────────────────────────────────────

# Mirrors `migrateLegacyDayConfig()` in static/index.html. Kept
# intentionally close to the JS implementation so behavior matches
# what the editor produced from a V1 day_config — diffing the two is
# how we'd catch drift.

_LUNCH_RE     = re.compile(r"\blunch\b", re.I)
_BREAK_RE     = re.compile(r"\bbreak\b|\brecess\b|\bintermission\b", re.I)
_AWARDS_RE    = re.compile(r"\bawards?\b", re.I)
_ALLIANCE_RE  = re.compile(r"\balliance\s*selection\b|\balliance\s*pick", re.I)
_CEREMONY_RE  = re.compile(r"\bceremony\b|\bopening\b|\bclosing\b", re.I)


def _detect_break_kind(name: str | None) -> str:
    """Heuristic: name-based detection of break kind.

    Returns one of "lunch" / "break" / "other". The "other" bucket
    means the user has typed a custom name we don't recognize; the
    editor's UI surfaces this as "Other" with a name field.
    """
    if not name or not isinstance(name, str):
        return "break"
    if _LUNCH_RE.search(name):
        return "lunch"
    if _BREAK_RE.search(name):
        return "break"
    return "other"


def _detect_subtype(name: str | None) -> str:
    """Classify a V1 break entry by its name.

    Returns a V2 block type. The classifier is conservative — it only
    upgrades to a tier-3 specialty type (awards/ceremony/alliance) when
    the name contains an unambiguous keyword. Otherwise stays as
    "break". This matters for V1 data that predates subtype
    preservation: those names are our only signal.

    Match order matters: "Awards ceremony" → awards (because "awards"
    is the more specific noun; the trailing "ceremony" is generic).
    "Opening ceremony" → ceremony (no specifier wins). The order
    reflects what the editor's display would call these too.
    """
    if not name or not isinstance(name, str):
        return "break"
    if _AWARDS_RE.search(name):
        return "awards"
    if _ALLIANCE_RE.search(name):
        return "alliance_selection"
    if _CEREMONY_RE.search(name):
        return "ceremony"
    return "break"


def _detect_ceremony_kind(name: str | None, position_hint: str | None = None) -> str:
    """Classify ceremony by name keywords; fall back to position hint.

    `position_hint`: "first" or "last" (or None) — used when the name
    is generic ("Ceremony") to guess opening vs closing from where in
    the day the block sits.
    """
    if name:
        n = name.lower()
        if "open" in n:
            return "opening"
        if "clos" in n:
            return "closing"
    if position_hint == "last":
        return "closing"
    return "opening"


def migrate_v1_to_v2(dc: Any) -> dict | None:
    """V1 day_config dict → V2 day_config dict.

    Idempotent: if the input is already V2 (has dayConfigVersion=2),
    returns it unchanged. None and non-dict inputs return None.

    Lossiness: V1 break entries don't carry subtype info, so we
    classify them by name keyword (`_detect_subtype`). Unrecognized
    names land as "break". Per V2_SPEC §12, V1→V2 is not a lossless
    migration — type info that V1 didn't have is reconstructed
    heuristically.
    """
    if dc is None or not isinstance(dc, dict):
        return None

    if is_v2_shape(dc):
        return dc

    out: dict[str, Any] = {
        "dayConfigVersion": 2,
        "cycleTime":   dc.get("cycleTime", DEFAULT_CYCLE_TIME),
        "breakBuffer": dc.get("breakBuffer", DEFAULT_BREAK_BUFFER),
        "days": [],
    }

    # Pass through editor side-channel fields. These aren't part of
    # V2 spec but live on day_config as host-state piggybacks; we
    # preserve them on round-trip rather than dropping silently.
    for sidekey in ("autoPopulate", "autoMaxCycles", "autoAssign", "timeline_blocks"):
        if sidekey in dc:
            out[sidekey] = dc[sidekey]

    # Practice day → day with one practice block. V1 separates practice
    # day from regular days; V2 makes it a regular day with a
    # practice-typed block. This is the right unification per
    # V2_SPEC Q-02 (resolved tentatively).
    pd = dc.get("practiceDay")
    if isinstance(pd, dict) and pd.get("enabled") and pd.get("start") and pd.get("end"):
        practice_block: dict[str, Any] = {
            "type":      "practice",
            "start":     pd["start"],
            "end":       pd["end"],
            "cycleTime": pd.get("ct") or pd.get("cycleTime") or out["cycleTime"],
            "guaranteed": pd.get("guaranteed", DEFAULT_PRACTICE_GUARAN),
            "maxFiller":  pd.get("filler",     DEFAULT_PRACTICE_FILLER) if "filler" in pd else pd.get("maxFiller", DEFAULT_PRACTICE_FILLER),
            "breaks":    [],
            "changes":   [],
        }
        # Practice cycle changes
        pcc = pd.get("cycleChanges") or []
        if isinstance(pcc, list):
            for cc in pcc:
                if isinstance(cc, dict) and not cc.get("isStart"):
                    am = cc.get("afterMatch")
                    t  = cc.get("time") or cc.get("cycleTime")
                    if am and t:
                        try:
                            practice_block["changes"].append({
                                "afterMatch": int(am),
                                "cycleTime":  float(t),
                            })
                        except (ValueError, TypeError):
                            pass
                elif isinstance(cc, dict) and cc.get("isStart"):
                    t = cc.get("time") or cc.get("cycleTime")
                    if t:
                        try:
                            practice_block["cycleTime"] = float(t)
                        except (ValueError, TypeError):
                            pass

        # Practice breaks
        for b in pd.get("breaks") or []:
            if isinstance(b, dict) and b.get("start") and b.get("end"):
                practice_block["breaks"].append(_v1_break_to_v2(b))

        out["days"].append({
            "label": pd.get("label") or "Practice",
            "date":  pd.get("date") or "",
            "blocks": [practice_block],
        })

    # Regular days → day with one qualification block (containing the
    # day's breaks as nested children). Sibling-level tier-3 blocks
    # (awards / alliance_selection / ceremony) get hoisted to the day
    # level by name detection — this is the fix for "alliance selection
    # absorbed into qualification" per the recurring V1→V2 bug.
    global_match_offset = 0
    for i, day in enumerate(dc.get("days") or []):
        if not isinstance(day, dict):
            continue

        # Build the qual block. cycleTime + changes attach to it.
        qual: dict[str, Any] = {
            "type":      "qualification",
            "start":     day.get("start") or "",
            "end":       day.get("end") or "",
            "cycleTime": day.get("cycleTime") or out["cycleTime"],
            "breaks":    [],
            "changes":   [],
        }

        # isStart cycleChange resets base cycleTime; afterMatch goes to changes.
        for cc in day.get("cycleChanges") or []:
            if not isinstance(cc, dict):
                continue
            if cc.get("isStart"):
                t = cc.get("time") or cc.get("cycleTime")
                if t:
                    try:
                        qual["cycleTime"] = float(t)
                    except (ValueError, TypeError):
                        pass
            else:
                am = cc.get("afterMatch")
                t  = cc.get("time") or cc.get("cycleTime")
                if am and t:
                    try:
                        qual["changes"].append({
                            "afterMatch": int(am),
                            "cycleTime":  float(t),
                        })
                    except (ValueError, TypeError):
                        pass

        # Break list classification. V1 break entries become V2 blocks;
        # those with subtype hints (awards/alliance/ceremony) hoist to
        # day-level, generic breaks nest inside qual. This is the fix
        # for the "alliance selection absorbed into qualification" bug.
        v1_breaks = day.get("breaks") or []
        day_blocks: list[dict] = [qual]
        ceremony_count = sum(1 for b in v1_breaks if _detect_subtype((b or {}).get("name")) == "ceremony")
        ceremony_seen  = 0
        for b in v1_breaks:
            if not isinstance(b, dict):
                continue
            if not (b.get("start") and b.get("end")):
                continue
            subtype = _detect_subtype(b.get("name"))

            if subtype == "break":
                # Stays nested inside qual.
                qual["breaks"].append(_v1_break_to_v2(b))
            else:
                # Hoist to day level. Position hint for ceremony kind:
                # if it's the first ceremony in the day, opening; if
                # the last, closing.
                ceremony_seen += 1
                position_hint = "first" if ceremony_seen == 1 else (
                    "last" if ceremony_seen == ceremony_count else None
                )
                day_blocks.append(_v1_break_to_v2(b, subtype=subtype,
                                                 position_hint=position_hint))

        # Playoff blocks live on a side-channel field in V1
        # (`playoffBlocks` array, indexed by day_index). Hoist them
        # into the day's block list at the right position.
        for pb in dc.get("playoffBlocks") or []:
            if not isinstance(pb, dict):
                continue
            if pb.get("dayIndex") != i:
                continue
            if not (pb.get("start") and pb.get("end")):
                continue
            day_blocks.append({
                "type":             "playoff",
                "start":            pb["start"],
                "end":              pb["end"],
                "playoffFormat":    pb.get("format") or "double_elim",
                "playoffAlliances": pb.get("alliances") or pb.get("teams") or 8,
                "cycleTime":        pb.get("cycleTime") or DEFAULT_PLAYOFF_CT,
                "changes":          [],
                "breaks":           [],
                "alliances":        [],
                "matches":          [],
            })

        # Sort by start time so the day reads chronologically.
        day_blocks.sort(key=lambda b: _hhmm_to_min(b.get("start", "")) or 0)

        out["days"].append({
            "label": day.get("label") or f"Day {i + 1}",
            "date":  day.get("date") or "",
            "blocks": day_blocks,
        })

        # Track running match count for any future cross-day
        # afterMatch translation. (V1 doesn't actually use this on
        # input; included for symmetry with the editor's downgrader.)
        dur = (_hhmm_to_min(day.get("end") or "") or 0) - (_hhmm_to_min(day.get("start") or "") or 0)
        ct  = qual["cycleTime"] or out["cycleTime"] or DEFAULT_CYCLE_TIME
        global_match_offset += max(0, int(dur / ct)) if ct > 0 else 0

    return out


def _v1_break_to_v2(
    b: dict,
    *,
    subtype: str | None = None,
    position_hint: str | None = None,
) -> dict:
    """Convert one V1 break entry to a V2 block.

    `subtype` overrides the auto-detected type. When None (the default,
    used for nested children of qual), the result is always a generic
    `break` block. For hoisted siblings, the caller passes the detected
    subtype explicitly.
    """
    name = b.get("name") or "Break"
    if subtype is None:
        subtype = "break"

    out: dict[str, Any] = {
        "type":  subtype,
        "start": b.get("start"),
        "end":   b.get("end"),
        "label": name,
    }
    if subtype == "break":
        out["breakKind"] = _detect_break_kind(name)
    elif subtype == "ceremony":
        out["ceremonyKind"] = _detect_ceremony_kind(name, position_hint)
    return out


# ── V2 → V1 downgrade (server-side) ──────────────────────────────────────────

def downgrade_v2_to_v1(dc: dict) -> dict:
    """Produce a V1-shape day_config from a V2 input.

    Used during the transition window when a client expects V1 output.
    Once phase 3 (editor V2-only) ships and all clients are V2, this
    function becomes obsolete. Per V2_ROADMAP phase 5, it's kept until
    we confirm zero callers in metrics.

    Lossiness: per-block cycle times collapse to a single per-day
    cycle time (the qual block's). Type info for tier-3 blocks
    (subtype, ceremonyKind) becomes break.name. Playoff blocks move
    to the side-channel `playoffBlocks` array.

    This is the inverse of `migrate_v1_to_v2()` modulo the lossy
    parts. Round-trip V2→V1→V2 is NOT identity; round-trip V1→V2→V1
    is identity for V1-representable inputs.
    """
    if not isinstance(dc, dict):
        return {}
    if not is_v2_shape(dc):
        # Already V1 (or some unknown shape) — pass through.
        return dc

    out: dict[str, Any] = {
        "cycleTime":   dc.get("cycleTime", DEFAULT_CYCLE_TIME),
        "breakBuffer": dc.get("breakBuffer", DEFAULT_BREAK_BUFFER),
        "days":        [],
        "playoffBlocks": [],
    }

    # Pass through side-channel fields.
    for sidekey in ("autoPopulate", "autoMaxCycles", "autoAssign", "timeline_blocks"):
        if sidekey in dc:
            out[sidekey] = dc[sidekey]

    practice_day_emitted = False
    global_match_offset = 0

    for di, day in enumerate(dc.get("days") or []):
        blocks = day.get("blocks") or []
        practices = [b for b in blocks if b.get("type") == "practice"]
        quals     = [b for b in blocks if b.get("type") == "qualification"]
        playoffs  = [b for b in blocks if b.get("type") == "playoff"]
        tier3s    = [b for b in blocks if b.get("type") in TIER_3_TYPES]

        # If this V2 day has only a practice block and we haven't
        # emitted V1's practiceDay yet, emit it as practiceDay rather
        # than a regular day.
        if practices and not quals and not practice_day_emitted:
            p = practices[0]
            out["practiceDay"] = _practice_block_to_v1(p, day)
            practice_day_emitted = True
            continue

        # Otherwise this is a regular V1 day. Use the qual block (or
        # the first practice if no qual) as the day's window.
        primary = quals[0] if quals else (practices[0] if practices else None)
        if primary is None:
            # Day with only tier-3 / playoff blocks. V1 needs a
            # window; synthesize from min/max of all blocks.
            starts = [_hhmm_to_min(b.get("start") or "") for b in blocks]
            ends   = [_hhmm_to_min(b.get("end")   or "") for b in blocks]
            starts = [s for s in starts if s is not None]
            ends   = [e for e in ends   if e is not None]
            if not starts or not ends:
                continue
            day_start = _min_to_hhmm(min(starts))
            day_end   = _min_to_hhmm(max(ends))
            day_ct    = out["cycleTime"]
        else:
            day_start = primary.get("start") or ""
            day_end   = primary.get("end") or ""
            day_ct    = primary.get("cycleTime") or out["cycleTime"]

        # Flatten breaks: nested + hoisted tier-3 → V1 breaks list.
        v1_breaks: list[dict] = []
        if primary:
            for nb in primary.get("breaks") or []:
                v1_breaks.append(_v2_block_to_v1_break(nb))
        for t3 in tier3s:
            v1_breaks.append(_v2_block_to_v1_break(t3))
        v1_breaks.sort(key=lambda b: _hhmm_to_min(b.get("start") or "") or 0)

        # Cycle changes from the primary block — translate block-local
        # afterMatch to global. V1's scheduler sees the global indices.
        v1_cc: list[dict] = []
        if primary and primary.get("cycleTime"):
            # Don't emit isStart for the day's primary cycleTime —
            # that's already captured by the day-level field. But
            # if the primary's cycleTime differs from the day-config
            # cycleTime, we'd need an isStart. V1's day field is
            # called `cycleTime` (set at top-level day, not per-block);
            # we encode any deviation as an isStart cc.
            if abs(float(primary.get("cycleTime")) - float(out["cycleTime"])) > 0.001:
                v1_cc.append({
                    "isStart": True,
                    "time":    float(primary.get("cycleTime")),
                })
        if primary:
            for cc in primary.get("changes") or []:
                if not isinstance(cc, dict):
                    continue
                am = cc.get("afterMatch")
                t  = cc.get("cycleTime")
                if am and t:
                    try:
                        v1_cc.append({
                            "isStart":    False,
                            "afterMatch": int(am) + global_match_offset,
                            "time":       float(t),
                        })
                    except (ValueError, TypeError):
                        pass

        v1_day: dict[str, Any] = {
            "start":        day_start,
            "end":          day_end,
            "cycleTime":    day_ct,
            "breaks":       v1_breaks,
            "cycleChanges": v1_cc,
            "earlyEnd":     None,
            "label":        day.get("labelOverride") or day.get("label") or f"Day {di + 1}",
            "date":         day.get("date") or "",
        }
        out["days"].append(v1_day)

        # Hoist playoff blocks to the side-channel.
        for pb in playoffs:
            out["playoffBlocks"].append({
                "dayIndex":   len(out["days"]) - 1,
                "start":      pb.get("start"),
                "end":        pb.get("end"),
                "format":     pb.get("playoffFormat") or "double_elim",
                "alliances":  pb.get("playoffAlliances") or pb.get("playoffTeams") or 8,
                "cycleTime":  pb.get("cycleTime") or DEFAULT_PLAYOFF_CT,
            })

        # Update running match count for next day's afterMatch translation.
        s_min = _hhmm_to_min(day_start)
        e_min = _hhmm_to_min(day_end)
        if s_min is not None and e_min is not None and day_ct and day_ct > 0:
            global_match_offset += max(0, int((e_min - s_min) / day_ct))

    if not practice_day_emitted:
        # V1 always carries a practiceDay slot, even if disabled.
        out["practiceDay"] = {"enabled": False, "start": "", "end": "", "ct": out["cycleTime"], "guaranteed": 1}

    return out


def _min_to_hhmm(m: int | None) -> str:
    if m is None:
        return ""
    h, mm = divmod(int(m) % (24 * 60), 60)
    return f"{h:02d}:{mm:02d}"


def _practice_block_to_v1(p: dict, day: dict) -> dict:
    """Practice block → V1 practiceDay shape."""
    cc_list = p.get("changes") or []
    v1_cc: list[dict] = []
    if p.get("cycleTime"):
        v1_cc.append({"isStart": True, "time": float(p["cycleTime"])})
    for cc in cc_list:
        if isinstance(cc, dict):
            am = cc.get("afterMatch")
            t  = cc.get("cycleTime")
            if am and t:
                try:
                    v1_cc.append({"isStart": False, "afterMatch": int(am), "time": float(t)})
                except (ValueError, TypeError):
                    pass
    return {
        "enabled":      True,
        "start":        p.get("start", ""),
        "end":          p.get("end", ""),
        "ct":           p.get("cycleTime", DEFAULT_PRACTICE_CT),
        "guaranteed":   p.get("guaranteed", DEFAULT_PRACTICE_GUARAN),
        "filler":       p.get("maxFiller", DEFAULT_PRACTICE_FILLER),
        "breaks":       [_v2_block_to_v1_break(b) for b in p.get("breaks") or []],
        "cycleChanges": v1_cc,
        "earlyEnd":     None,
        "date":         day.get("date") or "",
        "label":        day.get("label") or "Practice",
    }


def _v2_block_to_v1_break(b: dict) -> dict:
    """V2 tier-3 block → V1 break entry."""
    name = b.get("label")
    if not name:
        # Synthesize a label from type / kind.
        t = b.get("type", "break")
        if t == "ceremony":
            kind = b.get("ceremonyKind", "opening")
            name = f"{kind.capitalize()} ceremony"
        elif t == "alliance_selection":
            name = "Alliance selection"
        elif t == "awards":
            name = "Awards"
        else:
            kind = b.get("breakKind", "break")
            name = "Lunch" if kind == "lunch" else "Break"
    return {
        "name":  name,
        "start": b.get("start"),
        "end":   b.get("end"),
    }


# ── Schedule materialization (server-side reference) ─────────────────────────
#
# Per V2_SPEC §10. The editor has its own materializer (in
# static/index.html); the server-side version exists for backend
# match generation paths that need to produce timed entries from a
# V2 day_config + an abstract match list.
#
# For phase 1, this is a stub — match generation in scheduler.py is
# abstract (slot-based) and doesn't know about times yet. When match
# generation gets time-awareness, this is the function it calls.
# For now we keep the contract documented.

def materialize_v2(dc: dict, abstract_matches: list[dict] | None = None) -> dict:
    """Materialize V2 day_config + abstract matches → timed entries.

    NOT YET IMPLEMENTED — phase 1 reserves the function. The editor's
    JS materializer is the current authoritative implementation; this
    Python version becomes authoritative when backend match generation
    needs time-aware output (e.g. for match-time emission to TBA Sync,
    Nexus posting, or PDF generation directly from server data).

    Per V2_SPEC §10, output shape:
        {
            "days": [
                {
                    "label": str,
                    "date":  str,
                    "entries": [
                        {"type": "match", "num": int, "red": [int]*3, "blue": [int]*3,
                         "startMin": int, "endMin": int},
                        {"type": "break", "name": str, "start": int, "end": int,
                         "subtype": str, "breakKind": str|None, "ceremonyKind": str|None},
                        {"type": "cycle-change", "start": int, "time": float},
                    ],
                },
                ...
            ],
            "playoffBlocks": [...],
        }
    """
    raise NotImplementedError(
        "materialize_v2 is reserved for phase 1+ backend match-time generation. "
        "Today the editor materializes client-side."
    )


# ── Convenience: normalize on read ────────────────────────────────────────────

def normalize_to_v2(dc: Any) -> dict | None:
    """Best-effort: return a V2 dict given any input. None for non-dicts."""
    if dc is None:
        return None
    if not isinstance(dc, dict):
        return None
    if is_v2_shape(dc):
        return dc
    try:
        return migrate_v1_to_v2(dc)
    except (KeyError, TypeError, ValueError) as exc:
        log.warning("V1→V2 migration failed: %s; returning as-is", exc)
        return dc
