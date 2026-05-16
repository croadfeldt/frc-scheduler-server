# SPDX-License-Identifier: GPL-3.0-or-later
"""Test that all Nexus field-level status strings map to internal codes.

This is a focused unit test on app/live.py:_NEXUS_STATUS_MAP. The
mapping table had a regression: it omitted the "Queuing soon" entry,
which caused Nexus's earliest-warning state to be silently dropped
by _process_nexus_match_status (via the `if not status: skip` branch).

Symptom: matches that were queued in Nexus didn't show up as
'Queueing' in the view page's 3-up. Fixed by adding all 5 documented
Nexus states, with both US (queuing) and UK (queueing) spellings
for the two states where Nexus's own examples vary.

Reference: https://frc.nexus/en/api — match status values:
  Queuing soon | Now queuing | On deck | On field | Completed
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Import the map directly. We test it as a pure data structure rather
# than going through _process_nexus_match_status, which requires a DB.
from app.live import _NEXUS_STATUS_MAP  # noqa: E402


# ── Test runner ──────────────────────────────────────────────────

_failures = 0


def check(name, cond, detail=""):
    global _failures
    if cond:
        print(f"  ✓ {name}")
    else:
        _failures += 1
        print(f"  ✗ {name}: {detail}")


# ── Tests ────────────────────────────────────────────────────────

print("Status string coverage (per Nexus API docs):")

# Each Nexus-documented status must map to a known internal code.
# The internal codes must match what the client-side view code
# reads (see static/view.html: queueing_soon | now_queueing |
# on_deck | on_field | completed).
expected_states = {
    "queueing_soon",
    "now_queueing",
    "on_deck",
    "on_field",
    "completed",
}

# Documented Nexus strings (case-folded — the map's lookups
# casefold the input before comparing).
nexus_inputs = [
    # All five documented states (US spelling — Nexus default)
    ("queuing soon", "queueing_soon"),
    ("now queuing",  "now_queueing"),
    ("on deck",      "on_deck"),
    ("on field",     "on_field"),
    ("completed",    "completed"),
    # UK spelling variants — Nexus payloads occasionally mix these
    ("queueing soon", "queueing_soon"),
    ("now queueing",  "now_queueing"),
]

for nexus_input, expected in nexus_inputs:
    actual = _NEXUS_STATUS_MAP.get(nexus_input)
    check(
        f"Nexus {nexus_input!r:20s} → {expected!r}",
        actual == expected,
        f"got: {actual!r}",
    )


print("\nAll documented internal codes are reachable:")
mapped_codes = set(_NEXUS_STATUS_MAP.values())
for code in expected_states:
    check(
        f"internal code {code!r} appears in the map's values",
        code in mapped_codes,
        f"map values: {sorted(mapped_codes)}",
    )


print("\nUnknown statuses fall through cleanly:")
# The actual lookup uses _NEXUS_STATUS_MAP.get(input.lower(), ""),
# so unknown strings return "" by convention. Verify that no real
# Nexus state we'd want to handle maps to "" by accident.
for bogus in ["bogus", "unknown", "random text", ""]:
    check(
        f"unknown {bogus!r:15s} → not in map",
        _NEXUS_STATUS_MAP.get(bogus) is None,
        f"unexpectedly mapped to {_NEXUS_STATUS_MAP.get(bogus)!r}",
    )


print()
if _failures > 0:
    print(f"{_failures} failure(s).")
    sys.exit(1)
print("All Nexus status-mapping tests passed.")
