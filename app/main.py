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
from fastapi import Depends, FastAPI, File, HTTPException, Path, Query, Request, UploadFile, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.db import (
    AbstractSchedule, AssignedSchedule, AssignedScheduleHistory,
    AssignedScheduleLockEvent, AsyncSessionLocal,
    Event, EventTeam, MatchResult, MatchRow, PdfImport, Team, User,
    get_session, init_db,
)
from app.scheduler import run_iterations_worker, run_assignment_chunk
from app.quality_presets import (
    QUALITY_PRESETS, DEFAULT_PRESET, MAX_ITERATIONS,
    iterations_for_preset, preset_for_iterations,
)
from app.frc_compliance import (
    FRC_DEFAULTS, DEFAULT_COOLDOWN,
    compute_deviations, is_competition_approved, build_audit_record,
)
from app import live as live_data
from app import statbotics as statbotics_client
from app import tba as tba_client
from app import frc_events as frc_client
from app import pdf_extract
from app import pdf_dayplan
from app import pdf_render
from app import pdf_validate
from app import xlsx_extract
from app import csv_extract
from app import schedule_derive
from app import llm_client
from app import day_config_v2
from app.day_config_v2 import normalize_to_v2, validate_v2, is_v2_shape
from app.quality import compute_diversity_report
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


# ── day_config V2 normalization helper ────────────────────────────────────────
def _normalize_dc(dc: object, *, allow_none: bool = True) -> dict | None:
    """Normalize an incoming day_config to V2 shape and validate it.

    Called at the top of every write endpoint that accepts a
    body.day_config payload. Centralizes the shape contract so write
    sites don't need to know about V1 vs V2 — they always store V2.

    Behavior:
    * None or missing: returns None (when allow_none, the typical case)
      or raises 400 (when the endpoint requires day_config).
    * V1-shape: migrated to V2 via day_config_v2.migrate_v1_to_v2.
    * V2-shape: validated against the V2 Pydantic model.
    * Invalid V2: raises HTTP 400 with the validation error.

    The returned dict is JSON-serializable and ready to write to the
    DB column. Pydantic's model_dump() with mode='json' converts
    Decimal/datetime/etc. to JSON-native types if any sneak in.
    """
    if dc is None:
        if allow_none:
            return None
        raise HTTPException(400, "day_config is required")
    if not isinstance(dc, dict):
        raise HTTPException(400, "day_config must be an object")

    # Normalize shape: migrate V1 to V2 if needed. Idempotent on V2.
    normalized = normalize_to_v2(dc)
    if normalized is None:
        # Shouldn't happen for dict input — normalize_to_v2 only
        # returns None for None or non-dict — but handle defensively.
        raise HTTPException(400, "day_config could not be normalized to V2")

    # Validate against V2 schema. Reject malformed input loud and
    # early rather than letting it sit in the DB as a time bomb.
    try:
        validated = validate_v2(normalized)
    except Exception as exc:
        # Pydantic ValidationError serializes to a readable string
        # via str(exc); FastAPI surfaces this back to the client.
        raise HTTPException(400, f"day_config validation failed: {exc}") from exc

    # model_dump(mode='json') gives a plain dict suitable for JSON
    # storage. Use exclude_none=False so reserved fields (alliances,
    # matches) round-trip as empty arrays rather than disappearing.
    return validated.model_dump(mode='json')


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


# Catch-all for unhandled exceptions. Without this, FastAPI returns a
# generic "Internal Server Error" with no JSON body and the user has
# nowhere to look but pod logs (which they may not have access to). With
# it, the user sees the actual exception type+message in the browser
# AND we still log the full traceback to pod stdout. Don't put sensitive
# data in exception messages — they're now externally visible. (We rely
# on Python's standard practice of not putting secrets in exception
# strings, which holds across our codebase.)
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # FastAPI already handles HTTPException — this only fires for things
    # that escaped all other handlers. Log full traceback to pod stdout.
    log.exception(
        "Unhandled exception in %s %s",
        request.method, request.url.path,
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": f"{type(exc).__name__}: {str(exc)[:500]}",
            "path":   str(request.url.path),
        },
    )


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


# ── Apple Sign-In domain verification ─────────────────────────────────────────
# Apple requires the server to host an "association file" at a well-known
# URL before it will issue Sign In with Apple credentials for the domain.
# When the operator has configured Apple sign-in, they download the file
# from Apple's developer portal and place it on disk; we serve it from a
# configurable path via APPLE_DOMAIN_ASSOCIATION_FILE.
#
# When the env var is unset OR the file doesn't exist, the route returns
# 404. Apple's verifier reads this file once during Service-ID setup to
# confirm domain ownership. After verification succeeds, the file isn't
# strictly required to remain in place — but leaving it served is harmless
# and lets re-verification (e.g. after rotating credentials) succeed
# without redeploying.
#
# The file MUST be served as Content-Type text/plain or
# application/octet-stream — Apple's verifier rejects HTML.
APPLE_DOMAIN_ASSOCIATION_FILE = os.getenv("APPLE_DOMAIN_ASSOCIATION_FILE", "")


@app.get("/.well-known/apple-developer-domain-association",
         include_in_schema=False)
async def apple_domain_association():
    """Serve the Apple domain-association file when configured.

    Returns 404 when APPLE_DOMAIN_ASSOCIATION_FILE is unset or points at
    a missing file. Apple's verifier follows the GET, expects 200 with
    text/plain content matching what the developer portal generated.
    """
    if not APPLE_DOMAIN_ASSOCIATION_FILE:
        raise HTTPException(404, "Apple domain association not configured")
    if not os.path.isfile(APPLE_DOMAIN_ASSOCIATION_FILE):
        raise HTTPException(404, "Apple domain association file not found")
    # Serve as text/plain — Apple's verifier rejects HTML responses
    return FileResponse(
        APPLE_DOMAIN_ASSOCIATION_FILE,
        media_type="text/plain",
    )


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
    cooldown:         int        = Field(2, ge=1, le=20)
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
    # Quality preset: 'fair' | 'good' | 'best' | 'maximum'. Resolves to
    # an iteration count via app.quality_presets. If both quality_preset
    # and iterations are provided, iterations takes precedence (advanced
    # users tuning specific runs). If neither is provided, defaults to
    # the DEFAULT_PRESET ('good').
    #
    # Tuned per docs/scheduler/ITERATION_CEILING.md sweep on Stark.
    # K* (tight criterion) is documented as > 5M, not found within range.
    quality_preset:       str | None = Field(None, pattern="^(fair|good|best|maximum)$")
    iterations:           int | None = Field(None, ge=1, le=MAX_ITERATIONS)
    assign_seed:          str | None = Field(None, max_length=16)
    name:                 str        = Field("Schedule", max_length=128)
    day_config:           Any        = None
    practice_matches:     Any        = None

    # ── FRC §10.5.2 compliance ─────────────────────────────────────
    # competition_approved is a UI hint. The actual compliance status
    # is computed server-side from the algorithm toggles and stored
    # in AssignedSchedule.competition_approved + audit_trail.
    # Default True (UI checkbox starts checked).
    #
    # If a user submits competition_approved=True but ALSO submits
    # algorithm overrides that violate FRC defaults (e.g., disabling
    # the R/B post-pass), the server detects the contradiction and
    # records the actual deviations — competition_approved is set
    # to False regardless of the request hint.
    competition_approved: bool       = Field(True)

    # ── Algorithm toggles (optional advanced controls) ─────────────
    # All default to FRC-compliant values. Setting any to non-default
    # creates a deviation in the audit trail.
    rb_post_pass:         bool       = Field(True,
        description="Phase 1 R/B balance post-pass (FRC #5)")
    station_post_pass:    bool       = Field(True,
        description="Phase 2 station-balance post-pass (FRC #6)")
    cooldown:             int        = Field(2, ge=1, le=20,
        description="ideal_gap between matches per team; project default 2 per F1-e methodology decision (FRC §10.5.2 paramount-as-a-floor); user-tunable per event")

    def resolved_iterations(self) -> int:
        """Resolve the effective iteration count.

        Precedence: explicit iterations > quality_preset > DEFAULT_PRESET.
        """
        if self.iterations is not None:
            return self.iterations
        preset = self.quality_preset or DEFAULT_PRESET
        return iterations_for_preset(preset)

    def settings_dict(self) -> dict:
        """Build the settings dict for FRC compliance computation.

        Returns the algorithm-level settings (NOT iteration count or
        cooldown — those are audited separately and don't unset
        competition_approved).
        """
        return {
            'rb_post_pass':       self.rb_post_pass,
            'station_post_pass':  self.station_post_pass,
            'lex_score':          True,    # always on after Phase 0a
            'hard_cooldown':      True,    # always on after Phase 0b
            'targeted_moves':     True,    # always on after Phase 0c
            'weights':            None,    # no custom weights in this endpoint
            'surrogate_handling': '3rd_match_as_surrogate',
        }


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
async def create_event(
    body: EventCreate,
    db: AsyncSession = Depends(get_session),
    user: dict = Depends(require_auth),
):
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
    user: dict = Depends(require_auth),
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

    Authorization: auth required (Phase A); event freeze respected
    (only freezer or admin can change branding on a frozen event).
    """
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    if _is_event_frozen(event, user):
        raise HTTPException(
            status_code=423,
            detail=f"Event is frozen by {event.locked_by_name or 'another user'} "
                   "— only the freezer or an admin can change branding.",
        )
    # Replace, don't merge — caller has the full object. Use empty dict to clear.
    event.branding = branding if isinstance(branding, dict) else {}
    await db.commit()
    return {"id": event.id, "branding": event.branding}


@app.delete("/api/events/{event_id}", status_code=204)
async def delete_event(
    event_id: int,
    db: AsyncSession = Depends(get_session),
    user: dict = Depends(require_auth),
):
    """Delete an event and everything under it.

    Authorization layering:
      - Auth required (Phase A; was missing pre-fix)
      - Event freeze respected — frozen events can only be deleted
        by the freezer or an admin (Part 13)
      - Cascade deletion handles abstract_schedules,
        assigned_schedules, event_teams, etc. via FK ON DELETE
        CASCADE in the schema
    """
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    if _is_event_frozen(event, user):
        raise HTTPException(
            status_code=423,
            detail=f"Event is frozen by {event.locked_by_name or 'another user'} "
                   "— only the freezer or an admin can delete it.",
        )
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
async def tba_import_event(
    event_key: str = Path(..., max_length=64),
    db: AsyncSession = Depends(get_session),
    user: dict = Depends(require_auth),
):
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
    # Freeze check — only apply when an existing event would be
    # mutated (a fresh event create from import is permitted for
    # any authenticated user). Refresh-imports against a frozen
    # event by anyone except freezer/admin: 423.
    if event is not None and _is_event_frozen(event, user):
        raise HTTPException(
            status_code=423,
            detail=f"Event is frozen by {event.locked_by_name or 'another user'} "
                   "— TBA refresh-import would mutate event metadata and team "
                   "roster. Only the freezer or an admin can re-import.",
        )
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
async def frc_import_event(
    year: int = Path(..., ge=1992, le=2100),
    event_code: str = Path(..., max_length=32),
    db: AsyncSession = Depends(get_session),
    user: dict = Depends(require_auth),
):
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
    # Freeze check — only apply when an existing event would be
    # mutated. Refresh-imports against a frozen event by anyone
    # except freezer/admin: 423.
    if event is not None and _is_event_frozen(event, user):
        raise HTTPException(
            status_code=423,
            detail=f"Event is frozen by {event.locked_by_name or 'another user'} "
                   "— FRC Events refresh-import would mutate event metadata and "
                   "team roster. Only the freezer or an admin can re-import.",
        )
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


@app.get("/api/events/{event_id}/teams/export")
async def export_event_teams(event_id: int,
                             db: AsyncSession = Depends(get_session)):
    """Export the event's team list in FMS-import format.

    Returns a plain-text file with one team number per line, sorted
    ascending. This is the format accepted by FRC's FMS Off-Season
    "Import Teams from File" button — confirmed empirically. The
    same format is also accepted by TBA Event Wizard, Nexus, and
    most other community tools.

    Format notes:
      - One team number per line, no header
      - Plain integers; no padding, no commas, no quoting
      - Unix LF line endings; no trailing blank line
      - Sorted ascending so the file is human-scannable

    The file extension is .csv even though there are no commas:
      - FMS file picker filters typically include *.csv
      - The single-column shape is degenerate-CSV-compatible
      - Confirmed working against FMS Off-Season

    No auth required — this is a read-only export of data already
    visible on the event's public surfaces.
    """
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")

    result = await db.execute(
        select(EventTeam).options(selectinload(EventTeam.team))
        .where(EventTeam.event_id == event_id)
    )
    team_numbers = sorted(et.team.number for et in result.scalars())

    body = "\n".join(str(n) for n in team_numbers)
    if team_numbers:
        # No trailing newline — FMS validates each line and an empty
        # final line could be parsed as a missing team number.
        pass

    # Filename: "<event-key>-teams.csv" if the event has a key
    # (e.g. "2026mnst-teams.csv"); otherwise fall back to the event
    # id. Quotes around the filename in Content-Disposition handle
    # any spaces or special characters defensively.
    safe_key = (event.key or f"event-{event.id}").replace('"', '')
    filename = f"{safe_key}-teams.csv"

    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # Cache-Control is short — team list can change as
            # rosters are added/removed pre-event. 60s is enough to
            # absorb a double-click but not stale enough to hurt.
            "Cache-Control": "private, max-age=60",
        },
    )


@app.post("/api/events/{event_id}/teams", status_code=201)
async def add_team_to_event(
    event_id: int,
    body: TeamIn,
    db: AsyncSession = Depends(get_session),
    user: dict = Depends(require_auth),
):
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    if _is_event_frozen(event, user):
        raise HTTPException(
            status_code=423,
            detail=f"Event is frozen by {event.locked_by_name or 'another user'} "
                   "— team roster cannot change.",
        )
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
async def remove_team(
    event_id: int,
    team_number: int,
    db: AsyncSession = Depends(get_session),
    user: dict = Depends(require_auth),
):
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    if _is_event_frozen(event, user):
        raise HTTPException(
            status_code=423,
            detail=f"Event is frozen by {event.locked_by_name or 'another user'} "
                   "— team roster cannot change.",
        )
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
async def enrich_team(
    event_id: int,
    team_number: int,
    body: dict,
    db: AsyncSession = Depends(get_session),
    user: dict = Depends(require_auth),
):
    """Update team metadata (nickname, name).

    The Team row is shared across events, so freeze on event_id
    is informational only — editing a team's nickname doesn't
    affect the frozen event's snapshot. We still require auth and
    an existing event match for routing/audit purposes, but don't
    block on freeze (the same team in another active event would
    be unfairly blocked).
    """
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
    user: dict = Depends(require_auth),
):
    loop = asyncio.get_event_loop()
    pool = get_pool()
    _seed_int = int(body.seed, 16) if body.seed else None

    # Normalize day_config to V2 shape + validate. Done at request
    # entry (before the long-running stream) so a malformed payload
    # gets rejected immediately with a 400, not silently stored.
    body.day_config = _normalize_dc(body.day_config)

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
                    created_by=user["sub"] if user else None,
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
        "round_boundaries": sched.round_boundaries,
        # Normalize to V2 on read. Pre-migration rows store V1 shape;
        # the DB migration (phase 2) will rewrite them in place but
        # until that runs, this normalize-on-read keeps the API
        # contract V2-only. Idempotent on V2 inputs.
        "day_config": normalize_to_v2(sched.day_config),
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
    user: dict = Depends(require_auth),
):
    # Normalize day_config to V2 shape + validate. Same rationale as
    # generate_abstract: fail fast on malformed input rather than
    # storing a future bug.
    body.day_config = _normalize_dc(body.day_config)
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
        # Resolve iteration count from quality_preset or explicit iterations.
        # See app/quality_presets.py for the preset map.
        iterations = body.resolved_iterations()

        # Phase 0+ chunking strategy (corrected 2026-05-09):
        # Under FRC paramount lex SA, the optimizer needs MANY consecutive
        # iterations on a single trial to converge — splitting the budget
        # into small chunks produces near-construction-quality output
        # because each chunk barely warms up. Iteration sweep on Stark
        # (docs/scheduler/ITERATION_CEILING.md) confirms that par_quad
        # only reaches floor 252 with single-trial SA budgets ≥ 50K, and
        # opp_quad keeps improving up to and beyond 5M.
        #
        # Strategy: each worker runs the FULL iteration budget on its own
        # seed (best-of-N over independent trials). Wall-clock equals
        # single-trial time because workers run in parallel. With Stark's
        # 36 cores, "best" preset (2M iters) finishes in ~75s wall-clock
        # and produces ~best-of-36 quality.
        #
        # n_workers caps at actual_workers (avoid over-subscribing CPUs)
        # AND at a sensible best-of-N count (more workers don't help once
        # we have enough samples to cover the variance). 30 trials
        # matches the iteration sweep and reliably samples the lower tail.
        BEST_OF_N_TARGET = 30
        n_workers = min(actual_workers, BEST_OF_N_TARGET)
        # Each worker runs ONE trial at the full iteration budget.
        chunk_size = iterations
        chunks_per_worker = 1
        total_chunks = n_workers
        _aseed_int = int(body.assign_seed, 16) if body.assign_seed else None
        done_chunks  = 0
        best_result  = None

        sem = get_generation_semaphore()
        async with sem:
            futures = []
            for w in range(n_workers):
                worker_seed = (_aseed_int ^ (w * 99991)) if _aseed_int is not None else None
                # One full-budget trial per worker; no inner chunk loop.
                futures.append(loop.run_in_executor(
                    pool, run_assignment_chunk,
                    (abstract_matches, abstract_num_teams, team_numbers,
                     abstract_cooldown, chunk_size, w, worker_seed),
                ))
            for f in asyncio.as_completed(futures):
                try:
                    res = await f
                    done_chunks += 1
                    # Log per-worker timing — critical for diagnosing
                    # quality issues. Compares actual wall-clock to
                    # expected (~37-50μs/iter on dedicated CPU). Workers
                    # noticeably slower than that indicate CPU contention.
                    log.info(
                        "Stage 2 worker %s: iters=%s elapsed=%.1fs (%.0f μs/iter) tuple=%s",
                        res.get('worker_id', '?'),
                        res.get('iterations_done', '?'),
                        res.get('worker_elapsed_s', 0.0),
                        res.get('us_per_iter', 0.0),
                        res.get('score_tuple', '?'),
                    )
                    # Best-of-N comparison uses the FRC §10.5.2 lex tuple
                    # (lower is better) — authoritative for which trial wins.
                    # Fall back to score float for older worker results that
                    # lack score_tuple (shouldn't happen post-Phase-0a but
                    # the guard is cheap).
                    if best_result is None:
                        best_result = res
                    else:
                        new_t = res.get('score_tuple')
                        cur_t = best_result.get('score_tuple')
                        if new_t and cur_t:
                            if tuple(new_t) < tuple(cur_t):
                                best_result = res
                        else:
                            # Legacy fallback: higher score float = better
                            if res["score"] > best_result["score"]:
                                best_result = res
                    pct = int(done_chunks / total_chunks * 100)
                    # `done` and `total` are TRIAL counts (not iteration counts)
                    # under the new chunking. UI shows "5/30 trials complete".
                    progress_msg = {
                        'type':  'progress',
                        'done':  done_chunks,
                        'total': total_chunks,
                        'pct':   pct,
                        'score': best_result['score'],
                    }
                    yield f"data: {json.dumps(progress_msg)}\n\n"
                except Exception as e:
                    log.error("Stage 2 worker error: %s", e)

        if best_result is None:
            yield f"data: {json.dumps({'type':'error','message':'Assignment failed'})}\n\n"
            return

        async with AsyncSessionLocal() as db:
            # Event-freeze guard for new schedule creation. When the
            # event is frozen the user shouldn't be able to spin up
            # new schedules under it (matches the "no changes to the
            # event" semantics). Done here AFTER the assignment math
            # rather than at request entry because the assignment is
            # already done by this point — refusing here just means
            # we don't persist; the user gets a clean error.
            ev_check = await db.get(Event, body.event_id) if body.event_id else None
            if _is_event_frozen(ev_check):
                yield f"data: {json.dumps({'type':'error','message':'Event is frozen — cannot create new schedules.'})}\n\n"
                return
            await db.execute(
                update(AssignedSchedule)
                .where(AssignedSchedule.event_id == body.event_id)
                .values(is_active=False)
            )
            # Build the FRC compliance audit trail. This is server-authoritative
            # — even if the request's competition_approved hint is True, the
            # server detects deviations from the algorithm-level toggles and
            # sets the actual approval bit accordingly.
            settings = body.settings_dict()
            audit = build_audit_record(
                settings_used=settings,
                cooldown_used=body.cooldown,
                iterations_used=body.resolved_iterations(),
                preset_used=body.quality_preset,
            )
            assigned = AssignedSchedule(
                abstract_schedule_id=abstract_id, event_id=body.event_id,
                name=body.name, is_active=True,
                slot_map=best_result["slot_map"], day_config=body.day_config,
                practice_matches=body.practice_matches,
                assign_seed=body.assign_seed,
                created_by=user["sub"] if user else None,
                competition_approved=audit['competition_approved'],
                audit_trail=audit,
            )
            db.add(assigned)
            await db.flush()
            # Phase 0: best_result['matches'] contains the SA-optimized match
            # list with real team numbers. Use that directly rather than
            # re-applying slot_map to the original abstract_matches — the SA
            # may have changed which teams are in which match (which is
            # exactly the point: it's the optimization we want).
            optimized_matches = best_result.get("matches")
            if optimized_matches is None:
                # Defensive: legacy worker output may not include matches.
                # Fall back to slot_map-applied abstract.
                slot_map = {int(k): v for k, v in best_result["slot_map"].items()}
                optimized_matches = []
                for m in abstract_matches:
                    optimized_matches.append({
                        "red":            [slot_map[s] for s in m["red"]],
                        "blue":           [slot_map[s] for s in m["blue"]],
                        "red_surrogate":  list(m["red_surrogate"]),
                        "blue_surrogate": list(m["blue_surrogate"]),
                    })
            for i, om in enumerate(optimized_matches, start=1):
                db.add(MatchRow(
                    assigned_schedule_id=assigned.id, match_num=i,
                    red1=om["red"][0], red2=om["red"][1], red3=om["red"][2],
                    blue1=om["blue"][0], blue2=om["blue"][1], blue3=om["blue"][2],
                    red1_surrogate=om["red_surrogate"][0],
                    red2_surrogate=om["red_surrogate"][1],
                    red3_surrogate=om["red_surrogate"][2],
                    blue1_surrogate=om["blue_surrogate"][0],
                    blue2_surrogate=om["blue_surrogate"][1],
                    blue3_surrogate=om["blue_surrogate"][2],
                ))
            # Initial history row — captures the schedule as created.
            # Without this, history view would be empty until the
            # first PATCH lands. Action='create' so the UI can
            # distinguish "this is the original".
            await _snapshot_schedule_history(db, assigned, action="create", user=user)
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
    schedules = list(result.scalars())

    # Compute "has been edited" reliably from history rows rather
    # than via an updated_at-vs-created_at heuristic. Rationale: a
    # schedule's updated_at bumps every time ANY column changes —
    # including is_official, is_active, and is_locked transitions.
    # Marking a schedule official, promoting it to active, or
    # locking it via the auto-lock-on-mark-official path all fire
    # `onupdate=utcnow` and trip the heuristic. The result is the
    # active schedule (which gets is_active=true bumped on
    # promotion) showing "edited" even when nothing about its
    # content was changed.
    #
    # Ground truth: the history table only writes a 'patch' row
    # when content changes via PATCH endpoint, plus 'restore' for
    # restore actions. 'create', 'mark-official', and 'rename'
    # don't count as content edits. Aggregating these per schedule
    # in one query gives us a clean, accurate edited indicator.
    if schedules:
        ids = [s.id for s in schedules]
        from sqlalchemy import func
        hist_q = await db.execute(
            select(
                AssignedScheduleHistory.assigned_schedule_id,
                func.count(AssignedScheduleHistory.id),
            )
            .where(AssignedScheduleHistory.assigned_schedule_id.in_(ids))
            .where(AssignedScheduleHistory.action.in_(("patch", "restore")))
            .group_by(AssignedScheduleHistory.assigned_schedule_id)
        )
        edit_counts = dict(hist_q.all())
    else:
        edit_counts = {}

    # Include lock + official fields so the saved-schedules modal
    # can render indicators (🔒 ⭐ "edited") without a per-row GET.
    # `is_official` is the permanent commitment marker (one per
    # event), `content_edit_count` counts genuine content edits
    # since creation (excluding marker/lock/rename transitions).
    return [
        {"id": s.id, "name": s.name, "is_active": s.is_active,
         "abstract_schedule_id": s.abstract_schedule_id,
         "num_teams": s.abstract_schedule.num_teams,
         "matches_per_team": s.abstract_schedule.matches_per_team,
         # Cooldown is rendered in the saved-schedules header
         # ("36 teams · 8 mpt · cooldown 3 — 2 versions"). It lives
         # on AbstractSchedule, so we surface it here for the UI
         # to read without a second fetch. Same reasoning for
         # surrogate_count and score — readers occasionally need
         # them and the joined query is already loaded.
         "cooldown":          s.abstract_schedule.cooldown,
         "surrogate_count":   s.abstract_schedule.surrogate_count,
         "score":             s.abstract_schedule.score,
         "created_at": s.created_at.isoformat(),
         "updated_at": s.updated_at.isoformat() if s.updated_at else None,
         # Number of content-changing history rows ('patch' or
         # 'restore'). 0 = pristine since creation; ≥1 = edited.
         "content_edit_count": int(edit_counts.get(s.id, 0)),
         "locked_at":      s.locked_at.isoformat() if s.locked_at else None,
         "locked_by_name": s.locked_by_name,
         "is_official":      s.is_official,
         "official_at":      s.official_at.isoformat() if s.official_at else None,
         "official_by_name": s.official_by_name,
         "forked_from_id":   s.forked_from_id,
         # FRC §10.5.2 compliance status. NULL → pre-feature schedule
         # (UI renders as "approval status unknown"). True/False are
         # post-feature deterministic values.
         "competition_approved": s.competition_approved}
        for s in schedules
    ]


async def _build_assigned_schedule_response(assigned: AssignedSchedule, db: AsyncSession) -> dict:
    """Shared response builder for GET / PATCH / lock / unlock endpoints.

    Includes lock fields so the frontend can render the locked state
    on first load without a separate fetch. Lock fields are nullable
    (None when unlocked). Also includes is_official + official_*
    metadata so the UI can render the star indicator and gate
    the Delete button. Event-level lock state ships under
    `event.locked_at` so the editor can render the "event frozen"
    banner without a second fetch.

    Always fetches abstract_schedule explicitly via db.get() rather
    than dereferencing assigned.abstract_schedule directly. The lazy
    relationship raises MissingGreenlet in async context when it
    hasn't been eagerly loaded — and after db.refresh() in the
    lock/unlock endpoints, the relationship is unloaded. db.get()
    uses the identity map so it's free when already loaded.
    """
    abstract = await db.get(AbstractSchedule, assigned.abstract_schedule_id)
    if abstract is None:
        raise HTTPException(500, "Underlying abstract schedule missing")
    slot_map = {int(k): v for k, v in assigned.slot_map.items()}
    resolved_matches = [
        {"red": [slot_map[s] for s in m["red"]], "blue": [slot_map[s] for s in m["blue"]],
         "red_surrogate": m["red_surrogate"], "blue_surrogate": m["blue_surrogate"]}
        for m in abstract.matches
    ]
    resolved_practice_matches = _resolve_practice_matches(assigned.practice_matches, slot_map)
    event = await db.get(Event, assigned.event_id) if assigned.event_id else None
    event_info = None
    if event:
        event_info = {
            "id": event.id, "key": event.key, "name": event.name,
            "year": event.year, "location": event.location,
            "branding": event.branding or {},
            # Event-level freeze state — independent of per-schedule
            # lock. UI uses this to gate a separate "Event frozen"
            # banner with the matching disabled-buttons treatment.
            "locked_at":         event.locked_at.isoformat() if event.locked_at else None,
            "locked_by_user_id": event.locked_by_user_id,
            "locked_by_name":    event.locked_by_name,
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
        # Normalize day_config to V2 shape on read. Pre-migration
        # rows hold V1 shape; phase 2 DB migration fixes them in place.
        "day_config": normalize_to_v2(assigned.day_config),
        "created_at": assigned.created_at.isoformat(),
        # updated_at lets the UI render an "edited" badge by comparing
        # against created_at. Bumped on every PATCH and restore.
        "updated_at": assigned.updated_at.isoformat() if assigned.updated_at else None,
        "locked_at":         assigned.locked_at.isoformat() if assigned.locked_at else None,
        "locked_by_user_id": assigned.locked_by_user_id,
        "locked_by_name":    assigned.locked_by_name,
        # Official mark — at most one True per event_id (partial
        # unique index). UI gates Delete and renders the star icon.
        "is_official":        assigned.is_official,
        "official_at":        assigned.official_at.isoformat() if assigned.official_at else None,
        "official_by_user_id": assigned.official_by_user_id,
        "official_by_name":   assigned.official_by_name,
        # Lineage — NULL on originals, parent id on forks. Editor
        # uses this to render "Forked from {parent.name}" hint and
        # to show a lineage chain for once-official ancestors.
        "forked_from_id":     assigned.forked_from_id,
        # FRC §10.5.2 compliance audit. competition_approved is
        # NULL on pre-feature schedules (UI: "approval status unknown").
        # audit_trail holds the full forensic record per
        # app.frc_compliance.build_audit_record().
        "competition_approved": assigned.competition_approved,
        "audit_trail":         assigned.audit_trail,
    }


# ─── Helpers for history + lock-event writes ─────────────────────────
# Centralized so each endpoint that mutates the schedule produces a
# consistent audit trail. Helpers do NOT commit — the caller's
# transaction owns the commit so a failed mutation rolls back the
# history row alongside it.

async def _resolve_actor_display_name(db: AsyncSession, user: dict | None) -> tuple[int | None, str | None]:
    """Return (user_id, display_name) for an audit row.

    Pulls the canonical name from the User row when possible (JWT
    email could be stale if the user changed providers). Returns
    (None, None) when the request is anonymous.
    """
    if not user:
        return (None, None)
    uid = user.get("uid")
    if not uid:
        return (None, user.get("email"))
    user_row = await db.get(User, uid)
    name = (user_row.name if user_row and user_row.name else None) \
           or (user_row.email if user_row else None) \
           or user.get("email") \
           or f"user#{uid}"
    return (uid, name[:256])


async def _snapshot_schedule_history(
    db: AsyncSession,
    assigned: AssignedSchedule,
    action: str,
    user: dict | None,
) -> AssignedScheduleHistory:
    """Insert a history row carrying the schedule's current state.

    Caller invokes this BEFORE applying changes for action='patch'
    or 'restore' (so the row preserves the prior state) and AFTER
    insert for action='create' (so the row matches the just-created
    schedule).
    """
    actor_id, actor_name = await _resolve_actor_display_name(db, user)
    row = AssignedScheduleHistory(
        assigned_schedule_id=assigned.id,
        name=assigned.name,
        day_config=assigned.day_config,
        slot_map=assigned.slot_map,
        practice_matches=assigned.practice_matches,
        action=action,
        actor_user_id=actor_id,
        actor_name=actor_name,
    )
    db.add(row)
    return row


async def _record_lock_event(
    db: AsyncSession,
    schedule_id: int,
    action: str,        # 'lock' | 'unlock'
    user: dict | None,
) -> AssignedScheduleLockEvent:
    """Append an audit row for a lock/unlock action.

    Independent of the live `assigned_schedules.locked_at` column
    (which carries only the *current* state). This table preserves
    every change so a future lock_events GET can answer "when was
    this unlocked, by whom" after the fact.
    """
    actor_id, actor_name = await _resolve_actor_display_name(db, user)
    row = AssignedScheduleLockEvent(
        assigned_schedule_id=schedule_id,
        action=action,
        actor_user_id=actor_id,
        actor_name=actor_name,
    )
    db.add(row)
    return row


def _is_admin(user: dict | None) -> bool:
    """Read the is_admin flag from a JWT-derived user dict.

    Default-False on any malformed input. Callers should pass the
    user object straight from `Depends(require_auth)` or
    `Depends(get_current_user)`.
    """
    return bool(user and user.get("is_admin"))


def _user_can_bypass_event_freeze(event: Event | None, user: dict | None) -> bool:
    """Return True if `user` is permitted to mutate a frozen event.

    Two paths bypass the freeze:
      1. The original freezer (event.locked_by_user_id matches the
         JWT's uid). Symmetric to working-lock semantics — the user
         who took the lock retains full access while it's held.
      2. An admin (JWT's is_admin claim is True). Cross-event
         override authority for support and recovery cases.

    When the event is not frozen at all, this returns True (there's
    nothing to bypass). Callers should typically gate this behind a
    `_is_event_frozen(event)` check first, but it's safe to call
    unconditionally.
    """
    if not event or event.locked_at is None:
        return True
    if not user:
        return False
    if _is_admin(user):
        return True
    return event.locked_by_user_id == user.get("uid")


def _is_event_frozen(event: Event | None, user: dict | None = None) -> bool:
    """Returns True when the event freeze blocks `user`'s mutations.

    Use this for endpoints that operate on the event itself (event
    metadata edits, mark-official / unmark-official, schedule
    create paths like Generate/Assign/PDF-import, event delete).
    Those operations affect the canonical state of the event and
    must respect the freeze.

    Freeze semantics:
      - Event is not frozen → returns False (no block)
      - Event is frozen but user is the freezer → returns False
      - Event is frozen but user is admin → returns False
      - Event is frozen and user is anyone else → returns True (blocked)

    The `user` arg is optional for backward compatibility; calling
    without `user` means "is the event in frozen state at all" and
    is correct for code paths that have already authorized the
    actor separately. New call sites should pass `user`.

    For per-schedule mutations (PATCH / DELETE / lock / unlock /
    restore), use _schedule_protected_by_event_freeze instead —
    that helper applies snapshot-in-time semantics: schedules
    created AFTER the freeze are sandbox copies, exempt.
    """
    if not event or event.locked_at is None:
        return False
    if user is None:
        # Legacy call — no user available. Report raw frozen state.
        return True
    return not _user_can_bypass_event_freeze(event, user)


def _schedule_protected_by_event_freeze(
    event: Event | None, assigned: AssignedSchedule, user: dict | None = None,
) -> bool:
    """Returns True if the schedule should be blocked by the event freeze.

    Snapshot-in-time semantics: a schedule is protected when (a) the
    event is frozen AND (b) the schedule existed at freeze time
    (created_at < locked_at) AND (c) the user is neither the freezer
    nor an admin. Schedules created after the freeze are sandbox
    copies — created via /duplicate, which intentionally bypasses
    the freeze guard so users can iterate without affecting the
    canonical state.

    Why this rule: a "copy to experiment" workflow doesn't make
    sense if the copy is itself frozen. Pre-freeze schedules
    represent the canonical state at the moment the user said
    "this is set, don't touch it." Post-freeze copies are
    derivative and explicitly outside that scope.

    The `user` arg is optional for backward compatibility — calling
    without `user` means "is this schedule under a frozen
    canonical-state event" with no actor-aware override. New call
    sites should pass `user` so the freezer (and admins) can
    continue to mutate their own frozen events.
    """
    if not event or event.locked_at is None:
        return False
    # Both columns are timezone-aware (DateTime(timezone=True)) so
    # comparison is well-defined.
    if assigned.created_at >= event.locked_at:
        # Sandbox copy — exempt from freeze regardless of user.
        return False
    if user is not None and _user_can_bypass_event_freeze(event, user):
        return False
    return True


async def _was_ever_official(
    db: AsyncSession, assigned: AssignedSchedule
) -> bool:
    """Return True if this schedule has ever been marked official.

    Per docs/workstreams/schedule-lifecycle.md Part 4: structural immutability
    is permanent. Once a schedule has been marked official, its
    structural fields (slot_map, day_config, practice_matches,
    name) are frozen forever — even after unmark-official. The
    only path forward for changes is to fork (POST /duplicate).

    Implementation: query the history table for any row with
    action='mark-official'. Two-step check (currently is_official
    OR ever was) is required because the spec specifies that
    unmarking does NOT restore mutability.

    Why this matters: an admin who unmarks a schedule cannot then
    "fix" something on it — they must fork. Reasoning about "is
    this safe to edit" reduces to one question: was this schedule
    ever official?
    """
    if assigned.is_official:
        return True
    result = await db.execute(
        select(AssignedScheduleHistory.id)
        .where(AssignedScheduleHistory.assigned_schedule_id == assigned.id)
        .where(AssignedScheduleHistory.action == "mark-official")
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


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
    return await _build_assigned_schedule_response(assigned, db)


@app.patch("/api/assigned-schedules/{schedule_id}", status_code=200)
async def patch_assigned_schedule(
    schedule_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_session),
    user: dict = Depends(require_auth),
):
    """Update day_config (and other safe metadata) on an assigned schedule
    WITHOUT touching slot_map or matches[].

    The day_config carries time/structure metadata — day start/end times,
    breaks, cycle changes, practice day config. These can change after
    teams are assigned (e.g. organizers adjust the lunch break, push the
    day later, add a cycle-time change) WITHOUT invalidating the team
    assignments themselves. The slot map is a permutation; it doesn't
    care about wall-clock times.

    Match count changes (numTeams / matchesPerTeam edits) are NOT
    supported through this endpoint — they require regenerating the
    abstract schedule and reassigning teams. The frontend should
    direct the user back through the generate-then-assign flow for
    those.
    """
    assigned = await db.get(AssignedSchedule, schedule_id)
    if not assigned:
        raise HTTPException(404, "Assigned schedule not found")

    # ── Guards (in order of severity) ──────────────────────────
    # 1. Event-frozen + pre-freeze schedule → no mutations.
    #    Snapshot-in-time semantics: schedules created BEFORE the
    #    event was frozen are protected; schedules created after
    #    (only possible via /duplicate) are sandbox copies and
    #    remain editable. Must be checked first because freeze
    #    overrides everything, including locker bypass.
    event = await db.get(Event, assigned.event_id) if assigned.event_id else None
    if _schedule_protected_by_event_freeze(event, assigned, user):
        raise HTTPException(
            status_code=423,
            detail=f"Event is frozen by {event.locked_by_name or 'another user'} "
                   "— this schedule was frozen at that point. "
                   "Unfreeze the event, or duplicate this schedule to edit a sandbox copy.",
        )
    # 2. Ever-official → permanent structural immutability. Per
    #    docs/workstreams/schedule-lifecycle.md Part 4: once a schedule has been
    #    marked official, even once, its structural fields are
    #    frozen forever. Unmarking does NOT restore mutability.
    #    Forking is the only path forward.
    #
    #    Why "ever" not just "currently": a schedule that was the
    #    canonical record for an event represents historical truth.
    #    Allowing it to be unmarked-and-edited would let someone
    #    silently rewrite history. The audit log would show the
    #    unmark and the edit, but anyone reading the schedule later
    #    would see the post-edit state without context.
    #
    #    Returns 409 Conflict (not 423 Locked) because forking is
    #    a different action from unlocking, and the frontend
    #    handles 409 differently (offers "Fork this schedule"
    #    affordance rather than "Unlock to edit").
    if await _was_ever_official(db, assigned):
        raise HTTPException(
            status_code=409,
            detail=f"This schedule was marked official by "
                   f"{assigned.official_by_name or 'a previous user'} and is "
                   "structurally immutable. Fork it (POST /duplicate) to make changes.",
            headers={"X-Fork-Hint": f"/api/assigned-schedules/{assigned.id}/duplicate"},
        )
    # 3. Lock guard — refuse PATCH on a locked schedule unless the
    #    request is coming from the locker themselves. Returns HTTP
    #    423 Locked (RFC 4918) which the frontend handles distinctly
    #    from 401/403. The locker-bypass exists because the same
    #    user toggling Save in their own session shouldn't be blocked
    #    by their own lock — they explicitly chose to lock, so they
    #    retain edit rights.
    if assigned.locked_at is not None:
        if not user or assigned.locked_by_user_id != user.get("uid"):
            raise HTTPException(
                status_code=423,
                detail=f"Schedule is locked by {assigned.locked_by_name or 'another user'}.",
            )

    # Snapshot BEFORE mutating so the history row carries the prior
    # state. If the commit later fails, the history insert rolls back
    # with the rest of the transaction — no orphaned snapshots.
    has_changes = "day_config" in payload or "practice_matches" in payload
    if has_changes:
        await _snapshot_schedule_history(db, assigned, action="patch", user=user)

    if "day_config" in payload:
        new_dc = payload["day_config"]
        # Normalize to V2 + validate. _normalize_dc handles the
        # type-check (must be dict), V1→V2 migration (idempotent on
        # V2 input), and shape validation. On invalid input, raises
        # HTTPException(400) with a useful message.
        new_dc = _normalize_dc(new_dc, allow_none=False)
        assigned.day_config = new_dc
        # SQLAlchemy needs an explicit flag for JSON column mutation
        # to be picked up by the dirty-tracker.
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(assigned, "day_config")

    # ── practice_matches PATCH ──
    # Allow setting/replacing the practice match list on an existing
    # schedule. Useful for imported schedules (PDF/XLSX) which create
    # with practice_matches=[] — the user can then PATCH a practice
    # list separately. Accepts a list of dicts shaped like:
    #   [{"red": [t1, t2, t3], "blue": [t4, t5, t6],
    #     "red_surrogate": [false, ...], "blue_surrogate": [false, ...]}, ...]
    # Team numbers are stored as-is (not slot indices) for imported
    # schedules. _resolve_practice_matches falls through to identity
    # mapping for slots not in slot_map, so this works correctly.
    if "practice_matches" in payload:
        new_pm = payload["practice_matches"]
        if new_pm is not None and not isinstance(new_pm, list):
            raise HTTPException(400, "practice_matches must be a list or null")
        # Light shape validation — every entry must have red+blue arrays.
        # We don't enforce length=3 because some practice formats may
        # use fewer teams per alliance for early matches.
        if isinstance(new_pm, list):
            for i, m in enumerate(new_pm):
                if not isinstance(m, dict):
                    raise HTTPException(400, f"practice_matches[{i}] must be a dict")
                if not isinstance(m.get("red"), list) or not isinstance(m.get("blue"), list):
                    raise HTTPException(
                        400,
                        f"practice_matches[{i}] must have 'red' and 'blue' lists"
                    )
        assigned.practice_matches = new_pm
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(assigned, "practice_matches")

    # Bump updated_at on any meaningful change. The "EDITED" badge
    # in the saved-schedules modal compares updated_at > created_at.
    if has_changes:
        from datetime import datetime, timezone
        assigned.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(assigned)
    return await _build_assigned_schedule_response(assigned, db)


@app.post("/api/assigned-schedules/{schedule_id}/lock", status_code=200)
async def lock_assigned_schedule(
    schedule_id: int,
    db: AsyncSession = Depends(get_session),
    user: dict = Depends(require_auth),
):
    """Lock a schedule against further edits. Requires authentication.

    Stores who locked it (user_id + display name snapshot) and when.
    Locking a schedule that's already locked is a no-op when the
    requester is the existing locker; returns 423 if locked by
    someone else (keeps the original lock intact).

    The authorization matrix is intentionally minimal — anyone
    authenticated can lock, only the locker can unlock. Tighter
    rules (event ownership, admin override, etc.) come later.
    """
    assigned = await db.get(AssignedSchedule, schedule_id)
    if not assigned:
        raise HTTPException(404, "Assigned schedule not found")

    # Event-freeze guard. Pre-freeze schedules can't be locked
    # (event freeze already locks them implicitly; an extra
    # per-schedule lock would be misleading). Sandbox copies
    # (created after the freeze) remain lockable so users can
    # protect their experimental work-in-progress within the
    # frozen event.
    event = await db.get(Event, assigned.event_id) if assigned.event_id else None
    if _schedule_protected_by_event_freeze(event, assigned, user):
        raise HTTPException(
            status_code=423,
            detail=f"Event is frozen — schedule lock not needed (and not added).",
        )

    if assigned.locked_at is not None:
        # Already locked. If by us, fine — return current state. If by
        # someone else, refuse so users can't quietly steal locks.
        if assigned.locked_by_user_id != user.get("uid"):
            raise HTTPException(
                status_code=423,
                detail=f"Schedule is already locked by {assigned.locked_by_name or 'another user'}.",
            )
        return await _build_assigned_schedule_response(assigned, db)

    # Pull display name from the User row so the snapshot reflects
    # what's currently in the DB rather than what's in the JWT
    # (JWT email could be stale if the user changed providers).
    locker = await db.get(User, user.get("uid"))
    display_name = (locker.name if locker and locker.name else None) \
                   or (locker.email if locker else None) \
                   or user.get("email") \
                   or f"user#{user.get('uid')}"

    from datetime import datetime, timezone
    assigned.locked_at = datetime.now(timezone.utc)
    assigned.locked_by_user_id = user.get("uid")
    assigned.locked_by_name = display_name[:256]
    # Audit row — preserves history even after this lock is later
    # cleared (locked_at reset to NULL). Without this, "when was
    # this unlocked" would be unanswerable.
    await _record_lock_event(db, schedule_id, action="lock", user=user)
    await db.commit()
    await db.refresh(assigned)
    return await _build_assigned_schedule_response(assigned, db)


@app.post("/api/assigned-schedules/{schedule_id}/unlock", status_code=200)
async def unlock_assigned_schedule(
    schedule_id: int,
    db: AsyncSession = Depends(get_session),
    user: dict = Depends(require_auth),
):
    """Unlock a schedule. Currently only the locker can unlock.

    Future authorization-matrix work may relax this (event admins
    overriding stale locks, time-based auto-expiry, etc.) — for
    now, "only the locker can unlock" is the safest default.

    Refuses if the schedule is marked official (auto-lock from
    is_official); user must POST /unmark-official first.

    Refuses if the parent event is frozen — global freeze takes
    precedence and a granular unlock would be misleading.
    """
    assigned = await db.get(AssignedSchedule, schedule_id)
    if not assigned:
        raise HTTPException(404, "Assigned schedule not found")

    event = await db.get(Event, assigned.event_id) if assigned.event_id else None
    if _schedule_protected_by_event_freeze(event, assigned, user):
        raise HTTPException(
            status_code=423,
            detail=f"Event is frozen by {event.locked_by_name or 'another user'} "
                   "— unfreeze the event first.",
        )

    if assigned.is_official:
        raise HTTPException(
            status_code=423,
            detail="Schedule is marked official and remains locked. "
                   "Unmark official first via POST /unmark-official.",
        )

    if assigned.locked_at is None:
        # Idempotent — unlock on an unlocked schedule is fine.
        return await _build_assigned_schedule_response(assigned, db)

    if assigned.locked_by_user_id != user.get("uid"):
        raise HTTPException(
            status_code=423,
            detail=f"Only {assigned.locked_by_name or 'the original locker'} can unlock this schedule.",
        )

    assigned.locked_at = None
    assigned.locked_by_user_id = None
    assigned.locked_by_name = None
    # Audit row — captures who unlocked when. Pairs with the lock
    # row inserted by /lock.
    await _record_lock_event(db, schedule_id, action="unlock", user=user)
    await db.commit()
    await db.refresh(assigned)
    return await _build_assigned_schedule_response(assigned, db)


@app.post("/api/assigned-schedules/{schedule_id}/activate", status_code=200)
async def activate_assigned_schedule(
    schedule_id: int,
    db: AsyncSession = Depends(get_session),
    user: dict = Depends(require_auth),
):
    """Promote a schedule to active.

    Active schedule is the one users see on /view, the one live
    data overlays onto, the one tournament officials are running.
    A high-stakes operation — the per-event uniqueness of
    is_active=true means promoting one demotes the previous.

    Authorization layering:
      - Auth required (Phase A)
      - Event freeze respected — only the freezer or admin can
        change the active schedule in a frozen event (Part 13)
      - Schedule lock respected — only the locker or admin can
        promote a locked schedule (consistent with PATCH semantics
        on a locked schedule)
      - Demote ownership — if there's a CURRENTLY active schedule
        on this event and it was promoted by someone else, only
        that someone (or an admin) can demote it. This means
        promoting schedule X over schedule Y requires either
        being the user who originally promoted Y, or being an
        admin. Prevents quiet promotion-snatching during an event.
      - Once-official schedules can still be promoted (officiality
        is structural-immutability, not is_active gating)

    Limitation: the initial promote (no current active to demote)
    has no per-event ownership gate today — any authenticated user
    can do it. RBAC closes that gap when role grants ship.
    """
    assigned = await db.get(AssignedSchedule, schedule_id)
    if not assigned:
        raise HTTPException(404, "Assigned schedule not found")

    event = await db.get(Event, assigned.event_id) if assigned.event_id else None
    if _schedule_protected_by_event_freeze(event, assigned, user):
        raise HTTPException(
            status_code=423,
            detail=f"Event is frozen by {event.locked_by_name or 'another user'} "
                   "— only the freezer or an admin can promote a schedule.",
        )

    # Working-lock check: if the SOURCE schedule (the one being
    # promoted) is locked by someone other than the requester and
    # the requester isn't admin, refuse. This mirrors PATCH lock
    # semantics — taking the lock asserts ownership of mutations.
    if assigned.locked_at is not None and assigned.locked_by_user_id != user.get("uid"):
        if not _is_admin(user):
            raise HTTPException(
                status_code=423,
                detail=f"Schedule is locked by {assigned.locked_by_name or 'another user'}. "
                       "Only the locker or an admin can promote it.",
            )

    # Look up the currently active schedule for demote-ownership
    # check. We track the promoter as the schedule's locker on its
    # transition into active, but is_active doesn't have a dedicated
    # promoter_user_id column today. Heuristic: the current locker
    # is the most-recent-actor on the schedule, which is good enough
    # for this gate. RBAC supersedes this with a clean Manager check.
    current_active = await db.execute(
        select(AssignedSchedule)
        .where(AssignedSchedule.event_id == assigned.event_id)
        .where(AssignedSchedule.is_active == True)  # noqa: E712
    )
    previous_active = current_active.scalar_one_or_none()

    if (
        previous_active is not None
        and previous_active.id != schedule_id
        and previous_active.locked_by_user_id is not None
        and previous_active.locked_by_user_id != user.get("uid")
        and not _is_admin(user)
    ):
        # Someone else owns the current active schedule. Refuse the
        # promote — the demote-as-side-effect would override their
        # ownership without their consent.
        raise HTTPException(
            status_code=423,
            detail=f"The currently active schedule (\"{previous_active.name}\") "
                   f"is held by {previous_active.locked_by_name or 'another user'}. "
                   "Only that user or an admin can change which schedule is active.",
        )

    previous_active_id = previous_active.id if previous_active is not None else None

    await db.execute(
        update(AssignedSchedule)
        .where(AssignedSchedule.event_id == assigned.event_id)
        .values(is_active=False)
    )
    assigned.is_active = True
    await db.commit()
    return {
        "activated": schedule_id,
        "previous_active_id": previous_active_id,
    }


# ─── History + audit endpoints ──────────────────────────────────────

@app.get("/api/assigned-schedules/{schedule_id}/history")
async def get_schedule_history(
    schedule_id: int,
    db: AsyncSession = Depends(get_session),
):
    """List history rows for a schedule, newest first.

    Each row is a snapshot of the schedule taken before a mutation.
    The UI uses this for the "View history" panel and the "Restore"
    action. Public — no auth required for read access; restoring
    requires auth via POST /restore/{history_id}.
    """
    # Make sure the schedule exists before exposing history rows.
    assigned = await db.get(AssignedSchedule, schedule_id)
    if not assigned:
        raise HTTPException(404, "Assigned schedule not found")
    result = await db.execute(
        select(AssignedScheduleHistory)
        .where(AssignedScheduleHistory.assigned_schedule_id == schedule_id)
        .order_by(AssignedScheduleHistory.occurred_at.desc())
    )
    rows = result.scalars().all()
    return [
        {
            "id": h.id,
            "action": h.action,
            "name": h.name,
            "actor_user_id": h.actor_user_id,
            "actor_name":    h.actor_name,
            "occurred_at":   h.occurred_at.isoformat(),
            # Snapshot bodies — small enough to ship in the list
            # response. The "diff against previous" UI fetches the
            # whole list at once, so per-row drill-in fetches aren't
            # needed. day_config typically <30KB per snapshot.
            "day_config":       h.day_config,
            "slot_map":         h.slot_map,
            "practice_matches": h.practice_matches,
        }
        for h in rows
    ]


@app.post("/api/assigned-schedules/{schedule_id}/restore/{history_id}", status_code=200)
async def restore_schedule_from_history(
    schedule_id: int,
    history_id: int,
    db: AsyncSession = Depends(get_session),
    user: dict = Depends(require_auth),
):
    """Restore a schedule to a previous version from a history row.

    Behavior:
      1. Snapshot the current state with action='restore' (so the
         pre-restore version remains recoverable).
      2. Copy the named history row's snapshot back onto the live
         schedule.
      3. Bump updated_at.

    Lock state and is_official are NOT touched by restore — they're
    operational metadata, not content. A locked schedule can be
    restored (by the locker); a once-official schedule cannot be
    restored (structural immutability — fork instead).

    Same guard pattern as PATCH: refuses if event is frozen, if
    schedule was ever official, or if locked by someone other
    than the requester.
    """
    assigned = await db.get(AssignedSchedule, schedule_id)
    if not assigned:
        raise HTTPException(404, "Assigned schedule not found")

    event = await db.get(Event, assigned.event_id) if assigned.event_id else None
    if _schedule_protected_by_event_freeze(event, assigned, user):
        raise HTTPException(423, f"Event is frozen by {event.locked_by_name or 'another user'}.")
    # Structural immutability — once-official schedules cannot be
    # restored. The state in history is a snapshot of when this
    # schedule was canonical; restoring it would let someone
    # rewrite "what we ran the event on." Fork via /duplicate
    # if a derivative schedule starting from a historical state
    # is needed.
    if await _was_ever_official(db, assigned):
        raise HTTPException(
            status_code=409,
            detail="This schedule was marked official and is structurally "
                   "immutable. Fork it (POST /duplicate) to create an "
                   "editable copy, then restore on the fork.",
            headers={"X-Fork-Hint": f"/api/assigned-schedules/{assigned.id}/duplicate"},
        )
    if assigned.locked_at is not None:
        if not user or assigned.locked_by_user_id != user.get("uid"):
            raise HTTPException(423,
                f"Schedule is locked by {assigned.locked_by_name or 'another user'}.")

    history_row = await db.get(AssignedScheduleHistory, history_id)
    if not history_row or history_row.assigned_schedule_id != schedule_id:
        raise HTTPException(404, "History row not found for this schedule")

    # Snapshot the current state BEFORE applying the restore so we
    # can roll forward again if the user changes their mind.
    await _snapshot_schedule_history(db, assigned, action="restore", user=user)

    # Apply the historical snapshot back to the live row.
    assigned.name             = history_row.name
    assigned.day_config       = history_row.day_config
    assigned.slot_map         = history_row.slot_map
    assigned.practice_matches = history_row.practice_matches
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(assigned, "day_config")
    flag_modified(assigned, "slot_map")
    flag_modified(assigned, "practice_matches")
    from datetime import datetime, timezone
    assigned.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(assigned)
    return await _build_assigned_schedule_response(assigned, db)


@app.get("/api/assigned-schedules/{schedule_id}/lock-events")
async def get_schedule_lock_events(
    schedule_id: int,
    db: AsyncSession = Depends(get_session),
):
    """List lock/unlock events for a schedule, newest first.

    Diagnostic endpoint — answers "when was this unlocked, by whom"
    without requiring direct DB access. Public read; the live
    schedule itself is also publicly readable, so the audit log
    isn't more sensitive than that.
    """
    assigned = await db.get(AssignedSchedule, schedule_id)
    if not assigned:
        raise HTTPException(404, "Assigned schedule not found")
    result = await db.execute(
        select(AssignedScheduleLockEvent)
        .where(AssignedScheduleLockEvent.assigned_schedule_id == schedule_id)
        .order_by(AssignedScheduleLockEvent.occurred_at.desc())
    )
    return [
        {
            "id": e.id,
            "action": e.action,
            "actor_user_id": e.actor_user_id,
            "actor_name":    e.actor_name,
            "occurred_at":   e.occurred_at.isoformat(),
        }
        for e in result.scalars()
    ]


# ─── Mark/unmark official ──────────────────────────────────────────

@app.post("/api/assigned-schedules/{schedule_id}/mark-official", status_code=200)
async def mark_schedule_official(
    schedule_id: int,
    db: AsyncSession = Depends(get_session),
    user: dict = Depends(require_auth),
):
    """Mark a schedule as the event's official / canonical version.

    Side effects:
      - is_official set TRUE
      - official_at, official_by_user_id, official_by_name set
      - The schedule is auto-locked (locked_at set if not already)
        with a paired lock-event row in the audit log
      - At most one schedule per event_id can be official; the
        partial unique index in the migration enforces this. If the
        user attempts to mark a second one, we return a clear 409
        Conflict error rather than letting the constraint raise a
        cryptic IntegrityError.

    The auto-lock is necessary: an "official but editable" schedule
    is a footgun (someone could quietly change the canonical record).
    Once unmarked, the lock can be cleared independently.
    """
    assigned = await db.get(AssignedSchedule, schedule_id)
    if not assigned:
        raise HTTPException(404, "Assigned schedule not found")

    event = await db.get(Event, assigned.event_id) if assigned.event_id else None
    if _is_event_frozen(event, user):
        raise HTTPException(423, f"Event is frozen by {event.locked_by_name or 'another user'}.")

    if assigned.is_official:
        # Idempotent — already official, return current state.
        return await _build_assigned_schedule_response(assigned, db)

    # Refuse if a different schedule on this event is already
    # official. Caller must unmark the existing one first; we
    # refuse to silently steal the marker.
    existing_official = await db.execute(
        select(AssignedSchedule)
        .where(AssignedSchedule.event_id == assigned.event_id)
        .where(AssignedSchedule.is_official.is_(True))
    )
    other = existing_official.scalar_one_or_none()
    if other is not None and other.id != schedule_id:
        raise HTTPException(
            status_code=409,
            detail=f"Another schedule (\"{other.name}\") is already marked official "
                   "for this event. Unmark it first.",
        )

    # Pull display name from User row for snapshot consistency.
    actor = await db.get(User, user.get("uid"))
    display_name = (actor.name if actor and actor.name else None) \
                   or (actor.email if actor else None) \
                   or user.get("email") \
                   or f"user#{user.get('uid')}"

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    assigned.is_official        = True
    assigned.official_at        = now
    assigned.official_by_user_id = user.get("uid")
    assigned.official_by_name   = display_name[:256]

    # Auto-lock if not already locked. Re-uses the same lock columns
    # so existing lock semantics (PATCH guard, banner) work without
    # special-casing for "official-implied lock". A separate
    # is_official check on PATCH catches the case where someone is
    # the locker but is_official=True — the editor must unmark first.
    if assigned.locked_at is None:
        assigned.locked_at         = now
        assigned.locked_by_user_id = user.get("uid")
        assigned.locked_by_name   = display_name[:256]
        await _record_lock_event(db, schedule_id, action="lock", user=user)

    # History snapshot with action='mark-official'. This row is the
    # permanent fingerprint that lets _was_ever_official() know this
    # schedule has been promoted at least once. Even after unmark,
    # this row persists, and the ever-official check returns True.
    # That preserves the structural-immutability guarantee: once a
    # schedule has been THE schedule, it can never be silently
    # mutated — fork is the only path forward.
    await _snapshot_schedule_history(db, assigned, action="mark-official", user=user)

    await db.commit()
    await db.refresh(assigned)
    return await _build_assigned_schedule_response(assigned, db)


@app.post("/api/assigned-schedules/{schedule_id}/unmark-official", status_code=200)
async def unmark_schedule_official(
    schedule_id: int,
    db: AsyncSession = Depends(get_session),
    user: dict = Depends(require_auth),
):
    """Clear the is_official mark.

    Lock state is preserved — unmarking official doesn't auto-unlock
    (the user explicitly unlocks via /unlock if they want to edit).
    Only the original marker or an admin can unmark, mirroring the
    unlock policy.

    Note that unmarking does NOT make the schedule editable —
    structural immutability is forever (see _was_ever_official).
    The fork escape hatch is the only path to changes after
    mark-official has been issued, even after unmark. The unmark
    primarily serves to (a) clear the visible "official" indicator,
    (b) free the auto-lock so a different schedule can be promoted
    to active, and (c) let a different schedule be marked official
    in its place.
    """
    assigned = await db.get(AssignedSchedule, schedule_id)
    if not assigned:
        raise HTTPException(404, "Assigned schedule not found")

    event = await db.get(Event, assigned.event_id) if assigned.event_id else None
    if _is_event_frozen(event, user):
        raise HTTPException(423, f"Event is frozen by {event.locked_by_name or 'another user'}.")

    if not assigned.is_official:
        # Idempotent.
        return await _build_assigned_schedule_response(assigned, db)

    if assigned.official_by_user_id != user.get("uid") and not _is_admin(user):
        raise HTTPException(
            status_code=423,
            detail=f"Only {assigned.official_by_name or 'the original marker'} "
                   "or an admin can unmark this schedule.",
        )

    assigned.is_official = False
    assigned.official_at = None
    assigned.official_by_user_id = None
    assigned.official_by_name = None
    # Lock stays set — the user explicitly unlocks via /unlock if
    # they want to edit. Two-step intentional friction: official
    # status is a permanent commitment, undoing it shouldn't also
    # silently clear the lock.

    await db.commit()
    await db.refresh(assigned)
    return await _build_assigned_schedule_response(assigned, db)


# ─── Event-level freeze ────────────────────────────────────────────

@app.post("/api/events/{event_id}/freeze", status_code=200)
async def freeze_event(
    event_id: int,
    db: AsyncSession = Depends(get_session),
    user: dict = Depends(require_auth),
):
    """Freeze the event. Blocks edits to the event itself and to
    any schedules under it. Independent of per-schedule locks.

    Idempotent if already frozen by the same user. Returns 423
    if frozen by someone else.
    """
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")

    if event.locked_at is not None:
        if event.locked_by_user_id != user.get("uid"):
            raise HTTPException(
                status_code=423,
                detail=f"Event is already frozen by {event.locked_by_name or 'another user'}.",
            )
        return _event_freeze_payload(event)

    actor = await db.get(User, user.get("uid"))
    display_name = (actor.name if actor and actor.name else None) \
                   or (actor.email if actor else None) \
                   or user.get("email") \
                   or f"user#{user.get('uid')}"

    from datetime import datetime, timezone
    event.locked_at = datetime.now(timezone.utc)
    event.locked_by_user_id = user.get("uid")
    event.locked_by_name = display_name[:256]
    await db.commit()
    await db.refresh(event)
    return _event_freeze_payload(event)


@app.post("/api/events/{event_id}/unfreeze", status_code=200)
async def unfreeze_event(
    event_id: int,
    db: AsyncSession = Depends(get_session),
    user: dict = Depends(require_auth),
):
    """Unfreeze the event. Only the original freezer can unfreeze
    (mirrors the per-schedule unlock policy)."""
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")

    if event.locked_at is None:
        return _event_freeze_payload(event)

    # Original freezer can always unfreeze. Admins can override —
    # cross-event recovery authority. Anyone else: 423.
    if event.locked_by_user_id != user.get("uid") and not _is_admin(user):
        raise HTTPException(
            status_code=423,
            detail=f"Only {event.locked_by_name or 'the original freezer'} or an admin can unfreeze this event.",
        )

    event.locked_at = None
    event.locked_by_user_id = None
    event.locked_by_name = None
    await db.commit()
    await db.refresh(event)
    return _event_freeze_payload(event)


def _event_freeze_payload(event: Event) -> dict:
    """Compact response for freeze/unfreeze endpoints. Mirrors the
    fields embedded in `event` inside the schedule payload so
    frontend code can apply the same render path."""
    return {
        "id": event.id,
        "key": event.key,
        "locked_at":         event.locked_at.isoformat() if event.locked_at else None,
        "locked_by_user_id": event.locked_by_user_id,
        "locked_by_name":    event.locked_by_name,
    }


@app.delete("/api/assigned-schedules/{schedule_id}", status_code=204)
async def delete_assigned_schedule(
    schedule_id: int, db: AsyncSession = Depends(get_session),
    user: dict = Depends(require_auth),
):
    """Delete an assigned schedule. Refuses on:
      - Schedules marked official (must unmark first).
      - Schedules locked by another user (must be unlocked).
      - Schedules under a frozen event (must unfreeze first).
    Owner-only — non-creators get 403 (legacy behavior preserved).
    """
    assigned = await db.get(AssignedSchedule, schedule_id)
    if not assigned:
        raise HTTPException(404, "Assigned schedule not found")
    # Event-freeze takes precedence for pre-freeze schedules.
    # Sandbox copies (post-freeze) can be deleted freely — they
    # don't represent canonical state.
    event = await db.get(Event, assigned.event_id) if assigned.event_id else None
    if _schedule_protected_by_event_freeze(event, assigned, user):
        raise HTTPException(
            status_code=423,
            detail=f"Event is frozen by {event.locked_by_name or 'another user'}.",
        )
    # Official → permanent commitment, can't delete
    # without unmarking. Prevents losing the canonical record.
    if assigned.is_official:
        raise HTTPException(
            status_code=423,
            detail=f"Schedule is marked official by {assigned.official_by_name or 'another user'} "
                   "— unmark official first.",
        )
    # Lock guard — refuse if locked by someone other than the requester.
    # Locker bypass: their own lock shouldn't block their own delete
    # (consistent with the PATCH locker bypass).
    if assigned.locked_at is not None:
        if not user or assigned.locked_by_user_id != user.get("uid"):
            raise HTTPException(
                status_code=423,
                detail=f"Schedule is locked by {assigned.locked_by_name or 'another user'}.",
            )
    if assigned.created_by and (not user or user.get("sub") != assigned.created_by):
        raise HTTPException(403, "You do not own this schedule")
    await db.delete(assigned)
    await db.commit()


@app.post("/api/assigned-schedules/{schedule_id}/duplicate", status_code=201)
async def duplicate_assigned_schedule(
    schedule_id: int, db: AsyncSession = Depends(get_session),
    user: dict = Depends(require_auth),
):
    result = await db.execute(
        select(AssignedSchedule)
        .options(selectinload(AssignedSchedule.abstract_schedule))
        .where(AssignedSchedule.id == schedule_id)
    )
    src = result.scalar_one_or_none()
    if not src:
        raise HTTPException(404, "Schedule not found")
    # NOTE: /duplicate intentionally bypasses the event-freeze guard.
    # The whole purpose of Copy is to give users a sandbox where
    # they can iterate without affecting the canonical state — that
    # workflow is most valuable precisely when the event IS frozen
    # (the user has committed to a canonical version and now wants
    # to explore alternatives risk-free). The new copy is created
    # AFTER event.locked_at, so _schedule_protected_by_event_freeze
    # will correctly classify it as a sandbox in subsequent PATCH /
    # DELETE / lock / restore calls — those operations remain
    # available on the copy even while the source remains frozen.
    src_event = await db.get(Event, src.event_id) if src.event_id else None
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
        created_by=user["sub"] if user else None,
    )
    db.add(new_abs)
    await db.flush()
    new_asgn = AssignedSchedule(
        abstract_schedule_id=new_abs.id, event_id=src.event_id,
        name=f"{src.name} (copy)", is_active=False,
        slot_map=src.slot_map, day_config=src.day_config,
        practice_matches=src.practice_matches,
        assign_seed=src.assign_seed,
        # Lineage pointer — see docs/workstreams/schedule-lifecycle.md Part 5.
        # Set unconditionally for any duplicate so the lineage chain
        # exists for both "casual copy" and "fork from once-official"
        # use cases. Walking the chain backward via forked_from_id
        # reaches the original schedule (NULL forked_from_id).
        forked_from_id=src.id,
        # FRC compliance audit propagates through forks. The fork has
        # the same algorithm-level provenance as the source: it was
        # GENERATED by the same algorithm, even if the user later
        # edits matches manually. (Manual edits don't unset the
        # competition_approved bit — they're tracked separately via
        # AssignedScheduleHistory.)
        competition_approved=src.competition_approved,
        audit_trail=src.audit_trail,
        created_by=user["sub"] if user else None,
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
    # Initial 'create' history row for the duplicate. Captures the
    # state-as-duplicated; subsequent edits will land on top.
    await _snapshot_schedule_history(db, new_asgn, action="create", user=user)
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
                    "start_date": event.start_date,
                    "end_date":   event.end_date,
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
            # See _build_assigned_payload comment — dates are required
            # for the agenda-fit "past day" overlay. Local Event row
            # may have these from a prior TBA event sync.
            "start_date": event.start_date,
            "end_date":   event.end_date,
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
            # TBA payload carries start/end dates as YYYY-MM-DD when
            # available — same shape as our local DB column. Pass
            # through directly so the view can derive day dates
            # without a local Event row.
            "start_date": tba_event.get("start_date"),
            "end_date":   tba_event.get("end_date"),
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
    """Build a minimal V2 day_config from TBA match times. The view page uses this
    for break/cycle-time logic; for TBA data we just want a reasonable default
    so the schedule can render at all. The actual times shown will come from
    TBA's predicted_time/actual_time per match, not from day_config math.

    Per V2_SPEC: one V2 day per distinct calendar date, each with a single
    qualification block spanning the day's match window. No breaks are
    inferred (TBA doesn't carry break metadata)."""
    times = [m.get("time") or m.get("predicted_time") or m.get("actual_time")
             for m in qual_matches]
    times = [t for t in times if t]
    if not times:
        return None
    from datetime import datetime as _dt, timezone as _tz
    # Group matches by date, build a V2 day per distinct calendar date
    days_by_date: dict[str, list[int]] = {}
    for t in sorted(times):
        d = _dt.fromtimestamp(t, tz=_tz.utc).astimezone()
        days_by_date.setdefault(d.strftime("%Y-%m-%d"), []).append(t)
    days = []
    for date_str, day_times in days_by_date.items():
        d_start = _dt.fromtimestamp(min(day_times), tz=_tz.utc).astimezone()
        d_end   = _dt.fromtimestamp(max(day_times), tz=_tz.utc).astimezone()
        # Each TBA day → one V2 day with one qualification block.
        # cycleTime is nominal; the view page uses real per-match
        # times rather than computing from cycle.
        days.append({
            "label":  d_start.strftime("%a %b %d"),
            "date":   date_str,
            "blocks": [
                {
                    "type":      "qualification",
                    "start":     d_start.strftime("%H:%M"),
                    "end":       d_end.strftime("%H:%M"),
                    "cycleTime": 8,
                    "changes":   [],
                    "breaks":    [],
                }
            ],
        })
    return {
        "dayConfigVersion": 2,
        "cycleTime":   8,    # ignored for TBA data — UI uses real times per match
        "breakBuffer": 5,
        "days":        days,
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
            # start_date / end_date drive the agenda-fit progress
            # overlay's "past day" greying. Without them, view.html's
            # _deriveDayDate falls through to '' and the bar never
            # turns gray for past events. Both fields are nullable
            # YYYY-MM-DD strings on the Event model, so passing the
            # raw value through is sufficient — view.html parses with
            # a regex that defends against missing/malformed values.
            "start_date": event.start_date,
            "end_date":   event.end_date,
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
        # Normalize day_config to V2 shape on read. Pre-migration
        # rows hold V1 shape; phase 2 DB migration fixes them in place.
        "day_config": normalize_to_v2(assigned.day_config),
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
    user: dict = Depends(require_auth),
):
    """Begin simulating event progress for testing live mode. Generates fake
    match results based on the active assigned schedule. Replaces TBA as the
    data source until simulate/stop is called."""
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    return await live_data.start_simulation(db, event_id, speedup=speedup)


@app.post("/api/events/{event_id}/simulate/stop")
async def stop_event_simulation(
    event_id: int,
    db: AsyncSession = Depends(get_session),
    user: dict = Depends(require_auth),
):
    """End simulation and clear simulated data."""
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    return await live_data.stop_simulation(db, event_id)


@app.post("/api/webhooks/nexus")
async def nexus_webhook(request: Request, db: AsyncSession = Depends(get_session)):
    """Receive a Nexus event webhook (Push mode).

    Setup flow per Nexus's API page (https://frc.nexus/en/api):
      1. You add this webhook's URL on the Nexus dashboard
      2. Nexus generates a token and shows it to you
      3. You paste that token into NEXUS_WEBHOOK_TOKEN
      4. Nexus does a POST verification ping to your URL — must get 200 OK
      5. After verification, Nexus pushes a snapshot every time match status updates

    Nexus sends the token in the `Nexus-Token` request header (their docs;
    we also accept the lowercase variant defensively).

    Verification ping handling: Nexus's verification request may have an
    empty body or a body that isn't shaped like our normal payload. We
    return 200 in both cases — the only thing that matters at verify time
    is that the URL is reachable and the token (if checked) matches. Real
    payloads with valid JSON proceed to ingest_nexus_event normally.
    """
    expected_token = os.environ.get("NEXUS_WEBHOOK_TOKEN", "")
    if expected_token:
        provided = request.headers.get("Nexus-Token") or request.headers.get("x-nexus-token") or ""
        if provided != expected_token:
            raise HTTPException(403, "Invalid Nexus token")

    # Try to parse JSON; if body is empty or unparseable, treat as a
    # verification ping and return 200 with a friendly status. This is what
    # Nexus needs to confirm the webhook URL is valid during setup.
    raw_body = await request.body()
    if not raw_body or not raw_body.strip():
        log.info("Nexus webhook verification ping received (empty body) — returning 200")
        return {"status": "ok", "type": "verification"}

    try:
        payload = json.loads(raw_body)
    except Exception:
        log.info("Nexus webhook with non-JSON body received (likely verification ping) — returning 200")
        return {"status": "ok", "type": "verification"}

    # Real payload — hand off to live data ingestion
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

    Per `docs/workstreams/schedule-quality-reporting.md` Phase A, the
    computation lives in `app/quality.py` — this endpoint is a thin wrapper
    around `compute_diversity_report()`. The response JSON shape is preserved
    exactly for `static/index.html renderDiversityCard()` compatibility.
    """
    async with AsyncSessionLocal() as db:
        sched = await db.get(AbstractSchedule, schedule_id)
        if not sched:
            raise HTTPException(404, "Abstract schedule not found")

        report = compute_diversity_report(
            sched.matches,
            num_teams=sched.num_teams,
            matches_per_team=sched.matches_per_team,
            teams_per_alliance=3,  # FRC: all qual matches are 3v3
        )
        report.schedule_id = schedule_id
        return report.to_dict()


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
    # Same for practice matches — XLSX/CSV imports of files with a
    # Practice sheet send this through. None falls back to whatever
    # the cached parse contained (empty list for sources without practice).
    practice:      list[dict] | None = None
    day_config:    Any = None


@app.post("/api/schedules/import-pdf")
async def import_pdf(
    file: UploadFile = File(...),
    event_id: int | None = Query(None),
    nocache: bool = Query(False, description="Bypass content-hash cache; force re-extraction"),
    user: dict = Depends(require_auth),
):
    """Parse a schedule PDF using the configured LLM. Returns a preview
    that the user confirms (or edits) before committing via /commit.

    The result is cached by content hash, so re-uploading the same file
    is free. Pass `?nocache=1` to bypass and force re-extraction (useful
    when a previous import wrote bad data to the cache).

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

    # Trace marker: if you don't see this in pod logs after a request,
    # the new code isn't actually deployed (image cache, replica didn't
    # roll, etc.). Includes a build/version stamp so we can tell which
    # revision is handling the request.
    log.info(
        "import_pdf request: file=%s size=%d hash=%s nocache=%s event_id=%s",
        file.filename, len(content), pdf_hash[:8], nocache, event_id,
    )

    # Check cache first — same PDF, no LLM call needed. Skip when nocache=1.
    if not nocache:
        async with AsyncSessionLocal() as db:
            existing = await db.execute(
                select(PdfImport).where(PdfImport.pdf_hash == pdf_hash)
            )
            cached = existing.scalar_one_or_none()
            if cached:
                # Defensive: SQLAlchemy *should* deserialize JSONB to a
                # dict, but if a row was written with a partial / null
                # parsed payload we don't want a generic 500.
                cached_parsed = cached.parsed if isinstance(cached.parsed, dict) else {}
                method = cached.method or ""

                # Day-plan cache entries have method "llm:dayplan:<strategy>"
                # and parsed = {"dayplan": {...}, "day_config": {...}}.
                # Match-list entries have method without the "dayplan:" infix
                # and parsed = {"matches": [...]}. Return the right shape
                # for each kind so the frontend can render it.
                is_cached_dayplan = method.startswith("llm:dayplan:") or "dayplan" in cached_parsed

                log.info(
                    "PDF cache hit: %s (%s) kind=%s",
                    pdf_hash[:8], file.filename, "dayplan" if is_cached_dayplan else "matches",
                )

                if is_cached_dayplan:
                    dayplan = cached_parsed.get("dayplan") or {}
                    legacy_cfg = cached_parsed.get("day_config") or {}
                    return {
                        "kind":            "dayplan",
                        "pdf_import_id":   cached.id,
                        "pdf_hash":        pdf_hash,
                        "file_name":       cached.file_name,
                        "page_count":      cached.page_count,
                        "method":          method,
                        "format_detected": cached.format_detected,
                        "confidence":      dayplan.get("confidence") if isinstance(dayplan, dict) else None,
                        "event_dates":     dayplan.get("event_dates") if isinstance(dayplan, dict) else None,
                        "blocks":          dayplan.get("blocks", []) if isinstance(dayplan, dict) else [],
                        "day_config":      legacy_cfg,
                        "notes":           dayplan.get("notes", "") if isinstance(dayplan, dict) else "",
                        "_cache":          "hit",
                    }

                # Match-list cache entry — original behaviour
                roster = None
                if event_id:
                    roster_result = await db.execute(
                        select(Team.number).join(EventTeam, EventTeam.team_id == Team.id).where(EventTeam.event_id == event_id)
                    )
                    roster = [r[0] for r in roster_result.all()] or None
                try:
                    validation = pdf_validate.validate_schedule(
                        cached_parsed.get("matches", []), roster,
                    )
                except Exception as e:
                    log.exception("Cache hit validation failed for hash=%s", pdf_hash[:8])
                    raise HTTPException(
                        500,
                        f"Cache hit validation error: {type(e).__name__}: {e}. "
                        f"Try ?nocache=1 to force re-extraction."
                    )
                return {
                    "kind":            "matches",
                    "pdf_import_id":   cached.id,
                    "pdf_hash":        pdf_hash,
                    "file_name":       cached.file_name,
                    "page_count":      cached.page_count,
                    "method":          method,
                    "format_detected": cached.format_detected,
                    "matches":         cached_parsed.get("matches", []),
                    "practice":        cached_parsed.get("practice", []),
                    "validation":      validation,
                    "notes":           cached_parsed.get("notes", ""),
                    "_cache":          "hit",
                }
    else:
        log.info("PDF cache bypassed via ?nocache=1 for hash=%s", pdf_hash[:8])

    # Not cached — extract using the strategy router. This tries native
    # text extraction first (works for most FIRST PDFs), falls through to
    # OCR for image-based PDFs (MSHSL state schedule, scanned events),
    # and finally to vision LLM for anything else.
    try:
        extracted = await pdf_extract.extract_schedule(content)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        log.exception("PDF extraction failed")
        raise HTTPException(500, f"PDF extraction failed: {e}")

    strategy = extracted["strategy"]
    log.info("PDF extraction succeeded via strategy=%s", strategy)

    # ── Auto-detect: match list vs. day plan ─────────────────────────────────
    # Day-plan PDFs (event-day programs, MSHSL itinerary, etc.) are prose
    # itineraries with no team-number table. We route these through the
    # day-plan extractor instead of the match-list extractor.
    #
    # Vision-strategy results don't get this branch — they always produce a
    # match-list-shaped JSON because that's what the vision system prompt
    # asks for. (Day-plan PDFs are text-extractable in practice; OCR or
    # native always finds them. If a future vision-only day-plan emerges,
    # we'd extend this dispatch.)
    pdf_text = pdf_extract.format_for_llm(extracted) if strategy != "vision" else ""

    is_dayplan = strategy != "vision" and pdf_dayplan.looks_like_dayplan(pdf_text)
    if is_dayplan:
        log.info("PDF detected as day plan; using dayplan extractor")
        try:
            dayplan = await pdf_dayplan.extract_dayplan(pdf_text)
        except RuntimeError as e:
            raise HTTPException(503, str(e))
        except ValueError as e:
            raise HTTPException(502, f"LLM returned malformed day-plan: {e}")
        except HTTPException:
            raise
        except Exception as e:
            # Catch-all so the user sees what actually broke instead of a
            # generic "Internal Server Error". Pod logs get the full
            # traceback via log.exception(); the browser gets the type
            # and message, which is usually enough to diagnose.
            log.exception("Unexpected error during day-plan LLM extraction")
            raise HTTPException(
                500,
                f"Day-plan extraction failed: {type(e).__name__}: {e}"
            )

        if not dayplan:
            raise HTTPException(503, "LLM extraction not configured")

        # Convert to today's day_config schema for direct form-field apply.
        # Wrapped because the adapter touches arbitrary model output and
        # we'd rather surface "AttributeError: 'list' object has no
        # attribute 'lower'" than a 500 with no body.
        try:
            # V2-native emit path. Internally goes through the legacy
            # builder + migrate_v1_to_v2 so existing PDF parsing logic
            # (auto-cap, lunch detection) is reused without porting.
            legacy_cfg = pdf_dayplan.to_v2_day_config(dayplan)
        except Exception as e:
            log.exception(
                "Day-plan adapter failed. dayplan keys: %s, blocks count: %s",
                list(dayplan.keys()) if isinstance(dayplan, dict) else "(not dict)",
                len(dayplan.get("blocks", [])) if isinstance(dayplan, dict) else "(N/A)",
            )
            raise HTTPException(
                500,
                f"Day-plan adapter error: {type(e).__name__}: {e}. "
                f"This usually means the model output didn't match the "
                f"expected schema. Check scheduler pod logs for details."
            )

        # Save to cache. Reuse the PdfImport table — `kind` is encoded in
        # the method field ("llm:dayplan:<strategy>") so the commit endpoint
        # can dispatch correctly.
        #
        # Race / retry safety: if a previous request for the same PDF
        # already wrote a row (and we're getting here because nocache=1
        # was passed, or the cache check missed due to a concurrent
        # request), the INSERT fails on the unique constraint over
        # pdf_hash. Catch that specific case and fetch the existing
        # row instead — the caller still gets a valid pdf_import_id
        # they can commit, and the import isn't lost.
        try:
            async with AsyncSessionLocal() as db:
                pdf_import = PdfImport(
                    pdf_hash=pdf_hash,
                    file_name=file.filename,
                    byte_size=len(content),
                    page_count=extracted["page_count"],
                    parsed={"dayplan": dayplan, "day_config": legacy_cfg},
                    validation={"dayplan_blocks": len(dayplan.get("blocks", []))},
                    format_detected=dayplan.get("format_detected"),
                    method=f"llm:dayplan:{strategy}",
                )
                db.add(pdf_import)
                try:
                    await db.commit()
                    await db.refresh(pdf_import)
                except IntegrityError as ie:
                    # Row already exists — fetch it and use that. We
                    # OVERWRITE the parsed payload because this run is
                    # newer / fresher, especially when triggered by
                    # ?nocache=1 (the user explicitly asked for
                    # re-extraction). Without overwriting, the user's
                    # nocache request would silently keep returning
                    # the old cached data.
                    await db.rollback()
                    log.info(
                        "PDF row already existed for hash=%s; updating in-place",
                        pdf_hash[:8],
                    )
                    existing = await db.execute(
                        select(PdfImport).where(PdfImport.pdf_hash == pdf_hash)
                    )
                    pdf_import = existing.scalar_one()
                    pdf_import.file_name       = file.filename
                    pdf_import.byte_size       = len(content)
                    pdf_import.page_count      = extracted["page_count"]
                    pdf_import.parsed          = {"dayplan": dayplan, "day_config": legacy_cfg}
                    pdf_import.validation      = {"dayplan_blocks": len(dayplan.get("blocks", []))}
                    pdf_import.format_detected = dayplan.get("format_detected")
                    pdf_import.method          = f"llm:dayplan:{strategy}"
                    await db.commit()
                    await db.refresh(pdf_import)
        except Exception as e:
            log.exception("Day-plan cache write failed")
            raise HTTPException(
                500,
                f"Day-plan import succeeded but cache write failed: "
                f"{type(e).__name__}: {e}"
            )

        return {
            "kind":            "dayplan",
            "pdf_import_id":   pdf_import.id,
            "pdf_hash":        pdf_hash,
            "file_name":       file.filename,
            "page_count":      extracted["page_count"],
            "method":          f"llm:dayplan:{strategy}",
            "strategy":        strategy,
            "tried":           extracted.get("tried", []),
            "format_detected": dayplan.get("format_detected"),
            "confidence":      dayplan.get("confidence"),
            "event_dates":     dayplan.get("event_dates"),
            "blocks":          dayplan.get("blocks", []),
            "day_config":      legacy_cfg,
            "notes":           dayplan.get("notes", ""),
            "_cache":          "miss",
        }

    # ── Match-list flow (existing behaviour) ─────────────────────────────────
    # Vision strategy returns already-parsed JSON. Skip the text-LLM step.
    if strategy == "vision":
        parsed = extracted["parsed"]
    else:
        # Native or OCR — feed extracted text to the text LLM as before.
        # Refuse if estimated tokens exceed context window.
        est_tokens = pdf_extract.estimate_token_budget(extracted)
        if est_tokens > 16000:
            raise HTTPException(
                413,
                f"PDF too long for LLM extraction: ~{est_tokens} input tokens "
                f"(max ~16000). Try a more focused document or split into pages."
            )

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
        raise HTTPException(
            422,
            "LLM did not extract any matches from the PDF, and the document doesn't "
            "look like an event-day program either. If this is a match schedule, the "
            "format may be too unusual for the parser. If this is an event itinerary, "
            "make sure it mentions phases like 'Qualification Rounds' or 'Practice "
            "Matches' so the system can recognize it."
        )

    # Pull roster for cross-check if event provided
    roster = None
    if event_id:
        async with AsyncSessionLocal() as db:
            roster_result = await db.execute(
                select(Team.number).join(EventTeam, EventTeam.team_id == Team.id).where(EventTeam.event_id == event_id)
            )
            roster = [r[0] for r in roster_result.all()] or None

    validation = pdf_validate.validate_schedule(matches, roster)

    # Save to cache regardless of validation pass — user may want to edit
    # bad parses rather than re-call the LLM. Same race / retry safety
    # as the day-plan path: handle UniqueViolation by updating the
    # existing row.
    async with AsyncSessionLocal() as db:
        pdf_import = PdfImport(
            pdf_hash=pdf_hash,
            file_name=file.filename,
            byte_size=len(content),
            page_count=extracted["page_count"],
            parsed=parsed,
            validation=validation,
            format_detected=parsed.get("format_detected"),
            method=f"llm:{strategy}",
        )
        db.add(pdf_import)
        try:
            await db.commit()
            await db.refresh(pdf_import)
        except IntegrityError:
            await db.rollback()
            log.info(
                "PDF row already existed for hash=%s; updating in-place",
                pdf_hash[:8],
            )
            existing = await db.execute(
                select(PdfImport).where(PdfImport.pdf_hash == pdf_hash)
            )
            pdf_import = existing.scalar_one()
            pdf_import.file_name       = file.filename
            pdf_import.byte_size       = len(content)
            pdf_import.page_count      = extracted["page_count"]
            pdf_import.parsed          = parsed
            pdf_import.validation      = validation
            pdf_import.format_detected = parsed.get("format_detected")
            pdf_import.method          = f"llm:{strategy}"
            await db.commit()
            await db.refresh(pdf_import)

    return {
        "kind":            "matches",
        "pdf_import_id":   pdf_import.id,
        "pdf_hash":        pdf_hash,
        "file_name":       file.filename,
        "page_count":      extracted["page_count"],
        "method":          f"llm:{strategy}",
        "strategy":        strategy,
        "tried":           extracted.get("tried", []),
        "format_detected": parsed.get("format_detected"),
        "matches":         matches,
        "practice":        parsed.get("practice", []),
        "validation":      validation,
        "notes":           parsed.get("notes", ""),
        "_cache":          "miss",
    }


@app.post("/api/schedules/import-xlsx")
async def import_xlsx(
    file: UploadFile = File(...),
    event_id: int | None = Query(None),
    nocache: bool = Query(False, description="Bypass content-hash cache"),
    user: dict = Depends(require_auth),
):
    """Parse an FMS-style schedule XLSX file. Reliable round-trip path
    for xlsx files exported by this app (or any FMS-compatible export).

    Returns the same shape as /import-pdf for match-list cache hits, so
    the existing preview UI in static/index.html can render the result
    without changes. Commits go through /import-pdf/commit just like
    PDF imports.

    Unlike PDF import, this doesn't need an LLM endpoint — the format
    is structured and we parse it deterministically.
    """
    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty file")

    # XLSX files are zip archives starting with PK\x03\x04. Cheap
    # magic-byte check to fail fast on the wrong format.
    if not content.startswith(b"PK\x03\x04"):
        raise HTTPException(
            400,
            "File is not an XLSX (missing zip magic bytes). Make sure "
            "you're uploading the .xlsx file, not a CSV or PDF."
        )

    pdf_hash = pdf_extract.hash_pdf(content)  # reuse the same hasher
    log.info(
        "import_xlsx request: file=%s size=%d hash=%s event_id=%s",
        file.filename, len(content), pdf_hash[:8], event_id,
    )

    # Same cache strategy as PDF — content-hash keyed in pdf_imports.
    if not nocache:
        async with AsyncSessionLocal() as db:
            existing = await db.execute(
                select(PdfImport).where(PdfImport.pdf_hash == pdf_hash)
            )
            cached = existing.scalar_one_or_none()
            if cached:
                cached_parsed = cached.parsed if isinstance(cached.parsed, dict) else {}
                # Cache entries written before the §4.4 practice-storage fix
                # (HANDOFF.md) shaped `parsed` as {"matches", "notes"} — no
                # "practice" key. We can't distinguish "no practice in
                # source file" from "practice was dropped at write time"
                # from the cached dict alone, so when the key is absent we
                # invalidate and re-parse. The parser is fast (xlsx_extract
                # is deterministic, no LLM call) so this is cheap. Without
                # this check, reference scheduler xlsx files with a Practice sheet
                # silently lose their practice section through a stale-
                # cache hit even though `format_detected` (set at parse
                # time) still mentions the practice count.
                if "practice" not in cached_parsed:
                    log.info(
                        "XLSX cache hash=%s lacks 'practice' key — pre-dates "
                        "practice support; invalidating and re-parsing",
                        pdf_hash[:8],
                    )
                else:
                    log.info("XLSX cache hit: %s (%s)", pdf_hash[:8], file.filename)
                    roster = None
                    if event_id:
                        roster_result = await db.execute(
                            select(Team.number).join(EventTeam, EventTeam.team_id == Team.id).where(EventTeam.event_id == event_id)
                        )
                        roster = [r[0] for r in roster_result.all()] or None
                    validation = pdf_validate.validate_schedule(
                        cached_parsed.get("matches", []), roster,
                    )
                    return {
                        "kind":            "matches",
                        "pdf_import_id":   cached.id,
                        "pdf_hash":        pdf_hash,
                        "file_name":       cached.file_name,
                        "page_count":      cached.page_count,
                        "method":          cached.method or "xlsx",
                        "format_detected": cached.format_detected,
                        "matches":         cached_parsed.get("matches", []),
                        "practice":        cached_parsed.get("practice", []),
                        "validation":      validation,
                        "notes":           cached_parsed.get("notes", ""),
                        "derived":         _safe_derive(
                            cached_parsed.get("matches", []),
                            cached_parsed.get("practice", []),
                        ),
                        "_cache":          "hit",
                    }

    # Parse fresh.
    try:
        parsed = xlsx_extract.parse_xlsx(content)
    except ValueError as e:
        raise HTTPException(422, f"XLSX parse failed: {e}")
    except Exception as e:
        log.exception("Unexpected error parsing XLSX")
        raise HTTPException(500, f"XLSX parser error: {type(e).__name__}: {e}")

    matches = parsed.get("matches", [])

    # Validate against roster if event provided.
    roster = None
    async with AsyncSessionLocal() as db:
        if event_id:
            roster_result = await db.execute(
                select(Team.number).join(EventTeam, EventTeam.team_id == Team.id).where(EventTeam.event_id == event_id)
            )
            roster = [r[0] for r in roster_result.all()] or None
    validation = pdf_validate.validate_schedule(matches, roster)

    # Cache the parse — upsert on conflict, same pattern as PDF.
    async with AsyncSessionLocal() as db:
        pdf_import = PdfImport(
            pdf_hash=pdf_hash,
            file_name=file.filename,
            byte_size=len(content),
            page_count=parsed.get("page_count", 1),
            parsed={"matches": matches, "practice": parsed.get("practice", []), "notes": parsed.get("notes", "")},
            validation=validation,
            format_detected=parsed.get("format_detected"),
            method="xlsx",
        )
        db.add(pdf_import)
        try:
            await db.commit()
            await db.refresh(pdf_import)
        except IntegrityError:
            await db.rollback()
            log.info(
                "XLSX row already existed for hash=%s; updating in-place",
                pdf_hash[:8],
            )
            existing = await db.execute(
                select(PdfImport).where(PdfImport.pdf_hash == pdf_hash)
            )
            pdf_import = existing.scalar_one()
            pdf_import.file_name       = file.filename
            pdf_import.byte_size       = len(content)
            pdf_import.page_count      = parsed.get("page_count", 1)
            pdf_import.parsed          = {"matches": matches, "practice": parsed.get("practice", []), "notes": parsed.get("notes", "")}
            pdf_import.validation      = validation
            pdf_import.format_detected = parsed.get("format_detected")
            pdf_import.method          = "xlsx"
            await db.commit()
            await db.refresh(pdf_import)

    return {
        "kind":            "matches",
        "pdf_import_id":   pdf_import.id,
        "pdf_hash":        pdf_hash,
        "file_name":       file.filename,
        "page_count":      parsed.get("page_count", 1),
        "method":          "xlsx",
        "format_detected": parsed.get("format_detected"),
        "matches":         matches,
        "practice":        parsed.get("practice", []),
        "validation":      validation,
        "notes":           parsed.get("notes", ""),
        # Derive parameters from the match list. The XLSX export shape
        # doesn't carry numTeams / MPT / cycle time / day_config, so
        # we re-create them from the data. The frontend pre-fills the
        # form fields with these so the user doesn't have to retype
        # known values. Confidence flags let the UI flag uncertain
        # values for the user to verify. When practice matches are
        # present we also synthesise a practice day in the V2
        # day_config so /view renders the practice tab without the
        # user having to manually configure it.
        "derived":         _safe_derive(matches, parsed.get("practice", [])),
        "_cache":          "miss",
    }


def _safe_derive(
    matches: list[dict],
    practice_matches: list[dict] | None = None,
) -> dict | None:
    """Wrap derivation so a bad match list doesn't break the import."""
    try:
        return schedule_derive.derive_parameters(matches, practice_matches)
    except Exception as e:
        log.warning("Parameter derivation failed: %s", e)
        return None


@app.post("/api/schedules/import-csv")
async def import_csv_endpoint(
    file: UploadFile = File(...),
    event_id: int | None = Query(None),
    nocache: bool = Query(False, description="Bypass content-hash cache"),
    user: dict = Depends(require_auth),
):
    """Parse a schedule CSV. Accepts both the flat layout we export
    (Match,Time,Type,Blue 1-3,Red 1-3) and the FMS layout (Time,
    Description with embedded match number, Blue 1-3, Red 1-3).

    Same response shape as import-xlsx — the frontend reuses the
    PDF preview UI for both. Pre-fills form parameters via the
    derive step.
    """
    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty file")

    # CSV doesn't have a clean magic-byte signature. We accept anything
    # decodable as text. parse_csv() will surface format-mismatch errors
    # with useful messages.
    pdf_hash = pdf_extract.hash_pdf(content)
    log.info(
        "import_csv request: file=%s size=%d hash=%s event_id=%s",
        file.filename, len(content), pdf_hash[:8], event_id,
    )

    if not nocache:
        async with AsyncSessionLocal() as db:
            existing = await db.execute(
                select(PdfImport).where(PdfImport.pdf_hash == pdf_hash)
            )
            cached = existing.scalar_one_or_none()
            if cached:
                cached_parsed = cached.parsed if isinstance(cached.parsed, dict) else {}
                # See import_xlsx for rationale: pre-§4.4 cache entries
                # have no "practice" key, and we'd silently swallow it.
                if "practice" not in cached_parsed:
                    log.info(
                        "CSV cache hash=%s lacks 'practice' key — pre-dates "
                        "practice support; invalidating and re-parsing",
                        pdf_hash[:8],
                    )
                else:
                    log.info("CSV cache hit: %s (%s)", pdf_hash[:8], file.filename)
                    roster = None
                    if event_id:
                        roster_result = await db.execute(
                            select(Team.number).join(EventTeam, EventTeam.team_id == Team.id).where(EventTeam.event_id == event_id)
                        )
                        roster = [r[0] for r in roster_result.all()] or None
                    validation = pdf_validate.validate_schedule(
                        cached_parsed.get("matches", []), roster,
                    )
                    return {
                        "kind":            "matches",
                        "pdf_import_id":   cached.id,
                        "pdf_hash":        pdf_hash,
                        "file_name":       cached.file_name,
                        "page_count":      cached.page_count,
                        "method":          cached.method or "csv",
                        "format_detected": cached.format_detected,
                        "matches":         cached_parsed.get("matches", []),
                        "practice":        cached_parsed.get("practice", []),
                        "validation":      validation,
                        "notes":           cached_parsed.get("notes", ""),
                        "derived":         _safe_derive(
                            cached_parsed.get("matches", []),
                            cached_parsed.get("practice", []),
                        ),
                        "_cache":          "hit",
                    }

    try:
        parsed = csv_extract.parse_csv(content)
    except ValueError as e:
        raise HTTPException(422, f"CSV parse failed: {e}")
    except Exception as e:
        log.exception("Unexpected error parsing CSV")
        raise HTTPException(500, f"CSV parser error: {type(e).__name__}: {e}")

    matches = parsed.get("matches", [])

    roster = None
    async with AsyncSessionLocal() as db:
        if event_id:
            roster_result = await db.execute(
                select(Team.number).join(EventTeam, EventTeam.team_id == Team.id).where(EventTeam.event_id == event_id)
            )
            roster = [r[0] for r in roster_result.all()] or None
    validation = pdf_validate.validate_schedule(matches, roster)

    async with AsyncSessionLocal() as db:
        pdf_import = PdfImport(
            pdf_hash=pdf_hash,
            file_name=file.filename,
            byte_size=len(content),
            page_count=parsed.get("page_count", 1),
            parsed={"matches": matches, "practice": parsed.get("practice", []), "notes": parsed.get("notes", "")},
            validation=validation,
            format_detected=parsed.get("format_detected"),
            method="csv",
        )
        db.add(pdf_import)
        try:
            await db.commit()
            await db.refresh(pdf_import)
        except IntegrityError:
            await db.rollback()
            log.info(
                "CSV row already existed for hash=%s; updating in-place",
                pdf_hash[:8],
            )
            existing = await db.execute(
                select(PdfImport).where(PdfImport.pdf_hash == pdf_hash)
            )
            pdf_import = existing.scalar_one()
            pdf_import.file_name       = file.filename
            pdf_import.byte_size       = len(content)
            pdf_import.page_count      = parsed.get("page_count", 1)
            pdf_import.parsed          = {"matches": matches, "practice": parsed.get("practice", []), "notes": parsed.get("notes", "")}
            pdf_import.validation      = validation
            pdf_import.format_detected = parsed.get("format_detected")
            pdf_import.method          = "csv"
            await db.commit()
            await db.refresh(pdf_import)

    return {
        "kind":            "matches",
        "pdf_import_id":   pdf_import.id,
        "pdf_hash":        pdf_hash,
        "file_name":       file.filename,
        "page_count":      parsed.get("page_count", 1),
        "method":          "csv",
        "format_detected": parsed.get("format_detected"),
        "matches":         matches,
        "practice":        parsed.get("practice", []),
        "validation":      validation,
        "notes":           parsed.get("notes", ""),
        "derived":         _safe_derive(matches, parsed.get("practice", [])),
        "_cache":          "miss",
    }


@app.post("/api/schedules/render-pdf")
async def render_schedule_pdf_endpoint(
    body: dict,
    format: str = "pdf",
):
    """Render a schedule to PDF or HTML.

    No auth required — print/export operate on schedule data the
    /view page already exposes publicly to spectators and kiosks.
    The same view.html page that renders schedules without login
    needs to be able to print and export them too. Mirrors the
    posture of /api/events/{id}/teams/export.

    Body shape (see app.pdf_render docstring for details):
        {
            "schedule": {event_name, event_year, num_teams, ..., days: [...]},
            "options":  {scope, page_break_after_practice, ..., show_*},
            "branding": {primary_color, logo_text, title, subtitle}  // optional
        }

    Query params:
        format: "pdf" (default) — returns PDF binary for download.
                "html"           — returns a self-contained HTML page
                                   for the browser print popup.

    Both formats are rendered from the same template (see
    app/pdf_render.py:_build_full_html), so Print and PDF outputs
    are guaranteed visually identical.

    The PDF path replaces the previous client-side html2pdf flow
    (cross-browser inconsistencies, blank pages, off-page content,
    font-loading races, table page-break bugs). WeasyPrint produces
    deterministic, text-based PDFs.

    The HTML path lets the browser-print popup display the same
    template and call window.print(), so the user can choose
    "Save as PDF" or send to a printer with output that matches the
    PDF download exactly.
    """
    if not isinstance(body, dict) or "schedule" not in body:
        raise HTTPException(400, "Missing 'schedule' in request body")

    fmt = (format or "pdf").lower()
    if fmt not in ("pdf", "html"):
        raise HTTPException(400, f"format must be 'pdf' or 'html', got '{fmt}'")

    try:
        if fmt == "html":
            html_text = pdf_render.render_schedule_html(
                body, branding=body.get("branding"),
            )
        else:
            pdf_bytes = pdf_render.render_schedule_pdf(
                body, branding=body.get("branding"),
            )
    except ValueError as e:
        raise HTTPException(422, f"Invalid schedule data: {e}")
    except RuntimeError as e:
        # weasyprint import / system-dep error (PDF path only)
        log.exception("PDF rendering runtime error")
        raise HTTPException(503, str(e))
    except Exception as e:
        log.exception("Unexpected error rendering schedule")
        raise HTTPException(500, f"Render error: {type(e).__name__}: {e}")

    # HTML response: serve as text/html so the popup can render it.
    # No download disposition — the popup window receives this and
    # calls window.print(); we don't want it to trigger a download.
    if fmt == "html":
        return Response(
            content=html_text,
            media_type="text/html; charset=utf-8",
        )

    # PDF response: filename derived from event metadata for nicer
    # download UX.
    schedule = body.get("schedule") or {}
    event_name = schedule.get("event_name") or "schedule"
    year = schedule.get("event_year")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in event_name).strip("_")
    filename = f"{safe or 'schedule'}_{year or ''}.pdf".replace("__", "_").strip("_")

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
        },
    )


@app.post("/api/schedules/import-pdf/commit")
async def commit_pdf_import(
    body: PdfImportCommitRequest,
    user: dict = Depends(require_auth),
):
    """Commit a previewed PDF import as a real AssignedSchedule.

    The user confirms (and optionally edits) the parsed matches before
    calling this. We DON'T auto-commit — bad parses can corrupt schedules
    and the cost of a manual review step is small vs the cost of importing
    a wrong schedule.
    """
    # Normalize day_config to V2 shape + validate. PDF imports build
    # day_config from the parser's output (pdf_dayplan emits V2
    # natively post-phase-1) but the user may have edited it during
    # the preview — so we re-validate here regardless of source.
    body.day_config = _normalize_dc(body.day_config)
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
            select(Team.number).join(EventTeam, EventTeam.team_id == Team.id).where(EventTeam.event_id == body.event_id)
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
            created_by=user["sub"] if user else None,
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
        # Practice matches — prefer the user-edited list from the request
        # body (the preview UI sends them through as `practice`). Fall back
        # to the cached parse for backward-compat with clients that only
        # send the qual `matches` field. Empty list is the no-practice
        # default. Stored with real team numbers (not slot indices) for
        # imported schedules; _resolve_practice_matches falls through to
        # identity mapping for unknown slots so this round-trips.
        if body.practice is not None:
            practice_parsed = body.practice
        else:
            practice_parsed = pdf_import.parsed.get("practice", []) or []
        practice_for_db = []
        for pm in practice_parsed:
            red  = list(pm.get("red")  or [])
            blue = list(pm.get("blue") or [])
            if not (red and blue):
                continue
            practice_for_db.append({
                "red":            red,
                "blue":           blue,
                "red_surrogate":  pm.get("red_surrogate")  or [False] * len(red),
                "blue_surrogate": pm.get("blue_surrogate") or [False] * len(blue),
            })

        assigned = AssignedSchedule(
            abstract_schedule_id=sched.id, event_id=body.event_id,
            name=body.name, is_active=True,
            slot_map=slot_map, day_config=body.day_config,
            practice_matches=practice_for_db,
            assign_seed=None,
            created_by=user["sub"] if user else None,
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

        # Initial 'create' history row — captures the imported state
        # so the user can later compare against subsequent edits and
        # see which differences came from their own changes vs the
        # original PDF import.
        await _snapshot_schedule_history(db, assigned, action="create", user=user)
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
    """Returns LLM availability for the UI to surface in the import button.

    Reports both the text endpoint (used for native + OCR strategies) and
    the optional vision endpoint (used for image-only PDFs the other
    strategies can't handle).
    """
    text   = await llm_client.health_check()
    return text


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
    token = create_jwt(user.id, user.sub, "google", user.email, is_admin=user.is_admin)
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
    token = create_jwt(user.id, user.sub, "apple", user.email, is_admin=user.is_admin)
    return _oauth_popup_response(token)


@app.get("/auth/me")
async def auth_me(current_user: dict | None = Depends(get_current_user)):
    if not current_user:
        return {"authenticated": False}
    return {
        "authenticated": True, "sub": current_user.get("sub"),
        "email": current_user.get("email"), "provider": current_user.get("provider"),
        "uid": current_user.get("uid"),
        # Surface is_admin so the frontend can conditionally render
        # admin-only affordances (force-unfreeze, unmark-official, etc.).
        # The flag is sourced from the JWT, which was issued at login —
        # admin-status changes since then take effect on next sign-in.
        "is_admin": bool(current_user.get("is_admin")),
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
                     user: dict = Depends(require_auth)):
    log.info(
        "SCHEDULE_COMMITTED user=%s event=%s teams=%d matches=%s",
        (user or {}).get("sub", "anonymous"),
        body.event_info.get("key") if body.event_info else "none",
        len(body.teams), body.match_count,
    )
