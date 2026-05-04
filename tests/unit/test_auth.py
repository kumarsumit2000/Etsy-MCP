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


def test_save_creates_file_with_0o600_perms(tmp_tokens_path):
    """Tokens file holds an access token; must not be world-readable."""
    import stat
    TokenStore(tmp_tokens_path).save(
        access_token="secret",
        refresh_token="ref",
        expires_in=3600,
        scope="x",
    )
    mode = stat.S_IMODE(tmp_tokens_path.stat().st_mode)
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


def test_save_cleans_tmp_file_when_serialization_fails(tmp_tokens_path, monkeypatch):
    """If json.dump raises, the .tmp file must not be left behind."""
    import json as json_module

    def boom(*a, **kw):
        raise ValueError("simulated serialization failure")

    monkeypatch.setattr(json_module, "dump", boom)

    with pytest.raises(ValueError):
        TokenStore(tmp_tokens_path).save(
            access_token="acc",
            refresh_token="ref",
            expires_in=3600,
            scope="x",
        )

    tmp_path = tmp_tokens_path.with_suffix(tmp_tokens_path.suffix + ".tmp")
    assert not tmp_path.exists(), "tmp file should be cleaned up after failure"


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


import asyncio


@respx.mock
async def test_concurrent_get_access_token_refreshes_only_once(tmp_tokens_path):
    """Two coroutines calling get_access_token while expiring should result
    in exactly ONE refresh request — the second waits on the lock, then sees
    the freshly-refreshed token and returns it without calling the endpoint.
    """
    TokenStore(tmp_tokens_path).save(
        access_token="stale",
        refresh_token="ref-1",
        expires_in=10,  # under leeway, will trigger refresh
        scope="x",
    )
    route = respx.post(ETSY_TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "fresh",
                "refresh_token": "ref-2",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )
    )

    results = await asyncio.gather(
        get_access_token(keystring="kkey", tokens_path=tmp_tokens_path),
        get_access_token(keystring="kkey", tokens_path=tmp_tokens_path),
        get_access_token(keystring="kkey", tokens_path=tmp_tokens_path),
    )

    # All three coroutines see the new token
    assert results == ["fresh", "fresh", "fresh"]
    # But only ONE refresh actually went over the wire
    assert route.call_count == 1


@respx.mock
async def test_refresh_network_error_raises_network_error(tmp_tokens_path):
    """Connection-level failure → NetworkError, not raw httpx.TransportError."""
    from etsy_mcp.errors import NetworkError as NE

    TokenStore(tmp_tokens_path).save(
        access_token="acc",
        refresh_token="ref",
        expires_in=10,
        scope="x",
    )
    respx.post(ETSY_TOKEN_URL).mock(side_effect=httpx.ConnectError("dns down"))

    with pytest.raises(NE):
        await refresh_access_token(keystring="kkey", tokens_path=tmp_tokens_path)


@respx.mock
async def test_refresh_500_raises_network_error(tmp_tokens_path):
    """5xx from token endpoint must not leak as raw HTTPStatusError."""
    from etsy_mcp.errors import NetworkError as NE

    TokenStore(tmp_tokens_path).save(
        access_token="acc",
        refresh_token="ref",
        expires_in=10,
        scope="x",
    )
    respx.post(ETSY_TOKEN_URL).mock(
        return_value=httpx.Response(500, json={"error": "internal"})
    )

    with pytest.raises(NE):
        await refresh_access_token(keystring="kkey", tokens_path=tmp_tokens_path)


@respx.mock
async def test_refresh_malformed_200_raises_auth_invalid(tmp_tokens_path):
    """Etsy 200 with missing access_token must not leak as raw KeyError."""
    TokenStore(tmp_tokens_path).save(
        access_token="acc",
        refresh_token="ref",
        expires_in=10,
        scope="x",
    )
    respx.post(ETSY_TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={"refresh_token": "new-ref", "expires_in": 3600},  # access_token missing
        )
    )

    with pytest.raises(AuthInvalid):
        await refresh_access_token(keystring="kkey", tokens_path=tmp_tokens_path)
