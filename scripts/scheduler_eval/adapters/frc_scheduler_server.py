"""Adapter wrapping our in-house scheduler (app/scheduler.py).

Wraps the two-stage generator:
  1. generate_matches() — produces "match shape" (which slot plays which)
  2. assign_teams()     — maps slot indices to real team numbers

For best-of-N runs, we generate N candidates with different seeds and
return them. The harness's runner is responsible for keeping all N or
picking the best by score; the adapter doesn't pre-filter.

Configuration:
  - ideal_gap: minimum desired gap between a team's matches. Default 3,
    which is what the production code uses. Pass 4 to test the
    "hard cooldown" hypothesis from the scheduler quality roadmap.
  - assignment_iterations: number of inner iterations for stage 2.
    Higher = better assignment, slower. 100 is the production default.
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

from app.scheduler import generate_matches, assign_teams

from .base import Adapter
from ..harness_types import Fixture, Match, Schedule


class FrcSchedulerServerAdapter(Adapter):
    """Wraps app/scheduler.py for the harness."""

    name = "frc-scheduler-server"

    def __init__(self,
                 ideal_gap: int = 3,
                 assignment_iterations: int = 100,
                 weights: dict | None = None):
        self.ideal_gap = ideal_gap
        self.assignment_iterations = assignment_iterations
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

        # Stage 1: abstract slot-vs-slot match shape
        stage1 = generate_matches(
            num_teams=fixture.num_teams,
            matches_per_team=fixture.matches_per_team,
            ideal_gap=self.ideal_gap,
            seed=actual_seed,
            weights=self.weights,
        )

        # Convert NamedTuple matches into the dict shape assign_teams expects
        abstract_matches = [
            {
                "red":            list(m.red),
                "blue":           list(m.blue),
                "red_surrogate":  list(m.red_surrogate),
                "blue_surrogate": list(m.blue_surrogate),
            }
            for m in stage1.matches
        ]

        # Stage 2: assign actual team numbers to slots
        assignment = assign_teams(
            abstract_matches=abstract_matches,
            num_teams=fixture.num_teams,
            team_numbers=fixture.teams,
            ideal_gap=self.ideal_gap,
            n_iterations=self.assignment_iterations,
            seed=actual_seed,
        )
        # assign_teams returns slot_map with STRING keys ({str(k): v}).
        # Stage 1's match data uses integer slot indices, so we need to
        # bridge the type. Without this, slot_map.get(s, s) silently
        # falls back to the slot index and produces a Schedule with
        # placeholder integers (1..N) instead of real team numbers —
        # invisible until the metrics surface team numbers, at which
        # point burden analysis shows "team 28" instead of "team 2052".
        raw_slot_map = assignment.get("slot_map") or {}
        slot_map: dict[int, int] = {}
        for k, v in raw_slot_map.items():
            try:
                slot_map[int(k)] = int(v)
            except (TypeError, ValueError):
                pass

        # Defensive check: if the slot map is empty or doesn't cover
        # every slot in the schedule, the schedule is unusable for
        # downstream comparison. Fail loudly rather than silently
        # emit slot indices.
        all_slots = set()
        for am in abstract_matches:
            all_slots.update(am["red"])
            all_slots.update(am["blue"])
        missing_slots = all_slots - set(slot_map.keys())
        if missing_slots:
            raise RuntimeError(
                f"frc-scheduler-server: assign_teams did not produce a "
                f"slot_map covering every slot. Missing: "
                f"{sorted(missing_slots)[:10]}{'...' if len(missing_slots) > 10 else ''}. "
                f"Stage 2 likely failed; stage 2 score was "
                f"{assignment.get('score')}."
            )

        elapsed = time.monotonic() - t0

        # Build harness Match objects from the assignment result
        matches = []
        for i, am in enumerate(abstract_matches, start=1):
            red_teams  = [slot_map[s] for s in am["red"]]
            blue_teams = [slot_map[s] for s in am["blue"]]
            matches.append(Match(
                match_num=i,
                blue=blue_teams,
                red=red_teams,
                blue_surrogate=list(am["blue_surrogate"]),
                red_surrogate=list(am["red_surrogate"]),
            ))

        return Schedule(
            fixture_id=fixture.fixture_id,
            adapter_name=self.name,
            matches=matches,
            generation_seconds=elapsed,
            seed=actual_seed,
            adapter_diagnostics={
                "stage1_score":           stage1.score,
                "stage1_surrogate_count": list(stage1.surrogate_count),
                "stage2_score":           assignment.get("score"),
                "stage2_iterations":      self.assignment_iterations,
                "ideal_gap":              self.ideal_gap,
                "weights":                self.weights or "default",
                "trial":                  trial,
            },
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
