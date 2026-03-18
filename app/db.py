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
    pool_size=5,          # keep 5 connections open permanently
    max_overflow=10,      # allow up to 10 more under load
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
    start_date:  Mapped[str|None] = mapped_column(String(32),  nullable=True)
    end_date:    Mapped[str|None] = mapped_column(String(32),  nullable=True)
    tba_synced:  Mapped[bool]     = mapped_column(Boolean, default=False)
    created_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    teams:              Mapped[list["EventTeam"]]       = relationship(back_populates="event", cascade="all, delete-orphan")
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
    state:       Mapped[str|None] = mapped_column(String(64),  nullable=True)
    country:     Mapped[str|None] = mapped_column(String(64),  nullable=True)
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
    team_id:  Mapped[int] = mapped_column(BigInteger, ForeignKey("teams.id",  ondelete="CASCADE"))

    event: Mapped["Event"] = relationship(back_populates="teams")
    team:  Mapped["Team"]  = relationship(back_populates="events")


class AbstractSchedule(Base):
    """
    Stage 1 output — a slot-based match structure with no team numbers.

    Matches contain slot indices 1..N (abstract positions).
    Surrogate flags are per-slot.  This structure is reusable with any
    roster of the same size.
    """
    __tablename__ = "abstract_schedules"

    id:               Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id:         Mapped[int|None] = mapped_column(BigInteger, ForeignKey("events.id", ondelete="SET NULL"), nullable=True)
    name:             Mapped[str]      = mapped_column(String(128), default="Abstract Schedule")

    # Scheduling parameters
    num_teams:        Mapped[int]      = mapped_column(Integer)
    matches_per_team: Mapped[int]      = mapped_column(Integer)
    cooldown:         Mapped[int]      = mapped_column(Integer)
    seed:             Mapped[str|None] = mapped_column(String(16), nullable=True)
    iterations_run:   Mapped[int]      = mapped_column(Integer)
    best_iteration:   Mapped[int]      = mapped_column(Integer)
    score:            Mapped[float]    = mapped_column(Float)
    created_by:       Mapped[str|None] = mapped_column(String(256), nullable=True, index=True)

    # Slot-based match data — red/blue contain slot indices 1..N, not team numbers
    matches:          Mapped[Any] = mapped_column(JSON)  # [{red:[s1,s2,s3], blue:[s4,s5,s6], red_surrogate:[...], blue_surrogate:[...]}]
    surrogate_count:  Mapped[Any] = mapped_column(JSON)  # [0, count_slot1, count_slot2, ...] 1-indexed
    round_boundaries: Mapped[Any] = mapped_column(JSON)  # {"1": match_idx, "2": match_idx, ...}
    day_config:       Mapped[Any|None] = mapped_column(JSON, nullable=True)  # timing/break/cycle config snapshot

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    event:              Mapped["Event|None"]          = relationship(back_populates="abstract_schedules")
    assigned_schedules: Mapped[list["AssignedSchedule"]] = relationship(back_populates="abstract_schedule", cascade="all, delete-orphan")


class AssignedSchedule(Base):
    """
    Stage 2 output — real team numbers mapped onto an abstract schedule.

    slot_map: {slot_index: team_number} for all 1..N slots.
    The match data from the abstract schedule combined with slot_map gives
    the full human-readable schedule.
    """
    __tablename__ = "assigned_schedules"

    id:                   Mapped[int]  = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    abstract_schedule_id: Mapped[int]  = mapped_column(BigInteger, ForeignKey("abstract_schedules.id", ondelete="CASCADE"))
    event_id:             Mapped[int]  = mapped_column(BigInteger, ForeignKey("events.id", ondelete="CASCADE"))
    name:                 Mapped[str]  = mapped_column(String(128), default="Schedule")
    is_active:            Mapped[bool] = mapped_column(Boolean, default=False)

    # Slot → team number mapping: {"1": 254, "2": 1114, ...}
    slot_map:     Mapped[Any]      = mapped_column(JSON)
    day_config:   Mapped[Any|None] = mapped_column(JSON, nullable=True)
    assign_seed:  Mapped[str|None] = mapped_column(String(16), nullable=True)
    created_by:   Mapped[str|None] = mapped_column(String(256), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    abstract_schedule: Mapped["AbstractSchedule"] = relationship(back_populates="assigned_schedules")
    event:             Mapped["Event"]             = relationship(back_populates="assigned_schedules")
    match_rows:        Mapped[list["MatchRow"]]    = relationship(back_populates="assigned_schedule", cascade="all, delete-orphan")


class User(Base):
    """OAuth user — created on first login via Google or Apple."""
    __tablename__ = "users"

    id:         Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    sub:        Mapped[str]      = mapped_column(String(256), unique=True, index=True)  # OAuth subject
    provider:   Mapped[str]      = mapped_column(String(32))   # "google" | "apple"
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


# ── DB helpers ────────────────────────────────────────────────────────────────

async def init_db(retries: int = 10, delay: float = 2.0) -> None:
    """Create all tables (idempotent). Retries for slow Postgres start."""
    import asyncio
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
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
