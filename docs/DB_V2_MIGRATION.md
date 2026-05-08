# DB migration to V2-native day_config

**Status:** active. Goal — every `day_config` JSON column in the
database holds a `dayConfigVersion: 2` object, validated per
[V2_SPEC.md](V2_SPEC.md).

---

## 1. Current state

Three tables hold `day_config` as a `JSON` column with no type
constraints (any shape accepted):

| Table                          | Column          | NULL? | Source                                      |
|--------------------------------|-----------------|-------|---------------------------------------------|
| `abstract_schedules`           | `day_config`    | yes   | POST `/abstract-schedules` body            |
| `assigned_schedules`           | `day_config`    | yes   | POST `/assigned-schedules` body            |
| `assigned_schedule_history`    | `day_config`    | yes   | snapshot taken on lock/unlock/edit         |

(See `app/db.py` lines 130, 169, 235.)

The shape stored is whatever the client sends. Today the client sends
`downgradeToV1(v2dc)` — V1 shape, lossy on type info. Older rows may
hold pure V1 (no `dayConfigVersion`) or partial V2 mid-development
shapes.

## 2. Target state

After migration:

- Every row's `day_config` has `dayConfigVersion: 2` at the top level.
- Every row's `day_config` validates against the V2 schema (see
  [V2_SPEC.md](V2_SPEC.md)).
- The column type stays `JSON`. (We don't move to JSONB or a typed
  schema yet; if validation pressure grows, we will.)

## 3. Migration strategy

One-shot SQL migration plus a server-side fallback for any rows that
slipped through.

### 3.1 The migration script

`migrate_day_config_to_v2.sql` (to be authored) — runs the V1→V2
reconstruction in PL/pgSQL, mirroring the JS `migrateLegacyDayConfig`
logic. The PG version preserves type metadata (`subtype`,
`ceremonyKind`, `breakKind`) when V1 break entries carry them; falls
back to heuristic classification when they don't.

Pseudocode:

```sql
UPDATE abstract_schedules
SET day_config = migrate_v1_to_v2(day_config)
WHERE day_config IS NOT NULL
  AND COALESCE((day_config->>'dayConfigVersion')::int, 1) < 2;

UPDATE assigned_schedules        SET day_config = migrate_v1_to_v2(day_config) WHERE …;
UPDATE assigned_schedule_history SET day_config = migrate_v1_to_v2(day_config) WHERE …;
```

`migrate_v1_to_v2(jsonb)` is a PL/pgSQL function that:

1. Returns the input unchanged if `dayConfigVersion = 2`.
2. Constructs a V2 root with `dayConfigVersion: 2`, `cycleTime`,
   `breakBuffer` from the V1 input.
3. For each V1 day, builds a single V2 day with:
   - One `qualification` block for `(start, end)` carrying the V1
     `cycleTime` and `cycleChanges[].afterMatch` translated to local.
   - Tier-3 children for V1 break entries:
     - If the break has `subtype` field (post-fix-3 saves), routes
       by subtype: `alliance_selection | awards | ceremony` → day
       level; `break` → into the qual block.
     - Else (pre-subtype legacy data), all breaks go into the qual
       block. Loses no information that the V1 row had.
4. For each V1 `practiceDay` (when enabled), builds a separate day
   with one `practice` block.
5. For each V1 `playoffBlocks[]` entry, attaches a `playoff` block
   to the day at `dayIndex`.

### 3.2 Server-side fallback

`app/main.py` GET handlers (B-04 in
[V1_RETIREMENT.md](V1_RETIREMENT.md)) run the migrator on read for
any row that's still V1-shape. After the one-shot SQL migration,
this should never fire — but it's a safety net for any row that
escapes (e.g. created by an older client during deploy).

This fallback gets removed in phase 5 (after a confidence period
where the metric stays at zero invocations).

### 3.3 Validation on write

`app/main.py` POST/PATCH handlers (B-01, B-02, B-03 in
[V1_RETIREMENT.md](V1_RETIREMENT.md)) validate incoming `day_config`
against the V2 Pydantic model. Rejects with 400 if non-conforming.

During the transition, the server can auto-migrate V1 input on
write — but this masks client-side bugs. Better to fail loud and
make the editor fix its emit.

## 4. Schema changes (none required)

The `JSON` column type accepts arbitrary shape. No DDL change is
required for the migration itself. We may later add:

- A check constraint: `(day_config IS NULL) OR (day_config->>'dayConfigVersion' = '2')`
  — added in phase 5 as a one-way ratchet.
- A CHECK on the JSON for top-level field presence (`days`,
  `cycleTime`) — same phase.

## 5. Backfill + rollback strategy

### Backfill

The migration script is idempotent — running it twice is a no-op
because of the version guard (`< 2`). Safe to run repeatedly.

### Snapshot before migrating (OpenShift)

The cluster runs PostgreSQL in a pod (currently
`frc-postgres-58ddc5cd7-6v56s`); pod names rotate on redeploy, so
all commands resolve the current pod by label first.

```bash
# Resolve the current postgres pod by label.
PG_POD=$(oc get pod -l app=frc-postgres -o jsonpath='{.items[0].metadata.name}')
echo "Postgres pod: $PG_POD"

# Stream pg_dump output directly to a local file via stdout.
# --column-inserts produces one INSERT per row (verbose but
# survives schema drift better than copy-binary on restore).
# --data-only because the schema lives in our migration files,
# not in the dump (we don't want to drop+recreate tables on
# rollback).
TS=$(date -u +%Y%m%d_%H%M%S)
oc exec "$PG_POD" -- bash -c \
  'pg_dump -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    --table=abstract_schedules \
    --table=assigned_schedules \
    --table=assigned_schedule_history \
    --data-only --column-inserts' \
  > "pre_v2_migration_backup_${TS}.sql"

# Verify the dump is non-empty and looks like SQL.
ls -la "pre_v2_migration_backup_${TS}.sql"
head -20 "pre_v2_migration_backup_${TS}.sql"
```

**Storage:** keep the dump in a versioned location (e.g. a private
GitHub gist, a personal cloud drive, or just a local backup folder
that's part of your normal backup rotation). The dump contains user
data — store accordingly.

### Apply the migration (OpenShift)

```bash
# Copy the migration SQL to the pod, run it, verify, clean up.
oc cp ./migrate_day_config_to_v2.sql "$PG_POD":/tmp/migration.sql

oc exec -it "$PG_POD" -- \
  psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
       -f /tmp/migration.sql

# Spot-check: every row should now report version 2.
oc exec "$PG_POD" -- \
  psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
       -c "SELECT 'abstract' AS tbl, day_config->>'dayConfigVersion' AS v, COUNT(*) FROM abstract_schedules WHERE day_config IS NOT NULL GROUP BY 2
           UNION ALL
           SELECT 'assigned', day_config->>'dayConfigVersion', COUNT(*) FROM assigned_schedules WHERE day_config IS NOT NULL GROUP BY 2
           UNION ALL
           SELECT 'history',  day_config->>'dayConfigVersion', COUNT(*) FROM assigned_schedule_history WHERE day_config IS NOT NULL GROUP BY 2;"

# Tidy up the pod.
oc exec "$PG_POD" -- rm -f /tmp/migration.sql
```

Expected output: every row in the `v` column should be `2` after
migration.

### Rollback procedure (OpenShift)

Only required if phase 1-2 surfaces a blocker that can't be hot-fixed.

```bash
PG_POD=$(oc get pod -l app=frc-postgres -o jsonpath='{.items[0].metadata.name}')

# 1. Stop the application pods to prevent concurrent writes.
oc scale deployment/frc-scheduler --replicas=0

# 2. Truncate the affected tables. CASCADE because of FK relationships
#    (assigned_schedules -> abstract_schedules, history -> assigned).
oc exec -it "$PG_POD" -- \
  psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
       -c "TRUNCATE assigned_schedule_history, assigned_schedules, abstract_schedules CASCADE;"

# 3. Restore from the snapshot.
oc cp ./pre_v2_migration_backup_TIMESTAMP.sql "$PG_POD":/tmp/restore.sql
oc exec -it "$PG_POD" -- \
  psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
       -f /tmp/restore.sql

# 4. Redeploy the prior application image.
oc rollout undo deployment/frc-scheduler

# 5. Bring traffic back.
oc scale deployment/frc-scheduler --replicas=1

# 6. Verify the app responds and old schedules load correctly.
curl -sf https://frc-scheduler.roadfeldt.com/healthz
```

### Routine backups (independent of migration)

Recommended ongoing practice — independent of the V2 migration:

```bash
# Add to a cron or run before any deploy that touches DB schema.
PG_POD=$(oc get pod -l app=frc-postgres -o jsonpath='{.items[0].metadata.name}')
TS=$(date -u +%Y%m%d_%H%M%S)
oc exec "$PG_POD" -- \
  pg_dump -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  > "frc_full_backup_${TS}.sql"
```

A full dump (no `--data-only`) preserves both schema and data, so a
single restore command rebuilds the database from scratch. Useful
before any schema migration; less convenient for partial restores.

### Verifying a backup is restorable

Belt-and-suspenders check before relying on any backup:

```bash
# Spin up a throwaway postgres locally, restore the dump, verify
# row counts match the source.
docker run --rm -d --name frc-restore-test \
  -e POSTGRES_PASSWORD=test -p 5544:5432 postgres:16
sleep 5
docker exec -i frc-restore-test \
  psql -U postgres -c "CREATE DATABASE frc_scheduler;"
docker exec -i frc-restore-test \
  psql -U postgres -d frc_scheduler < frc_full_backup_TIMESTAMP.sql
docker exec -i frc-restore-test \
  psql -U postgres -d frc_scheduler -c "SELECT COUNT(*) FROM abstract_schedules;"
docker stop frc-restore-test
```

If the count matches what `oc exec` shows on the live pod, the backup
is restorable.

## 6. Migration window

The migration runs during a planned maintenance window. Steps:

1. Announce maintenance.
2. Snapshot the three tables (per §5 "Snapshot before migrating").
3. Verify the snapshot is restorable (per §5 "Verifying a backup").
4. Stop write traffic:
   ```bash
   oc scale deployment/frc-scheduler --replicas=0
   ```
5. Apply the migration (per §5 "Apply the migration"). Should take
   seconds for typical workloads (a few hundred rows).
6. Spot-check 5-10 rows: query `day_config->>'dayConfigVersion'`
   should return `'2'`; full V2 validation passes (§5 has the
   one-shot SQL for this).
7. Resume traffic:
   ```bash
   oc scale deployment/frc-scheduler --replicas=1
   oc rollout status deployment/frc-scheduler
   ```
8. Watch the server-side fallback metric for 30 days. If zero, drop
   the fallback in a phase-5 cleanup pass.

Total expected downtime: under 5 minutes for current data volumes
(the snapshot + migration + verification all run in seconds; the
bulk of the window is application restart and smoke-testing).

## 7. Adjacent considerations

### 7.1 Practice match data

`assigned_schedules.practice_matches` (line 191 in `db.py`) holds
already-resolved practice match pairings. Not affected by V2
migration — it's a flat list of matches, no day_config dependency.

### 7.2 `round_boundaries` and `surrogate_count`

These reference the abstract `matches` array by index. Unaffected by
V2 migration since they don't carry day_config-derived data.

### 7.3 `weights`

The placement criteria weights JSON (line 161 in `db.py`) is its own
small object, unaffected by V2 migration.

### 7.4 `events` table

No `day_config` column on `events`. The day config travels with
schedules, not events. Events stay V2-agnostic.

## 8. Out of scope

- Renaming `day_config` to `day_config_v2`. The column name stays;
  the wire-version field inside it (`dayConfigVersion`) is the
  source of truth for shape.
- Splitting `day_config` into separate columns (e.g. `cycle_time`
  as its own column). The JSON blob is the right representation
  for tree-shaped editor state.
- Per-row schema versioning of other JSON columns (`matches`,
  `slot_map`). Those have stable shapes already.
