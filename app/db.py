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

    # ── Event-level freeze ────────────────────────────────────────
    # Strategic-level lock. When set, the event itself is frozen:
    # event metadata can't be PATCH'd, all schedules under it can't
    # be PATCH'd or DELETE'd, no new schedules can be created, and
    # the event itself can't be deleted. Independent of per-schedule
    # locks (which protect a specific version) — see AssignedSchedule
    # locked_at for the granular case.
    locked_at:         Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by_user_id: Mapped[int|None]      = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    locked_by_name:    Mapped[str|None]      = mapped_column(String(256), nullable=True)

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
    # Placement criteria weights (FIRST-aligned defaults if NULL). Stored so
    # generated schedules are fully reproducible — a schedule generated with
    # custom weights stays consistent on reload. See app.scheduler for shape.
    weights:          Mapped[Any|None] = mapped_column(JSON, nullable=True)

    # Schedule Quality Framework Phase B fields. NULL on legacy rows;
    # populated for every schedule created after the migration.
    # source: where this schedule came from. One of:
    #   'generated'         - SA-generated fresh
    #   'canonical_library' - served from app/canonical_schedules/
    #   'imported'          - user-uploaded (PDF, xlsx, etc.)
    source:           Mapped[str|None] = mapped_column(String(32), nullable=True)
    # source_url: optional URL pointing at the schedule's external source
    # (e.g., a Statbotics event page, an FRC event archive link, or any
    # other public reference). Only meaningful when source='imported'.
    source_url:       Mapped[str|None] = mapped_column(Text, nullable=True)
    # quality_report: full per-metric report keyed to fixture floors.
    # See app.quality_report.build_quality_report for the dict shape.
    # NULL on legacy rows; populated for every new schedule.
    quality_report:   Mapped[Any|None] = mapped_column(JSON, nullable=True)

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

    # Lineage pointer for forks. NULL = original schedule (not a fork).
    # Set when this schedule was created by /duplicate from another
    # schedule. ON DELETE SET NULL preserves the fork as an orphan
    # if the parent is somehow deleted (normal flow prevents this
    # since deleting a parent that's been forked from is forbidden,
    # but the FK is defensive).
    #
    # Lineage chains are allowed: fork-of-fork-of-original. The chain
    # is reconstructable by walking forked_from_id pointers backward
    # until NULL. Per docs/workstreams/schedule-lifecycle.md Part 5.
    forked_from_id: Mapped[int|None] = mapped_column(
        BigInteger, ForeignKey("assigned_schedules.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

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

    # ── Lock fields ──────────────────────────────────────────────
    # When set, the schedule is locked against edits/PATCH/lock-bypass
    # operations. Only the locking user can unlock (until the
    # authorization matrix is implemented). All three columns are
    # populated together when locking and cleared together on unlock.
    # `locked_by_name` is denormalized so we can render "Locked by
    # Alice" without a join — the user's display name at the time
    # of locking. If the user later changes their name, the lock
    # banner still shows the original snapshot.
    locked_at:         Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by_user_id: Mapped[int|None]      = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    locked_by_name:    Mapped[str|None]      = mapped_column(String(256), nullable=True)

    # ── Official mark ────────────────────────────────────────────
    # "This is THE schedule" — permanent, one per event (enforced by
    # a partial unique index in the migration). Setting auto-locks
    # the schedule. Unmarking requires explicit POST /unmark-official
    # with confirmation in the UI. Once an event is run with a
    # particular schedule, marking it official locks in the
    # historical record.
    is_official:        Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    official_at:        Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    official_by_user_id: Mapped[int|None]     = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    official_by_name:   Mapped[str|None]      = mapped_column(String(256), nullable=True)

    # ── FRC §10.5.2 competition compliance audit trail ──────────────
    # competition_approved: NULL = pre-feature, TRUE/FALSE = post-feature.
    # See app/frc_compliance.py for the canonical definition. The UI
    # surfaces this as a green/yellow/gray badge per schedule.
    #
    # audit_trail: full forensic JSON. See build_audit_record() for shape.
    # Includes the FRC defaults snapshot at generation time so the audit
    # remains valid even if FRC §10.5.2 changes in the future.
    competition_approved: Mapped[bool|None] = mapped_column(Boolean, nullable=True)
    audit_trail:          Mapped[Any|None]  = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Bumped to NOW() on every meaningful mutation (PATCH, restore-
    # from-history, mark-official rename). Lock/unlock and is_active
    # toggles do NOT bump it — those aren't content changes.
    # Initialized to created_at on insert so brand-new rows read as
    # "never edited" until something actually changes them.
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    abstract_schedule: Mapped["AbstractSchedule"]  = relationship(back_populates="assigned_schedules")
    event:             Mapped["Event"]              = relationship(back_populates="assigned_schedules")
    match_rows:        Mapped[list["MatchRow"]]     = relationship(back_populates="assigned_schedule", cascade="all, delete-orphan")
    history_rows:      Mapped[list["AssignedScheduleHistory"]]   = relationship(back_populates="assigned_schedule", cascade="all, delete-orphan")
    lock_events:       Mapped[list["AssignedScheduleLockEvent"]] = relationship(back_populates="assigned_schedule", cascade="all, delete-orphan")


class AssignedScheduleHistory(Base):
    """Snapshot of an assigned schedule taken before each mutation.

    Copy-on-write recovery: every PATCH (or restore) writes a row
    here BEFORE applying changes, so the previous state is preserved.
    Restoring is `POST /api/assigned-schedules/{id}/restore/{history_id}`
    which copies the named row back onto the live schedule and inserts
    a new history row with action='restore'.

    is_active and lock state are intentionally NOT in the snapshot —
    they're operational metadata, not "content". A restore preserves
    the live schedule's lock state and active status.
    """
    __tablename__ = "assigned_schedule_history"

    id:                   Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    assigned_schedule_id: Mapped[int]      = mapped_column(BigInteger, ForeignKey("assigned_schedules.id", ondelete="CASCADE"), index=True)

    name:             Mapped[str]      = mapped_column(String(128))
    day_config:       Mapped[Any|None] = mapped_column(JSON, nullable=True)
    slot_map:         Mapped[Any]      = mapped_column(JSON)
    practice_matches: Mapped[Any|None] = mapped_column(JSON, nullable=True)

    # 'create' | 'patch' | 'rename' | 'restore' | 'mark-official'
    # The 'mark-official' value is the permanent fingerprint that
    # _was_ever_official() in main.py looks for. Once any row with
    # action='mark-official' exists for a schedule, that schedule
    # is structurally immutable forever — even after unmark-official.
    # Per docs/workstreams/schedule-lifecycle.md Part 4.
    action:        Mapped[str]      = mapped_column(String(16))
    actor_user_id: Mapped[int|None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_name:    Mapped[str|None] = mapped_column(String(256), nullable=True)
    occurred_at:   Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    assigned_schedule: Mapped["AssignedSchedule"] = relationship(back_populates="history_rows")


class AssignedScheduleLockEvent(Base):
    """One row per lock or unlock action.

    The live `assigned_schedules.locked_at` column carries the
    *current* state. This audit table preserves the history so
    diagnostics can answer "when was this unlocked, and by whom"
    after the fact — without it, that history is lost the instant
    `locked_at` is reset to NULL.
    """
    __tablename__ = "assigned_schedule_lock_events"

    id:                   Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    assigned_schedule_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("assigned_schedules.id", ondelete="CASCADE"), index=True)

    # 'lock' | 'unlock'
    action:        Mapped[str]      = mapped_column(String(16))
    actor_user_id: Mapped[int|None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_name:    Mapped[str|None] = mapped_column(String(256), nullable=True)
    occurred_at:   Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    assigned_schedule: Mapped["AssignedSchedule"] = relationship(back_populates="lock_events")


class User(Base):
    """OAuth user — created on first login via Google or Apple."""
    __tablename__ = "users"

    id:         Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    sub:        Mapped[str]      = mapped_column(String(256), unique=True, index=True)
    provider:   Mapped[str]      = mapped_column(String(32))
    email:      Mapped[str|None] = mapped_column(String(256), nullable=True)
    name:       Mapped[str|None] = mapped_column(String(256), nullable=True)
    # Interim admin flag — replaced by RBAC role grants when that
    # workstream lands (see docs/workstreams/rbac.md). For now: a single
    # boolean granting cross-event override authority. Set via the
    # ADMIN_EMAILS env-var allow-list at login time, or directly
    # via DB. Capabilities gated on this flag:
    #   - Override event freeze (mutate frozen events the user
    #     didn't freeze themselves)
    #   - Override schedule lock (currently NOT — locker-only
    #     remains for now; admin override can be added later if
    #     operationally needed)
    #   - Future: unmark-official, force-unlock, etc. (per
    #     docs/workstreams/schedule-lifecycle.md Phase E)
    is_admin:   Mapped[bool]     = mapped_column(Boolean, default=False, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PdfImport(Base):
    """Cache of LLM-parsed schedule PDFs.

    Same PDF (by SHA-256) → same parsed result. Stops repeat LLM calls when
    users re-upload the same file (very common during testing or iterating).

    Cache entries are NOT tied to a specific event — a PDF that gets imported
    for one event might also be reusable for another. We keep them separate
    from AssignedSchedule and only materialize into AssignedSchedule on the
    user's explicit confirmation.
    """
    __tablename__ = "pdf_imports"

    id:           Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    pdf_hash:     Mapped[str]      = mapped_column(String, unique=True, index=True)
    file_name:    Mapped[str|None] = mapped_column(String, nullable=True)
    byte_size:    Mapped[int]      = mapped_column(Integer)
    page_count:   Mapped[int]      = mapped_column(Integer)
    # Raw LLM-parsed output before validation/edits. Reusable across attempts.
    parsed:       Mapped[Any]      = mapped_column(JSON)
    # Validation result (errors, warnings, stats). Computed at parse time and
    # cached so the preview loads instantly on repeat upload.
    validation:   Mapped[Any]      = mapped_column(JSON)
    # Format identifier from the LLM ("MSHSL state schedule with...") — handy
    # for debugging and surfacing to the user.
    format_detected: Mapped[str|None] = mapped_column(String, nullable=True)
    # Extraction method: "llm" or "deterministic_<format>"
    method:       Mapped[str]      = mapped_column(String, default="llm")
    created_at:   Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


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
                await conn.execute(text(
                    "ALTER TABLE abstract_schedules ADD COLUMN IF NOT EXISTS weights JSONB"
                ))
                # Schedule Quality Framework Phase B: track where each
                # schedule came from and embed its quality report so the
                # UI can display per-criterion / floor-comparison data
                # without recomputing. source values:
                #   'generated'         (legacy + new generations)
                #   'canonical_library' (served from pre-computed library)
                #   'imported'          (uploaded by user; source_url optional)
                # quality_report is the full dict from app.quality_report.build_quality_report
                # — per-metric value, floor, distance, confidence, matches_floor.
                await conn.execute(text(
                    "ALTER TABLE abstract_schedules "
                    "ADD COLUMN IF NOT EXISTS source VARCHAR(32)"
                ))
                await conn.execute(text(
                    "ALTER TABLE abstract_schedules "
                    "ADD COLUMN IF NOT EXISTS source_url TEXT"
                ))
                await conn.execute(text(
                    "ALTER TABLE abstract_schedules "
                    "ADD COLUMN IF NOT EXISTS quality_report JSONB"
                ))
                # Interim admin flag — replaced by RBAC role grants
                # (docs/workstreams/rbac.md) when that workstream lands.
                # Default false for all existing users; promotion
                # happens via ADMIN_EMAILS env-var allow-list at
                # login or by direct DB UPDATE.
                await conn.execute(text(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE"
                ))
                # Lineage pointer for forks (docs/workstreams/schedule-lifecycle.md
                # Part 5). NULL on existing rows means "original";
                # forks set this to the parent schedule's id.
                await conn.execute(text(
                    "ALTER TABLE assigned_schedules "
                    "ADD COLUMN IF NOT EXISTS forked_from_id BIGINT "
                    "REFERENCES assigned_schedules(id) ON DELETE SET NULL"
                ))
                # Index for "find all forks of schedule X" queries.
                # Partial index — most rows are NULL (originals).
                await conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS assigned_schedules_forked_from_idx "
                    "ON assigned_schedules(forked_from_id) "
                    "WHERE forked_from_id IS NOT NULL"
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
