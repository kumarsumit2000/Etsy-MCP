"""One-time OAuth 2.0 PKCE bootstrap for Etsy MCP.

Usage:
    python scripts/bootstrap_oauth.py

Prerequisites:
    - .env with ETSY_KEYSTRING and ETSY_SHARED_SECRET set
    - Your Etsy app's redirect URI configured to http://localhost:3003/callback

Behavior:
    1. Generates PKCE verifier + challenge.
    2. Spins up a localhost HTTP server on $ETSY_OAUTH_REDIRECT_PORT (default 3003).
    3. Opens your default browser to the Etsy authorize URL.
    4. After you click "Allow", Etsy redirects to /callback?code=...&state=...
    5. Exchanges code for tokens, writes .tokens.json.
    6. Calls /users/me + /users/{id}/shops to fetch shop_id, prints it.
"""

from __future__ import annotations

import os
import secrets
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from etsy_mcp.auth import TokenStore, generate_pkce_pair, ETSY_TOKEN_URL  # noqa: E402

ETSY_AUTHORIZE_URL = "https://www.etsy.com/oauth/connect"
ETSY_API_BASE = "https://openapi.etsy.com/v3"

SCOPES = [
    "listings_r", "listings_w", "listings_d",
    "shops_r", "shops_w",
    "transactions_r", "transactions_w",
    "feedback_r",
    "email_r", "profile_r", "address_r",
]


class _CallbackState:
    """Threadsafe one-shot holder for the OAuth callback result."""
    code: str | None = None
    state: str | None = None
    error: str | None = None
    received = threading.Event()


def _make_handler(expected_state: str, holder: _CallbackState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a, **kw):
            pass  # silence default access log

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            qs = urllib.parse.parse_qs(parsed.query)
            err = qs.get("error", [None])[0]
            code = qs.get("code", [None])[0]
            state = qs.get("state", [None])[0]

            if err:
                holder.error = err
                self._respond(400, f"OAuth error: {err}")
            elif state != expected_state:
                holder.error = "state_mismatch"
                self._respond(400, "OAuth state mismatch — possible CSRF.")
            elif not code:
                holder.error = "missing_code"
                self._respond(400, "Missing code parameter.")
            else:
                holder.code = code
                holder.state = state
                self._respond(
                    200,
                    "Authorization received. You can close this tab and return to the terminal.",
                )
            holder.received.set()

        def _respond(self, status: int, body: str):
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

    return Handler


def main() -> int:
    load_dotenv(ROOT / ".env")
    keystring = os.environ.get("ETSY_KEYSTRING", "").strip()
    shared_secret = os.environ.get("ETSY_SHARED_SECRET", "").strip()
    port = int(os.environ.get("ETSY_OAUTH_REDIRECT_PORT", "3003"))

    if not keystring or not shared_secret:
        print("ERROR: ETSY_KEYSTRING and ETSY_SHARED_SECRET must be set in .env", file=sys.stderr)
        return 2

    # If ETSY_OAUTH_REDIRECT_URI is set (e.g. Cloudflare Tunnel public URL),
    # use it as the redirect_uri sent to Etsy. The local callback server still
    # listens on $port — the tunnel proxies the public URL back to it.
    redirect_uri = os.environ.get("ETSY_OAUTH_REDIRECT_URI", "").strip() \
        or f"http://localhost:{port}/callback"
    verifier, challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(24)

    auth_params = {
        "response_type": "code",
        "client_id": keystring,
        "redirect_uri": redirect_uri,
        "scope": " ".join(SCOPES),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    auth_url = f"{ETSY_AUTHORIZE_URL}?{urllib.parse.urlencode(auth_params)}"

    holder = _CallbackState()
    server = HTTPServer(("127.0.0.1", port), _make_handler(state, holder))
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    print(f"Opening browser to authorize…\n  {auth_url}\n")
    webbrowser.open(auth_url)
    print(f"Waiting for redirect on http://localhost:{port}/callback (timeout 5 min)…")
    if not holder.received.wait(timeout=300):
        print("ERROR: timed out waiting for OAuth redirect.", file=sys.stderr)
        return 3
    server.server_close()

    if holder.error or not holder.code:
        print(f"ERROR: OAuth callback failed: {holder.error}", file=sys.stderr)
        return 4

    # Exchange code → tokens
    print("Authorization received. Exchanging code for tokens…")
    with httpx.Client(timeout=20) as client:
        resp = client.post(
            ETSY_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": keystring,
                "redirect_uri": redirect_uri,
                "code": holder.code,
                "code_verifier": verifier,
            },
        )
    if resp.status_code != 200:
        print(f"ERROR: token exchange failed ({resp.status_code}): {resp.text}", file=sys.stderr)
        return 5
    body = resp.json()

    tokens_path = ROOT / ".tokens.json"
    TokenStore(tokens_path).save(
        access_token=body["access_token"],
        refresh_token=body["refresh_token"],
        expires_in=body["expires_in"],
        scope=body.get("scope", " ".join(SCOPES)),
    )
    print(f"Tokens saved to {tokens_path}")

    # Fetch shop_id. Etsy requires "<keystring>:<shared_secret>" in x-api-key
    # for OAuth-authenticated calls on approved apps.
    print("Fetching shop_id…")
    headers = {
        "x-api-key": f"{keystring}:{shared_secret}",
        "Authorization": f"Bearer {body['access_token']}",
    }
    with httpx.Client(timeout=20) as client:
        me = client.get(f"{ETSY_API_BASE}/application/users/me", headers=headers)
        if me.status_code != 200:
            print(f"WARN: /users/me returned {me.status_code}: {me.text}", file=sys.stderr)
            print("Tokens were saved, but couldn't auto-fetch shop_id. Set ETSY_SHOP_ID manually.")
            return 0
        user_id = me.json()["user_id"]

        shops = client.get(
            f"{ETSY_API_BASE}/application/users/{user_id}/shops",
            headers=headers,
        )
        if shops.status_code != 200:
            print(f"WARN: /users/{user_id}/shops returned {shops.status_code}", file=sys.stderr)
            print("Set ETSY_SHOP_ID manually after browsing your shop on etsy.com.")
            return 0

    shop_data = shops.json()
    # Etsy may wrap as {results: [...]} or return single object — handle both
    shop = shop_data["results"][0] if "results" in shop_data else shop_data
    shop_id = shop.get("shop_id") or shop.get("id")
    shop_name = shop.get("shop_name") or shop.get("name", "?")

    print()
    print("=" * 60)
    print(f"  Shop: {shop_name}")
    print(f"  shop_id: {shop_id}")
    print("=" * 60)
    print(f"\nAdd this to your .env:\n\n  ETSY_SHOP_ID={shop_id}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
