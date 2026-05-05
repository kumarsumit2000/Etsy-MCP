"""Tests for etsy_mcp.reviews tools."""

from __future__ import annotations

import httpx
import pytest
import respx

from etsy_mcp.http import ETSY_API_BASE
from etsy_mcp.reviews import register_review_tools


@respx.mock
async def test_list_reviews_default(make_tools):
    tools = make_tools(register_review_tools, shop_id="42")
    route = respx.get(f"{ETSY_API_BASE}/application/shops/42/reviews").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "results": [
                    {"review_id": 1, "rating": 5, "review": "Loved it"},
                ],
            },
        )
    )

    result = await tools["etsy_list_reviews"]()

    assert route.called
    call = route.calls.last
    assert call.request.url.params["limit"] == "25"
    assert call.request.url.params["offset"] == "0"
    assert result["count"] == 1


@respx.mock
async def test_list_reviews_with_date_range(make_tools):
    tools = make_tools(register_review_tools, shop_id="42")
    route = respx.get(f"{ETSY_API_BASE}/application/shops/42/reviews").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    await tools["etsy_list_reviews"](
        min_created=1700000000, max_created=1800000000, limit=100, offset=50
    )

    call = route.calls.last
    assert call.request.url.params["min_created"] == "1700000000"
    assert call.request.url.params["max_created"] == "1800000000"
    assert call.request.url.params["limit"] == "100"
    assert call.request.url.params["offset"] == "50"


async def test_list_reviews_missing_shop_id(make_tools):
    tools = make_tools(register_review_tools, shop_id="")
    result = await tools["etsy_list_reviews"]()
    assert result["code"] == "auth_invalid"
