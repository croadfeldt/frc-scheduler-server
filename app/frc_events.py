# SPDX-License-Identifier: GPL-3.0-or-later
# FRC Match Scheduler
# Copyright (C) 2025 FRC Match Scheduler Contributors
#
# NOTE: This file was substantially generated with the assistance of Claude,
# an AI assistant by Anthropic, and reviewed/modified by human contributors.
# See LICENSE for full terms.

"""
FIRST FRC Events API client — https://frc-api-docs.firstinspires.org/
Base: https://frc-api.firstinspires.org/v3.0/
Authentication: HTTP Basic (base64 username:token)
Register at: https://frc-events.firstinspires.org/services/API
"""

import os
import base64
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

FRC_BASE     = "https://frc-api.firstinspires.org/v3.0"
FRC_USERNAME = os.getenv("FRC_EVENTS_USERNAME", "").strip()
FRC_TOKEN    = os.getenv("FRC_EVENTS_TOKEN", "").strip()


def _auth_header() -> str:
    if not FRC_USERNAME or not FRC_TOKEN:
        raise ValueError(
            "FRC Events API credentials are not configured. "
            "Set FRC_EVENTS_USERNAME and FRC_EVENTS_TOKEN in your environment. "
            "Register free at https://frc-events.firstinspires.org/services/API"
        )
    return "Basic " + base64.b64encode(f"{FRC_USERNAME}:{FRC_TOKEN}".encode()).decode()


async def _get(path: str, params: dict | None = None) -> Any:
    async with httpx.AsyncClient(
        base_url=FRC_BASE,
        headers={"Authorization": _auth_header(), "Accept": "application/json"},
        timeout=15.0,
    ) as client:
        resp = await client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()


async def get_events(year: int) -> list[dict]:
    data = await _get(f"/{year}/events")
    return data.get("Events", [])


async def get_event(year: int, event_code: str) -> dict | None:
    data = await _get(f"/{year}/events", params={"eventCode": event_code.upper()})
    events = data.get("Events", [])
    return events[0] if events else None


async def get_event_teams(year: int, event_code: str) -> list[dict]:
    teams: list[dict] = []
    page = 1
    while True:
        data = await _get(f"/{year}/teams", params={
            "eventCode": event_code.upper(),
            "page": page,
        })
        page_teams = data.get("teams", [])
        if not page_teams:
            break
        teams.extend(page_teams)
        if len(page_teams) < 65:
            break
        page += 1
    return teams


async def search_events(year: int, search: str) -> list[dict]:
    events = await get_events(year)
    s = search.lower()
    return [e for e in events if s in e.get("code", "").lower() or s in e.get("name", "").lower()]


def is_configured() -> bool:
    return bool(FRC_USERNAME and FRC_TOKEN)


def normalise_team(frc: dict) -> dict:
    return {
        "number":      frc.get("teamNumber", 0),
        "name":        frc.get("nameFull") or frc.get("nameShort"),
        "nickname":    frc.get("nameShort"),
        "city":        frc.get("city"),
        "state":       frc.get("stateProv"),
        "country":     frc.get("country"),
        "rookie_year": frc.get("rookieYear"),
    }


def normalise_event(frc: dict, year: int) -> dict:
    code = frc.get("code", "")
    key = f"{year}{code.lower()}"
    location = ", ".join(filter(None, [
        frc.get("city"),
        frc.get("stateprov") or frc.get("stateProv"),
        frc.get("country"),
    ]))
    return {
        "key":        key,
        "name":       frc.get("name", ""),
        "year":       year,
        "location":   location,
        "start_date": frc.get("dateStart", "")[:10] if frc.get("dateStart") else None,
        "end_date":   frc.get("dateEnd", "")[:10] if frc.get("dateEnd") else None,
        "tba_synced": True,
        "_frc_code":  code,
    }
