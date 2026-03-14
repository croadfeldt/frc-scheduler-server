"""
Database models using SQLAlchemy 2.x async ORM with PostgreSQL.
"""

import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Float, ForeignKey,
    Integer, JSON, String, Text, UniqueConstraint, func,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://frc:frc@localhost:5432/frc_scheduler"
)

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
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
    name:        Mapped[str]      = mapped_column(String(256))
    year:        Mapped[int]      = mapped_column(Integer)
    location:    Mapped[str|None] = mapped_column(String(256), nullable=True)
    start_date:  Mapped[str|None] = mapped_column(String(32),  nullable=True)
    end_date:    Mapped[str|None] = mapped_column(String(32),  nullable=True)
    tba_synced:  Mapped[bool]     = mapped_column(Boolean, default=False)
    created_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    teams:     Mapped[list["EventTeam"]]   = relationship(back_populates="event", cascade="all, delete-orphan")
    schedules: Mapped[list["Schedule"]]    = relationship(back_populates="event", cascade="all, delete-orphan")


class Team(Base):
    """A registered FRC team."""
    __tablename__ = "teams"

    id:          Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    number:      Mapped[int]      = mapped_column(Integer, unique=True, index=True)
    name:        Mapped[str|None] = mapped_column(String(256), nullable=True)
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
    # Slot number used in the scheduler (1..N, assigned at generate time)
    slot:     Mapped[int|None] = mapped_column(Integer, nullable=True)

    event: Mapped["Event"] = relationship(back_populates="teams")
    team:  Mapped["Team"]  = relationship(back_populates="events")


class Schedule(Base):
    """
    A generated qualification schedule for an event.
    Multiple schedules can exist per event; one is marked active.
    """
    __tablename__ = "schedules"

    id:              Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id:        Mapped[int]      = mapped_column(BigInteger, ForeignKey("events.id", ondelete="CASCADE"))
    name:            Mapped[str]      = mapped_column(String(128), default="Schedule")
    is_active:       Mapped[bool]     = mapped_column(Boolean, default=False)

    # Config snapshot
    num_teams:       Mapped[int]   = mapped_column(Integer)
    matches_per_team: Mapped[int]  = mapped_column(Integer)
    cooldown:        Mapped[int]   = mapped_column(Integer)
    iterations_run:  Mapped[int]   = mapped_column(Integer)
    best_iteration:  Mapped[int]   = mapped_column(Integer)
    score:           Mapped[float] = mapped_column(Float)

    # Full schedule data as JSON
    matches:          Mapped[Any] = mapped_column(JSON)   # list of match dicts
    surrogate_count:  Mapped[Any] = mapped_column(JSON)   # list indexed by slot
    round_boundaries: Mapped[Any] = mapped_column(JSON)   # {round: match_idx}

    # Day/timing config snapshot
    day_config: Mapped[Any|None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    event:        Mapped["Event"]         = relationship(back_populates="schedules")
    match_rows:   Mapped[list["MatchRow"]] = relationship(back_populates="schedule", cascade="all, delete-orphan")


class MatchRow(Base):
    """
    Individual match row — denormalised for easy querying.
    Lets you ask "which matches does team 254 play?" without JSON parsing.
    """
    __tablename__ = "match_rows"

    id:          Mapped[int]  = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    schedule_id: Mapped[int]  = mapped_column(BigInteger, ForeignKey("schedules.id", ondelete="CASCADE"))
    match_num:   Mapped[int]  = mapped_column(Integer)

    red1:  Mapped[int]  = mapped_column(Integer)
    red2:  Mapped[int]  = mapped_column(Integer)
    red3:  Mapped[int]  = mapped_column(Integer)
    blue1: Mapped[int]  = mapped_column(Integer)
    blue2: Mapped[int]  = mapped_column(Integer)
    blue3: Mapped[int]  = mapped_column(Integer)

    red1_surrogate:  Mapped[bool] = mapped_column(Boolean, default=False)
    red2_surrogate:  Mapped[bool] = mapped_column(Boolean, default=False)
    red3_surrogate:  Mapped[bool] = mapped_column(Boolean, default=False)
    blue1_surrogate: Mapped[bool] = mapped_column(Boolean, default=False)
    blue2_surrogate: Mapped[bool] = mapped_column(Boolean, default=False)
    blue3_surrogate: Mapped[bool] = mapped_column(Boolean, default=False)

    schedule: Mapped["Schedule"] = relationship(back_populates="match_rows")


# ── DB helpers ────────────────────────────────────────────────────────────────

async def init_db(retries: int = 10, delay: float = 2.0) -> None:
    """
    Create all tables (idempotent).
    Retries on connection failure so the app survives a slow Postgres start,
    even if the initContainer or healthcheck doesn't catch every edge case.
    """
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
