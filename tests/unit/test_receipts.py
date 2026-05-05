"""Tests for etsy_mcp.receipts tools."""

from __future__ import annotations

import httpx
import pytest
import respx

from etsy_mcp.http import ETSY_API_BASE
from etsy_mcp.receipts import register_receipt_tools


@respx.mock
async def test_list_receipts_default_params(make_tools):
    tools = make_tools(register_receipt_tools, shop_id="42")
    route = respx.get(f"{ETSY_API_BASE}/application/shops/42/receipts").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    await tools["etsy_list_receipts"]()

    call = route.calls.last
    assert call.request.url.params["limit"] == "25"
    assert call.request.url.params["offset"] == "0"
    # Optional filters NOT sent when None
    assert "min_created" not in call.request.url.params
    assert "was_paid" not in call.request.url.params


@respx.mock
async def test_list_receipts_with_filters(make_tools):
    tools = make_tools(register_receipt_tools, shop_id="42")
    route = respx.get(f"{ETSY_API_BASE}/application/shops/42/receipts").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    await tools["etsy_list_receipts"](
        was_paid=True,
        was_shipped=False,
        min_created=1700000000,
        max_created=1800000000,
        limit=50,
        offset=10,
    )

    call = route.calls.last
    assert call.request.url.params["was_paid"] == "true"
    assert call.request.url.params["was_shipped"] == "false"
    assert call.request.url.params["min_created"] == "1700000000"
    assert call.request.url.params["max_created"] == "1800000000"
    assert call.request.url.params["limit"] == "50"
    assert call.request.url.params["offset"] == "10"


async def test_list_receipts_missing_shop_id(make_tools):
    tools = make_tools(register_receipt_tools, shop_id="")
    result = await tools["etsy_list_receipts"]()
    assert result["code"] == "auth_invalid"
