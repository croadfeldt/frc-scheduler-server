-- SPDX-License-Identifier: GPL-3.0-or-later
-- Migration: add personal_access_tokens table for CLI / programmatic API auth
--
-- Applied via the standard openshift migration job (08-build-cronjob style)
-- or manually:
--     psql $DATABASE_URL -f scripts/migrations/20260515_add_personal_access_tokens.sql
--
-- Safe to re-run: uses CREATE TABLE IF NOT EXISTS and CREATE INDEX IF NOT EXISTS.
-- Schema matches the SQLAlchemy model in app/db.py:PersonalAccessToken; if you
-- update one, update the other.

CREATE TABLE IF NOT EXISTS personal_access_tokens (
    id             BIGSERIAL PRIMARY KEY,
    user_id        BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name           VARCHAR(128) NOT NULL,
    token_prefix   VARCHAR(16)  NOT NULL,
    token_hash     VARCHAR(64)  NOT NULL UNIQUE,
    scopes         JSON         NOT NULL DEFAULT '["*"]',
    is_admin       BOOLEAN      NOT NULL DEFAULT FALSE,
    expires_at     TIMESTAMPTZ,
    revoked_at     TIMESTAMPTZ,
    last_used_at   TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- token_hash is the lookup path on every authenticated API request that
-- uses a PAT. Without this index, each request would do a sequential
-- scan of the table; with it, lookups are O(log n).
CREATE INDEX IF NOT EXISTS idx_pat_token_hash ON personal_access_tokens (token_hash);

-- Secondary index: list-by-user is the second hot path (UI + CLI `frc tokens list`).
CREATE INDEX IF NOT EXISTS idx_pat_user_id ON personal_access_tokens (user_id);

-- Partial index for "active tokens for user" — the most common list query.
-- Skips revoked tokens entirely. Optional optimization; safe to skip on
-- small deployments.
CREATE INDEX IF NOT EXISTS idx_pat_user_active
  ON personal_access_tokens (user_id, created_at DESC)
  WHERE revoked_at IS NULL;
