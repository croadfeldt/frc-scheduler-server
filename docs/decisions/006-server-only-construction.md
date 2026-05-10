# ADR 006 — Server-only construction; retire the browser scheduler

**Status:** Accepted
**Date:** 2026-05-10
**Context:** The codebase has two implementations of Stage 1
abstract construction: a Python implementation in
`app/scheduler.py` (called from `/api/generate-abstract` and used
by the eval harness) and a JavaScript implementation in
`static/index.html` (`generateMatches()` at lines 8793 and 17233 —
itself duplicated). They have evolved differently:

- The Python implementation was refactored in Phase 0 to use the
  unified lex SA with FRC §10.5.2 paramount priority. Eval data
  is collected against this path.
- The JavaScript implementation still uses the original weighted-
  sum scoring with construction-only logic (no SA pass).

Users in the editor who click "Generate" without subsequently
clicking "Assign Teams" get a schedule from the JS path that's
materially worse than what the project's quality measurements
suggest the algorithm produces. Two implementations of "the
algorithm" also create ongoing drift risk and double-work for any
algorithm change going forward.

## Decision

The browser scheduler path is retired. Stage 1 construction is
server-side only, via `/api/generate-abstract`. The browser is
presentation: it sends the user's event configuration to the
server, receives the constructed schedule, renders it. The user-
facing flow ("click Generate") is preserved but its
implementation moves entirely server-side.

Specifically:

1. The two `generateMatches()` JS function definitions in
   `static/index.html` (main schedule and practice schedule) are
   removed.
2. Every call site that invoked them locally is rewritten to call
   `/api/generate-abstract` (or a similar practice-match endpoint
   if one is needed; practice matches today reuse
   `generateMatches` with different parameters).
3. The "Placement Criteria" panel in the editor — which lets
   users tweak the browser scheduler's weights — is either
   removed or reframed as a read-only summary. Tuning a
   configuration that no longer runs in the browser is misleading.
4. The user experience continues to feel like one click. Loading
   feedback during the server round-trip mirrors what
   `/api/generate-abstract` already produces (it streams progress
   via SSE, which the editor consumes today for the SA path).

## Alternatives considered

**Option B — keep both paths, align browser scoring to lex SA.**
Update the JS implementation to mirror Python's lex tuple,
paramount cooldown, and post-passes. Rejected because:

- Maintaining two implementations of the same algorithm doubles
  the work for every future algorithm change. Phase 5 Plan C
  (lex-tuple extension) and any cooling-schedule rework would
  have to land in both languages with bit-equivalent semantics
  to avoid drift.
- The algorithms must agree exactly or eval methodology breaks
  again — bit-equivalent JS↔Python implementations are difficult
  to maintain (RNG conventions differ, integer overflow rules
  differ, sort stability differs).
- The browser path can't run the SA budget that the server path
  runs. "Best" preset = 2M iterations × ~100s wall-clock; users
  would expect their editor click to take 100 seconds, or settle
  for a smaller budget than production gets, which reintroduces
  the divergence Option A solves.

**Status quo — leave the browser scheduler.** Rejected for the
correctness reasons in Context above; the divergence between
"editor preview" and "deployed schedule" is exactly the kind of
silent quality bug that the eval methodology correction was
about, just in a different surface.

**Hybrid — server-only Stage 1, but preserve the browser path
as offline/preview.** Rejected because no user has asked for
offline operation, and the cost of carrying the browser path is
the same whether it's offline-only or always-active. The
"preview before commit" UX is solved by `/api/generate-abstract`
streaming results and the user accepting/discarding them.

## Consequences

**Good:**
- Single canonical algorithm. "The scheduler" means one thing in
  documentation, eval, and production.
- Phase 5 Plan B/C work lands in one place. Drift risk eliminated.
- The editor's quality matches the eval's quality — no silent
  regression for users who don't click "Assign Teams."
- The Placement Criteria panel disappearing simplifies the
  editor UI; the construction weights are a developer concern,
  not a user-facing knob.

**Bad:**
- The editor now requires a server round-trip on every Generate.
  Today's offline-after-load experience for the construction
  step disappears. The Assign Teams step already requires a
  server round-trip, so this aligns the two but doesn't reduce
  network requirement overall.
- Practice match generation needs a server endpoint. Today
  practice matches share `generateMatches()` with their own
  parameters; that path needs a server analog. Not architecturally
  hard but it's surface area to design.
- Some users may have come to rely on the editor running offline
  for casual exploration. Mitigation: keep the editor's day-config
  and team-list editing offline; only the Generate-Schedule action
  becomes server-bound.
- The retirement is a non-trivial code change. The two
  `generateMatches()` definitions, the practice-match call site,
  the "Placement Criteria" panel, and the surrounding flow control
  all need refactoring. Estimate: 2-3 days of focused work.

## Action items

- [ ] Inventory every call site of `generateMatches()` in
      `static/index.html` (main schedule generation, practice
      match generation, any test/debugging use).
- [ ] Decide whether practice-match generation gets its own
      server endpoint or uses an extension of
      `/api/generate-abstract`.
- [ ] Implement the retirement: replace JS calls with server
      calls; remove the `generateMatches()` definitions; update
      the editor UX to flow through the server path with
      progress indication.
- [ ] Remove or reframe the Placement Criteria panel. If kept,
      label it "Construction parameters (informational)" with the
      values the server is using for transparency.
- [ ] Verify no test relies on the browser scheduler. The JS test
      suite (`test_v2_url.js`, `test_field_three_up.js`,
      `test_v2_scheduler_input.js`, `test_cycle_change_walker.js`)
      tests URL parsing and cycle-change semantics, not the
      scheduler itself, so this should be a no-op for tests.
- [ ] Update `docs/HANDOFF.md` §5.1 once shipped — it currently
      describes the work as Option A vs B; that ambiguity is
      resolved by this ADR.

## References

- `app/scheduler.py` — `generate_matches()` (the Python
  implementation that becomes the canonical path).
- `app/main.py` — `/api/generate-abstract` endpoint.
- `static/index.html:8793` and `:17233` — the JS `generateMatches`
  duplicates that this ADR retires.
- `static/index.html` — the "Placement Criteria" panel
  (`#placementCriteriaPanel`) that becomes vestigial.
- HANDOFF §5.1 — the prior Option A vs B framing.
- ADR 003 — three-layer architecture; this ADR sharpens it by
  making Layer 2 (abstract schedule) server-only.
