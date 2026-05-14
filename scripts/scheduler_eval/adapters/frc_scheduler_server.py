# SPDX-License-Identifier: GPL-3.0-or-later
# FRC Match Scheduler
# Copyright (C) 2025 FRC Match Scheduler Contributors
"""Adapter wrapping our in-house scheduler (app/scheduler.py).

Phase 0 (2026): the adapter uses the unified placement function
``generate_matches(team_numbers=..., n_sa_iterations=...)``. The legacy
``assign_teams`` step has been removed; team identity and SA optimization
both happen inside ``generate_matches``.

History note (2026-05-10): the prior adapter default was
``sa_iterations=0``, which silently disabled the SA optimization pass
in every harness run. That made the eval measure construction +
post-passes only, NOT the algorithm production users actually get.
The default has been bumped to match the UI's default preset
(``app.quality_presets.DEFAULT_PRESET``, currently ``good`` = 500K
iterations). Eval runs that want a different preset can pass
``sa_iterations=N`` directly or use the runner's ``--sa-iterations`` /
``--quality-preset`` CLI flags.

Configuration:
  - ideal_gap: minimum desired gap between a team's matches. Default 3.
  - sa_iterations: number of SA optimization iterations applied to the
    construction-phase output. Defaults to the UI's default preset
    (500K). 0 explicitly opts out (construction + post-passes only).
    Higher = better quality at higher wall-clock cost. See
    ``app/quality_presets.py`` for production levels.
  - weights: per-objective weight overrides. Passing None uses
    DEFAULT_WEIGHTS. Useful for tuning experiments.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
import sys

# Make app/ importable when running from the repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.scheduler import generate_matches
from app.quality_floors import fixture_floors
from app.quality_presets import (
    DEFAULT_PRESET,
    iterations_for_preset,
)

from .base import Adapter
from ..harness_types import Fixture, Match, Schedule


# Module-level constant — exposed so tests can pin the default and so
# the runner's report can record exactly which preset/iteration count
# the eval used. If the UI's DEFAULT_PRESET shifts, this follows.
DEFAULT_SA_ITERATIONS = iterations_for_preset(DEFAULT_PRESET)

# Default CP-SAT post-pass budget for eval runs. Matches the "Thorough"
# UI preset — long enough to reach OPTIMAL on station for the standards
# inventory, comfortable on larger fixtures up to ~80t. Set to 0 to opt
# out (legacy SA-only behavior). The eval composite is dragged hard
# when station_spread > 1, so the budget is worth the cost.
DEFAULT_CPSAT_BUDGET_S = 120.0


# Cached probe — only check the first time, and only inside a function
# so the import-time cost is zero. importlib.util.find_spec returns None
# when the package isn't installed and a ModuleSpec when it is; no
# actual import side-effect.
_ORTOOLS_PROBED: bool | None = None


def _ortools_available() -> bool:
    """Return True if `ortools` (used by the CP-SAT post-pass) can be
    imported. Cached so subsequent calls are O(1).

    The eval may run on machines (CI, lightweight dev containers)
    without ortools installed. Without this probe, the first call to
    generate_matches with a positive CP-SAT budget would raise
    ModuleNotFoundError inside the worker process, breaking the run.
    """
    global _ORTOOLS_PROBED
    if _ORTOOLS_PROBED is None:
        import importlib.util
        _ORTOOLS_PROBED = importlib.util.find_spec("ortools") is not None
    return _ORTOOLS_PROBED


class FrcSchedulerServerAdapter(Adapter):
    """Wraps app/scheduler.py for the harness."""

    name = "frc-scheduler-server"

    def __init__(self,
                 ideal_gap: int | None = None,
                 sa_iterations: int | None = None,
                 weights: dict | None = None,
                 cpsat_post_pass_budget_s: float | None = None,
                 # Backwards compat with old kwarg name. Previously this was
                 # the slot-based SA budget; now it's the new SA budget.
                 assignment_iterations: int | None = None):
        # ideal_gap: None (default) means "compute the maximum feasible
        # gap per fixture, matching MatchMaker's behavior of using the
        # tightest spacing the fixture supports." Pass an int to override
        # (e.g., for testing the legacy behavior at gap=3, or for fixtures
        # where the FRC §10.6.6 small-event exception applies).
        #
        # History: through 2026-05-13 the default was a hardcoded 3,
        # which left 2-4 gap-units on the table for typical MN regional
        # fixtures (cooldown_max=5..7 at 51-61 teams × 9 MPT). MatchMaker
        # auto-computes the max feasible gap; bug A diagnosis exposed
        # this as the largest single contributor to the eval composite
        # gap (10+ composite points on each of three fixtures).
        self.ideal_gap_override = ideal_gap

        # Resolution order: explicit kwarg wins, then legacy alias, then
        # the UI's default preset. None (the new default) means "use the
        # UI default"; pass an explicit 0 to opt out of SA entirely.
        if assignment_iterations is not None:
            self.sa_iterations = assignment_iterations
        elif sa_iterations is not None:
            self.sa_iterations = sa_iterations
        else:
            self.sa_iterations = DEFAULT_SA_ITERATIONS
        self.weights = weights
        # CP-SAT exact post-pass budget. Defaults to a "thorough" 120s
        # which matches the UI's recommended budget for fixtures with
        # surrogate-required shapes (30+ teams). Opt-out: pass 0.
        #
        # Defensive: check whether ortools is actually installed in this
        # Python environment. If not, the import inside generate_matches
        # would fail at runtime when budget > 0, producing
        # ModuleNotFoundError and breaking the eval. Detect at adapter
        # init and silently fall back to SA-only with a one-time warning.
        # This keeps the eval working on machines where ortools isn't
        # installed (CI, lightweight dev containers) while preserving
        # the CP-SAT improvements on machines where it is.
        if cpsat_post_pass_budget_s is None:
            requested_budget = DEFAULT_CPSAT_BUDGET_S
        else:
            requested_budget = float(cpsat_post_pass_budget_s)

        if requested_budget > 0 and not _ortools_available():
            import warnings
            warnings.warn(
                "frc-scheduler-server adapter: ortools not installed; "
                "falling back to SA-only post-pass. Install ortools "
                "(`pip install ortools`) to enable CP-SAT polish — "
                "expected ~10 composite-point improvement on 30+ team "
                "fixtures.",
                RuntimeWarning,
                stacklevel=2,
            )
            requested_budget = 0.0
        self.cpsat_post_pass_budget_s = requested_budget

    def _resolve_ideal_gap(self, fixture: Fixture) -> int:
        """Resolve ideal_gap for this fixture.

        If the caller provided an explicit override at construction time,
        use that. Otherwise compute a fixture-aware gap that the SA can
        reliably honor and that matches MatchMaker's behavior.

        Heuristic: `cooldown_max - 4`, with a floor of 1. The -4 buffer
        matches MatchMaker's empirical choice exactly on the three MN
        regional fixtures that motivated this fix:

          - 51×9 (M=77, cooldown_max=9 → ideal_gap=5, matches MM)
          - 55×9 (M=83, cooldown_max=10 → ideal_gap=6, matches MM)
          - 61×9 (M=92, cooldown_max=11 → ideal_gap=7, matches MM)

        The buffer is also empirically safe: smoke tests at higher
        gap values (cooldown_max - 2 and above) show the construction
        phase silently falling back to gap=1 on 55-61 team fixtures —
        a separate scheduler-quality bug. cooldown_max - 4 stays well
        below that threshold while still crossing the "near-optimal"
        threshold of gap ≥ 4 for all production-sized fixtures.

        Smaller fixtures (cooldown_max ≤ 4) just use cooldown_max
        directly — the FRC §10.6.6 small-event exception applies.
        """
        if self.ideal_gap_override is not None:
            return self.ideal_gap_override
        ff = fixture_floors(
            n_teams=fixture.num_teams,
            matches_per_team=fixture.matches_per_team,
            teams_per_alliance=fixture.teams_per_alliance,
            cooldown=2,  # placeholder; we read cooldown_max, not feasibility
        )
        cd_max = ff.cooldown_max
        if cd_max <= 4:
            return max(1, cd_max)
        return cd_max - 4

    def generate(self, fixture: Fixture, *, seed: int | None = None,
                 trial: int = 0) -> Schedule:
        if fixture.teams_per_alliance != 3:
            raise ValueError(
                f"frc-scheduler-server only supports 3v3 alliances; "
                f"fixture {fixture.fixture_id} requests "
                f"{fixture.teams_per_alliance}v{fixture.teams_per_alliance}"
            )

        # Derive a per-trial seed if the caller passed a base seed but
        # nothing trial-specific. Two trials with the same base seed
        # need different actual seeds or they produce identical output.
        actual_seed = seed
        if seed is not None and trial != 0:
            actual_seed = seed ^ (trial * 1_000_003)

        # Resolve fixture-aware parameters
        ideal_gap = self._resolve_ideal_gap(fixture)

        t0 = time.monotonic()

        # Phase 0 unified call: real teams from the start, SA optimization
        # baked in. No separate Stage-1/Stage-2 split.
        result = generate_matches(
            num_teams=fixture.num_teams,
            matches_per_team=fixture.matches_per_team,
            ideal_gap=ideal_gap,
            seed=actual_seed,
            weights=self.weights,
            team_numbers=list(fixture.teams),
            n_sa_iterations=self.sa_iterations,
            cpsat_post_pass_budget_s=self.cpsat_post_pass_budget_s,
        )

        elapsed = time.monotonic() - t0

        # Build harness Match objects from result.matches
        matches = []
        for i, m in enumerate(result.matches, start=1):
            matches.append(Match(
                match_num=i,
                blue=list(m.blue),
                red=list(m.red),
                blue_surrogate=list(m.blue_surrogate),
                red_surrogate=list(m.red_surrogate),
            ))

        return Schedule(
            fixture_id=fixture.fixture_id,
            adapter_name=self.name,
            matches=matches,
            generation_seconds=elapsed,
            seed=actual_seed,
            adapter_diagnostics={
                "score":           result.score,
                "sa_iterations":   self.sa_iterations,
                "ideal_gap":       ideal_gap,
                "ideal_gap_source": "fixture_floors.cooldown_max" if self.ideal_gap_override is None else f"override={self.ideal_gap_override}",
                "cpsat_post_pass_budget_s": self.cpsat_post_pass_budget_s,
                "cpsat_available": _ortools_available(),
                "weights":         self.weights or "default",
                "trial":           trial,
            },
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
