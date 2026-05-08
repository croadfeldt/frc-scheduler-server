# SPDX-License-Identifier: GPL-3.0-or-later
"""
OAuth2 authentication — Google and Apple sign-in.

Security:
  - JWT token delivered to popup via postMessage with targetOrigin=BASE_URL (not '*')
  - Token is json.dumps()-encoded before embedding in script block — prevents
    script injection from tokens containing quotes or JS special chars
  - Frontend validates postMessage origin against window.location.origin
  - JWT_SECRET default value is rejected at startup in production mode
"""

import json
import os
import time
import logging
from typing import Optional

import httpx
from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import User, get_session

log = logging.getLogger(__name__)

JWT_SECRET       = os.getenv("JWT_SECRET", "change-me-in-production")
JWT_ALGORITHM    = "HS256"
JWT_EXPIRE_SECS  = 60 * 60 * 24 * 30

GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()

# All four Apple values get stripped at load time because OpenShift's
# secret-editor commonly introduces trailing newlines when pasting
# values from the developer portal — and Apple rejects JWT claims
# containing whitespace with an opaque `invalid_client` error. The
# stripped values are also what `_apple_client_secret` and
# `apple_exchange_code` use everywhere downstream.
APPLE_CLIENT_ID   = os.getenv("APPLE_CLIENT_ID", "").strip()
APPLE_TEAM_ID     = os.getenv("APPLE_TEAM_ID", "").strip()
APPLE_KEY_ID      = os.getenv("APPLE_KEY_ID", "").strip()
# Private key is NOT stripped — the PEM format requires its trailing
# newline. Strip is done in _apple_client_secret only on the
# whitespace-around the body; internal newlines are preserved.
APPLE_PRIVATE_KEY = os.getenv("APPLE_PRIVATE_KEY", "")

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").strip().rstrip("/")

# Interim admin allow-list: comma-separated email addresses that are
# automatically promoted to is_admin=true at login time. Replaced
# by RBAC role grants when docs/RBAC_MODEL.md ships. Whitespace and
# case are normalized; an empty value disables the allow-list (no
# auto-promotion happens, and only manually-set is_admin survives).
#
# Removing an email from this list does NOT revoke admin status —
# that requires direct DB intervention. This is intentional:
# auto-revoke would risk locking out the only admin during a
# config typo or a deploy that briefly drops the env var.
_admin_emails_raw = os.getenv("ADMIN_EMAILS", "")
ADMIN_EMAILS = frozenset(
    e.strip().lower()
    for e in _admin_emails_raw.split(",")
    if e.strip()
)
if ADMIN_EMAILS:
    log.info("Admin allow-list configured for %d email(s)", len(ADMIN_EMAILS))


def create_jwt(user_id: int, sub: str, provider: str, email: str | None,
               is_admin: bool = False) -> str:
    payload = {
        "sub": sub, "uid": user_id, "provider": provider,
        "email": email or "",
        # Embed is_admin in the JWT so freeze/lock guards can check
        # without a DB round-trip per request. Trade-off: when admin
        # status changes (DB update or ADMIN_EMAILS allow-list), the
        # change takes effect on the user's NEXT login (max 30 days
        # given JWT_EXPIRE_SECS). Acceptable for an interim flag;
        # RBAC will revisit when it lands.
        "is_admin": bool(is_admin),
        "iat": int(time.time()), "exp": int(time.time()) + JWT_EXPIRE_SECS,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_jwt(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict | None:
    if not credentials:
        return None
    try:
        return decode_jwt(credentials.credentials)
    except JWTError:
        return None


async def require_auth(user: dict | None = Depends(get_current_user)) -> dict:
    if not user:
        raise HTTPException(401, "Authentication required")
    return user


async def upsert_user(sub: str, provider: str, email: str | None,
                      name: str | None, db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.sub == sub))
    user = result.scalar_one_or_none()
    if user:
        user.email = email
        user.name  = name
    else:
        user = User(sub=sub, provider=provider, email=email, name=name)
        db.add(user)
    # Apply the ADMIN_EMAILS allow-list. Idempotent — flips the
    # flag on if the user's email matches; never flips it off, so
    # an admin promoted via DB stays admin even if their email is
    # not in the env-var list. To revoke admin status, set
    # is_admin=false directly in the DB.
    if email and ADMIN_EMAILS and email.strip().lower() in ADMIN_EMAILS:
        if not user.is_admin:
            user.is_admin = True
            log.info("Promoted user %s to admin via ADMIN_EMAILS allow-list", email)
    await db.commit()
    await db.refresh(user)
    return user


def _oauth_popup_response(token: str) -> HTMLResponse:
    """
    Deliver JWT to opener via postMessage.

    Security:
    - targetOrigin is BASE_URL, not '*' — only our origin receives the token
    - json.dumps() escapes all JS-special chars in the token string, preventing
      script injection (quotes, backslashes, Unicode line terminators U+2028/2029)
    - Falls back to localStorage + redirect if no opener window
    """
    token_js         = json.dumps(token)        # safe JS string literal
    target_origin_js = json.dumps(BASE_URL)     # safe JS string literal

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"></head><body><script>
(function(){{
  var t={token_js};
  var o={target_origin_js};
  if(window.opener){{window.opener.postMessage({{token:t}},o);window.close();}}
  else{{try{{localStorage.setItem('frc_token',t);}}catch(e){{}}window.location.replace('/')}}
}})();
</script></body></html>"""
    return HTMLResponse(html)


# ── Google OAuth ──────────────────────────────────────────────────────────────

GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO  = "https://www.googleapis.com/oauth2/v3/userinfo"


def google_login_url(state: str = "") -> str:
    import urllib.parse
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": f"{BASE_URL}/auth/google/callback",
        "response_type": "code", "scope": "openid email profile",
        "state": state, "prompt": "select_account",
    }
    return GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params)


async def google_exchange_code(code: str) -> dict:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(GOOGLE_TOKEN_URL, data={
            "client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET,
            "code": code, "grant_type": "authorization_code",
            "redirect_uri": f"{BASE_URL}/auth/google/callback",
        })
        resp.raise_for_status()
        tokens = resp.json()
        info = await client.get(GOOGLE_USERINFO,
                                headers={"Authorization": f"Bearer {tokens['access_token']}"})
        info.raise_for_status()
        return info.json()


# ── Apple OAuth ───────────────────────────────────────────────────────────────

APPLE_AUTH_URL  = "https://appleid.apple.com/auth/authorize"
APPLE_TOKEN_URL = "https://appleid.apple.com/auth/token"
APPLE_KEYS_URL  = "https://appleid.apple.com/auth/keys"


def _apple_client_secret() -> str:
    # Apple requires a short-lived JWT signed with the .p8 private key
    # as the client_secret. The JWT carries:
    #   iss = APPLE_TEAM_ID    — 10-char team identifier
    #   sub = APPLE_CLIENT_ID  — Service ID (NOT the App ID)
    #   aud = appleid.apple.com
    #   iat / exp window
    # Header carries `kid = APPLE_KEY_ID` so Apple knows which public
    # key to verify against.
    if not APPLE_PRIVATE_KEY:
        log.error("Apple client secret: APPLE_PRIVATE_KEY is unset")
        return ""
    missing = [name for name, val in [
        ("APPLE_TEAM_ID",   APPLE_TEAM_ID),
        ("APPLE_KEY_ID",    APPLE_KEY_ID),
        ("APPLE_CLIENT_ID", APPLE_CLIENT_ID),
    ] if not val]
    if missing:
        log.error("Apple client secret: missing env vars: %s", ", ".join(missing))
        return ""
    # The .p8 file is a multi-line PEM. OpenShift secrets often store
    # it as escaped \n; normalize both. Also ensure the BEGIN/END
    # lines are present — a common error is pasting only the base64
    # body without the wrappers.
    private_key = APPLE_PRIVATE_KEY.replace("\\n", "\n").strip()
    if "BEGIN PRIVATE KEY" not in private_key:
        log.error(
            "Apple client secret: APPLE_PRIVATE_KEY does not contain "
            "'BEGIN PRIVATE KEY'. Paste the FULL .p8 file contents, "
            "including the -----BEGIN PRIVATE KEY----- and "
            "-----END PRIVATE KEY----- lines."
        )
        return ""
    now = int(time.time())
    try:
        return jwt.encode(
            {"iss": APPLE_TEAM_ID, "iat": now, "exp": now + 86400,
             "aud": "https://appleid.apple.com", "sub": APPLE_CLIENT_ID},
            private_key, algorithm="ES256",
            headers={"alg": "ES256", "kid": APPLE_KEY_ID},
        )
    except Exception as e:
        log.error(
            "Apple client secret JWT encode failed: %s. Check that "
            "APPLE_PRIVATE_KEY contains a valid ES256 (P-256) PEM "
            "private key — Apple's .p8 files are this format.",
            e,
        )
        return ""


def apple_login_url(state: str = "") -> str:
    import urllib.parse
    params = {
        "client_id": APPLE_CLIENT_ID, "redirect_uri": f"{BASE_URL}/auth/apple/callback",
        "response_type": "code", "scope": "name email",
        "response_mode": "form_post", "state": state,
    }
    return APPLE_AUTH_URL + "?" + urllib.parse.urlencode(params)


async def apple_exchange_code(code: str, id_token_raw: str | None = None) -> dict:
    # Generate the JWT client_secret. If this fails (missing env vars,
    # malformed private key), `_apple_client_secret` returns "" and
    # logs the cause. Posting an empty client_secret to Apple yields
    # a 400 with no useful surface diagnostic — catch it here.
    client_secret = _apple_client_secret()
    if not client_secret:
        raise ValueError(
            "Apple client secret could not be generated. Check that "
            "APPLE_TEAM_ID, APPLE_KEY_ID, APPLE_CLIENT_ID, and "
            "APPLE_PRIVATE_KEY are all set and that the private key "
            "is the .p8 contents (not just the filename). See "
            "earlier log entries for the underlying cryptographic "
            "error."
        )
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(APPLE_TOKEN_URL, data={
            "client_id": APPLE_CLIENT_ID, "client_secret": client_secret,
            "code": code, "grant_type": "authorization_code",
            "redirect_uri": f"{BASE_URL}/auth/apple/callback",
        })
        # Apple returns JSON with `error` and `error_description` fields
        # on failure — the standard OAuth2 error shape. Surfacing those
        # in the exception turns "400 Bad Request" into something
        # actionable like "invalid_client: Client authentication failed."
        # Common error codes from Apple at this endpoint:
        #   invalid_client       — client_secret JWT rejected (wrong team/key/sub,
        #                          expired, or wrong algorithm). Most common cause:
        #                          APPLE_CLIENT_ID is the App ID instead of the
        #                          Service ID, or the key isn't associated with the
        #                          App ID in the developer portal.
        #   invalid_grant        — `code` already used or expired (~10 min lifetime).
        #   invalid_request      — malformed body (rare; would mean a code bug).
        #   unsupported_grant_type — bug in our request shape.
        if resp.status_code != 200:
            try:
                err_body = resp.json()
                err_code = err_body.get("error", "unknown")
                err_desc = err_body.get("error_description", "")
                detail = f"Apple token endpoint returned {resp.status_code}: {err_code}"
                if err_desc:
                    detail += f" ({err_desc})"
            except Exception:
                detail = f"Apple token endpoint returned {resp.status_code}: {resp.text[:300]}"
            log.error("Apple OAuth token exchange failed: %s", detail)
            raise ValueError(detail)
        tokens = resp.json()
    async with httpx.AsyncClient(timeout=15.0) as client:
        keys_resp = await client.get(APPLE_KEYS_URL)
        keys_resp.raise_for_status()
        jwks = keys_resp.json()
    id_token = tokens.get("id_token") or id_token_raw or ""
    header   = jwt.get_unverified_header(id_token)
    key      = next((k for k in jwks["keys"] if k["kid"] == header["kid"]), None)
    if not key:
        raise ValueError("Apple public key not found")
    # Apple's id_token includes an `at_hash` claim — a hash of the
    # access_token, designed to let a relying party verify that the
    # access_token and id_token belong to the same OAuth response.
    # python-jose validates this automatically when the access_token
    # is passed in. Without it, jose raises:
    #   "No access_token provided to compare against at_hash claim"
    # Apple sends the access_token in the same response body that
    # carried the id_token, so we always have it available here. If
    # the token endpoint omitted access_token (shouldn't happen for
    # an authorization_code grant, but be defensive), we fall back
    # to disabling the at_hash check rather than failing the login.
    access_token = tokens.get("access_token")
    decode_kwargs = {
        "key":        key,
        "algorithms": ["RS256"],
        "audience":   APPLE_CLIENT_ID,
    }
    if access_token:
        decode_kwargs["access_token"] = access_token
    else:
        decode_kwargs["options"] = {"verify_at_hash": False}
    claims = jwt.decode(id_token, **decode_kwargs)
    return {"sub": claims.get("sub"), "email": claims.get("email"), "name": None}
