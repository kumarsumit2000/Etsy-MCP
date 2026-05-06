"""HTTP wrapper for the Etsy Open API v3.

All API-driven tools call etsy_request(). The wrapper handles:
- in-process rate limiting (token bucket, default 10 req/s)
- 401 → automatic token refresh + one retry
- 429 → honor Retry-After, retry up to 3 times
- 5xx → exponential backoff, retry up to 3 times
- network errors → retry up to max_retries times with exponential backoff
- terminal failure → raise the right EtsyMCPError subclass
"""

from __future__ import annotations

import asyncio
import os
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
    attempt = 0  # counts retries for 429/5xx/network only

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        while True:
            await _LIMITER.acquire()
            access_token = await get_access_token(
                keystring=keystring, tokens_path=tokens_path
            )
            # Etsy requires the shared secret appended to the keystring in the
            # x-api-key header (format: "<keystring>:<shared_secret>") for
            # OAuth-authenticated calls on approved apps. Falls back to bare
            # keystring if no secret is configured.
            shared_secret = os.environ.get("ETSY_SHARED_SECRET", "").strip()
            api_key_header = f"{keystring}:{shared_secret}" if shared_secret else keystring
            headers = {
                "x-api-key": api_key_header,
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
            except httpx.TransportError as exc:
                if attempt >= max_retries:
                    raise NetworkError(
                        f"Network error after {attempt} retries: {exc}"
                    ) from exc
                await asyncio.sleep(backoff_base_seconds * (2 ** attempt))
                attempt += 1
                continue

            # Success
            if 200 <= resp.status_code < 300:
                if resp.status_code == 204 or not resp.content:
                    return {}
                return resp.json()

            # Auth: refresh once, then immediately retry (does NOT count against max_retries)
            if resp.status_code == 401:
                if refreshed_once:
                    raise AuthInvalid(
                        "Etsy API returned 401 after token refresh. "
                        "Keystring may be invalid or scopes insufficient.",
                        details=_safe_json(resp),
                    )
                await refresh_access_token(
                    keystring=keystring, tokens_path=tokens_path
                )
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
                await asyncio.sleep(
                    _parse_retry_after(resp)
                    or backoff_base_seconds * (2 ** attempt)
                )
                attempt += 1
                continue

            # 5xx
            if 500 <= resp.status_code < 600:
                if attempt >= max_retries:
                    raise EtsyMCPError(
                        f"Etsy server error {resp.status_code} after {attempt} retries.",
                        details=_safe_json(resp),
                    )
                await asyncio.sleep(backoff_base_seconds * (2 ** attempt))
                attempt += 1
                continue

            # 404 / 400 / others — terminal
            body = _safe_json(resp)
            if resp.status_code == 404:
                raise NotFound(f"Etsy API: {path} not found.", details=body)
            if resp.status_code == 400:
                raise ValidationFailed(
                    f"Etsy API rejected request: "
                    f"{body.get('error_description') or body.get('message') or body.get('error', 'bad request')}",
                    details=body,
                )
            raise EtsyMCPError(
                f"Etsy API returned {resp.status_code}: {body}",
                details=body,
            )


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


async def paginate_all(
    method: str,
    path: str,
    *,
    keystring: str,
    tokens_path: str,
    params: dict | None = None,
    page_size: int = 100,
    results_key: str = "results",
) -> list[dict]:
    """Fetch every page of an Etsy paginated endpoint, return concatenated results.

    Calls etsy_request repeatedly with increasing offset until a page returns
    fewer than page_size items (or zero). Any EtsyMCPError raised by the
    underlying request propagates — the caller wraps it.

    Args:
        method: HTTP method (typically "GET").
        path: Etsy API path (relative or absolute).
        keystring: Etsy app keystring.
        tokens_path: Path to .tokens.json.
        params: Query parameters added to every request. `limit` and `offset`
            are managed by this function — do not include them.
        page_size: Items per page. Etsy max is 100.
        results_key: The key under which the page's items live. Etsy uses
            "results" universally; the param exists for forward-compatibility.

    Returns:
        Flat list of all items across all pages.
    """
    base_params = dict(params or {})
    offset = 0
    out: list[dict] = []

    while True:
        page_params = {**base_params, "limit": page_size, "offset": offset}
        page = await etsy_request(
            method,
            path,
            keystring=keystring,
            tokens_path=tokens_path,
            params=page_params,
        )
        if not isinstance(page, dict):
            return out  # Defensive — etsy_request normally returns dict for paginated endpoints.

        items = page.get(results_key) or []
        out.extend(items)

        if len(items) < page_size:
            break
        offset += page_size

    return out
