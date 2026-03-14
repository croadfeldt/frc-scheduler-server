FROM python:3.12-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# OpenShift runs containers as a random UID in the root group (GID 0).
# Ensure the app directory is group-writable so that arbitrary UIDs can write
# log / temp files without requiring a specific numeric UID.
RUN chgrp -R 0 /app && chmod -R g=u /app

# Use all available cores; override with CPU_WORKERS env var
ENV CPU_WORKERS=0
ENV PYTHONUNBUFFERED=1

# Unprivileged port — OpenShift's default SCC blocks ports < 1024
EXPOSE 8000

# Run as non-root (OpenShift will override with a random UID anyway)
USER 1001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
