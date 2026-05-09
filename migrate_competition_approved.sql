-- FRC Scheduler — competition-approved checkbox + audit trail
-- Run once against the production DB after deploying the updated code.
-- Idempotent: ADD COLUMN uses IF NOT EXISTS, so re-running is safe.

-- ────────────────────────────────────────────────────────────────────
-- AssignedSchedule: add three columns for FRC compliance audit trail
-- ────────────────────────────────────────────────────────────────────

-- competition_approved:
--   NULL = pre-feature schedule (created before this migration). UI
--          should render as "unknown" rather than yes/no.
--   TRUE = generated with FRC §10.5.2 defaults (no deviations).
--   FALSE = at least one deviation from FRC defaults at generation time.
ALTER TABLE assigned_schedules
    ADD COLUMN IF NOT EXISTS competition_approved BOOLEAN;

-- audit_trail:
--   JSONB containing the full audit record built by
--   app.frc_compliance.build_audit_record(). Includes:
--     - schema_version (int)
--     - competition_approved (bool, redundant with the column above)
--     - settings_used (dict — actual settings used)
--     - frc_defaults_at_time_of_generation (dict — what we considered
--       FRC-default at the time, for forensic comparison if FRC §10.5.2
--       changes in the future)
--     - deviations (list of strings — human-readable departures)
--     - cooldown (dict|null — ideal_gap value if non-default)
--     - iterations_used (int — SA budget actually used)
--     - preset_used (string|null — quality preset name if any)
--   NULL on pre-feature schedules.
ALTER TABLE assigned_schedules
    ADD COLUMN IF NOT EXISTS audit_trail JSONB;

-- For fast filtering "show me only competition-approved schedules"
CREATE INDEX IF NOT EXISTS idx_assigned_schedules_comp_approved
    ON assigned_schedules (competition_approved)
    WHERE competition_approved IS NOT NULL;

-- Backfill is intentionally NOT done. Pre-feature schedules stay NULL,
-- which the UI renders as "Generated before this feature existed —
-- approval status unknown." Backfilling would require us to invent a
-- settings_used record that we don't actually know.
