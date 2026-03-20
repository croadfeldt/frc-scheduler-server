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
#   PUID        — UID to run as                    (default: 1000)
#   PGID        — GID to run as                    (default: 1000)
#   APP_PORT    — port uvicorn listens on           (default: 8080)
#   SSL_CERTFILE — path to TLS certificate file    (optional)
#   SSL_KEYFILE  — path to TLS private key file    (optional)
#
# When SSL_CERTFILE and SSL_KEYFILE are both set and the files exist,
# uvicorn is started with TLS enabled on APP_PORT.

set -e

PUID=${PUID:-1000}
PGID=${PGID:-1000}
APP_PORT=${APP_PORT:-8080}
WEB_WORKERS=${WEB_WORKERS:-1}

# Build SSL args if cert files are present
SSL_ARGS=""
if [ -n "${SSL_CERTFILE}" ] && [ -n "${SSL_KEYFILE}" ] \
   && [ -f "${SSL_CERTFILE}" ] && [ -f "${SSL_KEYFILE}" ]; then
    SSL_ARGS="--ssl-certfile ${SSL_CERTFILE} --ssl-keyfile ${SSL_KEYFILE}"
    echo "TLS enabled: ${SSL_CERTFILE}"
else
    echo "TLS disabled (SSL_CERTFILE/SSL_KEYFILE not set or files not found)"
fi

echo "
-------------------------------------
    FRC Match Scheduler
-------------------------------------
    PUID:     ${PUID}
    PGID:     ${PGID}
    APP_PORT: ${APP_PORT}
    TLS:      ${SSL_ARGS:-disabled}
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
            uvicorn app.main:app --host 0.0.0.0 --port "${APP_PORT}" --workers "${WEB_WORKERS}" ${SSL_ARGS}
    elif command -v su-exec > /dev/null 2>&1; then
        exec su-exec "${PUID}:${PGID}" \
            uvicorn app.main:app --host 0.0.0.0 --port "${APP_PORT}" --workers "${WEB_WORKERS}" ${SSL_ARGS}
    else
        exec runuser -u appuser -- \
            uvicorn app.main:app --host 0.0.0.0 --port "${APP_PORT}" --workers "${WEB_WORKERS}" ${SSL_ARGS}
    fi
else
    # Non-root already (OpenShift arbitrary UID, rootless with --user flag)
    exec uvicorn app.main:app --host 0.0.0.0 --port "${APP_PORT}" --workers "${WEB_WORKERS}" ${SSL_ARGS}
fi
