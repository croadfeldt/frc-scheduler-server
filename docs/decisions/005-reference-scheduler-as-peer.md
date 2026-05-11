# ADR 005 — Reference scheduler as peer, not competitor

**Status:** Accepted
**Date:** Project inception (reaffirmed throughout)
**Context:** FRC has an established reference scheduler — the tool
used by the official Field Management System and the de facto
standard against which scheduling quality is judged in the
community. A new scheduler can position itself in several ways
relative to that prior art. The project's positioning shapes
everything from the eval methodology to the copy in user-facing
documentation.

## Decision

Our scheduler treats the reference tool as a **peer reference**,
not a competitor.

- The eval harness compares against published FRC schedules and,
  when a user supplies them, against externally-generated CSVs.
  The framing is "what does our output look like compared to a
  reference at this fixture shape" — not "did we win."
- The "actual" adapter (FRC's published schedules, fetched via
  the TBA API) is a primary comparison point in eval. Beating any
  named external tool is not the goal; producing schedules of
  comparable quality at the fixture shapes FRC events use is.
- Documentation acknowledges prior art generically — established
  FRC scheduling approaches, the underlying simulated-annealing
  technique, the station-balance algorithm — without invoking
  upstream brand names in user-facing surfaces.
- The station-balance approach used in Phase 2 is an independent
  implementation of a publicly described technique. No code is
  ported from any external tool. See
  `REFERENCE_SCHEDULER_LICENSING.md` for the legal boundary.

## Why this matters

A "competitor" framing leads to:
- Eval methodology biased toward winning ("if our composite is
  lower, we win") rather than understanding ("why do reference
  schedules hit station_spread=0 and we hit 5?").
- Marketing-ish copy that sets up adversarial expectations users
  won't have — most users want a schedule that works, not a
  scheduler that beats some other scheduler.
- Pressure to ship algorithmic differences for differentiation
  rather than for genuine quality.
- Legal and relationship exposure when comparative claims are
  imprecise, particularly against a specifically named external
  tool. Comparative-advertising standards apply even to small
  projects, and bad blood with established tools in the same
  niche is unnecessary.

A "peer reference" framing leads to:
- Eval methodology that uses published FRC schedules as ground
  truth where they're strong (often), and as a comparable-quality
  target elsewhere.
- Documentation that credits prior art and clearly distinguishes
  ported code (none) from independent implementations of the same
  algorithmic idea.
- Algorithmic priorities driven by what produces good schedules,
  not by what differentiates from any specific upstream.
- Reduced legal/relationship exposure. Comparison statements
  reference the FRC schedule corpus, not a named product, so they
  describe an empirical distribution rather than a head-to-head
  match.

## Alternatives considered

**Competitor framing** — set up named-product beats explicitly as
goals, report wins in changelogs. Rejected for the reasons above.
Also rejected because established FRC schedulers have decades of
refinement and treating them as something to beat sets up an
unrealistic short-term expectation that hurts when single-fixture
wins don't generalize.

**Wrapper over a named external tool** — call the external tool as
a subprocess; let it do the heavy lifting; provide UI on top.
Rejected because of licensing constraints (see
`REFERENCE_SCHEDULER_LICENSING.md`), because we want to control
the algorithm for FRC §10.5.2 compliance specifically, and
because the external tool doesn't run as a service / can't be
easily containerized.

**Ignore prior art entirely** — eval only against FRC's published
schedules without any other comparison source. Partially
acceptable but underuses what's available: where a user supplies
their own externally-generated schedule for comparison (which the
licensing brief explicitly permits), accepting that input adds
value without legal exposure.

## Consequences

**Good:**
- Eval framings are diagnostic, not adversarial. "Published FRC
  schedules at this size hit station_spread=0 on 10/13 fixtures,
  we hit ≥2 on every fixture — let's understand why."
- Documentation credits prior art generically (the technique, the
  algorithmic ideas, the FRC schedule corpus) without putting any
  specific external tool's brand name in user-facing copy.
- The project has clear cultural permission to use established
  approaches where they work, without trying to invent new ones
  for the sake of difference.
- When we improve on prior art on a metric, the framing is "we
  found a useful improvement over the prior art" rather than "we
  beat $TOOL."
- Reduced exposure on comparative-claim accuracy. Generic
  framings ("published FRC schedules at this size show...") are
  empirically grounded statements rather than head-to-head
  product claims.

**Bad:**
- Some users may expect a competitor framing and read the
  measured tone as underconfidence. Mitigation: the README and
  eval findings speak plainly about both strengths and gaps,
  grounded in measured comparison.
- We can't say "we replaced $TOOL" because that's not what we're
  doing. (This is good in fact, but reads as a limitation if you
  came expecting the other framing.)

## References

- `docs/scheduler/REFERENCE_SCHEDULER_LICENSING.md` — the legal and
  licensing analysis.
- `docs/scheduler/REFERENCE_SCHEDULER_ALIGNMENT.md` — historical
  context for which behaviors of established FRC schedulers we
  deliberately match vs deliberately diverge from.
- `app/post_passes/station_balance.py` — header comment crediting
  the technique and noting the independent implementation.
- `scripts/scheduler_eval/adapters/` — multiple adapters compared
  on equal footing.
