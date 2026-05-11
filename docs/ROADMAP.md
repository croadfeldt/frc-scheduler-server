# FRC Match Scheduler — Roadmap

**Owner:** roadfeldt
**Repo:** github.com/croadfeldt/frc-scheduler-server
**Status:** active development, continuous deployment

This is the single source of truth for "where the project is going."
Each line item points to its workstream design document.

Replaces the prior scatter across `docs/PRIORITIES.md`, the open-items
section of `docs/HANDOFF.md`, and the per-workstream roadmap docs.
HANDOFF is now a per-session log, not a master plan; PRIORITIES is now
a technical reference for FRC §10.5.2 placement priorities, not a
project priority list.

## Release model

**Continuous deployment.** Every push to `main` is the production
version. There are no release tags or version numbers right now —
the project ships as fast as it lands. If the project later grows
into a place where users need to pin to versions or there's a story
to tell about "what's new," that's the trigger to add a CHANGELOG and
tagging cadence. Today neither is needed.

What we do have:
- A session log (`HANDOFF.md`) that records what shipped each session,
  with file paths and code references.
- A working test suite (12 suites, ~150+ individual tests) that gates
  every deploy.
- A session-deliverable protocol (`REPRODUCTION_PROMPT.md`) that
  produces commit-ready bundles per session.

That's enough release process for the current scale.

## Versioning intent

Even without tags, "v1.0 / v1.1 / v1.2 / v2.0" are useful planning
buckets to know what's in scope for the near, medium, and long term.
The boundaries below are direction, not commitments.

### v1.0 — current state, "reliable scheduler for state-event use"

This is essentially what's deployed today. Item statuses reflect
shipped, not planned.

- ✓ Two-stage scheduler (abstract construction + SA assignment)
- ✓ Lex-tuple optimization per FRC §10.5.2 paramount priority
- ✓ R/B post-pass (Phase 1) and Sykes station post-pass (Phase 2)
- ✓ Quality presets (fair / good / best / maximum)
- ✓ V2 day config with breaks, cycle changes, practice day support
- ✓ Auth (Google + GitHub OAuth), mandatory on writes
- ✓ Schedule lifecycle phases A/B/C/E (auth, fork via duplicate,
  structural immutability, `is_admin` interim authorization)
- ✓ Schedule Quality card in editor UI
- ✓ Stable URLs, exports (PDF/XLSX/CSV), public `/view`
- ✓ MatchMaker xlsx + CSV + PDF imports
- ✓ Eval harness (16-fixture inventory, working as of 2026-05-10)

Quality baseline at this point: mean composite 30.64 across 16 TBA
fixtures with `--quality-preset best`. Just over the "investigate
further" cutoff (30) per `workstreams/scheduler-quality.md`. The
failure has narrowed to two specific phenomena (see v1.1 first item).

### v1.1 — "schedule quality polish"

Active work. Reshaped 2026-05-10 around two new workstreams that
together form the v1.1 quality story:

- **Abstract Schedule Library** — pre-computed best-known abstracts
  per FRC fixture shape, looked up at Generate time; cache-on-miss
  for uncovered shapes. Quality becomes deterministic per shape;
  curation budgets become unlimited (offline, max-budget compute).
  See [`workstreams/abstract-library.md`](workstreams/abstract-library.md).
- **Schedule Quality Scoring & Reporting** — unified quality
  framework callable everywhere (server, CLI, UI). One canonical
  answer to "is this schedule good?" instead of today's four
  overlapping systems. Tiered UI exposure with per-pair detail,
  lex tuple, reference comparison, and cross-schedule comparison.
  See [`workstreams/schedule-quality-reporting.md`](workstreams/schedule-quality-reporting.md).
  Supersedes the prior `workstreams/ui-quality-exposure.md`.

Phase 5 of `workstreams/scheduler-quality.md` continues in parallel
as the curation pipeline that populates the library — diagnostic
experiments running on Stark as of 2026-05-10 will determine which
algorithmic change to invest in.

**Suggested sequencing when work starts:**

1. **Schedule Quality Reporting Phase A** (`app/quality.py` consolidation,
   ~2 days). The library workstream depends on this for measuring
   library entry quality — needed before curation begins. Also pays
   immediate dividends: unified scoring fixes the "four overlapping
   quality systems" problem regardless of library timing.
2. **Abstract Schedule Library Phase 1** (~2 days). Schema, API,
   lookup-first/cache-on-miss, supersession when a higher-quality
   generation arrives. Ships with empty library; day-one behavior
   identical to current. Earns its value with each subsequent cache
   hit.
3. **Schedule Quality Reporting Phase B** (server API, ~1 day) and
   **Phase C** (UI Tier 1, ~3-4 hours). Surfaces per-pair / per-team
   detail in the editor against the now-cached library entries.
4. **Phase 5 result lands**. Diagnostic data from Stark determines
   Plan B vs Plan C. Either becomes a parameter/code change in the
   curation pipeline, not in every Generate.
5. **Abstract Schedule Library Phase 2** (curate FRC-common shapes,
   ~weekend of Stark compute). With Phase 5 settled, curation
   produces the best library entries achievable. Production users
   start getting library hits.

This order minimizes risk by getting the measurement-and-scoring
infrastructure in before the structural changes that depend on it.
Steps 1-3 are safe to ship sequentially regardless of how Phase 5
resolves.

Line items:

- ☐ Phase 5 Plan A diagnostics — running on Stark. Two experiments
  that distinguish iteration-limited from objective-limited causes
  for `max_station_spread` and `repeat_opponents` failures.
  Determines whether Plan B (post-pass budget bump) or Plan C
  (lex-tuple expansion) is the right curation-pipeline investment.
- ☐ Phase 5 Plan B (if iteration-limited): raise post-pass
  iteration budget per fixture size. Becomes a parameter of the
  curation pipeline rather than of every Generate.
- ☐ Phase 5 Plan C (if objective-limited): extend the lex tuple
  with a count-clustering term, or redesign post-pass move set.
  Becomes a one-time curation-pipeline change rather than a
  reproducibility break.
- ☐ Abstract Schedule Library (Phase 1) — schema, API, curation
  script, lookup-first/cache-second integration. ~2 days. See
  abstract-library.md Phase 1.
- ☐ Abstract Schedule Library (Phase 2) — curate FRC-common
  shapes at maximum budget. ~1 weekend of Stark compute + ~1 day
  review.
- ☐ Schedule Quality Reporting (Phase A) — unified `app/quality.py`
  module consolidating today's four scoring systems. ~2 days.
- ☐ Schedule Quality Reporting (Phase B) — server API:
  `/api/schedules/{id}/quality-report` endpoint + enrichment of
  existing responses + `quality_composite` column. ~1 day.
- ☐ Schedule Quality Reporting (Phase C — UI Tier 1) — surface
  per-pair detail + per-team breakdown + concentrated surrogate
  slots in the existing editor Quality card. ~3-4 hours.
- ☐ Schedule Quality Reporting (Phase D — UI Tier 2) — surface
  the lex tuple in the editor + schedule comparison view. ~1 day.
  Pre-work: decide `match_equity` slot fate (Q2 in
  schedule-quality-reporting.md).
- ☐ Retire the browser scheduler. With the library in place,
  this becomes "replace JS `generateMatches()` with API call to
  the library lookup endpoint" — ~half a day instead of the
  original 2-3 days. ADR 006's action items get re-shaped by the
  library work. See HANDOFF §5.1.
- ☐ Production CPU_WORKERS quality gap — eval ran best-of-100
  on Stark; production users get best-of-12 (or best-of-3 under
  load). Less critical with the library in place (library entries
  are computed at best-of-1000+ offline) but worth measuring for
  the cache-miss path quality story. See HANDOFF §5.x or open as
  a new item.
- ☐ Three odd-team-count fixtures still error on MatchMaker
  (2023mnmi 61t, 2024mndu 55t, 2025mnmi 51t). The
  `[FIXED 2026-05-09]` claim in EVAL_FINDINGS.md is incorrect.
  ~5-minute investigation, independent of everything else.

### v1.2 — "multi-event, multi-tenant"

The current `is_admin` model is interim. v1.2 lifts that.

- ☐ RBAC R-1 + R-2 (schema + authorization checker, replacing
  `is_admin`). The foundation everything else builds on. See
  `workstreams/rbac.md`. Paused pending change-freeze lift +
  decisions on the seven open design questions in that doc.
- ☐ Schedule lifecycle phase F — lock TTL + heartbeat. Highest
  immediate UX value of the open lifecycle phases (kills the
  "dead lock from a closed tab" papercut). See
  `workstreams/schedule-lifecycle.md`.
- ☐ Schedule lifecycle phase G — lifecycle response field on
  schedule reads. Removes ad-hoc layering checks in the frontend.
- ☐ Schedule Quality Reporting (Phase E — UI Tier 3) — reference
  comparison via recalibrated thresholds. Requires the
  calibration data work in `pull_tba_fixtures.py`. Percentile
  badges in the UI; "your schedule's repeat_partners is at the
  70th percentile of comparable FRC events." Substantial effort
  due to calibration judgment calls (bucket boundaries, sample
  size). See schedule-quality-reporting.md Phase E.

### v2.0 — "public release"

Long-term shape of the product. Not actively planned.

- ☐ RBAC R-3 through R-7 (delegation, expiration, in-app
  notifications, role request flow, full UI for role management).
- ☐ Schedule lifecycle phase D — consolidated `event_audit_events`
  table + audit-log UI.
- ☐ Schedule Quality Reporting (Phase F — UI Tier 4) — quality
  info on `/view` (public spectator surface). Gated on the open
  product question: do public spectators benefit from seeing
  schedule-quality detail, or does it invite litigation of
  mathematically-forced edge cases. See
  schedule-quality-reporting.md Phase F.
- ☐ Abstract Schedule Library — promotion of long-tail shapes
  from cache-on-miss to curated. Continuous improvement of
  existing entries via `--improve-existing` curation runs as
  algorithm work lands.

## Backlog (not version-targeted)

- Container parallelism investigation (HANDOFF §5.2) — best-of-N
  on container vs Stark behaves differently; root cause unknown.
- par_quad outlier diagnosis (HANDOFF §5.3) — single fixture
  produces par_quad=256 instead of floor 252 ~5% of trials on
  container, never on Stark. Likely related to #5.2.
- Best-of-N production runner (HANDOFF §5.4) — explicit
  "Generate Best Schedule" workflow with progress reporting.
- Extended iteration sweep (HANDOFF §5.5) — find K* per the
  tight-criterion definition. ~5 hours wall-clock on Stark.
- Threshold recalibration in `metrics.py` (EVAL_FINDINGS issue
  #2) — current thresholds classify MatchMaker output as "poor"
  on most metrics. Calibrate against TBA played-schedule
  distribution.
- Per-metric aggregate view in eval report (EVAL_FINDINGS
  issue #2) — diagnostic table for which metric × fixture-size
  combinations are bottlenecks.
- Speed-proposals review (HANDOFF, "Speed proposals" doc from
  another session) — five proposals for wall-clock reduction.
  Quality-first verdict: defer until v1.1 lands and we know
  there's quality margin to spend.

## How this doc is maintained

- Updated as part of any session that affects scope.
- Status markers: `✓` shipped, `◐` partially shipped, `☐` planned.
- Each item points to a design doc (`workstreams/*.md`,
  `scheduler/*.md`, or HANDOFF section). If something doesn't have
  a design doc, it shouldn't be on the roadmap yet — write the
  design first.
- Items move between version buckets as scope and priorities
  shift. Items in Backlog don't get promoted until there's a
  reason to commit them to a version.
- The HANDOFF doc captures *what shipped*; this doc captures
  *what's planned*. Don't conflate the two.
