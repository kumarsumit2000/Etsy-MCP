"""Tests for etsy_mcp.shop tools."""

from __future__ import annotations

import httpx
import pytest
import respx

from etsy_mcp.http import ETSY_API_BASE
from etsy_mcp.shop import register_shop_tools


@respx.mock
async def test_get_shop_returns_shop_dict(make_tools):
    tools = make_tools(register_shop_tools, shop_id="42")
    respx.get(f"{ETSY_API_BASE}/application/shops/42").mock(
        return_value=httpx.Response(
            200,
            json={"shop_id": 42, "shop_name": "TestShop", "currency_code": "USD"},
        )
    )

    result = await tools["etsy_get_shop"]()

    assert result == {"shop_id": 42, "shop_name": "TestShop", "currency_code": "USD"}


@respx.mock
async def test_get_shop_returns_structured_error_when_shop_id_missing(make_tools):
    tools = make_tools(register_shop_tools, shop_id="")
    # No respx mock — we should never reach the network.

    result = await tools["etsy_get_shop"]()

    assert result["code"] == "auth_invalid"
    assert "ETSY_SHOP_ID" in result["error"]


@respx.mock
async def test_get_shop_wraps_api_error_as_dict(make_tools):
    tools = make_tools(register_shop_tools, shop_id="42")
    respx.get(f"{ETSY_API_BASE}/application/shops/42").mock(
        return_value=httpx.Response(404, json={"error": "Shop not found"})
    )

    result = await tools["etsy_get_shop"]()

    assert result["code"] == "not_found"
    assert "error" in result


@respx.mock
async def test_get_shop_stats_aggregates_receipts(make_tools):
    tools = make_tools(register_shop_tools, shop_id="42")
    # Single page of 3 receipts spanning the requested window.
    respx.get(f"{ETSY_API_BASE}/application/shops/42/receipts").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 3,
                "results": [
                    {"receipt_id": 1, "grandtotal": {"amount": 1500, "divisor": 100, "currency_code": "USD"}},
                    {"receipt_id": 2, "grandtotal": {"amount": 2500, "divisor": 100, "currency_code": "USD"}},
                    {"receipt_id": 3, "grandtotal": {"amount": 3000, "divisor": 100, "currency_code": "USD"}},
                ],
            },
        )
    )

    result = await tools["etsy_get_shop_stats"](
        min_created=1700000000, max_created=1800000000
    )

    assert result["orders"] == 3
    # 1500 + 2500 + 3000 = 7000 cents = 70 USD
    assert result["revenue"]["amount_cents"] == 7000
    assert result["revenue"]["currency_code"] == "USD"
    assert result["period"]["min_created"] == 1700000000
    assert result["period"]["max_created"] == 1800000000


@respx.mock
async def test_get_shop_stats_handles_empty_period(make_tools):
    tools = make_tools(register_shop_tools, shop_id="42")
    respx.get(f"{ETSY_API_BASE}/application/shops/42/receipts").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    result = await tools["etsy_get_shop_stats"](
        min_created=1700000000, max_created=1800000000
    )

    assert result["orders"] == 0
    assert result["revenue"]["amount_cents"] == 0


async def test_get_shop_stats_missing_shop_id(make_tools):
    tools = make_tools(register_shop_tools, shop_id="")
    result = await tools["etsy_get_shop_stats"](
        min_created=1700000000, max_created=1800000000
    )
    assert result["code"] == "auth_invalid"


@respx.mock
async def test_get_shop_stats_paginates_to_collect_all(make_tools):
    """Receipts paginate. The tool must follow pages until exhausted.

    First page has 100 receipts. Second page has 25. Total: 125 orders.
    """
    tools = make_tools(register_shop_tools, shop_id="42")

    page1 = {
        "count": 125,
        "results": [
            {"receipt_id": i, "grandtotal": {"amount": 100, "divisor": 100, "currency_code": "USD"}}
            for i in range(100)
        ],
    }
    page2 = {
        "count": 125,
        "results": [
            {"receipt_id": i, "grandtotal": {"amount": 100, "divisor": 100, "currency_code": "USD"}}
            for i in range(100, 125)
        ],
    }

    respx.get(f"{ETSY_API_BASE}/application/shops/42/receipts").mock(
        side_effect=[
            httpx.Response(200, json=page1),
            httpx.Response(200, json=page2),
        ]
    )

    result = await tools["etsy_get_shop_stats"](
        min_created=1700000000, max_created=1800000000
    )

    assert result["orders"] == 125
    assert result["revenue"]["amount_cents"] == 12500
