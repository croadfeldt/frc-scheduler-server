# ADR 005 — MatchMaker as peer, not competitor

**Status:** Accepted
**Date:** Project inception (reaffirmed throughout)
**Context:** Idle Loop's MatchMaker is the de facto reference
schedule generator in the FRC community — most events run with it,
and its output is what teams expect. A new scheduler can position
itself in several ways relative to MatchMaker. The project's
positioning shapes everything from the eval methodology to the
copy in the README.

## Decision

MatchMaker is treated as a **peer reference**, not a competitor.

- The eval harness (`scripts/scheduler_eval/`) compares against
  MatchMaker's output as one adapter among several. Beating
  MatchMaker is not the goal; matching it on FRC §10.5.2 paramount
  criteria and producing comparable schedules is.
- The `actual` adapter (FRC's published schedules, which are
  themselves usually MatchMaker-generated) is included in eval
  comparisons. We aim to be in the same neighborhood as both.
- Documentation acknowledges MatchMaker's role — it's not framed
  as something to replace, it's framed as the prior art the
  project builds on top of.
- The Sykes station-balance algorithm (used in Phase 2 post-pass)
  is independent reference of the same idea; we did not port
  MatchMaker code or wrap the MatchMaker binary. See
  `MATCHMAKER_LICENSING_BRIEF.md` for the boundary.

## Why this matters

A "competitor" framing leads to:
- Eval methodology that's biased toward winning ("if our
  composite is lower, we win") rather than understanding ("why
  does MM hit station_spread=0 and we hit 5?").
- Marketing-ish copy that sets up adversarial expectations users
  won't have — most users want a schedule that works, not a
  scheduler that beats some other scheduler.
- Pressure to ship algorithmic differences for differentiation
  rather than for genuine quality.

A "peer reference" framing leads to:
- Eval methodology that uses MM as ground truth where MM is
  strong (which is often), and as a comparable-quality target
  elsewhere.
- Documentation that credits MM's prior art and clearly
  distinguishes ported code (none) from independent
  implementations of the same idea (Sykes station balance).
- Algorithmic priorities driven by what produces good schedules,
  not by what differentiates from MM.

## Alternatives considered

**Competitor framing** — set up MM beats explicitly as goals,
report wins in changelogs. Rejected for the reasons above. Also
rejected because at our scale MM has 20+ years of refinement and
treating it as something to beat sets up an unrealistic
short-term expectation that hurts when single-fixture wins don't
generalize (as observed during Phase 5 diagnostic work).

**Wrapper over MM** — call MM as a subprocess; let it do the
heavy lifting; provide UI on top. Rejected because of
licensing constraints (see `MATCHMAKER_LICENSING_BRIEF.md`),
because we want to control the algorithm for FRC §10.5.2
compliance specifically, and because MM doesn't run as a
service / can't be easily containerized.

**Ignore MM entirely** — eval only against FRC's published
schedules. Rejected because published schedules ARE usually MM
output, so we'd be measuring against MM transitively without
explicitly recognizing it. Better to measure against MM directly
when comparing.

## Consequences

**Good:**
- Eval framings ("MatchMaker hits station_spread=0 on 10/13
  fixtures, we hit ≥2 on every fixture — let's understand why")
  are diagnostic, not adversarial.
- Documentation can credit prior art freely without confusion.
- The project has clear cultural permission to use MM-style
  approaches where they work, without trying to invent new ones
  for the sake of difference.
- When we beat MM on something (color imbalance, max opponent
  repeats, min match gap — all from the post-Phase-4 baseline),
  the framing is "we found a useful improvement over the prior
  art" rather than "we won."

**Bad:**
- Some users may expect a competitor framing and read the
  measured-not-marketing tone as underconfidence. Mitigation: the
  README and eval findings speak plainly about both wins and
  losses.
- It limits some eval framings — we can't say "we replaced
  MatchMaker" because that's not what we're doing.

## References

- `docs/scheduler/MATCHMAKER_LICENSING_BRIEF.md` — the legal /
  licensing analysis.
- `docs/scheduler/MATCHMAKER_ALIGNMENT_ROADMAP.md` — historical
  context for which MatchMaker behaviors we deliberately match
  vs deliberately diverge from.
- `app/post_passes/station_balance.py` — header comment crediting
  Sykes for the station-balance idea and noting the independent
  implementation.
- `scripts/scheduler_eval/adapters/matchmaker.py` — MM as one
  adapter among several.
