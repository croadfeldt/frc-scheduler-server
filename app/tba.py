# SPDX-License-Identifier: GPL-3.0-or-later
# FRC Match Scheduler
# Copyright (C) 2025 FRC Match Scheduler Contributors
#
# NOTE: This file was substantially generated with the assistance of Claude,
# an AI assistant by Anthropic, and reviewed/modified by human contributors.
# See LICENSE for full terms.

"""The Blue Alliance (TBA) API client — https://www.thebluealliance.com/apidocs/v3"""

import os
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

TBA_BASE = "https://www.thebluealliance.com/api/v3"
TBA_KEY  = os.getenv("TBA_API_KEY", "").strip()


async def _get(path: str) -> Any:
    if not TBA_KEY:
        raise ValueError(
            "TBA_API_KEY is not configured on the server. "
            "Set it in your .env file or OpenShift secret. "
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


async def get_events(year: int) -> list[dict]:
    events = await _get(f"/events/{year}/simple")
    events.sort(key=lambda e: e.get("start_date") or "")
    return events


async def get_event(event_key: str) -> dict:
    return await _get(f"/event/{event_key}/simple")


# ── Live event data ───────────────────────────────────────────────────────────

async def get_event_matches(event_key: str) -> list[dict]:
    """All matches (qual + playoff) for the event, with scores+times when played."""
    return await _get(f"/event/{event_key}/matches")


async def get_event_rankings(event_key: str) -> dict | None:
    """Team rankings for an event. Returns None for events with no rankings yet
    (TBA returns an HTTP 404-ish empty response in that case)."""
    return await _get(f"/event/{event_key}/rankings")


async def get_event_teams(event_key: str) -> list[dict]:
    return await _get(f"/event/{event_key}/teams/simple")


async def get_team(team_key: str) -> dict:
    return await _get(f"/team/{team_key}/simple")


async def get_teams_by_number(team_numbers: list[int]) -> list[dict]:
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
    events = await get_events(year)
    s = search.lower()
    return [e for e in events if s in e.get("key", "").lower() or s in e.get("name", "").lower()]


def normalise_team(tba: dict) -> dict:
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
    return {
        "key":        tba.get("key", ""),
        "name":       tba.get("name", ""),
        "year":       tba.get("year", 0),
        "location":   ", ".join(filter(None, [tba.get("city"), tba.get("state_prov"), tba.get("country")])),
        "start_date": tba.get("start_date"),
        "end_date":   tba.get("end_date"),
        "tba_synced": True,
    }
