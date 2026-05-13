# SPDX-License-Identifier: GPL-3.0-or-later
# FRC Match Scheduler
# Copyright (C) 2025 FRC Match Scheduler Contributors
"""Canonical schedule library — JSON-file-backed lookup of pre-computed
best-known schedules for common FRC fixture shapes.

This is Phase B of the Schedule Quality Framework. The library serves
schedules that have been produced by deep search (CP-SAT to optimality,
SA-best-of-N for shapes where CP-SAT can't terminate). When an organizer
requests a schedule for a covered shape, they get the canonical
instead of waiting for the SA. Quality is deterministic per shape.

Storage: JSON files in `app/canonical_schedules/`, one per shape.
Naming: `{n}x{mpt}x{tpa}_cd{cooldown}.json`.

Future migration: this module is the prototype/seed for the
`abstract-library.md` workstream's DB-backed library. The JSON
schema here is designed to map cleanly onto the future table.

See `docs/scheduler/canonical-library.md` for the file format and
producer methodology.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ── Constants ────────────────────────────────────────────────────────────


# Where the canonical JSON files live. Override via env var for tests
# that want a temp directory.
CANONICAL_DIR = Path(os.environ.get(
    "CANONICAL_SCHEDULES_DIR",
    str(Path(__file__).resolve().parent / "canonical_schedules"),
))

# Schedule-entry confidence vocabulary. Distinguishes "schedule was
# proven optimal by an exhaustive solver" from "schedule was the best
# found in a defined search budget" from "schedule matches the
# theoretical floor on this metric (so even if we can't prove
# optimality by exhaustion, we know it's mathematically as good as
# the lower bound permits)".
SCHEDULE_CONFIDENCE_PROVEN_OPTIMAL    = 'proven_optimal'
SCHEDULE_CONFIDENCE_MATCHES_FLOOR     = 'matches_floor'
SCHEDULE_CONFIDENCE_BEST_KNOWN        = 'best_known'


# ── Filename helpers ────────────────────────────────────────────────────


def canonical_filename(n_teams: int, matches_per_team: int,
                       teams_per_alliance: int, cooldown: int) -> str:
    """Canonical JSON filename for a fixture shape.

    Example: canonical_filename(36, 7, 3, 2) → '36x7x3_cd2.json'
    """
    return (f"{n_teams}x{matches_per_team}x{teams_per_alliance}"
            f"_cd{cooldown}.json")


def canonical_path(n_teams: int, matches_per_team: int,
                    teams_per_alliance: int, cooldown: int,
                    base_dir: Path | None = None) -> Path:
    """Full path to the canonical JSON file for a fixture shape."""
    base = base_dir if base_dir is not None else CANONICAL_DIR
    return base / canonical_filename(n_teams, matches_per_team,
                                      teams_per_alliance, cooldown)


# ── Loader ───────────────────────────────────────────────────────────────


@dataclass
class CanonicalEntry:
    """In-memory canonical-library entry.

    Mirrors the JSON file format. Built by the producer
    (`scripts/scheduler_eval/build_canonical.py`) and consumed by the
    API endpoint (`POST /api/schedules`).
    """
    # Fixture shape
    n_teams:            int
    matches_per_team:   int
    teams_per_alliance: int
    cooldown:           int

    # Schedule-entry confidence ('proven_optimal' / 'matches_floor' /
    # 'best_known'). See SCHEDULE_CONFIDENCE_* constants.
    confidence:         str

    # The schedule itself as a list of match dicts:
    #   {red: [int, int, int],
    #    blue: [int, int, int],
    #    red_surrogate: [bool, bool, bool],
    #    blue_surrogate: [bool, bool, bool]}
    matches:            list[dict[str, Any]]

    # Achieved lex tuple (8 elements per app.scheduler._score_from_state)
    achieved_lex_tuple: list[int | float]

    # Quality report (computed at production time, embedded with the
    # canonical so consumers don't have to recompute). Shape matches
    # build_quality_report() output in app/quality_report.py.
    quality_report:     dict[str, Any]

    # Provenance: how the canonical was produced.
    provenance:         dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            'n_teams':            self.n_teams,
            'matches_per_team':   self.matches_per_team,
            'teams_per_alliance': self.teams_per_alliance,
            'cooldown':           self.cooldown,
            'confidence':         self.confidence,
            'matches':            self.matches,
            'achieved_lex_tuple': self.achieved_lex_tuple,
            'quality_report':     self.quality_report,
            'provenance':         self.provenance,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> 'CanonicalEntry':
        return cls(
            n_teams            = d['n_teams'],
            matches_per_team   = d['matches_per_team'],
            teams_per_alliance = d.get('teams_per_alliance', 3),
            cooldown           = d['cooldown'],
            confidence         = d['confidence'],
            matches            = d['matches'],
            achieved_lex_tuple = d['achieved_lex_tuple'],
            quality_report     = d['quality_report'],
            provenance         = d.get('provenance', {}),
        )


def load_canonical(n_teams: int, matches_per_team: int,
                    teams_per_alliance: int = 3, cooldown: int = 2,
                    base_dir: Path | None = None) -> CanonicalEntry | None:
    """Look up a canonical schedule by fixture shape.

    Returns the CanonicalEntry if a JSON file exists, or None if no
    canonical is available for this shape. The caller (typically the
    new /api/schedules endpoint) handles cache-miss by falling through
    to generation.
    """
    path = canonical_path(n_teams, matches_per_team, teams_per_alliance,
                          cooldown, base_dir=base_dir)
    if not path.exists():
        return None
    try:
        with path.open('r') as f:
            data = json.load(f)
        return CanonicalEntry.from_dict(data)
    except (OSError, json.JSONDecodeError, KeyError) as e:
        # Malformed canonical files shouldn't break the API. Log and
        # treat as cache-miss; the producer will regenerate next time.
        import logging
        logging.getLogger(__name__).warning(
            "Canonical file at %s is malformed: %s. Treating as cache-miss.",
            path, e,
        )
        return None


def save_canonical(entry: CanonicalEntry,
                   base_dir: Path | None = None) -> Path:
    """Write a CanonicalEntry to disk. Returns the path written.

    Producer uses this. The endpoint never writes — it only reads.
    """
    base = base_dir if base_dir is not None else CANONICAL_DIR
    base.mkdir(parents=True, exist_ok=True)
    path = canonical_path(entry.n_teams, entry.matches_per_team,
                          entry.teams_per_alliance, entry.cooldown,
                          base_dir=base)
    with path.open('w') as f:
        json.dump(entry.to_dict(), f, indent=2, default=str)
    return path


def list_canonicals(base_dir: Path | None = None) -> list[CanonicalEntry]:
    """Enumerate all canonicals in the library. Used by tooling and
    by the /api/schedules/canonicals listing endpoint.
    """
    base = base_dir if base_dir is not None else CANONICAL_DIR
    if not base.exists():
        return []
    entries: list[CanonicalEntry] = []
    for path in sorted(base.glob('*.json')):
        try:
            with path.open('r') as f:
                data = json.load(f)
            entries.append(CanonicalEntry.from_dict(data))
        except (OSError, json.JSONDecodeError, KeyError):
            continue  # skip malformed
    return entries


__all__ = [
    'CANONICAL_DIR',
    'SCHEDULE_CONFIDENCE_PROVEN_OPTIMAL',
    'SCHEDULE_CONFIDENCE_MATCHES_FLOOR',
    'SCHEDULE_CONFIDENCE_BEST_KNOWN',
    'CanonicalEntry',
    'canonical_filename',
    'canonical_path',
    'load_canonical',
    'save_canonical',
    'list_canonicals',
]
