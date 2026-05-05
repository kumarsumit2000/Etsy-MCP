"""Tests for etsy_mcp.listings tools."""

from __future__ import annotations

import httpx
import pytest
import respx

from etsy_mcp.http import ETSY_API_BASE
from etsy_mcp.listings import register_listing_tools


@respx.mock
async def test_list_listings_active_default(make_tools):
    tools = make_tools(register_listing_tools, shop_id="42")
    route = respx.get(f"{ETSY_API_BASE}/application/shops/42/listings").mock(
        return_value=httpx.Response(
            200,
            json={"count": 2, "results": [{"listing_id": 1}, {"listing_id": 2}]},
        )
    )

    result = await tools["etsy_list_listings"]()

    # Verify call params
    assert route.called
    call = route.calls.last
    assert call.request.url.params["state"] == "active"
    assert call.request.url.params["limit"] == "25"
    assert call.request.url.params["offset"] == "0"

    # Verify response shape
    assert result["count"] == 2
    assert len(result["results"]) == 2


@respx.mock
async def test_list_listings_custom_state_and_paging(make_tools):
    tools = make_tools(register_listing_tools, shop_id="42")
    route = respx.get(f"{ETSY_API_BASE}/application/shops/42/listings").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    await tools["etsy_list_listings"](state="draft", limit=50, offset=100)

    call = route.calls.last
    assert call.request.url.params["state"] == "draft"
    assert call.request.url.params["limit"] == "50"
    assert call.request.url.params["offset"] == "100"


async def test_list_listings_missing_shop_id(make_tools):
    tools = make_tools(register_listing_tools, shop_id="")
    result = await tools["etsy_list_listings"]()
    assert result["code"] == "auth_invalid"
