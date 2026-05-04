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
from fastapi import Depends, FastAPI, File, HTTPException, Path, Query, Request, UploadFile
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
    Event, EventTeam, MatchResult, MatchRow, PdfImport, Team, User,
    get_session, init_db,
)
from app.scheduler import run_iterations_worker, run_assignment_chunk
from app import live as live_data
from app import statbotics as statbotics_client
from app import tba as tba_client
from app import frc_events as frc_client
from app import pdf_extract
from app import pdf_validate
from app import llm_client
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


@app.get("/view", include_in_schema=False)
async def view_page():
    """Read-only schedule viewer for teams, audiences, and printable handouts.
    Same query params as the editor (?aid, ?id) plus optional ?team, ?live,
    ?org branding presets, and ?logo / ?color / ?title overrides."""
    return FileResponse(os.path.join(STATIC_DIR, "view.html"))


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
    # Optional weight overrides for placement criteria. When None, FIRST-aligned
    # defaults from app.scheduler.DEFAULT_WEIGHTS are used. The editor's
    # "Advanced criteria" panel uses this to let users tune scoring while
    # preserving reproducibility — the chosen weights round-trip through the URL.
    weights:          dict[str, float] | None = None

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
    # Optional: practice match list, generated client-side. Same shape as
    # AbstractSchedule.matches but with already-resolved team numbers.
    practice_matches:     Any        = None


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
        "branding": event.branding or {},
        "teams": [
            {"number": et.team.number, "nickname": et.team.nickname, "name": et.team.name}
            for et in sorted(event.teams, key=lambda x: x.team.number)
        ],
    }


@app.patch("/api/events/{event_id}/branding")
async def patch_event_branding(
    event_id: int,
    branding: dict,
    db: AsyncSession = Depends(get_session),
):
    """Update the event's branding payload for the /view page.

    Accepts an arbitrary JSON object. Recognized keys (all optional):
      preset:          str  — one of "mshsl", "frc" (built-in styling)
      logo_url:        str  — URL of an event/org logo (rendered top-left)
      primary_color:   str  — "#RRGGBB" — header background, accents
      secondary_color: str  — "#RRGGBB" — secondary highlights
      title:           str  — override the page title
      subtitle:        str  — secondary line under the title (e.g. venue + date)
      venue:           str  — venue display (e.g. "Concordia University, St. Paul")
      footer:          str  — footer line (sponsor credits etc.)

    Pass an empty object {} or null fields to clear branding.
    """
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    # Replace, don't merge — caller has the full object. Use empty dict to clear.
    event.branding = branding if isinstance(branding, dict) else {}
    await db.commit()
    return {"id": event.id, "branding": event.branding}


@app.delete("/api/events/{event_id}", status_code=204)
async def delete_event(event_id: int, db: AsyncSession = Depends(get_session)):
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    await db.delete(event)
    await db.commit()


# ── TBA ───────────────────────────────────────────────────────────────────────

@app.get("/api/tba/events/{year}")
async def tba_events(year: int = Path(..., ge=1992, le=2100),
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
async def tba_team_lookup(team_number: int = Path(..., ge=1, le=99999)):
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
async def tba_import_event(event_key: str = Path(..., max_length=64),
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
async def frc_events_list(year: int = Path(..., ge=1992, le=2100),
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
async def frc_import_event(year: int = Path(..., ge=1992, le=2100), event_code: str = Path(..., max_length=32),
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
                    (body.num_teams, body.matches_per_team, body.cooldown, 1, 0, _seed_int, body.weights),
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
                    weights=body.weights,  # None = FIRST defaults
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
        "weights": sched.weights,  # None means FIRST defaults were used
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
                practice_matches=body.practice_matches,
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
    # Practice matches are stored with slot indices (1..N) because they're
    # generated client-side using the abstract scheduler. Translate them
    # to real team numbers using the same slot_map so they render with
    # team numbers like the qual matches. Falls through unchanged for
    # entries that already contain team numbers (e.g. older saved schedules
    # or external imports), since slot_map.get returns None and we keep
    # the original value as a fallback.
    resolved_practice_matches = _resolve_practice_matches(assigned.practice_matches, slot_map)
    # Pull event info too — saves an extra round-trip for the /view page
    event = await db.get(Event, assigned.event_id) if assigned.event_id else None
    event_info = None
    if event:
        event_info = {
            "id": event.id, "key": event.key, "name": event.name,
            "year": event.year, "location": event.location,
            "branding": event.branding or {},
        }
    return {
        "id": assigned.id, "name": assigned.name, "is_active": assigned.is_active,
        "event_id": assigned.event_id, "event": event_info,
        "abstract_schedule_id": assigned.abstract_schedule_id,
        "num_teams": abstract.num_teams, "matches_per_team": abstract.matches_per_team,
        "cooldown": abstract.cooldown, "seed": abstract.seed,
        "assign_seed": assigned.assign_seed, "created_by": assigned.created_by,
        "slot_map": assigned.slot_map, "matches": resolved_matches,
        "practice_matches": resolved_practice_matches,
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
        weights=abs_src.weights,
        created_by=current_user["sub"] if current_user else None,
    )
    db.add(new_abs)
    await db.flush()
    new_asgn = AssignedSchedule(
        abstract_schedule_id=new_abs.id, event_id=src.event_id,
        name=f"{src.name} (copy)", is_active=False,
        slot_map=src.slot_map, day_config=src.day_config,
        practice_matches=src.practice_matches,
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


# ── Event-keyed view resolver ────────────────────────────────────────────────
#
# A stable URL like /view?event=2026mnst should "just work" for teams,
# audiences, and printed flyers without needing to know an opaque schedule ID.
# This endpoint resolves an event key to a unified payload that the view page
# can consume the same way regardless of source:
#
#   1. Local active AssignedSchedule exists  → return that (current behavior)
#   2. Multiple local schedules, none active → return a picker payload
#   3. No local schedule but TBA has it      → synthesize a TBA-sourced payload
#   4. Nothing                                → 404
#
# The output shape mirrors GET /api/assigned-schedules/{id} so the frontend
# can treat both paths interchangeably. The "source" field on the payload
# tells the UI which path was taken.
#
# Auth note (TODO, separate landing):
#   /view payloads are intentionally public — anyone with the event key can
#   see the schedule. Editing endpoints (create/update/delete) will be the
#   ones that get auth in the next pass. The view page treats the schedule
#   as read-only by design.


@app.get("/api/events/by-key/{event_key}/view-payload")
async def get_event_view_payload(
    event_key: str,
    db: AsyncSession = Depends(get_session),
):
    """Resolve an event key to a /view-ready payload, regardless of whether
    we have a local schedule for it.

    Returns one of:
      { source: 'local',         ...full assigned schedule shape... }
      { source: 'local-picker',  candidates: [...] }       — multiple, none active
      { source: 'tba',           ...synthesized from TBA... }
      { source: 'none', error:'...' }                      — nothing found
    """
    # Look up local Event by key first
    res = await db.execute(select(Event).where(Event.key == event_key))
    event = res.scalar_one_or_none()

    # ── Path 1+2: Local schedule lookup ──
    if event:
        # Find AssignedSchedules for this event, preferring the active one
        sched_res = await db.execute(
            select(AssignedSchedule)
            .options(selectinload(AssignedSchedule.abstract_schedule))
            .where(AssignedSchedule.event_id == event.id)
            .order_by(AssignedSchedule.is_active.desc(),
                      AssignedSchedule.created_at.desc())
        )
        schedules = sched_res.scalars().all()

        if schedules:
            # Pick the active schedule, or auto-select if there's only one
            active = next((s for s in schedules if s.is_active), None)
            if active is not None:
                payload = await _build_assigned_payload(db, active, event)
                payload["source"] = "local"
                return payload
            if len(schedules) == 1:
                payload = await _build_assigned_payload(db, schedules[0], event)
                payload["source"] = "local"
                return payload
            # Multiple schedules, none active → picker
            return {
                "source": "local-picker",
                "event": {
                    "id": event.id, "key": event.key, "name": event.name,
                    "year": event.year, "location": event.location,
                    "branding": event.branding or {},
                },
                "candidates": [
                    {
                        "id": s.id, "name": s.name, "is_active": s.is_active,
                        "created_at": s.created_at.isoformat(),
                        "created_by": s.created_by,
                    }
                    for s in schedules
                ],
            }

    # ── Path 3: TBA-only fallback ──
    # No local AssignedSchedule (and possibly no local Event row either).
    # If TBA has matches for this key, synthesize a payload from them.
    try:
        tba_event = await tba_client.get_event(event_key)
    except Exception:
        tba_event = None

    if not tba_event:
        raise HTTPException(404, f"Event '{event_key}' not found locally or on TBA")

    # Try to fetch TBA matches — these may not exist yet pre-event
    try:
        tba_matches = await tba_client.get_event_matches(event_key)
    except Exception as e:
        log.warning("TBA matches fetch failed for %s: %s", event_key, e)
        tba_matches = []

    # If we have a local Event row but no schedules, use its branding/info.
    # If we don't, build minimal info from the TBA event payload.
    if event:
        event_info = {
            "id": event.id, "key": event.key, "name": event.name,
            "year": event.year, "location": event.location,
            "branding": event.branding or {},
        }
        event_id = event.id
    else:
        event_info = {
            "id": None, "key": event_key,
            "name": tba_event.get("name") or event_key,
            "year": tba_event.get("year"),
            "location": (
                ", ".join(filter(None, [
                    tba_event.get("city"), tba_event.get("state_prov"),
                    tba_event.get("country"),
                ])) or None
            ),
            "branding": {},
        }
        event_id = None

    # Synthesize matches from TBA. We only include qualification matches —
    # playoffs are out of scope for the schedule view.
    qual_matches = [m for m in tba_matches if m.get("comp_level") == "qm"]
    qual_matches.sort(key=lambda m: m.get("match_number", 0))

    synthetic_matches = []
    teams_seen = set()
    for m in qual_matches:
        red  = (m.get("alliances") or {}).get("red",  {}) or {}
        blue = (m.get("alliances") or {}).get("blue", {}) or {}
        red_teams  = [_tba_key_to_num(k) for k in (red.get("team_keys")  or [])]
        blue_teams = [_tba_key_to_num(k) for k in (blue.get("team_keys") or [])]
        # Preserve surrogates if TBA reports them
        red_surrogate  = [
            _tba_key_to_num(k) in red_teams
            for k in (red.get("surrogate_team_keys") or [])
        ] if red.get("surrogate_team_keys") else [False, False, False]
        blue_surrogate = [
            _tba_key_to_num(k) in blue_teams
            for k in (blue.get("surrogate_team_keys") or [])
        ] if blue.get("surrogate_team_keys") else [False, False, False]
        # If surrogate_team_keys is present, build a positional flag list
        red_flags  = _surrogate_flags(red_teams,  red.get("surrogate_team_keys"))
        blue_flags = _surrogate_flags(blue_teams, blue.get("surrogate_team_keys"))
        synthetic_matches.append({
            "red": red_teams, "blue": blue_teams,
            "red_surrogate": red_flags, "blue_surrogate": blue_flags,
        })
        teams_seen.update(red_teams)
        teams_seen.update(blue_teams)

    # Compose a minimal day_config from TBA's first/last match times. The view
    # page primarily needs day windows for time computation, but for TBA-sourced
    # data the times come straight from TBA so we don't need elaborate breaks.
    day_config = _synthesize_day_config_from_tba(qual_matches)

    return {
        "source": "tba",
        "id": None,  # No local schedule ID
        "name": tba_event.get("name") or event_key,
        "is_active": True,
        "event_id": event_id,
        "event": event_info,
        "abstract_schedule_id": None,
        "num_teams": len(teams_seen),
        "matches_per_team": (len(synthetic_matches) * 6 // len(teams_seen)) if teams_seen else 0,
        "cooldown": None,
        "seed": None, "assign_seed": None, "created_by": None,
        "slot_map": {},
        "matches": synthetic_matches,
        "practice_matches": [],  # TBA doesn't track practice
        "surrogate_count": sum(
            sum(m["red_surrogate"]) + sum(m["blue_surrogate"]) for m in synthetic_matches
        ),
        "round_boundaries": {},
        "day_config": day_config,
        "created_at": None,
    }


def _tba_key_to_num(key: str) -> int:
    """'frc2169' → 2169."""
    if not key: return 0
    s = key[3:] if key.startswith("frc") else key
    try: return int(s)
    except (ValueError, TypeError): return 0


def _surrogate_flags(team_list: list[int], surrogate_keys: list[str] | None) -> list[bool]:
    """Build a positional [bool, bool, bool] surrogate flag list from TBA's
    flat surrogate_team_keys array. Defaults to [False, False, False] if no
    surrogate data is present."""
    if not surrogate_keys:
        return [False, False, False]
    surrogate_nums = {_tba_key_to_num(k) for k in surrogate_keys}
    flags = [t in surrogate_nums for t in team_list]
    # Pad to length 3 to match the editor's data shape
    while len(flags) < 3:
        flags.append(False)
    return flags[:3]


def _resolve_practice_matches(
    practice_matches: list[dict] | None, slot_map: dict[int, int]
) -> list[dict]:
    """Translate practice match slot indices to real team numbers using slot_map.

    Practice matches are generated client-side from the abstract scheduler,
    so they're stored with slot indices (1..N) just like the qual abstract
    schedule. When returning an assigned schedule, both qual and practice
    matches need their slots translated to team numbers — otherwise the
    practice tab on /view shows slot numbers (looks broken) instead of real
    team numbers.

    Falls back to leaving values unchanged for any slot not in slot_map —
    older saved schedules might already contain real team numbers, and we
    don't want to lose them by mapping through a missing key.
    """
    if not practice_matches:
        return []
    out = []
    for m in practice_matches:
        out.append({
            "red":  [slot_map.get(s, s) for s in (m.get("red") or [])],
            "blue": [slot_map.get(s, s) for s in (m.get("blue") or [])],
            "red_surrogate":  m.get("red_surrogate")  or [False, False, False],
            "blue_surrogate": m.get("blue_surrogate") or [False, False, False],
        })
    return out


def _synthesize_day_config_from_tba(qual_matches: list[dict]) -> dict | None:
    """Build a minimal day_config from TBA match times. The view page uses this
    for break/cycle-time logic; for TBA data we just want a reasonable default
    so the schedule can render at all. The actual times shown will come from
    TBA's predicted_time/actual_time per match, not from day_config math."""
    times = [m.get("time") or m.get("predicted_time") or m.get("actual_time")
             for m in qual_matches]
    times = [t for t in times if t]
    if not times:
        return None
    from datetime import datetime as _dt, timezone as _tz
    first = _dt.fromtimestamp(min(times), tz=_tz.utc).astimezone()
    last  = _dt.fromtimestamp(max(times), tz=_tz.utc).astimezone()
    # Group matches by date, build a day per distinct calendar date
    days_by_date: dict[str, list[int]] = {}
    for t in sorted(times):
        d = _dt.fromtimestamp(t, tz=_tz.utc).astimezone()
        days_by_date.setdefault(d.strftime("%Y-%m-%d"), []).append(t)
    days = []
    for date_str, day_times in days_by_date.items():
        d_start = _dt.fromtimestamp(min(day_times), tz=_tz.utc).astimezone()
        d_end   = _dt.fromtimestamp(max(day_times), tz=_tz.utc).astimezone()
        days.append({
            "start": d_start.strftime("%H:%M"),
            "end":   d_end.strftime("%H:%M"),
            "breaks": [], "cycleChanges": [], "earlyEnd": None,
            "dateLabel": d_start.strftime("%a %b %d"),
        })
    return {
        "cycleTime": 8,  # ignored for TBA data — UI uses real times per match
        "breakBuffer": 5,
        "numDays": len(days),
        "days": days,
        "practiceDay": None,
    }


async def _build_assigned_payload(
    db: AsyncSession, assigned: AssignedSchedule, event: Event,
) -> dict:
    """Build the same payload as GET /api/assigned-schedules/{id} given a
    pre-loaded AssignedSchedule and its Event."""
    abstract = assigned.abstract_schedule
    slot_map = {int(k): v for k, v in (assigned.slot_map or {}).items()}
    resolved_matches = [
        {"red": [slot_map[s] for s in m["red"]], "blue": [slot_map[s] for s in m["blue"]],
         "red_surrogate": m["red_surrogate"], "blue_surrogate": m["blue_surrogate"]}
        for m in (abstract.matches or [])
    ]
    resolved_practice_matches = _resolve_practice_matches(assigned.practice_matches, slot_map)
    return {
        "id": assigned.id, "name": assigned.name, "is_active": assigned.is_active,
        "event_id": assigned.event_id,
        "event": {
            "id": event.id, "key": event.key, "name": event.name,
            "year": event.year, "location": event.location,
            "branding": event.branding or {},
        },
        "abstract_schedule_id": assigned.abstract_schedule_id,
        "num_teams": abstract.num_teams, "matches_per_team": abstract.matches_per_team,
        "cooldown": abstract.cooldown, "seed": abstract.seed,
        "assign_seed": assigned.assign_seed, "created_by": assigned.created_by,
        "slot_map": assigned.slot_map, "matches": resolved_matches,
        "practice_matches": resolved_practice_matches,
        "surrogate_count": abstract.surrogate_count,
        "round_boundaries": abstract.round_boundaries,
        "day_config": assigned.day_config,
        "created_at": assigned.created_at.isoformat(),
    }





# ── Live event data ───────────────────────────────────────────────────────────
# These endpoints power /view's live-mode UI: scores, current match, drift,
# rankings, and queue status. Data is sourced from TBA + Nexus webhooks, with
# a simulator for offline testing. Refresh is lazy + throttled — multiple
# clients viewing the same event don't multiply API calls.


@app.get("/api/events/{event_id}/live")
async def get_event_live(
    event_id: int,
    db: AsyncSession = Depends(get_session),
    refresh: bool = Query(True, description="Whether to attempt a TBA refresh before returning"),
    force: bool = Query(False, description="Bypass the 30s throttle on TBA refreshes"),
):
    """Aggregated live data for the /view page. Returns current match results,
    rankings, queue status, drift estimate, and data-source availability flags.
    Lazily refreshes from TBA at most once per 30 seconds."""
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    refresh_result = None
    if refresh:
        refresh_result = await live_data.refresh_event(db, event, force=force)
    payload = await live_data.get_event_live_data(db, event)
    if refresh_result is not None:
        payload["refresh"] = {
            k: (v.isoformat() if hasattr(v, "isoformat") else v)
            for k, v in refresh_result.items()
        }
    return payload


@app.get("/api/events/by-key/{event_key}/live")
async def get_event_live_by_key(
    event_key: str,
    db: AsyncSession = Depends(get_session),
    refresh: bool = Query(True),
    force: bool = Query(False),
):
    """Same as /api/events/{event_id}/live but resolves by event key. Use this
    for events that only exist on TBA (no local Event row). If a local Event
    row exists for this key, this is equivalent to the numeric variant."""
    res = await db.execute(select(Event).where(Event.key == event_key))
    event = res.scalar_one_or_none()
    # If the event isn't in our DB at all, create a minimal local Event row
    # so live data has something to attach to (rankings, sync state, etc.).
    # This is the "we're a parser of TBA data" path — we still need to track
    # per-event metadata locally for lazy refresh throttling and freshness.
    if not event:
        try:
            tba_event = await tba_client.get_event(event_key)
        except Exception:
            tba_event = None
        if not tba_event:
            raise HTTPException(404, f"Event '{event_key}' not found locally or on TBA")
        event = Event(
            key=event_key,
            name=tba_event.get("name") or event_key,
            year=tba_event.get("year") or 0,
            location=", ".join(filter(None, [
                tba_event.get("city"), tba_event.get("state_prov"),
                tba_event.get("country"),
            ])) or None,
            tba_synced=True,
        )
        db.add(event)
        await db.flush()
        await db.commit()
    refresh_result = None
    if refresh:
        refresh_result = await live_data.refresh_event(db, event, force=force)
    payload = await live_data.get_event_live_data(db, event)
    if refresh_result is not None:
        payload["refresh"] = {
            k: (v.isoformat() if hasattr(v, "isoformat") else v)
            for k, v in refresh_result.items()
        }
    return payload


@app.post("/api/events/{event_id}/simulate/start")
async def start_event_simulation(
    event_id: int,
    speedup: float = Query(60.0, gt=0, le=3600, description="1.0 = real-time, 60 = 1 sec per sim minute"),
    db: AsyncSession = Depends(get_session),
):
    """Begin simulating event progress for testing live mode. Generates fake
    match results based on the active assigned schedule. Replaces TBA as the
    data source until simulate/stop is called."""
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    return await live_data.start_simulation(db, event_id, speedup=speedup)


@app.post("/api/events/{event_id}/simulate/stop")
async def stop_event_simulation(event_id: int, db: AsyncSession = Depends(get_session)):
    """End simulation and clear simulated data."""
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    return await live_data.stop_simulation(db, event_id)


@app.post("/api/webhooks/nexus")
async def nexus_webhook(request: Request, db: AsyncSession = Depends(get_session)):
    """Receive a Nexus event webhook. Validates the configured token and
    upserts queue status into our DB. Configure the webhook URL in Nexus's
    settings page; configure the token via NEXUS_WEBHOOK_TOKEN env var."""
    expected_token = os.environ.get("NEXUS_WEBHOOK_TOKEN", "")
    if expected_token:
        provided = request.headers.get("Nexus-Token") or request.headers.get("x-nexus-token") or ""
        if provided != expected_token:
            raise HTTPException(403, "Invalid Nexus token")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")
    return await live_data.ingest_nexus_event(db, payload)


# ── Statbotics integration ──────────────────────────────────────────────────
#
# Statbotics provides EPA (Expected Points Added) ratings — basically Elo
# but in match-point units, with auto/teleop/endgame splits. Free public API.
# We fetch on-demand per (team, event) when the user expands a team panel.


@app.get("/api/statbotics/team-event/{team_number}/{event_key}")
async def get_statbotics_team_event(team_number: int, event_key: str):
    """Get EPA stats for a team at an event. Returns 404 if Statbotics
    doesn't have data (happens for off-season events outside their dataset
    or for teams that haven't played any matches yet)."""
    raw = await statbotics_client.get_team_event(team_number, event_key)
    if not raw:
        # Try team-year as a fallback for pre-event lookups
        # Extract year from event_key (e.g., '2026mnst' → 2026)
        try:
            year = int(event_key[:4])
            raw_year = await statbotics_client.get_team_year(team_number, year)
            if raw_year:
                # Normalize team-year payload to look like team-event for frontend
                epa = raw_year.get("epa") or {}
                return {
                    "team": team_number, "year": year, "event": None,
                    "team_name": raw_year.get("team_name") or raw_year.get("name"),
                    "norm_epa": epa.get("norm") or raw_year.get("norm_epa"),
                    "epa_end": (epa.get("stats") or {}).get("end"),
                    "auto_epa": (epa.get("breakdown") or {}).get("auto_points"),
                    "teleop_epa": (epa.get("breakdown") or {}).get("teleop_points"),
                    "endgame_epa": (epa.get("breakdown") or {}).get("endgame_points"),
                    "predicted_rank": None,
                    "wins": (raw_year.get("record") or {}).get("wins"),
                    "losses": (raw_year.get("record") or {}).get("losses"),
                    "ties": (raw_year.get("record") or {}).get("ties"),
                    "winrate": (raw_year.get("record") or {}).get("winrate"),
                    "_source": "team_year_fallback",
                }
        except (ValueError, TypeError):
            pass
        raise HTTPException(404, "Not found in Statbotics")
    return statbotics_client.normalize_team_event(raw)


# ── Scheduler defaults ────────────────────────────────────────────────────────
# Exposes the canonical FIRST-aligned weight defaults so the editor's "Advanced
# criteria" panel can show "what FIRST does" and compare against user's choices.


@app.get("/api/scheduler/defaults")
async def scheduler_defaults():
    """Return the FIRST-aligned default weights for placement criteria. The
    editor uses this to populate the Advanced Criteria panel and to detect
    when the user has deviated from canonical FIRST settings (which triggers
    a notice indicating non-standard configuration)."""
    from app import scheduler as sched
    return {
        "defaults": sched.DEFAULT_WEIGHTS,
        "first_strict": sched.FIRST_STRICT_WEIGHTS,
        # Documentation surfaces what each weight does, so the UI can render
        # tooltips without hardcoding strings.
        "descriptions": {
            "balance":  "Penalty per unit of red/blue imbalance per team. FIRST balances each team's red vs blue appearances.",
            "gap":      "Bonus per match-cycle of waiting between a team's appearances. Encourages spacing.",
            "count":    "Penalty for over-scheduling; tie-breaker within iteration scoring.",
            "opponent": "Penalty per cross-alliance opponent repeat. Quadratic — second repeat costs 4× first.",
            "partner":  "Penalty per same-alliance partner repeat. Higher than opponent (FIRST: only 2 partners but 3 opponents per match).",
            "station":  "Penalty for uneven station appearances. FIRST balances all 6 stations (R1-R3, B1-B3).",
            "sur_rpt":  "Penalty for surrogate concentration on the same teams.",
        },
    }


# ── Diversity report ──────────────────────────────────────────────────────────
# Computes the actual distribution metrics for a generated schedule — partner
# repeat histogram, opponent repeat histogram, station balance per team,
# surrogate placement, worst-case callouts. The frontend renders this as a
# panel below the generated schedule.


@app.get("/api/abstract-schedules/{schedule_id}/diversity-report")
async def get_diversity_report(schedule_id: int):
    """Return per-pair partner/opponent repeat distributions, station balance
    per slot, surrogate distribution, and worst-case callouts. All metrics
    are computed against slot indices (1..N), not real team numbers — this
    works on Stage 1 abstract schedules. The frontend can map slots → teams
    after the fact for display.
    """
    import math
    async with AsyncSessionLocal() as db:
        sched = await db.get(AbstractSchedule, schedule_id)
        if not sched:
            raise HTTPException(404, "Abstract schedule not found")

        N = sched.num_teams
        MPT = sched.matches_per_team
        matches = sched.matches  # list of {red, blue, red_surrogate, blue_surrogate}

        # ── Pair counts ────────────────────────────────────────────────────
        # partner[a][b] = # of times slots a and b shared an alliance
        # opponent[a][b] = # of times slots a and b were on opposing alliances
        # Indices are 1-based; index 0 unused.
        partner  = [[0] * (N + 1) for _ in range(N + 1)]
        opponent = [[0] * (N + 1) for _ in range(N + 1)]
        # Station counts per slot — 6 positions (R1, R2, R3, B1, B2, B3)
        station = [[0] * 6 for _ in range(N + 1)]
        # Surrogate count per slot
        surrogate = [0] * (N + 1)

        for m in matches:
            red = m["red"]; blue = m["blue"]
            for i, t in enumerate(red):
                station[t][i] += 1
            for i, t in enumerate(blue):
                station[t][3 + i] += 1
            for i, s in enumerate(m.get("red_surrogate", [False] * 3)):
                if s: surrogate[red[i]] += 1
            for i, s in enumerate(m.get("blue_surrogate", [False] * 3)):
                if s: surrogate[blue[i]] += 1
            # Same-alliance pairs
            for a_list in (red, blue):
                for i in range(len(a_list)):
                    for j in range(i + 1, len(a_list)):
                        x, y = a_list[i], a_list[j]
                        partner[x][y] += 1
                        partner[y][x] += 1
            # Cross-alliance opponents
            for r in red:
                for b in blue:
                    opponent[r][b] += 1
                    opponent[b][r] += 1

        # ── Theoretical floors ────────────────────────────────────────────
        # Each slot has 2 partners × MPT total partner-slots = 2*MPT encounters
        # spread across N-1 possible partners. Best-case avg = 2*MPT/(N-1).
        # If 2*MPT < (N-1), some pairs MUST be at 0 — floor is 0.
        # If 2*MPT >= (N-1), some pairs MUST be at 1+ — floor is ceil(2*MPT/(N-1)).
        partner_floor  = math.ceil((2 * MPT) / max(1, N - 1)) if N > 1 else 0
        opponent_floor = math.ceil((3 * MPT) / max(1, N - 1)) if N > 1 else 0

        # ── Pair distribution (only count each unordered pair once: a < b) ─
        partner_hist  = {}   # repeat_count → number_of_pairs
        opponent_hist = {}
        partner_max = 0; opponent_max = 0
        partner_sum = 0; opponent_sum = 0
        zero_partner_pairs = 0; zero_opponent_pairs = 0
        # Worst-case pairs (over the floor)
        worst_partner = []   # [{slots: [a, b], count: n}]
        worst_opponent = []
        for a in range(1, N + 1):
            for b in range(a + 1, N + 1):
                p = partner[a][b]
                o = opponent[a][b]
                partner_hist[p]  = partner_hist.get(p, 0) + 1
                opponent_hist[o] = opponent_hist.get(o, 0) + 1
                partner_sum += p; opponent_sum += o
                if p == 0: zero_partner_pairs += 1
                if o == 0: zero_opponent_pairs += 1
                if p > partner_max:  partner_max = p
                if o > opponent_max: opponent_max = o
                if p > partner_floor:
                    worst_partner.append({"slots": [a, b], "count": p})
                if o > opponent_floor:
                    worst_opponent.append({"slots": [a, b], "count": o})
        worst_partner.sort(key=lambda x: -x["count"])
        worst_opponent.sort(key=lambda x: -x["count"])
        total_pairs = (N * (N - 1)) // 2

        # ── Per-slot table ────────────────────────────────────────────────
        # For each slot: distinct partners, distinct opponents, station balance
        slot_table = []
        for t in range(1, N + 1):
            distinct_partners  = sum(1 for x in range(1, N + 1) if x != t and partner[t][x] > 0)
            distinct_opponents = sum(1 for x in range(1, N + 1) if x != t and opponent[t][x] > 0)
            sta = station[t]
            station_imbalance = (max(sta) - min(sta)) if any(sta) else 0
            slot_table.append({
                "slot": t,
                "distinct_partners":  distinct_partners,
                "distinct_opponents": distinct_opponents,
                "max_partners":  2 * MPT,
                "max_opponents": 3 * MPT,
                "stations": sta,
                "station_imbalance": station_imbalance,
                "surrogate_count": surrogate[t],
            })

        # ── Headline numbers ──────────────────────────────────────────────
        avg_partner  = partner_sum / total_pairs if total_pairs else 0.0
        avg_opponent = opponent_sum / total_pairs if total_pairs else 0.0
        max_station_imbalance = max((s["station_imbalance"] for s in slot_table), default=0)

        return {
            "schedule_id": schedule_id,
            "num_teams":   N,
            "matches_per_team": MPT,
            "total_pairs": total_pairs,
            "partner": {
                "histogram":   partner_hist,
                "max":         partner_max,
                "floor":       partner_floor,
                "average":     round(avg_partner, 3),
                "zero_pairs":  zero_partner_pairs,
                "worst_pairs": worst_partner[:10],   # limit for UI
            },
            "opponent": {
                "histogram":   opponent_hist,
                "max":         opponent_max,
                "floor":       opponent_floor,
                "average":     round(avg_opponent, 3),
                "zero_pairs":  zero_opponent_pairs,
                "worst_pairs": worst_opponent[:10],
            },
            "stations": {
                "max_imbalance":     max_station_imbalance,
                "imbalanced_slots":  sum(1 for s in slot_table if s["station_imbalance"] > 1),
            },
            "surrogates": {
                "total":      sum(surrogate),
                "max_per_slot": max(surrogate) if N > 0 else 0,
                "concentrated_slots": sum(1 for x in surrogate if x > 1),
            },
            "slots": slot_table,
        }


# ── PDF schedule import (LLM-powered) ────────────────────────────────────────
#
# Accepts an arbitrary schedule PDF, extracts table content, sends to a
# self-hosted LLM (vLLM or llama.cpp via OpenAI-compatible HTTP) for
# parsing, validates the result, returns a preview the user confirms
# before committing.
#
# Configured via env vars LLM_ENDPOINT, LLM_MODEL, LLM_API_KEY. When
# unconfigured, this endpoint refuses with a clear error — there's no
# fallback yet (a deterministic MSHSL parser is potential future work).
#
# Cached by SHA-256 of file content: same PDF re-uploaded → no LLM call,
# instant response. Cache stored in pdf_imports table.


class PdfImportPreview(BaseModel):
    """Response shape for /api/schedules/import-pdf"""
    pdf_import_id:    int
    pdf_hash:         str
    file_name:        str | None
    page_count:       int
    method:           str
    format_detected:  str | None
    matches:          list[dict]
    validation:       dict   # see app.pdf_validate.validate_schedule
    notes:            str    # LLM's free-form notes


class PdfImportCommitRequest(BaseModel):
    """Body for /api/schedules/import-pdf/commit"""
    pdf_import_id: int
    event_id:      int
    name:          str = Field("Imported Schedule", max_length=128)
    # User may have edited the matches in the preview UI before confirming.
    # If provided, use these instead of the cached parsed matches.
    matches:       list[dict] | None = None
    day_config:    Any = None


@app.post("/api/schedules/import-pdf")
async def import_pdf(
    file: UploadFile = File(...),
    event_id: int | None = Query(None),
    current_user: dict | None = Depends(get_current_user),
):
    """Parse a schedule PDF using the configured LLM. Returns a preview
    that the user confirms (or edits) before committing via /commit.

    The result is cached by content hash, so re-uploading the same file
    is free.

    Cross-checks against the event roster when event_id is provided —
    catches OCR errors that produce team numbers not in the roster.
    """
    if not llm_client.is_configured():
        raise HTTPException(
            503,
            "PDF import requires an LLM endpoint. Set LLM_ENDPOINT and LLM_MODEL "
            "in the deployment secrets, or import via TBA event key instead. "
            "See docs/INTEGRATIONS.md for setup."
        )

    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty file")
    if not (content[:4] == b"%PDF"):
        raise HTTPException(400, "File is not a PDF (missing %PDF header)")

    pdf_hash = pdf_extract.hash_pdf(content)

    # Check cache first — same PDF, no LLM call needed
    async with AsyncSessionLocal() as db:
        existing = await db.execute(
            select(PdfImport).where(PdfImport.pdf_hash == pdf_hash)
        )
        cached = existing.scalar_one_or_none()
        if cached:
            log.info("PDF cache hit: %s (%s)", pdf_hash[:8], file.filename)
            # Re-run validation in case the validator has improved since
            # the cache entry was written, OR roster has changed
            roster = None
            if event_id:
                roster_result = await db.execute(
                    select(EventTeam.team_number).where(EventTeam.event_id == event_id)
                )
                roster = [r[0] for r in roster_result.all()] or None
            validation = pdf_validate.validate_schedule(cached.parsed.get("matches", []), roster)
            return {
                "pdf_import_id":   cached.id,
                "pdf_hash":        pdf_hash,
                "file_name":       cached.file_name,
                "page_count":      cached.page_count,
                "method":          cached.method,
                "format_detected": cached.format_detected,
                "matches":         cached.parsed.get("matches", []),
                "validation":      validation,
                "notes":           cached.parsed.get("notes", ""),
                "_cache":          "hit",
            }

    # Not cached — extract and call LLM
    try:
        extracted = pdf_extract.extract_tables(content)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        log.exception("PDF extraction failed")
        raise HTTPException(500, f"PDF extraction failed: {e}")

    # Refuse if estimated tokens exceed the LLM context window. 32K
    # leaves ~16K for output tokens.
    est_tokens = pdf_extract.estimate_token_budget(extracted)
    if est_tokens > 16000:
        raise HTTPException(
            413,
            f"PDF too long for LLM extraction: ~{est_tokens} input tokens "
            f"(max ~16000). Try a more focused document or split into pages."
        )

    pdf_text = pdf_extract.format_for_llm(extracted)

    try:
        parsed = await llm_client.parse_schedule(pdf_text)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    except ValueError as e:
        # LLM returned malformed JSON
        raise HTTPException(502, f"LLM returned malformed response: {e}")

    if not parsed:
        raise HTTPException(503, "LLM extraction not configured")

    matches = parsed.get("matches") or []
    if not matches:
        raise HTTPException(422, "LLM did not extract any matches from the PDF. "
                                  "Check that the PDF contains a qualification schedule.")

    # Pull roster for cross-check if event provided
    roster = None
    if event_id:
        async with AsyncSessionLocal() as db:
            roster_result = await db.execute(
                select(EventTeam.team_number).where(EventTeam.event_id == event_id)
            )
            roster = [r[0] for r in roster_result.all()] or None

    validation = pdf_validate.validate_schedule(matches, roster)

    # Save to cache regardless of validation pass — user may want to edit
    # bad parses rather than re-call the LLM
    async with AsyncSessionLocal() as db:
        pdf_import = PdfImport(
            pdf_hash=pdf_hash,
            file_name=file.filename,
            byte_size=len(content),
            page_count=extracted["page_count"],
            parsed=parsed,
            validation=validation,
            format_detected=parsed.get("format_detected"),
            method="llm",
        )
        db.add(pdf_import)
        await db.commit()
        await db.refresh(pdf_import)

    return {
        "pdf_import_id":   pdf_import.id,
        "pdf_hash":        pdf_hash,
        "file_name":       file.filename,
        "page_count":      extracted["page_count"],
        "method":          "llm",
        "format_detected": parsed.get("format_detected"),
        "matches":         matches,
        "validation":      validation,
        "notes":           parsed.get("notes", ""),
        "_cache":          "miss",
    }


@app.post("/api/schedules/import-pdf/commit")
async def commit_pdf_import(
    body: PdfImportCommitRequest,
    current_user: dict | None = Depends(get_current_user),
):
    """Commit a previewed PDF import as a real AssignedSchedule.

    The user confirms (and optionally edits) the parsed matches before
    calling this. We DON'T auto-commit — bad parses can corrupt schedules
    and the cost of a manual review step is small vs the cost of importing
    a wrong schedule.
    """
    async with AsyncSessionLocal() as db:
        pdf_import = await db.get(PdfImport, body.pdf_import_id)
        if not pdf_import:
            raise HTTPException(404, "PDF import not found")
        event = await db.get(Event, body.event_id)
        if not event:
            raise HTTPException(404, "Event not found")

        # Use user-edited matches if provided, else cached parse
        matches = body.matches if body.matches is not None else pdf_import.parsed.get("matches", [])
        if not matches:
            raise HTTPException(400, "No matches to commit")

        # Final validation. If user submitted edited matches that have errors,
        # bail with a useful message — don't silently corrupt the schedule.
        roster_result = await db.execute(
            select(EventTeam.team_number).where(EventTeam.event_id == body.event_id)
        )
        roster = [r[0] for r in roster_result.all()] or None
        validation = pdf_validate.validate_schedule(matches, roster)
        if not validation["ok"]:
            err_summary = "; ".join(e["message"] for e in validation["errors"][:3])
            raise HTTPException(
                422,
                f"Validation failed: {err_summary}. Edit the preview and try again."
            )

        stats = validation["stats"]
        N = stats["num_teams"]
        MPT = stats["mpt_normal"]

        # Build a slot-based abstract schedule + slot map. Imported schedules
        # don't have a "real" abstract schedule (no seed, no iterations) — we
        # synthesize one to fit the existing data model so /view and the
        # preview pipeline work uniformly.
        # Slot indices are assigned by first-appearance order of teams.
        team_to_slot: dict[int, int] = {}
        next_slot = 1
        abstract_matches: list[dict] = []
        for m in sorted(matches, key=lambda x: x.get("match_num", 0)):
            red_slots = []
            for t in m.get("red") or []:
                if t not in team_to_slot:
                    team_to_slot[t] = next_slot; next_slot += 1
                red_slots.append(team_to_slot[t])
            blue_slots = []
            for t in m.get("blue") or []:
                if t not in team_to_slot:
                    team_to_slot[t] = next_slot; next_slot += 1
                blue_slots.append(team_to_slot[t])
            abstract_matches.append({
                "red":            red_slots,
                "blue":           blue_slots,
                "red_surrogate":  m.get("red_surrogate")  or [False, False, False],
                "blue_surrogate": m.get("blue_surrogate") or [False, False, False],
            })
        slot_map = {str(slot): team for team, slot in team_to_slot.items()}

        # Synthesize round_boundaries — assume one round per ceil(N/6) matches
        # in the absence of source-specific information
        import math
        matches_per_round = max(1, math.ceil(N / 6))
        round_boundaries = {
            str(r + 1): r * matches_per_round
            for r in range(math.ceil(len(matches) / matches_per_round))
        }

        # Surrogate count per slot
        surrogate_count = [0] * (N + 1)
        for am in abstract_matches:
            for i, s in enumerate(am["red"]):
                if am["red_surrogate"][i]: surrogate_count[s] += 1
            for i, s in enumerate(am["blue"]):
                if am["blue_surrogate"][i]: surrogate_count[s] += 1

        sched = AbstractSchedule(
            event_id=body.event_id, name=body.name + " (abstract)",
            num_teams=N, matches_per_team=MPT,
            cooldown=1, seed=None,  # imported — no seed
            iterations_run=0, best_iteration=0, score=0.0,
            created_by=current_user["sub"] if current_user else None,
            matches=abstract_matches, surrogate_count=surrogate_count,
            round_boundaries=round_boundaries, day_config=body.day_config,
            weights=None,
        )
        db.add(sched)
        await db.flush()

        # Deactivate any prior active schedule on this event
        await db.execute(
            update(AssignedSchedule)
            .where(AssignedSchedule.event_id == body.event_id)
            .values(is_active=False)
        )
        assigned = AssignedSchedule(
            abstract_schedule_id=sched.id, event_id=body.event_id,
            name=body.name, is_active=True,
            slot_map=slot_map, day_config=body.day_config,
            practice_matches=[],   # imports don't include practice
            assign_seed=None,
            created_by=current_user["sub"] if current_user else None,
        )
        db.add(assigned)
        await db.flush()

        # Materialize MatchRow records for queryability
        slot_map_int = {int(k): v for k, v in slot_map.items()}
        for i, am in enumerate(abstract_matches, start=1):
            db.add(MatchRow(
                assigned_schedule_id=assigned.id, match_num=i,
                red1=slot_map_int[am["red"][0]], red2=slot_map_int[am["red"][1]], red3=slot_map_int[am["red"][2]],
                blue1=slot_map_int[am["blue"][0]], blue2=slot_map_int[am["blue"][1]], blue3=slot_map_int[am["blue"][2]],
            ))

        await db.commit()

        return {
            "abstract_schedule_id": sched.id,
            "assigned_schedule_id": assigned.id,
            "name":                 assigned.name,
            "matches_imported":     len(matches),
            "teams":                N,
        }


@app.get("/api/llm/status")
async def llm_status():
    """Returns LLM availability for the UI to surface in the import button."""
    return await llm_client.health_check()


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
