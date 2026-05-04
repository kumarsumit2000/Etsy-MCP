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
