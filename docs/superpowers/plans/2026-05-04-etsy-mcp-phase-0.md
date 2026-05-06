# Etsy MCP — Phase 0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lay the foundation: a working MCP server with OAuth 2.0 PKCE bootstrap, automatic access-token refresh with rotation, rate-limited HTTP wrapper, and two functioning tools (`etsy_whoami`, `etsy_token_status`) that prove end-to-end auth works against the real Etsy API.

**Architecture:** Python 3.10+ package `etsy_mcp/` modularized by concern (`auth`, `http`, `errors`); FastMCP server in `server.py`; one-time CLI bootstrap script that runs the OAuth PKCE flow with a localhost callback. Refresh tokens rotate on every refresh and are persisted atomically. Every API call funnels through a single `etsy_request()` that handles rate limiting, retries, and 401-triggered token refresh.

**Tech Stack:** Python 3.10+, `mcp[cli]` (FastMCP), `httpx` (async), `python-dotenv`, `pytest` + `pytest-asyncio`. PKCE built on stdlib (`secrets`, `hashlib`, `base64`); OAuth callback uses stdlib `http.server`.

**Spec:** `docs/superpowers/specs/2026-05-04-etsy-mcp-design.md`

---

## File Structure (Phase 0 only)

```
~/Desktop/Etsy MCP/
├── etsy_mcp/
│   ├── __init__.py            # package marker, version constant
│   ├── errors.py              # error code constants + structured-error helper
│   ├── auth.py                # TokenStore + access-token refresh
│   └── http.py                # rate limiter + etsy_request wrapper
├── scripts/
│   └── bootstrap_oauth.py     # one-time OAuth PKCE flow → .tokens.json
├── tests/
│   ├── __init__.py
│   ├── conftest.py            # pytest-asyncio config, shared fixtures
│   └── unit/
│       ├── __init__.py
│       ├── test_errors.py
│       ├── test_auth.py
│       ├── test_http.py
│       └── test_pkce.py
├── .env.example
├── .gitignore                 # already exists
├── pytest.ini
├── requirements.txt
├── requirements-dev.txt
├── README.md
├── SETUP.md                   # walkthrough: Etsy dev account → app → bootstrap
└── server.py                  # FastMCP entrypoint, registers etsy_whoami + etsy_token_status
```

**Why this split:** `auth.py` only knows about tokens; `http.py` only knows about HTTP semantics; `errors.py` is shared by both. `server.py` stays thin — it imports tools and registers them. This makes Phase 1+ additions trivial: each new domain (`listings.py`, `receipts.py`, etc.) imports `etsy_request` from `http.py` and exposes tools that `server.py` registers.

---

## Task 1: Project scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `pytest.ini`
- Create: `.env.example`
- Create: `README.md`
- Create: `SETUP.md`
- Create: `etsy_mcp/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/unit/__init__.py`

- [ ] **Step 1: Create the Python virtual environment**

```bash
cd "<project root>"
python3 -m venv .venv
source .venv/bin/activate
python --version
```

Expected: `Python 3.10.x` or higher. If lower, install Python 3.10+ first via `brew install python@3.12`.

- [ ] **Step 2: Write `requirements.txt`**

```
mcp[cli]>=1.2.0
httpx>=0.27.0
python-dotenv>=1.0.0
```

- [ ] **Step 3: Write `requirements-dev.txt`**

```
-r requirements.txt
pytest>=8.0.0
pytest-asyncio>=0.23.0
respx>=0.21.0
```

- [ ] **Step 4: Install dependencies**

```bash
pip install -r requirements-dev.txt
```

Expected: installs without errors. Confirm with `pip list | grep -E 'mcp|httpx|pytest'`.

- [ ] **Step 5: Write `pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
filterwarnings =
    ignore::DeprecationWarning
```

- [ ] **Step 6: Write `.env.example`**

```
# Etsy API credentials — get from https://www.etsy.com/developers/your-apps
ETSY_KEYSTRING=your_keystring_here
ETSY_SHARED_SECRET=your_shared_secret_here

# Populated by bootstrap_oauth.py — paste the printed shop_id here after running it
ETSY_SHOP_ID=

# Optional
ETSY_LOG_LEVEL=INFO
ETSY_OAUTH_REDIRECT_PORT=3003
```

- [ ] **Step 7: Write `etsy_mcp/__init__.py`**

```python
"""Etsy MCP — Shopify-style MCP server for the Etsy Open API v3."""

__version__ = "0.1.0"
```

- [ ] **Step 8: Write `tests/__init__.py` and `tests/unit/__init__.py`**

Both files empty (just package markers).

```bash
touch tests/__init__.py tests/unit/__init__.py
```

- [ ] **Step 9: Write `tests/conftest.py`**

```python
"""Shared pytest fixtures for Etsy MCP tests."""

import pytest


@pytest.fixture
def tmp_tokens_path(tmp_path):
    """Provide a temp path for .tokens.json that's isolated per test."""
    return tmp_path / "tokens.json"
```

- [ ] **Step 10: Write minimal `README.md`**

```markdown
# Etsy MCP

Python MCP server for managing an Etsy shop end-to-end from Claude.

**Status:** Phase 0 — auth foundation. See [docs/superpowers/specs/2026-05-04-etsy-mcp-design.md](docs/superpowers/specs/2026-05-04-etsy-mcp-design.md) for full design.

## Quick start

1. Follow [SETUP.md](SETUP.md) to create your Etsy developer app.
2. Copy `.env.example` to `.env` and fill in `ETSY_KEYSTRING` and `ETSY_SHARED_SECRET`.
3. Run the OAuth bootstrap:
   ```bash
   source .venv/bin/activate
   python scripts/bootstrap_oauth.py
   ```
4. Paste the printed `shop_id` into `.env` as `ETSY_SHOP_ID`.
5. Add the MCP to Claude Code (see SETUP.md § "Wire MCP into Claude").
6. From Claude, call `etsy_whoami` to verify.

## Layout

```
etsy_mcp/         Python package — auth, http, errors
scripts/          one-time bootstrap scripts
tests/            pytest suite
server.py         FastMCP entrypoint
```

## Development

```bash
pip install -r requirements-dev.txt
pytest                 # run unit tests
pytest -v -k auth      # focused
```
```

- [ ] **Step 11: Write `SETUP.md`**

```markdown
# Etsy MCP — Setup Walkthrough

## 1. Create an Etsy developer account

1. Go to https://www.etsy.com/developers/register and sign in with your Etsy account.
2. Accept the API terms.

## 2. Create an app

1. Go to https://www.etsy.com/developers/your-apps and click **Create a New App**.
2. Fill in:
   - **Name:** Etsy MCP (or anything)
   - **Description:** Personal MCP server
   - **Website:** any URL you control (or `http://localhost`)
   - **What kind of app:** "I'm building an app for myself"
3. After creation, you'll see your **Keystring** (API key) and **Shared Secret**. Copy both.
4. Click **Edit** on your app and add this OAuth redirect URI:
   ```
   http://localhost:3003/callback
   ```
   Save.

## 3. Configure local environment

```bash
cd "<project root>"
cp .env.example .env
# Open .env and paste your Keystring + Shared Secret
```

## 4. Run the OAuth bootstrap

```bash
source .venv/bin/activate
python scripts/bootstrap_oauth.py
```

What happens:
1. Script opens your default browser to Etsy's authorization page.
2. Click **Allow Access**.
3. Browser redirects to `localhost:3003/callback`. The script captures the auth code.
4. Script exchanges the code for access + refresh tokens and writes them to `.tokens.json`.
5. Script prints your `shop_id`. Paste it into `.env` as `ETSY_SHOP_ID`.

If anything fails, the script prints a clear error. Re-run after fixing.

## 5. Wire MCP into Claude Code

Edit `~/.claude/claude_desktop_config.json` (or your project-scoped config) and add:

```json
{
  "mcpServers": {
    "etsy": {
      "command": "<project root>/.venv/bin/python",
      "args": ["<project root>/server.py"]
    }
  }
}
```

Restart Claude Code. From a chat, call `etsy_whoami` — you should see your shop info.

## 6. When refresh tokens expire (every 90 days)

You'll see this error from any tool:
```
{"error": "Refresh token expired. Re-run scripts/bootstrap_oauth.py", "code": "auth_expired"}
```

Just re-run `python scripts/bootstrap_oauth.py`. Takes 30 seconds.
```

- [ ] **Step 12: Verify scaffolding by running pytest (should find no tests yet)**

```bash
pytest
```

Expected: `no tests ran in 0.0Xs`. This confirms pytest is configured correctly.

- [ ] **Step 13: Commit**

```bash
git add requirements.txt requirements-dev.txt pytest.ini .env.example README.md SETUP.md etsy_mcp/__init__.py tests/__init__.py tests/conftest.py tests/unit/__init__.py
git commit -m "$(cat <<'EOF'
chore: scaffold Etsy MCP project

Python 3.10+ project with mcp/httpx/python-dotenv runtime deps and
pytest/pytest-asyncio/respx dev deps. README + SETUP walkthrough for
Etsy dev account creation and OAuth bootstrap.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Errors module

**Files:**
- Create: `etsy_mcp/errors.py`
- Create: `tests/unit/test_errors.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_errors.py
"""Tests for etsy_mcp.errors."""

from etsy_mcp.errors import (
    ErrorCode,
    structured_error,
    EtsyMCPError,
    RefreshTokenExpired,
    RateLimited,
)


def test_structured_error_basic():
    result = structured_error("Something broke", ErrorCode.UNKNOWN)
    assert result == {
        "error": "Something broke",
        "code": "unknown",
    }


def test_structured_error_with_details():
    result = structured_error(
        "Field invalid",
        ErrorCode.VALIDATION_FAILED,
        details={"field": "price", "reason": "must be > 0"},
    )
    assert result == {
        "error": "Field invalid",
        "code": "validation_failed",
        "details": {"field": "price", "reason": "must be > 0"},
    }


def test_error_code_values():
    # Codes used across the project — verify they exist with expected string values.
    assert ErrorCode.AUTH_EXPIRED.value == "auth_expired"
    assert ErrorCode.AUTH_INVALID.value == "auth_invalid"
    assert ErrorCode.NOT_FOUND.value == "not_found"
    assert ErrorCode.RATE_LIMITED.value == "rate_limited"
    assert ErrorCode.VALIDATION_FAILED.value == "validation_failed"
    assert ErrorCode.NETWORK.value == "network"
    assert ErrorCode.SESSION_EXPIRED.value == "session_expired"
    assert ErrorCode.SELECTOR_MISSING.value == "selector_missing"
    assert ErrorCode.UNKNOWN.value == "unknown"


def test_refresh_token_expired_is_etsy_mcp_error():
    err = RefreshTokenExpired("expired")
    assert isinstance(err, EtsyMCPError)
    assert err.code == ErrorCode.AUTH_EXPIRED


def test_rate_limited_carries_retry_after():
    err = RateLimited("429", retry_after=5)
    assert err.retry_after == 5
    assert err.code == ErrorCode.RATE_LIMITED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_errors.py -v`
Expected: FAIL with `ImportError: cannot import name 'ErrorCode' from 'etsy_mcp.errors'` (module doesn't exist).

- [ ] **Step 3: Write the implementation**

```python
# etsy_mcp/errors.py
"""Error codes and exceptions for Etsy MCP.

Every tool returns either the success payload (dict/list) or the result of
structured_error(). Internal code raises EtsyMCPError subclasses; the HTTP
wrapper or tool entrypoint converts them to structured-error dicts.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    AUTH_EXPIRED = "auth_expired"
    AUTH_INVALID = "auth_invalid"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    VALIDATION_FAILED = "validation_failed"
    NETWORK = "network"
    SESSION_EXPIRED = "session_expired"
    SELECTOR_MISSING = "selector_missing"
    UNKNOWN = "unknown"


def structured_error(
    message: str,
    code: ErrorCode,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canonical error dict returned by MCP tools."""
    out: dict[str, Any] = {"error": message, "code": code.value}
    if details is not None:
        out["details"] = details
    return out


class EtsyMCPError(Exception):
    """Base exception for all Etsy MCP errors."""

    code: ErrorCode = ErrorCode.UNKNOWN

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        return structured_error(self.message, self.code, self.details)


class AuthInvalid(EtsyMCPError):
    code = ErrorCode.AUTH_INVALID


class RefreshTokenExpired(EtsyMCPError):
    code = ErrorCode.AUTH_EXPIRED


class RateLimited(EtsyMCPError):
    code = ErrorCode.RATE_LIMITED

    def __init__(
        self,
        message: str,
        retry_after: int | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message, details)
        self.retry_after = retry_after


class NotFound(EtsyMCPError):
    code = ErrorCode.NOT_FOUND


class ValidationFailed(EtsyMCPError):
    code = ErrorCode.VALIDATION_FAILED


class NetworkError(EtsyMCPError):
    code = ErrorCode.NETWORK
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_errors.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add etsy_mcp/errors.py tests/unit/test_errors.py
git commit -m "$(cat <<'EOF'
feat(errors): add ErrorCode enum and exception hierarchy

Single source of truth for error codes used across the MCP. EtsyMCPError
subclasses carry their code; structured_error() produces the dict shape
returned by tools.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: PKCE helpers (TDD)

**Files:**
- Create: `etsy_mcp/auth.py` (will be extended in Task 4)
- Create: `tests/unit/test_pkce.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_pkce.py
"""Tests for PKCE code-verifier and code-challenge generation."""

import base64
import hashlib
import re

from etsy_mcp.auth import generate_pkce_pair


def test_verifier_length_and_charset():
    verifier, _ = generate_pkce_pair()
    # RFC 7636: 43-128 chars, [A-Z][a-z][0-9]-._~
    assert 43 <= len(verifier) <= 128
    assert re.fullmatch(r"[A-Za-z0-9\-._~]+", verifier)


def test_challenge_is_s256_of_verifier():
    verifier, challenge = generate_pkce_pair()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    assert challenge == expected


def test_pairs_are_unique():
    pairs = {generate_pkce_pair()[0] for _ in range(50)}
    assert len(pairs) == 50  # cryptographically vanishing chance of collision
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_pkce.py -v`
Expected: FAIL with `ImportError: cannot import name 'generate_pkce_pair'`.

- [ ] **Step 3: Write the implementation (start of `etsy_mcp/auth.py`)**

```python
# etsy_mcp/auth.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_pkce.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add etsy_mcp/auth.py tests/unit/test_pkce.py
git commit -m "$(cat <<'EOF'
feat(auth): PKCE verifier/challenge generation per RFC 7636 (S256)

64-char URL-safe verifier; challenge is base64url(SHA256(verifier))
with padding stripped. Uses secrets module for cryptographic randomness.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: TokenStore (load/save with atomic write)

**Files:**
- Modify: `etsy_mcp/auth.py` (extend with TokenStore)
- Create: `tests/unit/test_auth.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_auth.py
"""Tests for TokenStore: load, save, atomic write, round-trip."""

import json
import time

import pytest

from etsy_mcp.auth import TokenStore


def test_save_then_load_round_trip(tmp_tokens_path):
    store = TokenStore(tmp_tokens_path)
    store.save(
        access_token="acc-1",
        refresh_token="ref-1",
        expires_in=3600,
        scope="listings_r",
    )

    loaded = TokenStore(tmp_tokens_path).load()
    assert loaded["access_token"] == "acc-1"
    assert loaded["refresh_token"] == "ref-1"
    assert loaded["scope"] == "listings_r"
    # expires_at is now() + expires_in, give or take 5 seconds for test runtime.
    assert abs(loaded["expires_at"] - (time.time() + 3600)) < 5


def test_load_missing_file_raises(tmp_tokens_path):
    store = TokenStore(tmp_tokens_path)
    with pytest.raises(FileNotFoundError):
        store.load()


def test_save_is_atomic_no_partial_file(tmp_tokens_path, monkeypatch):
    """If serialization succeeds but rename is interrupted, the destination
    must contain either the old content or nothing — never a half-written file.
    """
    store = TokenStore(tmp_tokens_path)
    store.save(
        access_token="acc-1",
        refresh_token="ref-1",
        expires_in=3600,
        scope="listings_r",
    )
    original = tmp_tokens_path.read_text()

    # Make os.replace blow up — the destination file should still hold the
    # original content (the .tmp file is what got written, not the target).
    import os
    real_replace = os.replace

    def explode(*a, **kw):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(os, "replace", explode)

    with pytest.raises(OSError):
        store.save(
            access_token="acc-2",
            refresh_token="ref-2",
            expires_in=3600,
            scope="listings_r",
        )

    monkeypatch.setattr(os, "replace", real_replace)
    assert tmp_tokens_path.read_text() == original


def test_save_persists_obtained_at(tmp_tokens_path):
    before = time.time()
    TokenStore(tmp_tokens_path).save(
        access_token="acc",
        refresh_token="ref",
        expires_in=3600,
        scope="x",
    )
    after = time.time()
    loaded = TokenStore(tmp_tokens_path).load()
    assert before <= loaded["obtained_at"] <= after


def test_save_omits_tmp_file_after_success(tmp_tokens_path):
    TokenStore(tmp_tokens_path).save(
        access_token="acc",
        refresh_token="ref",
        expires_in=3600,
        scope="x",
    )
    tmp_path = tmp_tokens_path.with_suffix(tmp_tokens_path.suffix + ".tmp")
    assert not tmp_path.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_auth.py -v`
Expected: FAIL with `ImportError: cannot import name 'TokenStore'`.

- [ ] **Step 3: Extend `etsy_mcp/auth.py` with TokenStore**

Append to `etsy_mcp/auth.py` (after the `generate_pkce_pair` function):

```python
import json
import os
import time
from pathlib import Path
from typing import Any


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
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
```

Also add the import at the top of the file (next to the existing imports):

```python
# (top of etsy_mcp/auth.py — add to the existing import block)
import json
import os
import time
from pathlib import Path
from typing import Any
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_auth.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add etsy_mcp/auth.py tests/unit/test_auth.py
git commit -m "$(cat <<'EOF'
feat(auth): TokenStore with atomic-write persistence

Writes via .tmp file + os.replace so the live tokens.json is never
half-written. Computes absolute expires_at from expires_in at save time.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Token refresh with rotation (TDD)

**Files:**
- Modify: `etsy_mcp/auth.py`
- Modify: `tests/unit/test_auth.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_auth.py`:

```python
import respx
import httpx

from etsy_mcp.auth import (
    refresh_access_token,
    get_access_token,
    ETSY_TOKEN_URL,
)
from etsy_mcp.errors import RefreshTokenExpired, AuthInvalid


@respx.mock
async def test_refresh_rotates_refresh_token(tmp_tokens_path):
    """Etsy returns a NEW refresh token on every refresh — the new one must be persisted."""
    TokenStore(tmp_tokens_path).save(
        access_token="old-acc",
        refresh_token="old-ref",
        expires_in=10,  # near expiry
        scope="listings_r",
    )

    respx.post(ETSY_TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "new-acc",
                "refresh_token": "new-ref",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )
    )

    new_access = await refresh_access_token(
        keystring="kkey",
        tokens_path=tmp_tokens_path,
    )

    assert new_access == "new-acc"
    persisted = TokenStore(tmp_tokens_path).load()
    assert persisted["access_token"] == "new-acc"
    assert persisted["refresh_token"] == "new-ref"  # rotation persisted


@respx.mock
async def test_refresh_invalid_grant_raises_refresh_token_expired(tmp_tokens_path):
    TokenStore(tmp_tokens_path).save(
        access_token="acc",
        refresh_token="ref-dead",
        expires_in=10,
        scope="x",
    )
    respx.post(ETSY_TOKEN_URL).mock(
        return_value=httpx.Response(
            400,
            json={"error": "invalid_grant", "error_description": "expired"},
        )
    )

    with pytest.raises(RefreshTokenExpired):
        await refresh_access_token(keystring="kkey", tokens_path=tmp_tokens_path)


@respx.mock
async def test_refresh_invalid_client_raises_auth_invalid(tmp_tokens_path):
    TokenStore(tmp_tokens_path).save(
        access_token="acc",
        refresh_token="ref",
        expires_in=10,
        scope="x",
    )
    respx.post(ETSY_TOKEN_URL).mock(
        return_value=httpx.Response(
            401,
            json={"error": "invalid_client"},
        )
    )

    with pytest.raises(AuthInvalid):
        await refresh_access_token(keystring="kkey", tokens_path=tmp_tokens_path)


async def test_get_access_token_returns_cached_when_not_expiring(tmp_tokens_path):
    TokenStore(tmp_tokens_path).save(
        access_token="cached-acc",
        refresh_token="ref",
        expires_in=3600,  # 1 hour out — well above the 60s refresh threshold
        scope="x",
    )
    result = await get_access_token(keystring="kkey", tokens_path=tmp_tokens_path)
    assert result == "cached-acc"


@respx.mock
async def test_get_access_token_refreshes_when_within_60s_of_expiry(tmp_tokens_path):
    TokenStore(tmp_tokens_path).save(
        access_token="stale-acc",
        refresh_token="ref-1",
        expires_in=30,  # under 60s threshold
        scope="x",
    )
    respx.post(ETSY_TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "fresh-acc",
                "refresh_token": "ref-2",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )
    )

    result = await get_access_token(keystring="kkey", tokens_path=tmp_tokens_path)
    assert result == "fresh-acc"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_auth.py -v`
Expected: FAIL with `ImportError: cannot import name 'refresh_access_token'`.

- [ ] **Step 3: Extend `etsy_mcp/auth.py` with refresh logic**

Append to `etsy_mcp/auth.py`:

```python
import httpx

from .errors import AuthInvalid, RefreshTokenExpired

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_auth.py -v`
Expected: 10 passed (5 from Task 4 + 5 new).

- [ ] **Step 5: Commit**

```bash
git add etsy_mcp/auth.py tests/unit/test_auth.py
git commit -m "$(cat <<'EOF'
feat(auth): refresh_access_token with rotation + get_access_token caching

Refresh endpoint persists new refresh_token (rotation is mandatory; failing
to do so bricks auth on next call). get_access_token reuses the cached
access token until within 60s of expiry, then refreshes silently.

invalid_grant from Etsy → RefreshTokenExpired (user must re-bootstrap).
401/403 → AuthInvalid (keystring/secret wrong).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Rate limiter (TDD)

**Files:**
- Create: `etsy_mcp/http.py` (will be extended in Task 7)
- Create: `tests/unit/test_http.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_http.py
"""Tests for rate limiter and etsy_request HTTP wrapper."""

import asyncio
import time

import pytest

from etsy_mcp.http import RateLimiter


async def test_rate_limiter_allows_burst_up_to_capacity():
    rl = RateLimiter(rate_per_second=10, capacity=10)
    start = time.monotonic()
    for _ in range(10):
        await rl.acquire()
    elapsed = time.monotonic() - start
    assert elapsed < 0.05  # 10 acquires from a full bucket should be near-instant


async def test_rate_limiter_throttles_when_empty():
    rl = RateLimiter(rate_per_second=10, capacity=2)
    # Drain the bucket
    await rl.acquire()
    await rl.acquire()
    # Next acquire must wait ~100ms (1 token at 10/s)
    start = time.monotonic()
    await rl.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.08  # allow ~20ms slack for scheduler
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_http.py -v`
Expected: FAIL with `ImportError: cannot import name 'RateLimiter'`.

- [ ] **Step 3: Write `etsy_mcp/http.py` with RateLimiter**

```python
# etsy_mcp/http.py
"""HTTP wrapper for the Etsy Open API v3.

All API-driven tools call etsy_request(). The wrapper handles:
- in-process rate limiting (token bucket, default 10 req/s)
- 401 → automatic token refresh + one retry
- 429 → honor Retry-After, retry up to 3 times
- 5xx → exponential backoff, retry up to 3 times
- network errors → one retry after 1s
- terminal failure → raise the right EtsyMCPError subclass
"""

from __future__ import annotations

import asyncio
import time


class RateLimiter:
    """Token-bucket limiter. Default 10/s matches Etsy's per-app limit.

    Note on the lock: we acquire-and-release the internal lock per iteration
    rather than holding it across asyncio.sleep() so other coroutines can
    refill the bucket independently. The loop will re-check tokens after
    sleeping.
    """

    def __init__(self, rate_per_second: float = 10.0, capacity: int = 10):
        self.rate = rate_per_second
        self.capacity = float(capacity)
        self._tokens = float(capacity)
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                self._tokens = min(
                    self.capacity,
                    self._tokens + (now - self._last) * self.rate,
                )
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self.rate
            await asyncio.sleep(wait)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_http.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add etsy_mcp/http.py tests/unit/test_http.py
git commit -m "$(cat <<'EOF'
feat(http): token-bucket RateLimiter (default 10/s)

Matches Etsy's per-app rate limit. Allows bursting up to capacity, then
sleeps to spread requests out. Async-safe via single internal lock.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: etsy_request wrapper (TDD)

**Files:**
- Modify: `etsy_mcp/http.py`
- Modify: `tests/unit/test_http.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_http.py`:

```python
import httpx
import respx

from etsy_mcp.http import etsy_request, ETSY_API_BASE
from etsy_mcp.auth import TokenStore
from etsy_mcp.errors import (
    EtsyMCPError,
    NotFound,
    RateLimited,
    NetworkError,
    AuthInvalid,
)


def _seed_tokens(path, expires_in=3600):
    TokenStore(path).save(
        access_token="acc",
        refresh_token="ref",
        expires_in=expires_in,
        scope="listings_r",
    )


@respx.mock
async def test_request_returns_json_on_200(tmp_tokens_path):
    _seed_tokens(tmp_tokens_path)
    respx.get(f"{ETSY_API_BASE}/application/users/me").mock(
        return_value=httpx.Response(200, json={"user_id": 12345})
    )

    result = await etsy_request(
        "GET",
        "/application/users/me",
        keystring="kkey",
        tokens_path=tmp_tokens_path,
    )
    assert result == {"user_id": 12345}


@respx.mock
async def test_request_raises_not_found_on_404(tmp_tokens_path):
    _seed_tokens(tmp_tokens_path)
    respx.get(f"{ETSY_API_BASE}/application/listings/999").mock(
        return_value=httpx.Response(404, json={"error": "Listing not found"})
    )

    with pytest.raises(NotFound):
        await etsy_request(
            "GET",
            "/application/listings/999",
            keystring="kkey",
            tokens_path=tmp_tokens_path,
        )


@respx.mock
async def test_request_retries_429_with_retry_after(tmp_tokens_path):
    _seed_tokens(tmp_tokens_path)
    route = respx.get(f"{ETSY_API_BASE}/application/users/me").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"user_id": 1}),
        ]
    )
    result = await etsy_request(
        "GET",
        "/application/users/me",
        keystring="kkey",
        tokens_path=tmp_tokens_path,
    )
    assert result == {"user_id": 1}
    assert route.call_count == 2


@respx.mock
async def test_request_429_after_max_retries_raises(tmp_tokens_path):
    _seed_tokens(tmp_tokens_path)
    respx.get(f"{ETSY_API_BASE}/application/users/me").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "0"})
    )
    with pytest.raises(RateLimited):
        await etsy_request(
            "GET",
            "/application/users/me",
            keystring="kkey",
            tokens_path=tmp_tokens_path,
            max_retries=2,
        )


@respx.mock
async def test_request_retries_5xx_with_backoff(tmp_tokens_path):
    _seed_tokens(tmp_tokens_path)
    route = respx.get(f"{ETSY_API_BASE}/application/users/me").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(200, json={"user_id": 2}),
        ]
    )
    result = await etsy_request(
        "GET",
        "/application/users/me",
        keystring="kkey",
        tokens_path=tmp_tokens_path,
        backoff_base_seconds=0.0,  # speed up test
    )
    assert result == {"user_id": 2}
    assert route.call_count == 2


@respx.mock
async def test_request_401_triggers_refresh_and_retries_once(tmp_tokens_path):
    """Mid-call expiry: even if cached token looks fresh, server can reject.
    Wrapper must refresh and retry exactly once before giving up.
    """
    _seed_tokens(tmp_tokens_path, expires_in=3600)  # appears fresh

    api_route = respx.get(f"{ETSY_API_BASE}/application/users/me").mock(
        side_effect=[
            httpx.Response(401, json={"error": "expired"}),
            httpx.Response(200, json={"user_id": 7}),
        ]
    )
    refresh_route = respx.post("https://api.etsy.com/v3/public/oauth/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "fresh",
                "refresh_token": "ref-new",
                "expires_in": 3600,
            },
        )
    )

    result = await etsy_request(
        "GET",
        "/application/users/me",
        keystring="kkey",
        tokens_path=tmp_tokens_path,
    )
    assert result == {"user_id": 7}
    assert refresh_route.called
    assert api_route.call_count == 2


@respx.mock
async def test_request_401_twice_raises_auth_invalid(tmp_tokens_path):
    _seed_tokens(tmp_tokens_path, expires_in=3600)
    respx.get(f"{ETSY_API_BASE}/application/users/me").mock(
        return_value=httpx.Response(401, json={"error": "expired"})
    )
    respx.post("https://api.etsy.com/v3/public/oauth/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "fresh",
                "refresh_token": "ref-new",
                "expires_in": 3600,
            },
        )
    )
    with pytest.raises(AuthInvalid):
        await etsy_request(
            "GET",
            "/application/users/me",
            keystring="kkey",
            tokens_path=tmp_tokens_path,
        )


@respx.mock
async def test_request_network_error_retried_once(tmp_tokens_path):
    _seed_tokens(tmp_tokens_path)
    route = respx.get(f"{ETSY_API_BASE}/application/users/me").mock(
        side_effect=[
            httpx.ConnectError("boom"),
            httpx.Response(200, json={"user_id": 3}),
        ]
    )
    result = await etsy_request(
        "GET",
        "/application/users/me",
        keystring="kkey",
        tokens_path=tmp_tokens_path,
        backoff_base_seconds=0.0,
    )
    assert result == {"user_id": 3}
    assert route.call_count == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_http.py -v`
Expected: 8 failures (or import errors) — `etsy_request` and `ETSY_API_BASE` don't exist yet.

- [ ] **Step 3: Append `etsy_request` to `etsy_mcp/http.py`**

```python
# Append to etsy_mcp/http.py

import httpx

from .auth import get_access_token, refresh_access_token
from .errors import (
    AuthInvalid,
    NetworkError,
    NotFound,
    RateLimited,
    ValidationFailed,
    EtsyMCPError,
)

ETSY_API_BASE = "https://openapi.etsy.com/v3"

_LIMITER = RateLimiter(rate_per_second=10.0, capacity=10)


async def etsy_request(
    method: str,
    path: str,
    *,
    keystring: str,
    tokens_path: str,
    params: dict | None = None,
    json_body: dict | None = None,
    data: dict | None = None,
    files: dict | None = None,
    max_retries: int = 3,
    backoff_base_seconds: float = 1.0,
    timeout_seconds: float = 30.0,
) -> dict | list:
    """Send a single API request with rate limiting, retries, and 401 refresh.

    Path may be absolute (https://...) or relative (/application/...). Returns
    parsed JSON on success. Raises EtsyMCPError subclasses on failure.
    """
    url = path if path.startswith("http") else f"{ETSY_API_BASE}{path}"
    refreshed_once = False

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        for attempt in range(max_retries + 1):
            await _LIMITER.acquire()
            access_token = await get_access_token(
                keystring=keystring, tokens_path=tokens_path
            )
            headers = {
                "x-api-key": keystring,
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            }
            try:
                resp = await client.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json_body,
                    data=data,
                    files=files,
                )
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
                if attempt >= max_retries:
                    raise NetworkError(f"Network error after {attempt} retries: {exc}") from exc
                await asyncio.sleep(backoff_base_seconds * (2 ** attempt))
                continue

            # Success
            if 200 <= resp.status_code < 300:
                if resp.status_code == 204 or not resp.content:
                    return {}
                return resp.json()

            # Auth: refresh once, then give up
            if resp.status_code == 401:
                if refreshed_once:
                    raise AuthInvalid(
                        "Etsy API returned 401 after token refresh. "
                        "Keystring may be invalid or scopes insufficient.",
                        details=_safe_json(resp),
                    )
                await refresh_access_token(keystring=keystring, tokens_path=tokens_path)
                refreshed_once = True
                continue

            # Rate limit
            if resp.status_code == 429:
                if attempt >= max_retries:
                    raise RateLimited(
                        "Rate limited by Etsy after retries exhausted.",
                        retry_after=_parse_retry_after(resp),
                        details=_safe_json(resp),
                    )
                await asyncio.sleep(_parse_retry_after(resp) or backoff_base_seconds * (2 ** attempt))
                continue

            # 5xx
            if 500 <= resp.status_code < 600:
                if attempt >= max_retries:
                    raise EtsyMCPError(
                        f"Etsy server error {resp.status_code} after {attempt} retries.",
                        details=_safe_json(resp),
                    )
                await asyncio.sleep(backoff_base_seconds * (2 ** attempt))
                continue

            # 404 / 400 / others — terminal
            body = _safe_json(resp)
            if resp.status_code == 404:
                raise NotFound(f"Etsy API: {path} not found.", details=body)
            if resp.status_code == 400:
                raise ValidationFailed(
                    f"Etsy API rejected request: {body.get('error_description') or body.get('error', 'bad request')}",
                    details=body,
                )
            raise EtsyMCPError(
                f"Etsy API returned {resp.status_code}: {body}",
                details=body,
            )

    # Should be unreachable, but defensive.
    raise EtsyMCPError("etsy_request: retry loop exited unexpectedly")


def _parse_retry_after(resp: httpx.Response) -> int:
    raw = resp.headers.get("Retry-After", "").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _safe_json(resp: httpx.Response) -> dict:
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text[:500]}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_http.py -v`
Expected: 10 passed (2 from Task 6 + 8 new).

- [ ] **Step 5: Run full suite to confirm nothing broke**

Run: `pytest -v`
Expected: all tests pass (errors + pkce + auth + http).

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/http.py tests/unit/test_http.py
git commit -m "$(cat <<'EOF'
feat(http): etsy_request wrapper with rate-limit, retries, and 401 refresh

Single entrypoint every API-driven tool will use. Handles 429 (Retry-After),
5xx (exponential backoff), network errors (one retry), and 401 (auto refresh
once via auth.refresh_access_token, then give up).

Maps Etsy responses to the right EtsyMCPError subclass: 404→NotFound,
400→ValidationFailed, 401-after-refresh→AuthInvalid, 429-exhausted→RateLimited.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: OAuth bootstrap script

**Files:**
- Create: `scripts/bootstrap_oauth.py`
- Create: `scripts/__init__.py` (empty)

This is a CLI script with significant procedural complexity (localhost server, browser open, code exchange). Manual verification at the end of this task is the test.

- [ ] **Step 1: Create `scripts/__init__.py`**

```bash
mkdir -p scripts
touch scripts/__init__.py
```

- [ ] **Step 2: Write `scripts/bootstrap_oauth.py`**

```python
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

    redirect_uri = f"http://localhost:{port}/callback"
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

    # Fetch shop_id
    print("Fetching shop_id…")
    headers = {
        "x-api-key": keystring,
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
```

- [ ] **Step 3: Pre-flight: confirm the script imports cleanly**

```bash
source .venv/bin/activate
python -c "import scripts.bootstrap_oauth"
```

Expected: no output, no import errors.

- [ ] **Step 4: Manual end-to-end verification**

Prerequisites: you've completed `SETUP.md` § 1-3 (Etsy dev account + app + `.env` populated with keystring + shared secret).

```bash
source .venv/bin/activate
python scripts/bootstrap_oauth.py
```

Expected:
1. Terminal prints: `Opening browser to authorize…`
2. Browser opens to Etsy's authorize page.
3. Click **Allow Access**.
4. Browser shows: "Authorization received. You can close this tab…"
5. Terminal prints: `Tokens saved to .../.tokens.json`
6. Terminal prints `Shop: <name>` and `shop_id: <number>`.
7. `.tokens.json` exists in project root with all 5 fields.

Paste the printed shop_id into `.env` as `ETSY_SHOP_ID=...`.

If anything fails, the error message tells you what's wrong. Common issues:
- Redirect URI not registered in Etsy app settings → fix at apps.etsy.com.
- Port 3003 in use → set `ETSY_OAUTH_REDIRECT_PORT=3004` in `.env` and add the new redirect URI to your app.

- [ ] **Step 5: Commit**

```bash
git add scripts/__init__.py scripts/bootstrap_oauth.py
git commit -m "$(cat <<'EOF'
feat(scripts): one-time OAuth PKCE bootstrap script

Spins up a stdlib HTTP server on :3003, opens browser to Etsy authorize URL,
captures the code via /callback, exchanges for tokens with PKCE verifier,
persists to .tokens.json, then auto-fetches shop_id via /users/me + /users/{id}/shops.

State parameter checked for CSRF protection. Handles port conflicts via
ETSY_OAUTH_REDIRECT_PORT env var.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: FastMCP server with etsy_whoami and etsy_token_status

**Files:**
- Create: `server.py`

These tools are simple enough that we verify them by manual call from Claude rather than unit tests. The HTTP layer they sit on is fully tested in Task 7.

- [ ] **Step 1: Write `server.py`**

```python
"""Etsy MCP — FastMCP server entrypoint.

Run: python server.py

Phase 0 tools:
- etsy_whoami: verify auth, return user + shop info
- etsy_token_status: report access-token expiry + refresh-token age

Future phases register more tools here by importing from etsy_mcp/<domain>.py.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from etsy_mcp.auth import TokenStore
from etsy_mcp.errors import EtsyMCPError
from etsy_mcp.http import etsy_request

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

KEYSTRING = os.environ.get("ETSY_KEYSTRING", "").strip()
TOKENS_PATH = ROOT / ".tokens.json"

if not KEYSTRING:
    raise RuntimeError(
        "ETSY_KEYSTRING is not set. Copy .env.example to .env and fill it in."
    )

mcp = FastMCP("etsy")


def _err_to_dict(exc: EtsyMCPError) -> dict[str, Any]:
    return exc.to_dict()


@mcp.tool()
async def etsy_whoami() -> dict[str, Any]:
    """Return the authenticated user + their shop.

    Verifies that .tokens.json is valid and the API is reachable. Use this
    as your first call after running the OAuth bootstrap.
    """
    try:
        me = await etsy_request(
            "GET",
            "/application/users/me",
            keystring=KEYSTRING,
            tokens_path=str(TOKENS_PATH),
        )
        user_id = me["user_id"]
        shops_resp = await etsy_request(
            "GET",
            f"/application/users/{user_id}/shops",
            keystring=KEYSTRING,
            tokens_path=str(TOKENS_PATH),
        )
    except EtsyMCPError as exc:
        return _err_to_dict(exc)

    shop = (
        shops_resp["results"][0]
        if isinstance(shops_resp, dict) and "results" in shops_resp
        else shops_resp
    )
    return {
        "user_id": user_id,
        "login_name": me.get("login_name"),
        "primary_email": me.get("primary_email"),
        "shop_id": shop.get("shop_id") or shop.get("id"),
        "shop_name": shop.get("shop_name") or shop.get("name"),
    }


@mcp.tool()
async def etsy_token_status() -> dict[str, Any]:
    """Show access-token expiry and refresh-token age.

    Refresh tokens expire after 90 days. If refresh_age_days exceeds ~85,
    plan to re-run scripts/bootstrap_oauth.py soon.
    """
    try:
        tokens = TokenStore(TOKENS_PATH).load()
    except FileNotFoundError:
        return {
            "error": "No .tokens.json found. Run scripts/bootstrap_oauth.py first.",
            "code": "auth_invalid",
        }

    now = time.time()
    access_remaining = max(0, int(tokens["expires_at"] - now))
    refresh_age_days = int((now - tokens["obtained_at"]) / 86400)
    return {
        "access_expires_in_seconds": access_remaining,
        "refresh_age_days": refresh_age_days,
        "refresh_expires_in_days_estimate": max(0, 90 - refresh_age_days),
        "scope": tokens.get("scope", ""),
    }


if __name__ == "__main__":
    mcp.run()
```

- [ ] **Step 2: Verify the server starts without errors**

```bash
source .venv/bin/activate
timeout 3 python server.py 2>&1 || true
```

Expected: server starts, awaits stdio input (no traceback). `timeout 3` kills it after 3s — that's fine, we just want to confirm there's no startup error.

If you see `RuntimeError: ETSY_KEYSTRING is not set` you haven't filled in `.env` yet — do that first.

- [ ] **Step 3: Wire MCP into Claude Code**

Edit `~/.claude/claude_desktop_config.json` (or your project-scoped MCP config) and add:

```json
{
  "mcpServers": {
    "etsy": {
      "command": "<project root>/.venv/bin/python",
      "args": ["<project root>/server.py"]
    }
  }
}
```

Restart Claude Code. Verify `etsy_whoami` and `etsy_token_status` show up in the tool list.

- [ ] **Step 4: Manual acceptance — call etsy_whoami from Claude**

In a Claude Code chat:

> Call etsy_whoami

Expected: returns `{user_id, login_name, primary_email, shop_id, shop_name}` — real values from your shop.

- [ ] **Step 5: Manual acceptance — call etsy_token_status from Claude**

> Call etsy_token_status

Expected: `{access_expires_in_seconds: <near 3600>, refresh_age_days: 0, refresh_expires_in_days_estimate: 90, scope: "listings_r listings_w ..."}`.

- [ ] **Step 6: Commit**

```bash
git add server.py
git commit -m "$(cat <<'EOF'
feat(server): FastMCP entrypoint with etsy_whoami + etsy_token_status

Two foundational tools that prove end-to-end auth works:
- etsy_whoami: hits /users/me + /users/{id}/shops and returns flattened summary
- etsy_token_status: surfaces access-token expiry and refresh-token age

Both wrap EtsyMCPError → structured-error dict so failures are inspectable
from Claude without crashing the MCP server.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Final verification + push to GitHub

- [ ] **Step 1: Run the full test suite one more time**

```bash
source .venv/bin/activate
pytest -v
```

Expected: all unit tests pass (errors + pkce + auth + http). Approximate count: ~20 tests.

- [ ] **Step 2: Confirm `.env`, `.tokens.json`, and `logs/` are gitignored**

```bash
git status --ignored | grep -E "\.env$|\.tokens\.json|logs/"
```

Expected: shows them under "Ignored files".

- [ ] **Step 3: Confirm no secrets are about to be committed**

```bash
git diff --staged
git log --all --full-history -- .env .tokens.json
```

Expected: first command shows no staged changes; second shows no history of those files. If either contains secrets, STOP and remove via `git rm --cached <file>` before pushing.

- [ ] **Step 4: Push to GitHub**

```bash
git push -u origin main
```

Expected: pushes 6+ commits to https://github.com/kumarsumit2000/Etsy-MCP. If push fails because the remote is non-empty, do not force-push — investigate first (likely the repo was initialized on GitHub with a README; in that case run `git pull origin main --rebase` and resolve, then push).

- [ ] **Step 5: Mark Phase 0 complete**

Phase 0 acceptance criteria from the spec:

> You run bootstrap, then `etsy_whoami` returns your shop info from Claude

Both must be true. If either failed, fix before declaring Phase 0 done. The next phase (1a — listings/receipts/reviews/shop reads) will be planned as a separate document once you confirm Phase 0 works end-to-end.

---

## Spec coverage check (Phase 0 requirements only)

Cross-reference against `docs/superpowers/specs/2026-05-04-etsy-mcp-design.md`:

| Spec requirement | Task |
|------------------|------|
| § 3.2 Project layout (etsy_mcp/, scripts/, tests/, server.py) | Task 1 |
| § 4.1 Manual Etsy app setup walkthrough | Task 1 (SETUP.md) |
| § 4.1 Bootstrap script with localhost callback + PKCE + token exchange + shop_id fetch | Tasks 3, 8 |
| § 4.1 Runtime token refresh with rotation | Task 5 |
| § 4.1 `.tokens.json` shape with absolute expires_at + obtained_at | Task 4 |
| § 4.1 Atomic file write (.tmp + rename) | Task 4 |
| § 4.1 invalid_grant → RefreshTokenExpired | Task 5 |
| § 6.1 Token-bucket rate limiter @ 10/s | Task 6 |
| § 6.1 429 retry with Retry-After | Task 7 |
| § 6.1 5xx exponential backoff | Task 7 |
| § 6.1 Network-error retry | Task 7 |
| § 6.2 Structured error contract with codes | Task 2 + Task 7 |
| § 5.1 etsy_whoami | Task 9 |
| § 5.1 etsy_token_status | Task 9 |
| § 7 Phase 0 acceptance | Task 9 step 4 + Task 10 |

Out of scope for Phase 0 (deferred to later phases):
- Logging via structlog → kept simple for now; add when first phase needs it
- Listing/receipt/review tools → Phases 1a/1b
- Browser automation + ads tools → Phase 1c
- Bulk export, taxonomy → Phase 1b
- Anything in Tier 2 or 3 → later phases
