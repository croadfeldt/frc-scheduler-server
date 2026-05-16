"""
Regression guards for Nexus → MatchResult timestamp synthesis.

When TBA doesn't populate actual_time / post_result_time for completed
matches (FMS upload lag at the venue, TBA service hiccup), Nexus's
queue_status carries enough info to synthesize the same fields
heuristically in _process_nexus_match_status:

    status='on_field'  → set MatchResult.actual_time if null
    status='completed' → set both actual_time and post_result_time if null

Why source-substring tests instead of behavioral tests: app/db.py is
hard-wired for Postgres (pool kwargs incompatible with sqlite), so
spinning up a test DB requires more plumbing than the value of this
particular test justifies. The synthesis logic is short and the
substring guards catch accidental removal / reversion.
"""
import os
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
LIVE_PY = (REPO / "app" / "live.py").read_text(encoding="utf-8")


def check(name, ok, reason=""):
    if ok:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}: {reason}")
        global _failures
        _failures += 1


_failures = 0
print("Nexus → MatchResult synthesis guards:")

# 1. Synthesis section exists with the right context comment
check(
    "synthesis section is in _process_nexus_match_status",
    "Synthesize MatchResult timestamps from Nexus status" in LIVE_PY,
    "lost or renamed the synthesis block",
)

# 2. Only fires for on_field / completed
check(
    "synthesis gated on status in (on_field, completed)",
    "status in ('on_field', 'completed')" in LIVE_PY,
    "should only synthesize for those two statuses; others must skip",
)

# 3. on_field sets actual_time only when null
check(
    "on_field writes actual_time only when null",
    "if status == 'on_field' and mrow.actual_time is None:" in LIVE_PY
    and "mrow.actual_time = synth_ts" in LIVE_PY,
    "TBA's actual_time must win over synthesis",
)

# 4. completed sets both fields only when null
import re
post_block = re.search(
    r"if status == 'completed':[\s\S]{0,400}post_result_time = synth_ts", LIVE_PY
)
check(
    "completed writes post_result_time only when null",
    bool(post_block)
    and "if mrow.post_result_time is None:" in post_block.group(0),
    "post_result_time must be guarded; TBA's value wins over synthesis",
)

# 5. Synthesis prefers actualQueueTime, falls back to current time
check(
    "synthesis prefers actualQueueTime over current time",
    "actualQueueTime" in LIVE_PY,
    "should read Nexus's actualQueueTime if present",
)
check(
    "synthesis falls back to current UTC time",
    "datetime.now(timezone.utc).timestamp()" in LIVE_PY,
    "should use now() when no actualQueueTime",
)

# 6. Synthesis creates a row if none exists
match_create_block = re.search(
    r"if mrow is None:[\s\S]{0,400}MatchResult\(\s*event_id", LIVE_PY
)
check(
    "synthesis creates a MatchResult row when missing",
    bool(match_create_block),
    "must auto-create MatchResult row so 3-up / table can reference it",
)

# 7. Practice matches are filtered earlier in the function
check(
    'practice ("p" comp_level) is filtered before synthesis',
    'if comp_level == "p":' in LIVE_PY,
    "practice matches should not get synthesized as quals",
)

if _failures:
    print(f"\n{_failures} failure(s).")
    raise SystemExit(1)
print("\nAll Nexus synthesis guards passed.")
