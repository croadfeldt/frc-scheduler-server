# Metrics/Scores Split — Persisted vs Derived

**Modules:** `app/quality_report.py`, `app/quality_scoring.py`
**Schema:** `abstract_schedules.quality_report` (metrics), `creation_provenance` (audit)
**Tests:** `tests/test_metrics_scores_split.py`

---

## The problem this fixes

Phase B persisted the full `quality_report` JSON — metrics AND scores —
to the `abstract_schedules.quality_report` column. Phase C added
scoring on top. That created a staleness trap: when scoring curves
or weights change, every stored row becomes incorrect because its
embedded scores reflect old math, but the UI displays them anyway.

The fix: **only metrics are persisted; scores are derived at every
read**. The math runs against current code under current weights
on every request — no possibility of stale scores.

---

## Storage shape

The `quality_report` JSONB column now stores only:

```json
{
  "achieved_lex_tuple": [0, 252, 462, 0, 1, 43, 0, 0],
  "is_valid_paramount": true,
  "metrics": {
    "cooldown_violations":     {"value":0, "floor":0, ...},
    "par_quad":                {"value":252, "floor":252, ...},
    "opp_quad":                {"value":462, "floor":378, ...},
    "surrogate_count":         {"value":0, "floor":0, ...},
    "rb_per_team":             {"value":1, "floor":1, ...},
    "station_per_team_spread": {"value":1, "floor":1, ...}
  },
  "summary": {
    "all_proven_floors_matched": true,
    "n_metrics_at_floor": 4,
    "n_metrics_total": 6
  }
}
```

No `scores` key. Metrics are observations of the schedule against
the fixture's floors; deterministic given the matches; stable for
the lifetime of an AbstractSchedule.

When the GET endpoint returns this row, scores are computed fresh
and attached:

```json
{
  ...persisted...,
  "scores": {
    "composite": 100.0,
    "composite_uncapped": 100.0,
    "per_criterion": {
      "cooldown":  {"score": 100.0, ...},
      "partner":   {"score": 100.0, ...},
      "opponent":  {"score":  95.1, ...},
      "surrogate": {"score": 100.0, ...},
      "color":     {"score": 100.0, ...},
      "station":   {"score": 100.0, ...}
    },
    "weights_used": {...},
    "best_known_floors_used": true
  }
}
```

The `scores` block is computed by `apply_scores()` at read time.
If scoring curves later change, the next read picks up the new
math automatically. No backfill needed for the score change itself —
only for the underlying metrics, if those change.

---

## API surface

### Reads always derive scores

`GET /api/abstract-schedules/{id}` calls `apply_scores()` against
the stored metrics, using the schedule's `quality_weights` (or
DEFAULT_QUALITY_WEIGHTS if NULL). The response always reflects
current scoring code.

If a row's `quality_report` is NULL or lacks `metrics` (legacy /
pre-Phase-B rows), the GET response carries `quality_report: null`
or a metrics-less object. The UI's auto-backfill (see below)
populates it on first view.

### `POST /api/abstract-schedules/{id}/backfill-metrics`

Computes metrics from the stored matches and persists them.
Idempotent — safe to call repeatedly. Default behavior is "if
already populated, no-op." Pass `?force=true` to recompute (useful
after changes to `compute_metrics()` or fixture floor definitions).

Response includes the derived scores under default weights so the
caller can immediately render.

### `POST /api/abstract-schedules/{id}/rescore`

Re-scores under different weights without modifying the row.
Logically redundant with "GET with weights query param" (which
we don't expose due to URL-encoding awkwardness) — kept as the
dedicated weight-override path used by the UI's live slider
rescoring.

### `POST /api/score-preview`

Stateless. Takes a matches list + fixture shape + (optional)
weights. Returns metrics + scores. Persists nothing. Useful for:

- Editor what-if previews: "what would this schedule score if I
  made this change?" without persisting the edit
- Import preview: score before deciding to save
- Third-party tools comparing their own output

---

## Creation provenance (auditability)

The `abstract_schedules.creation_provenance` JSONB column captures
how each schedule came to exist. Shape varies by method:

```json
// SA-generated
{
  "method": "sa_generated",
  "sa_iterations": 500000,
  "sa_weights": {...} | null,
  "seed": "abc123" | null,
  "created_via": "POST /api/schedules (generate)"
}

// Canonical library
{
  "method": "canonical_library",
  "canonical_provenance": {...},  // copy of the canonical's own provenance
  "canonical_confidence": "best_known" | "matches_floor" | "proven_optimal",
  "created_via": "POST /api/schedules (canonical)"
}

// Imported
{
  "method": "imported",
  "source_url": "https://..." | null,
  "created_via": "POST /api/schedules (import)"
}
```

NULL on pre-existing rows; populated for every new schedule via
the unified endpoint and the legacy `/api/generate-abstract`.

Audit for AbstractSchedule is creation-only because the row is
immutable after creation. Mutations happen on AssignedSchedule
(stage 2: team-number-mapped); that table already has the
`assigned_schedule_history` snapshot mechanism for revisions.

---

## UI behavior

### Auto-backfill on load

When the Quality card loads a schedule whose `quality_report` is
NULL or lacks `metrics`, `loadDiversityReport()` calls
`/backfill-metrics` and renders with the fresh data. Silent —
no button, no flicker. Failures log to console but don't disrupt
the rest of the card.

### Live debounced rescore

The weights editor's sliders update scores live as the user moves
them. Debounced at 200ms so rapid slider movement coalesces into
a single network call. The "Re-score" button is removed (now
redundant). "Reset to defaults" triggers an immediate rescore.

### Score-preview hook (future)

The `/score-preview` endpoint is wired but not yet called from
the UI. When the editor gains live mutation support (manual team
swaps, surrogate edits before save), the score-preview path
gives it interactive feedback without persisting changes.

---

## Bulk backfill

```bash
# Dry-run: report what would change
python3 scripts/backfill_quality_metrics.py --dry-run

# Apply
python3 scripts/backfill_quality_metrics.py

# Force-recompute every row (useful after compute_metrics() changes)
python3 scripts/backfill_quality_metrics.py --force
```

The script iterates the production DB, identifies rows needing
backfill (NULL, missing `metrics`, or carrying stale `scores`),
and rebuilds them metrics-only.

---

## Why this matters

Three concrete wins from the split:

1. **No stale-score trap.** When we tune scoring curves (the
   rb_per_team post-pass weakness we identified in Phase C, or
   future Phase D-driven adjustments), the next read reflects
   the new math everywhere — old schedules and new alike.

2. **Cheaper canonical re-curation.** Higher-budget canonical
   rebuilds on Stark don't need to coordinate with scoring code
   changes. The canonicals store matches + metrics + provenance;
   scoring is applied at use time.

3. **Cleaner mental model for organizers.** A schedule's metrics
   are facts. Scores are interpretations. The UI now shows you
   the same facts under whatever scoring you want, never under
   "scoring code as of when this was created."

The tradeoff: every GET on an abstract schedule does ~10ms of
scoring work. Acceptable given the read volume profile and the
correctness benefit.
