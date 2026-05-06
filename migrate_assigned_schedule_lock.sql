-- FRC Scheduler — add lock columns to assigned_schedules
-- Run once against the production DB after deploying the updated code.
-- All three columns are nullable so existing rows are unaffected.
-- Safe to run multiple times (IF NOT EXISTS guards each ADD COLUMN).

ALTER TABLE assigned_schedules ADD COLUMN IF NOT EXISTS locked_at         TIMESTAMPTZ;
ALTER TABLE assigned_schedules ADD COLUMN IF NOT EXISTS locked_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE assigned_schedules ADD COLUMN IF NOT EXISTS locked_by_name    VARCHAR(256);

-- Confirm
SELECT column_name, data_type, is_nullable
  FROM information_schema.columns
 WHERE table_name = 'assigned_schedules'
   AND column_name IN ('locked_at', 'locked_by_user_id', 'locked_by_name')
 ORDER BY column_name;
