# SPDX-License-Identifier: GPL-3.0-or-later
# FRC Match Scheduler
# Copyright (C) 2025 FRC Match Scheduler Contributors
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.
#
# NOTE: This file was substantially generated with the assistance of Claude,
# an AI assistant by Anthropic, and reviewed/modified by human contributors.
# See LICENSE for full terms.

"""
The Blue Alliance (TBA) API client.
Docs: https://www.thebluealliance.com/apidocs/v3

Set TBA_API_KEY environment variable to your read key.
Get one free at: https://www.thebluealliance.com/account
"""

import os
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

TBA_BASE = "https://www.thebluealliance.com/api/v3"
TBA_KEY  = os.getenv("TBA_API_KEY", "").strip()

# Don't create a module-level AsyncClient singleton — async clients must be
# created inside a running event loop. Create a fresh client per request instead.
# (The performance cost is negligible; TBA calls are infrequent.)


async def _get(path: str) -> Any:
    if not TBA_KEY:
        raise ValueError(
            "TBA_API_KEY is not configured on the server. "
            "Set it in your .env file or OpenShift secret (frc-app-secret → TBA_API_KEY). "
            "Get a free key at https://www.thebluealliance.com/account"
        )
    async with httpx.AsyncClient(
        base_url=TBA_BASE,
        headers={"X-TBA-Auth-Key": TBA_KEY},
        timeout=15.0,
    ) as client:
        resp = await client.get(path)
        resp.raise_for_status()
        return resp.json()


# ── Public API calls ──────────────────────────────────────────────────────────

async def get_events(year: int) -> list[dict]:
    """All events for a given year, sorted by start date."""
    events = await _get(f"/events/{year}/simple")
    # Sort by start_date so upcoming events appear first in the dropdown
    events.sort(key=lambda e: e.get("start_date") or "")
    return events


async def get_event(event_key: str) -> dict:
    """Single event details."""
    return await _get(f"/event/{event_key}/simple")


async def get_event_teams(event_key: str) -> list[dict]:
    """All teams registered for an event."""
    return await _get(f"/event/{event_key}/teams/simple")


async def get_team(team_key: str) -> dict:
    """Single team details. team_key is e.g. 'frc254'."""
    return await _get(f"/team/{team_key}/simple")


async def get_teams_by_number(team_numbers: list[int]) -> list[dict]:
    """
    Fetch details for a list of team numbers.
    TBA doesn't have a bulk endpoint, so we batch with asyncio.
    """
    import asyncio
    keys = [f"frc{n}" for n in team_numbers]
    tasks = [_get(f"/team/{k}/simple") for k in keys]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    teams = []
    for r in results:
        if isinstance(r, Exception):
            log.warning("TBA team fetch error: %s", r)
        else:
            teams.append(r)
    return teams


async def search_events(year: int, search: str) -> list[dict]:
    """Filter events by name/key substring (client-side — TBA has no search endpoint)."""
    events = await get_events(year)
    s = search.lower()
    return [e for e in events if s in e.get("key", "").lower() or s in e.get("name", "").lower()]


# ── Normalise TBA responses to our schema ────────────────────────────────────

def normalise_team(tba: dict) -> dict:
    """Convert TBA team dict to our Team schema."""
    key = tba.get("key", "")
    num = int(key.replace("frc", "")) if key.startswith("frc") else tba.get("team_number", 0)
    return {
        "number":      num,
        "name":        tba.get("name"),
        "nickname":    tba.get("nickname"),
        "city":        tba.get("city"),
        "state":       tba.get("state_prov"),
        "country":     tba.get("country"),
        "rookie_year": tba.get("rookie_year"),
    }


def normalise_event(tba: dict) -> dict:
    """Convert TBA event dict to our Event schema."""
    return {
        "key":        tba.get("key", ""),
        "name":       tba.get("name", ""),
        "year":       tba.get("year", 0),
        "location":   ", ".join(filter(None, [tba.get("city"), tba.get("state_prov"), tba.get("country")])),
        "start_date": tba.get("start_date"),
        "end_date":   tba.get("end_date"),
        "tba_synced": True,
    }
