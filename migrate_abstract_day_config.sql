-- Migration: add day_config column to abstract_schedules
-- Run once on any existing database before deploying this build.
--
-- oc exec -n frc-scheduler-server $(oc get pod -l app=frc-postgres -o name) \
--   -- psql -U frc -d frc_scheduler \
--   -c "ALTER TABLE abstract_schedules ADD COLUMN IF NOT EXISTS day_config JSON;"

ALTER TABLE abstract_schedules ADD COLUMN IF NOT EXISTS day_config JSON;
