# Generic Containerfile — works with Docker, Podman, and any standard OCI builder.
# For OpenShift builds use: Containerfile.openshift
#
# Follows the linuxserver.io PUID/PGID convention for runtime user mapping:
#   PUID  — user ID the process runs as  (default: 1000)
#   PGID  — group ID the process runs as (default: 1000)
#   APP_PORT — port uvicorn listens on   (default: 8080)
#
# Example (rootless Podman, map to host user):
#   podman run -e PUID=$(id -u) -e PGID=$(id -g) -p 8080:8080 frc-scheduler-server

FROM python:3.12-slim

WORKDIR /app

# System deps + gosu for privilege dropping (linuxserver pattern)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev gosu \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Allow any UID in GID 0 to write (OpenShift arbitrary-UID compatibility)
RUN chgrp -R 0 /app && chmod -R g=u /app

ENV CPU_WORKERS=0
ENV PYTHONUNBUFFERED=1
ENV APP_PORT=8080
ENV PUID=1000
ENV PGID=1000

EXPOSE ${APP_PORT}

ENTRYPOINT ["/entrypoint.sh"]
