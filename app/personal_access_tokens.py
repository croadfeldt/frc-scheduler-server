# SPDX-License-Identifier: GPL-3.0-or-later
"""
Personal Access Token (PAT) authentication.

PATs are long-lived API credentials a user creates in the web UI (or
via this module's helpers) to authenticate non-browser clients — CLI
tools, scripts, CI/CD jobs. They're a complement to the OAuth JWT
flow, not a replacement: JWTs are still issued at OAuth login for
the web UI, and any endpoint that accepts a JWT also accepts a PAT.

See `app/db.py:PersonalAccessToken` for the schema and the design
rationale (why SHA-256 not bcrypt, why is_admin is snapshotted at
mint, etc.).

Token format
------------

    frc_pat_<43 chars base64url of 32 random bytes>

The `frc_pat_` prefix is the auth dispatcher key: app/auth.py looks at
`Authorization: Bearer <value>` and routes anything starting with that
prefix to this module's `verify_pat`, falling through to JWT decode
otherwise. The prefix is fixed, not configurable — it's a recognition
marker, not a secret.

The 32-byte random body gives 256 bits of entropy, vastly more than
needed to be unguessable. Base64url-encoded so it's URL-safe in case
anyone foolishly puts it in a query string (don't — use a header).

Mint flow
---------

    plaintext, row = await mint_pat(user_id=u.id, name="my laptop",
                                     is_admin=u.is_admin, db=session)
    # Return plaintext to caller ONCE — it cannot be recovered later
    # (we only store the hash). The DB row is committed by the caller
    # in the same transaction.

Verify flow
-----------

    pat = await verify_pat(plaintext="frc_pat_xJK3...", db=session)
    if pat is None:
        # Not found, expired, or revoked — caller treats as auth failure
        ...
    # pat is a PersonalAccessToken row. Use pat.user_id, pat.is_admin, etc.
    # last_used_at has already been bumped (best-effort, non-fatal).
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timezone
from typing import Tuple

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import PersonalAccessToken

log = logging.getLogger(__name__)


# Token prefix is exposed as a module constant so app/auth.py can use it
# for dispatch and tests can assert on it without copy-paste.
PAT_PREFIX = "frc_pat_"

# Random body length in BYTES (before base64 encoding). 32 bytes = 256 bits.
# Don't lower this; brute-force resistance + future quantum-future-proofing.
_PAT_RANDOM_BYTES = 32

# Prefix length to store for UI display. "frc_pat_" + 4 chars = 12.
# Enough for users to disambiguate "the laptop one" from "the CI one"
# without leaking enough material to be useful to an attacker.
_TOKEN_PREFIX_DISPLAY_LEN = 12


def generate_plaintext() -> str:
    """Mint a fresh PAT plaintext value.

    Uses secrets.token_urlsafe which calls os.urandom under the hood —
    cryptographically secure on all supported platforms.
    """
    return PAT_PREFIX + secrets.token_urlsafe(_PAT_RANDOM_BYTES)


def hash_token(plaintext: str) -> str:
    """Hex-encoded SHA-256 hash, suitable for the token_hash column.

    Why SHA-256 and not bcrypt: see PersonalAccessToken class docstring
    in app/db.py. Short version: PATs are 256-bit random secrets, not
    passwords, so the bruteforce-resistance properties of bcrypt aren't
    relevant — and bcrypt's slowness would add ~100ms per API request,
    unacceptable for non-interactive use.
    """
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


async def mint_pat(
    *,
    user_id: int,
    name: str,
    is_admin: bool,
    db: AsyncSession,
    scopes: list[str] | None = None,
    expires_at: datetime | None = None,
) -> Tuple[str, PersonalAccessToken]:
    """Create a new PAT for a user.

    Returns (plaintext, row). The plaintext MUST be returned to the
    caller and shown to the user once — it cannot be retrieved later
    (we only store the hash).

    The row is added to the session and flushed but NOT committed —
    the caller controls the transaction so the mint can be part of a
    larger operation. Typically the API endpoint commits at the end
    of the request.

    Args:
        user_id:   The owning user's primary key.
        name:      Human-readable label (max 128 chars; truncated).
                   Not unique; users can have multiple tokens named
                   "laptop" if they want.
        is_admin:  Snapshot of the user's admin status at mint time.
                   See PersonalAccessToken docstring for why this is
                   captured rather than fetched per-request.
        db:        Async session; the row is added + flushed here.
        scopes:    Optional list of scope strings. Defaults to ["*"]
                   ("all endpoints"). Scope enforcement is NOT
                   implemented yet — forward-compat only.
        expires_at: Optional UTC datetime; after this the token is
                    rejected with 401. None = never expires.

    Raises:
        ValueError: if name is empty or only whitespace.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("token name cannot be empty")
    if len(name) > 128:
        name = name[:128]

    plaintext = generate_plaintext()
    row = PersonalAccessToken(
        user_id=user_id,
        name=name,
        token_prefix=plaintext[:_TOKEN_PREFIX_DISPLAY_LEN],
        token_hash=hash_token(plaintext),
        scopes=scopes or ["*"],
        is_admin=bool(is_admin),
        expires_at=expires_at,
    )
    db.add(row)
    await db.flush()  # populates row.id without committing
    return plaintext, row


async def verify_pat(
    plaintext: str,
    db: AsyncSession,
) -> PersonalAccessToken | None:
    """Look up a PAT by its plaintext and validate it's usable.

    Returns the row if the token exists AND is not revoked AND is
    not expired; None otherwise.

    Best-effort updates last_used_at to now. The update is not
    awaited as a transaction boundary — if it fails (unlikely), we
    still return the row so the API call succeeds. The trade-off:
    last_used_at might be slightly behind in pathological cases.

    Performance: single indexed SELECT by token_hash, then one UPDATE.
    Both sub-millisecond on a properly-indexed table.
    """
    if not plaintext or not plaintext.startswith(PAT_PREFIX):
        return None
    th = hash_token(plaintext)
    result = await db.execute(
        select(PersonalAccessToken).where(PersonalAccessToken.token_hash == th)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    if row.revoked_at is not None:
        return None
    now = datetime.now(timezone.utc)
    if row.expires_at is not None and row.expires_at < now:
        return None

    # Best-effort touch of last_used_at. We use a separate UPDATE rather
    # than mutating row.last_used_at + db.commit() because we want this
    # to be a side effect of an authenticated read, not gate the
    # request on a commit. If the caller's outer transaction rolls back
    # for an unrelated reason, the timestamp still updates.
    try:
        await db.execute(
            update(PersonalAccessToken)
            .where(PersonalAccessToken.id == row.id)
            .values(last_used_at=now)
        )
        await db.commit()
    except Exception:
        # Don't fail auth just because we couldn't bump a timestamp.
        # Log at info, not error — this is observable but non-critical.
        log.info("Failed to update last_used_at for PAT %d", row.id,
                 exc_info=True)
        # Best effort to roll back the failed touch so the session is
        # usable downstream. The auth still succeeds.
        try:
            await db.rollback()
        except Exception:
            pass
    # Set last_used_at on the returned row so callers see fresh data
    # without re-querying.
    row.last_used_at = now
    return row


async def revoke_pat(
    *,
    token_id: int,
    user_id: int,
    db: AsyncSession,
) -> bool:
    """Mark a PAT revoked. Returns True if revoked, False if not found
    or not owned by the given user.

    Idempotent: revoking an already-revoked token returns True
    (the desired end state is the same).

    Caller commits the transaction.
    """
    result = await db.execute(
        select(PersonalAccessToken).where(
            PersonalAccessToken.id == token_id,
            PersonalAccessToken.user_id == user_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
    return True


async def list_pats(
    *,
    user_id: int,
    include_revoked: bool = False,
    db: AsyncSession,
) -> list[PersonalAccessToken]:
    """Return all PATs owned by the given user, newest first.

    Plaintext is NOT in the rows — it was only ever in memory at mint
    time and never persisted. UI should display token_prefix as
    identification.
    """
    q = select(PersonalAccessToken).where(PersonalAccessToken.user_id == user_id)
    if not include_revoked:
        q = q.where(PersonalAccessToken.revoked_at.is_(None))
    q = q.order_by(PersonalAccessToken.created_at.desc())
    result = await db.execute(q)
    return list(result.scalars().all())
