"""
FRC Match Scheduler — FastAPI backend
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
    AsyncSessionLocal, Event, EventTeam, MatchRow, Schedule, Team,
    get_session, init_db,
)
from app.scheduler import run_iterations_worker
from app import tba as tba_client

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ── ProcessPoolExecutor — one pool shared across all requests ─────────────────
CPU_WORKERS = int(os.getenv("CPU_WORKERS", os.cpu_count() or 4))
_pool: ProcessPoolExecutor | None = None

def get_pool() -> ProcessPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ProcessPoolExecutor(max_workers=CPU_WORKERS)
    return _pool


# ── App setup ─────────────────────────────────────────────────────────────────
app = FastAPI(title="FRC Match Scheduler", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    await init_db()
    get_pool()  # warm up the process pool
    log.info("Started with %d CPU workers", CPU_WORKERS)

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
    key:       str = Field(..., max_length=64)
    name:      str = Field(..., max_length=256)
    year:      int
    location:  str | None = None
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


class GenerateRequest(BaseModel):
    event_id:        int
    matches_per_team: int = Field(6, ge=1, le=20)
    cooldown:        int = Field(3, ge=1, le=20)
    iterations:      int = Field(1000, ge=1)
    schedule_name:   str = "Schedule"
    day_config:      Any = None   # forwarded from frontend, stored as-is


class DayConfig(BaseModel):
    day_config: Any = None


# ── Events ────────────────────────────────────────────────────────────────────

@app.get("/api/events")
async def list_events(db: AsyncSession = Depends(get_session)):
    result = await db.execute(select(Event).order_by(Event.year.desc(), Event.name))
    return [
        {
            "id": e.id, "key": e.key, "name": e.name,
            "year": e.year, "location": e.location,
            "start_date": e.start_date, "end_date": e.end_date,
            "tba_synced": e.tba_synced,
        }
        for e in result.scalars()
    ]


@app.post("/api/events", status_code=201)
async def create_event(body: EventCreate, db: AsyncSession = Depends(get_session)):
    existing = await db.execute(select(Event).where(Event.key == body.key))
    if existing.scalar_one_or_none():
        raise HTTPException(409, f"Event '{body.key}' already exists")
    event = Event(**body.model_dump())
    db.add(event)
    await db.commit()
    await db.refresh(event)
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
        "id": event.id, "key": event.key, "name": event.name,
        "year": event.year, "location": event.location,
        "start_date": event.start_date, "end_date": event.end_date,
        "tba_synced": event.tba_synced,
        "teams": [
            {
                "slot": et.slot,
                "number": et.team.number,
                "nickname": et.team.nickname,
                "name": et.team.name,
            }
            for et in sorted(event.teams, key=lambda x: x.slot or 0)
        ],
    }


@app.delete("/api/events/{event_id}", status_code=204)
async def delete_event(event_id: int, db: AsyncSession = Depends(get_session)):
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    await db.delete(event)
    await db.commit()


# ── TBA integration ───────────────────────────────────────────────────────────

@app.get("/api/tba/events/{year}")
async def tba_events(year: int, search: str = Query("", max_length=100)):
    try:
        events = await tba_client.search_events(year, search) if search else await tba_client.get_events(year)
        return [tba_client.normalise_event(e) for e in events]
    except Exception as e:
        raise HTTPException(502, f"TBA API error: {e}")


@app.post("/api/tba/import/{event_key}", status_code=201)
async def tba_import_event(event_key: str, db: AsyncSession = Depends(get_session)):
    """
    Pull event + team roster from TBA and upsert into our DB.
    """
    try:
        tba_event = await tba_client.get_event(event_key)
        tba_teams = await tba_client.get_event_teams(event_key)
    except Exception as e:
        raise HTTPException(502, f"TBA API error: {e}")

    # Upsert event
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

    # Upsert teams and link to event
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

        # Link event ↔ team
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
        select(EventTeam)
        .options(selectinload(EventTeam.team))
        .where(EventTeam.event_id == event_id)
        .order_by(EventTeam.slot)
    )
    return [
        {
            "slot": et.slot, "number": et.team.number,
            "nickname": et.team.nickname, "name": et.team.name,
            "city": et.team.city, "state": et.team.state,
        }
        for et in result.scalars()
    ]


@app.post("/api/events/{event_id}/teams", status_code=201)
async def add_team_to_event(event_id: int, body: TeamIn, db: AsyncSession = Depends(get_session)):
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")

    # Upsert team
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
    await db.delete(link)
    await db.commit()


# ── Schedule generation with SSE progress ────────────────────────────────────

@app.post("/api/events/{event_id}/generate")
async def generate_schedule(
    event_id: int,
    body: GenerateRequest,
    db: AsyncSession = Depends(get_session),
):
    """
    Stream Server-Sent Events while scheduling runs on CPU workers.
    The final SSE event carries the complete schedule ID.
    """
    # Load event teams and assign slots
    result = await db.execute(
        select(EventTeam)
        .options(selectinload(EventTeam.team))
        .where(EventTeam.event_id == event_id)
        .order_by(EventTeam.team_id)
    )
    event_teams = list(result.scalars())
    if not event_teams:
        raise HTTPException(400, "Event has no teams")

    # Assign sequential slots 1..N
    for i, et in enumerate(event_teams, start=1):
        et.slot = i
    await db.commit()

    num_teams        = len(event_teams)
    matches_per_team = body.matches_per_team
    cooldown         = body.cooldown
    iterations       = body.iterations

    pool = get_pool()
    loop = asyncio.get_event_loop()

    async def run_and_stream() -> AsyncGenerator[str, None]:
        # Split iterations across CPU workers
        n_workers = min(iterations, CPU_WORKERS)
        base      = iterations // n_workers
        remainder = iterations % n_workers

        futures = []
        for w in range(n_workers):
            w_iters = base + (1 if w < remainder else 0)
            future  = loop.run_in_executor(
                pool, run_iterations_worker,
                (num_teams, matches_per_team, cooldown, w_iters, w)
            )
            futures.append(future)

        total_done     = 0
        best_result    = None

        # Poll futures every 200ms and stream progress
        pending = list(futures)
        while pending:
            done, pending_set = await asyncio.wait(
                [asyncio.ensure_future(f) for f in pending],
                timeout=0.2,
                return_when=asyncio.FIRST_COMPLETED,
            )
            still_pending = []
            for f in pending:
                fut = asyncio.ensure_future(f)
                if fut in done:
                    try:
                        result = fut.result()
                        total_done += iterations // n_workers + (1 if len(futures) - pending.index(f) <= remainder else 0)
                        if best_result is None or result["score"] > best_result["score"]:
                            best_result = result
                    except Exception as e:
                        log.error("Worker error: %s", e)
                else:
                    still_pending.append(f)
            pending = still_pending
            pct = min(99, round(total_done / iterations * 100))
            yield f"data: {json.dumps({'type': 'progress', 'done': total_done, 'total': iterations, 'pct': pct})}\n\n"

        # All workers done — save to DB
        if not best_result or not best_result.get("matches"):
            yield f"data: {json.dumps({'type': 'error', 'message': 'No schedule generated'})}\n\n"
            return

        # Deactivate existing schedules for this event
        await db.execute(
            update(Schedule)
            .where(Schedule.event_id == event_id)
            .values(is_active=False)
        )

        sched = Schedule(
            event_id=event_id,
            name=body.schedule_name,
            is_active=True,
            num_teams=num_teams,
            matches_per_team=matches_per_team,
            cooldown=cooldown,
            iterations_run=iterations,
            best_iteration=best_result.get("worker_id", 0),
            score=best_result["score"],
            matches=best_result["matches"],
            surrogate_count=best_result["surrogate_count"],
            round_boundaries={str(k): v for k, v in best_result["round_boundaries"].items()},
            day_config=body.day_config,
        )
        db.add(sched)
        await db.flush()

        # Denormalise into match_rows for queryability
        for i, m in enumerate(best_result["matches"], start=1):
            db.add(MatchRow(
                schedule_id=sched.id, match_num=i,
                red1=m["red"][0], red2=m["red"][1], red3=m["red"][2],
                blue1=m["blue"][0], blue2=m["blue"][1], blue3=m["blue"][2],
                red1_surrogate=m["red_surrogate"][0],
                red2_surrogate=m["red_surrogate"][1],
                red3_surrogate=m["red_surrogate"][2],
                blue1_surrogate=m["blue_surrogate"][0],
                blue2_surrogate=m["blue_surrogate"][1],
                blue3_surrogate=m["blue_surrogate"][2],
            ))
        await db.commit()

        yield f"data: {json.dumps({'type': 'done', 'schedule_id': sched.id, 'score': best_result['score'], 'pct': 100})}\n\n"

    return StreamingResponse(
        run_and_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Schedule retrieval ────────────────────────────────────────────────────────

@app.get("/api/events/{event_id}/schedules")
async def list_schedules(event_id: int, db: AsyncSession = Depends(get_session)):
    result = await db.execute(
        select(Schedule)
        .where(Schedule.event_id == event_id)
        .order_by(Schedule.created_at.desc())
    )
    return [
        {
            "id": s.id, "name": s.name, "is_active": s.is_active,
            "num_teams": s.num_teams, "matches_per_team": s.matches_per_team,
            "iterations_run": s.iterations_run, "score": s.score,
            "created_at": s.created_at.isoformat(),
        }
        for s in result.scalars()
    ]


@app.get("/api/schedules/{schedule_id}")
async def get_schedule(schedule_id: int, db: AsyncSession = Depends(get_session)):
    sched = await db.get(Schedule, schedule_id)
    if not sched:
        raise HTTPException(404, "Schedule not found")
    return {
        "id": sched.id, "name": sched.name, "is_active": sched.is_active,
        "event_id": sched.event_id,
        "num_teams": sched.num_teams,
        "matches_per_team": sched.matches_per_team,
        "cooldown": sched.cooldown,
        "iterations_run": sched.iterations_run,
        "best_iteration": sched.best_iteration,
        "score": sched.score,
        "matches": sched.matches,
        "surrogate_count": sched.surrogate_count,
        "round_boundaries": sched.round_boundaries,
        "day_config": sched.day_config,
        "created_at": sched.created_at.isoformat(),
    }


@app.post("/api/schedules/{schedule_id}/activate", status_code=200)
async def activate_schedule(schedule_id: int, db: AsyncSession = Depends(get_session)):
    sched = await db.get(Schedule, schedule_id)
    if not sched:
        raise HTTPException(404, "Schedule not found")
    await db.execute(
        update(Schedule)
        .where(Schedule.event_id == sched.event_id)
        .values(is_active=False)
    )
    sched.is_active = True
    await db.commit()
    return {"activated": schedule_id}


@app.delete("/api/schedules/{schedule_id}", status_code=204)
async def delete_schedule(schedule_id: int, db: AsyncSession = Depends(get_session)):
    sched = await db.get(Schedule, schedule_id)
    if not sched:
        raise HTTPException(404, "Schedule not found")
    await db.delete(sched)
    await db.commit()


# ── Team lookup for a schedule ────────────────────────────────────────────────

@app.get("/api/schedules/{schedule_id}/team/{slot}")
async def team_matches(schedule_id: int, slot: int, db: AsyncSession = Depends(get_session)):
    """Return all matches for a given team slot in a schedule."""
    result = await db.execute(
        select(MatchRow)
        .where(MatchRow.schedule_id == schedule_id)
        .where(
            (MatchRow.red1 == slot) | (MatchRow.red2 == slot) | (MatchRow.red3 == slot) |
            (MatchRow.blue1 == slot) | (MatchRow.blue2 == slot) | (MatchRow.blue3 == slot)
        )
        .order_by(MatchRow.match_num)
    )
    rows = result.scalars().all()
    return [
        {
            "match_num": r.match_num,
            "alliance": "red" if slot in (r.red1, r.red2, r.red3) else "blue",
            "surrogate": (
                (slot == r.red1 and r.red1_surrogate) or
                (slot == r.red2 and r.red2_surrogate) or
                (slot == r.red3 and r.red3_surrogate) or
                (slot == r.blue1 and r.blue1_surrogate) or
                (slot == r.blue2 and r.blue2_surrogate) or
                (slot == r.blue3 and r.blue3_surrogate)
            ),
        }
        for r in rows
    ]


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {"status": "ok", "cpu_workers": CPU_WORKERS}
