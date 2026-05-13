# SPDX-License-Identifier: GPL-3.0-or-later
"""Smoke test for the Phase D standing eval suite.

Runs a single fixture at a single seed with low iteration count to
verify the framework wires together correctly. The full standing
eval (scripts/scheduler_eval/standards.py) is the operational tool;
this test is just a sanity check that the framework works.

A passing smoke test does NOT imply that production scheduling
meets quality standards — for that, run the full standards.py
with realistic iteration counts (500K+).

Coverage:
  1. Config loads correctly
  2. INVENTORY is non-empty and well-formed
  3. get_bars() returns the expected shape
  4. run_one_seed() produces a quality report with scoring
  5. evaluate_fixture() returns the expected dict shape
  6. The full pipeline (config → eval → report) works end-to-end
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.scheduler_eval.standards_config import (  # noqa: E402
    INVENTORY,
    DEFAULT_BARS,
    PER_FIXTURE_OVERRIDES,
    get_bars,
)
from scripts.scheduler_eval.standards import (  # noqa: E402
    run_one_seed,
    evaluate_fixture,
    run_standards_eval,
)


_failures = 0


def check(name, cond, detail=""):
    global _failures
    if cond:
        print(f"  ✓ {name}")
    else:
        _failures += 1
        print(f"  ✗ {name}: {detail}")


# ── 1. Config loads ──────────────────────────────────────────────────


print("Config:")
check("INVENTORY non-empty", len(INVENTORY) > 0)
check("INVENTORY entries are 5-tuples",
      all(len(f) == 5 for f in INVENTORY))
check("INVENTORY shapes are sensible",
      all(f[0] >= 6 and f[1] >= 1 and f[2] >= 2 and f[3] >= 1 for f in INVENTORY))
check("INVENTORY has named fixtures",
      all(isinstance(f[4], str) and f[4] for f in INVENTORY))

# DEFAULT_BARS
check("DEFAULT_BARS has hard_requirements", "hard_requirements" in DEFAULT_BARS)
check("DEFAULT_BARS has soft_thresholds", "soft_thresholds" in DEFAULT_BARS)
check("DEFAULT_BARS.hard_requirements has is_valid_paramount",
      "is_valid_paramount" in DEFAULT_BARS["hard_requirements"])


# ── 2. get_bars dispatch ─────────────────────────────────────────────


print("\nget_bars:")
bars_default = get_bars("nonexistent_fixture_name")
check("get_bars on unknown returns DEFAULT_BARS-shaped",
      bars_default["hard_requirements"]["is_valid_paramount"]
      == DEFAULT_BARS["hard_requirements"]["is_valid_paramount"])
check("get_bars on unknown has empty notes",
      bars_default["notes"] == "")

# For a fixture with an override, the override should be reflected
if "12x6_cd2" in PER_FIXTURE_OVERRIDES:
    bars_12 = get_bars("12x6_cd2")
    check("get_bars on 12x6_cd2 picks up notes override",
          bars_12["notes"] != "")
    # Soft threshold should match override or default
    override_comp = PER_FIXTURE_OVERRIDES["12x6_cd2"].get(
        "soft_thresholds", {}).get("composite_min")
    if override_comp is not None:
        check("get_bars merges soft_thresholds override",
              bars_12["soft_thresholds"]["composite_min"] == override_comp)


# ── 3. run_one_seed produces a report ────────────────────────────────


print("\nrun_one_seed (using 12x6 at low iter for speed):")
result = run_one_seed(12, 6, 3, 2, seed=42, sa_iterations=10_000)
check("result has 'ok' field", "ok" in result)
if result.get("ok"):
    check("result has quality_report",
          "quality_report" in result and isinstance(result["quality_report"], dict))
    check("quality_report has scores",
          "scores" in result["quality_report"])
    check("quality_report scores has composite",
          isinstance(result["quality_report"]["scores"].get("composite"), (int, float)))
    check("quality_report has metrics dict",
          isinstance(result["quality_report"].get("metrics"), dict))
    check("wall_clock_s is numeric",
          isinstance(result.get("wall_clock_s"), (int, float)))
else:
    # Even if generation failed (low iter), the framework should report
    # the error cleanly
    check("on failure, has error field", "error" in result)
    print(f"     (generation failed at 10K iter — expected occasionally: {result.get('error')})")


# ── 4. evaluate_fixture returns expected shape ──────────────────────


print("\nevaluate_fixture (single seed, low iter):")
result = evaluate_fixture(12, 6, 3, 2, "12x6_cd2",
                           n_seeds=1, sa_iterations=10_000, verbose=False)
check("result has fixture name", result.get("fixture") == "12x6_cd2")
check("result has shape", result.get("shape") == (12, 6, 3, 2))
check("result has verdict", result.get("verdict") in ("pass", "warn", "fail"))
check("result has bars", isinstance(result.get("bars"), dict))
check("result has seed_results", isinstance(result.get("seed_results"), list))
check("seed_results has 1 entry", len(result.get("seed_results", [])) == 1)


# ── 5. Full pipeline ────────────────────────────────────────────────


print("\nrun_standards_eval (single fixture, 1 seed, low iter):")
report = run_standards_eval(
    fixture_names=["12x6_cd2"],
    n_seeds=1,
    sa_iterations=10_000,
    verbose=False,
)
check("report has overall_verdict",
      report.get("overall_verdict") in ("pass", "warn", "fail"))
check("report has elapsed_s", isinstance(report.get("elapsed_s"), (int, float)))
check("report.per_fixture has 1 entry",
      len(report.get("per_fixture", [])) == 1)
check("per_fixture entry references 12x6_cd2",
      report["per_fixture"][0]["fixture"] == "12x6_cd2")


# ── 6. Unknown fixture filter ───────────────────────────────────────


print("\nUnknown fixture handling:")
report = run_standards_eval(
    fixture_names=["zzz_nonexistent"],
    n_seeds=1,
    sa_iterations=10_000,
    verbose=False,
)
check("unknown-only request results in 0 fixtures evaluated",
      len(report.get("per_fixture", [])) == 0)
check("overall_verdict is 'pass' when no fixtures evaluated",
      report.get("overall_verdict") == "pass")


# ── Done ────────────────────────────────────────────────────────────


print()
if _failures > 0:
    print(f"{_failures} failure(s).")
    sys.exit(1)
print("All standards smoke tests passed.")
