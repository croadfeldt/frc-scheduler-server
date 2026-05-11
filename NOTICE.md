# FRC Match Scheduler — Third-Party Software Notices

This NOTICE accompanies the GPL v3 LICENSE and documents this project's
posture toward third-party software, services, and intellectual property.
GPL applies to all code originated by this project; the items below
describe how we relate to external resources.

## License of this project

GPL v3 (see `LICENSE`). Substantial portions of the codebase were
generated with AI assistance under human direction; the LICENSE file
includes the full disclosure.

## Third-party software dependencies

### Python runtime dependencies (`requirements.txt`)

All current dependencies are under GPL-compatible licenses:

| Package | License |
|---|---|
| asyncpg | Apache 2.0 |
| fastapi | MIT |
| httpx | BSD-3-Clause |
| openpyxl | MIT |
| pdfplumber | MIT |
| Pillow | HPND |
| pydantic | MIT |
| pytesseract (wraps Tesseract OCR) | Apache 2.0 |
| python-jose[cryptography] | MIT + Apache 2.0/BSD |
| python-multipart | Apache 2.0 |
| sqlalchemy | MIT |
| uvicorn[standard] | BSD-3-Clause |
| slowapi | MIT |
| weasyprint | BSD-3-Clause |

Adding a dependency under a non-permissive or GPL-incompatible license
(e.g. AGPL, CDDL, proprietary) requires explicit review.

## Third-party services

### The Blue Alliance (TBA)

The Blue Alliance provides a public read-only API for FRC event data
(team rosters, match schedules, results). This project queries TBA for
research and validation purposes — most notably the scheduler eval
harness in `scripts/scheduler_eval/`.

- API documentation: https://www.thebluealliance.com/apidocs
- Terms: https://www.thebluealliance.com/page/api
- Attribution required: TBA expects clients to identify themselves via
  `User-Agent` and to acknowledge data attribution.

The client in `app/tba.py` sets the appropriate headers. Any new code
that queries TBA must reuse that client rather than rolling its own.

Data ownership: match schedules and results are owned collectively by
the participating teams, FIRST, and TBA's curation. Our use is
read-only and does not constitute redistribution of TBA's database.

### FIRST Robotics Competition (FRC) Events API

The official FIRST API provides authoritative event data. The client
in `app/frc_events.py` uses it.

- API documentation: https://frc-events.firstinspires.org/services/API
- Use is governed by FIRST's API terms (login required to view)
- Attribution: schedules/results derived from this API should
  acknowledge "Data from FIRST Robotics Competition"

## Algorithm attribution

The scheduler in `app/scheduler.py` implements FRC qualification
scheduling using approaches that align with publicly-documented work
on this problem. Per the published criteria:

- The scheduling criteria themselves (round uniformity, match
  separation, pairing uniformity, red/blue balancing, station-position
  balancing, surrogate handling) are described in the FRC Game Manual
  (§13.6.2 in 2025) and are public specifications. Implementing these
  is not constrained by any external license.

- Where our implementation parallels approaches described in published
  work — notably the simulated annealing approach for pairing
  uniformity described by Tom and Cathy Saxton in the MatchMaker white
  paper (https://idleloop.com/matchmaker/), and the station-balancing
  algorithm developed by Caleb Sykes (https://idleloop.com/matchmaker/stations.php)
  — the lineage is acknowledged here. Our implementation is independent
  (we do not reproduce or call MatchMaker code or binaries) and is
  derived from the published descriptions only.

## Idle Loop's MatchMaker — evaluation only

The scheduler eval harness (`scripts/scheduler_eval/`) includes an
adapter that can wrap an externally-installed copy of Idle Loop
Software Design's MatchMaker binary for benchmarking purposes.

- MatchMaker is distributed under an "evaluation purposes only"
  license. See `scripts/scheduler_eval/NOTICE.md` for the full posture.
- The harness does not bundle, redistribute, or auto-download the
  MatchMaker binary. Users supply their own copy under their own
  evaluation license with Idle Loop.
- The matchmaker adapter is for personal local evaluation only — it
  is not invoked by the running app, is not part of any production
  code path, and is not run in CI.
- The shipped scheduler in `app/scheduler.py` is independent of
  MatchMaker; the harness is a research tool, not a runtime
  dependency.
- For ongoing scheduler validation, the harness uses TBA-fetched
  played schedules (the `actual` adapter) as the primary comparison
  surface.

See `scripts/scheduler_eval/NOTICE.md` for harness-specific operational
guidance and the implementation brief at
`docs/scheduler/REFERENCE_SCHEDULER_LICENSING.md` for the architectural
constraints this posture creates.

## Reporting concerns

Licensing or attribution concerns may be raised via GitHub issues at
https://github.com/croadfeldt/frc-scheduler-server. The project owner
will route to the relevant author for resolution.

---

*This notice is informational and does not constitute legal advice.*
