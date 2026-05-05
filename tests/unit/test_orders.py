"""Tests for etsy_mcp.orders tools."""

from __future__ import annotations

import httpx
import pytest
import respx

from etsy_mcp.http import ETSY_API_BASE
from etsy_mcp.orders import register_order_tools


@respx.mock
async def test_mark_receipt_shipped_sends_tracking(make_tools):
    tools = make_tools(register_order_tools, shop_id="42")
    route = respx.post(
        f"{ETSY_API_BASE}/application/shops/42/receipts/12345/tracking"
    ).mock(
        return_value=httpx.Response(
            200, json={"shipped": True, "notification_sent": True}
        )
    )

    result = await tools["etsy_mark_receipt_shipped"](
        receipt_id=12345,
        tracking_code="1Z999AA10123456784",
        carrier_name="ups",
        send_bcc=True,
    )

    sent = dict(httpx.QueryParams(route.calls.last.request.content.decode()))
    assert sent["tracking_code"] == "1Z999AA10123456784"
    assert sent["carrier_name"] == "ups"
    assert sent["send_bcc"] == "true"
    assert result["shipped"] is True


@respx.mock
async def test_mark_receipt_shipped_default_send_bcc_false(make_tools):
    tools = make_tools(register_order_tools, shop_id="42")
    route = respx.post(
        f"{ETSY_API_BASE}/application/shops/42/receipts/12345/tracking"
    ).mock(return_value=httpx.Response(200, json={"shipped": True}))

    await tools["etsy_mark_receipt_shipped"](
        receipt_id=12345,
        tracking_code="abc",
        carrier_name="usps",
    )

    sent = dict(httpx.QueryParams(route.calls.last.request.content.decode()))
    assert sent["send_bcc"] == "false"


async def test_mark_receipt_shipped_missing_shop_id(make_tools):
    tools = make_tools(register_order_tools, shop_id="")
    result = await tools["etsy_mark_receipt_shipped"](
        receipt_id=1, tracking_code="x", carrier_name="usps"
    )
    assert result["code"] == "auth_invalid"


@respx.mock
async def test_bulk_mark_shipped_processes_all_rows(make_tools, tmp_path):
    tools = make_tools(register_order_tools, shop_id="42")
    csv_path = tmp_path / "ship.csv"
    csv_path.write_text(
        "receipt_id,tracking_code,carrier_name\n"
        "100,A100,ups\n"
        "200,B200,usps\n"
        "300,C300,fedex\n"
    )

    respx.post(
        f"{ETSY_API_BASE}/application/shops/42/receipts/100/tracking"
    ).mock(return_value=httpx.Response(200, json={"shipped": True}))
    respx.post(
        f"{ETSY_API_BASE}/application/shops/42/receipts/200/tracking"
    ).mock(return_value=httpx.Response(200, json={"shipped": True}))
    respx.post(
        f"{ETSY_API_BASE}/application/shops/42/receipts/300/tracking"
    ).mock(return_value=httpx.Response(200, json={"shipped": True}))

    result = await tools["etsy_bulk_mark_shipped"](csv_path=str(csv_path))

    assert result["succeeded"] == 3
    assert result["failed"] == []


@respx.mock
async def test_bulk_mark_shipped_records_failures(make_tools, tmp_path):
    tools = make_tools(register_order_tools, shop_id="42")
    csv_path = tmp_path / "ship.csv"
    csv_path.write_text(
        "receipt_id,tracking_code,carrier_name\n"
        "100,A100,ups\n"
        "999,X999,usps\n"
    )

    respx.post(
        f"{ETSY_API_BASE}/application/shops/42/receipts/100/tracking"
    ).mock(return_value=httpx.Response(200, json={"shipped": True}))
    respx.post(
        f"{ETSY_API_BASE}/application/shops/42/receipts/999/tracking"
    ).mock(
        return_value=httpx.Response(404, json={"error": "Receipt not found"})
    )

    result = await tools["etsy_bulk_mark_shipped"](csv_path=str(csv_path))

    assert result["succeeded"] == 1
    assert len(result["failed"]) == 1
    assert result["failed"][0]["receipt_id"] == 999
    assert "not found" in result["failed"][0]["error"].lower()


async def test_bulk_mark_shipped_missing_csv(make_tools, tmp_path):
    tools = make_tools(register_order_tools, shop_id="42")
    result = await tools["etsy_bulk_mark_shipped"](
        csv_path=str(tmp_path / "no-such-file.csv")
    )
    assert result["code"] == "validation_failed"
    assert "not found" in result["error"].lower() or "no such file" in result["error"].lower()


async def test_bulk_mark_shipped_csv_missing_required_column(make_tools, tmp_path):
    tools = make_tools(register_order_tools, shop_id="42")
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("receipt_id,tracking_code\n100,A100\n")  # missing carrier_name

    result = await tools["etsy_bulk_mark_shipped"](csv_path=str(csv_path))

    assert result["code"] == "validation_failed"
    assert "carrier_name" in result["error"]


async def test_issue_refund_without_confirm_refuses(make_tools):
    tools = make_tools(register_order_tools, shop_id="42")
    result = await tools["etsy_issue_refund"](
        receipt_id=12345,
        amount_cents=500,
        reason="Buyer requested",
    )
    assert result["code"] == "validation_failed"
    assert "confirm" in result["error"].lower()


@respx.mock
async def test_issue_refund_with_confirm_calls_api(make_tools):
    tools = make_tools(register_order_tools, shop_id="42")
    route = respx.post(
        f"{ETSY_API_BASE}/application/shops/42/receipts/12345/refunds"
    ).mock(
        return_value=httpx.Response(
            200, json={"refund_id": 999, "amount": 500, "status": "Pending"}
        )
    )

    result = await tools["etsy_issue_refund"](
        receipt_id=12345,
        amount_cents=500,
        reason="Defective item",
        confirm=True,
    )

    sent = dict(httpx.QueryParams(route.calls.last.request.content.decode()))
    assert sent["amount"] == "500"
    assert sent["reason"] == "Defective item"
    assert result["refund_id"] == 999


async def test_issue_refund_validates_positive_amount(make_tools):
    tools = make_tools(register_order_tools, shop_id="42")
    result = await tools["etsy_issue_refund"](
        receipt_id=12345,
        amount_cents=0,
        reason="x",
        confirm=True,
    )
    assert result["code"] == "validation_failed"
    assert "amount" in result["error"].lower()


async def test_issue_refund_missing_shop_id(make_tools):
    tools = make_tools(register_order_tools, shop_id="")
    result = await tools["etsy_issue_refund"](
        receipt_id=1, amount_cents=100, reason="x", confirm=True
    )
    assert result["code"] == "auth_invalid"
