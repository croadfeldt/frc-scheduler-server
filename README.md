# FRC Match Scheduler

A two-stage qualification match scheduler for FIRST Robotics Competition events.
Built as a containerised FastAPI + PostgreSQL server with a single-file HTML/CSS/JS
frontend. Deployable via Docker Compose or OpenShift.

---

## ⚠ AI-Assisted Development Notice

This project was substantially written with the assistance of
[Claude](https://claude.ai), an AI assistant developed by Anthropic.

### What this means

- **Architecture, requirements, and design decisions** were directed by human
  contributors who have domain knowledge of FRC competition operations.
- **All AI-generated code was reviewed, tested, and modified** by human contributors
  before inclusion. No code was merged without human verification.
- **The scheduling algorithm logic** — priorities, weights, surrogate rules, and
  post-generation sweeps — was designed and validated by humans, then implemented
  with AI assistance.
- **Bugs and limitations** may still exist. AI assistance does not guarantee
  correctness. Please report issues via GitHub.

### For contributors

If you contribute to this project using AI assistance, follow these practices:

1. **Review everything the AI generates.** Do not commit AI output verbatim without
   reading and understanding it. You are responsible for code you submit.
2. **Test AI-generated logic independently.** Particularly for algorithmic code,
   write your own test cases rather than accepting the AI's self-validation.
3. **Disclose AI use in your PR description.** Note which parts were AI-assisted
   and what review you performed. Example: *"Generated initial implementation with
   Claude, verified surrogate logic by hand with 3 test cases."*
4. **Do not use AI to generate security-sensitive code without expert review.**
   Authentication flows, JWT handling, and OAuth integration require careful
   human scrutiny.
5. **Maintain the SPDX header.** All source files carry `SPDX-License-Identifier:
   GPL-3.0-or-later`. Do not remove it.

This project follows the emerging open-source community norm of transparent
disclosure for AI-assisted contributions. See also:
[OSAID](https://opensource.org/ai/open-source-ai-definition),
[GitHub's guidance on AI-generated code](https://docs.github.com/en/copilot/responsible-use-of-github-copilot-features).

---

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE).

Copyright (C) 2025 FRC Match Scheduler Contributors.

---

## Quick Start (Docker Compose)

```bash
# 1. Clone
git clone https://github.com/croadfeldt/frc-scheduler-server.git
cd frc-scheduler-server

# 2. Configure
cp env.example .env
# Edit .env — at minimum set TBA_API_KEY (optional) and auth secrets

# 3. Build and start
docker compose up --build

# App is at http://localhost:8080
```

---

## Quick Start (OpenShift)

```bash
# 1. Create project
oc new-project frc-scheduler-server

# 2. Edit secrets (set passwords, TBA key, auth credentials)
vi openshift/01-secrets.yaml

# 3. Apply in order
oc apply -f openshift/01-secrets.yaml
oc apply -f openshift/02-postgres.yaml
oc rollout status deployment/frc-postgres -n frc-scheduler-server
oc apply -f openshift/03-buildconfig.yaml
oc start-build frc-scheduler-server-git --follow -n frc-scheduler-server
oc apply -f openshift/04-deployment.yaml
oc apply -f openshift/05-route.yaml
oc apply -f openshift/07-build-trigger-sa.yaml
oc apply -f openshift/08-build-cronjob.yaml

# Get the public URL
oc get route frc-scheduler-server -n frc-scheduler-server -o jsonpath='{.spec.host}'
```

See `openshift/README.md` for full details.

---

## Container Builds

Two Containerfiles are provided — use the one appropriate for your build environment:

| File | Build target | Base image | Package manager |
|------|-------------|-----------|----------------|
| `Containerfile` | Docker, Podman, any OCI builder | `python:3.12-slim` (Docker Hub) | apt-get |
| `Containerfile.openshift` | **OpenShift BuildConfig only** | `quay.io/sclorg/python-312-c10s` | dnf |

**`Containerfile.openshift` is not intended for local Docker/Podman use.** It exists solely to avoid Docker Hub rate limits in OpenShift build pods and is referenced by `openshift/03-buildconfig.yaml` via `dockerfilePath: Containerfile.openshift`.

### Rootless container support

Both Containerfiles are rootless-compliant. The following environment variables control runtime identity and port binding:

| Variable | Default | Description |
|----------|---------|-------------|
| `PUID` | `1000` | User ID the process runs as. Set to `$(id -u)` to match your host user (linuxserver.io convention). |
| `PGID` | `1000` | Group ID the process runs as. Set to `$(id -g)` to match your host group. |
| `APP_PORT` | `8080` | Port uvicorn listens on. Ports ≥1024 require no special capabilities. |

All app files are `chgrp -R 0 && chmod -R g=u` so any UID in GID 0 can write without privilege escalation.

Standard Docker/Podman builds always use `Containerfile`:
```bash
docker compose up --build                        # uses Containerfile, port 8080

# Rootless Podman with host user mapping:
podman run --rm -e PUID=$(id -u) -e PGID=$(id -g) \
  -p 8080:8080 frc-scheduler-server
```

OpenShift builds are triggered via:
```bash
bash openshift/rebuild.sh        # full teardown + rebuild
# or after a git push, the CronJob auto-triggers within 5 minutes
```

---

## Architecture

### Two-stage scheduling

```
Stage 1 — Abstract Schedule
  Input:  numTeams, matchesPerTeam, cooldown, seed (hex)
  Output: slot-indexed match structure (no real team numbers)
          reproducible: same seed → identical structure

Stage 2 — Team Assignment
  Input:  abstract schedule + event roster + assign_seed (hex)
  Output: slot_map {slot: team_number}
          reproducible: same assign_seed → identical mapping
```

### System components

```
Browser (static/index.html)
    │  REST + SSE  +  Authorization: Bearer <jwt>
    ▼
FastAPI (app/main.py)              port 8080
    │
    ├─ /auth/*          OAuth2 (Google, Apple) → JWT
    ├─ /api/events/*    Event + team management + TBA import
    ├─ /api/generate-abstract   Stage 1 SSE stream
    ├─ /api/abstract-schedules/{id}/assign  Stage 2 SSE stream
    └─ /api/assigned-schedules/*  History, activate, duplicate
    │
    │  ProcessPoolExecutor (CPU_WORKERS processes)
    ├─► Worker 0  ──┐
    ├─► Worker 1  ──┤  app/scheduler.py  (pure Python, no I/O, seeded RNG)
    └─► Worker N  ──┘
    │
    │  asyncpg
    ▼
PostgreSQL                         port 5432 (internal)
```

### Why ProcessPoolExecutor?
Python's GIL prevents CPU parallelism with threads. `ProcessPoolExecutor` spawns
real OS processes. On a 16-core pod, 500 assignment iterations finish in ~1/16th
the single-core time.

### Seeded RNG
Both stages use deterministic seeded PRNGs:
- JS: mulberry32 (`makeRng(parseInt(seed, 16))`)
- Python: `random.Random(int(seed, 16))`

Same seed always produces identical output. Seeds are auto-generated, stored in
the database, and encoded in the share URL so any schedule can be exactly reproduced.

### URL reproducibility
After generating a schedule, the browser URL is updated:
```
?n=51&mpt=11&cd=3&ct=8&days=2&seed=a1b2c3d4&aseed=cafebabe
  &d1=08:00-17:00&d1b=Lunch|12:00|13:00
  &d2=08:00-15:00
  &teams=254,1114,...
```

| Parameter | Example | Description |
|-----------|---------|-------------|
| `n` | `51` | Number of teams |
| `mpt` | `11` | Matches per team |
| `cd` | `3` | Cooldown |
| `ct` | `8` | Cycle time (minutes, any decimal e.g. `7.3`, `6.75`) |
| `days` | `2` | Number of competition days |
| `seed` | `a1b2c3d4` | Stage 1 hex seed |
| `aseed` | `cafebabe` | Stage 2 hex seed |
| `teams` | `254,1114,...` | Team numbers in slot order |
| `d1`–`d5` | `08:00-17:00` | Per-day start–end (`HH:MM-HH:MM`) |
| `d1b`–`d5b` | `Lunch\|12:00\|13:00,...` | Per-day breaks: `Name\|start\|end`, comma-separated |

Opening this URL auto-reproduces the full schedule including day/time configuration.
Without `teams`, the abstract structure renders with slot labels (S1, S2...).

---

## API Reference

### Events
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | /api/events | — | List events |
| POST | /api/events | — | Create event |
| GET | /api/events/{id} | — | Event + team roster |
| DELETE | /api/events/{id} | — | Delete event |
| GET | /api/events/{id}/teams | — | List teams |
| POST | /api/events/{id}/teams | — | Add team |
| DELETE | /api/events/{id}/teams/{num} | — | Remove team |

### TBA Integration
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | /api/tba/events/{year}?search= | — | Search TBA events |
| POST | /api/tba/import/{event_key} | — | Import event + teams from TBA |

### Stage 1 — Abstract Schedule
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /api/generate-abstract | optional | Generate slot structure (SSE stream) |
| GET | /api/abstract-schedules | — | List abstract schedules |
| GET | /api/abstract-schedules/{id} | — | Full slot-based schedule + seed |
| DELETE | /api/abstract-schedules/{id} | — | Delete |

### Stage 2 — Team Assignment
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /api/abstract-schedules/{id}/assign | optional | Assign teams (SSE stream) |
| GET | /api/events/{id}/assigned-schedules | — | Version history |
| GET | /api/assigned-schedules/{id} | — | Resolved schedule + seeds |
| POST | /api/assigned-schedules/{id}/activate | — | Promote to active |
| DELETE | /api/assigned-schedules/{id} | owned | Delete (requires ownership) |
| POST | /api/assigned-schedules/{id}/duplicate | optional | Copy as new owned schedule |

### Authentication
| Method | Path | Description |
|--------|------|-------------|
| GET | /auth/google/login | Redirect to Google consent |
| GET | /auth/google/callback | Exchange code → issue JWT |
| GET | /auth/apple/login | Redirect to Apple consent |
| POST | /auth/apple/callback | Exchange code (form_post) → issue JWT |
| GET | /auth/me | Current user info from JWT |
| GET | /auth/providers | Which providers are configured |

### Health
| Method | Path | Description |
|--------|------|-------------|
| GET | /api/health | Status + CPU worker count |

**Auth notes:**
- All reads are public — no token required.
- `Authorization: Bearer <jwt>` enables ownership. Schedules gain a `created_by`
  field (OAuth subject). Deletion requires matching `created_by`.
- Anonymous schedules (`created_by = NULL`) are publicly readable but not deletable.
- Anyone can duplicate a schedule; the copy is owned by the caller.

Interactive docs: http://localhost:8080/docs (Swagger UI)

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://frc:frc@localhost:5432/frc_scheduler` | Postgres DSN |
| `TBA_API_KEY` | (empty) | The Blue Alliance read key — [get one free](https://www.thebluealliance.com/account) |
| `CPU_WORKERS` | `0` (auto) | Scheduler worker processes; 0 = `os.cpu_count()` |
| `WEB_WORKERS` | `1` | Uvicorn process count. 1 = single user, 2–4 = multi-user. Each worker has its own ProcessPoolExecutor. |
| `JWT_SECRET` | (required for auth) | Long random string — `openssl rand -hex 32` |
| `BASE_URL` | `http://localhost:8080` | Public URL — used for OAuth redirect URIs |
| `GOOGLE_CLIENT_ID` | (empty) | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | (empty) | Google OAuth client secret |
| `APPLE_CLIENT_ID` | (empty) | Apple Service ID (web) |
| `APPLE_TEAM_ID` | (empty) | Apple developer team ID |
| `APPLE_KEY_ID` | (empty) | Apple private key ID |
| `APPLE_PRIVATE_KEY` | (empty) | Apple ES256 PEM key (newlines as `\n`) |

Auth is **optional** — the scheduler works fully without OAuth configured.
Users can generate, view, and share schedules anonymously.

---

## Setting Up OAuth

### Google
1. Go to [Google Cloud Console → APIs → Credentials](https://console.cloud.google.com/apis/credentials)
2. Create OAuth 2.0 Client ID → Web application
3. Add authorized redirect URI: `${BASE_URL}/auth/google/callback`
4. Copy Client ID and Secret to `.env` or OpenShift secret

### Apple
1. Go to [Apple Developer → Identifiers](https://developer.apple.com/account/resources/identifiers)
2. Register a Services ID (for web)
3. Enable Sign In with Apple, add redirect URI: `${BASE_URL}/auth/apple/callback`
4. Create a private key under Keys, download the `.p8` file
5. Set `APPLE_CLIENT_ID`, `APPLE_TEAM_ID`, `APPLE_KEY_ID`, and `APPLE_PRIVATE_KEY`
   (replace newlines in the PEM with literal `\n`)

---

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run with local Postgres
DATABASE_URL=postgresql+asyncpg://frc:frc@localhost:5432/frc_scheduler \
  uvicorn app.main:app --reload

# Test scheduler reproducibility
python3 -c "
from app.scheduler import generate_matches
r1 = generate_matches(30, 6, 3, seed=0xdeadbeef)
r2 = generate_matches(30, 6, 3, seed=0xdeadbeef)
print('Reproducible:', r1.matches == r2.matches)
print('Score:', r1.score)
"

# Verify surrogate rules
python3 -c "
from app.scheduler import generate_matches
r = generate_matches(51, 11, 3, seed=42)
last = r.matches[-1]
assert not any(last.red_surrogate), 'R1 violated: surrogate in last match'
assert not any(last.blue_surrogate), 'R1 violated: surrogate in last match'
print('Post-gen sweep rules OK')
"
```

---

## Scaling

| Concern | Approach |
|---------|----------|
| More iterations | Increase Assignment Iterations in UI (default 1000) |
| More cores | Set `CPU_WORKERS` to physical core count |
| Memory | Each worker ≈ 50 MB; 16 workers ≈ 800 MB |
| Multiple replicas | Each replica has its own worker pool; note — more small pods beats one big pod for scheduling throughput only if each pod has enough cores |
| Concurrent users | Set `WEB_WORKERS=2–4`. A generation semaphore (CPU_WORKERS÷2, min 2) prevents pool saturation. The client AbortController cancels in-flight requests on param changes. |
| DB migrations | `create_all` is used (dev-friendly). Add Alembic for production schema migrations. |
