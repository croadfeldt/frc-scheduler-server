#!/bin/sh
# Entrypoint following the linuxserver.io PUID/PGID convention.

set -e

PUID=${PUID:-1000}
PGID=${PGID:-1000}
APP_PORT=${APP_PORT:-8080}
WEB_WORKERS=${WEB_WORKERS:-1}

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
    if [ "${PGID}" != "0" ]; then
        if ! getent group "${PGID}" > /dev/null 2>&1; then
            groupadd -g "${PGID}" appgroup 2>/dev/null || true
        fi
    fi
    if ! getent passwd "${PUID}" > /dev/null 2>&1; then
        useradd -u "${PUID}" -g "${PGID}" -d /app -s /bin/sh appuser 2>/dev/null || true
    fi
    exec gosu "${PUID}:${PGID}" uvicorn app.main:app \
        --host 0.0.0.0 \
        --port "${APP_PORT}" \
        --workers "${WEB_WORKERS}" \
        ${SSL_ARGS}
else
    exec uvicorn app.main:app \
        --host 0.0.0.0 \
        --port "${APP_PORT}" \
        --workers "${WEB_WORKERS}" \
        ${SSL_ARGS}
fi
