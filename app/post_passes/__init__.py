# SPDX-License-Identifier: GPL-3.0-or-later
# FRC Match Scheduler
# Copyright (C) 2025 FRC Match Scheduler Contributors
"""Post-passes that operate on a finalized schedule's slot-level structure.

Each pass is a separable optimization that improves one criterion without
changing others. Used after the SA optimization phase in
``app/scheduler.py:generate_matches`` to close gaps the SA can't close
efficiently on its own.

Modules:
- ``rb_balance``: Red/Blue alliance balance (Phase 1)
- ``station_balance``: standard station-balance distribution (Phase 2)
"""
