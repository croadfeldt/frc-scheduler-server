# Architecture

Design principles and key decisions for the FRC Match Scheduler.
Not a code reference — for that read the source. This doc captures
the *why* behind major structural choices so future changes don't
fight the architecture without realizing it.

## Guiding principles

1. **Server owns the data. Client owns the interactivity.** The
   server is the source of truth for schedules, events, teams, and
   live data feeds. The client renders that data interactively
   (filtering, sorting, selection) and produces print/PDF output.

2. **Multiple consumers, one source.** Every output format (live
   page, print, PDF, XLSX, CSV, JSON, FMS) is fed from the same
   underlying data. Differences are in formatting, not content.

3. **Filtering is presentation, not data.** When a user filters
   "only my teams," that's a view-state choice. The schedule
   underneath is unchanged. Filtering is applied at render time
   on whatever side does the rendering.

4. **Live data overlays the schedule, doesn't replace it.** TBA
   scores, Nexus queue status, Statbotics rankings — these annotate
   the schedule for the live page. They aren't part of the
   schedule itself, and they don't appear in print/PDF output
   because they're transient.

5. **Architecture follows the platform, not the other way around.**
   Where state actually lives drives where logic lives. Don't
   fight the browser to do server-side work, and don't fight the
   server to do browser-side work.

## High-level shape

```
┌─────────────────────────────────────────────────────────────────┐
│                          FastAPI                                │
│                                                                 │
│  Schedule data    │  Live data         │  Render               │
│  (Postgres)       │  (TBA, Nexus,      │  (WeasyPrint)         │
│                   │   Statbotics)      │                       │
│                   │                    │                       │
│  /api/events      │  /api/.../live     │  /api/.../render-pdf  │
│  /api/.../assign  │                    │   ?format=pdf|html    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTP / JSON / PDF / HTML
                              │
┌─────────────────────────────────────────────────────────────────┐
│                        Browser                                  │
│                                                                 │
│  Editor (index.html)  │  View (view.html)                       │
│   - Generation worker │   - Live polling (TBA + Nexus)          │
│   - Schedule editor   │   - Team selection / filter             │
│   - Save / load       │   - Print / Export                      │
│                       │                                         │
│  Both reuse:                                                    │
│   - Schedule rendering (table builders, day-grouping)           │
│   - Export modal (format picker, options)                       │
│   - Restore-from-file pipeline (JSON / XLSX / CSV)              │
└─────────────────────────────────────────────────────────────────┘
```

## Key components

### Backend (`app/`)

- **`main.py`** — FastAPI app, all HTTP endpoints. Schedule CRUD,
  event management, live data fetch/cache, file imports, PDF render.
- **`scheduler.py`** — abstract schedule generation (slot-based
  search). Stage 1 of two-stage scheduling.
- **`assignment.py`** — abstract → concrete schedule by mapping
  team numbers to slots. Stage 2.
- **`pdf_render.py`** — HTML+CSS template + WeasyPrint pipeline.
  Used for both PDF download and HTML responses (the latter feeds
  the browser-print popup; see *Print and PDF* below).
- **`pdf_extract.py` / `pdf_dayplan.py`** — LLM-driven PDF import
  for arbitrary schedule PDFs. Two strategies: tabular extraction
  for FMS-style sheets, day-plan for itinerary-style PDFs.
- **`xlsx_extract.py` / `csv_extract.py`** — file-based imports.
  Reliable round-trip from this app's own exports.
- **`schedule_derive.py`** — recovers parameters (numTeams, MPT,
  cycle time, day_config) from a match list when no parameters
  block is in the source.
- **`tba.py` / `live.py` / `frc_events.py` / `statbotics.py`** —
  external API clients. Each handles its own caching and rate
  limiting. The view page polls `live.py` which merges TBA + Nexus
  per-match.

### Frontend (`static/`)

- **`index.html`** — schedule editor. Single-page app with worker
  threads for generation. Heavy because that's where the work
  happens.
- **`view.html`** — read-only view. Light by design; just renders
  schedule + live overlays and provides export. Public (no login
  required) so audiences can read schedules from a share link.

### Stateful data flow

Schedules persist in Postgres as `Event → AbstractSchedule →
AssignedSchedule`. The editor produces these; the view consumes them.

For live data, the view polls `/api/events/{id}/live` every 30s.
That endpoint merges TBA results + Nexus queue status into a
per-match state dict. Each viewer polls independently, but the
server caches the upstream calls so 1000 viewers don't trigger
1000 TBA requests.

## Print and PDF rendering

This is the architecturally interesting part. Print and PDF must
produce visually identical output, must respect the user's
filtering and selections, and must remain in sync with whatever
new data fields we add to the schedule.

### Decision: render server-side from a single template

The flow:

1. Frontend collects current view state: schedule data (already
   has it), filter (which teams the user picked), display options
   (page breaks, scope, etc).
2. Frontend POSTs that to `/api/schedules/render-pdf?format=pdf`
   or `/api/schedules/render-pdf?format=html`.
3. Backend's `pdf_render.py` runs the same Jinja-style template
   either way:
   - `format=pdf` → WeasyPrint produces PDF bytes; client downloads
   - `format=html` → response body is the rendered HTML; client
     opens a popup with that HTML and calls `window.print()`
4. Print and PDF are guaranteed identical because they're generated
   from the same template + same payload.

### Why not client-side

We tried this. html2canvas + html2pdf.js had several failure modes:
- Blank PDFs from off-screen rendering quirks
- Cropped PDFs from canvas-width miscalculation
- Font-loading races
- Unreliable `page-break-before` on `<tr>` elements across browsers
- Output is rasterized images, not real text (not searchable, not
  accessible, larger files)

WeasyPrint produces real PDF text, deterministic output, correct
page breaks. Cost: ~150MB image growth from Pango/HarfBuzz/fontconfig
deps, ~1-2 seconds per render. Acceptable for the operational use
case (small audiences, infrequent generation).

### Why server-side for both Print and PDF

The alternative — server PDF + client window.print() on the live DOM
— means two different render paths. They drift. The live DOM has
overlays (Nexus pills, TBA scores, drift badges) that aren't
appropriate for print. Filtering them out for print mode means
duplicating the filter logic. Adding a new schedule field means
updating both renders.

One template, two output formats from the same endpoint, eliminates
the drift. The client just tells the server "render this schedule
data as PDF" or "render this schedule data as HTML for printing"
and gets back a fully-formed result.

### Why not full server-side rendering for the live page too

We considered it. A truly clean-slate design might have the server
own all rendering (including the live view), with the client as a
thin polling consumer.

We didn't go this way because:
- The app is already client-driven. Migration cost is high.
- Live data integration is naturally client-side (low-latency
  polling, per-user state like team selection).
- Filtering on the live page should be instant. Server round-trip
  on every team-toggle click would be a worse UX.
- The current architecture lets the editor (which does heavy work
  in worker threads) and the view (which is light) share the same
  general approach without forcing one to look like the other.

If we ever wanted to revisit this — e.g. for a richer live-data
experience or to support truly thin clients — the server-side
render template is already in place. We'd add a JSON endpoint that
returns the merged view payload, and a separate render path for
the HTML fragment. Out of scope today.

## File-based imports

Three reliable round-trip formats:

- **JSON** — full restore (parameters + day_config + all matches +
  surrogates + breaks + cycle-changes + seeds). Client-side parse;
  no server hit needed.
- **XLSX** — match list only (FMS-canonical layout). Server-side
  parse via openpyxl, returns the same shape as PDF match-list
  import so the existing preview UI works.
- **CSV** — match list only (three layouts auto-detected: flat,
  report-style, FMS-equivalent). Server-side parse, same response
  shape.

For XLSX and CSV imports, when the source carries no `parameters`
block, `schedule_derive.py` infers num_teams / MPT / cycle_time /
cooldown / num_days / day_config from the match list and pre-fills
the form fields. Each derived field has a confidence rating (high
/ medium / low) so the UI can flag uncertain values for the user
to verify.

A fourth format — **PDF** — exists as an "Import a PDF [BETA]"
path that uses an LLM endpoint to extract structured data from
arbitrary PDFs. Reliability is much lower than the JSON / XLSX /
CSV paths, hence the BETA label. Reserved for cases where the user
has only a PDF (e.g. MSHSL state schedule).

## Live data architecture

The view page polls `/api/events/{id}/live` every 30s in live mode.
That endpoint:

1. Fetches TBA event matches (cached server-side, refreshed every
   60s)
2. Fetches Nexus queue status (cached, 30s refresh)
3. Optionally fetches Statbotics rankings (cached, longer refresh)
4. Merges all three into a per-match dict keyed by qualification
   match number

The client receives a unified payload and updates its UI overlays
without making three separate calls. Future work: when we want
multiple viewers to share live state without each triggering full
polls, switch to server-sent events on the merged feed.

Practice matches don't get live data — TBA and Nexus only track
qualification matches. The live render skips overlay lookups for
practice rows.

## Two-stage scheduling

The scheduler runs in two stages:

1. **Abstract schedule** — slot-based search optimizing for FIRST's
   official quality criteria (round-robin coverage, station balance,
   alliance balance, cooldown, cycle time). The output is a slot
   plan: "match 1 has slots [3, 7, 12] vs [1, 5, 9]." No team
   numbers yet.

2. **Assignment** — map team numbers to slots. Random by default;
   the editor lets the user re-roll the assignment seed without
   regenerating the abstract schedule.

This separation lets the user generate one good abstract schedule
and try multiple team-to-slot mappings cheaply. It's also why
"surrogates" work cleanly — surrogate flags are properties of the
slot, not the match, so they survive re-assignment.

## Constraints we honor

- **No client-side scheduling for the view page**. View is read-
  only, no worker threads, no expensive computation. Editor does
  the work; view just renders.
- **Public-readable view, auth-protected edits**. The `/view` page
  is intentionally public. See [AUTH_DESIGN.md](AUTH_DESIGN.md).
- **No external CDN dependencies for critical functionality**. Live
  view, exports, and basic interactivity work without internet
  beyond the initial page load. (CDN is used for QR codes and
  XLSX styling — both fail gracefully.)
- **Container image stays runnable on OpenShift restricted SCC**.
  No root, no privileged ports, no host filesystem assumptions.

## Future directions

These are explicitly *not* current work, but worth recording so
future decisions can build on them:

1. **Server-side live-data aggregation feed**. Move the per-viewer
   TBA + Nexus polls into a single server-side worker that
   broadcasts to viewers via SSE. Big win for high-viewership
   scenarios.

2. **Print template extraction**. The current `pdf_render.py`
   template is one big Python f-string. Could be moved to Jinja2
   if/when we want template variants (different column orders,
   different paper sizes, different branding strategies).

3. **Multi-event views**. Today the view page shows one event.
   Multi-event aggregations (a district's full season, or a
   regional's playoff bracket alongside qualifying) would need
   either a new view page or a richer query parameter.

4. **Real-time collaborative editing**. Multiple managers editing
   one event at once. Requires a CRDT or operational transform on
   the schedule data. Big project.
