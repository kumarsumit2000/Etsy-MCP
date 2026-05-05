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


@respx.mock
async def test_request_401_on_final_attempt_still_refreshes_and_succeeds(tmp_tokens_path):
    """Critical bug: 401 on the final loop iteration must still refresh + retry,
    not fall through to the unreachable sentinel.

    Scenario: max_retries=2, two 429s consume the retry budget, the final
    attempt hits 401 with a stale token. After refresh, the retry must succeed.
    """
    _seed_tokens(tmp_tokens_path, expires_in=3600)

    api_route = respx.get(f"{ETSY_API_BASE}/application/users/me").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(401, json={"error": "expired"}),
            httpx.Response(200, json={"user_id": 99}),
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
        max_retries=2,
        backoff_base_seconds=0.0,
    )

    assert result == {"user_id": 99}
    assert refresh_route.call_count == 1
    assert api_route.call_count == 4  # 429, 429, 401, 200


@respx.mock
async def test_request_connect_timeout_is_retried(tmp_tokens_path):
    """httpx.ConnectTimeout is a subclass of TransportError but NOT ConnectError.
    Make sure it's caught and retried, not surfaced raw.
    """
    _seed_tokens(tmp_tokens_path)
    route = respx.get(f"{ETSY_API_BASE}/application/users/me").mock(
        side_effect=[
            httpx.ConnectTimeout("syn dropped"),
            httpx.Response(200, json={"user_id": 5}),
        ]
    )
    result = await etsy_request(
        "GET",
        "/application/users/me",
        keystring="kkey",
        tokens_path=tmp_tokens_path,
        backoff_base_seconds=0.0,
    )
    assert result == {"user_id": 5}
    assert route.call_count == 2


from etsy_mcp.http import paginate_all


@respx.mock
async def test_paginate_all_concatenates_pages_until_short(tmp_tokens_path):
    _seed_tokens(tmp_tokens_path)
    page1 = {"count": 250, "results": [{"id": i} for i in range(100)]}
    page2 = {"count": 250, "results": [{"id": i} for i in range(100, 200)]}
    page3 = {"count": 250, "results": [{"id": i} for i in range(200, 250)]}  # short page → stop

    respx.get(f"{ETSY_API_BASE}/application/shops/42/widgets").mock(
        side_effect=[
            httpx.Response(200, json=page1),
            httpx.Response(200, json=page2),
            httpx.Response(200, json=page3),
        ]
    )

    results = await paginate_all(
        "GET",
        "/application/shops/42/widgets",
        keystring="kkey",
        tokens_path=str(tmp_tokens_path),
        params={"state": "active"},
        page_size=100,
    )

    assert len(results) == 250
    assert results[0]["id"] == 0
    assert results[-1]["id"] == 249


@respx.mock
async def test_paginate_all_empty_first_page_returns_empty_list(tmp_tokens_path):
    _seed_tokens(tmp_tokens_path)
    respx.get(f"{ETSY_API_BASE}/application/shops/42/widgets").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    results = await paginate_all(
        "GET",
        "/application/shops/42/widgets",
        keystring="kkey",
        tokens_path=str(tmp_tokens_path),
        params={},
        page_size=100,
    )

    assert results == []
