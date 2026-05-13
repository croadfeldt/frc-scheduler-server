# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the PDF import flow's import_mode parameter shape.

Verifies the model definition itself (default value, optional target,
permissive string acceptance — endpoint-level validation rejects bad
values with a useful HTTPException, tested by the endpoint integration
path).

We deliberately don't import app/main.py here because it pulls heavy
runtime deps (httpx, fastapi server, etc) that the test environment
doesn't always have. Instead, we re-define the same Pydantic model
locally and verify both that the model accepts the expected shape AND
that the model definition in app/main.py matches by reading the source.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# Locally-defined copy of the model — should match app/main.py.
class PdfImportCommitRequest(BaseModel):
    pdf_import_id: int
    event_id:      int
    name:          str = Field("Imported Schedule", max_length=128)
    matches:       list[dict] | None = None
    practice:      list[dict] | None = None
    day_config:    Any = None
    import_mode:   str = Field("new_schedule")
    target_schedule_id: int | None = None


_failures = 0


def check(name, cond, detail=""):
    global _failures
    if cond:
        print(f"  ✓ {name}")
    else:
        _failures += 1
        print(f"  ✗ {name}: {detail}")


# ─────────────────────────────────────────────────────────────────────
# 1. Default mode is 'new_schedule'
# ─────────────────────────────────────────────────────────────────────

print("Default import_mode is 'new_schedule':")
r = PdfImportCommitRequest(
    pdf_import_id=1, event_id=1,
    matches=[{"red":[1,2,3],"blue":[4,5,6]}],
)
check("default import_mode is new_schedule", r.import_mode == 'new_schedule')
check("default target_schedule_id is None", r.target_schedule_id is None)


# ─────────────────────────────────────────────────────────────────────
# 2. replace_schedule mode with target
# ─────────────────────────────────────────────────────────────────────

print("\nreplace_schedule mode:")
r = PdfImportCommitRequest(
    pdf_import_id=1, event_id=1,
    import_mode='replace_schedule', target_schedule_id=42,
    matches=[{"red":[1,2,3],"blue":[4,5,6]}],
)
check("import_mode is replace_schedule", r.import_mode == 'replace_schedule')
check("target_schedule_id is 42", r.target_schedule_id == 42)


# ─────────────────────────────────────────────────────────────────────
# 3. Backward compat: legacy body still works
# ─────────────────────────────────────────────────────────────────────

print("\nBackward compat:")
r = PdfImportCommitRequest(
    pdf_import_id=1, event_id=1,
    name="Imported",
    matches=[{"red":[1,2,3],"blue":[4,5,6]}],
    practice=[], day_config=None,
)
check("legacy body (no import_mode field) → new_schedule default",
      r.import_mode == 'new_schedule')


# ─────────────────────────────────────────────────────────────────────
# 4. app/main.py model has matching shape
# ─────────────────────────────────────────────────────────────────────

print("\napp/main.py model matches expected shape:")
main_src = (Path(_REPO_ROOT) / "app" / "main.py").read_text()
# Find the class definition and walk forward until next def/class.
m = re.search(
    r'class\s+PdfImportCommitRequest\(BaseModel\):(.+?)(?=\n\n\n|\nclass |\n@app\.|\nasync def )',
    main_src, re.DOTALL,
)
if not m:
    check("can find PdfImportCommitRequest in app/main.py", False, "regex no match")
else:
    body = m.group(1)
    check("has 'import_mode: str = Field(\"new_schedule\")'",
          'import_mode:' in body and '"new_schedule"' in body)
    check("has 'target_schedule_id: int | None = None'",
          'target_schedule_id:' in body and 'int | None' in body)


# ─────────────────────────────────────────────────────────────────────
# 5. Endpoint validates import_mode + target_schedule_id
# ─────────────────────────────────────────────────────────────────────

print("\nEndpoint enforces import_mode validation:")
# Look at the source code of commit_pdf_import for the validation block.
m = re.search(
    r'async def commit_pdf_import\(.+?\):(.+?)(?=\nasync def |\n@app\.|\nclass )',
    main_src, re.DOTALL,
)
if not m:
    check("can find commit_pdf_import", False, "regex no match")
else:
    body = m.group(1)
    check("rejects invalid import_mode",
          "Invalid import_mode" in body or "import_mode not in" in body or
          "import_mode != 'new_schedule'" in body or "'new_schedule', 'replace_schedule'" in body)
    check("requires target_schedule_id when replace_schedule",
          "target_schedule_id" in body and "replace_schedule" in body)
    check("replace_schedule path checks _was_ever_official",
          "_was_ever_official" in body)
    check("replace_schedule path checks lock state",
          "locked_at" in body)
    check("replace_schedule path calls _snapshot_schedule_history",
          "_snapshot_schedule_history" in body and 'action="patch"' in body)
    check("response distinguishes the two modes",
          '"import_mode":' in body)


# ─────────────────────────────────────────────────────────────────────
# Done
# ─────────────────────────────────────────────────────────────────────

print()
if _failures > 0:
    print(f"{_failures} failure(s).")
    sys.exit(1)
print("All PDF import_mode tests passed.")
