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


@respx.mock
async def test_get_receipt_returns_receipt(make_tools):
    tools = make_tools(register_receipt_tools, shop_id="42")
    respx.get(f"{ETSY_API_BASE}/application/shops/42/receipts/12345").mock(
        return_value=httpx.Response(
            200,
            json={"receipt_id": 12345, "status": "Paid", "grandtotal": {"amount": 5000}},
        )
    )

    result = await tools["etsy_get_receipt"](receipt_id=12345)

    assert result["receipt_id"] == 12345
    assert result["status"] == "Paid"


@respx.mock
async def test_get_receipt_transactions_returns_line_items(make_tools):
    tools = make_tools(register_receipt_tools, shop_id="42")
    respx.get(
        f"{ETSY_API_BASE}/application/shops/42/receipts/12345/transactions"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 2,
                "results": [
                    {"transaction_id": 1, "title": "Cushion A", "quantity": 2},
                    {"transaction_id": 2, "title": "Cushion B", "quantity": 1},
                ],
            },
        )
    )

    result = await tools["etsy_get_receipt_transactions"](receipt_id=12345)

    assert result["count"] == 2
    assert len(result["results"]) == 2


@respx.mock
async def test_list_shop_payments_with_date_range(make_tools):
    tools = make_tools(register_receipt_tools, shop_id="42")
    route = respx.get(
        f"{ETSY_API_BASE}/application/shops/42/payment-account/ledger-entries"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "results": [
                    {"entry_id": 1, "amount": 5000, "currency": "USD", "entry_type": "Charge"},
                ],
            },
        )
    )

    await tools["etsy_list_shop_payments"](
        min_created=1700000000, max_created=1800000000, limit=50
    )

    call = route.calls.last
    assert call.request.url.params["min_created"] == "1700000000"
    assert call.request.url.params["max_created"] == "1800000000"
    assert call.request.url.params["limit"] == "50"


async def test_list_shop_payments_missing_shop_id(make_tools):
    tools = make_tools(register_receipt_tools, shop_id="")
    result = await tools["etsy_list_shop_payments"]()
    assert result["code"] == "auth_invalid"
