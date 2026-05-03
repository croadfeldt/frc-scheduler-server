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
Database models using SQLAlchemy 2.x async ORM with PostgreSQL.

Two-stage scheduling model:
  Stage 1 — AbstractSchedule: slot-based structure (no team numbers)
  Stage 2 — AssignedSchedule: maps real team numbers onto an abstract schedule
"""

import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Float, ForeignKey,
    Integer, JSON, String, Text, UniqueConstraint,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://frc:frc@localhost:5432/frc_scheduler"
)

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    connect_args={
        "server_settings": {"application_name": "frc-scheduler"},
        "command_timeout": 60,
    },
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Models ────────────────────────────────────────────────────────────────────

class Event(Base):
    """An FRC event (regional, district, championship, or custom)."""
    __tablename__ = "events"

    id:          Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    key:         Mapped[str]      = mapped_column(String(64), unique=True, index=True)
    name:        Mapped[str]      = mapped_column(Text)
    year:        Mapped[int]      = mapped_column(Integer)
    location:    Mapped[str|None] = mapped_column(Text, nullable=True)
    start_date:  Mapped[str|None] = mapped_column(String(32), nullable=True)
    end_date:    Mapped[str|None] = mapped_column(String(32), nullable=True)
    tba_synced:  Mapped[bool]     = mapped_column(Boolean, default=False)
    # Per-event branding for /view (logo URL, primary color, subtitle, etc).
    # Schema (all keys optional): {"preset": "mshsl"|"frc"|null, "logo_url": str,
    # "primary_color": "#RRGGBB", "secondary_color": "#RRGGBB", "title": str,
    # "subtitle": str, "venue": str, "footer": str}
    branding:    Mapped[dict|None] = mapped_column(JSON, nullable=True)
    created_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    teams:              Mapped[list["EventTeam"]]        = relationship(back_populates="event", cascade="all, delete-orphan")
    abstract_schedules: Mapped[list["AbstractSchedule"]] = relationship(back_populates="event", cascade="all, delete-orphan")
    assigned_schedules: Mapped[list["AssignedSchedule"]] = relationship(back_populates="event", cascade="all, delete-orphan")


class Team(Base):
    """A registered FRC team."""
    __tablename__ = "teams"

    id:          Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    number:      Mapped[int]      = mapped_column(Integer, unique=True, index=True)
    name:        Mapped[str|None] = mapped_column(Text, nullable=True)
    nickname:    Mapped[str|None] = mapped_column(String(128), nullable=True)
    city:        Mapped[str|None] = mapped_column(String(128), nullable=True)
    state:       Mapped[str|None] = mapped_column(String(64), nullable=True)
    country:     Mapped[str|None] = mapped_column(String(64), nullable=True)
    rookie_year: Mapped[int|None] = mapped_column(Integer, nullable=True)
    created_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    events: Mapped[list["EventTeam"]] = relationship(back_populates="team")


class EventTeam(Base):
    """Association between an event and the teams attending it."""
    __tablename__ = "event_teams"
    __table_args__ = (UniqueConstraint("event_id", "team_id"),)

    id:       Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("events.id", ondelete="CASCADE"))
    team_id:  Mapped[int] = mapped_column(BigInteger, ForeignKey("teams.id", ondelete="CASCADE"))

    event: Mapped["Event"] = relationship(back_populates="teams")
    team:  Mapped["Team"]  = relationship(back_populates="events")


class AbstractSchedule(Base):
    """
    Stage 1 output — a slot-based match structure with no team numbers.

    Matches contain slot indices 1..N (abstract positions).
    Surrogate flags are per-slot. This structure is reusable with any
    roster of the same size.
    """
    __tablename__ = "abstract_schedules"

    id:               Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id:         Mapped[int|None] = mapped_column(BigInteger, ForeignKey("events.id", ondelete="SET NULL"), nullable=True)
    name:             Mapped[str]      = mapped_column(String(128), default="Abstract Schedule")

    num_teams:        Mapped[int]      = mapped_column(Integer)
    matches_per_team: Mapped[int]      = mapped_column(Integer)
    cooldown:         Mapped[int]      = mapped_column(Integer)
    seed:             Mapped[str|None] = mapped_column(String(16), nullable=True)
    iterations_run:   Mapped[int]      = mapped_column(Integer)
    best_iteration:   Mapped[int]      = mapped_column(Integer)
    score:            Mapped[float]    = mapped_column(Float)
    created_by:       Mapped[str|None] = mapped_column(String(256), nullable=True, index=True)

    # Slot-based match data — red/blue contain slot indices 1..N, not team numbers
    matches:          Mapped[Any]      = mapped_column(JSON)
    surrogate_count:  Mapped[Any]      = mapped_column(JSON)
    round_boundaries: Mapped[Any]      = mapped_column(JSON)
    day_config:       Mapped[Any|None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    event:              Mapped["Event|None"]              = relationship(back_populates="abstract_schedules")
    assigned_schedules: Mapped[list["AssignedSchedule"]]  = relationship(back_populates="abstract_schedule", cascade="all, delete-orphan")


class AssignedSchedule(Base):
    """
    Stage 2 output — real team numbers mapped onto an abstract schedule.

    slot_map: {slot_index: team_number} for all 1..N slots.
    """
    __tablename__ = "assigned_schedules"

    id:                   Mapped[int]  = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    abstract_schedule_id: Mapped[int]  = mapped_column(BigInteger, ForeignKey("abstract_schedules.id", ondelete="CASCADE"))
    event_id:             Mapped[int]  = mapped_column(BigInteger, ForeignKey("events.id", ondelete="CASCADE"))
    name:                 Mapped[str]  = mapped_column(String(128), default="Schedule")
    is_active:            Mapped[bool] = mapped_column(Boolean, default=False)

    slot_map:     Mapped[Any]      = mapped_column(JSON)
    day_config:   Mapped[Any|None] = mapped_column(JSON, nullable=True)
    # Practice matches generated client-side at schedule-creation time.
    # Already-resolved team numbers (not slot indices), shape:
    #   [{red:[t,t,t], blue:[t,t,t], red_surrogate:[bool×3], blue_surrogate:[bool×3]}, ...]
    # Practice matches don't follow the abstract schedule's structure (different
    # team count, no surrogate balancing, no team-pair constraints) so we store
    # them inline rather than via an AbstractSchedule indirection.
    practice_matches: Mapped[Any|None] = mapped_column(JSON, nullable=True)
    assign_seed:  Mapped[str|None] = mapped_column(String(16), nullable=True)
    created_by:   Mapped[str|None] = mapped_column(String(256), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    abstract_schedule: Mapped["AbstractSchedule"]  = relationship(back_populates="assigned_schedules")
    event:             Mapped["Event"]              = relationship(back_populates="assigned_schedules")
    match_rows:        Mapped[list["MatchRow"]]     = relationship(back_populates="assigned_schedule", cascade="all, delete-orphan")


class User(Base):
    """OAuth user — created on first login via Google or Apple."""
    __tablename__ = "users"

    id:         Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    sub:        Mapped[str]      = mapped_column(String(256), unique=True, index=True)
    provider:   Mapped[str]      = mapped_column(String(32))
    email:      Mapped[str|None] = mapped_column(String(256), nullable=True)
    name:       Mapped[str|None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class MatchRow(Base):
    """
    Denormalised match row for queryable team lookups.
    Stores real team numbers after Stage 2 assignment.
    """
    __tablename__ = "match_rows"

    id:                   Mapped[int]  = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    assigned_schedule_id: Mapped[int]  = mapped_column(BigInteger, ForeignKey("assigned_schedules.id", ondelete="CASCADE"))
    match_num:            Mapped[int]  = mapped_column(Integer)

    red1:  Mapped[int] = mapped_column(Integer)
    red2:  Mapped[int] = mapped_column(Integer)
    red3:  Mapped[int] = mapped_column(Integer)
    blue1: Mapped[int] = mapped_column(Integer)
    blue2: Mapped[int] = mapped_column(Integer)
    blue3: Mapped[int] = mapped_column(Integer)

    red1_surrogate:  Mapped[bool] = mapped_column(Boolean, default=False)
    red2_surrogate:  Mapped[bool] = mapped_column(Boolean, default=False)
    red3_surrogate:  Mapped[bool] = mapped_column(Boolean, default=False)
    blue1_surrogate: Mapped[bool] = mapped_column(Boolean, default=False)
    blue2_surrogate: Mapped[bool] = mapped_column(Boolean, default=False)
    blue3_surrogate: Mapped[bool] = mapped_column(Boolean, default=False)

    assigned_schedule: Mapped["AssignedSchedule"] = relationship(back_populates="match_rows")


# ── Live event data ───────────────────────────────────────────────────────────
# Match results synced from The Blue Alliance API. We store these so multiple
# users viewing the same event don't multiply API calls and so the data
# survives venue wifi flakiness. Refreshed lazily — see app.live.refresh_event.

class MatchResult(Base):
    """Result for a single played match. Sourced from TBA. One row per match
    per event."""
    __tablename__ = "match_results"
    __table_args__ = (
        UniqueConstraint("event_id", "comp_level", "match_number",
                         "set_number", name="uix_match_result_key"),
    )

    id:           Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id:     Mapped[int] = mapped_column(BigInteger, ForeignKey("events.id", ondelete="CASCADE"), index=True)
    comp_level:   Mapped[str] = mapped_column(String(8))   # 'qm', 'sf', 'f', etc.
    match_number: Mapped[int] = mapped_column(Integer)
    set_number:   Mapped[int] = mapped_column(Integer, default=1)  # only meaningful in playoffs

    # Time fields (unix seconds, nullable until set by TBA)
    actual_time:      Mapped[int|None] = mapped_column(BigInteger, nullable=True)
    predicted_time:   Mapped[int|None] = mapped_column(BigInteger, nullable=True)
    post_result_time: Mapped[int|None] = mapped_column(BigInteger, nullable=True)

    # Teams (red 1/2/3, blue 1/2/3) — denormalized for queries
    red_teams:  Mapped[list] = mapped_column(JSON, default=list)   # [int, int, int]
    blue_teams: Mapped[list] = mapped_column(JSON, default=list)

    # Scores
    red_score:         Mapped[int|None] = mapped_column(Integer, nullable=True)
    blue_score:        Mapped[int|None] = mapped_column(Integer, nullable=True)
    winning_alliance:  Mapped[str|None] = mapped_column(String(8), nullable=True)  # 'red'/'blue'/'tie'

    # Year-specific score breakdown — pass through whatever TBA returns
    score_breakdown: Mapped[dict|None] = mapped_column(JSON, nullable=True)

    # Video keys (TBA's "videos" array)
    videos: Mapped[list|None] = mapped_column(JSON, nullable=True)

    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TeamRanking(Base):
    """Current event ranking for a team. Sourced from TBA's rankings endpoint."""
    __tablename__ = "team_rankings"
    __table_args__ = (
        UniqueConstraint("event_id", "team_number", name="uix_team_ranking_key"),
    )

    id:           Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id:     Mapped[int] = mapped_column(BigInteger, ForeignKey("events.id", ondelete="CASCADE"), index=True)
    team_number:  Mapped[int] = mapped_column(Integer, index=True)

    rank:         Mapped[int|None]   = mapped_column(Integer, nullable=True)
    wins:         Mapped[int]        = mapped_column(Integer, default=0)
    losses:       Mapped[int]        = mapped_column(Integer, default=0)
    ties:         Mapped[int]        = mapped_column(Integer, default=0)
    matches_played: Mapped[int]      = mapped_column(Integer, default=0)
    ranking_score: Mapped[float|None] = mapped_column(Float, nullable=True)
    avg_match_score: Mapped[float|None] = mapped_column(Float, nullable=True)

    # Raw "extra stats" from TBA — year-specific breakdown
    extra_stats: Mapped[dict|None] = mapped_column(JSON, nullable=True)

    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QueueStatus(Base):
    """Current queueing status for a match. Sourced from Nexus webhooks.

    Status values match Nexus's terminology:
      'queueing_soon', 'now_queueing', 'on_deck', 'on_field', 'completed'
    """
    __tablename__ = "queue_status"
    __table_args__ = (
        UniqueConstraint("event_id", "comp_level", "match_number",
                         "set_number", name="uix_queue_status_key"),
    )

    id:           Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id:     Mapped[int] = mapped_column(BigInteger, ForeignKey("events.id", ondelete="CASCADE"), index=True)
    comp_level:   Mapped[str] = mapped_column(String(8))
    match_number: Mapped[int] = mapped_column(Integer)
    set_number:   Mapped[int] = mapped_column(Integer, default=1)

    status:       Mapped[str] = mapped_column(String(32))  # 'queueing_soon' | 'now_queueing' | 'on_deck' | 'on_field' | 'completed'
    queue_time:   Mapped[int|None] = mapped_column(BigInteger, nullable=True)  # unix seconds, when the match should queue
    updated_at:   Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class EventLiveSync(Base):
    """Tracks per-event sync state — when we last refreshed TBA, errors, etc.
    Used to throttle TBA API calls and surface freshness to clients."""
    __tablename__ = "event_live_sync"

    event_id:           Mapped[int] = mapped_column(BigInteger, ForeignKey("events.id", ondelete="CASCADE"), primary_key=True)
    tba_last_fetched:   Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    tba_last_error:     Mapped[str|None]      = mapped_column(Text, nullable=True)
    nexus_last_event:   Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    nexus_last_error:   Mapped[str|None]      = mapped_column(Text, nullable=True)
    # Simulation mode — when set, refresh_event() generates fake data instead
    # of calling TBA. Stores epoch-seconds when simulation started so progress
    # is deterministic on each call.
    sim_started_at:     Mapped[int|None]  = mapped_column(BigInteger, nullable=True)
    sim_speedup:        Mapped[float|None] = mapped_column(Float, nullable=True)


# ── DB helpers ────────────────────────────────────────────────────────────────

async def init_db(retries: int = 10, delay: float = 2.0) -> None:
    """Create all tables (idempotent). Retries for slow Postgres start."""
    import asyncio
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                # Idempotent column additions for schema evolution.
                # Postgres `ADD COLUMN IF NOT EXISTS` is supported since 9.6.
                # Keep this list short and rare; for anything bigger use Alembic.
                from sqlalchemy import text
                await conn.execute(text(
                    "ALTER TABLE events ADD COLUMN IF NOT EXISTS branding JSONB"
                ))
                await conn.execute(text(
                    "ALTER TABLE assigned_schedules ADD COLUMN IF NOT EXISTS practice_matches JSONB"
                ))
            return
        except Exception as e:
            last_error = e
            if attempt < retries:
                import logging
                logging.getLogger(__name__).warning(
                    "DB not ready (attempt %d/%d): %s — retrying in %.0fs",
                    attempt, retries, e, delay
                )
                await asyncio.sleep(delay)
    raise RuntimeError(f"Could not connect to database after {retries} attempts") from last_error


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
