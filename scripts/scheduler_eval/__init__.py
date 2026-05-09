"""Scheduler evaluation harness.

Run from the repo root:

    python -m scripts.scheduler_eval.runner --fixtures all

See README.md in this directory for the full operator runbook.
"""

from .harness_types    import Fixture, Match, Schedule
from .metrics  import analyze, AnalysisReport, MetricResult, THRESHOLDS

__all__ = [
    "Fixture", "Match", "Schedule",
    "analyze", "AnalysisReport", "MetricResult", "THRESHOLDS",
]
