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
