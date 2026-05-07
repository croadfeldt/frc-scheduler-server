-- FRC Scheduler — schedule history + official mark + event freeze
-- Run once against the production DB after deploying the updated code.
-- Idempotent: every CREATE / ADD COLUMN / CREATE INDEX uses IF NOT EXISTS,
-- so re-running is safe.

-- ────────────────────────────────────────────────────────────────────
-- 1. Per-schedule history (copy-on-write recovery)
-- ────────────────────────────────────────────────────────────────────
-- One row per "save point" — initial create + before each PATCH +
-- restore actions. Snapshot stores the schedule's mutable fields.
-- Recovery: pick a row, restore back onto the live schedule via
-- POST /api/assigned-schedules/{id}/restore/{history_id}.
CREATE TABLE IF NOT EXISTS assigned_schedule_history (
    id                     BIGSERIAL    PRIMARY KEY,
    assigned_schedule_id   BIGINT       NOT NULL REFERENCES assigned_schedules(id) ON DELETE CASCADE,
    name                   VARCHAR(128) NOT NULL,
    day_config             JSONB,
    slot_map               JSONB        NOT NULL,
    practice_matches       JSONB,
    -- 'create' | 'patch' | 'rename' | 'restore'
    action                 VARCHAR(16)  NOT NULL,
    actor_user_id          BIGINT       REFERENCES users(id) ON DELETE SET NULL,
    actor_name             VARCHAR(256),
    occurred_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sched_history_schedule
    ON assigned_schedule_history (assigned_schedule_id, occurred_at DESC);

-- ────────────────────────────────────────────────────────────────────
-- 2. Per-schedule lock event log (audit)
-- ────────────────────────────────────────────────────────────────────
-- Every lock and unlock action writes one row here. Answers the
-- diagnostic question "when was this unlocked, by whom" — the live
-- assigned_schedules.locked_at column only carries the *current*
-- lock state.
CREATE TABLE IF NOT EXISTS assigned_schedule_lock_events (
    id                     BIGSERIAL    PRIMARY KEY,
    assigned_schedule_id   BIGINT       NOT NULL REFERENCES assigned_schedules(id) ON DELETE CASCADE,
    -- 'lock' | 'unlock'
    action                 VARCHAR(16)  NOT NULL,
    actor_user_id          BIGINT       REFERENCES users(id) ON DELETE SET NULL,
    actor_name             VARCHAR(256),
    occurred_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sched_lock_events_schedule
    ON assigned_schedule_lock_events (assigned_schedule_id, occurred_at DESC);

-- ────────────────────────────────────────────────────────────────────
-- 3. updated_at on assigned_schedules — cheap "has it changed" check
-- ────────────────────────────────────────────────────────────────────
-- Bumped to NOW() on every PATCH and on restore. Set equal to
-- created_at on initial insert. UI compares updated_at > created_at
-- (with a 1-second buffer) to render the "edited" badge.
ALTER TABLE assigned_schedules
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;
-- Backfill for existing rows: copy created_at so they read as
-- "never edited" until the next mutation.
UPDATE assigned_schedules
   SET updated_at = created_at
 WHERE updated_at IS NULL;
-- Make NOT NULL after backfill — only safe once all rows have a value.
ALTER TABLE assigned_schedules
    ALTER COLUMN updated_at SET NOT NULL;
ALTER TABLE assigned_schedules
    ALTER COLUMN updated_at SET DEFAULT NOW();

-- ────────────────────────────────────────────────────────────────────
-- 4. is_official + official_* on assigned_schedules
-- ────────────────────────────────────────────────────────────────────
-- "This is THE schedule" mark — permanent, one-per-event. Setting
-- is_official auto-locks the schedule; unmarking requires explicit
-- POST /unmark-official with confirmation in the UI.
ALTER TABLE assigned_schedules
    ADD COLUMN IF NOT EXISTS is_official       BOOLEAN     NOT NULL DEFAULT FALSE;
ALTER TABLE assigned_schedules
    ADD COLUMN IF NOT EXISTS official_at       TIMESTAMPTZ;
ALTER TABLE assigned_schedules
    ADD COLUMN IF NOT EXISTS official_by_user_id BIGINT     REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE assigned_schedules
    ADD COLUMN IF NOT EXISTS official_by_name  VARCHAR(256);

-- Partial unique index — at most one official per event. Postgres
-- allows multiple FALSE values but enforces uniqueness on TRUE rows.
-- This is the right tool here: a regular UNIQUE constraint on
-- (event_id, is_official) would forbid >1 non-official schedule per
-- event, which we want to allow.
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_official_per_event
    ON assigned_schedules (event_id) WHERE is_official = TRUE;

-- ────────────────────────────────────────────────────────────────────
-- 5. Event-level freeze (locked_at / locked_by_*)
-- ────────────────────────────────────────────────────────────────────
-- Strategic-level lock. When set, freezes event metadata edits and
-- all schedules under the event. Independent of per-schedule locks.
ALTER TABLE events
    ADD COLUMN IF NOT EXISTS locked_at         TIMESTAMPTZ;
ALTER TABLE events
    ADD COLUMN IF NOT EXISTS locked_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE events
    ADD COLUMN IF NOT EXISTS locked_by_name    VARCHAR(256);

-- ────────────────────────────────────────────────────────────────────
-- 6. Seed history for existing schedules
-- ────────────────────────────────────────────────────────────────────
-- Without this, the history view would show empty for schedules
-- created before the migration. Insert a synthetic 'create' row
-- carrying the current state — this becomes the "as-of-migration"
-- baseline. Skip if a history row already exists (idempotent).
INSERT INTO assigned_schedule_history
    (assigned_schedule_id, name, day_config, slot_map, practice_matches,
     action, actor_user_id, actor_name, occurred_at)
SELECT a.id, a.name,
       a.day_config::jsonb, a.slot_map::jsonb, a.practice_matches::jsonb,
       'create',
       NULL,                   -- no user known for pre-existing rows
       NULL,
       a.created_at
  FROM assigned_schedules a
 WHERE NOT EXISTS (
       SELECT 1 FROM assigned_schedule_history h
        WHERE h.assigned_schedule_id = a.id
       );

-- ────────────────────────────────────────────────────────────────────
-- Confirm
-- ────────────────────────────────────────────────────────────────────
SELECT 'assigned_schedule_history' AS table_name,
       COUNT(*) AS row_count FROM assigned_schedule_history
UNION ALL
SELECT 'assigned_schedule_lock_events', COUNT(*) FROM assigned_schedule_lock_events
UNION ALL
SELECT 'events with locked_at column', COUNT(*) FROM information_schema.columns
       WHERE table_name = 'events' AND column_name = 'locked_at'
UNION ALL
SELECT 'assigned_schedules.is_official column', COUNT(*) FROM information_schema.columns
       WHERE table_name = 'assigned_schedules' AND column_name = 'is_official'
UNION ALL
SELECT 'assigned_schedules.updated_at column', COUNT(*) FROM information_schema.columns
       WHERE table_name = 'assigned_schedules' AND column_name = 'updated_at';
