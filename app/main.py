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

from fastapi import Depends, FastAPI, HTTPException, Query
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
from app.scheduler import run_iterations_worker, run_assignment_worker
from app import tba as tba_client
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


# ── App setup ─────────────────────────────────────────────────────────────────
app = FastAPI(title="FRC Match Scheduler", version="2.0.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

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
    matches_per_team: int         = Field(6, ge=1, le=20)
    cooldown:         int         = Field(3, ge=1, le=20)
    iterations:       int         = Field(1, ge=1)   # Stage 1 is single deterministic pass
    seed:             str | None  = None              # hex seed for reproducibility
    name:             str         = "Abstract Schedule"
    event_id:         int | None  = None              # optional — link to an event


class AssignRequest(BaseModel):
    """Stage 2: assign real team numbers to an abstract schedule."""
    event_id:             int
    abstract_schedule_id: int
    iterations:           int         = Field(500, ge=1)
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
    except Exception as e:
        raise HTTPException(502, f"TBA API error: {e}")


@app.post("/api/tba/import/{event_key}", status_code=201)
async def tba_import_event(event_key: str, db: AsyncSession = Depends(get_session)):
    try:
        tba_event = await tba_client.get_event(event_key)
        tba_teams = await tba_client.get_event_teams(event_key)
    except Exception as e:
        msg = str(e)
        if not tba_client.TBA_KEY:
            detail = "TBA_API_KEY is not set."
        elif "401" in msg:
            detail = "TBA API key is invalid or expired."
        elif "404" in msg:
            detail = f"Event '{event_key}' not found on The Blue Alliance."
        else:
            detail = f"TBA API error: {msg}"
        raise HTTPException(502, detail)

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
    db: AsyncSession = Depends(get_session),
    current_user: dict | None = Depends(get_current_user),
):
    """
    Stage 1 — Generate a slot-based abstract schedule (no team numbers).
    Streams SSE progress. Final event carries abstract_schedule_id.
    """
    pool = get_pool()
    loop = asyncio.get_event_loop()
    iterations = body.iterations

    async def stream() -> AsyncGenerator[str, None]:
        actual_workers = CPU_WORKERS or (os.cpu_count() or 4)
        n_workers = min(iterations, actual_workers)
        base = iterations // n_workers
        remainder = iterations % n_workers

        tasks: list[asyncio.Task] = []
        worker_iters: list[int] = []
        for w in range(n_workers):
            w_iters = base + (1 if w < remainder else 0)
            worker_iters.append(w_iters)
            _seed_int = int(body.seed, 16) if body.seed else None
            _w_seed = (_seed_int ^ w) if _seed_int is not None else None
            task = asyncio.ensure_future(
                loop.run_in_executor(pool, run_iterations_worker,
                    (body.num_teams, body.matches_per_team, body.cooldown, w_iters, w, _w_seed))
            )
            tasks.append(task)

        total_done = 0
        best_result = None
        pending = set(tasks)

        while pending:
            done_set, pending = await asyncio.wait(pending, timeout=0.2,
                                                   return_when=asyncio.FIRST_COMPLETED)
            for task in done_set:
                try:
                    result = task.result()
                    total_done += worker_iters[tasks.index(task)]
                    if best_result is None or result["score"] > best_result["score"]:
                        best_result = result
                except Exception as e:
                    log.error("Stage 1 worker error: %s", e)
                    total_done += worker_iters[tasks.index(task)]
            pct = min(99, round(total_done / iterations * 100))
            yield f"data: {json.dumps({'type':'progress','done':total_done,'total':iterations,'pct':pct})}\n\n"

        if not best_result or not best_result.get("matches"):
            yield f"data: {json.dumps({'type':'error','message':'No schedule generated'})}\n\n"
            return

        sched = AbstractSchedule(
            event_id=body.event_id,
            name=body.name,
            num_teams=body.num_teams,
            matches_per_team=body.matches_per_team,
            cooldown=body.cooldown,
            seed=body.seed,
            iterations_run=iterations,
            best_iteration=best_result.get("worker_id", 0),
            score=best_result["score"],
            created_by=current_user["sub"] if current_user else None,
            matches=best_result["matches"],
            surrogate_count=best_result["surrogate_count"],
            round_boundaries={str(k): v for k, v in best_result["round_boundaries"].items()},
        )
        db.add(sched)
        await db.commit()
        await db.refresh(sched)

        yield f"data: {json.dumps({'type':'done','abstract_schedule_id':sched.id,'score':best_result['score'],'total':iterations,'pct':100})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})


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
    db: AsyncSession = Depends(get_session),
    current_user: dict | None = Depends(get_current_user),
):
    """
    Stage 2 — Assign real team numbers to an abstract schedule.
    Streams SSE progress. Final event carries assigned_schedule_id.
    """
    abstract = await db.get(AbstractSchedule, abstract_id)
    if not abstract:
        raise HTTPException(404, "Abstract schedule not found")

    # Load event teams
    result = await db.execute(
        select(EventTeam).options(selectinload(EventTeam.team))
        .where(EventTeam.event_id == body.event_id)
    )
    event_teams = list(result.scalars())
    if not event_teams:
        raise HTTPException(400, "Event has no teams")
    if len(event_teams) != abstract.num_teams:
        raise HTTPException(400,
            f"Event has {len(event_teams)} teams but abstract schedule was built for {abstract.num_teams}")

    team_numbers = sorted(et.team.number for et in event_teams)
    abstract_matches = abstract.matches
    pool = get_pool()
    loop = asyncio.get_event_loop()
    iterations = body.iterations

    async def stream() -> AsyncGenerator[str, None]:
        actual_workers = CPU_WORKERS or (os.cpu_count() or 4)
        n_workers = min(iterations, actual_workers)
        base = iterations // n_workers
        remainder = iterations % n_workers

        tasks: list[asyncio.Task] = []
        worker_iters: list[int] = []
        for w in range(n_workers):
            w_iters = base + (1 if w < remainder else 0)
            worker_iters.append(w_iters)
            _aseed_int = int(body.assign_seed, 16) if body.assign_seed else None
            _aw_seed = (_aseed_int ^ w) if _aseed_int is not None else None
            task = asyncio.ensure_future(
                loop.run_in_executor(pool, run_assignment_worker,
                    (abstract_matches, abstract.num_teams, team_numbers,
                     abstract.cooldown, w_iters, w, _aw_seed))
            )
            tasks.append(task)

        total_done = 0
        best_result = None
        pending = set(tasks)

        while pending:
            done_set, pending = await asyncio.wait(pending, timeout=0.2,
                                                   return_when=asyncio.FIRST_COMPLETED)
            for task in done_set:
                try:
                    result = task.result()
                    total_done += worker_iters[tasks.index(task)]
                    if best_result is None or result["score"] > best_result["score"]:
                        best_result = result
                except Exception as e:
                    log.error("Stage 2 worker error: %s", e)
                    total_done += worker_iters[tasks.index(task)]
            pct = min(99, round(total_done / iterations * 100))
            yield f"data: {json.dumps({'type':'progress','done':total_done,'total':iterations,'pct':pct})}\n\n"

        if not best_result or not best_result.get("slot_map"):
            yield f"data: {json.dumps({'type':'error','message':'Assignment failed'})}\n\n"
            return

        # Always insert a new record — each assignment is a new version.
        # History is preserved so the user can revert to any previous assignment.
        # Deactivate all existing schedules for this event first.
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

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})


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
