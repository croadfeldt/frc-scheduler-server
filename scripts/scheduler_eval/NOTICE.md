# Scheduler Eval Harness — Third-Party Software Notice

This harness compares scheduling algorithms by computing diversity metrics
on schedules from multiple sources. Some sources are third-party software
with licensing terms that govern how they may be used. This notice
documents the project's posture toward those terms.

## Idle Loop's MatchMaker

The harness includes an adapter (`adapters/matchmaker.py`) that invokes
Idle Loop Software Design's MatchMaker binary as a subprocess to
generate schedules for comparison.

**Licensing facts (as published at https://idleloop.com/matchmaker/download.php):**

> "These programs are available for evaluation purposes only.
> For licensing, contact us at info@idleloop.com."

> "©2000-2026 Idle Loop Software Design, LLC. You may not copy or
> reproduce any content from this site without our consent."

**What this harness does:**

- Wraps a `matchmaker` binary that the user has separately installed on
  their own machine, under their own evaluation license with Idle Loop.
- Invokes it via `subprocess` to capture a schedule, then parses the
  output to compute diversity metrics for comparison purposes.
- Documents the CLI flags and output format empirically observed,
  derived from Idle Loop's published release notes and the binary's
  own behavior, for interoperability.

**What this harness does not do:**

- Bundle, redistribute, or auto-download the MatchMaker binary.
- Include any MatchMaker source code, decompiled output, or other
  proprietary IP from Idle Loop.
- Run MatchMaker as part of the shipped `frc-scheduler-server` product.
  The harness lives in `scripts/scheduler_eval/` and is a developer
  tool for evaluation only — it is not invoked by the running app
  and is not part of any production code path.

**Operational guidance:**

- Use of MatchMaker via this harness is appropriate for personal,
  local evaluation — the same activity the binary's evaluation license
  is designed to permit.
- Do not run the matchmaker adapter in CI, in hosted services, or in
  any context that goes beyond a single evaluator running a single
  binary on their own machine.
- For ongoing scheduler validation (regression detection, quality
  tracking over time), prefer the `actual` adapter, which compares
  against publicly-available FRC event schedules from The Blue
  Alliance. TBA data is public record; it requires no MatchMaker
  invocation.

**Crediting the algorithm authors:**

Tom and Cathy Saxton (Idle Loop Software Design, LLC) developed the
simulated annealing approach for FRC qualification scheduling
described in their published white paper at
https://idleloop.com/matchmaker/index.php.

Caleb Sykes developed the station-balancing algorithm added to
MatchMaker version 1.4 (December 2021), described at
https://idleloop.com/matchmaker/stations.php.

Any independent reimplementation of these published algorithms in
this project's `app/scheduler.py` credits these authors in the
algorithm suite documentation. The algorithms themselves (described
in published prose) are separate from the closed-source MatchMaker
binary and may be independently implemented; only the binary,
source code, and Idle Loop's published page content are bound by
the evaluation-only license.

## The Blue Alliance

The harness fetches qualification schedules from The Blue Alliance
(https://www.thebluealliance.com/) via their public API. TBA data is
public record; the API has its own terms of service which the user
is responsible for following (in particular: requesting a TBA API key
and identifying the requesting client). The fetcher in
`pull_tba_fixtures.py` reuses the existing `app/tba.py` client which
sets the appropriate headers.

---

Questions about this posture should be directed to the project owner.
This notice is informational and does not constitute legal advice.
