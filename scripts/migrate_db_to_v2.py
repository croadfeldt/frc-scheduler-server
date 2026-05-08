#!/usr/bin/env python3
"""Phase 2 DB migration: rewrite stored day_config columns to V2 shape.

Runs against the live DB pointed at by $DATABASE_URL. Idempotent —
running multiple times is safe (V2 rows skip; only V1 rows migrate).

Usage:
    python scripts/migrate_db_to_v2.py             # dry run (default)
    python scripts/migrate_db_to_v2.py --apply     # actually write changes
    python scripts/migrate_db_to_v2.py --verify    # show version distribution; no writes

Per docs/DB_V2_MIGRATION.md, this script is the authoritative migration
tool. The migration logic itself comes from app.day_config_v2.migrate_v1_to_v2,
which is the same Python function exercised by tests/test_day_config_v2.py
(31 passing tests). This script is the SQLAlchemy plumbing around that
function.

Output summarizes counts per table (null / V1 / V2 / other) before
and after, plus per-row "would-write / wrote" lines for transparency.
A non-zero exit code on any unexpected error signals the wrapper
script to halt before doing anything destructive.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Locate the app package. The script runs in two contexts:
#
#  1. Local dev: the repo is cloned at e.g. ~/git/frc-scheduler-server and
#     this script lives in scripts/migrate_db_to_v2.py. The app package
#     is at ../app/ relative to the script.
#  2. OpenShift: the script is copied to /tmp/migrate_db_to_v2.py inside
#     the running container, where the app package lives at /app/app/
#     (per Containerfile.openshift WORKDIR=/app, COPY . .).
#
# Try candidate locations in order; first match wins. Fall through to
# letting Python's normal import mechanism work if PYTHONPATH is
# already configured externally.
_app_candidates = [
    # Local repo layout: scripts/migrate_db_to_v2.py → repo root is parent.parent
    Path(__file__).resolve().parent.parent,
    # Container WORKDIR per Containerfile.openshift
    Path("/app"),
    # Alternative container layouts
    Path("/code"),
    Path("/opt/app-root/src"),
    # Last-ditch: current working directory
    Path.cwd(),
]
for _candidate in _app_candidates:
    if (_candidate / "app" / "db.py").exists():
        sys.path.insert(0, str(_candidate))
        break
else:
    print(
        "ERROR: could not locate the 'app' package. Tried:\n  "
        + "\n  ".join(str(c) for c in _app_candidates),
        file=sys.stderr,
    )
    print(
        "Ensure this script is either:\n"
        "  - run from the repo root (with app/ as a subdirectory), or\n"
        "  - run inside a container where the app code is at /app/app/",
        file=sys.stderr,
    )
    sys.exit(2)

from sqlalchemy import select               # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession  # noqa: E402
from sqlalchemy.orm.attributes import flag_modified                   # noqa: E402

from app.db import (  # noqa: E402
    AbstractSchedule,
    AssignedSchedule,
    AssignedScheduleHistory,
)
from app.day_config_v2 import migrate_v1_to_v2, is_v2_shape  # noqa: E402


# Tables that hold a `day_config` JSON column. Column type is JSON, no
# schema change required — only the contents move from V1 to V2 shape.
TABLES = [
    ("abstract_schedules",         AbstractSchedule),
    ("assigned_schedules",         AssignedSchedule),
    ("assigned_schedule_history",  AssignedScheduleHistory),
]


def _classify(dc: object) -> str:
    """Return a category label for a stored day_config: null / v1 / v2 / other."""
    if dc is None:
        return "null"
    if not isinstance(dc, dict):
        return "other"
    v = dc.get("dayConfigVersion")
    if v == 2:
        return "v2"
    if v is None or v == 1:
        return "v1"
    return "other"


async def report_distribution(session: AsyncSession, label: str) -> dict[str, dict[str, int]]:
    """Print the version distribution per table; return raw counts."""
    print(f"\n── version distribution {label} ──")
    print(f"{'table':<32}  {'total':>6} {'null':>6} {'v1':>6} {'v2':>6} {'other':>6}")
    print("-" * 70)

    all_counts: dict[str, dict[str, int]] = {}
    for name, model in TABLES:
        result = await session.execute(select(model.day_config))
        rows = list(result.scalars())
        counts = {"null": 0, "v1": 0, "v2": 0, "other": 0}
        for dc in rows:
            counts[_classify(dc)] += 1
        all_counts[name] = counts
        print(f"{name:<32}  {len(rows):>6} {counts['null']:>6} {counts['v1']:>6} "
              f"{counts['v2']:>6} {counts['other']:>6}")
    return all_counts


async def migrate_table(session: AsyncSession, name: str, model, *,
                         apply_changes: bool, verbose: bool) -> tuple[int, int, int]:
    """Migrate one table's rows from V1 to V2.

    Returns (would_write, skipped, errors).

    A row is migrated when:
      - day_config is non-null
      - day_config is a dict
      - day_config does NOT have dayConfigVersion == 2

    The actual migration is delegated to app.day_config_v2.migrate_v1_to_v2;
    if that function returns the input unchanged (e.g. for already-V2 input
    or unmigratable shapes) the row is treated as skipped.
    """
    # Stream rows one at a time to keep memory bounded — a large
    # AssignedScheduleHistory table could be hundreds of rows × tens
    # of KB each. Loading them all eagerly is fine today but the
    # streaming pattern is small additional work for safety.
    result = await session.execute(select(model))
    rows = list(result.scalars())

    would_write = 0
    skipped     = 0
    errors      = 0

    for row in rows:
        dc = row.day_config
        if dc is None:
            skipped += 1
            continue
        if not isinstance(dc, dict):
            # Stored day_config that isn't a dict — log and skip. This
            # shouldn't happen given the JSON column type, but defend
            # against pathological data.
            print(f"  [warn] {name}.id={row.id}: day_config is {type(dc).__name__}, skipping")
            skipped += 1
            continue

        if is_v2_shape(dc):
            skipped += 1
            continue

        try:
            new_dc = migrate_v1_to_v2(dc)
        except (KeyError, TypeError, ValueError) as exc:
            print(f"  [error] {name}.id={row.id}: migration raised {type(exc).__name__}: {exc}")
            errors += 1
            continue

        # Defensive: if the migrator handed back the same object or
        # something not-a-dict, treat as skipped to avoid touching
        # the row.
        if new_dc is None or new_dc is dc or not isinstance(new_dc, dict):
            skipped += 1
            continue

        # If the result still doesn't look like V2, something is off.
        # Log and skip rather than commit a half-migration.
        if not is_v2_shape(new_dc):
            print(f"  [error] {name}.id={row.id}: post-migration shape is not V2 (version="
                  f"{new_dc.get('dayConfigVersion')!r}), skipping")
            errors += 1
            continue

        would_write += 1
        if verbose:
            print(f"  {'WROTE' if apply_changes else 'WOULD WRITE'} "
                  f"{name}.id={row.id} (V1 → V2)")

        if apply_changes:
            row.day_config = new_dc
            # Flag the column as dirty — required for JSON columns
            # because SQLAlchemy doesn't track in-place dict changes.
            flag_modified(row, "day_config")

    if apply_changes and would_write > 0:
        await session.commit()
        print(f"  committed {would_write} rows in {name}")

    return would_write, skipped, errors


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply",   action="store_true",
                        help="Actually write changes to the DB. Without this flag, runs in dry-run mode.")
    parser.add_argument("--verify",  action="store_true",
                        help="Skip migration; just print version distribution.")
    parser.add_argument("--verbose", action="store_true",
                        help="Print one line per migrated row.")
    args = parser.parse_args()

    if args.apply and args.verify:
        print("--apply and --verify are mutually exclusive", file=sys.stderr)
        return 2

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2

    # Hide credentials from logs but show host/db so the operator
    # can confirm they're targeting the right DB. URL shape:
    #   postgresql+asyncpg://user:pass@host:port/dbname
    safe_url = db_url
    if "@" in safe_url:
        prefix, host_part = safe_url.split("@", 1)
        # Replace credentials with ***. Keep schema:// at the front.
        scheme = prefix.split("//", 1)[0] if "//" in prefix else prefix
        safe_url = f"{scheme}//***:***@{host_part}"
    print(f"Connecting to: {safe_url}")
    print(f"Mode: {'APPLY (writes)' if args.apply else 'VERIFY only' if args.verify else 'DRY RUN (no writes)'}")

    engine = create_async_engine(db_url, future=True)
    try:
        async with AsyncSession(engine) as session:
            before = await report_distribution(session, label="before")

            if args.verify:
                # Verify-only mode: report and exit.
                return 0

            print()
            print(f"── {'applying migration' if args.apply else 'dry run — nothing will be written'} ──")
            total_would = 0
            total_skip  = 0
            total_err   = 0
            for name, model in TABLES:
                ww, sk, er = await migrate_table(
                    session, name, model,
                    apply_changes=args.apply,
                    verbose=args.verbose,
                )
                total_would += ww
                total_skip  += sk
                total_err   += er
                print(f"{name}: {ww} {'wrote' if args.apply else 'would write'}, "
                      f"{sk} skipped, {er} error{'s' if er != 1 else ''}")

            print()
            print(f"summary: {total_would} migrated, {total_skip} skipped, {total_err} errors")

            if args.apply:
                # Re-query to show the post-migration state.
                await report_distribution(session, label="after")

            if total_err > 0:
                # Non-zero exit so the OpenShift wrapper script halts.
                return 1
    finally:
        await engine.dispose()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
