"""Standing eval suite configuration.

Defines the per-fixture bars the production scheduler must meet for
each shape in the proving inventory. Bars are split into:

  - hard_requirements: failing any of these = test failure
  - soft_thresholds:   failing these = warning, not test failure
                       (can be promoted to hard via env var)

Per-fixture overrides let specific shapes have looser bars where
structural constraints make tight bars unrealistic (e.g., 12×6 cd=2's
par_quad floor isn't achievable).

The bars are starting points based on Phase C scoring observations
on 100K SA iter × 3 seeds. Higher-budget production runs should
score higher; if they regress below these bars, that's a real issue.
"""

from __future__ import annotations

# ── Proving inventory ────────────────────────────────────────────────


# Each entry: (n_teams, matches_per_team, teams_per_alliance, cooldown, name)
INVENTORY = [
    (12, 6,  3, 2, "12x6_cd2"),
    (20, 8,  3, 2, "20x8_cd2"),   # surrogate-required
    (24, 8,  3, 2, "24x8_cd2"),
    (36, 7,  3, 2, "36x7_cd2"),   # 2026mnst shape
    (60, 12, 3, 2, "60x12_cd2"),
]


# ── Bar definitions ──────────────────────────────────────────────────


# Default bars applied to every fixture unless overridden below.
DEFAULT_BARS = {
    "hard_requirements": {
        "is_valid_paramount":   True,    # cooldown_violations = 0 mandatory
        "cooldown_score_min":   100.0,   # FRC §10.5.2 paramount
    },
    "soft_thresholds": {
        "composite_min":        80.0,    # overall quality
        "per_criterion_min":    50.0,    # no criterion below this
    },
}


# Per-fixture overrides where structural constraints push the bars
# different from defaults. Each entry merges over DEFAULT_BARS.
PER_FIXTURE_OVERRIDES: dict[str, dict] = {
    # 12×6 at cooldown=2: structural gap on par_quad. Without
    # best-known floor scoring (which the eval uses by default),
    # par_quad would score 0. With best-known scoring, the canonical
    # is its own reference so composite = 100. The bar here is set
    # high to ensure regression detection.
    "12x6_cd2": {
        "soft_thresholds": {
            "composite_min":     85.0,    # Should match canonical closely
            "per_criterion_min": 50.0,    # color/station may drag with low iter
        },
        "notes": (
            "Structural cooldown=2 gap on par_quad. Best-known floor "
            "scoring used to give meaningful bars."
        ),
    },

    # 20×8: surrogate-required. Surrogate count is structurally fixed
    # at 2; surrogate score should be 100 (matches floor by construction).
    "20x8_cd2": {
        "soft_thresholds": {
            "composite_min":     75.0,    # 100K iter sees ~75-80
        },
        "notes": (
            "Surrogate-required (2 slots). par_quad/opp_quad floors "
            "tight; rb/station post-passes may not reach floor at "
            "default iterations."
        ),
    },

    # 36×7: production-scale (2026mnst shape). Bar held high.
    "36x7_cd2": {
        "soft_thresholds": {
            "composite_min":     85.0,    # par_quad routinely at floor
        },
        "notes": (
            "2026mnst production shape. par_quad floor=252 is "
            "achievable; rb/station post-pass weakness drags "
            "composite at default iter budget."
        ),
    },

    # 60×12: largest fixture. CP-SAT-infeasible. SA-only.
    "60x12_cd2": {
        "soft_thresholds": {
            "composite_min":     80.0,
        },
        "notes": (
            "Largest fixture (120 matches). SA-only generation. "
            "par_quad routinely hits floor; rb_per_team often above."
        ),
    },
}


# ── Scheduler invocation knobs ───────────────────────────────────────


# How many seeds per fixture. Each seed runs the full SA + post-pass
# pipeline; the median across seeds is what the bars are checked against.
# 3 is enough to filter outliers without dominating wall-clock; 5+ is
# more rigorous for production runs.
DEFAULT_N_SEEDS = 3

# SA iteration budget per seed. 100K is what the v1.0 canonicals were
# built at — production typically runs higher. Set per-eval-mode:
DEFAULT_SA_ITERATIONS = 100_000


def get_bars(fixture_name: str) -> dict:
    """Return the merged bars dict for a fixture name, applying any
    per-fixture override on top of DEFAULT_BARS."""
    bars = {
        "hard_requirements": dict(DEFAULT_BARS["hard_requirements"]),
        "soft_thresholds":   dict(DEFAULT_BARS["soft_thresholds"]),
        "notes":             "",
    }
    override = PER_FIXTURE_OVERRIDES.get(fixture_name, {})
    if "hard_requirements" in override:
        bars["hard_requirements"].update(override["hard_requirements"])
    if "soft_thresholds" in override:
        bars["soft_thresholds"].update(override["soft_thresholds"])
    if "notes" in override:
        bars["notes"] = override["notes"]
    return bars


__all__ = [
    "INVENTORY",
    "DEFAULT_BARS",
    "PER_FIXTURE_OVERRIDES",
    "DEFAULT_N_SEEDS",
    "DEFAULT_SA_ITERATIONS",
    "get_bars",
]
