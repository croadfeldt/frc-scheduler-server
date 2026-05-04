"""Thin wrapper around the Statbotics REST API v3.

Statbotics provides EPA (Expected Points Added) ratings for FRC teams —
similar to Elo but in match-point units, with separate auto/teleop/endgame
components. We pull team-event EPA snapshots to display in the per-team
panel alongside the TBA rank.

Docs: https://www.statbotics.io/docs/rest
The API is free and unauthenticated for read access.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

STATBOTICS_BASE = "https://api.statbotics.io/v3"

# Per-team-per-event lookups happen at most once per few minutes per (team, event)
# pair, so we cache aggressively. Keyed by (team_num, event_key) → (timestamp, data).
# This is an in-process cache; with multiple workers it's per-worker. That's fine —
# Statbotics doesn't enforce strict per-IP limits and a few duplicate calls are
# a reasonable tradeoff for not adding Redis just for this.
_CACHE: dict[tuple[int, str], tuple[float, dict | None]] = {}
_CACHE_TTL_SECONDS = 600   # 10 minutes


async def _get(path: str) -> Any:
    url = f"{STATBOTICS_BASE}{path}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.get(url)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            log.warning("Statbotics request failed for %s: %s", url, e)
            return None


async def get_team_event(team_number: int, event_key: str) -> dict | None:
    """Get EPA stats for a team at a specific event.

    Returns a dict like:
        {
          "team": 2169, "year": 2026, "event": "2026mnst",
          "team_name": "Team Name",
          "epa": {
            "ranking": {"rank": 5, "rps": 18, "wins": 6, "losses": 2, "ties": 0},
            "total_points": {"mean": 142.3, ...},
            "norm": 1750,        # normalized EPA (0-2500ish, higher is better)
            "stats": {"start": ..., "pre_playoffs": ..., "end": ...},
            ...
          },
          "record": {"wins": 6, "losses": 2, "ties": 0},
          ...
        }

    Returns None if Statbotics doesn't have data for this (team, event) pair —
    happens for off-season events that aren't in their database yet, or for
    teams that haven't played yet.
    """
    import time
    cache_key = (team_number, event_key.lower())
    now = time.time()
    if cache_key in _CACHE:
        ts, data = _CACHE[cache_key]
        if now - ts < _CACHE_TTL_SECONDS:
            return data
    data = await _get(f"/team_event/{team_number}/{event_key.lower()}")
    _CACHE[cache_key] = (now, data)
    return data


async def get_team_year(team_number: int, year: int) -> dict | None:
    """Get a team's overall EPA stats for a given year. Used as a fallback
    when team-event data isn't yet available (e.g., before the event)."""
    return await _get(f"/team_year/{team_number}/{year}")


def normalize_team_event(raw: dict) -> dict:
    """Pluck the fields we surface in the UI from Statbotics's verbose payload.
    Returns None for missing fields rather than crashing on schema drift."""
    if not raw:
        return {}
    epa = raw.get("epa") or {}
    record = raw.get("record") or {}
    ranking = (epa.get("ranking") or {})
    return {
        "team":            raw.get("team"),
        "team_name":       raw.get("team_name"),
        "event":           raw.get("event"),
        "year":            raw.get("year"),
        # Normalized EPA — comparable across years/games. Higher = better.
        "norm_epa":        epa.get("norm"),
        # Raw end-of-event EPA (point units, current-game-specific)
        "epa_end":         (epa.get("stats") or {}).get("end") or epa.get("total_points", {}).get("mean"),
        # Component breakdowns (auto/teleop/endgame) — year-agnostic keys
        "auto_epa":        (epa.get("breakdown") or {}).get("auto_points"),
        "teleop_epa":      (epa.get("breakdown") or {}).get("teleop_points"),
        "endgame_epa":     (epa.get("breakdown") or {}).get("endgame_points"),
        # Win/loss record (matches Statbotics's view, not necessarily TBA)
        "wins":            record.get("wins"),
        "losses":          record.get("losses"),
        "ties":            record.get("ties"),
        # Rank within the event (Statbotics's prediction rank, not TBA's official rank)
        "predicted_rank":  ranking.get("rank"),
        # Statbotics's confidence-style fields
        "winrate":         (raw.get("record") or {}).get("winrate"),
    }
