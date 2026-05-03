"""Live event data — sync TBA scores/rankings, ingest Nexus webhooks, and
simulate progress for testing.

All functions are async and operate on a single event at a time. The /view
page calls refresh_event() lazily (max once per 60s) so we don't poll TBA
when nobody's watching, and one viewer's refresh benefits all viewers.
"""
from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from . import tba
from .db import (
    AssignedSchedule, Event, EventLiveSync, MatchResult, QueueStatus,
    TeamRanking, utcnow,
)

log = logging.getLogger(__name__)

# Throttle: never call TBA more often than once per N seconds per event,
# regardless of how many viewers ask for refreshes.
TBA_MIN_INTERVAL_SECONDS = 30


async def refresh_event(db: AsyncSession, event: Event, *, force: bool = False) -> dict:
    """Sync TBA matches + rankings for an event. Idempotent and throttled.

    Returns a dict describing the refresh result so callers can surface freshness:
        {ok: bool, source: 'tba'|'simulation'|'cache'|'skip',
         fetched_at: datetime, error: str|None, matches: int, rankings: int}

    If the event has simulation enabled, generates fake data instead of calling
    TBA. Used by /api/events/{id}/simulate/start to validate the live UI without
    a real event in progress.
    """
    sync = await db.get(EventLiveSync, event.id)
    if not sync:
        sync = EventLiveSync(event_id=event.id)
        db.add(sync)
        await db.flush()

    # Simulation mode short-circuits everything else
    if sync.sim_started_at is not None:
        return await _refresh_simulated(db, event, sync)

    # Throttle real TBA calls — caller asked for fresh, but we said no
    if not force and sync.tba_last_fetched:
        age = (datetime.now(timezone.utc) - sync.tba_last_fetched).total_seconds()
        if age < TBA_MIN_INTERVAL_SECONDS:
            return {"ok": True, "source": "cache", "fetched_at": sync.tba_last_fetched,
                    "error": None, "matches": 0, "rankings": 0,
                    "throttled": True, "age_seconds": int(age)}

    # No TBA event key on this event → nothing to fetch
    if not event.key:
        return {"ok": False, "source": "skip", "fetched_at": None,
                "error": "Event has no TBA key", "matches": 0, "rankings": 0}

    # ── Fetch from TBA ──
    matches_synced = 0
    rankings_synced = 0
    err: str | None = None
    try:
        # Matches
        tba_matches = await tba.get_event_matches(event.key)
        if tba_matches:
            matches_synced = await _upsert_matches(db, event.id, tba_matches)

        # Rankings (404 / empty for early-event)
        try:
            tba_rankings = await tba.get_event_rankings(event.key)
            if tba_rankings and "rankings" in tba_rankings:
                rankings_synced = await _upsert_rankings(db, event.id, tba_rankings)
        except Exception as e:
            log.info("rankings unavailable for %s: %s", event.key, e)

        sync.tba_last_fetched = datetime.now(timezone.utc)
        sync.tba_last_error = None
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        sync.tba_last_error = err[:500]
        log.warning("TBA refresh failed for %s: %s", event.key, err)

    await db.commit()
    return {
        "ok": err is None, "source": "tba", "fetched_at": sync.tba_last_fetched,
        "error": err, "matches": matches_synced, "rankings": rankings_synced,
    }


async def _upsert_matches(db: AsyncSession, event_id: int, tba_matches: list[dict]) -> int:
    """Bulk upsert TBA matches into the match_results table."""
    # Pull existing rows for this event keyed by (comp_level, match_num, set_num)
    existing = (await db.execute(
        select(MatchResult).where(MatchResult.event_id == event_id)
    )).scalars().all()
    by_key = {(r.comp_level, r.match_number, r.set_number): r for r in existing}

    count = 0
    for m in tba_matches:
        key = (m.get("comp_level", "qm"), m.get("match_number", 0), m.get("set_number", 1))
        # Pull alliances safely
        red  = (m.get("alliances") or {}).get("red",  {}) or {}
        blue = (m.get("alliances") or {}).get("blue", {}) or {}
        red_teams  = [_team_key_to_num(k) for k in (red.get("team_keys")  or [])]
        blue_teams = [_team_key_to_num(k) for k in (blue.get("team_keys") or [])]

        # TBA returns -1 for "not yet played" scores; normalize to None
        rs = red.get("score")
        bs = blue.get("score")
        if rs is not None and rs < 0: rs = None
        if bs is not None and bs < 0: bs = None

        winning = m.get("winning_alliance") or None
        if winning == "":
            # TBA uses empty string for ties when both scores are valid
            if rs is not None and bs is not None and rs == bs:
                winning = "tie"
            else:
                winning = None

        row = by_key.get(key)
        if row is None:
            row = MatchResult(
                event_id=event_id, comp_level=key[0],
                match_number=key[1], set_number=key[2],
            )
            db.add(row)

        row.actual_time      = m.get("actual_time")
        row.predicted_time   = m.get("predicted_time")
        row.post_result_time = m.get("post_result_time")
        row.red_teams        = red_teams
        row.blue_teams       = blue_teams
        row.red_score        = rs
        row.blue_score       = bs
        row.winning_alliance = winning
        row.score_breakdown  = m.get("score_breakdown")
        row.videos           = m.get("videos") or []
        row.fetched_at       = datetime.now(timezone.utc)
        count += 1

    await db.flush()
    return count


def _team_key_to_num(key: str) -> int:
    """'frc2169' -> 2169."""
    if not key: return 0
    s = key[3:] if key.startswith("frc") else key
    try: return int(s)
    except (ValueError, TypeError): return 0


async def _upsert_rankings(db: AsyncSession, event_id: int, tba_payload: dict) -> int:
    """Replace all rankings for the event with the latest TBA payload."""
    # TBA's "rankings" payload is verbose. Schema (2018+):
    #   payload.rankings = [{rank, team_key, record:{wins,losses,ties},
    #                        sort_orders:[...], extra_stats_info:[...],
    #                        matches_played, qual_average, ...}]
    rankings = tba_payload.get("rankings") or []
    sort_keys = [s.get("name") for s in (tba_payload.get("sort_order_info") or [])]

    # Wipe existing for simplicity (small event sizes — never thousands)
    await db.execute(delete(TeamRanking).where(TeamRanking.event_id == event_id))

    count = 0
    for r in rankings:
        team_num = _team_key_to_num(r.get("team_key", ""))
        if not team_num: continue
        rec = r.get("record") or {}
        sort_orders = r.get("sort_orders") or []
        # The first sort_order is conventionally the ranking score
        rscore = sort_orders[0] if sort_orders else None
        # Build a label→value dict for sort_orders so the UI can render them
        extra = {}
        for i, name in enumerate(sort_keys):
            if i < len(sort_orders) and name:
                extra[name] = sort_orders[i]

        db.add(TeamRanking(
            event_id=event_id, team_number=team_num,
            rank=r.get("rank"),
            wins=rec.get("wins", 0), losses=rec.get("losses", 0), ties=rec.get("ties", 0),
            matches_played=r.get("matches_played", 0),
            ranking_score=rscore if isinstance(rscore, (int, float)) else None,
            avg_match_score=r.get("qual_average"),
            extra_stats=extra or None,
            fetched_at=datetime.now(timezone.utc),
        ))
        count += 1

    await db.flush()
    return count


# ── Simulation ────────────────────────────────────────────────────────────────

async def start_simulation(db: AsyncSession, event_id: int, speedup: float = 60.0) -> dict:
    """Begin simulating event progress for testing live mode.

    Speedup defaults to 60x: 1 real second = 1 simulated minute. So a 7-hour
    event compresses to 7 minutes. Set speedup=1.0 for real-time playback.
    """
    sync = await db.get(EventLiveSync, event_id)
    if not sync:
        sync = EventLiveSync(event_id=event_id)
        db.add(sync)
    sync.sim_started_at = int(time.time())
    sync.sim_speedup = float(speedup)
    sync.tba_last_error = None
    # Wipe any existing match results so we start clean
    await db.execute(delete(MatchResult).where(MatchResult.event_id == event_id))
    await db.execute(delete(TeamRanking).where(TeamRanking.event_id == event_id))
    await db.execute(delete(QueueStatus).where(QueueStatus.event_id == event_id))
    await db.commit()
    return {"ok": True, "speedup": speedup, "started_at": sync.sim_started_at}


async def stop_simulation(db: AsyncSession, event_id: int) -> dict:
    """End simulation and clear simulated data. Restores live TBA mode."""
    sync = await db.get(EventLiveSync, event_id)
    if sync:
        sync.sim_started_at = None
        sync.sim_speedup = None
        sync.tba_last_fetched = None
    await db.execute(delete(MatchResult).where(MatchResult.event_id == event_id))
    await db.execute(delete(TeamRanking).where(TeamRanking.event_id == event_id))
    await db.execute(delete(QueueStatus).where(QueueStatus.event_id == event_id))
    await db.commit()
    return {"ok": True}


async def _refresh_simulated(db: AsyncSession, event: Event, sync: EventLiveSync) -> dict:
    """Generate fake match results based on simulated time.

    Strategy:
      - Simulated minutes elapsed = (real_seconds_since_start * speedup) / 60
      - Walk through the active assigned schedule's matches in order
      - A match becomes "playing" when sim_clock crosses its scheduled start
      - A match completes 2.5 sim minutes later with a random plausible score
      - Drift increases gradually so the UI's drift indicator has something to show
    """
    # Locate the active assigned schedule
    res = await db.execute(
        select(AssignedSchedule).where(
            AssignedSchedule.event_id == event.id,
            AssignedSchedule.is_active == True,  # noqa: E712
        )
    )
    assigned = res.scalar_one_or_none()
    if not assigned:
        # Fall back to most recent assigned schedule
        res = await db.execute(
            select(AssignedSchedule)
            .where(AssignedSchedule.event_id == event.id)
            .order_by(AssignedSchedule.created_at.desc())
            .limit(1)
        )
        assigned = res.scalar_one_or_none()
    if not assigned:
        sync.tba_last_error = "Simulation: no assigned schedule found"
        await db.commit()
        return {"ok": False, "source": "simulation", "fetched_at": None,
                "error": sync.tba_last_error, "matches": 0, "rankings": 0}

    # Resolve slot map → real teams
    slot_map = {int(k): v for k, v in (assigned.slot_map or {}).items()}
    # Get the abstract for matches
    await db.refresh(assigned, ["abstract_schedule"])
    abstract = assigned.abstract_schedule
    raw_matches = abstract.matches or []

    # Compute scheduled times from day_config
    scheduled_starts = _compute_scheduled_starts(assigned.day_config, len(raw_matches))

    # Simulated wall clock — minutes since some reference epoch
    real_now = int(time.time())
    sim_seconds = (real_now - (sync.sim_started_at or real_now)) * (sync.sim_speedup or 60.0)
    sim_minutes = sim_seconds / 60.0

    # Drift grows linearly: 1 minute of drift per 30 sim-minutes (capped)
    cumulative_drift_min = min(20.0, sim_minutes / 30.0)

    rng = random.Random(int(sync.sim_started_at or 0))

    # Wipe existing rows and rebuild — small data, simple
    await db.execute(delete(MatchResult).where(MatchResult.event_id == event.id))
    await db.execute(delete(QueueStatus).where(QueueStatus.event_id == event.id))

    rankings: dict[int, dict] = {}
    queue_rows: list[QueueStatus] = []

    for i, m in enumerate(raw_matches):
        match_num = i + 1
        scheduled_min = scheduled_starts[i] if i < len(scheduled_starts) else None
        # Apply drift to the predicted time
        predicted_min = (scheduled_min + cumulative_drift_min) if scheduled_min is not None else None
        # Resolve teams
        red  = [slot_map.get(s, s) for s in m.get("red", [])]
        blue = [slot_map.get(s, s) for s in m.get("blue", [])]

        # Determine match state from sim clock
        actual_time = predicted_time = post_time = None
        red_score = blue_score = None
        winning = None
        breakdown = None

        if predicted_min is not None:
            # Convert sim minutes to a real-looking unix timestamp
            # Anchor: pretend "minute 0" is 8:30 AM today
            today_anchor = _today_8_30_am_epoch()
            predicted_time = int(today_anchor + predicted_min * 60)

            if sim_minutes >= predicted_min + 2.5:
                # Completed
                actual_time = predicted_time
                post_time = actual_time + 90
                red_score, blue_score = _fake_score_pair(rng)
                winning = "red" if red_score > blue_score else ("blue" if blue_score > red_score else "tie")
                breakdown = _fake_breakdown(rng, red_score, blue_score)
                # Update rankings tally
                for t in red:
                    _bump_ranking(rankings, t, red_score, blue_score, won=(winning == "red"), tied=(winning == "tie"))
                for t in blue:
                    _bump_ranking(rankings, t, blue_score, red_score, won=(winning == "blue"), tied=(winning == "tie"))
            elif sim_minutes >= predicted_min:
                # Currently playing
                actual_time = predicted_time
                post_time = None

        # Queue status for the next few matches
        if predicted_min is not None and post_time is None and actual_time is None:
            mins_until = predicted_min - sim_minutes
            qstatus = None
            if 0 <= mins_until <= 4:
                qstatus = "on_deck"
            elif 4 < mins_until <= 8:
                qstatus = "now_queueing"
            elif 8 < mins_until <= 12:
                qstatus = "queueing_soon"
            if qstatus:
                queue_rows.append(QueueStatus(
                    event_id=event.id, comp_level="qm", match_number=match_num,
                    set_number=1, status=qstatus,
                    queue_time=int(_today_8_30_am_epoch() + predicted_min * 60),
                ))
        elif actual_time is not None and post_time is None:
            queue_rows.append(QueueStatus(
                event_id=event.id, comp_level="qm", match_number=match_num,
                set_number=1, status="on_field",
            ))

        db.add(MatchResult(
            event_id=event.id, comp_level="qm", match_number=match_num, set_number=1,
            actual_time=actual_time, predicted_time=predicted_time, post_result_time=post_time,
            red_teams=red, blue_teams=blue,
            red_score=red_score, blue_score=blue_score,
            winning_alliance=winning, score_breakdown=breakdown,
            videos=[], fetched_at=datetime.now(timezone.utc),
        ))

    for q in queue_rows:
        db.add(q)

    # Build rankings
    sorted_teams = sorted(
        rankings.items(),
        key=lambda kv: (-kv[1]["wins"] * 2 - kv[1]["ties"], -kv[1]["scored"]),
    )
    for rank, (team, stats) in enumerate(sorted_teams, 1):
        avg = stats["scored"] / stats["matches"] if stats["matches"] else 0.0
        db.add(TeamRanking(
            event_id=event.id, team_number=team,
            rank=rank,
            wins=stats["wins"], losses=stats["losses"], ties=stats["ties"],
            matches_played=stats["matches"],
            ranking_score=stats["wins"] * 2 + stats["ties"],
            avg_match_score=avg,
            extra_stats={"Ranking Score": stats["wins"] * 2 + stats["ties"],
                         "Avg Match": round(avg, 1)},
            fetched_at=datetime.now(timezone.utc),
        ))

    sync.tba_last_fetched = datetime.now(timezone.utc)
    sync.tba_last_error = None
    await db.commit()
    return {
        "ok": True, "source": "simulation", "fetched_at": sync.tba_last_fetched,
        "error": None, "matches": len(raw_matches), "rankings": len(rankings),
        "sim_minutes": round(sim_minutes, 1), "drift_minutes": round(cumulative_drift_min, 1),
    }


def _bump_ranking(rankings: dict, team: int, scored: int, allowed: int, *, won: bool, tied: bool) -> None:
    r = rankings.setdefault(team, {"wins": 0, "losses": 0, "ties": 0, "matches": 0, "scored": 0})
    r["matches"] += 1
    r["scored"] += int(scored or 0)
    if tied:    r["ties"] += 1
    elif won:   r["wins"] += 1
    else:       r["losses"] += 1


def _fake_score_pair(rng: random.Random) -> tuple[int, int]:
    """Generate plausible-looking FRC scores. Most matches in 80-180 range."""
    base = rng.randint(70, 180)
    return base + rng.randint(-25, 25), base + rng.randint(-25, 25)


def _fake_breakdown(rng: random.Random, red_score: int, blue_score: int) -> dict:
    """Year-agnostic score breakdown — uses keys that have been stable across
    games since 2018 (autoPoints, teleopPoints, foulPoints, endGamePoints)."""
    def split(total: int) -> dict:
        auto    = max(0, int(total * rng.uniform(0.15, 0.30)))
        endgame = max(0, int(total * rng.uniform(0.10, 0.25)))
        foul    = rng.choice([0, 0, 0, 5, 10])
        teleop  = max(0, total - auto - endgame - foul)
        return {
            "autoPoints":    auto,
            "teleopPoints":  teleop,
            "endGamePoints": endgame,
            "foulPoints":    foul,
            "totalPoints":   total,
        }
    return {"red": split(red_score), "blue": split(blue_score)}


def _today_8_30_am_epoch() -> int:
    """Return today's 8:30 AM as a unix timestamp."""
    now = datetime.now()
    today_830 = now.replace(hour=8, minute=30, second=0, microsecond=0)
    return int(today_830.timestamp())


def _compute_scheduled_starts(day_config: dict | None, num_matches: int) -> list[float]:
    """Walk the day_config and produce scheduled start minutes for each match.
    Mirrors the editor's _finishGenerationInner logic — keep in sync.

    Returns a list of starts in minutes-from-midnight. Lighter-weight than the
    full editor logic; honors day windows, breaks, and cycle-time changes."""
    cfg = day_config or {}
    days = cfg.get("days") or [{"start": "08:30", "end": "17:00", "breaks": [], "cycleChanges": []}]
    cycle_time = float(cfg.get("cycleTime") or 8)
    break_buf  = float(cfg.get("breakBuffer") or 5)

    starts: list[float] = []
    match_idx = 0
    for day in days:
        if match_idx >= num_matches: break
        start_min = _hhmm_to_min(day.get("start") or "08:30")
        end_min   = _hhmm_to_min(day.get("end") or "17:00")
        breaks    = sorted([
            {"start": _to_min(b.get("start")), "end": _to_min(b.get("end")), "done": False}
            for b in (day.get("breaks") or [])
            if b.get("start") and b.get("end")
        ], key=lambda b: b["start"])
        ccs = day.get("cycleChanges") or []
        cur_ct = cycle_time
        for cc in ccs:
            if cc.get("isStart") and cc.get("time"): cur_ct = float(cc["time"])
        cursor = float(start_min)
        early_end = day.get("earlyEnd")
        day_match_count = 0

        while match_idx < num_matches:
            # Flush breaks at/before cursor
            for b in breaks:
                if not b["done"] and b["start"] <= cursor:
                    cursor = max(cursor, b["end"])
                    b["done"] = True
            # Break-buffer
            nxt = next((b for b in breaks if not b["done"] and b["start"] > cursor), None)
            if nxt and break_buf > 0 and (nxt["start"] - cursor) < break_buf:
                cursor = max(cursor, nxt["end"])
                nxt["done"] = True
                continue
            # Effective ct
            ct = cur_ct
            for cc in ccs:
                if cc.get("isStart") and cc.get("time"): ct = float(cc["time"])
                elif (not cc.get("isStart")) and cc.get("afterMatch") and cc.get("time"):
                    if (match_idx + 1) > int(cc["afterMatch"]):
                        ct = float(cc["time"])
            match_end = cursor + ct
            interrupt = next((b for b in breaks if not b["done"]
                             and b["start"] > cursor and b["start"] < match_end), None)
            if interrupt and (not nxt or break_buf <= 0 or (nxt["start"] - cursor) < break_buf) is False:
                # Skip — flushed via break-buffer above
                pass
            elif interrupt:
                cursor = max(cursor, interrupt["end"])
                interrupt["done"] = True
                continue
            if match_end > end_min: break
            starts.append(cursor)
            cursor = match_end
            match_idx += 1
            day_match_count += 1
            if early_end and day_match_count >= int(early_end): break

    return starts


def _hhmm_to_min(s: str) -> int:
    if not s or ":" not in s: return 0
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _to_min(v: Any) -> int:
    if isinstance(v, (int, float)): return int(v)
    if isinstance(v, str): return _hhmm_to_min(v)
    return 0


# ── Nexus webhook ingestion ──────────────────────────────────────────────────

# Map Nexus's status values to ours. Nexus uses camelCase or kebab in different
# places; normalize aggressively.
_NEXUS_STATUS_MAP = {
    "queueing-soon": "queueing_soon",   "queueingSoon":  "queueing_soon",
    "now-queueing":  "now_queueing",    "nowQueueing":   "now_queueing",
    "on-deck":       "on_deck",         "onDeck":        "on_deck",
    "on-field":      "on_field",        "onField":       "on_field",
    "completed":     "completed",
}


async def ingest_nexus_event(db: AsyncSession, payload: dict) -> dict:
    """Process a Nexus webhook payload.

    The Nexus API documents several event types:
      - 'event-status': overall event state (e.g. running, lunch, ended)
      - 'match-status': individual match status changed
      - 'schedule-update': match schedule was modified

    We mostly care about match-status. Payload keys vary — handle gracefully.
    """
    # Nexus identifies events by a key like '2026mnst'; we look up our Event
    # row by that key.
    evt_key = (payload.get("event") or {}).get("key") or payload.get("eventKey") or ""
    if not evt_key:
        return {"ok": False, "error": "No event key in payload"}
    res = await db.execute(select(Event).where(Event.key == evt_key))
    event = res.scalar_one_or_none()
    if not event:
        # We don't track this event — silently accept (Nexus may send for many)
        return {"ok": True, "ignored": True, "reason": "Event not tracked"}

    sync = await db.get(EventLiveSync, event.id)
    if not sync:
        sync = EventLiveSync(event_id=event.id)
        db.add(sync)

    try:
        kind = (payload.get("type") or "").lower()
        if kind == "match-status" or "matchStatus" in payload:
            await _process_nexus_match_status(db, event.id, payload)
        elif kind == "schedule-update":
            # Schedule changed — we ignore for now; clients re-poll the schedule
            pass
        sync.nexus_last_event = datetime.now(timezone.utc)
        sync.nexus_last_error = None
    except Exception as e:
        sync.nexus_last_error = f"{type(e).__name__}: {e}"[:500]
        log.warning("nexus ingest error: %s", e)

    await db.commit()
    return {"ok": True}


async def _process_nexus_match_status(db: AsyncSession, event_id: int, payload: dict) -> None:
    ms = payload.get("matchStatus") or payload
    match_num = ms.get("matchNumber") or ms.get("match_number")
    comp_level = (ms.get("compLevel") or ms.get("comp_level") or "qm").lower()
    set_num = ms.get("setNumber") or ms.get("set_number") or 1
    status_raw = (ms.get("status") or "").strip()
    queue_time = ms.get("queueTime") or ms.get("queue_time")
    if not match_num or not status_raw:
        return
    status = _NEXUS_STATUS_MAP.get(status_raw, status_raw.replace("-", "_"))

    # Upsert
    res = await db.execute(
        select(QueueStatus).where(
            QueueStatus.event_id == event_id,
            QueueStatus.comp_level == comp_level,
            QueueStatus.match_number == int(match_num),
            QueueStatus.set_number == int(set_num),
        )
    )
    row = res.scalar_one_or_none()
    if row is None:
        row = QueueStatus(
            event_id=event_id, comp_level=comp_level,
            match_number=int(match_num), set_number=int(set_num),
            status=status, queue_time=queue_time,
        )
        db.add(row)
    else:
        row.status = status
        if queue_time: row.queue_time = queue_time


# ── Aggregation for /api/events/{id}/live ─────────────────────────────────────

async def get_event_live_data(db: AsyncSession, event: Event) -> dict:
    """Aggregate everything the /view page needs in one response.

    Returns:
      {
        event_id, event_key, fetched_at, sources: {tba, nexus, sim},
        matches: [{match_number, comp_level, ..., status: 'upcoming'|'playing'|'completed'}],
        rankings: [{team_number, rank, ...}],
        queue: [{match_number, status, queue_time}],
        drift_minutes: float|None,
      }
    """
    sync = await db.get(EventLiveSync, event.id)

    # Pull rows
    matches_res = await db.execute(
        select(MatchResult).where(MatchResult.event_id == event.id)
        .order_by(MatchResult.comp_level, MatchResult.match_number)
    )
    matches = matches_res.scalars().all()

    rankings_res = await db.execute(
        select(TeamRanking).where(TeamRanking.event_id == event.id)
        .order_by(TeamRanking.rank.asc().nulls_last())
    )
    rankings = rankings_res.scalars().all()

    queue_res = await db.execute(
        select(QueueStatus).where(QueueStatus.event_id == event.id)
        .order_by(QueueStatus.match_number)
    )
    queue = queue_res.scalars().all()

    # Compute drift: for each match where actual_time and predicted_time
    # both exist, drift is actual - scheduled. We take the median of the
    # most recent 5 to smooth out noise.
    drift_min: float | None = None
    if matches:
        recent_drifts = []
        for m in sorted(matches, key=lambda r: r.match_number, reverse=True):
            if m.actual_time and m.predicted_time:
                # We don't have the original scheduled time stored, use predicted as proxy.
                # Drift here is "how late actual was vs predicted."
                # The frontend computes additional drift vs originally-scheduled times.
                pass
            if m.predicted_time and m.actual_time and len(recent_drifts) < 5:
                recent_drifts.append((m.actual_time - m.predicted_time) / 60.0)
        if recent_drifts:
            recent_drifts.sort()
            drift_min = recent_drifts[len(recent_drifts) // 2]

    def match_status(m: MatchResult) -> str:
        if m.post_result_time or m.red_score is not None:
            return "completed"
        if m.actual_time:
            return "playing"
        return "upcoming"

    return {
        "event_id": event.id,
        "event_key": event.key,
        "fetched_at": (sync.tba_last_fetched.isoformat() if sync and sync.tba_last_fetched else None),
        "sources": {
            "tba": {
                "available": bool(sync and sync.tba_last_fetched and not sync.sim_started_at),
                "last_fetched": sync.tba_last_fetched.isoformat() if sync and sync.tba_last_fetched else None,
                "last_error": sync.tba_last_error if sync else None,
            },
            "nexus": {
                "available": bool(sync and sync.nexus_last_event),
                "last_event": sync.nexus_last_event.isoformat() if sync and sync.nexus_last_event else None,
                "last_error": sync.nexus_last_error if sync else None,
            },
            "simulation": {
                "active": bool(sync and sync.sim_started_at),
                "started_at": sync.sim_started_at if sync else None,
                "speedup": sync.sim_speedup if sync else None,
            },
        },
        "matches": [
            {
                "match_number":     m.match_number,
                "comp_level":       m.comp_level,
                "set_number":       m.set_number,
                "actual_time":      m.actual_time,
                "predicted_time":   m.predicted_time,
                "post_result_time": m.post_result_time,
                "red_teams":        m.red_teams or [],
                "blue_teams":       m.blue_teams or [],
                "red_score":        m.red_score,
                "blue_score":       m.blue_score,
                "winning_alliance": m.winning_alliance,
                "score_breakdown":  m.score_breakdown,
                "videos":           m.videos or [],
                "status":           match_status(m),
            }
            for m in matches
        ],
        "rankings": [
            {
                "team_number":     r.team_number,
                "rank":            r.rank,
                "wins":            r.wins,
                "losses":          r.losses,
                "ties":            r.ties,
                "matches_played":  r.matches_played,
                "ranking_score":   r.ranking_score,
                "avg_match_score": r.avg_match_score,
                "extra_stats":     r.extra_stats or {},
            }
            for r in rankings
        ],
        "queue": [
            {
                "match_number": q.match_number, "comp_level": q.comp_level,
                "status": q.status, "queue_time": q.queue_time,
                "updated_at": q.updated_at.isoformat() if q.updated_at else None,
            }
            for q in queue
        ],
        "drift_minutes": drift_min,
    }
