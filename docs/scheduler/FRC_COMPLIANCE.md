# FRC §10.5.2 Competition Compliance

**Status:** Backend complete. UI work pending.

## What this is

Every newly generated schedule gets a server-authoritative answer to
"is this legal for FRC competition?" stored alongside the schedule in
the database. The bit is computed from the algorithm-level settings
used to generate the schedule, not from a user's checkbox alone.

## Three columns on `assigned_schedules`

- `competition_approved BOOLEAN NULLABLE`:
  - `NULL` — pre-feature schedule (UI: "approval status unknown")
  - `TRUE` — generated with FRC §10.5.2 defaults
  - `FALSE` — at least one deviation from FRC defaults
- `audit_trail JSONB NULLABLE` — full forensic record (see shape below)
- (Index on `competition_approved` for filtered queries)

Migration: `migrate_competition_approved.sql` (idempotent).

## What counts as FRC default

See `app/frc_compliance.py::FRC_DEFAULTS`:

| Setting | FRC default | Why |
|---|---|---|
| `rb_post_pass` | True | FRC #5 (red/blue distribution) optimization |
| `station_post_pass` | True | FRC #6 (driver station distribution) optimization |
| `lex_score` | True | FRC §10.5.2 priority order enforcement |
| `hard_cooldown` | True | FRC #1 cooldown is paramount |
| `targeted_moves` | True | SA convergence; doesn't change criteria |
| `weights` | None | Lex tuple is authoritative; weights are legacy |
| `surrogate_handling` | `'3rd_match_as_surrogate'` | FRC standard |

`lex_score`, `hard_cooldown`, `targeted_moves` are always on after
Phase 0a/0b/0c — the request body can't disable them. They appear in
the audit trail for forensic completeness.

`rb_post_pass` and `station_post_pass` are user-controllable via the
generation request. The UI checkbox locks both to True.

## What's audited but not a deviation

- **Cooldown (`ideal_gap`)** — FRC says this varies by event size.
  Stored separately in `audit_trail.cooldown` when non-default (2 per
  project policy; see `phase1-f1e-eval-methodology.md`).
  Does NOT unset `competition_approved`.
- **Iteration count / quality preset** — controls search thoroughness,
  not algorithm choice. Always stored in `audit_trail.iterations_used`
  and `audit_trail.preset_used`.

## Audit trail JSON shape

```json
{
  "schema_version": 1,
  "competition_approved": true,
  "settings_used": {
    "rb_post_pass": true,
    "station_post_pass": true,
    "lex_score": true,
    "hard_cooldown": true,
    "targeted_moves": true,
    "weights": null,
    "surrogate_handling": "3rd_match_as_surrogate"
  },
  "frc_defaults_at_time_of_generation": { ... same shape ... },
  "deviations": [],
  "cooldown": null,
  "iterations_used": 2000000,
  "preset_used": "best"
}
```

When deviations exist:
```json
"deviations": [
  "R/B balance post-pass (Phase 1) disabled — FRC #5 (red/blue distribution) not optimized",
  "Station balance post-pass (Phase 2) disabled — FRC #6 (driver station distribution) not optimized"
]
```

When cooldown is non-default:
```json
"cooldown": {
  "value": 5,
  "project_default": 2,
  "note": "Cooldown editable per FRC §10.5.2 'varies by event size' guidance; project default is 2 per F1-e methodology decision (paramount-as-a-floor); not a deviation but recorded for audit"
}
```

## Why `frc_defaults_at_time_of_generation` exists

If FRC §10.5.2 changes in the future (new criterion, reordering), the
audit trail still tells us what *we* considered FRC-default at the
moment of generation. The schedule was approved under those rules.
Without this snapshot, audit comparisons against future versions of
`FRC_DEFAULTS` would be lossy.

## Behavior on duplicate / fork

`/duplicate` propagates `competition_approved` and `audit_trail`
unchanged. The fork is "the same algorithm-generated schedule, just
with a new ID and lineage pointer."

Manual edits via `PATCH /api/assigned-schedules/{id}` do NOT unset
`competition_approved`. The user's intent at generation time is
preserved; the edit is tracked separately in
`AssignedScheduleHistory`.

## Behavior on import (CSV / the reference scheduler)

The `/import` endpoint creates `AssignedSchedule` rows with
`competition_approved = NULL` (we don't know the algorithm
provenance of an externally-built schedule). UI renders this as
"imported — approval status unknown."

## API contract for UI work

### Request
`POST /api/abstract-schedules/{id}/assign`
```json
{
  "event_id": 1,
  "abstract_schedule_id": 42,
  "name": "State Quals",
  "quality_preset": "best",            // or 'fair' | 'good' | 'maximum'
  "competition_approved": true,        // UI hint, server validates
  "rb_post_pass": true,                // checkbox locks this on
  "station_post_pass": true,           // checkbox locks this on
  "cooldown": 2                        // editable, audited if != 2 (project default per F1-e)
}
```

### Response (per schedule GET)
```json
{
  "id": 123,
  "name": "State Quals",
  ...
  "competition_approved": true,        // OR null, OR false
  "audit_trail": { ... see shape above ... }
}
```

### List response (lighter)
```json
[{ "id": 123, "name": "...", "competition_approved": true, ... }]
```

## UI work pending

These are not yet implemented in `static/index.html` /
`static/view.html`:

1. **Generate form**: prominent green checkbox at top of advanced
   settings, defaulted to checked. Banner: "Generated with FRC
   §10.5.2 defaults." Auto-uncheck on any algorithm setting edit.
2. **Edit page banner**: green "FRC Approved" / yellow "Approval
   Unknown" / red "Settings deviate from FRC §10.5.2."
3. **Schedule list**: small badge per schedule (✓ green, ! yellow, ?
   gray).
4. **Audit modal**: clicking the badge opens a modal with the full
   `audit_trail` JSON rendered as human-readable rows.
5. **"Reset to FRC defaults" modal**: when re-checking an unchecked
   box, confirm: "Reset all algorithm settings to FRC §10.5.2 defaults?"

When implementing the UI, read this doc first to understand which
settings affect approval and which are just audited.

## Tests

`tests/test_frc_compliance.py` — 11 tests covering:
- Default settings yield zero deviations
- Each individual deviation type detected correctly
- Multiple deviations all reported
- Cooldown audited but not a deviation
- Audit record shape stable
- FRC defaults snapshot captured for forensic comparison
- settings_used independence (no shared mutable state)
- Deviation strings are human-readable

Run with: `python3 tests/test_frc_compliance.py`
