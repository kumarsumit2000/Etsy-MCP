"""OAuth 2.0 PKCE helpers + token storage + access-token refresh.

The MCP runtime calls get_access_token() before every API request. It reads
.tokens.json, refreshes if the access token is within 60 seconds of expiry,
and persists the rotated refresh token atomically.

The bootstrap script (scripts/bootstrap_oauth.py) uses generate_pkce_pair()
and TokenStore.save() to seed .tokens.json the first time.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

import httpx

from .errors import AuthInvalid, RefreshTokenExpired


def generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) per RFC 7636 with S256.

    Verifier: 64 URL-safe chars (well within the 43-128 spec range).
    Challenge: base64url(SHA256(verifier)) with trailing '=' stripped.
    """
    verifier = secrets.token_urlsafe(48)[:64]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


class TokenStore:
    """Persist OAuth tokens to a JSON file with atomic writes.

    File shape:
        {
          "access_token": str,
          "refresh_token": str,
          "expires_at": float (unix seconds),
          "obtained_at": float (unix seconds),
          "scope": str
        }
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        with self.path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def save(
        self,
        *,
        access_token: str,
        refresh_token: str,
        expires_in: int,
        scope: str,
    ) -> None:
        now = time.time()
        payload = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": now + expires_in,
            "obtained_at": now,
            "scope": scope,
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise


ETSY_TOKEN_URL = "https://api.etsy.com/v3/public/oauth/token"
REFRESH_LEEWAY_SECONDS = 60


async def refresh_access_token(
    *,
    keystring: str,
    tokens_path: str | Path,
) -> str:
    """Hit Etsy's refresh endpoint, persist new tokens (rotation included), return access_token.

    Raises:
        RefreshTokenExpired: refresh token expired (90 days) or revoked.
        AuthInvalid: keystring invalid.
    """
    store = TokenStore(tokens_path)
    current = store.load()

    payload = {
        "grant_type": "refresh_token",
        "client_id": keystring,
        "refresh_token": current["refresh_token"],
    }

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(ETSY_TOKEN_URL, data=payload)

    if resp.status_code == 400:
        body = _safe_json(resp)
        if body.get("error") == "invalid_grant":
            raise RefreshTokenExpired(
                "Refresh token expired or revoked. Re-run scripts/bootstrap_oauth.py.",
                details=body,
            )
        raise AuthInvalid(
            f"Token refresh failed (400): {body.get('error_description', 'no description')}",
            details=body,
        )
    if resp.status_code in (401, 403):
        raise AuthInvalid(
            f"Token refresh rejected ({resp.status_code}). Check ETSY_KEYSTRING.",
            details=_safe_json(resp),
        )
    resp.raise_for_status()

    body = resp.json()
    store.save(
        access_token=body["access_token"],
        refresh_token=body["refresh_token"],
        expires_in=body["expires_in"],
        scope=body.get("scope", current.get("scope", "")),
    )
    return body["access_token"]


async def get_access_token(
    *,
    keystring: str,
    tokens_path: str | Path,
) -> str:
    """Return a valid access token, refreshing if it expires within the leeway window."""
    current = TokenStore(tokens_path).load()
    if current["expires_at"] - time.time() > REFRESH_LEEWAY_SECONDS:
        return current["access_token"]
    return await refresh_access_token(keystring=keystring, tokens_path=tokens_path)


def _safe_json(resp: httpx.Response) -> dict[str, Any]:
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text[:500]}
