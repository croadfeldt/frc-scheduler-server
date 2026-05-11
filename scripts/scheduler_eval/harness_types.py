"""Core data structures for the scheduler evaluation harness.

This module defines three things:

  - Fixture: the input description of an event (team list, match counts,
    surrogate config, day structure). Loaded from JSON; the same fixture
    is fed to every adapter so we can compare outputs apples-to-apples.

  - Match: a single qualification match with red/blue alliances and
    surrogate flags. Driver-station position is encoded by list index
    within each alliance (0 = station 1, 1 = station 2, 2 = station 3).

  - Schedule: a sequence of Matches, plus metadata about which adapter
    produced it and any per-tool diagnostics.

Practice matches are deliberately NOT included in the Schedule. The
metrics that matter (repeat partners, color balance, station spread,
gap, etc.) only consider qualification matches. Practice matches don't
count toward team standing and have different scheduling rules.

Surrogate matches DO count for team appearance but DON'T count toward
repeat-partner / repeat-opponent statistics — a surrogate is a team
filling in for capacity, not playing competitively. We track the flag
but exclude surrogate slots from those specific metrics.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


# ── Fixture ─────────────────────────────────────────────────────────────


@dataclass
class Fixture:
    """An event configuration that can be fed to any scheduling adapter.

    Fields are deliberately minimal. Things like venue name, dates, and
    branding are out of scope — this is purely the input to scheduling
    algorithms, not a UI-facing event description.

    `surrogate_first_match` is the match number (1-indexed) where the
    first surrogate appearance occurs in the actual played schedule.
    Descriptive only — the harness DOES NOT pass this to the reference scheduler as
    a `-u` round flag (that was a previous bug). the reference scheduler handles
    surrogate placement itself, defaulting to round 3 since 2008
    per FIRST's convention.

    `surrogate_count` is the total number of surrogate slot-fills in
    the actual played schedule. Per the upstream tool's authors's white paper, this is
    at most 5 for FRC events.

    Both surrogate fields are descriptive metadata about the actual
    schedule we pulled from TBA, not configuration for the schedulers
    we're evaluating.

    `breaks` is a list of break specifications using the reference scheduler's -k
    syntax conceptually — match number after which to insert a break.
    Used for lunch breaks in multi-block days.
    """
    fixture_id:        str             # stable ID used in filenames and reports
    name:              str             # human-readable label for reports
    teams:             list[int]       # team numbers — order doesn't matter
    matches_per_team:  int             # qual matches each team plays
    teams_per_alliance: int = 3        # FRC standard is 3; configurable for non-FIRST

    # Surrogate metadata describes the played schedule (descriptive),
    # NOT a configuration knob for schedulers (they handle this themselves)
    surrogate_first_match: int | None = None  # 1-indexed match number
    surrogate_count:       int = 0            # total slot-fills (≤5 per FRC convention)

    # Optional metadata — useful for fixture provenance and reports
    source:            str = "synthetic"   # 'tba', 'mnhsl', 'synthetic', 'live'
    year:              int | None = None
    event_key:         str | None = None   # TBA event key if applicable
    notes:             str = ""

    @property
    def num_teams(self) -> int:
        return len(self.teams)

    @property
    def total_matches(self) -> int:
        """Number of qualification matches the schedule should produce.

        Each match has 2 alliances × teams_per_alliance team-slots, and
        each team plays matches_per_team times, so:

            total_team_slots = num_teams × matches_per_team
            total_matches    = total_team_slots / (2 × teams_per_alliance)

        This must come out to an integer. If it doesn't, the fixture is
        unschedulable as-stated and a surrogate round can balance it.
        """
        slots_per_match = 2 * self.teams_per_alliance
        total_slots = self.num_teams * self.matches_per_team
        return total_slots // slots_per_match

    @property
    def needs_surrogate(self) -> bool:
        slots_per_match = 2 * self.teams_per_alliance
        total_slots = self.num_teams * self.matches_per_team
        return (total_slots % slots_per_match) != 0

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> Fixture:
        # Backward compat: older fixtures used `surrogate_round` (which
        # was always populated with a match number despite the name) —
        # accept it under the new name. The semantic content is the
        # same; only the label was wrong before.
        if "surrogate_round" in data and "surrogate_first_match" not in data:
            data = dict(data)
            data["surrogate_first_match"] = data.pop("surrogate_round")
        return cls(**data)

    @classmethod
    def load(cls, path: str | Path) -> Fixture:
        with open(path) as f:
            return cls.from_json_dict(json.load(f))

    def save(self, path: str | Path) -> None:
        with open(path, "w") as f:
            json.dump(self.to_json_dict(), f, indent=2)


# ── Match ───────────────────────────────────────────────────────────────


@dataclass
class Match:
    """A single qualification match.

    Alliances are lists indexed by driver-station position.
    blue[0] is blue station 1, blue[1] is blue station 2, etc.

    Surrogate flags mark teams who are filling in for capacity reasons
    — their participation in this match doesn't count toward repeat
    statistics. blue_surrogate[i] corresponds to blue[i].
    """
    match_num:       int          # 1-indexed within the schedule
    blue:            list[int]    # team numbers, length = teams_per_alliance
    red:             list[int]
    blue_surrogate:  list[bool] = field(default_factory=list)
    red_surrogate:   list[bool] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Default surrogate flags to all False if not provided
        if not self.blue_surrogate:
            self.blue_surrogate = [False] * len(self.blue)
        if not self.red_surrogate:
            self.red_surrogate = [False] * len(self.red)
        if len(self.blue) != len(self.red):
            raise ValueError(
                f"match {self.match_num}: blue alliance has {len(self.blue)} "
                f"teams, red has {len(self.red)}"
            )
        if len(self.blue_surrogate) != len(self.blue):
            raise ValueError(
                f"match {self.match_num}: blue_surrogate length mismatch"
            )
        if len(self.red_surrogate) != len(self.red):
            raise ValueError(
                f"match {self.match_num}: red_surrogate length mismatch"
            )

    @property
    def all_teams(self) -> list[int]:
        """Every team in the match, blue first then red."""
        return self.blue + self.red

    def alliance_of(self, team: int) -> str | None:
        """Returns 'blue', 'red', or None if team isn't in this match."""
        if team in self.blue:
            return "blue"
        if team in self.red:
            return "red"
        return None

    def position_of(self, team: int) -> int | None:
        """Driver-station position (1-indexed) of `team`, or None."""
        if team in self.blue:
            return self.blue.index(team) + 1
        if team in self.red:
            return self.red.index(team) + 1
        return None

    def is_surrogate(self, team: int) -> bool:
        if team in self.blue:
            return self.blue_surrogate[self.blue.index(team)]
        if team in self.red:
            return self.red_surrogate[self.red.index(team)]
        return False


# ── Schedule ────────────────────────────────────────────────────────────


@dataclass
class Schedule:
    """A scheduling adapter's output for a fixture.

    The adapter that produced it is recorded in `adapter_name`, which
    is also used in report headers. Generation diagnostics (time taken,
    iterations, internal score, anything else the adapter wants to
    preserve) live in `adapter_diagnostics`.

    The fixture this schedule was generated for is referenced by
    fixture_id (not embedded directly) so schedules can be saved
    standalone without duplicating fixture data. Reports look up the
    fixture by ID when they need it.
    """
    fixture_id:          str
    adapter_name:        str          # 'matchmaker', 'frc-scheduler-server', 'cp-sat', 'actual'
    matches:             list[Match]

    # Diagnostics — every adapter populates these
    generation_seconds:  float = 0.0
    seed:                int | None = None    # for stochastic adapters
    adapter_diagnostics: dict[str, Any] = field(default_factory=dict)

    # When the adapter ran; useful for distinguishing reruns
    generated_at:        str = ""

    @property
    def num_matches(self) -> int:
        return len(self.matches)

    def teams_in_match(self, match_num: int) -> list[int]:
        """Convenience: all teams playing in match N (1-indexed)."""
        for m in self.matches:
            if m.match_num == match_num:
                return m.all_teams
        return []

    def matches_for_team(self, team: int) -> list[Match]:
        """All matches in which `team` plays (in match_num order)."""
        return [m for m in self.matches if team in m.all_teams]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "fixture_id":          self.fixture_id,
            "adapter_name":        self.adapter_name,
            "matches": [
                {
                    "match_num":      m.match_num,
                    "blue":           m.blue,
                    "red":            m.red,
                    "blue_surrogate": m.blue_surrogate,
                    "red_surrogate":  m.red_surrogate,
                }
                for m in self.matches
            ],
            "generation_seconds":  self.generation_seconds,
            "seed":                self.seed,
            "adapter_diagnostics": self.adapter_diagnostics,
            "generated_at":        self.generated_at,
        }

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> Schedule:
        matches = [Match(**m) for m in data["matches"]]
        return cls(
            fixture_id=data["fixture_id"],
            adapter_name=data["adapter_name"],
            matches=matches,
            generation_seconds=data.get("generation_seconds", 0.0),
            seed=data.get("seed"),
            adapter_diagnostics=data.get("adapter_diagnostics", {}),
            generated_at=data.get("generated_at", ""),
        )

    def save(self, path: str | Path) -> None:
        with open(path, "w") as f:
            json.dump(self.to_json_dict(), f, indent=2)

    @classmethod
    def load(cls, path: str | Path) -> Schedule:
        with open(path) as f:
            return cls.from_json_dict(json.load(f))
