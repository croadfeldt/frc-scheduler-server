-- FRC Scheduler — widen string columns that TBA data can overflow
-- Run once against the production DB after deploying the updated code.
-- Safe to run multiple times (ALTER TYPE to TEXT is idempotent if already TEXT).

ALTER TABLE teams  ALTER COLUMN name     TYPE TEXT;
ALTER TABLE events ALTER COLUMN name     TYPE TEXT;
ALTER TABLE events ALTER COLUMN location TYPE TEXT;

-- Confirm
SELECT column_name, data_type, character_maximum_length
  FROM information_schema.columns
 WHERE table_name IN ('teams','events')
   AND column_name IN ('name','location')
 ORDER BY table_name, column_name;
