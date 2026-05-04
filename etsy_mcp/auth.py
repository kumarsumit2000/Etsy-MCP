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
import secrets


def generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) per RFC 7636 with S256.

    Verifier: 64 URL-safe chars (well within the 43-128 spec range).
    Challenge: base64url(SHA256(verifier)) with trailing '=' stripped.
    """
    verifier = secrets.token_urlsafe(48)[:64]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge
