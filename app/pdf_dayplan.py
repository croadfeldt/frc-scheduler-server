"""Extract event-day timeline (start/end/lunch/practice/playoff blocks)
from a published event-program PDF.

This is a sibling to pdf_extract.py (which handles match-list PDFs). The two
target structurally different documents:

  - Match-list PDF: a table of matches, one row per match with team numbers
  - Day-plan PDF:   prose phases with start/end times (this module)

Some events publish both as separate documents (MSHSL, regional state events).
Others publish only one or the other. The PDF import endpoint in main.py
auto-detects which kind it received and routes accordingly.

Output contract (returned from extract_dayplan()):

    {
      "format_detected":  str,         # human description ("MSHSL state ...")
      "confidence":       "high"|"medium"|"low",
      "event_dates":      {"start": "YYYY-MM-DD"|null, "end": ...|null},
      "blocks":           [Block, ...],
      "raw_phases":       [{label, time_text}, ...],   # verbatim PDF lines
      "notes":            str,
    }

    Block = {
      "kind":      "practice"|"qual"|"lunch"|"break"|"ceremony"|"playoff",
      "day_index": int,                     # 0-indexed across event days
      "start":     "HH:MM"|null,
      "end":       "HH:MM"|null,
      "label":     str,                     # "Lunch Break", "Playoffs Begin", etc.
      "details":   str,                     # free text from the PDF
    }

Adapter `to_legacy_day_config()` produces the dict shape the existing
day_config UI consumes. It maps:
  - blocks of kind "practice"            → practiceDay   (one block expected)
  - blocks of kind "qual"                → days[]        (merged, lunch as a break)
  - blocks of kind "lunch"               → days[].breaks (merged into qual day)
  - blocks of kind "ceremony"|"playoff"  → timeline_blocks (informational; not
                                          used by the scheduler, but rendered
                                          on /view as labeled time ranges)
  - blocks of kind "break"               → days[].breaks (any non-meal break)

The auto-cap feature: if a playoff block is present and overlaps the end of
the qual day, the qual day's `end` is capped at the playoff block's `start`.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


# Heuristic: if the extracted text contains these phrases without a match
# table, it's almost certainly a day-plan, not a match list. Used by the
# auto-detection in main.py before deciding which extraction flow to run.
DAYPLAN_KEYWORDS = (
    "qualification rounds", "practice matches", "alliance selection",
    "playoffs begin", "lunch break", "drivers' meeting", "drivers meeting",
    "pit opens", "pits open", "opening ceremon", "awards ceremon",
)


def looks_like_dayplan(text: str) -> bool:
    """Heuristic: does this look like an event-day program?

    Looks for phase keywords. Returns True if the text reads like an
    itinerary rather than a match list.
    """
    low = text.lower()
    hits = sum(1 for kw in DAYPLAN_KEYWORDS if kw in low)
    return hits >= 3


# Vision-or-text agnostic prompt. The model gets the extracted text (or
# image, for the vision strategy) plus this system prompt and produces JSON.
SYSTEM_PROMPT = """You are a JSON extraction tool for FRC event day-plan documents.

You will be given the contents of an event-day program/itinerary PDF for a robotics tournament. Extract the timeline as strict JSON matching this schema (your entire reply must be valid JSON, with no other text):

{
  "format_detected": "<brief description, e.g. 'MSHSL state tournament 2-day program'>",
  "confidence": "<high|medium|low>",
  "event_dates": {
    "start": "<YYYY-MM-DD, or empty string if no date>",
    "end":   "<YYYY-MM-DD, or empty string>"
  },
  "blocks": [
    {
      "kind":      "<practice|qual|lunch|break|ceremony|playoff>",
      "day_index": <0-indexed event day; 0 = first day teams attend, regardless of whether matches happen that day>,
      "start":     "<HH:MM in 24-hour format, or empty string>",
      "end":       "<HH:MM in 24-hour format, or empty string if open-ended>",
      "label":     "<short human label exactly as written in the PDF>",
      "details":   "<free-text descriptors from the PDF: 'cycle time 10 minutes', '6 matches', etc.>"
    }
  ],
  "raw_phases": [
    {"label": "<verbatim phase name>", "time_text": "<verbatim time string>"}
  ],
  "notes": "<concerns or ambiguities, or empty string>"
}

Rules:

1. Block kinds (use these exact strings):
   - "practice"  — practice matches before quals start
   - "qual"      — qualification rounds (the main scheduled matches)
   - "lunch"     — lunch break specifically
   - "break"     — any other reserved break (pit close, connection time, etc.)
   - "ceremony"  — opening ceremony, alliance selection, awards, mascot parade
   - "playoff"   — playoffs / elimination rounds (just the time range; we don't model the bracket here)

2. Multi-segment qual days: if quals run morning AND afternoon with lunch between, emit THREE blocks: one qual block for the morning window, one lunch block, one qual block for the afternoon window. Keep them in chronological order.

3. Times: convert all to 24-hour HH:MM. "8:30 AM" → "08:30". "1:30 PM" → "13:30". If a phase has only a start time and no end ("4:00 PM Playoffs Begin"), set end to null.

4. day_index counts ALL days teams attend (Friday + Saturday = days 0 and 1), not just match days. If the document only covers one day, that day is day_index 0.

5. Skip purely informational sections (sponsor blurbs, award descriptions, footnotes). Do not put them in `blocks`.

6. The `details` field captures what makes a block specific: "6 matches, 10-minute cycles", "Concession stand open", "Dunwoody award judging on-site". Empty string if no details.

7. Output JSON ONLY. No prose before or after. No markdown fences."""


def _build_user_prompt(text: str) -> str:
    """Assemble the user message wrapping the extracted PDF text."""
    return (
        "Below is the text content of an event-day program PDF for an FRC tournament. "
        "Extract the day-plan timeline as JSON per the schema.\n\n"
        "=== PDF CONTENT ===\n"
        f"{text}\n"
        "=== END PDF CONTENT ===\n\n"
        "Return the JSON object now."
    )


async def extract_dayplan(text: str) -> dict[str, Any] | None:
    """Send extracted PDF text to the LLM and parse the response.

    Returns None if the LLM is not configured. Raises on extraction
    failures (timeout, network error, malformed response).

    Uses the consolidated llm_client._post() so timeout, error handling,
    and JSON-tolerant parsing are unified across all LLM call sites.

    Passes DAYPLAN_SCHEMA via guided_json so vLLM enforces output shape
    at decode time. Without this, smaller models (7B class) tend to
    drift mid-output, repeat themselves, or trail off — producing JSON
    that's syntactically broken and unrecoverable downstream.
    """
    from app import llm_client
    if not llm_client.is_configured():
        return None

    return await llm_client._post(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": _build_user_prompt(text)},
        ],
        # Day plans typically contain 5-10 blocks. Output is small, but
        # the `details` field can carry verbose descriptors and we've
        # seen the model hit the cap mid-output (parse error around
        # char ~4285 maps to ~1100-1300 tokens). Give meaningful
        # headroom so the model can finish and close the structure.
        max_tokens=4000,
        json_schema=llm_client.DAYPLAN_SCHEMA,
    )


# ── Adapter to existing day_config schema ────────────────────────────────────

def _hhmm_to_min(hhmm: str | None) -> int | None:
    """'13:30' → 810. None or blank → None."""
    if not hhmm:
        return None
    try:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def to_legacy_day_config(extracted: dict[str, Any], *,
                          default_cycle_time: float = 8.0,
                          default_break_buffer: float = 5.0) -> dict[str, Any]:
    """Convert the rich block-list output into today's day_config shape.

    Returns a dict matching what static/index.html's collectDayConfig()
    produces — that's what the scheduler consumes today. The caller can
    apply this directly to the form fields.

    Mapping rules:
      - "practice" blocks       → practiceDay (first block wins; warn if 2+)
      - "qual" blocks            → days[<day_index>] (merged per day)
      - "lunch"/"break" blocks   → days[<day_index>].breaks
      - "ceremony"/"playoff"     → timeline_blocks (informational; rendered
                                   in /view but not used by the scheduler)

    Auto-cap rule: if a playoff block exists on the same day_index as a qual
    day, AND the qual day's end is later than (or equal to) the playoff
    block's start, the qual day's end is capped at the playoff start. This
    prevents the scheduler from placing quals into the playoff window.
    """
    blocks = extracted.get("blocks") or []
    if not isinstance(blocks, list):
        blocks = []

    # Group by day_index for the qual aggregation pass
    by_day: dict[int, list[dict]] = {}
    practice_block: dict | None = None
    timeline_blocks: list[dict] = []   # ceremony + playoff (informational)

    for b in blocks:
        if not isinstance(b, dict):
            continue
        kind = (b.get("kind") or "").lower().strip()
        di = b.get("day_index")
        if not isinstance(di, int):
            di = 0

        if kind == "practice":
            # Take the first practice block; if multiple exist, the rest
            # become informational (we only model one practice window today).
            if practice_block is None:
                practice_block = b
            else:
                timeline_blocks.append({
                    "kind":      "practice_extra",
                    "day_index": di,
                    "start":     b.get("start"),
                    "end":       b.get("end"),
                    "label":     b.get("label", "Additional practice"),
                    "details":   b.get("details", ""),
                })
        elif kind in ("qual", "lunch", "break"):
            by_day.setdefault(di, []).append(b)
        elif kind in ("ceremony", "playoff"):
            timeline_blocks.append({
                "kind":      kind,
                "day_index": di,
                "start":     b.get("start"),
                "end":       b.get("end"),
                "label":     b.get("label", kind.title()),
                "details":   b.get("details", ""),
            })
        # Unknown kinds: ignored silently. The LLM may emit unforeseen kinds
        # we add later; better to drop than crash.

    # Build practiceDay payload
    if practice_block:
        details = (practice_block.get("details") or "").lower()
        # Try to pull a cycle time hint out of details ("10-minute cycles", "11min")
        ct_practice = None
        for token in details.replace("-", " ").split():
            if token.endswith("minute") or token.endswith("minutes") or token.endswith("min"):
                # Look at the token before
                pass
        # Simpler: regex for "<number> minute"
        import re as _re
        m = _re.search(r"(\d+(?:\.\d+)?)\s*[-]?\s*minute", details)
        if m:
            try:
                ct_practice = float(m.group(1))
            except ValueError:
                ct_practice = None

        # Try to pull "N matches" out of details
        m = _re.search(r"(\d+)\s*match", details)
        practice_count = int(m.group(1)) if m else None

        practice_day = {
            "enabled":    True,
            "start":      practice_block.get("start") or "",
            "end":        practice_block.get("end") or "",
            "guaranteed": practice_count if practice_count else 1,
            "filler":     0 if practice_count else 99,
            "ct":         ct_practice if ct_practice else default_cycle_time + 2,
            "breaks":         [],
            "cycleChanges":   [],
            "earlyEnd":       None,
        }
    else:
        practice_day = None

    # Build qual days. Each entry is for a sequential day_index that has at
    # least one qual block. We index OUTPUT days from 0 = first qual day.
    # MSHSL: practice on day_index 0 (Friday), quals on day_index 1 (Saturday)
    # → output days[0] = Saturday's qual content.
    qual_day_indices = sorted(
        di for di, lst in by_day.items()
        if any((b.get("kind") or "").lower() == "qual" for b in lst)
    )

    days_out: list[dict] = []
    for di in qual_day_indices:
        day_blocks = sorted(
            by_day[di],
            key=lambda b: _hhmm_to_min(b.get("start")) or 0,
        )
        # Span = earliest qual start → latest qual end. Lunch and break
        # blocks become entries in `breaks`; the span never includes them
        # at the edges, only between qual segments.
        qual_blocks = [b for b in day_blocks if (b.get("kind") or "").lower() == "qual"]
        non_qual    = [b for b in day_blocks if (b.get("kind") or "").lower() in ("lunch", "break")]

        if not qual_blocks:
            continue

        day_start = qual_blocks[0].get("start") or ""
        day_end   = qual_blocks[-1].get("end")   or ""

        breaks_out = []
        for b in non_qual:
            s = b.get("start")
            e = b.get("end")
            if not s or not e:
                continue
            # Only include breaks that fall WITHIN the qual span (between
            # the first qual start and the last qual end)
            s_min = _hhmm_to_min(s)
            e_min = _hhmm_to_min(e)
            day_s_min = _hhmm_to_min(day_start)
            day_e_min = _hhmm_to_min(day_end)
            if (s_min is not None and day_s_min is not None and s_min < day_s_min):
                continue
            if (e_min is not None and day_e_min is not None and e_min > day_e_min):
                continue
            breaks_out.append({
                "name":  b.get("label") or ("Lunch" if (b.get("kind") or "").lower() == "lunch" else "Break"),
                "start": s,
                "end":   e,
            })

        # Auto-cap qual end at any playoff block on the same day_index
        playoff_blocks = [
            tb for tb in timeline_blocks
            if tb["kind"] == "playoff" and tb["day_index"] == di and tb.get("start")
        ]
        if playoff_blocks:
            earliest_playoff = min(
                _hhmm_to_min(tb["start"]) or 0 for tb in playoff_blocks
            )
            day_e_min = _hhmm_to_min(day_end)
            if day_e_min is not None and day_e_min > earliest_playoff:
                # Convert back to HH:MM
                h, m = divmod(earliest_playoff, 60)
                day_end = f"{h:02d}:{m:02d}"
                log.info(
                    "Capping day_index=%d qual end to %s (playoff starts then)",
                    di, day_end,
                )

        days_out.append({
            "start":        day_start,
            "end":          day_end,
            "earlyEnd":     None,
            "cycleChanges": [],
            "breaks":       breaks_out,
        })

    if not days_out:
        # No qual day extracted — emit one empty day so the form has somewhere
        # to render. Caller should warn the user.
        days_out.append({
            "start": "", "end": "", "earlyEnd": None,
            "cycleChanges": [], "breaks": [],
        })

    return {
        "cycleTime":       default_cycle_time,
        "breakBuffer":     default_break_buffer,
        "numDays":         len(days_out),
        "practiceDay":     practice_day,
        "cycleChanges":    [],
        "days":            days_out,
        # Informational blocks (ceremony, playoff). Stored on day_config so
        # the /view page can render them as labeled time ranges. Scheduler
        # ignores them entirely.
        "timeline_blocks": timeline_blocks,
        # Auto-flags: when populated from PDF, default behaviour is to let
        # the scheduler recompute MPT and regenerate.
        "autoPopulate":    True,
        "autoMaxCycles":   True,
        "autoAssign":      False,
    }
