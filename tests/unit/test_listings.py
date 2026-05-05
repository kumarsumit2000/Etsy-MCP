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


@respx.mock
async def test_search_listings_filters_by_keyword_in_title(make_tools):
    tools = make_tools(register_listing_tools, shop_id="42")
    respx.get(f"{ETSY_API_BASE}/application/shops/42/listings").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 3,
                "results": [
                    {"listing_id": 1, "title": "Blue cushion cover", "tags": ["cushion"], "description": ""},
                    {"listing_id": 2, "title": "Red pillow", "tags": ["pillow"], "description": ""},
                    {"listing_id": 3, "title": "Outdoor bench", "tags": ["bench", "cushion"], "description": ""},
                ],
            },
        )
    )

    result = await tools["etsy_search_listings"](keyword="cushion")

    # listings 1 (matches title) + 3 (matches tag) → 2 results
    assert result["count"] == 2
    ids = sorted(r["listing_id"] for r in result["results"])
    assert ids == [1, 3]


@respx.mock
async def test_search_listings_case_insensitive(make_tools):
    tools = make_tools(register_listing_tools, shop_id="42")
    respx.get(f"{ETSY_API_BASE}/application/shops/42/listings").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "results": [
                    {"listing_id": 1, "title": "BLUE Cushion", "tags": [], "description": ""},
                ],
            },
        )
    )

    result = await tools["etsy_search_listings"](keyword="blue")
    assert result["count"] == 1


@respx.mock
async def test_search_listings_matches_description(make_tools):
    tools = make_tools(register_listing_tools, shop_id="42")
    respx.get(f"{ETSY_API_BASE}/application/shops/42/listings").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "results": [
                    {
                        "listing_id": 1,
                        "title": "Generic title",
                        "tags": [],
                        "description": "Made from organic linen",
                    },
                ],
            },
        )
    )

    result = await tools["etsy_search_listings"](keyword="linen")
    assert result["count"] == 1
