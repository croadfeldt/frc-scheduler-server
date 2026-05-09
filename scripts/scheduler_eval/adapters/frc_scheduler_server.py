# SPDX-License-Identifier: GPL-3.0-or-later
# FRC Match Scheduler
# Copyright (C) 2025 FRC Match Scheduler Contributors
"""Adapter wrapping our in-house scheduler (app/scheduler.py).

Phase 0 (2026): the adapter now uses the unified placement function
``generate_matches(team_numbers=..., n_sa_iterations=...)``. The legacy
``assign_teams`` step has been removed; team identity and SA optimization
both happen inside ``generate_matches``.

Configuration:
  - ideal_gap: minimum desired gap between a team's matches. Default 3.
  - sa_iterations: number of SA optimization iterations applied to the
    construction-phase output. 0 = construction only (legacy behavior);
    higher = better quality at higher wall-clock cost.
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

from .base import Adapter
from ..harness_types import Fixture, Match, Schedule


class FrcSchedulerServerAdapter(Adapter):
    """Wraps app/scheduler.py for the harness."""

    name = "frc-scheduler-server"

    def __init__(self,
                 ideal_gap: int = 3,
                 sa_iterations: int = 0,
                 weights: dict | None = None,
                 # Backwards compat with old kwarg name. Previously this was
                 # the slot-based SA budget; now it's the new SA budget.
                 assignment_iterations: int | None = None):
        self.ideal_gap = ideal_gap
        if assignment_iterations is not None:
            self.sa_iterations = assignment_iterations
        else:
            self.sa_iterations = sa_iterations
        self.weights = weights

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

        t0 = time.monotonic()

        # Phase 0 unified call: real teams from the start, SA optimization
        # baked in. No separate Stage-1/Stage-2 split.
        result = generate_matches(
            num_teams=fixture.num_teams,
            matches_per_team=fixture.matches_per_team,
            ideal_gap=self.ideal_gap,
            seed=actual_seed,
            weights=self.weights,
            team_numbers=list(fixture.teams),
            n_sa_iterations=self.sa_iterations,
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
                "ideal_gap":       self.ideal_gap,
                "weights":         self.weights or "default",
                "trial":           trial,
            },
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
