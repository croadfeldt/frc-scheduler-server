#!/bin/sh
# Entrypoint following the linuxserver.io PUID/PGID convention.
#
# If the container starts as root (standard Docker/Podman), it creates/reuses
# a user matching PUID:PGID and drops privileges before exec-ing uvicorn.
#
# If the container starts as non-root (OpenShift arbitrary UID, strict rootless
# Podman with --user), user creation is skipped and uvicorn runs directly.
#
# Environment variables:
#   PUID     — UID to run as          (default: 1000)
#   PGID     — GID to run as          (default: 1000)
#   APP_PORT — port uvicorn listens on (default: 8080)

set -e

PUID=${PUID:-1000}
PGID=${PGID:-1000}
APP_PORT=${APP_PORT:-8080}
# WEB_WORKERS: number of uvicorn worker processes.
# Default 1 is safe for a single-user install. Set to 2-4 for multi-user.
# Note: each worker has its own ProcessPoolExecutor, so CPU use scales with this.
WEB_WORKERS=${WEB_WORKERS:-1}

echo "
-------------------------------------
    FRC Match Scheduler
-------------------------------------
    PUID:     ${PUID}
    PGID:     ${PGID}
    APP_PORT: ${APP_PORT}
-------------------------------------
"

if [ "$(id -u)" = "0" ]; then
    # Running as root — create user/group matching PUID/PGID then drop privileges

    # Create group if needed (skip GID 0, always exists)
    if [ "${PGID}" != "0" ]; then
        if ! getent group "${PGID}" > /dev/null 2>&1; then
            groupadd -g "${PGID}" appgroup 2>/dev/null || true
        fi
    fi

    # Create user if needed
    if ! getent passwd "${PUID}" > /dev/null 2>&1; then
        useradd -u "${PUID}" -g "${PGID}" -d /app -s /sbin/nologin -M appuser 2>/dev/null || true
    fi

    # Ensure app directory is owned by the target user
    chown -R "${PUID}:${PGID}" /app 2>/dev/null || true

    # Drop privileges and exec — prefer gosu (Debian), fall back to su-exec or runuser
    if command -v gosu > /dev/null 2>&1; then
        exec gosu "${PUID}:${PGID}" \
            uvicorn app.main:app --host 0.0.0.0 --port "${APP_PORT}" --workers "${WEB_WORKERS}"
    elif command -v su-exec > /dev/null 2>&1; then
        exec su-exec "${PUID}:${PGID}" \
            uvicorn app.main:app --host 0.0.0.0 --port "${APP_PORT}" --workers "${WEB_WORKERS}"
    else
        exec runuser -u appuser -- \
            uvicorn app.main:app --host 0.0.0.0 --port "${APP_PORT}" --workers "${WEB_WORKERS}"
    fi
else
    # Non-root already (OpenShift arbitrary UID, rootless with --user flag)
    # PUID/PGID are informational only — just run directly
    exec uvicorn app.main:app --host 0.0.0.0 --port "${APP_PORT}" --workers "${WEB_WORKERS}"
fi
