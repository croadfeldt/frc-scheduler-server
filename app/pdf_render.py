"""HTML → PDF rendering for schedule exports.

Replaces the previous client-side html2canvas / html2pdf flow which
suffered from cross-browser inconsistencies, font-loading races,
canvas-width miscalculations, and unreliable table page-break support.

Architecture:

    Frontend POSTs schedule data + options → /api/schedules/render-pdf
    → this module renders an HTML template via Jinja-style string
    formatting (we don't bring in Jinja just for one template) → feeds
    HTML into weasyprint → returns the resulting PDF bytes.

Why weasyprint:
  - Real CSS Paged Media support: page-break-before/after work
    correctly on table rows, tbodies, and block elements
  - Renders text as actual PDF text (searchable, copy-pasteable,
    accessible), not rasterized canvases
  - Deterministic output across browsers, OSes, and clients
  - Drops Cairo as of v60 — only requires Pango/HarfBuzz/fontconfig
    on Linux

Input shape (from frontend):
    {
        "schedule": {
            "event_name":         str | None,
            "event_year":         int | None,
            "num_teams":          int,
            "matches_per_team":   int | float,
            "days": [
                {
                    "day_num":         int,
                    "is_practice_day": bool,
                    "label":           str,        # "Day 1" or "Practice"
                    "cycle_info":      str | None, # e.g. "8min/match"
                    "entries": [
                        {"type": "match", "num": int, "time": "HH:MM",
                         "red": [int,int,int], "blue": [int,int,int],
                         "red_surrogate": [bool,bool,bool],
                         "blue_surrogate": [bool,bool,bool],
                         "round": int | None},
                        {"type": "break", "name": str,
                         "start": "HH:MM", "end": "HH:MM"},
                        {"type": "cycle-change", "after_match": int,
                         "new_cycle_min": float, "at": "HH:MM"},
                    ],
                },
            ],
        },
        "options": {
            "scope":                 "both" | "qual" | "practice",
            "show_team_numbers":     bool,    # default True
            "show_cycle_times":      bool,
            "show_cycle_changes":    bool,
            "show_breaks":           bool,
            "show_day_breaks":       bool,
            "show_round_dividers":   bool,
            "page_break_after_practice": bool,
            "page_break_between_days":  bool,
        }
    }
"""
from __future__ import annotations

import html
import logging
from io import BytesIO
from typing import Any

log = logging.getLogger(__name__)

# Lazy import — weasyprint is heavy and pulls in Pango. We don't want
# to import it at module load on workers that never render PDFs (the
# scheduler workers, for example, get spawned in subprocesses and
# would each pay the import cost).
_WEASYPRINT = None


def _weasyprint():
    global _WEASYPRINT
    if _WEASYPRINT is None:
        try:
            from weasyprint import HTML, CSS  # noqa: F401
            _WEASYPRINT = (HTML, CSS)
        except Exception as e:
            raise RuntimeError(
                f"weasyprint failed to import. System deps missing? "
                f"On RHEL/CentOS: dnf install pango harfbuzz fontconfig dejavu-sans-fonts. "
                f"Error: {e}"
            )
    return _WEASYPRINT


# ─────────────────────────────────────────────────────────────────────
# CSS — kept here as a constant rather than a separate file so the
# whole renderer is one self-contained module. Print-aware: uses
# @page rules, page-break properties on the elements we tag.
# ─────────────────────────────────────────────────────────────────────

_CSS = r"""
@page {
    size: letter;
    margin: 0.5in;
    @bottom-right {
        content: "Page " counter(page) " of " counter(pages);
        font-size: 8pt;
        color: #6e7781;
    }
}

* { box-sizing: border-box; }

body {
    font-family: "DejaVu Sans", "Liberation Sans", sans-serif;
    color: #1c2128;
    font-size: 10pt;
    line-height: 1.4;
    margin: 0;
    padding: 0;
}

.brand-header {
    background: var(--primary-color, #0969da);
    color: #ffffff;
    padding: 8pt 12pt;
    margin: 0 0 10pt 0;
    border-radius: 4pt;
    display: table;
    width: 100%;
    table-layout: fixed;
}
.brand-header .logo-cell {
    display: table-cell;
    vertical-align: middle;
    width: 64pt;
    padding-right: 10pt;
}
.brand-header .logo {
    width: 50pt; height: 50pt;
    background: rgba(255, 255, 255, 0.18);
    border-radius: 4pt;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 16pt;
    font-weight: 700;
    color: #ffffff;
}
.brand-header .title-cell {
    display: table-cell;
    vertical-align: middle;
}
.brand-header h1 {
    margin: 0;
    font-size: 16pt;
    font-weight: 700;
    line-height: 1.15;
}
.brand-header .subtitle {
    font-size: 9pt;
    margin-top: 2pt;
    opacity: 0.9;
}

.day-section {
    /* Each day-section is a tbody-rooted block; CSS page-break
       properties on this work in WeasyPrint. */
    page-break-inside: auto;
}

.day-title {
    font-size: 11pt;
    font-weight: 700;
    margin: 12pt 0 4pt 0;
    border-bottom: 2pt solid #1c2128;
    padding-bottom: 2pt;
}
.day-title .cycle-info {
    font-weight: 400;
    color: #57606a;
    font-size: 9pt;
    margin-left: 6pt;
}
.day-title.page-break {
    page-break-before: always;
    margin-top: 0;
}

table.matches {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 8pt;
    font-size: 9pt;
    table-layout: fixed;
}
table.matches th {
    background: #f0f3f6;
    padding: 4pt;
    font-weight: 700;
    font-size: 8pt;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    border-bottom: 2pt solid #1c2128;
    text-align: center;
    color: #424a53;
}
table.matches th.left { text-align: left; padding-left: 8pt; }
table.matches th.blue { color: #0550ae; }
table.matches th.red  { color: #a3261a; }
table.matches td {
    padding: 3pt 4pt;
    border-bottom: 1pt solid #eaeef2;
    text-align: center;
    font-variant-numeric: tabular-nums;
}
table.matches td.left  { text-align: left; padding-left: 8pt; }
table.matches td.match { font-weight: 700; }
table.matches td.blue  { color: #0550ae; font-weight: 500; }
table.matches td.red   { color: #a3261a; font-weight: 500; }
table.matches tr:nth-child(even) td { background: #f7f8f9; }
table.matches tr.match-row.surrogate-only-row td { font-style: italic; }

/* Surrogate badge — small inline marker after the team number */
.sur {
    display: inline-block;
    font-size: 7pt;
    background: #fff3cd;
    color: #856404;
    padding: 0 2pt;
    border-radius: 2pt;
    margin-left: 2pt;
    vertical-align: super;
}

/* Break / cycle-change rows */
tr.break-row td {
    background: #fef9e7 !important;
    color: #b7770d;
    font-style: italic;
    font-weight: 500;
    font-size: 8.5pt;
    padding: 4pt;
}
tr.cc-row td {
    background: #f0f4ff !important;
    color: #444;
    font-style: italic;
    font-size: 8.5pt;
}
tr.round-row td {
    background: #f0f0f0 !important;
    color: #555;
    font-size: 7.5pt;
    text-align: center;
    letter-spacing: 0.05em;
    text-transform: uppercase;
}

/* Footer */
.footer {
    margin-top: 14pt;
    padding-top: 6pt;
    border-top: 1pt solid #d0d7de;
    font-size: 8pt;
    color: #57606a;
    text-align: center;
}

/* Column widths — fixed to keep layout consistent across pages.
   8 columns total: Time, Match, Blue 1-3, Red 1-3. The fixed
   table-layout above means these widths actually stick. */
table.matches col.time-col   { width: 12%; }
table.matches col.match-col  { width: 9%; }
table.matches col.team-col   { width: 13.16%; }  /* 6 cols × 13.16% = 79% */
"""


# ─────────────────────────────────────────────────────────────────────
# HTML construction
# ─────────────────────────────────────────────────────────────────────

def _esc(s: Any) -> str:
    """HTML-escape with str() coercion for None/int/etc."""
    return html.escape(str(s)) if s is not None else ""


def _team_cell(team: int, surrogate: bool, alliance: str) -> str:
    """Render a single team cell. alliance = 'red' or 'blue'."""
    if not team:
        return f'<td class="{alliance}">&mdash;</td>'
    sur = '<span class="sur">S</span>' if surrogate else ''
    return f'<td class="{alliance}">{_esc(team)}{sur}</td>'


def _build_day_section(
    day: dict[str, Any],
    options: dict[str, Any],
    is_first_day: bool,
    practice_break_before: bool,
) -> str:
    """Build one day's section: header + match table.

    practice_break_before: when True, emit page-break-before on the
    day-title (used to separate practice from quals). Independent of
    page_break_between_days, so both can be active at once.
    """
    show_team_numbers   = options.get("show_team_numbers", True)
    show_cycle_changes  = options.get("show_cycle_changes", True)
    show_breaks         = options.get("show_breaks", True)
    show_round_dividers = options.get("show_round_dividers", False)
    page_break_days     = options.get("page_break_between_days", True)
    show_cycle_times    = options.get("show_cycle_times", True)
    show_day_breaks     = options.get("show_day_breaks", True)

    classes = ["day-title"]
    if practice_break_before or (page_break_days and not is_first_day):
        classes.append("page-break")
    title_class = " ".join(classes)

    cycle_info_html = ""
    if show_cycle_times and day.get("cycle_info"):
        cycle_info_html = (
            f'<span class="cycle-info">&middot; {_esc(day["cycle_info"])}</span>'
        )

    match_count = sum(1 for e in day["entries"] if e.get("type") == "match")
    title_text = f'{_esc(day.get("label", "Day"))} &mdash; {match_count} matches{cycle_info_html}'

    parts = [
        f'<section class="day-section">',
        f'<div class="{title_class}">{title_text}</div>',
        '<table class="matches">',
        '<colgroup>',
        '<col class="time-col"><col class="match-col">',
        '<col class="team-col"><col class="team-col"><col class="team-col">',
        '<col class="team-col"><col class="team-col"><col class="team-col">',
        '</colgroup>',
        '<thead><tr>',
        '<th class="left">Time</th>',
        '<th class="left">Match</th>',
        '<th class="blue">Blue 1</th><th class="blue">Blue 2</th><th class="blue">Blue 3</th>',
        '<th class="red">Red 1</th><th class="red">Red 2</th><th class="red">Red 3</th>',
        '</tr></thead>',
        '<tbody>',
    ]

    for entry in day["entries"]:
        kind = entry.get("type")

        if kind == "break":
            if not show_breaks:
                continue
            parts.append(
                f'<tr class="break-row"><td colspan="8">'
                f'&#9646; {_esc(entry.get("name", "Break"))} &nbsp;&middot;&nbsp; '
                f'{_esc(entry.get("start", ""))} &ndash; {_esc(entry.get("end", ""))}'
                f'</td></tr>'
            )
            continue

        if kind == "cycle-change":
            if not show_cycle_changes:
                continue
            parts.append(
                f'<tr class="cc-row"><td colspan="8">'
                f'&#8645; Cycle time &rarr; <strong>{_esc(entry.get("new_cycle_min", ""))} min</strong> '
                f'from match {_esc(entry.get("after_match", 0) + 1)} '
                f'&nbsp;&middot;&nbsp; {_esc(entry.get("at", ""))}'
                f'</td></tr>'
            )
            continue

        if kind == "match":
            # Round divider row, before the match it precedes
            round_num = entry.get("round")
            if show_round_dividers and round_num is not None:
                note = "all teams guaranteed a first match" if round_num == 1 else "approximate boundary"
                parts.append(
                    f'<tr class="round-row"><td colspan="8">'
                    f'Round {_esc(round_num)} &mdash; {_esc(note)}'
                    f'</td></tr>'
                )

            # Match row itself
            num = entry.get("num", "")
            time_str = entry.get("time", "")
            red  = entry.get("red")  or [0, 0, 0]
            blue = entry.get("blue") or [0, 0, 0]
            red_sur  = entry.get("red_surrogate")  or [False, False, False]
            blue_sur = entry.get("blue_surrogate") or [False, False, False]

            # If team numbers shouldn't be shown, render dashes. Useful
            # for "abstract" mode previews where slot assignments
            # haven't been made yet.
            def cell(team: int, surrogate: bool, alliance: str) -> str:
                if not show_team_numbers:
                    return f'<td class="{alliance}">&mdash;</td>'
                return _team_cell(team, surrogate, alliance)

            match_label = f'{"P" if entry.get("is_practice") else "Q"}{_esc(num)}'

            parts.append(
                '<tr class="match-row">'
                f'<td class="left">{_esc(time_str)}</td>'
                f'<td class="left match">{match_label}</td>'
                f'{cell(blue[0], blue_sur[0] if len(blue_sur) > 0 else False, "blue")}'
                f'{cell(blue[1], blue_sur[1] if len(blue_sur) > 1 else False, "blue")}'
                f'{cell(blue[2], blue_sur[2] if len(blue_sur) > 2 else False, "blue")}'
                f'{cell(red[0],  red_sur[0]  if len(red_sur)  > 0 else False, "red")}'
                f'{cell(red[1],  red_sur[1]  if len(red_sur)  > 1 else False, "red")}'
                f'{cell(red[2],  red_sur[2]  if len(red_sur)  > 2 else False, "red")}'
                '</tr>'
            )
            continue

    parts.append('</tbody></table></section>')
    return "\n".join(parts)


def render_schedule_pdf(payload: dict[str, Any], branding: dict | None = None) -> bytes:
    """Render a schedule to PDF bytes.

    Args:
        payload: see module docstring for shape.
        branding: optional {"primary_color", "logo_text", "title", "subtitle"}
                  for branded output.

    Returns:
        PDF file contents as bytes.

    Raises:
        ValueError: if payload shape is invalid.
        RuntimeError: if weasyprint isn't available.
    """
    HTML, CSS = _weasyprint()

    schedule = payload.get("schedule") or {}
    options  = payload.get("options")  or {}
    branding = branding or {}

    days = schedule.get("days") or []
    if not days:
        raise ValueError("Cannot render PDF: no days in schedule")

    # Filter days by scope option. Scope is matches-side filtering;
    # day boundaries themselves stay (so a "qual only" PDF still has
    # the correct day numbers, just no practice day at the front).
    scope = options.get("scope", "both")
    if scope == "qual":
        days = [d for d in days if not d.get("is_practice_day")]
    elif scope == "practice":
        days = [d for d in days if d.get("is_practice_day")]

    if not days:
        raise ValueError(f"Scope '{scope}' filtered out all days")

    # Build branding header.
    primary_color = branding.get("primary_color", "#0969da")
    title_text    = branding.get("title") or schedule.get("event_name") or "FRC Match Schedule"
    subtitle      = branding.get("subtitle") or _build_subtitle(schedule)
    logo_text     = branding.get("logo_text") or (
        str(schedule.get("event_year"))[-2:] if schedule.get("event_year") else "FRC"
    )

    header_html = (
        '<header class="brand-header">'
        f'<div class="logo-cell"><div class="logo">{_esc(logo_text)}</div></div>'
        f'<div class="title-cell">'
        f'<h1>{_esc(title_text)}</h1>'
        + (f'<div class="subtitle">{_esc(subtitle)}</div>' if subtitle else '')
        + '</div></header>'
    )

    # Build day sections. Track practice→qual transition for the
    # page-break-after-practice option. Practice days come first
    # (day_num=0) by convention.
    page_break_after_practice = options.get("page_break_after_practice", True)
    sections_html = []
    seen_practice_day = False
    emitted_practice_break = False

    for i, day in enumerate(days):
        is_first = (i == 0)
        practice_break = (
            page_break_after_practice
            and seen_practice_day
            and not day.get("is_practice_day")
            and not emitted_practice_break
        )
        sections_html.append(
            _build_day_section(day, options, is_first, practice_break)
        )
        if practice_break:
            emitted_practice_break = True
        if day.get("is_practice_day"):
            seen_practice_day = True

    # Footer
    n_teams = schedule.get("num_teams")
    mpt     = schedule.get("matches_per_team")
    n_total = sum(
        sum(1 for e in d["entries"] if e.get("type") == "match")
        for d in days
    )
    foot_parts = []
    if n_teams: foot_parts.append(f"{_esc(n_teams)} teams")
    if mpt:     foot_parts.append(f"{_esc(mpt)} matches/team")
    foot_parts.append(f"{n_total} total matches")
    foot_parts.append("Generated by FRC Match Scheduler")
    footer_html = f'<div class="footer">{" &middot; ".join(foot_parts)}</div>'

    full_html = (
        '<!DOCTYPE html>'
        '<html lang="en"><head><meta charset="utf-8">'
        f'<title>{_esc(title_text)}</title>'
        '</head><body>'
        + header_html
        + "\n".join(sections_html)
        + footer_html
        + '</body></html>'
    )

    # CSS variable substitution (weasyprint supports CSS custom
    # properties but our --primary-color usage is in the brand-header
    # via JS-style var() calls; replace it here for guaranteed effect).
    css_text = _CSS.replace("var(--primary-color, #0969da)", primary_color)

    output = BytesIO()
    HTML(string=full_html).write_pdf(
        output,
        stylesheets=[CSS(string=css_text)],
    )
    return output.getvalue()


def _build_subtitle(schedule: dict[str, Any]) -> str:
    """Reasonable subtitle from schedule metadata."""
    parts = []
    if schedule.get("event_year"):
        parts.append(str(schedule["event_year"]))
    if schedule.get("event_location"):
        parts.append(str(schedule["event_location"]))
    return " · ".join(parts)
