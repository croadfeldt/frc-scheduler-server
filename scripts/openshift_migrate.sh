#!/bin/bash
# Phase 2 DB migration runner for OpenShift.
#
# Walks the operator through:
#   1. Resolve current postgres + scheduler pod names by label.
#   2. Snapshot the three day_config-bearing tables to a local file.
#   3. Verify the snapshot looks valid (non-empty, contains expected tables).
#   4. Run migrate_db_to_v2.py inside the scheduler pod (where Python deps
#      are installed) — first in dry-run mode to preview, then with --apply.
#   5. Verify the post-migration version distribution.
#
# Usage:
#   ./scripts/openshift_migrate.sh dryrun   # Steps 1-4 dry-run only
#   ./scripts/openshift_migrate.sh apply    # Full snapshot + apply + verify
#   ./scripts/openshift_migrate.sh verify   # Just print version distribution
#
# Idempotent — safe to run multiple times. The script halts on any error
# rather than continuing to a destructive step.

set -euo pipefail

MODE="${1:-dryrun}"
TS="$(date -u +%Y%m%d_%H%M%S)"
BACKUP_FILE="pre_v2_migration_backup_${TS}.sql"
SCRIPT_PATH="/tmp/migrate_db_to_v2.py"

# ── Resolve pods ─────────────────────────────────────────────────────────────
# Pod names rotate on redeploy. Resolve by label every time. The label
# values match what openshift/04-deployment.yaml sets (NAMESPACE-git
# for the app pod; app=frc-postgres for the DB pod).
PG_POD="$(oc get pod -l app=frc-postgres -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
APP_POD="$(oc get pod -l app=frc-scheduler-server-git -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"

if [ -z "${PG_POD}" ]; then
    echo "ERROR: could not resolve postgres pod (oc get pod -l app=frc-postgres returned nothing)" >&2
    echo "Are you connected to the right cluster? Run 'oc whoami' to check." >&2
    exit 2
fi
if [ -z "${APP_POD}" ]; then
    echo "ERROR: could not resolve scheduler pod (oc get pod -l app=frc-scheduler-server-git returned nothing)" >&2
    echo "Check the deployment label with: oc get pod --show-labels | grep scheduler" >&2
    exit 2
fi

echo "Postgres pod:  ${PG_POD}"
echo "Scheduler pod: ${APP_POD}"
echo "Mode:          ${MODE}"
echo

case "${MODE}" in
    verify)
        # Verify-only: copy script in, run with --verify, exit.
        oc cp scripts/migrate_db_to_v2.py "${APP_POD}:${SCRIPT_PATH}" >/dev/null
        oc exec "${APP_POD}" -- python "${SCRIPT_PATH}" --verify
        exit 0
        ;;

    dryrun)
        # Dry-run: snapshot first (cheap insurance — we want a backup
        # even when "just" testing), then run the migration script
        # without --apply. Backup file stays around regardless.
        ;;

    apply)
        # Apply: snapshot, dry-run preview, prompt for confirmation, apply.
        ;;

    *)
        echo "Usage: $0 {dryrun|apply|verify}" >&2
        exit 2
        ;;
esac

# ── Step 1: snapshot ────────────────────────────────────────────────────────
echo "── snapshotting three day_config tables to ${BACKUP_FILE} ──"
oc exec "${PG_POD}" -- bash -c \
    'pg_dump -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        --table=abstract_schedules \
        --table=assigned_schedules \
        --table=assigned_schedule_history \
        --data-only --column-inserts' \
    > "${BACKUP_FILE}"

# Sanity-check the snapshot. If any of these fails, abort before doing
# anything destructive.
if [ ! -s "${BACKUP_FILE}" ]; then
    echo "ERROR: backup file ${BACKUP_FILE} is empty — pg_dump may have failed silently" >&2
    exit 1
fi
SIZE=$(wc -c < "${BACKUP_FILE}")
echo "Backup size: ${SIZE} bytes"

# Look for expected SQL markers. If the dump doesn't contain INSERT
# statements for the three tables, it's not a usable rollback artifact.
if ! grep -q "abstract_schedules"        "${BACKUP_FILE}"; then
    echo "ERROR: backup doesn't reference abstract_schedules" >&2
    exit 1
fi
if ! grep -q "assigned_schedules"        "${BACKUP_FILE}"; then
    echo "ERROR: backup doesn't reference assigned_schedules" >&2
    exit 1
fi
if ! grep -q "assigned_schedule_history" "${BACKUP_FILE}"; then
    echo "ERROR: backup doesn't reference assigned_schedule_history" >&2
    exit 1
fi
echo "Snapshot looks valid."
echo

# ── Step 2: copy migration script to app pod ────────────────────────────────
echo "── copying migration script to ${APP_POD}:${SCRIPT_PATH} ──"
oc cp scripts/migrate_db_to_v2.py "${APP_POD}:${SCRIPT_PATH}" >/dev/null
echo

# ── Step 3: dry-run preview ─────────────────────────────────────────────────
echo "── dry-run preview ──"
oc exec "${APP_POD}" -- python "${SCRIPT_PATH}"
echo

if [ "${MODE}" = "dryrun" ]; then
    echo "Dry-run complete. Backup at ${BACKUP_FILE} preserved."
    echo "To apply:  $0 apply"
    exit 0
fi

# ── Step 4: confirm + apply (apply mode only) ───────────────────────────────
echo "── about to APPLY migration to the live database ──"
echo "Backup file: ${BACKUP_FILE}"
echo "Type 'apply' (without quotes) to proceed, or anything else to abort:"
read -r CONFIRM
if [ "${CONFIRM}" != "apply" ]; then
    echo "Aborted. Backup at ${BACKUP_FILE} preserved."
    exit 0
fi

echo
echo "── applying migration ──"
oc exec "${APP_POD}" -- python "${SCRIPT_PATH}" --apply

# ── Step 5: post-migration verify ───────────────────────────────────────────
echo
echo "── post-migration verification ──"
oc exec "${APP_POD}" -- python "${SCRIPT_PATH}" --verify

# ── Cleanup script from pod (backup stays local) ────────────────────────────
oc exec "${APP_POD}" -- rm -f "${SCRIPT_PATH}" || true

echo
echo "Migration complete."
echo "Backup retained at: ${BACKUP_FILE}"
echo
echo "If something looks wrong, rollback procedure is in docs/DB_V2_MIGRATION.md §5."
