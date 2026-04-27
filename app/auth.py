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

GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")

APPLE_CLIENT_ID   = os.getenv("APPLE_CLIENT_ID", "")
APPLE_TEAM_ID     = os.getenv("APPLE_TEAM_ID", "")
APPLE_KEY_ID      = os.getenv("APPLE_KEY_ID", "")
APPLE_PRIVATE_KEY = os.getenv("APPLE_PRIVATE_KEY", "")

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")


def create_jwt(user_id: int, sub: str, provider: str, email: str | None) -> str:
    payload = {
        "sub": sub, "uid": user_id, "provider": provider,
        "email": email or "",
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
    if not APPLE_PRIVATE_KEY:
        return ""
    now = int(time.time())
    try:
        return jwt.encode(
            {"iss": APPLE_TEAM_ID, "iat": now, "exp": now + 86400,
             "aud": "https://appleid.apple.com", "sub": APPLE_CLIENT_ID},
            APPLE_PRIVATE_KEY.replace("\\n", "\n"), algorithm="ES256",
            headers={"alg": "ES256", "kid": APPLE_KEY_ID},
        )
    except Exception as e:
        log.error("Apple client secret generation failed: %s", e)
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
    client_secret = _apple_client_secret()
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(APPLE_TOKEN_URL, data={
            "client_id": APPLE_CLIENT_ID, "client_secret": client_secret,
            "code": code, "grant_type": "authorization_code",
            "redirect_uri": f"{BASE_URL}/auth/apple/callback",
        })
        resp.raise_for_status()
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
    claims = jwt.decode(id_token, key, algorithms=["RS256"], audience=APPLE_CLIENT_ID)
    return {"sub": claims.get("sub"), "email": claims.get("email"), "name": None}
