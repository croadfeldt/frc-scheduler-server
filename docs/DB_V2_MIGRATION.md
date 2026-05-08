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

`scripts/migrate_db_to_v2.py` is the authoritative migration tool.
It uses `app.day_config_v2.migrate_v1_to_v2()` — the same Python
function exercised by `tests/test_day_config_v2.py` (31 passing tests)
— wrapped in SQLAlchemy plumbing that walks each `day_config`-bearing
table and rewrites V1 rows to V2.

Choice of Python over PL/pgSQL: keeps the migration logic in one
place. The V1→V2 reconstruction has nuance (subtype detection,
ceremony-kind heuristics, alliance-selection hoisting) that's
already battle-tested in Python. Porting it to PL/pgSQL would
duplicate the logic and add a drift risk.

The script supports three modes:
- **Default (dry run):** reports what would change without writing.
- `--apply`: actually rewrites V1 rows. Idempotent — V2 rows skip,
  null rows skip.
- `--verify`: prints the version distribution without modifying anything.

`scripts/openshift_migrate.sh` wraps this script with the snapshot
workflow described in §5 and §6, so the operator runs one command
rather than orchestrating snapshot + copy + exec by hand.

### 3.2 Server-side fallback

The fallback already exists. `app/main.py` GET handlers route
all stored `day_config` values through `app.day_config_v2.normalize_to_v2()`
before returning them. Pre-migration rows return as V2 transparently.

After phase 2 completes, the fallback is no longer load-bearing
(every row is V2 in storage) but stays in place as a safety net
through phase 5.

### 3.3 Validation on write

`app/main.py` POST/PATCH handlers route incoming `day_config`
through `_normalize_dc()`, which validates against `DayConfigV2`
(per [V2_SPEC.md](V2_SPEC.md) §8) and rejects malformed input
with HTTP 400. V1-shape input is auto-migrated.

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

The full flow is wrapped in `scripts/openshift_migrate.sh apply` (see §6).
The lower-level commands it runs:

```bash
APP_POD=$(oc get pod -l app=frc-scheduler-server-git -o jsonpath='{.items[0].metadata.name}')

# Copy the migration script to the scheduler pod (where Python deps
# are installed; postgres pod doesn't have Python dependencies).
oc cp scripts/migrate_db_to_v2.py "$APP_POD":/tmp/migrate_db_to_v2.py

# Dry-run to preview. Reports version distribution + per-table
# counts of "would write" / "skipped" / "errors". No writes.
oc exec "$APP_POD" -- python /tmp/migrate_db_to_v2.py

# Apply. Idempotent — V2 rows skip; only V1 rows are rewritten.
oc exec "$APP_POD" -- python /tmp/migrate_db_to_v2.py --apply

# Verify post-migration state. Every row should report v2; v1 count
# should be 0. Null is fine (some rows legitimately have no day_config).
oc exec "$APP_POD" -- python /tmp/migrate_db_to_v2.py --verify

# Tidy up the script from the pod.
oc exec "$APP_POD" -- rm -f /tmp/migrate_db_to_v2.py
```

Spot-check directly via psql if you want a second confirmation:

```bash
PG_POD=$(oc get pod -l app=frc-postgres -o jsonpath='{.items[0].metadata.name}')
oc exec "$PG_POD" -- \
  psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
       -c "SELECT 'abstract' AS tbl, day_config->>'dayConfigVersion' AS v, COUNT(*) FROM abstract_schedules WHERE day_config IS NOT NULL GROUP BY 2
           UNION ALL
           SELECT 'assigned', day_config->>'dayConfigVersion', COUNT(*) FROM assigned_schedules WHERE day_config IS NOT NULL GROUP BY 2
           UNION ALL
           SELECT 'history',  day_config->>'dayConfigVersion', COUNT(*) FROM assigned_schedule_history WHERE day_config IS NOT NULL GROUP BY 2;"
```

Expected output: every row in the `v` column should be `2` after migration.

### Rollback procedure (OpenShift)

Only required if phase 1-2 surfaces a blocker that can't be hot-fixed.

```bash
PG_POD=$(oc get pod -l app=frc-postgres -o jsonpath='{.items[0].metadata.name}')

# 1. Stop the application pods to prevent concurrent writes.
oc scale deployment/frc-scheduler-server --replicas=0

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
oc rollout undo deployment/frc-scheduler-server

# 5. Bring traffic back.
oc scale deployment/frc-scheduler-server --replicas=1

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

The migration runs during a planned maintenance window. With the
wrapper script (`scripts/openshift_migrate.sh`), the steps collapse to:

1. Announce maintenance.
2. (Optional) Stop write traffic if you want a frozen snapshot:
   ```bash
   oc scale deployment/frc-scheduler-server --replicas=0
   ```
   *Strictly speaking the migration is safe with traffic running —
   it's idempotent and atomic per row — but a quiescent window
   makes the snapshot match the post-migration state exactly.*
3. Dry-run first to preview:
   ```bash
   ./scripts/openshift_migrate.sh dryrun
   ```
   This snapshots, then runs the migration in dry-run mode. The
   snapshot is preserved either way. Output shows version
   distribution before, list of would-write per row, and summary.
4. Review the dry-run output. The would-write count should match
   what `--verify` reports as `v1` rows (modulo any null rows).
5. Apply for real:
   ```bash
   ./scripts/openshift_migrate.sh apply
   ```
   Same flow — fresh snapshot first, then dry-run preview, then
   prompts for confirmation, then applies, then verifies.
6. Resume traffic if you stopped it:
   ```bash
   oc scale deployment/frc-scheduler-server --replicas=1
   oc rollout status deployment/frc-scheduler-server
   ```
7. Watch the server-side fallback metric for 30 days. If zero, drop
   the fallback in a phase-5 cleanup pass.

Total expected downtime: **zero** if you skip step 2 (the migration
is safe with traffic), or under 5 minutes if you stop the app first.
The migration itself runs in seconds for current data volumes.

### 6.1 What the operator sees

```
$ ./scripts/openshift_migrate.sh apply
Postgres pod:  frc-postgres-58ddc5cd7-6v56s
Scheduler pod: frc-scheduler-server-7b44ff96c6-zcrt9
Mode:          apply

── snapshotting three day_config tables to pre_v2_migration_backup_20260507_211523.sql ──
Backup size: 84321 bytes
Snapshot looks valid.

── copying migration script to frc-scheduler-server-7b44ff96c6-zcrt9:/tmp/migrate_db_to_v2.py ──

── dry-run preview ──
Connecting to: postgresql+asyncpg://***:***@frc-postgres:5432/frc_scheduler
Mode: DRY RUN (no writes)

── version distribution before ──
table                              total   null     v1     v2  other
----------------------------------------------------------------------
abstract_schedules                    47      2     38      7      0
assigned_schedules                    62      0     51     11      0
assigned_schedule_history            148      0    121     27      0

── dry run — nothing will be written ──
abstract_schedules: 38 would write, 9 skipped, 0 errors
assigned_schedules: 51 would write, 11 skipped, 0 errors
assigned_schedule_history: 121 would write, 27 skipped, 0 errors

summary: 210 migrated, 47 skipped, 0 errors

── about to APPLY migration to the live database ──
Backup file: pre_v2_migration_backup_20260507_211523.sql
Type 'apply' (without quotes) to proceed, or anything else to abort:
apply

── applying migration ──
[...same numbers, with "wrote" instead of "would write"...]

── post-migration verification ──
[...table now shows all v2 / null counts; v1 should be 0...]

Migration complete.
Backup retained at: pre_v2_migration_backup_20260507_211523.sql
```

The "verify" command can be run at any time afterwards to spot-check:

```
$ ./scripts/openshift_migrate.sh verify
```

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
