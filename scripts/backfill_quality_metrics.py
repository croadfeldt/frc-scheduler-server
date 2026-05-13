#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bulk-backfill quality metrics on existing AbstractSchedule rows.

Iterates abstract_schedules in the production DB and backfills the
`quality_report` column for rows that are missing metrics or carrying
stale data (e.g., the old shape that embedded `scores` directly —
those should be replaced with metrics-only persistence).

Run modes:

    # Dry-run: report what would change, change nothing
    python3 scripts/backfill_quality_metrics.py --dry-run

    # Apply: actually backfill rows
    python3 scripts/backfill_quality_metrics.py

    # Force-rebuild every row (even those already with metrics)
    python3 scripts/backfill_quality_metrics.py --force

    # Limit (useful for testing or staged rollout)
    python3 scripts/backfill_quality_metrics.py --limit 100

Exits 0 on success, non-zero on any error during processing.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm.attributes import flag_modified  # noqa: E402

from app.db import AsyncSessionLocal, AbstractSchedule  # noqa: E402
from app.quality_report import compute_metrics  # noqa: E402


def _needs_backfill(sched: AbstractSchedule, force: bool) -> tuple[bool, str]:
    """Decide whether a row needs backfill, returning (yes/no, reason)."""
    if force:
        return True, "force=true"
    if sched.quality_report is None:
        return True, "quality_report is NULL"
    if not isinstance(sched.quality_report, dict):
        return True, "quality_report is not a dict"
    if 'metrics' not in sched.quality_report:
        return True, "quality_report lacks 'metrics' key"
    if 'scores' in sched.quality_report:
        # Stale shape: scores were embedded in storage. Recompute as
        # metrics-only so future reads derive scores fresh.
        return True, "quality_report has stale 'scores' embedded"
    return False, "already has metrics, no scores"


async def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dry-run', action='store_true',
                    help="Report what would change, change nothing")
    ap.add_argument('--force', action='store_true',
                    help="Backfill every row, even those with current metrics")
    ap.add_argument('--limit', type=int, default=None,
                    help="Process at most N rows (for staged rollout)")
    ap.add_argument('--verbose', action='store_true',
                    help="Print one line per row")
    args = ap.parse_args()

    n_examined  = 0
    n_changed   = 0
    n_skipped   = 0
    n_failed    = 0

    async with AsyncSessionLocal() as db:
        q = select(AbstractSchedule).order_by(AbstractSchedule.id.asc())
        if args.limit is not None:
            q = q.limit(args.limit)
        result = await db.execute(q)
        rows = list(result.scalars())

        print(f"Examining {len(rows)} AbstractSchedule rows "
              f"(dry_run={args.dry_run}, force={args.force})")

        for sched in rows:
            n_examined += 1
            needs, reason = _needs_backfill(sched, args.force)

            if not needs:
                n_skipped += 1
                if args.verbose:
                    print(f"  #{sched.id}: skip ({reason})")
                continue

            if args.dry_run:
                n_changed += 1
                print(f"  #{sched.id}: would backfill ({reason})")
                continue

            try:
                if not sched.matches:
                    n_failed += 1
                    print(f"  #{sched.id}: SKIP — no matches data")
                    continue
                metrics_report = compute_metrics(
                    matches=sched.matches,
                    n_teams=sched.num_teams,
                    matches_per_team=sched.matches_per_team,
                    teams_per_alliance=3,
                    cooldown=sched.cooldown,
                )
                sched.quality_report = metrics_report
                flag_modified(sched, "quality_report")
                n_changed += 1
                if args.verbose:
                    print(f"  #{sched.id}: backfilled ({reason})")
            except Exception as e:
                n_failed += 1
                print(f"  #{sched.id}: FAILED — {type(e).__name__}: {e}")

        if not args.dry_run and n_changed > 0:
            await db.commit()
            print(f"Committed {n_changed} changes.")

    print()
    print(f"Examined: {n_examined}")
    print(f"Changed:  {n_changed}{' (dry-run)' if args.dry_run else ''}")
    print(f"Skipped:  {n_skipped}")
    print(f"Failed:   {n_failed}")

    sys.exit(0 if n_failed == 0 else 1)


if __name__ == '__main__':
    asyncio.run(main())
