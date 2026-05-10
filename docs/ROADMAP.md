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

Active work. Phase 5 of `workstreams/scheduler-quality.md` is the
gate. Diagnostic experiments are running on Stark as of 2026-05-10
to determine which structural change closes the remaining gap.

- ☐ Phase 5 Plan A diagnostics — running. Two experiments that
  distinguish iteration-limited from objective-limited causes for
  `max_station_spread` and `repeat_opponents` failures. Result
  determines Plan B vs Plan C.
- ☐ Phase 5 Plan B (if iteration-limited): raise post-pass
  iteration budget per fixture size. Estimated 2-3 days.
- ☐ Phase 5 Plan C (if objective-limited): extend the lex tuple
  with a count-clustering term, or redesign post-pass move set.
  Estimated ~1 week. Requires reproducibility-policy decision
  (now made — see ADR 004).
- ☐ UI Quality Exposure Tier 1 — surface `worst_pairs` and
  `slot_table` per-team detail in the editor's Quality card.
  ~3-4 hours, no backend change. See
  `workstreams/ui-quality-exposure.md`.
- ☐ Production CPU_WORKERS quality gap — eval ran best-of-100
  on Stark; production users get best-of-12 (or best-of-3 under
  load). Whether eval overstates production quality is unknown
  and worth measuring. See HANDOFF §5.x or open as a new item.
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
- ☐ UI Quality Exposure Tier 2 — surface the lex tuple in the
  editor (new endpoint, Quality breakdown section, schedule
  comparison view).

### v2.0 — "public release"

Long-term shape of the product. Not actively planned.

- ☐ RBAC R-3 through R-7 (delegation, expiration, in-app
  notifications, role request flow, full UI for role management).
- ☐ Schedule lifecycle phase D — consolidated `event_audit_events`
  table + audit-log UI.
- ☐ UI Quality Exposure Tier 3 — reference comparison via
  TBA-calibrated thresholds. Highest user value, highest effort,
  needs calibration data validation.
- ☐ UI Quality Exposure Tier 4 — quality info on `/view` (public
  spectator surface). Gated on the open product question:
  do public spectators benefit from seeing schedule-quality
  detail, or does it invite litigation of mathematically-forced
  edge cases.

## Backlog (not version-targeted)

- Browser scheduler retirement (HANDOFF §5.1) — UI runs its own
  scheduler; container path is now better, browser path is dead
  weight.
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
