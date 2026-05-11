# Abstract Schedule Library

**Status:** Designed; not started.
**Roadmap target:** v1.1 (foundational for the quality story).
**Companion workstream:** `schedule-quality-reporting.md` — the unified
scoring/reporting that this workstream depends on for curation,
quality tracking, and UI exposure.

## What this is

A library of pre-computed Stage 1 abstract schedules indexed by
fixture shape `(num_teams, matches_per_team, teams_per_alliance)`.
At Generate time, the system **looks up** an abstract for the
requested shape rather than constructing one from scratch.
Construction (running the SA) becomes the fallback path, not the
default.

This is structurally an extension of the three-layer architecture
(ADR 003) — Layer 2 (abstract schedule) becomes a database lookup
when an entry exists, with runtime construction as the fallback.
Layer 1 (day config) and Layer 3 (team assignment) are unchanged.

## What this is not

- **A change to the algorithm.** The SA, post-passes, and lex
  tuple are unchanged. The library is *output* of running those
  at maximum compute budget, not a replacement for them.
- **A change to Stage 2.** Mapping slots → real teams still runs
  the SA each time. The library helps Layer 2 only.
- **A removal of runtime construction.** The SA path remains as
  the cache-miss fallback. Phase 5 algorithm work is still
  valuable — better SA = better library entries on future
  curation runs.

## Why this matters

Today every Generate runs the SA fresh. Quality varies by RNG
seed. The eval shows the SA can reach near-MatchMaker quality on
small/medium fixtures but the per-run variance is real and the
per-run wall-clock is real (~100s at "Best" preset).

A library inverts this. The library entry for `(36, 7, 3)` is
*always the same one* — computed once at SA=50M × best-of-1000
or higher, far beyond what any single user could afford to wait
for. Every 36×7 event subsequently gets that best-known abstract
in milliseconds. Quality becomes deterministic per fixture shape.

Concretely:

| Aspect              | Today                       | With library                                       |
|---------------------|-----------------------------|----------------------------------------------------|
| Compute per Generate| 100s (SA)                   | <1s (lookup)                                       |
| Quality variance    | High (SA seed-dependent)    | Zero (single fixed entry)                          |
| Quality ceiling     | Whatever this SA run found  | Whatever the curation budget reached, ever         |
| Phase 5 Plan C effort | Lands across the whole codebase | Re-curate the library once                   |

## Architecture

### Storage

Library entries live in the database as a new `abstract_library`
table. Each row is one curated abstract for one fixture shape.

```sql
CREATE TABLE abstract_library (
    id                 SERIAL PRIMARY KEY,
    num_teams          INTEGER NOT NULL,
    matches_per_team   INTEGER NOT NULL,
    teams_per_alliance INTEGER NOT NULL,
    cooldown           INTEGER NOT NULL,
    -- Slot-only structure. JSON array of matches, each with
    -- red/blue slot indices and surrogate flags.
    slot_pairings      TEXT    NOT NULL,
    -- Authoritative quality measurements at curation time.
    lex_tuple          TEXT    NOT NULL,   -- 8-element JSON
    composite_score    REAL    NOT NULL,   -- per schedule-quality-reporting.md
    -- Provenance.
    curation_method    VARCHAR(32) NOT NULL,  -- 'curated' / 'cached'
    sa_iterations      INTEGER,
    best_of_n          INTEGER,
    seed_used          VARCHAR(16),
    algorithm_version  VARCHAR(40) NOT NULL,  -- git commit short-hash
    -- When this entry was produced.
    created_at         TIMESTAMP NOT NULL DEFAULT now(),
    -- Optional human label. Curators can tag entries.
    label              VARCHAR(128),
    INDEX (num_teams, matches_per_team, teams_per_alliance,
           cooldown, composite_score)
);
```

The `cooldown` field is part of the key because abstracts are
cooldown-specific (the SA's hard filter depends on it). A
36×7×3 abstract built for cooldown=3 may have cooldown violations
when interpreted as a cooldown=4 schedule.

Multiple entries can exist for one shape. Selection at lookup
time uses `composite_score ASC` to pick the current best, with
ties broken by lex_tuple lex-order (also ASC).

### Lookup at Generate time

`/api/generate-abstract` does this:

```
def generate_abstract_endpoint(num_teams, matches_per_team,
                                teams_per_alliance, cooldown):
    # 1. Look up the best entry for this shape.
    entry = abstract_library.find_best(
        num_teams, matches_per_team, teams_per_alliance, cooldown,
    )
    if entry:
        return entry.slot_pairings, source='library', entry_id=entry.id

    # 2. Cache miss — run the SA at the user's quality preset.
    matches, lex_tuple = run_construction_and_sa(
        num_teams, matches_per_team, teams_per_alliance, cooldown,
        sa_iterations=preset_iterations,
    )
    composite = compute_composite(matches, num_teams, ...)

    # 3. Cache the result for future requests.
    new_entry = abstract_library.insert(
        num_teams, matches_per_team, teams_per_alliance, cooldown,
        slot_pairings=matches,
        lex_tuple=lex_tuple,
        composite_score=composite,
        curation_method='cached',
        sa_iterations=preset_iterations,
        best_of_n=1,  # cache entries come from the user's single Generate
        algorithm_version=current_git_hash(),
    )
    return matches, source='cached', entry_id=new_entry.id
```

The endpoint response includes the `source` so the UI can
display "Loaded curated abstract" vs. "Generated fresh and
cached" — see UI exposure below.

### Curation pipeline

A separate offline pipeline produces curated entries.
`scripts/scheduler_eval/curate.py`:

```
python3 -m scripts.scheduler_eval.curate \
    --shapes 36x7x3,40x12x3,32x3x3,... \
    --sa-iterations 50000000 \
    --best-of-n 1000 \
    --workers 36 \
    --output curated-entries.json
```

Output is loaded into the database via a separate import command,
giving humans the chance to review the lex tuples and composite
scores before promoting entries to production.

A curated entry's quality is recorded alongside the entry. When a
re-curation produces a better entry for an existing shape, the
old entry is kept (for provenance and rollback) but flagged
non-current; lookups pick the current best.

### Storage scale

A 60×9 abstract is ~50 matches × ~50 bytes = ~2.5KB of JSON. With
maybe 100 fixture shapes covered, 3-5 entries per shape (variety
+ historical), and per-row metadata, the table is well under 10MB
total. Negligible.

## Coverage strategy

Day 1 ship covers the FRC-common shapes. Long tail is handled by
the cache fallback.

### Which shapes get curated entries

To be determined by pulling TBA data and histogramming actual FRC
events. As a starting estimate:

- **Common state events:** 32×3 (Week 0), 36×7, 36×8, 40×7, 40×12,
  42×11
- **Common regional events:** 48×8, 50×8, 60×9
- **Common championship:** 75×10, 80×10
- **Estimated total:** 30-50 shapes covering ~95% of real events.

Action item before commit: run the TBA histogram and confirm the
count. If the answer is 30 shapes, the curation budget is one
weekend on Stark. If it's 300, the strategy shifts toward "curate
top-20, cache everything else."

### Cache-miss UX

When a user requests a shape with no library entry:

- The Generate endpoint runs the SA at the user's selected quality
  preset, just as it does today.
- **Every miss caches.** The result is always written back as a
  `curation_method='cached'` entry so subsequent requests for the
  same shape hit the cache. The cache is not opt-in, not optional,
  and not configurable per request. The library *is* the cache;
  curated entries are just one source of cache fill.
- The UI shows "Generated fresh — wait ~Ns" rather than the
  near-instant "Loaded curated abstract" message.

This means the first user to request a new shape pays the SA cost
to populate the cache. Subsequent users benefit. This is the
right tradeoff — cache miss is functionally equivalent to current
behavior; cache hit is a substantial improvement.

### Cache-hit-below-preset-quality

A subtle case the simple "lookup first" pattern doesn't cover:
the cache entry was made by a user on `fair` preset (50K iter,
composite=22); a new user runs at `best` preset on the same shape.
A naive lookup-first returns the cached entry, but the new user
paid for higher quality and would have gotten composite=18 if
they'd run from scratch.

**Policy:** the lookup compares the entry's curation budget against
the requesting user's preset budget. Three cases:

| Case | Cache state                                | Action                                                                 |
|------|--------------------------------------------|------------------------------------------------------------------------|
| 1    | No entry for shape                         | Run SA at user's preset; insert as `cached`.                           |
| 2    | Entry exists, budget ≥ user's preset budget | Return entry. The library has at-or-above the requested quality.       |
| 3    | Entry exists, budget < user's preset budget | Run SA at user's preset; if better, supersede. Otherwise return entry. |

Case 3 is "always cache" applied through: a user paying for higher
quality preset shouldn't be capped by a stale lower-quality cached
entry. They regenerate, and if their run beats the cache, it
becomes the new library entry. The user has contributed to library
quality, not just consumed it.

This makes every `best`-preset Generate an implicit curation run
for its shape. Over time the library trends toward `best`-preset
quality across every shape that's been hit, without any explicit
curation effort beyond running real users' requests.

```python
def find_or_generate(shape, user_preset):
    user_budget = iterations_for_preset(user_preset)
    entry = abstract_library.find_best(shape)
    if entry and entry.sa_iterations >= user_budget:
        return entry, source='library'  # Case 2

    # Case 1 (no entry) or Case 3 (entry below user's budget).
    new_matches, new_lex_tuple, new_composite = run_sa(shape, user_preset)

    if entry and new_composite >= entry.composite_score:
        # Generated worse than the existing entry — keep existing
        # as the library best, return the new schedule to the user.
        # The user's run didn't improve the library, but they get
        # a usable schedule.
        return new_matches, source='generated_no_supersede'
    else:
        # Generated better (or no prior entry) — cache it as the
        # new library best.
        abstract_library.upsert(shape, new_matches, ...)
        return new_matches, source='generated_cached'
```

The two systems that would otherwise be unrelated (cache fallback
+ explicit curation pipeline) unify here: the library trends toward
its best-known state through any combination of curation runs and
user-initiated Generate calls. Curation is an *accelerant*, not a
prerequisite.

### Cache promotion to curation

Cache entries are `curation_method='cached'`; their quality
reflects whatever budget the user's preset paid for. Periodically
the curator re-runs at full budget against shapes with hot cache
entries; if the curator beats the cache, the cache entry is
superseded by a curated entry.

## Variety vs. consistency

Open question: do we want one best entry per shape, or several
high-quality entries that the system rotates among?

**Pro one entry:** simplicity, fully deterministic, easy to
explain ("the best 36×7 schedule we know of"). Quality is
maximal.

**Pro several entries:** teams attending multiple 36×7 events
don't see the identical structural pattern repeatedly. Mitigates
the "all events have the same slot-1-plays-slot-2-in-match-1"
phenomenon.

**Recommendation:** start with one entry per shape. If users
report repetition as an issue, add a multi-entry rotation policy
later. The schema already supports multiple entries; the lookup
just picks the best. Switching to rotation is a query change, not
a schema migration.

## Connection to other workstreams

### Connection to ADR 003 (three-layer architecture)

Library lives at Layer 2. Layer 1 (day config) and Layer 3 (team
assignment) are unchanged. The library reinforces the three-layer
separation — Layer 2 is now obviously distinct from Layer 1
calendar work and Layer 3 team-identity work.

### Connection to ADR 006 (server-only construction)

ADR 006 retired the browser scheduler in favor of server-side
construction. With this workstream, "server-side construction"
becomes "library lookup + cache-miss fallback." ADR 006's
retirement work is functionally unchanged but radically simpler:
the JS construction is replaced by an API call that almost always
returns instantly. Estimated 2-3 days in ADR 006 drops to ~half a
day.

### Connection to scheduler-quality workstream

Phase 5 (current scheduler-quality.md) was about "how to improve
the SA." With a library, the SA improvements feed into curation
runs that produce better library entries. The same algorithmic
work; different deployment. Phase 5 Plan B/C investigations
remain valuable.

### Connection to schedule-quality-reporting.md

The library depends on a unified scoring mechanism — every entry
needs a composite_score, every entry needs comparable lex tuples,
and the UI needs to display these consistently across library
entries, generated schedules, and imported schedules. See
`schedule-quality-reporting.md` for that design.

### Connection to ui-quality-exposure.md

The four-tier plan in that doc becomes more powerful with the
library. Per-pair detail (Tier 1) is the same; lex-tuple
breakdown (Tier 2) gets richer because the library makes the
current schedule's lex tuple comparable to the library's known
best. Reference comparison (Tier 3) becomes "your schedule vs.
the library's best for this shape" — a much sharper comparison
than "your schedule vs. some unspecified TBA distribution." See
that doc for the integration.

## UI exposure

The Generate flow gains a small status indicator:

- "Loaded curated abstract (composite: 8.2)" — library hit,
  shape-best.
- "Loaded cached abstract (composite: 18.5, generated 3 weeks
  ago)" — cache hit but not curator-quality.
- "Generated fresh (composite: 22.1) — cached for future
  requests" — cache miss.

The composite_score and lex_tuple are exposed via the schedule
quality card, fed by the unified scoring mechanism. See
`schedule-quality-reporting.md` and `ui-quality-exposure.md`.

A "Browse library" admin view shows the table of entries:
shape × current best composite × curation method × algorithm
version. Useful for curators; gated behind admin auth (per
current `is_admin` model, or RBAC roles when that lands).

## Implementation phases

### Phase L-1: Library infrastructure

1. Schema migration (`abstract_library` table).
2. `app/abstract_library.py` module: lookup, insert,
   find_best, supersede.
3. `/api/generate-abstract` rewired to do lookup-first,
   construct-and-cache on miss.
4. Tests covering hit, miss, multiple entries per shape, the
   cooldown axis.
5. The Generate response surfaces the source field.

Estimated 1-2 days. Doesn't require any curated entries to ship —
day-one behavior is "always cache miss" while the library is empty,
which is identical to current behavior.

### Phase L-2: Curation pipeline

1. `scripts/scheduler_eval/curate.py` runner.
2. Output format compatible with the import command.
3. `scripts/scheduler_eval/import_curated.py` to load into DB.
4. Documentation in this file for the curation workflow.

Estimated 1 day.

### Phase L-3: Initial curation run

1. Pull TBA fixtures, histogram shapes, pick the top 30-50.
2. Run curation on Stark (~weekend wall-clock).
3. Review curated lex tuples; spot-check schedules; import.

Estimated 2-3 days of human time, ~weekend of compute.

### Phase L-4: UI integration

1. Generate response renders source/composite in the share bar.
2. Schedule quality card consumes the unified scoring data per
   schedule-quality-reporting.md.
3. Admin "Browse library" view.

Estimated 1-2 days. Depends on schedule-quality-reporting.md being designed.

### Total estimate

~1 week of focused work plus one weekend of curation compute,
spread across Phase L-1 through L-4. Phase L-1 can ship
independently; subsequent phases compound on it.

## Action items before committing

These are diagnostic questions to answer first:

- [ ] **TBA fixture histogram.** Pull the last 5 years of FRC
      events; count distinct `(num_teams, matches_per_team,
      teams_per_alliance, cooldown)` shapes. Determines whether
      "30-50 shapes covers 95%" is right or whether the long
      tail is bigger.
- [ ] **Quality ceiling estimate.** On a representative shape
      (probably 36×7 since we have the most data), run SA=50M ×
      best-of-100 on Stark. Does the composite score beat
      best-of-100 at SA=2M? If yes by how much? This determines
      whether the library's value is determinism+speed only or
      also raw quality.
- [ ] **Cooldown-axis cardinality.** Confirm the cooldown value
      is part of the lookup key. If cooldown=3 abstracts are
      reusable as cooldown=4 (no violations introduced), the
      schema can collapse this dimension.

## Open questions

- **Is the library entry a separate concept from the
  `abstract_schedules` table?** The latter records *user-
  generated* abstracts (with a creator, an event association,
  etc.). The library entries are *system-curated* and shape-
  associated. Cleanest design: separate tables. `abstract_library`
  is the catalog; `abstract_schedules` is the per-user
  instantiation (a user picking a library entry creates an
  `abstract_schedules` row that references it).
- **Should curated entries also pass through Stage 2 in
  curation?** I.e., curate not just the abstract but a
  default team assignment ordering? Probably not — Stage 2 is
  per-event (depends on team identities, color preferences, etc.)
  and varies by user. Curate Layer 2 only.
- **Versioning.** When the algorithm changes (Phase 5 Plan C
  lands, lex tuple gains a slot), do old library entries become
  invalid? Per ADR 004, no — the stored entries are the entries.
  Their lex tuples are still computable under the new algorithm;
  they may rank differently against fresh curation but they still
  produce valid schedules.
- **Public access to the catalog.** Should there be a public-
  facing endpoint listing the available shapes and their quality
  scores? Could be useful for transparency. Not part of the
  initial scope.

## References

- ADR 001 — Lex tuple as the canonical schedule score.
- ADR 003 — Three-layer architecture (library lives at Layer 2).
- ADR 006 — Server-only construction; this workstream subsumes
  most of its retirement work.
- `workstreams/scheduler-quality.md` — Phase 5 algorithm work
  feeds into curation runs.
- `workstreams/schedule-quality-reporting.md` — the unified scoring this
  workstream depends on.
- `workstreams/ui-quality-exposure.md` — surfaces library quality
  data to users.
- `scripts/scheduler_eval/` — the eval harness that grows the
  curator and import commands.
