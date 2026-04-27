# SPDX-License-Identifier: GPL-3.0-or-later
# FRC Match Scheduler — FastAPI backend
#
# Security hardening applied:
#   - Security headers middleware (X-Frame-Options, X-Content-Type-Options,
#     Referrer-Policy, Permissions-Policy, X-XSS-Protection)
#   - JWT_SECRET default value rejected at startup unless ALLOW_INSECURE_JWT=1
#   - Tighter per-route rate limits on CPU-intensive generation endpoints
#   - Auth callbacks use _oauth_popup_response (json.dumps token, targeted postMessage)
#   - Pydantic models enforce field length limits on all user-supplied strings

import asyncio
import json
import logging
import os
from concurrent.futures import ProcessPoolExecutor
from typing import Any, AsyncGenerator

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.db import (
    AbstractSchedule, AssignedSchedule, AsyncSessionLocal,
    Event, EventTeam, MatchRow, Team, User, get_session, init_db,
)
from app.scheduler import run_iterations_worker, run_assignment_chunk
from app import tba as tba_client
from app import frc_events as frc_client
from app.auth import (
    get_current_user, require_auth,
    google_login_url, google_exchange_code,
    apple_login_url, apple_exchange_code,
    upsert_user, create_jwt,
    GOOGLE_CLIENT_ID, APPLE_CLIENT_ID,
    _oauth_popup_response,
    JWT_SECRET,
)

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ── Security: reject default JWT secret in production ─────────────────────────
_ALLOW_INSECURE = os.getenv("ALLOW_INSECURE_JWT", "").lower() in ("1", "true", "yes")
if JWT_SECRET == "change-me-in-production" and not _ALLOW_INSECURE:
    raise RuntimeError(
        "JWT_SECRET is set to the default insecure value. "
        "Set a strong random secret via the JWT_SECRET environment variable. "
        "Generate one with: openssl rand -hex 32\n"
        "To bypass this check during local development only, set ALLOW_INSECURE_JWT=1"
    )

# ── ProcessPoolExecutor ───────────────────────────────────────────────────────
_cpu_workers_env = int(os.getenv("CPU_WORKERS", "0"))
CPU_WORKERS: int | None = _cpu_workers_env if _cpu_workers_env > 0 else None
_pool: ProcessPoolExecutor | None = None


def get_pool() -> ProcessPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ProcessPoolExecutor(max_workers=CPU_WORKERS)
    return _pool


def _noop(_: None = None) -> None:
    pass


_gen_concurrency = max(2, (CPU_WORKERS or os.cpu_count() or 4) // 3)
_generation_semaphore: asyncio.Semaphore | None = None


def get_generation_semaphore() -> asyncio.Semaphore:
    global _generation_semaphore
    if _generation_semaphore is None:
        _generation_semaphore = asyncio.Semaphore(_gen_concurrency)
    return _generation_semaphore


# ── Security headers middleware ────────────────────────────────────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Frame-Options"]           = "SAMEORIGIN"
        response.headers["X-Content-Type-Options"]    = "nosniff"
        response.headers["Referrer-Policy"]           = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"]          = "1; mode=block"
        response.headers["Permissions-Policy"]        = (
            "accelerometer=(), camera=(), geolocation=(), "
            "gyroscope=(), magnetometer=(), microphone=(), payment=()"
        )
        # Only add HSTS on HTTPS responses
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


# ── App setup ─────────────────────────────────────────────────────────────────
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])

app = FastAPI(title="FRC Match Scheduler", version="2.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

_ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "").split(",")
if not any(_ALLOWED_ORIGINS):
    _ALLOWED_ORIGINS = ["*"]
app.add_middleware(CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=True,
)

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    body = None
    try:
        body = (await request.body()).decode()
    except Exception:
        pass
    log.error("422 on %s %s — errors: %s", request.method, request.url.path, exc.errors())
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.on_event("startup")
async def startup():
    import time
    t0 = time.monotonic()
    await init_db()
    log.info("DB init done in %.2fs", time.monotonic() - t0)
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(__import__('sqlalchemy').text("SELECT 1"))
        log.info("DB pool warmed in %.2fs", time.monotonic() - t0)
    except Exception as e:
        log.warning("DB pool warm-up failed (non-fatal): %s", e)
    get_pool()
    loop = asyncio.get_event_loop()
    n_workers = CPU_WORKERS or (os.cpu_count() or 4)
    try:
        await asyncio.gather(*[loop.run_in_executor(get_pool(), _noop) for _ in range(n_workers)])
        log.info("Pool pre-spawned in %.2fs", time.monotonic() - t0)
    except Exception as e:
        log.warning("Worker pre-spawn failed (non-fatal): %s", e)


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
    key:        str  = Field(..., min_length=1, max_length=64)
    name:       str  = Field(..., min_length=1, max_length=256)
    year:       int  = Field(..., ge=1992, le=2100)
    location:   str | None = Field(None, max_length=512)
    start_date: str | None = Field(None, max_length=32)
    end_date:   str | None = Field(None, max_length=32)


class TeamIn(BaseModel):
    number:      int       = Field(..., ge=1, le=99999)
    name:        str | None = Field(None, max_length=512)
    nickname:    str | None = Field(None, max_length=128)
    city:        str | None = Field(None, max_length=128)
    state:       str | None = Field(None, max_length=64)
    country:     str | None = Field(None, max_length=64)
    rookie_year: int | None = Field(None, ge=1992, le=2100)


class AbstractGenerateRequest(BaseModel):
    num_teams:        int        = Field(..., ge=6, le=120)
    matches_per_team: int        = Field(6, ge=1, le=50)
    cooldown:         int        = Field(3, ge=1, le=20)
    iterations:       int        = Field(1, ge=1, le=10000)
    seed:             str | None = Field(None, max_length=16)
    name:             str        = Field("Abstract Schedule", max_length=128)
    event_id:         int | None = None
    day_config:       Any        = None

    from pydantic import field_validator

    @field_validator('seed', mode='before')
    @classmethod
    def coerce_empty_seed(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            return None
        return v


class AssignRequest(BaseModel):
    event_id:             int
    abstract_schedule_id: int
    iterations:           int        = Field(1000, ge=1, le=100000)
    assign_seed:          str | None = Field(None, max_length=16)
    name:                 str        = Field("Schedule", max_length=128)
    day_config:           Any        = None


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


@app.get("/api/events/adhoc")
async def get_or_create_adhoc_event(db: AsyncSession = Depends(get_session)):
    import datetime as _dt
    ADHOC_KEY = "adhoc"
    result = await db.execute(select(Event).where(Event.key == ADHOC_KEY))
    event = result.scalar_one_or_none()
    if not event:
        event = Event(key=ADHOC_KEY, name="Ad-hoc Schedule",
                      year=_dt.date.today().year, location="", tba_synced=False)
        db.add(event)
        await db.commit()
        await db.refresh(event)
    result2 = await db.execute(
        select(Event).options(selectinload(Event.teams).selectinload(EventTeam.team))
        .where(Event.id == event.id)
    )
    ev = result2.scalar_one()
    return {
        "id": ev.id, "key": ev.key, "name": ev.name, "year": ev.year,
        "location": ev.location, "tba_synced": ev.tba_synced,
        "teams": [
            {"number": et.team.number, "nickname": et.team.nickname, "name": et.team.name}
            for et in sorted(ev.teams, key=lambda x: x.team.number)
        ],
    }


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
        select(Event).options(selectinload(Event.teams).selectinload(EventTeam.team))
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
    await db.delete(event)
    await db.commit()


# ── TBA ───────────────────────────────────────────────────────────────────────

@app.get("/api/tba/events/{year}")
async def tba_events(year: int = Query(..., ge=1992, le=2100),
                     search: str = Query("", max_length=100)):
    try:
        events = await tba_client.search_events(year, search) if search else await tba_client.get_events(year)
        return [tba_client.normalise_event(e) for e in events]
    except ValueError as e:
        raise HTTPException(503, str(e))
    except httpx.TimeoutException:
        raise HTTPException(504, "TBA API request timed out")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            raise HTTPException(502, "TBA API key is invalid.")
        raise HTTPException(502, f"TBA API returned {e.response.status_code}")
    except Exception as e:
        log.error("TBA events error: %s", e)
        raise HTTPException(502, f"TBA API error: {e}")


@app.get("/api/tba/team/{team_number}")
async def tba_team_lookup(team_number: int = Query(..., ge=1, le=99999)):
    try:
        raw = await tba_client.get_team(f"frc{team_number}")
        return tba_client.normalise_team(raw)
    except ValueError as e:
        raise HTTPException(503, str(e))
    except Exception:
        raise HTTPException(404, f"Team {team_number} not found")


@app.get("/api/tba/search_index")
async def tba_search_index():
    import time as _time
    cache = app.state
    now = _time.monotonic()
    if getattr(cache, '_search_index_data', None) is not None:
        if now - getattr(cache, '_search_index_ts', 0) < 21600:
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
async def tba_import_event(event_key: str = Query(..., max_length=64),
                           db: AsyncSession = Depends(get_session)):
    try:
        tba_event = await tba_client.get_event(event_key)
        tba_teams = await tba_client.get_event_teams(event_key)
    except ValueError as e:
        raise HTTPException(503, str(e))
    except httpx.TimeoutException:
        raise HTTPException(504, "TBA API request timed out")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            raise HTTPException(502, "TBA API key is invalid.")
        if e.response.status_code == 404:
            raise HTTPException(404, f"Event '{event_key}' not found on TBA.")
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
    return {"id": event.id, "key": event_key, "name": event.name, "teams_imported": len(tba_teams)}


# ── FRC Events API ────────────────────────────────────────────────────────────

@app.get("/api/frc/configured")
@app.get("/api/frc/status")
async def frc_events_status():
    return {"configured": frc_client.is_configured()}


@app.get("/api/frc/events/{year}")
async def frc_events_list(year: int = Query(..., ge=1992, le=2100),
                          search: str = Query("", max_length=100)):
    try:
        events = await frc_client.search_events(year, search) if search else await frc_client.get_events(year)
        return [frc_client.normalise_event(e, year) for e in events]
    except ValueError as e:
        raise HTTPException(503, str(e))
    except httpx.TimeoutException:
        raise HTTPException(504, "FRC Events API request timed out")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            raise HTTPException(502, "FRC Events credentials invalid.")
        raise HTTPException(502, f"FRC Events API returned {e.response.status_code}")
    except Exception as e:
        log.error("FRC events error: %s", e)
        raise HTTPException(502, f"FRC Events API error: {e}")


@app.post("/api/frc/import/{year}/{event_code}", status_code=201)
async def frc_import_event(year: int, event_code: str = Query(..., max_length=32),
                           db: AsyncSession = Depends(get_session)):
    try:
        frc_event = await frc_client.get_event(year, event_code)
        if not frc_event:
            raise HTTPException(404, f"Event '{event_code}' ({year}) not found on FRC Events API.")
        frc_teams = await frc_client.get_event_teams(year, event_code)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(503, str(e))
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            raise HTTPException(502, "FRC Events credentials invalid.")
        if e.response.status_code == 404:
            raise HTTPException(404, f"Event '{event_code}' ({year}) not found.")
        raise HTTPException(502, f"FRC Events API returned {e.response.status_code}")
    except Exception as e:
        log.error("FRC Events import error: %s", e)
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
    return {"id": event.id, "key": key, "name": event.name, "teams_imported": len(frc_teams)}


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
    await db.delete(link)
    await db.commit()


@app.patch("/api/events/{event_id}/teams/{team_number}", status_code=200)
async def enrich_team(event_id: int, team_number: int, body: dict,
                      db: AsyncSession = Depends(get_session)):
    t = await db.execute(select(Team).where(Team.number == team_number))
    team = t.scalar_one_or_none()
    if not team:
        raise HTTPException(404, "Team not found")
    if "nickname" in body and body["nickname"]:
        team.nickname = str(body["nickname"])[:128]
    if "name" in body and body["name"]:
        team.name = str(body["name"])[:512]
    await db.commit()
    return {"number": team_number, "nickname": team.nickname, "name": team.name}


# ── Stage 1: Abstract Schedule Generation ────────────────────────────────────

@app.post("/api/generate-abstract")
@limiter.limit("10/minute")
async def generate_abstract(
    request: Request,
    body: AbstractGenerateRequest,
    current_user: dict | None = Depends(get_current_user),
):
    loop = asyncio.get_event_loop()
    pool = get_pool()
    _seed_int = int(body.seed, 16) if body.seed else None

    async def stream() -> AsyncGenerator[str, None]:
        yield ": connected\n\n"
        sem = get_generation_semaphore()
        async with sem:
            try:
                future = loop.run_in_executor(
                    pool, run_iterations_worker,
                    (body.num_teams, body.matches_per_team, body.cooldown, 1, 0, _seed_int),
                )
                while not future.done():
                    await asyncio.sleep(0.5)
                    yield ": ping\n\n"
                result = await future
            except Exception as e:
                log.error("Stage 1 worker error: %s", e)
                yield f"data: {json.dumps({'type':'error','message':str(e)})}\n\n"
                return

        try:
            async with AsyncSessionLocal() as db:
                sched = AbstractSchedule(
                    event_id=body.event_id, name=body.name,
                    num_teams=body.num_teams, matches_per_team=body.matches_per_team,
                    cooldown=body.cooldown, seed=body.seed,
                    iterations_run=1, best_iteration=0, score=result["score"],
                    created_by=current_user["sub"] if current_user else None,
                    matches=result["matches"], surrogate_count=result["surrogate_count"],
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

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no","Connection":"keep-alive"})


@app.get("/api/abstract-schedules")
async def list_abstract_schedules(event_id: int | None = Query(None),
                                  db: AsyncSession = Depends(get_session)):
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
        "iterations_run": sched.iterations_run, "score": sched.score,
        "matches": sched.matches, "surrogate_count": sched.surrogate_count,
        "round_boundaries": sched.round_boundaries, "day_config": sched.day_config,
        "created_at": sched.created_at.isoformat(),
    }


@app.delete("/api/abstract-schedules/{schedule_id}", status_code=204)
async def delete_abstract_schedule(schedule_id: int, db: AsyncSession = Depends(get_session)):
    sched = await db.get(AbstractSchedule, schedule_id)
    if not sched:
        raise HTTPException(404, "Abstract schedule not found")
    await db.delete(sched)
    await db.commit()


# ── Stage 2: Team Assignment ──────────────────────────────────────────────────

@app.post("/api/abstract-schedules/{abstract_id}/assign")
@limiter.limit("10/minute")
async def assign_teams_endpoint(
    request: Request,
    abstract_id: int,
    body: AssignRequest,
    current_user: dict | None = Depends(get_current_user),
):
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
                f"Event has {len(event_teams)} teams but schedule was built for {abstract.num_teams}")
        team_numbers = sorted(et.team.number for et in event_teams)
        abstract_matches   = abstract.matches
        abstract_cooldown  = abstract.cooldown
        abstract_num_teams = abstract.num_teams

    pool = get_pool()
    loop = asyncio.get_event_loop()

    async def stream() -> AsyncGenerator[str, None]:
        yield ": connected\n\n"
        await asyncio.sleep(0)
        actual_workers = CPU_WORKERS or (os.cpu_count() or 4)
        n_workers  = min(body.iterations, actual_workers)
        _aseed_int = int(body.assign_seed, 16) if body.assign_seed else None
        chunk_size = max(10, body.iterations // (n_workers * 20))
        chunks_per_worker = max(1, (body.iterations // n_workers) // chunk_size)
        total_chunks = n_workers * chunks_per_worker
        done_chunks  = 0
        best_result  = None

        sem = get_generation_semaphore()
        async with sem:
            futures = []
            for w in range(n_workers):
                worker_seed = (_aseed_int ^ (w * 99991)) if _aseed_int is not None else None
                for c in range(chunks_per_worker):
                    chunk_seed = (worker_seed ^ (c * 7919)) if worker_seed is not None else None
                    futures.append(loop.run_in_executor(
                        pool, run_assignment_chunk,
                        (abstract_matches, abstract_num_teams, team_numbers,
                         abstract_cooldown, chunk_size, w, chunk_seed),
                    ))
            for f in asyncio.as_completed(futures):
                try:
                    res = await f
                    done_chunks += 1
                    if best_result is None or res["score"] > best_result["score"]:
                        best_result = res
                    pct = int(done_chunks / total_chunks * 100)
                    yield f"data: {json.dumps({'type':'progress','pct':pct,'score':best_result['score']})}\n\n"
                except Exception as e:
                    log.error("Stage 2 worker error: %s", e)

        if best_result is None:
            yield f"data: {json.dumps({'type':'error','message':'Assignment failed'})}\n\n"
            return

        async with AsyncSessionLocal() as db:
            await db.execute(
                update(AssignedSchedule)
                .where(AssignedSchedule.event_id == body.event_id)
                .values(is_active=False)
            )
            assigned = AssignedSchedule(
                abstract_schedule_id=abstract_id, event_id=body.event_id,
                name=body.name, is_active=True,
                slot_map=best_result["slot_map"], day_config=body.day_config,
                assign_seed=body.assign_seed,
                created_by=current_user["sub"] if current_user else None,
            )
            db.add(assigned)
            await db.flush()
            slot_map = {int(k): v for k, v in best_result["slot_map"].items()}
            for i, m in enumerate(abstract_matches, start=1):
                db.add(MatchRow(
                    assigned_schedule_id=assigned.id, match_num=i,
                    red1=slot_map[m["red"][0]], red2=slot_map[m["red"][1]], red3=slot_map[m["red"][2]],
                    blue1=slot_map[m["blue"][0]], blue2=slot_map[m["blue"][1]], blue3=slot_map[m["blue"][2]],
                    red1_surrogate=m["red_surrogate"][0], red2_surrogate=m["red_surrogate"][1],
                    red3_surrogate=m["red_surrogate"][2],
                    blue1_surrogate=m["blue_surrogate"][0], blue2_surrogate=m["blue_surrogate"][1],
                    blue3_surrogate=m["blue_surrogate"][2],
                ))
            await db.commit()

        yield f"data: {json.dumps({'type':'done','assigned_schedule_id':assigned.id,'score':best_result['score'],'pct':100})}\n\n"

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
        {"id": s.id, "name": s.name, "is_active": s.is_active,
         "abstract_schedule_id": s.abstract_schedule_id,
         "num_teams": s.abstract_schedule.num_teams,
         "matches_per_team": s.abstract_schedule.matches_per_team,
         "created_at": s.created_at.isoformat()}
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
    resolved_matches = [
        {"red": [slot_map[s] for s in m["red"]], "blue": [slot_map[s] for s in m["blue"]],
         "red_surrogate": m["red_surrogate"], "blue_surrogate": m["blue_surrogate"]}
        for m in abstract.matches
    ]
    return {
        "id": assigned.id, "name": assigned.name, "is_active": assigned.is_active,
        "event_id": assigned.event_id,
        "abstract_schedule_id": assigned.abstract_schedule_id,
        "num_teams": abstract.num_teams, "matches_per_team": abstract.matches_per_team,
        "cooldown": abstract.cooldown, "seed": abstract.seed,
        "assign_seed": assigned.assign_seed, "created_by": assigned.created_by,
        "slot_map": assigned.slot_map, "matches": resolved_matches,
        "surrogate_count": abstract.surrogate_count,
        "round_boundaries": abstract.round_boundaries,
        "day_config": assigned.day_config,
        "created_at": assigned.created_at.isoformat(),
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
    schedule_id: int, db: AsyncSession = Depends(get_session),
    current_user: dict | None = Depends(get_current_user),
):
    assigned = await db.get(AssignedSchedule, schedule_id)
    if not assigned:
        raise HTTPException(404, "Assigned schedule not found")
    if assigned.created_by and (not current_user or current_user.get("sub") != assigned.created_by):
        raise HTTPException(403, "You do not own this schedule")
    await db.delete(assigned)
    await db.commit()


@app.post("/api/assigned-schedules/{schedule_id}/duplicate", status_code=201)
async def duplicate_assigned_schedule(
    schedule_id: int, db: AsyncSession = Depends(get_session),
    current_user: dict | None = Depends(get_current_user),
):
    result = await db.execute(
        select(AssignedSchedule)
        .options(selectinload(AssignedSchedule.abstract_schedule))
        .where(AssignedSchedule.id == schedule_id)
    )
    src = result.scalar_one_or_none()
    if not src:
        raise HTTPException(404, "Schedule not found")
    abs_src = src.abstract_schedule
    new_abs = AbstractSchedule(
        event_id=abs_src.event_id, name=f"{abs_src.name} (copy)",
        num_teams=abs_src.num_teams, matches_per_team=abs_src.matches_per_team,
        cooldown=abs_src.cooldown, seed=abs_src.seed,
        iterations_run=abs_src.iterations_run, best_iteration=abs_src.best_iteration,
        score=abs_src.score, matches=abs_src.matches,
        surrogate_count=abs_src.surrogate_count, round_boundaries=abs_src.round_boundaries,
        day_config=abs_src.day_config,
        created_by=current_user["sub"] if current_user else None,
    )
    db.add(new_abs)
    await db.flush()
    new_asgn = AssignedSchedule(
        abstract_schedule_id=new_abs.id, event_id=src.event_id,
        name=f"{src.name} (copy)", is_active=False,
        slot_map=src.slot_map, day_config=src.day_config,
        assign_seed=src.assign_seed,
        created_by=current_user["sub"] if current_user else None,
    )
    db.add(new_asgn)
    await db.flush()
    mr_result = await db.execute(select(MatchRow).where(MatchRow.assigned_schedule_id == schedule_id))
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


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "cpu_workers": CPU_WORKERS or os.cpu_count() or 1}


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.get("/auth/google/login")
async def google_login(state: str = Query("", max_length=256)):
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(501, "Google OAuth not configured")
    return RedirectResponse(google_login_url(state))


@app.get("/auth/google/callback")
@limiter.limit("20/minute")
async def google_callback(request: Request, code: str = Query(..., max_length=512),
                          db: AsyncSession = Depends(get_session)):
    try:
        info = await google_exchange_code(code)
    except Exception as e:
        raise HTTPException(400, f"Google OAuth failed: {e}")
    user  = await upsert_user(sub=f"google:{info['sub']}", provider="google",
                              email=info.get("email"), name=info.get("name"), db=db)
    token = create_jwt(user.id, user.sub, "google", user.email)
    return _oauth_popup_response(token)


@app.get("/auth/apple/login")
async def apple_login(state: str = Query("", max_length=256)):
    if not APPLE_CLIENT_ID:
        raise HTTPException(501, "Apple OAuth not configured")
    return RedirectResponse(apple_login_url(state))


@app.post("/auth/apple/callback")
@limiter.limit("20/minute")
async def apple_callback(request: Request, db: AsyncSession = Depends(get_session)):
    form = await request.form()
    code = form.get("code")
    id_token_raw = form.get("id_token")
    if not code:
        raise HTTPException(400, "No code in Apple callback")
    try:
        info = await apple_exchange_code(str(code), str(id_token_raw) if id_token_raw else None)
    except Exception as e:
        raise HTTPException(400, f"Apple OAuth failed: {e}")
    name = None
    if user_json := form.get("user"):
        try:
            u = json.loads(str(user_json))
            n = u.get("name", {})
            name = f"{n.get('firstName','')} {n.get('lastName','')}".strip() or None
        except Exception:
            pass
    user  = await upsert_user(sub=f"apple:{info['sub']}", provider="apple",
                              email=info.get("email"), name=name, db=db)
    token = create_jwt(user.id, user.sub, "apple", user.email)
    return _oauth_popup_response(token)


@app.get("/auth/me")
async def auth_me(current_user: dict | None = Depends(get_current_user)):
    if not current_user:
        return {"authenticated": False}
    return {
        "authenticated": True, "sub": current_user.get("sub"),
        "email": current_user.get("email"), "provider": current_user.get("provider"),
        "uid": current_user.get("uid"),
    }


@app.get("/auth/providers")
async def auth_providers():
    return {"google": bool(GOOGLE_CLIENT_ID), "apple": bool(APPLE_CLIENT_ID)}


# ── Commit log ────────────────────────────────────────────────────────────────

class CommitLogEntry(BaseModel):
    event:       str
    timestamp:   str
    schedule:    dict[str, Any]
    parameters:  dict[str, Any]
    teams:       list[int] = []
    match_count: int | None = None
    url:         str | None = Field(None, max_length=2048)
    event_info:  dict[str, Any] | None = None
    day_config:  dict[str, Any] | None = None
    surrogate_count: dict[str, Any] | None = None
    stats:       dict[str, Any] | None = None


@app.post("/api/log-commit", status_code=204)
async def log_commit(body: CommitLogEntry,
                     current_user: dict | None = Depends(get_current_user)):
    log.info(
        "SCHEDULE_COMMITTED user=%s event=%s teams=%d matches=%s",
        (current_user or {}).get("sub", "anonymous"),
        body.event_info.get("key") if body.event_info else "none",
        len(body.teams), body.match_count,
    )
