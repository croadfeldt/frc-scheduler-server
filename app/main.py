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
FRC Match Scheduler — FastAPI backend

Two-stage scheduling:
  Stage 1: POST /api/generate-abstract       → AbstractSchedule (slot indices, no team numbers)
  Stage 2: POST /api/abstract/{id}/assign    → AssignedSchedule (slot_map + real team numbers)
"""

import asyncio
import json
import logging
import os
from concurrent.futures import ProcessPoolExecutor
from typing import Any, AsyncGenerator

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import (
    AbstractSchedule, AssignedSchedule, AsyncSessionLocal,
    Event, EventTeam, MatchRow, Team, User,
    get_session, init_db,
)
from app.scheduler import run_iterations_worker, run_assignment_worker, run_assignment_chunk
from app import tba as tba_client
from app import frc_events as frc_client
from app.auth import (
    get_current_user, require_auth,
    google_login_url, google_exchange_code,
    apple_login_url, apple_exchange_code,
    upsert_user, create_jwt,
    GOOGLE_CLIENT_ID, APPLE_CLIENT_ID,
)

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ── ProcessPoolExecutor ───────────────────────────────────────────────────────
_cpu_workers_env = int(os.getenv("CPU_WORKERS", "0"))
CPU_WORKERS: int | None = _cpu_workers_env if _cpu_workers_env > 0 else None
_pool: ProcessPoolExecutor | None = None

def get_pool() -> ProcessPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ProcessPoolExecutor(max_workers=CPU_WORKERS)
    return _pool

# Semaphore limits concurrent schedule generations so the ProcessPoolExecutor
# is never completely saturated by a single user, preventing 503s for others.
# With WEB_WORKERS=1, the pool is shared by all requests in this process.
# Allow up to CPU_WORKERS // 3 concurrent jobs (each job gets ~3 workers minimum).
# Minimum 2 so at least two users can generate at once even on small deployments.
_gen_concurrency = max(2, (CPU_WORKERS or os.cpu_count() or 4) // 3)
_generation_semaphore: asyncio.Semaphore | None = None

def get_generation_semaphore() -> asyncio.Semaphore:
    global _generation_semaphore
    if _generation_semaphore is None:
        _generation_semaphore = asyncio.Semaphore(_gen_concurrency)
    return _generation_semaphore


# ── App setup ─────────────────────────────────────────────────────────────────
app = FastAPI(title="FRC Match Scheduler", version="2.0.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    body = None
    try:
        body = await request.body()
        body = body.decode()
    except Exception:
        pass
    log.error("422 Validation error on %s %s — body: %s — errors: %s",
              request.method, request.url.path, body, exc.errors())
    return JSONResponse(status_code=422, content={"detail": exc.errors()})

@app.on_event("startup")
async def startup():
    await init_db()
    get_pool()
    actual = CPU_WORKERS or (os.cpu_count() or 4)
    log.info("Started with %d CPU workers (CPU_WORKERS=%s)", actual, CPU_WORKERS)

@app.on_event("shutdown")
async def shutdown():
    if _pool:
        _pool.shutdown(wait=False)


# ── Static files ──────────────────────────────────────────────────────────────
STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")

@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class EventCreate(BaseModel):
    key:        str = Field(..., max_length=64)
    name:       str = Field(..., max_length=256)
    year:       int
    location:   str | None = None
    start_date: str | None = None
    end_date:   str | None = None


class TeamIn(BaseModel):
    number:      int
    name:        str | None = None
    nickname:    str | None = None
    city:        str | None = None
    state:       str | None = None
    country:     str | None = None
    rookie_year: int | None = None


class AbstractGenerateRequest(BaseModel):
    """Stage 1: generate slot-based abstract schedule."""
    num_teams:        int         = Field(..., ge=6, le=120)
    matches_per_team: int         = Field(6, ge=1, le=50)
    cooldown:         int         = Field(3, ge=1, le=20)
    iterations:       int         = Field(1, ge=1)
    seed:             str | None  = None
    name:             str         = "Abstract Schedule"
    event_id:         int | None  = None
    day_config:       Any         = None

    from pydantic import field_validator

    @field_validator('seed', mode='before')
    @classmethod
    def coerce_empty_seed(cls, v: object) -> object:
        """Coerce empty-string seed to None so int(v, 16) never raises."""
        if isinstance(v, str) and not v.strip():
            return None
        return v


class AssignRequest(BaseModel):
    """Stage 2: assign real team numbers to an abstract schedule."""
    event_id:             int
    abstract_schedule_id: int
    iterations:           int         = Field(1000, ge=1)
    assign_seed:          str | None  = None
    name:                 str         = "Schedule"
    day_config:           Any         = None


# ── Events ────────────────────────────────────────────────────────────────────

@app.get("/api/events")
async def list_events(db: AsyncSession = Depends(get_session)):
    result = await db.execute(select(Event).order_by(Event.year.desc(), Event.name))
    return [
        {"id": e.id, "key": e.key, "name": e.name, "year": e.year,
         "location": e.location, "start_date": e.start_date, "end_date": e.end_date,
         "tba_synced": e.tba_synced}
        for e in result.scalars()
    ]


@app.post("/api/events", status_code=201)
async def create_event(body: EventCreate, db: AsyncSession = Depends(get_session)):
    existing = await db.execute(select(Event).where(Event.key == body.key))
    if existing.scalar_one_or_none():
        raise HTTPException(409, f"Event '{body.key}' already exists")
    event = Event(**body.model_dump())
    db.add(event); await db.commit(); await db.refresh(event)
    return {"id": event.id, "key": event.key, "name": event.name}


@app.get("/api/events/{event_id}")
async def get_event(event_id: int, db: AsyncSession = Depends(get_session)):
    result = await db.execute(
        select(Event)
        .options(selectinload(Event.teams).selectinload(EventTeam.team))
        .where(Event.id == event_id)
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(404, "Event not found")
    return {
        "id": event.id, "key": event.key, "name": event.name, "year": event.year,
        "location": event.location, "tba_synced": event.tba_synced,
        "teams": [
            {"number": et.team.number, "nickname": et.team.nickname, "name": et.team.name}
            for et in sorted(event.teams, key=lambda x: x.team.number)
        ],
    }


@app.delete("/api/events/{event_id}", status_code=204)
async def delete_event(event_id: int, db: AsyncSession = Depends(get_session)):
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    await db.delete(event); await db.commit()


# ── TBA ───────────────────────────────────────────────────────────────────────

@app.get("/api/tba/events/{year}")
async def tba_events(year: int, search: str = Query("", max_length=100)):
    try:
        events = await tba_client.search_events(year, search) if search else await tba_client.get_events(year)
        return [tba_client.normalise_event(e) for e in events]
    except ValueError as e:
        # Missing API key — tell the client clearly
        raise HTTPException(503, str(e))
    except httpx.TimeoutException:
        raise HTTPException(504, "TBA API request timed out — try again in a moment")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            raise HTTPException(502, "TBA API key is invalid or expired. Check TBA_API_KEY in your environment.")
        raise HTTPException(502, f"TBA API returned {e.response.status_code}")
    except Exception as e:
        log.error("TBA events error: %s", e)
        raise HTTPException(502, f"TBA API error: {e}")


@app.get("/api/tba/search_index")
async def tba_search_index():
    """Proxy the TBA search index (all events, all years) for cross-year event search.
    Cached for 6 hours server-side — the index changes rarely."""
    import time
    cache = app.state  # use app.state as a simple namespace
    now = time.monotonic()
    if getattr(cache, '_search_index_data', None) is not None:
        if now - getattr(cache, '_search_index_ts', 0) < 21600:  # 6 hours
            return cache._search_index_data
    try:
        data = await tba_client._get("/search_index")
        result = data.get("events", []) if isinstance(data, dict) else data
        cache._search_index_data = result
        cache._search_index_ts   = now
        return result
    except ValueError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        log.error("TBA search_index error: %s", e)
        raise HTTPException(502, f"TBA API error: {e}")


@app.post("/api/tba/import/{event_key}", status_code=201)
async def tba_import_event(event_key: str, db: AsyncSession = Depends(get_session)):
    try:
        tba_event = await tba_client.get_event(event_key)
        tba_teams = await tba_client.get_event_teams(event_key)
    except ValueError as e:
        raise HTTPException(503, str(e))
    except httpx.TimeoutException:
        raise HTTPException(504, "TBA API request timed out — try again in a moment")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            raise HTTPException(502, "TBA API key is invalid or expired. Check TBA_API_KEY in your environment.")
        if e.response.status_code == 404:
            raise HTTPException(404, f"Event '{event_key}' not found on The Blue Alliance.")
        raise HTTPException(502, f"TBA API returned {e.response.status_code}")
    except Exception as e:
        log.error("TBA import error for %s: %s", event_key, e)
        raise HTTPException(502, f"TBA API error: {e}")

    existing = await db.execute(select(Event).where(Event.key == event_key))
    event = existing.scalar_one_or_none()
    event_data = tba_client.normalise_event(tba_event)
    if event:
        for k, v in event_data.items():
            setattr(event, k, v)
    else:
        event = Event(**event_data)
        db.add(event)
    await db.flush()

    for raw in tba_teams:
        td = tba_client.normalise_team(raw)
        if not td["number"]:
            continue
        t_result = await db.execute(select(Team).where(Team.number == td["number"]))
        team = t_result.scalar_one_or_none()
        if team:
            for k, v in td.items():
                setattr(team, k, v)
        else:
            team = Team(**td)
            db.add(team)
        await db.flush()
        et_result = await db.execute(
            select(EventTeam).where(EventTeam.event_id == event.id, EventTeam.team_id == team.id)
        )
        if not et_result.scalar_one_or_none():
            db.add(EventTeam(event_id=event.id, team_id=team.id))

    await db.commit()
    await db.refresh(event)
    return {"id": event.id, "key": event.key, "name": event.name,
            "teams_imported": len(tba_teams)}


# ── FRC Events API ────────────────────────────────────────────────────────────

@app.get("/api/frc/configured")
@app.get("/api/frc/status")
async def frc_events_status():
    """Return whether FRC Events API credentials are configured."""
    return {"configured": frc_client.is_configured()}


@app.get("/api/frc/events/{year}")
async def frc_events_list(year: int, search: str = Query("", max_length=100)):
    """List/search events from the FRC Events API for a given year."""
    try:
        events = await frc_client.search_events(year, search) if search else await frc_client.get_events(year)
        return [frc_client.normalise_event(e, year) for e in events]
    except ValueError as e:
        raise HTTPException(503, str(e))
    except httpx.TimeoutException:
        raise HTTPException(504, "FRC Events API request timed out — try again in a moment")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            raise HTTPException(502, "FRC Events credentials are invalid. Check FRC_EVENTS_USERNAME and FRC_EVENTS_TOKEN.")
        raise HTTPException(502, f"FRC Events API returned {e.response.status_code}")
    except Exception as e:
        log.error("FRC Events list error: %s", e)
        raise HTTPException(502, f"FRC Events API error: {e}")


@app.post("/api/frc/import/{year}/{event_code}", status_code=201)
async def frc_import_event(year: int, event_code: str, db: AsyncSession = Depends(get_session)):
    """Import an event and its teams from the FRC Events API."""
    try:
        frc_event = await frc_client.get_event(year, event_code)
        if not frc_event:
            raise HTTPException(404, f"Event '{event_code}' ({year}) not found on FRC Events API.")
        frc_teams = await frc_client.get_event_teams(year, event_code)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(503, str(e))
    except httpx.TimeoutException:
        raise HTTPException(504, "FRC Events API request timed out — try again in a moment")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            raise HTTPException(502, "FRC Events credentials are invalid. Check FRC_EVENTS_USERNAME and FRC_EVENTS_TOKEN.")
        if e.response.status_code == 404:
            raise HTTPException(404, f"Event '{event_code}' ({year}) not found on FRC Events API.")
        raise HTTPException(502, f"FRC Events API returned {e.response.status_code}")
    except Exception as e:
        log.error("FRC Events import error for %s/%s: %s", year, event_code, e)
        raise HTTPException(502, f"FRC Events API error: {e}")

    event_data = frc_client.normalise_event(frc_event, year)
    key = event_data["key"]
    event_data.pop("_frc_code", None)

    existing = await db.execute(select(Event).where(Event.key == key))
    event = existing.scalar_one_or_none()
    if event:
        for k, v in event_data.items():
            setattr(event, k, v)
    else:
        event = Event(**event_data)
        db.add(event)
    await db.flush()

    for raw in frc_teams:
        td = frc_client.normalise_team(raw)
        if not td["number"]:
            continue
        t_result = await db.execute(select(Team).where(Team.number == td["number"]))
        team = t_result.scalar_one_or_none()
        if team:
            for k, v in td.items():
                if v is not None:
                    setattr(team, k, v)
        else:
            team = Team(**td)
            db.add(team)
        await db.flush()
        et_result = await db.execute(
            select(EventTeam).where(EventTeam.event_id == event.id, EventTeam.team_id == team.id)
        )
        if not et_result.scalar_one_or_none():
            db.add(EventTeam(event_id=event.id, team_id=team.id))

    await db.commit()
    await db.refresh(event)
    return {"id": event.id, "key": key, "name": event.name,
            "teams_imported": len(frc_teams)}


# ── Teams ─────────────────────────────────────────────────────────────────────

@app.get("/api/events/{event_id}/teams")
async def list_event_teams(event_id: int, db: AsyncSession = Depends(get_session)):
    result = await db.execute(
        select(EventTeam).options(selectinload(EventTeam.team))
        .where(EventTeam.event_id == event_id)
    )
    return [
        {"number": et.team.number, "nickname": et.team.nickname,
         "name": et.team.name, "city": et.team.city, "state": et.team.state}
        for et in sorted(result.scalars(), key=lambda x: x.team.number)
    ]


@app.post("/api/events/{event_id}/teams", status_code=201)
async def add_team_to_event(event_id: int, body: TeamIn, db: AsyncSession = Depends(get_session)):
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    t_result = await db.execute(select(Team).where(Team.number == body.number))
    team = t_result.scalar_one_or_none()
    if team:
        for k, v in body.model_dump(exclude_none=True).items():
            setattr(team, k, v)
    else:
        team = Team(**body.model_dump())
        db.add(team)
    await db.flush()
    et_result = await db.execute(
        select(EventTeam).where(EventTeam.event_id == event_id, EventTeam.team_id == team.id)
    )
    if not et_result.scalar_one_or_none():
        db.add(EventTeam(event_id=event_id, team_id=team.id))
        await db.commit()
        return {"added": True, "number": body.number}
    return {"added": False, "number": body.number, "reason": "already in event"}


@app.delete("/api/events/{event_id}/teams/{team_number}", status_code=204)
async def remove_team(event_id: int, team_number: int, db: AsyncSession = Depends(get_session)):
    t = await db.execute(select(Team).where(Team.number == team_number))
    team = t.scalar_one_or_none()
    if not team:
        raise HTTPException(404, "Team not found")
    et = await db.execute(
        select(EventTeam).where(EventTeam.event_id == event_id, EventTeam.team_id == team.id)
    )
    link = et.scalar_one_or_none()
    if not link:
        raise HTTPException(404, "Team not in event")
    await db.delete(link); await db.commit()


# ── Stage 1: Abstract Schedule Generation ────────────────────────────────────


@app.post("/api/generate-abstract")
async def generate_abstract(
    body: AbstractGenerateRequest,
    current_user: dict | None = Depends(get_current_user),
):
    """
    Stage 1 — Generate a slot-based abstract schedule.
    Streams keepalive pings while computing, then sends the done event.
    The DB session is opened only for the insert — not held open during the
    long-running worker — so it doesn't block the connection pool.
    """
    loop = asyncio.get_event_loop()
    pool = get_pool()
    _seed_int = int(body.seed, 16) if body.seed else None

    async def stream() -> AsyncGenerator[str, None]:
        # Flush headers immediately
        yield ": connected\n\n"

        # Run the worker, sending a ping every 5s to keep the connection alive.
        # Acquire the generation semaphore to prevent overloading the process pool.
        sem = get_generation_semaphore()
        if sem.locked() and sem._value == 0:  # type: ignore[attr-defined]
            yield f"data: {json.dumps({'type':'error','message':'Server busy — please retry in a moment'})}\n\n"
            return

        async with sem:
            worker_task = asyncio.ensure_future(
                loop.run_in_executor(
                    pool, run_iterations_worker,
                    (body.num_teams, body.matches_per_team, body.cooldown, 1, 0, _seed_int)
                )
            )
            while not worker_task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(worker_task), timeout=5.0)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                except Exception:
                    break  # worker finished (success or error)

        # Worker finished — get result
        try:
            result = worker_task.result()
        except Exception as e:
            log.error("Stage 1 worker error: %s", e)
            yield f"data: {json.dumps({'type':'error','message':str(e)})}\n\n"
            return

        if not result or not result.get("matches"):
            yield f"data: {json.dumps({'type':'error','message':'No schedule generated'})}\n\n"
            return

        # Save to DB — open a short-lived session only for this insert
        try:
            async with AsyncSessionLocal() as db:
                sched = AbstractSchedule(
                    event_id=body.event_id,
                    name=body.name,
                    num_teams=body.num_teams,
                    matches_per_team=body.matches_per_team,
                    cooldown=body.cooldown,
                    seed=body.seed,
                    iterations_run=1,
                    best_iteration=0,
                    score=result["score"],
                    created_by=current_user["sub"] if current_user else None,
                    matches=result["matches"],
                    surrogate_count=result["surrogate_count"],
                    round_boundaries={str(k): v for k, v in result["round_boundaries"].items()},
                    day_config=body.day_config,
                )
                db.add(sched)
                await db.commit()
                await db.refresh(sched)
        except Exception as e:
            log.error("Stage 1 DB error: %s", e)
            yield f"data: {json.dumps({'type':'error','message':'Database error: ' + str(e)})}\n\n"
            return

        yield f"data: {json.dumps({'type':'done','abstract_schedule_id':sched.id,'score':result['score'],'pct':100})}\n\n"
        yield ": end\n\n"

    return StreamingResponse(
        stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                 "Connection": "keep-alive"},
    )


@app.get("/api/abstract-schedules")
async def list_abstract_schedules(
    event_id: int | None = Query(None),
    db: AsyncSession = Depends(get_session)
):
    q = select(AbstractSchedule).order_by(AbstractSchedule.created_at.desc())
    if event_id is not None:
        q = q.where(AbstractSchedule.event_id == event_id)
    result = await db.execute(q)
    return [
        {"id": s.id, "name": s.name, "event_id": s.event_id,
         "num_teams": s.num_teams, "matches_per_team": s.matches_per_team,
         "iterations_run": s.iterations_run, "score": s.score,
         "created_at": s.created_at.isoformat()}
        for s in result.scalars()
    ]


@app.get("/api/abstract-schedules/{schedule_id}")
async def get_abstract_schedule(schedule_id: int, db: AsyncSession = Depends(get_session)):
    sched = await db.get(AbstractSchedule, schedule_id)
    if not sched:
        raise HTTPException(404, "Abstract schedule not found")
    return {
        "id": sched.id, "name": sched.name, "event_id": sched.event_id,
        "num_teams": sched.num_teams, "matches_per_team": sched.matches_per_team,
        "cooldown": sched.cooldown, "seed": sched.seed,
        "iterations_run": sched.iterations_run,
        "score": sched.score, "matches": sched.matches,
        "surrogate_count": sched.surrogate_count,
        "round_boundaries": sched.round_boundaries,
        "day_config": sched.day_config,
        "created_by": sched.created_by,
        "created_at": sched.created_at.isoformat(),
    }


@app.delete("/api/abstract-schedules/{schedule_id}", status_code=204)
async def delete_abstract_schedule(schedule_id: int, db: AsyncSession = Depends(get_session)):
    sched = await db.get(AbstractSchedule, schedule_id)
    if not sched:
        raise HTTPException(404, "Abstract schedule not found")
    await db.delete(sched); await db.commit()


# ── Stage 2: Team Assignment ──────────────────────────────────────────────────

@app.post("/api/abstract-schedules/{abstract_id}/assign")
async def assign_teams(
    abstract_id: int,
    body: AssignRequest,
    current_user: dict | None = Depends(get_current_user),
):
    """
    Stage 2 — Assign real team numbers to an abstract schedule.
    Streams SSE progress. Final event carries assigned_schedule_id.
    The DB session is opened only for reads before the stream and for the
    final write after workers finish — never held open during computation.
    """
    # Short-lived read session — closed before the stream starts
    async with AsyncSessionLocal() as db:
        abstract = await db.get(AbstractSchedule, abstract_id)
        if not abstract:
            raise HTTPException(404, "Abstract schedule not found")

        result_q = await db.execute(
            select(EventTeam).options(selectinload(EventTeam.team))
            .where(EventTeam.event_id == body.event_id)
        )
        event_teams = list(result_q.scalars())
        if not event_teams:
            raise HTTPException(400, "Event has no teams")
        if len(event_teams) != abstract.num_teams:
            raise HTTPException(400,
                f"Event has {len(event_teams)} teams but abstract schedule was built for {abstract.num_teams}")

        team_numbers    = sorted(et.team.number for et in event_teams)
        abstract_matches = abstract.matches
        abstract_cooldown = abstract.cooldown
        abstract_num_teams = abstract.num_teams

    pool = get_pool()
    loop = asyncio.get_event_loop()
    iterations = body.iterations

    async def stream() -> AsyncGenerator[str, None]:
        yield ": connected\n\n"
        await asyncio.sleep(0)

        sem = get_generation_semaphore()
        if sem.locked() and sem._value == 0:  # type: ignore[attr-defined]
            yield f"data: {json.dumps({'type':'error','message':'Server busy — please retry in a moment'})}\n\n"
            return

        actual_workers = CPU_WORKERS or (os.cpu_count() or 4)
        n_workers = min(iterations, actual_workers)
        _aseed_int = int(body.assign_seed, 16) if body.assign_seed else None

        # Split iterations into chunks per worker so progress fires incrementally.
        # Target ~20 progress updates total: chunk_size = total / (workers * 20).
        # Minimum chunk size of 10 to avoid excessive task overhead.
        chunk_size = max(10, iterations // (n_workers * 20))

        # Build list of (worker_id, seed, chunk_iters) for all chunks across all workers
        # Each worker gets ceil(its_share / chunk_size) chunks
        base = iterations // n_workers
        remainder = iterations % n_workers
        all_chunks: list[tuple[int, int | None, int]] = []  # (worker_id, seed, iters)
        for w in range(n_workers):
            w_total = base + (1 if w < remainder else 0)
            _aw_seed = (_aseed_int ^ w) if _aseed_int is not None else None
            remaining = w_total
            chunk_idx = 0
            while remaining > 0:
                c_iters = min(chunk_size, remaining)
                # Vary seed per chunk so each chunk explores different permutations
                c_seed = (_aw_seed ^ (chunk_idx << 16)) if _aw_seed is not None else None
                all_chunks.append((w, c_seed, c_iters))
                remaining -= c_iters
                chunk_idx += 1

        total_done = 0
        best_result = None

        async with sem:
            # Submit all chunks as separate executor tasks
            pending: set[asyncio.Task] = set()
            chunk_iters_map: dict[asyncio.Task, int] = {}
            for (w, c_seed, c_iters) in all_chunks:
                task = asyncio.ensure_future(
                    loop.run_in_executor(pool, run_assignment_chunk,
                        (abstract_matches, abstract_num_teams, team_numbers,
                         abstract_cooldown, c_iters, w, c_seed))
                )
                chunk_iters_map[task] = c_iters
                pending.add(task)

            _last_ping2 = asyncio.get_event_loop().time()
            while pending:
                done_set, pending = await asyncio.wait(pending, timeout=0.5,
                                                       return_when=asyncio.FIRST_COMPLETED)
                _now2 = asyncio.get_event_loop().time()
                if _now2 - _last_ping2 >= 15:
                    yield ": ping\n\n"
                    _last_ping2 = _now2
                for task in done_set:
                    try:
                        result = task.result()
                        total_done += chunk_iters_map[task]
                        if best_result is None or result["score"] > best_result["score"]:
                            best_result = result
                    except Exception as e:
                        log.error("Stage 2 chunk error: %s", e)
                        total_done += chunk_iters_map[task]
                pct = min(99, round(total_done / iterations * 100))
                best_score = best_result["score"] if best_result else None
                yield f"data: {json.dumps({'type':'progress','done':total_done,'total':iterations,'pct':pct,'score':best_score})}\n\n"

        if not best_result or not best_result.get("slot_map"):
            yield f"data: {json.dumps({'type':'error','message':'Assignment failed'})}\n\n"
            return

        # Always insert a new record — each assignment is a new version.
        # History is preserved so the user can revert to any previous assignment.
        # Open a fresh short-lived session for the write — not held during workers.
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(AssignedSchedule)
                .where(AssignedSchedule.event_id == body.event_id)
                .values(is_active=False)
            )
            assigned = AssignedSchedule(
                abstract_schedule_id=abstract_id,
                event_id=body.event_id,
                name=body.name,
                is_active=True,
                slot_map=best_result["slot_map"],
                day_config=body.day_config,
                assign_seed=body.assign_seed,
                created_by=current_user["sub"] if current_user else None,
            )
            db.add(assigned)
            await db.flush()

            # Denormalise into MatchRow using slot_map to resolve real team numbers
            slot_map = {int(k): v for k, v in best_result["slot_map"].items()}
            for i, m in enumerate(abstract_matches, start=1):
                db.add(MatchRow(
                    assigned_schedule_id=assigned.id, match_num=i,
                    red1=slot_map[m["red"][0]], red2=slot_map[m["red"][1]], red3=slot_map[m["red"][2]],
                    blue1=slot_map[m["blue"][0]], blue2=slot_map[m["blue"][1]], blue3=slot_map[m["blue"][2]],
                    red1_surrogate=m["red_surrogate"][0], red2_surrogate=m["red_surrogate"][1],
                    red3_surrogate=m["red_surrogate"][2], blue1_surrogate=m["blue_surrogate"][0],
                    blue2_surrogate=m["blue_surrogate"][1], blue3_surrogate=m["blue_surrogate"][2],
                ))
            await db.commit()

        yield f"data: {json.dumps({'type':'done','assigned_schedule_id':assigned.id,'score':best_result['score'],'total':iterations,'pct':100})}\n\n"
        yield ": end\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no","Connection":"keep-alive"})


# ── Assigned Schedule retrieval ───────────────────────────────────────────────

@app.get("/api/events/{event_id}/assigned-schedules")
async def list_assigned_schedules(event_id: int, db: AsyncSession = Depends(get_session)):
    result = await db.execute(
        select(AssignedSchedule)
        .options(selectinload(AssignedSchedule.abstract_schedule))
        .where(AssignedSchedule.event_id == event_id)
        .order_by(AssignedSchedule.created_at.desc())
    )
    return [
        {
            "id":                   s.id,
            "name":                 s.name,
            "is_active":            s.is_active,
            "abstract_schedule_id": s.abstract_schedule_id,
            "num_teams":            s.abstract_schedule.num_teams,
            "matches_per_team":     s.abstract_schedule.matches_per_team,
            "cooldown":             s.abstract_schedule.cooldown,
            "created_at":           s.created_at.isoformat(),
        }
        for s in result.scalars()
    ]


@app.get("/api/assigned-schedules/{schedule_id}")
async def get_assigned_schedule(schedule_id: int, db: AsyncSession = Depends(get_session)):
    result = await db.execute(
        select(AssignedSchedule)
        .options(selectinload(AssignedSchedule.abstract_schedule))
        .where(AssignedSchedule.id == schedule_id)
    )
    assigned = result.scalar_one_or_none()
    if not assigned:
        raise HTTPException(404, "Assigned schedule not found")
    abstract = assigned.abstract_schedule
    slot_map = {int(k): v for k, v in assigned.slot_map.items()}

    # Resolve matches: replace slot indices with real team numbers
    resolved_matches = []
    for m in abstract.matches:
        resolved_matches.append({
            "red":           [slot_map[s] for s in m["red"]],
            "blue":          [slot_map[s] for s in m["blue"]],
            "red_surrogate": m["red_surrogate"],
            "blue_surrogate": m["blue_surrogate"],
        })

    return {
        "id":                   assigned.id,
        "name":                 assigned.name,
        "is_active":            assigned.is_active,
        "event_id":             assigned.event_id,
        "abstract_schedule_id": assigned.abstract_schedule_id,
        "num_teams":            abstract.num_teams,
        "matches_per_team":     abstract.matches_per_team,
        "cooldown":             abstract.cooldown,
        "seed":                 abstract.seed,
        "assign_seed":          assigned.assign_seed,
        "created_by":           assigned.created_by,
        "slot_map":             assigned.slot_map,
        "matches":              resolved_matches,
        "surrogate_count":      abstract.surrogate_count,
        "round_boundaries":     abstract.round_boundaries,
        "day_config":           assigned.day_config,
        "created_at":           assigned.created_at.isoformat(),
    }


@app.post("/api/assigned-schedules/{schedule_id}/activate", status_code=200)
async def activate_assigned_schedule(schedule_id: int, db: AsyncSession = Depends(get_session)):
    assigned = await db.get(AssignedSchedule, schedule_id)
    if not assigned:
        raise HTTPException(404, "Assigned schedule not found")
    await db.execute(
        update(AssignedSchedule)
        .where(AssignedSchedule.event_id == assigned.event_id)
        .values(is_active=False)
    )
    assigned.is_active = True
    await db.commit()
    return {"activated": schedule_id}


@app.delete("/api/assigned-schedules/{schedule_id}", status_code=204)
async def delete_assigned_schedule(
    schedule_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: dict | None = Depends(get_current_user),
):
    assigned = await db.get(AssignedSchedule, schedule_id)
    if not assigned:
        raise HTTPException(404, "Assigned schedule not found")
    if assigned.created_by and (not current_user or current_user.get("sub") != assigned.created_by):
        raise HTTPException(403, "You do not own this schedule")
    await db.delete(assigned); await db.commit()


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    actual_workers = CPU_WORKERS or os.cpu_count() or 1
    return {"status": "ok", "cpu_workers": actual_workers}


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.get("/auth/google/login")
async def google_login(state: str = ""):
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(501, "Google OAuth not configured (GOOGLE_CLIENT_ID missing)")
    return RedirectResponse(google_login_url(state))


@app.get("/auth/google/callback")
async def google_callback(code: str, db: AsyncSession = Depends(get_session)):
    try:
        info = await google_exchange_code(code)
    except Exception as e:
        raise HTTPException(400, f"Google OAuth failed: {e}")
    user = await upsert_user(
        sub=f"google:{info['sub']}", provider="google",
        email=info.get("email"), name=info.get("name"), db=db,
    )
    token = create_jwt(user.id, user.sub, "google", user.email)
    from fastapi.responses import HTMLResponse
    return HTMLResponse(f"""<!doctype html><html><body><script>
window.opener ? window.opener.postMessage({{token:'{token}'}}, '*') : (localStorage.setItem('frc_token','{token}'), window.location='/');
window.close();
</script></body></html>""")


@app.get("/auth/apple/login")
async def apple_login(state: str = ""):
    if not APPLE_CLIENT_ID:
        raise HTTPException(501, "Apple OAuth not configured (APPLE_CLIENT_ID missing)")
    return RedirectResponse(apple_login_url(state))


@app.post("/auth/apple/callback")
async def apple_callback(
    request: Request,
    db: AsyncSession = Depends(get_session),
):
    """Apple uses form_post so we need to parse form data."""
    form = await request.form()
    code = form.get("code")
    id_token_raw = form.get("id_token")
    if not code:
        raise HTTPException(400, "No code in Apple callback")
    try:
        info = await apple_exchange_code(str(code), str(id_token_raw) if id_token_raw else None)
    except Exception as e:
        raise HTTPException(400, f"Apple OAuth failed: {e}")
    # Apple may send user name only on first login via form field
    user_json = form.get("user")
    name = None
    if user_json:
        import json as _json
        try:
            u = _json.loads(str(user_json))
            n = u.get("name", {})
            name = f"{n.get('firstName','')} {n.get('lastName','')}".strip() or None
        except Exception:
            pass
    user = await upsert_user(
        sub=f"apple:{info['sub']}", provider="apple",
        email=info.get("email"), name=name, db=db,
    )
    token = create_jwt(user.id, user.sub, "apple", user.email)
    from fastapi.responses import HTMLResponse
    return HTMLResponse(f"""<!doctype html><html><body><script>
window.opener ? window.opener.postMessage({{token:'{token}'}}, '*') : (localStorage.setItem('frc_token','{token}'), window.location='/');
window.close();
</script></body></html>""")


@app.get("/auth/me")
async def auth_me(current_user: dict | None = Depends(get_current_user)):
    """Return current user info from JWT, or null if not authenticated."""
    if not current_user:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "sub":      current_user.get("sub"),
        "email":    current_user.get("email"),
        "provider": current_user.get("provider"),
        "uid":      current_user.get("uid"),
    }


@app.get("/auth/providers")
async def auth_providers():
    """Return which OAuth providers are configured."""
    return {
        "google": bool(GOOGLE_CLIENT_ID),
        "apple":  bool(APPLE_CLIENT_ID),
    }


# ── Duplicate schedule ────────────────────────────────────────────────────────

@app.post("/api/assigned-schedules/{schedule_id}/duplicate", status_code=201)
async def duplicate_assigned_schedule(
    schedule_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: dict | None = Depends(get_current_user),
):
    """
    Duplicate an assigned schedule — anyone can do this.
    Creates a new AssignedSchedule (and a copy of its AbstractSchedule) owned
    by the requesting user.  The original is not modified.
    """
    result = await db.execute(
        select(AssignedSchedule)
        .options(selectinload(AssignedSchedule.abstract_schedule))
        .where(AssignedSchedule.id == schedule_id)
    )
    src = result.scalar_one_or_none()
    if not src:
        raise HTTPException(404, "Schedule not found")

    abs_src = src.abstract_schedule

    # Duplicate abstract schedule
    new_abs = AbstractSchedule(
        event_id=abs_src.event_id,
        name=f"{abs_src.name} (copy)",
        num_teams=abs_src.num_teams,
        matches_per_team=abs_src.matches_per_team,
        cooldown=abs_src.cooldown,
        seed=abs_src.seed,
        iterations_run=abs_src.iterations_run,
        best_iteration=abs_src.best_iteration,
        score=abs_src.score,
        matches=abs_src.matches,
        surrogate_count=abs_src.surrogate_count,
        round_boundaries=abs_src.round_boundaries,
        day_config=abs_src.day_config,
        created_by=current_user["sub"] if current_user else None,
    )
    db.add(new_abs)
    await db.flush()

    # Duplicate assigned schedule
    new_asgn = AssignedSchedule(
        abstract_schedule_id=new_abs.id,
        event_id=src.event_id,
        name=f"{src.name} (copy)",
        is_active=False,
        slot_map=src.slot_map,
        day_config=src.day_config,
        assign_seed=src.assign_seed,
        created_by=current_user["sub"] if current_user else None,
    )
    db.add(new_asgn)
    await db.flush()

    # Copy match rows
    mr_result = await db.execute(
        select(MatchRow).where(MatchRow.assigned_schedule_id == schedule_id)
    )
    for mr in mr_result.scalars():
        db.add(MatchRow(
            assigned_schedule_id=new_asgn.id, match_num=mr.match_num,
            red1=mr.red1, red2=mr.red2, red3=mr.red3,
            blue1=mr.blue1, blue2=mr.blue2, blue3=mr.blue3,
            red1_surrogate=mr.red1_surrogate, red2_surrogate=mr.red2_surrogate,
            red3_surrogate=mr.red3_surrogate,
            blue1_surrogate=mr.blue1_surrogate, blue2_surrogate=mr.blue2_surrogate,
            blue3_surrogate=mr.blue3_surrogate,
        ))

    await db.commit()
    return {"id": new_asgn.id, "abstract_schedule_id": new_abs.id, "name": new_asgn.name}


# ── Schedule commit log ───────────────────────────────────────────────────────

class CommitLogEntry(BaseModel):
    """Structured completion log posted by the browser after committing a schedule."""
    event:      str                      # always "schedule_committed"
    timestamp:  str
    url:        str | None               = None
    event_info: dict[str, Any] | None    = None
    schedule:   dict[str, Any]
    parameters: dict[str, Any]
    day_config: dict[str, Any] | None    = None
    teams:      list[int]                = []
    match_count:      int | None         = None
    surrogate_count:  dict[str, Any] | None = None
    stats:      dict[str, Any] | None    = None


@app.post("/api/log-commit", status_code=204)
async def log_commit(
    body: CommitLogEntry,
    current_user: dict | None = Depends(get_current_user),
):
    """
    Receives the structured completion payload from the browser after a schedule
    is committed as active. Logs it server-side at INFO level so it appears in
    container stdout / log aggregation alongside the rest of the uvicorn logs.
    """
    log.info(
        "SCHEDULE_COMMITTED user=%s event=%s schedule_id=%s teams=%d matches=%s seed=%s assign_seed=%s",
        (current_user or {}).get("sub", "anonymous"),
        body.event_info.get("key") if body.event_info else "none",
        body.schedule.get("assigned_schedule_id"),
        len(body.teams),
        body.match_count,
        body.parameters.get("seed"),
        body.parameters.get("assign_seed"),
    )
    # Full structured payload at DEBUG level for detailed post-event analysis
    log.debug("SCHEDULE_COMMITTED_DETAIL %s", body.model_dump_json())

