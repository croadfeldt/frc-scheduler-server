"""Derive scheduler parameters from a match list when no parameters
block is present in the import source.

Used by /api/schedules/import-xlsx and /api/schedules/import-csv to
pre-fill the form fields after a "Restore from file" with a match-only
file. The user can override anything that looks wrong before
regenerating.

What we derive (and how reliable each is):

  num_teams          — distinct team numbers across all matches.
                       ALWAYS reliable.
  matches_per_team   — mode of appearance counts per team. Reliable
                       when the schedule is even; uses the most
                       common count when teams have varied
                       appearances.
  cycle_time_min     — modal time delta between consecutive matches
                       not separated by a break. Reliable when the
                       cadence is consistent. Reports the most
                       common delta.
  cooldown           — minimum gap between consecutive appearances
                       of the same team, in match slots. Reliable
                       lower bound; the actual cooldown may have
                       been higher.
  num_days           — count of distinct day boundaries in the
                       input. With single-sheet CSV/XLSX exports
                       this defaults to 1; multi-sheet workbooks
                       can hint at more.
  day_config         — best-effort: span (earliest match to latest
                       match plus one cycle), gaps over 30 min
                       become breaks. Practice day not derivable
                       from match data alone.

For each derived value, we also return a confidence flag ("high" /
"medium" / "low") so the UI can decide whether to silently apply
or to flag it as uncertain.
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any

log = logging.getLogger(__name__)


def _hhmm_to_min(t: str | None) -> int | None:
    """'08:30' -> 510. None / blank / malformed -> None."""
    if not t:
        return None
    s = str(t).strip()
    if not s:
        return None
    parts = s.split(":")
    if len(parts) != 2:
        return None
    try:
        h, m = int(parts[0]), int(parts[1])
        if 0 <= h < 48 and 0 <= m < 60:  # allow next-day overflow up to 47:59
            return h * 60 + m
    except (ValueError, TypeError):
        pass
    return None


def _min_to_hhmm(m: int | None) -> str:
    """510 -> '08:30'. None -> ''."""
    if m is None:
        return ""
    h, mm = divmod(int(m) % (24 * 60), 60)
    return f"{h:02d}:{mm:02d}"


def derive_parameters(
    matches: list[dict],
    practice_matches: list[dict] | None = None,
) -> dict[str, Any]:
    """Inspect a match list and return derived scheduler parameters
    plus a per-field confidence map.

    Args:
        matches: list of dicts with at minimum {match_num, time,
                 red[], blue[]}. Same shape as PDF/XLSX/CSV
                 importer output.
        practice_matches: optional list of practice matches in the
                 same shape. When supplied non-empty, the emitted
                 V2 day_config gains a leading practice-only day
                 with a derived practice block (start/end/cycleTime
                 from the practice times). This is what makes /view
                 render the practice tab — without a practiceDay in
                 day_config, view.html silently skips practice
                 matches even when they're present in the assigned
                 schedule's practice_matches column.

    Returns:
        {
            "parameters": {
                "num_teams":        int,
                "matches_per_team": int,
                "cycle_time_min":   float,
                "cooldown":         int,
                "num_days":         int,
            },
            "day_config": {
                "days": [{"start": "HH:MM", "end": "HH:MM",
                          "breaks": [{"name": "Break", "start": ...,
                                       "end": ...}]}],
                ...
            },
            "confidence": {
                "num_teams":        "high",
                "matches_per_team": "high"|"medium",
                ...
            },
            "notes": [<human-readable warnings>],
        }

    Raises ValueError if matches is empty.
    """
    if not matches:
        raise ValueError("Cannot derive parameters from empty match list")

    # Sort by match number first; we rely on order for cycle/cooldown.
    sorted_matches = sorted(matches, key=lambda m: int(m.get("match_num") or 0))

    confidence: dict[str, str] = {}
    notes: list[str] = []

    # ── num_teams ───────────────────────────────────────────────────
    teams: set[int] = set()
    for m in sorted_matches:
        for t in (m.get("red")  or []): teams.add(t)
        for t in (m.get("blue") or []): teams.add(t)
    num_teams = len(teams)
    confidence["num_teams"] = "high"

    # ── matches_per_team ────────────────────────────────────────────
    # Count appearances per team. The mode (most common count) is the
    # nominal MPT. If there's a clear modal value, that's high
    # confidence; if appearance counts are scattered (some teams
    # with N matches, many with N+1 — surrogates / partial day),
    # confidence drops.
    appearances = Counter()
    for m in sorted_matches:
        for t in (m.get("red")  or []): appearances[t] += 1
        for t in (m.get("blue") or []): appearances[t] += 1
    if appearances:
        count_dist = Counter(appearances.values())
        modal_count, modal_freq = count_dist.most_common(1)[0]
        matches_per_team = modal_count
        # If 90%+ of teams hit the modal count, high confidence.
        if num_teams > 0 and modal_freq / num_teams >= 0.9:
            confidence["matches_per_team"] = "high"
        elif modal_freq / num_teams >= 0.7:
            confidence["matches_per_team"] = "medium"
        else:
            confidence["matches_per_team"] = "low"
            notes.append(
                f"Per-team match counts are uneven — modal value {modal_count} "
                f"covers only {modal_freq}/{num_teams} teams. "
                f"Verify Matches Per Team before regenerating."
            )
    else:
        matches_per_team = 0
        confidence["matches_per_team"] = "low"

    # ── cycle_time_min ──────────────────────────────────────────────
    # Walk consecutive matches; record time deltas. Drop deltas above
    # 30 minutes (those are breaks, not the cycle cadence). Take the
    # mode of remaining deltas. A clean schedule has all deltas equal
    # — that's high confidence. Variance > 50% drops confidence.
    deltas: list[int] = []
    prev_min: int | None = None
    for m in sorted_matches:
        t_min = _hhmm_to_min(m.get("time"))
        if t_min is not None and prev_min is not None:
            d = t_min - prev_min
            if 0 < d <= 30:  # ignore breaks (>30 min) and back-in-time anomalies
                deltas.append(d)
        if t_min is not None:
            prev_min = t_min

    if deltas:
        delta_dist = Counter(deltas)
        modal_delta, modal_freq = delta_dist.most_common(1)[0]
        cycle_time_min = float(modal_delta)
        # Variance check: how often does the modal delta actually appear?
        if modal_freq / len(deltas) >= 0.85:
            confidence["cycle_time_min"] = "high"
        elif modal_freq / len(deltas) >= 0.6:
            confidence["cycle_time_min"] = "medium"
        else:
            confidence["cycle_time_min"] = "low"
            notes.append(
                f"Inconsistent cycle times — modal {modal_delta} min "
                f"covers {modal_freq}/{len(deltas)} consecutive pairs. "
                f"There may be cycle-time changes during the day."
            )
    else:
        cycle_time_min = 8.0  # safe default
        confidence["cycle_time_min"] = "low"
        notes.append("Could not derive cycle time (no consecutive match times).")

    # ── cooldown ────────────────────────────────────────────────────
    # Minimum gap (in match slots) between consecutive appearances of
    # the same team. Tracked as match-number distance. e.g. team 2052
    # appears in matches 1, 5, 9 -> gaps of 4 and 4 -> cooldown >= 3
    # (cooldown N means N matches between appearances).
    last_seen: dict[int, int] = {}
    min_gap: int | None = None
    for m in sorted_matches:
        mn = int(m.get("match_num") or 0)
        for t in (m.get("red") or []) + (m.get("blue") or []):
            if t in last_seen:
                gap = mn - last_seen[t] - 1   # cooldown = matches between, exclusive
                if gap >= 0 and (min_gap is None or gap < min_gap):
                    min_gap = gap
            last_seen[t] = mn

    cooldown = min_gap if min_gap is not None else 3
    # Cooldown derived from data is a tight lower bound — the original
    # constraint may have been ≥ this value. Confidence is "medium"
    # because we can't tell whether the minimum we observed is the
    # constraint or just an incidental value.
    confidence["cooldown"] = "medium" if min_gap is not None else "low"

    # ── num_days ────────────────────────────────────────────────────
    # Default to 1. Caller can override based on file structure (e.g.
    # multi-sheet XLSX with day labels). With a single match list and
    # 24-hour HH:MM, there's no reliable way to detect day rollover.
    num_days = 1
    confidence["num_days"] = "medium"

    # ── day_config ──────────────────────────────────────────────────
    # Single-day best-effort: span from earliest to latest match plus
    # one cycle, with gaps > 30 min becoming breaks. Real day_config
    # is richer (practice day, cycle changes) — those default to off.
    day_start_min: int | None = None
    day_end_min:   int | None = None
    breaks: list[dict] = []

    times_sorted = [
        _hhmm_to_min(m.get("time")) for m in sorted_matches
    ]
    times_sorted = [t for t in times_sorted if t is not None]
    if times_sorted:
        day_start_min = times_sorted[0]
        # End is last match's time + one cycle (so the last match has
        # time to actually run before the day ends).
        day_end_min = times_sorted[-1] + int(round(cycle_time_min))

        # Breaks: any gap > 30 min between consecutive matches becomes
        # a break block. Naming is generic ("Lunch" if it spans noon,
        # else "Break").
        for i in range(1, len(times_sorted)):
            gap = times_sorted[i] - times_sorted[i - 1]
            if gap > 30:
                start = times_sorted[i - 1] + int(round(cycle_time_min))
                end   = times_sorted[i]
                # Skip pathological "negative" breaks (cycle_time was
                # bigger than the gap due to noisy data).
                if start >= end:
                    continue
                # Heuristic naming: if the break covers any minute
                # between 11:30 and 13:30, call it Lunch.
                noon_low, noon_high = 11 * 60 + 30, 13 * 60 + 30
                is_lunch = (start <= noon_high) and (end >= noon_low)
                breaks.append({
                    "name":  "Lunch" if is_lunch else "Break",
                    "start": _min_to_hhmm(start),
                    "end":   _min_to_hhmm(end),
                })

    # Emit V2-shape day_config per docs/V2_SPEC.md. The single derived
    # day becomes one V2 day with one qualification block; breaks
    # become tier-3 nested children of the qual block. Lunch breaks
    # detected by name get breakKind="lunch"; everything else is
    # generic "break". The breakKind heuristic is intentionally
    # narrow — schedule_derive's input doesn't carry richer hints,
    # so we don't try to detect awards/ceremonies.
    qual_block: dict[str, Any] = {
        "type":      "qualification",
        "start":     _min_to_hhmm(day_start_min) or "08:30",
        "end":       _min_to_hhmm(day_end_min)   or "17:00",
        "cycleTime": cycle_time_min,
        "changes":   [],
        "breaks":    [
            {
                "type":      "break",
                "start":     b["start"],
                "end":       b["end"],
                "label":     b.get("name") or "Break",
                "breakKind": "lunch" if (b.get("name") or "").lower() == "lunch" else "break",
            }
            for b in breaks
        ],
    }

    v2_days: list[dict[str, Any]] = []

    # Practice day (if any). Encoded as a V2 day with a single
    # practice block — view.html's V2→V1 downgrade promotes a
    # practice-only day to `practiceDay`, which is what gates the
    # practice-tab render. Without this, importing a MatchMaker
    # workbook with a Practice sheet leaves practice matches in
    # the DB but invisible on /view.
    if practice_matches:
        p_block = _derive_practice_block(practice_matches, cycle_time_min)
        if p_block is not None:
            v2_days.append({
                "label":  "Practice",
                "date":   "",
                "blocks": [p_block],
            })

    v2_days.append({
        "label":  "Day 1",
        "date":   "",
        "blocks": [qual_block],
    })

    # num_days here counts V2 days emitted (qual + optional practice).
    # Confidence "high" when practice presence is unambiguous (the
    # caller passed an explicit non-empty list); otherwise "medium"
    # for the qual-only single-day default.
    num_days = len(v2_days)
    confidence["num_days"] = "high" if practice_matches else "medium"

    day_config: dict[str, Any] = {
        "dayConfigVersion": 2,
        "cycleTime":   cycle_time_min,
        "breakBuffer": 5,
        "days":        v2_days,
        # Side-channel state preserved across the V2 wire — these
        # aren't part of the canonical V2 model but the editor
        # piggybacks them on day_config. They get stripped on full
        # validation; preserving them here keeps existing UI flows
        # working through the transition.
        "autoPopulate":  True,
        "autoMaxCycles": True,
        "autoAssign":    False,
    }

    return {
        "parameters": {
            "num_teams":        num_teams,
            "matches_per_team": matches_per_team,
            "cycle_time_min":   cycle_time_min,
            "cooldown":         cooldown,
            "num_days":         num_days,
        },
        "day_config": day_config,
        "confidence": confidence,
        "notes":      notes,
    }


def _derive_practice_block(
    practice_matches: list[dict],
    fallback_cycle_min: float,
) -> dict[str, Any] | None:
    """Build a V2 practice block from the practice match list.

    Mirrors the qual derivation but on a smaller dataset. The
    practice section is typically a handful of matches at slower
    cadence (FRC regional convention is ~9 min/match vs 8 for
    quals — see docs/PRACTICE_DAY.md). Returns ``None`` only when
    the input is empty; otherwise always returns a usable block,
    falling back to defaults for any field the times don't yield.

    Args:
        practice_matches: parsed practice matches with HH:MM times.
        fallback_cycle_min: cycle to use when the practice deltas
            don't yield a confident value (e.g. only one match).
    """
    if not practice_matches:
        return None

    # Sort by match number, just like the qual path.
    sorted_pm = sorted(
        practice_matches, key=lambda m: int(m.get("match_num") or 0)
    )

    times_min = [
        t for t in (_hhmm_to_min(m.get("time")) for m in sorted_pm)
        if t is not None
    ]

    # Cycle time: modal delta among consecutive practice match starts,
    # filtering breaks (>30 min) and back-in-time anomalies. Practice
    # blocks are usually short and contiguous so the simplest
    # approach works. Fall back to the qual cycle when there's not
    # enough data — common for 1-3 practice match blocks.
    p_deltas: list[int] = []
    for a, b in zip(times_min, times_min[1:]):
        d = b - a
        if 0 < d <= 30:
            p_deltas.append(d)
    if p_deltas:
        from collections import Counter
        p_cycle = float(Counter(p_deltas).most_common(1)[0][0])
    else:
        p_cycle = float(fallback_cycle_min)

    # Start = earliest match. End = latest + one cycle (so the last
    # match has time to actually run before the block ends).
    if times_min:
        p_start = times_min[0]
        p_end   = times_min[-1] + int(round(p_cycle))
    else:
        p_start = None
        p_end   = None

    # docs/PRACTICE_DAY.md FRC convention: 3 guaranteed matches per
    # team. We can't infer this reliably from the match list (the
    # number of guaranteed matches isn't a function of how many
    # matches were scheduled), so we use the documented default and
    # let the user override it if their event is different.
    return {
        "type":       "practice",
        "start":      _min_to_hhmm(p_start) or "08:30",
        "end":        _min_to_hhmm(p_end)   or "17:00",
        "cycleTime":  p_cycle,
        "changes":    [],
        "breaks":     [],
        "guaranteed": 3,
        "maxFiller":  99,
    }
