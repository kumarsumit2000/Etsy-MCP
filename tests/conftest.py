"""Shared pytest fixtures for Etsy MCP tests."""

from __future__ import annotations

import inspect

import pytest

from etsy_mcp.auth import TokenStore


@pytest.fixture
def tmp_tokens_path(tmp_path):
    """Provide a temp path for .tokens.json that's isolated per test."""
    return tmp_path / "tokens.json"


@pytest.fixture
def seeded_tokens_path(tmp_tokens_path):
    """A tokens file that's already valid for ~1 hour. Tools can be called without
    triggering a refresh against Etsy."""
    TokenStore(tmp_tokens_path).save(
        access_token="test-acc",
        refresh_token="test-ref",
        expires_in=3600,
        scope="listings_r listings_w listings_d shops_r transactions_r feedback_r",
    )
    return tmp_tokens_path


@pytest.fixture
def make_tools(seeded_tokens_path):
    """Factory: given a register_<domain>_tools function, return the dict of
    tool callables. Inspects the register function's signature to only pass
    kwargs it accepts, so modules without shop_id_getter (e.g. taxonomy) work.

    Usage:
        tools = make_tools(register_listing_tools, shop_id="123")
        result = await tools["etsy_list_listings"](limit=5)
    """

    def _factory(register_fn, *, shop_id="999"):
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("etsy-test")
        sig = inspect.signature(register_fn)
        kwargs = {
            "keystring": "test-keystring",
            "tokens_path": seeded_tokens_path,
        }
        if "shop_id_getter" in sig.parameters:
            kwargs["shop_id_getter"] = lambda: shop_id
        return register_fn(mcp, **kwargs)

    return _factory
