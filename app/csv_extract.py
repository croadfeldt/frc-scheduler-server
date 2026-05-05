"""Parse schedule CSV files into match lists.

Mirrors the layout produced by the in-browser CSV exporter, plus
accepts the FMS-style XLSX layout transcribed to CSV (Description
column with embedded match number) for compatibility with workflows
that export FMS XLSX and convert.

Two header layouts are recognised:

  Flat (preferred — what we export):
    Match,Time,Type,Blue 1,Blue 2,Blue 3,Red 1,Red 2,Red 3
    1,08:30,Qualification,2052,2169,2220,2239,2472,2480

  FMS (XLSX-equivalent):
    Time,Description,Blue 1,Blue 2,Blue 3,Red 1,Red 2,Red 3
    08:30,Qualification 1,2052,2169,2220,2239,2472,2480

Surrogate notation isn't preserved by either format — flagged false on
import. Other columns past the recognised set are ignored. Detection
is by header row content (case-insensitive); rows above the header
(title, subtitle, MPT) are silently skipped.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from typing import Any

log = logging.getLogger(__name__)

_MATCH_NUM_RE = re.compile(r"(\d+)")


def _coerce_team(value: Any) -> int | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        n = int(s)
        return n if n > 0 else None
    except (ValueError, TypeError):
        return None


def _normalize_header(cell: str) -> str:
    return (cell or "").strip().lower()


def parse_csv(content: bytes) -> dict[str, Any]:
    """Parse a schedule CSV into the same dict shape as xlsx_extract /
    PDF match-list pipelines.

    Returns:
        {
            "matches":         [...],
            "practice":        [...],   # rows whose Type/Description says "Practice"
            "format_detected": "Schedule CSV (N qual, M practice)",
            "notes":           "<warnings>",
            "page_count":      1,
        }

    Raises ValueError if no parseable header row is found or no
    matches are extracted.
    """
    # Decode permissively. UTF-8 is standard; UTF-8-sig handles Excel's
    # BOM-prefixed CSV; latin-1 is a fallback for legacy files.
    text: str | None = None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("Could not decode CSV as UTF-8 or Latin-1.")

    # Sniff the dialect — handles comma, tab, or semicolon separators.
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
    except csv.Error:
        # No clear delimiter — fall back to comma. csv.reader will still
        # work on a single-column file; we'll just fail to find columns
        # and surface a useful error below.
        dialect = csv.excel

    reader = csv.reader(io.StringIO(text), dialect=dialect)
    rows = list(reader)

    if not rows:
        raise ValueError("CSV is empty.")

    # Find the header row. Look for any of three layout signatures:
    #
    #   Flat (preferred — what we'll export going forward):
    #     Match, Time, Type, Blue 1-3, Red 1-3
    #
    #   Report (what downloadCSV() in static/index.html currently emits):
    #     Type, Match, Day, Time, Red 1-3, Blue 1-3, Surrogates
    #
    #   FMS (XLSX-equivalent layout transcribed to CSV):
    #     Time, Description (with embedded match number), Blue 1-3, Red 1-3
    #
    # Detection is cheap; we walk the first 20 rows looking for any
    # signature that matches.
    header_idx = -1
    layout: str | None = None
    for i, row in enumerate(rows[:20]):
        cells = [_normalize_header(c) for c in row]
        if not cells:
            continue
        has_blue = any(c.startswith("blue ") for c in cells)
        has_red  = any(c.startswith("red ")  for c in cells)
        if not (has_blue and has_red):
            continue
        if "match" in cells and "time" in cells and "type" in cells:
            header_idx = i
            # The "report" layout has a "day" column; "flat" doesn't.
            layout = "report" if "day" in cells else "flat"
            break
        if "time" in cells and "description" in cells:
            header_idx = i
            layout = "fms"
            break

    if header_idx < 0:
        raise ValueError(
            "No recognisable header row found. Expected one of: "
            "'Match,Time,Type,Blue 1...' (flat), "
            "'Type,Match,Day,Time,Red 1...,Surrogates' (report), or "
            "'Time,Description,Blue 1...' (FMS). First few rows: "
            f"{rows[:3]!r}"
        )

    header = [_normalize_header(c) for c in rows[header_idx]]

    def col(name: str) -> int:
        try:
            return header.index(name)
        except ValueError:
            return -1

    # Resolve column positions based on detected layout.
    if layout in ("flat", "report"):
        c_match = col("match")
        c_time  = col("time")
        c_type  = col("type")
    else:  # fms
        c_match = -1
        c_time  = col("time")
        c_type  = col("description")
    c_blue       = [col(f"blue {i}") for i in (1, 2, 3)]
    c_red        = [col(f"red {i}")  for i in (1, 2, 3)]
    c_surrogates = col("surrogates")  # report layout only; -1 otherwise

    if c_time < 0 or c_type < 0 or any(i < 0 for i in c_blue + c_red):
        raise ValueError(
            f"Header row missing required columns. Got: {header!r}"
        )

    qual_matches: list[dict] = []
    practice_matches: list[dict] = []

    for row_num, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        if not row or all((c is None or str(c).strip() == "") for c in row):
            continue

        def cell(idx: int) -> str | None:
            if idx < 0 or idx >= len(row):
                return None
            return row[idx]

        type_val = (cell(c_type) or "").strip()
        if not type_val:
            continue

        # Determine match number + classification.
        if layout == "flat":
            match_raw = cell(c_match)
            if match_raw is None:
                continue
            try:
                match_num = int(str(match_raw).strip())
            except (ValueError, TypeError):
                continue
            is_practice = type_val.lower().startswith("practice")
        elif layout == "report":
            # Match column is "Q12" or "P3" — extract the digit run.
            match_raw = cell(c_match)
            if match_raw is None:
                continue
            m = _MATCH_NUM_RE.search(str(match_raw))
            if not m:
                continue
            match_num = int(m.group(1))
            # Type column says "Qualification" / "Practice" outright in
            # the report layout, OR the Match cell is prefixed with "P".
            mr_str = str(match_raw).strip().upper()
            is_practice = (
                type_val.lower().startswith("practice") or mr_str.startswith("P")
            )
        else:
            # FMS: extract number from description, classify by prefix
            m = _MATCH_NUM_RE.search(type_val)
            if not m:
                continue
            match_num   = int(m.group(1))
            is_practice = type_val.lower().startswith("practice")

        time_str = (cell(c_time) or "").strip()

        blue = [_coerce_team(cell(i)) for i in c_blue]
        red  = [_coerce_team(cell(i)) for i in c_red]

        if not any(blue) and not any(red):
            continue

        # Parse surrogate flags (report layout only). The export joins
        # surrogate team numbers with ';'. We turn that back into per-
        # position boolean flags.
        red_clean  = [t for t in red  if t is not None]
        blue_clean = [t for t in blue if t is not None]
        red_surr   = [False] * len(red_clean)
        blue_surr  = [False] * len(blue_clean)
        if c_surrogates >= 0:
            sur_str = (cell(c_surrogates) or "").strip()
            if sur_str:
                # Split on ; or , — both are reasonable separators.
                surr_teams = set()
                for tok in re.split(r"[;,]", sur_str):
                    tok = tok.strip()
                    if tok.isdigit():
                        surr_teams.add(int(tok))
                for j, t in enumerate(red_clean):
                    if t in surr_teams: red_surr[j] = True
                for j, t in enumerate(blue_clean):
                    if t in surr_teams: blue_surr[j] = True

        target = practice_matches if is_practice else qual_matches
        target.append({
            "match_num":      match_num,
            "time":           time_str,
            "red":            red_clean,
            "blue":           blue_clean,
            "red_surrogate":  red_surr,
            "blue_surrogate": blue_surr,
        })

    n_qual     = len(qual_matches)
    n_practice = len(practice_matches)
    if n_qual == 0 and n_practice == 0:
        raise ValueError(
            "No matches found in CSV — header was recognised but no "
            "data rows produced parseable matches. Check that team "
            "numbers are integers."
        )

    return {
        "matches":         qual_matches,
        "practice":        practice_matches,
        "format_detected": f"Schedule CSV ({n_qual} qual, {n_practice} practice, {layout} layout)",
        "notes":           "",
        "page_count":      1,
    }
