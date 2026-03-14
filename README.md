# FRC Match Scheduler — Server Edition

Containerised FastAPI + PostgreSQL backend with multi-process scheduling
and optional The Blue Alliance API integration.

## Quick start

```bash
# 1. Clone / copy this directory
cd frc-scheduler

# 2. Set your TBA API key (optional — manual team entry works without it)
cp .env.example .env
# Edit .env and add your TBA_API_KEY

# 3. Build and start
docker compose up --build

# App is now at http://localhost:8000
```

## Architecture

```
Browser (index.html)
    │  REST + SSE
    ▼
FastAPI (app/main.py)          port 8000
    │  ProcessPoolExecutor
    ├─► Worker 0  ──┐
    ├─► Worker 1  ──┤  app/scheduler.py (pure Python, no I/O)
    ├─► Worker N  ──┘
    │
    │  asyncpg
    ▼
PostgreSQL                     port 5432 (internal)
```

### Why ProcessPoolExecutor?
Python's GIL prevents true CPU parallelism with threads. `ProcessPoolExecutor`
spawns real OS processes, each running the scheduler on a separate core.
On a 16-core server, 1000 iterations finish in ~1/16th the single-core time.

### SSE progress streaming
`POST /api/events/{id}/generate` returns a `text/event-stream` response.
The browser reads events in real time using the `EventSource` API:
```javascript
const es = new EventSource('/api/events/1/generate');  // POST handled separately
es.onmessage = e => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'progress') updateProgressBar(msg.pct);
    if (msg.type === 'done')     loadSchedule(msg.schedule_id);
};
```

## API reference

### Events
| Method | Path | Description |
|--------|------|-------------|
| GET    | /api/events | List all events |
| POST   | /api/events | Create event manually |
| GET    | /api/events/{id} | Event detail + team roster |
| DELETE | /api/events/{id} | Delete event and all schedules |

### TBA Integration
| Method | Path | Description |
|--------|------|-------------|
| GET    | /api/tba/events/{year} | Search TBA events |
| POST   | /api/tba/import/{event_key} | Import event + teams from TBA |

### Teams
| Method | Path | Description |
|--------|------|-------------|
| GET    | /api/events/{id}/teams | List teams in event |
| POST   | /api/events/{id}/teams | Add team manually |
| DELETE | /api/events/{id}/teams/{number} | Remove team |

### Schedules
| Method | Path | Description |
|--------|------|-------------|
| POST   | /api/events/{id}/generate | Generate schedule (SSE stream) |
| GET    | /api/events/{id}/schedules | List schedules for event |
| GET    | /api/schedules/{id} | Full schedule data |
| POST   | /api/schedules/{id}/activate | Set as active schedule |
| DELETE | /api/schedules/{id} | Delete schedule |
| GET    | /api/schedules/{id}/team/{slot} | All matches for a team slot |

### Health
| Method | Path | Description |
|--------|------|-------------|
| GET    | /api/health | Health check + worker count |

## Interactive API docs
FastAPI auto-generates docs at:
- Swagger UI: http://localhost:8000/docs
- ReDoc:       http://localhost:8000/redoc

## Environment variables
| Variable | Default | Description |
|----------|---------|-------------|
| DATABASE_URL | postgresql+asyncpg://frc:frc@db:5432/frc_scheduler | Postgres DSN |
| TBA_API_KEY | (empty) | The Blue Alliance read API key |
| CPU_WORKERS | 0 (auto) | Number of scheduler worker processes |

## TBA API key
Free key at https://www.thebluealliance.com/account
The scheduler works fully without it — teams can be added manually.

## Scaling
- **More cores**: set `CPU_WORKERS` to the number of physical cores
- **More memory**: each worker uses ~50MB; 16 workers = ~800MB
- **Multiple instances**: run behind nginx with a shared Postgres instance
- **Cloud**: drop `docker-compose.yml` for a Kubernetes deployment or
  use Railway / Render / Fly.io which support Docker directly

## Development
```bash
# Run without Docker (requires local Postgres)
pip install -r requirements.txt
DATABASE_URL=postgresql+asyncpg://... uvicorn app.main:app --reload

# Run scheduler tests
python3 -c "from app.scheduler import generate_matches; print(generate_matches(25,6,3).score)"
```
