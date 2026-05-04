"""Schedule validation — applied to LLM-parsed schedules before user confirmation.

The validator catches everything that could go wrong with LLM extraction:
- OCR digit errors (8 vs 3, 0 vs 6) → wrong team numbers
- Missing surrogate notation → wrong appearance counts
- Off-by-one match numbering → gap or duplicate
- Same team twice in a match → mis-read column

Validation produces structured findings (errors + warnings + info) that
the frontend renders as a checklist before the user confirms the import.
We never auto-import without user review.
"""
from __future__ import annotations

from collections import Counter
from typing import Any


def validate_schedule(matches: list[dict], team_roster: list[int] | None = None) -> dict:
    """Check a parsed schedule for structural problems.

    Args:
        matches: list of {match_num, time, red, blue, red_surrogate, blue_surrogate}
        team_roster: optional list of expected team numbers. When provided,
                     we cross-check that the matches use exactly these teams.
                     When None (no roster supplied yet), we infer the team set
                     from the matches themselves.

    Returns dict with:
        ok:        bool — overall pass/fail (errors → False)
        errors:    list of {code, message, match_nums?}
        warnings:  list of same shape — non-blocking issues to surface to user
        info:      list of same shape — derived facts (team count, MPT, etc.)
        stats: {
          num_teams, total_matches, surrogate_count,
          appearances_per_team: {team: count},
          mpt_normal: int — most common appearance count, treated as MPT
          appearances_outliers: list of teams that don't match MPT or MPT+1
        }
    """
    errors: list[dict] = []
    warnings: list[dict] = []
    info: list[dict] = []

    if not matches:
        errors.append({"code": "no_matches", "message": "No matches found in PDF."})
        return {"ok": False, "errors": errors, "warnings": warnings, "info": info, "stats": {}}

    # ── Structural checks ──────────────────────────────────────────────────
    # Each match has 3 red, 3 blue, no duplicates within a match
    for m in matches:
        mn = m.get("match_num", "?")
        red = m.get("red") or []
        blue = m.get("blue") or []
        if len(red) != 3:
            errors.append({"code": "wrong_red_count", "message": f"Match {mn}: expected 3 red teams, got {len(red)}", "match_nums": [mn]})
        if len(blue) != 3:
            errors.append({"code": "wrong_blue_count", "message": f"Match {mn}: expected 3 blue teams, got {len(blue)}", "match_nums": [mn]})
        all_six = red + blue
        if len(set(all_six)) != len(all_six):
            errors.append({"code": "duplicate_team_in_match", "message": f"Match {mn}: a team appears more than once", "match_nums": [mn]})
        # Team numbers should be positive integers
        for t in all_six:
            if not isinstance(t, int) or t <= 0:
                errors.append({"code": "invalid_team_number", "message": f"Match {mn}: invalid team number '{t}'", "match_nums": [mn]})

    # ── Match number sequence ──────────────────────────────────────────────
    nums = [m.get("match_num") for m in matches if isinstance(m.get("match_num"), int)]
    if nums:
        if min(nums) != 1:
            warnings.append({"code": "first_match_not_1", "message": f"First match number is {min(nums)}, expected 1"})
        # Detect gaps and duplicates
        seen: dict[int, int] = {}
        for n in nums:
            seen[n] = seen.get(n, 0) + 1
        dupes = [n for n, c in seen.items() if c > 1]
        if dupes:
            errors.append({"code": "duplicate_match_nums", "message": f"Duplicate match numbers: {sorted(dupes)}", "match_nums": dupes})
        expected = set(range(min(nums), max(nums) + 1))
        gaps = sorted(expected - set(nums))
        if gaps:
            errors.append({"code": "missing_match_nums", "message": f"Missing match numbers: {gaps[:10]}", "match_nums": gaps[:10]})

    # ── Team appearance counts ─────────────────────────────────────────────
    appearances: Counter[int] = Counter()
    for m in matches:
        for t in (m.get("red") or []) + (m.get("blue") or []):
            if isinstance(t, int) and t > 0:
                appearances[t] += 1

    if not appearances:
        errors.append({"code": "no_teams", "message": "No valid team numbers found in matches"})
        return {"ok": False, "errors": errors, "warnings": warnings, "info": info, "stats": {}}

    # MPT inferred as the modal appearance count
    count_distribution = Counter(appearances.values())
    mpt_normal, _ = count_distribution.most_common(1)[0]
    outliers = [t for t, c in appearances.items() if c not in (mpt_normal, mpt_normal + 1)]

    if outliers:
        sample = sorted(outliers)[:5]
        warnings.append({
            "code":    "appearance_count_outlier",
            "message": f"{len(outliers)} team(s) don't have {mpt_normal} or {mpt_normal+1} appearances. "
                       f"Examples: {[(t, appearances[t]) for t in sample]}",
        })

    # ── Surrogate sanity ───────────────────────────────────────────────────
    # Total surrogate flags should equal total appearances - (num_teams * MPT).
    # If LLM missed surrogate notation, the count won't match.
    total_sur_flags = 0
    for m in matches:
        for f in (m.get("red_surrogate") or []) + (m.get("blue_surrogate") or []):
            if f: total_sur_flags += 1
    expected_sur = sum(appearances.values()) - len(appearances) * mpt_normal
    if expected_sur < 0:
        # Some teams have fewer than MPT appearances — different problem already flagged
        pass
    elif total_sur_flags != expected_sur:
        warnings.append({
            "code":    "surrogate_count_mismatch",
            "message": f"LLM marked {total_sur_flags} surrogate slots, but math says there should be {expected_sur} "
                       f"(based on MPT={mpt_normal} and {len(appearances)} teams). The LLM may have missed "
                       f"surrogate notation, or some teams have unusual appearance counts.",
        })

    # FIRST rule: surrogate appearance is the team's 3rd match
    # Track for each team which appearance index is flagged surrogate
    team_appearances: dict[int, list[bool]] = {}  # team -> list of (is_surrogate) per appearance
    for m in sorted(matches, key=lambda x: x.get("match_num", 0)):
        red = m.get("red") or []
        blue = m.get("blue") or []
        red_sur = m.get("red_surrogate") or [False, False, False]
        blue_sur = m.get("blue_surrogate") or [False, False, False]
        for i, t in enumerate(red):
            if isinstance(t, int):
                team_appearances.setdefault(t, []).append(bool(red_sur[i]) if i < len(red_sur) else False)
        for i, t in enumerate(blue):
            if isinstance(t, int):
                team_appearances.setdefault(t, []).append(bool(blue_sur[i]) if i < len(blue_sur) else False)
    surrogates_not_at_3 = []
    for t, flags in team_appearances.items():
        for i, f in enumerate(flags, start=1):
            if f and i != 3 and mpt_normal >= 3:
                surrogates_not_at_3.append((t, i))
    if surrogates_not_at_3:
        sample = surrogates_not_at_3[:5]
        warnings.append({
            "code":    "surrogate_not_at_3rd_match",
            "message": f"FIRST rule (manual §10.5.2) says surrogate appearances should be the team's 3rd match. "
                       f"{len(surrogates_not_at_3)} surrogate flag(s) are at other appearance numbers. Examples: {sample}",
        })

    # ── Roster cross-check (when provided) ─────────────────────────────────
    if team_roster is not None:
        roster_set = set(team_roster)
        in_matches = set(appearances.keys())
        unknown = in_matches - roster_set
        missing = roster_set - in_matches
        if unknown:
            errors.append({
                "code":    "team_not_in_roster",
                "message": f"{len(unknown)} team(s) in matches not in event roster: {sorted(unknown)[:10]}. "
                           f"Possible OCR error.",
            })
        if missing:
            warnings.append({
                "code":    "team_in_roster_unused",
                "message": f"{len(missing)} team(s) in roster not appearing in any match: {sorted(missing)[:10]}",
            })

    # ── Back-to-back check ─────────────────────────────────────────────────
    # FRC events generally have a cooldown of at least 1 match between
    # appearances. B2B is rare and worth flagging.
    sorted_matches = sorted(matches, key=lambda x: x.get("match_num", 0))
    b2b_pairs: list[tuple[int, int]] = []
    for i in range(1, len(sorted_matches)):
        prev = set((sorted_matches[i-1].get("red") or []) + (sorted_matches[i-1].get("blue") or []))
        curr = set((sorted_matches[i].get("red") or []) + (sorted_matches[i].get("blue") or []))
        common = prev & curr
        if common:
            b2b_pairs.append((sorted_matches[i-1].get("match_num"), sorted_matches[i].get("match_num")))
    if b2b_pairs:
        warnings.append({
            "code":    "back_to_back",
            "message": f"{len(b2b_pairs)} back-to-back team appearance(s) detected. Examples (match→match): {b2b_pairs[:5]}",
        })

    # ── Info ───────────────────────────────────────────────────────────────
    info.append({"code": "summary", "message":
        f"{len(appearances)} teams, {len(matches)} matches, MPT≈{mpt_normal}, "
        f"{total_sur_flags} surrogate slot(s)"})

    stats = {
        "num_teams":              len(appearances),
        "total_matches":          len(matches),
        "surrogate_count":        total_sur_flags,
        "appearances_per_team":   dict(appearances),
        "mpt_normal":             mpt_normal,
        "appearances_outliers":   outliers,
    }
    return {
        "ok":       len(errors) == 0,
        "errors":   errors,
        "warnings": warnings,
        "info":     info,
        "stats":    stats,
    }
