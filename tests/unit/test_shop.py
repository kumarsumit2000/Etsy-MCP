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
