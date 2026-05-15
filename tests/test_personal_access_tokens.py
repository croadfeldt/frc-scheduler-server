# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for app/personal_access_tokens.py (PAT mint, verify, revoke, list).

These are unit tests against an in-memory mock — they don't require a
running Postgres. The mock matches the SQLAlchemy patterns we actually
use (execute → scalar_one_or_none, etc.) so we get coverage of the real
code paths without infrastructure.

Integration with the real DB is exercised via the API smoke tests in
tests/test_pat_api_smoke.py.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.personal_access_tokens import (  # noqa: E402
    PAT_PREFIX,
    generate_plaintext, hash_token,
    mint_pat, verify_pat, revoke_pat, list_pats,
)
from app.db import PersonalAccessToken  # noqa: E402


# ── Minimal async session mock ───────────────────────────────────────
# Real SQLAlchemy would be overkill for unit tests; this mock implements
# only the subset of AsyncSession methods our code calls.

class _MockResult:
    def __init__(self, rows):
        self._rows = rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class MockSession:
    """Simulates an AsyncSession well enough for PAT unit tests.

    Instead of trying to parse compiled SQL (fragile), we introspect the
    statement's where_clause and walk its binary expressions to extract
    column-name + value pairs. This handles AND-of-equals predicates,
    which is everything the PAT module emits.
    """

    def __init__(self):
        self.rows: list[PersonalAccessToken] = []
        self._next_id = 1
        self.commits = 0
        self.rollbacks = 0

    @staticmethod
    def _extract_predicates(where_clause):
        """Walk a SQLAlchemy where clause and return list of (col, op, val).

        Handles ColumnClause = literal, ColumnClause IS NULL, and ANDs
        thereof. Returns [] for anything more complex (test will probably
        fail-soft by returning all rows).
        """
        from sqlalchemy.sql.elements import BinaryExpression, Null
        from sqlalchemy.sql.operators import eq, is_
        predicates = []
        # Flatten BooleanClauseList (AND) into list of clauses
        clauses = getattr(where_clause, "clauses", None)
        if clauses is None:
            clauses = [where_clause]
        for c in clauses:
            if not isinstance(c, BinaryExpression):
                continue
            left_name = getattr(c.left, "name", None) or getattr(c.left, "key", None)
            # Right side is either a BindParameter (carry the literal in .value)
            # or a literal expression
            right = c.right
            val = getattr(right, "value", None)
            if val is None and isinstance(right, Null):
                val = None
                predicates.append((left_name, "is", None))
                continue
            predicates.append((left_name, "eq", val))
        return predicates

    async def execute(self, stmt):
        s = str(stmt).lower().split()
        is_select = s and s[0] == "select"
        is_update = s and s[0] == "update"

        # Most statements have a whereclause attribute (None if no WHERE)
        where = getattr(stmt, "whereclause", None)
        preds = self._extract_predicates(where) if where is not None else []

        if is_select:
            filtered = list(self.rows)
            for col, op, val in preds:
                if op == "is" and val is None:
                    filtered = [r for r in filtered if getattr(r, col, None) is None]
                elif op == "eq":
                    filtered = [r for r in filtered if getattr(r, col, None) == val]
            # Order by created_at desc if requested in the stmt
            if "order by" in str(stmt).lower() and "created_at" in str(stmt).lower():
                filtered = sorted(filtered, key=lambda r: r.created_at, reverse=True)
            return _MockResult(filtered)

        if is_update:
            # PAT module only emits `UPDATE ... WHERE id = X SET last_used_at = Y`
            target_id = None
            for col, op, val in preds:
                if col == "id" and op == "eq":
                    target_id = val
            # Pull the SET values
            values = {}
            for col, bindparam in (getattr(stmt, "_values", None) or {}).items():
                col_name = getattr(col, "name", None) or getattr(col, "key", None) or str(col)
                v = getattr(bindparam, "value", None)
                values[col_name] = v
            for r in self.rows:
                if r.id == target_id:
                    for k, v in values.items():
                        setattr(r, k, v)
            return _MockResult([])

        return _MockResult([])

    def add(self, row):
        if row.id is None:
            row.id = self._next_id
            self._next_id += 1
        if not getattr(row, "created_at", None):
            row.created_at = datetime.now(timezone.utc)
        self.rows.append(row)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


# ── Test runner ──────────────────────────────────────────────────────

_failures = 0


def check(name, cond, detail=""):
    global _failures
    if cond:
        print(f"  ✓ {name}")
    else:
        _failures += 1
        print(f"  ✗ {name}: {detail}")


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Tests ────────────────────────────────────────────────────────────

print("Token format:")
plaintext = generate_plaintext()
check(f"plaintext starts with {PAT_PREFIX}",
      plaintext.startswith(PAT_PREFIX),
      f"got: {plaintext[:20]}...")
check("plaintext length plausible (45-55 chars)",
      45 <= len(plaintext) <= 55,
      f"got len={len(plaintext)}")

# Two consecutive mints produce different tokens
p1 = generate_plaintext()
p2 = generate_plaintext()
check("two mints produce different tokens", p1 != p2)


print("\nHashing:")
th = hash_token("frc_pat_abc123")
check("hash is 64 hex chars (sha256)",
      len(th) == 64 and all(c in "0123456789abcdef" for c in th),
      f"got: {th!r}")
check("hash is deterministic", hash_token("foo") == hash_token("foo"))
check("hash differs by input", hash_token("foo") != hash_token("bar"))


print("\nMint:")
session = MockSession()

# Mint a token
plaintext, row = run(mint_pat(
    user_id=42, name="my laptop", is_admin=False, db=session,
))
check("mint returns plaintext + row",
      plaintext.startswith(PAT_PREFIX) and row.id is not None)
check("row stored in session", row in session.rows)
check("row has correct user_id", row.user_id == 42)
check("row has correct name", row.name == "my laptop")
check("row has correct token_prefix",
      row.token_prefix == plaintext[:12])
check("row.token_hash matches sha256(plaintext)",
      row.token_hash == hash_token(plaintext))
check("default scopes are ['*']", row.scopes == ["*"])
check("default expires_at is None", row.expires_at is None)
check("is_admin matches input (False)", row.is_admin is False)

# Mint a second with admin
plaintext2, row2 = run(mint_pat(
    user_id=42, name="admin token", is_admin=True, db=session,
))
check("admin mint sets is_admin=True", row2.is_admin is True)

# Mint with expiry
future = datetime.now(timezone.utc) + timedelta(days=30)
plaintext3, row3 = run(mint_pat(
    user_id=42, name="expiring", is_admin=False,
    expires_at=future, db=session,
))
check("expiry mint stores expires_at", row3.expires_at == future)

# Empty name rejected
try:
    run(mint_pat(user_id=42, name="", is_admin=False, db=session))
    check("empty name raises ValueError", False, "no exception raised")
except ValueError:
    check("empty name raises ValueError", True)
try:
    run(mint_pat(user_id=42, name="   ", is_admin=False, db=session))
    check("whitespace-only name raises ValueError", False, "no exception raised")
except ValueError:
    check("whitespace-only name raises ValueError", True)


print("\nVerify:")
# Verify a valid token
verified = run(verify_pat(plaintext, db=session))
check("valid token verifies", verified is not None and verified.id == row.id)
check("last_used_at bumped on verify",
      verified is not None and verified.last_used_at is not None)

# Wrong token doesn't match
bad = run(verify_pat("frc_pat_obviously_wrong_token", db=session))
check("nonexistent token returns None", bad is None)

# Token without prefix doesn't match
unprefixed = run(verify_pat("just_some_jwt_like_string", db=session))
check("token without PAT_PREFIX returns None", unprefixed is None)

# Empty string
check("empty plaintext returns None",
      run(verify_pat("", db=session)) is None)


print("\nExpiry:")
past = datetime.now(timezone.utc) - timedelta(days=1)
plaintext_exp, row_exp = run(mint_pat(
    user_id=42, name="already-expired", is_admin=False,
    expires_at=past, db=session,
))
check("expired token returns None on verify",
      run(verify_pat(plaintext_exp, db=session)) is None)


print("\nRevocation:")
ok = run(revoke_pat(token_id=row.id, user_id=42, db=session))
check("revoke returns True for owned token", ok is True)
check("row.revoked_at is set", row.revoked_at is not None)

# Verifying a revoked token fails
revoked_verify = run(verify_pat(plaintext, db=session))
check("revoked token returns None on verify", revoked_verify is None)

# Idempotent: revoking again is still True (end state matches)
ok2 = run(revoke_pat(token_id=row.id, user_id=42, db=session))
check("revoke is idempotent", ok2 is True)

# Wrong user can't revoke
ok3 = run(revoke_pat(token_id=row2.id, user_id=999, db=session))
check("revoke from wrong user returns False", ok3 is False)
check("row2 not affected by wrong-user revoke", row2.revoked_at is None)

# Nonexistent token id
ok4 = run(revoke_pat(token_id=99999, user_id=42, db=session))
check("revoke of nonexistent token returns False", ok4 is False)


print("\nList:")
listed = run(list_pats(user_id=42, db=session))
# row was revoked, row3 still valid, row_exp expired-but-not-revoked, row2 admin
# Default excludes revoked
non_revoked_ids = {r.id for r in listed}
check("listing excludes revoked by default",
      row.id not in non_revoked_ids,
      f"got: {non_revoked_ids}")

all_listed = run(list_pats(user_id=42, include_revoked=True, db=session))
all_ids = {r.id for r in all_listed}
check("list with include_revoked=True returns all",
      row.id in all_ids,
      f"got: {all_ids}")

# Different user sees nothing
other_user = run(list_pats(user_id=999, db=session))
check("list for unrelated user returns empty", other_user == [])


print()
if _failures > 0:
    print(f"{_failures} failure(s).")
    sys.exit(1)
print("All PAT unit tests passed.")
