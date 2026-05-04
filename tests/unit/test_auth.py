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
