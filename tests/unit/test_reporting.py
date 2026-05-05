"""Tests for etsy_mcp.reporting tools."""

from __future__ import annotations

import httpx
import pytest
import respx

from etsy_mcp.http import ETSY_API_BASE
from etsy_mcp.reporting import register_reporting_tools


@respx.mock
async def test_revenue_report_groups_by_day(make_tools):
    tools = make_tools(register_reporting_tools, shop_id="42")
    respx.get(f"{ETSY_API_BASE}/application/shops/42/receipts").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 3,
                "results": [
                    {
                        "receipt_id": 1,
                        "create_timestamp": 1767225600,  # 2026-01-01
                        "grandtotal": {"amount": 1500, "divisor": 100, "currency_code": "USD"},
                    },
                    {
                        "receipt_id": 2,
                        "create_timestamp": 1767270000,  # 2026-01-01
                        "grandtotal": {"amount": 2500, "divisor": 100, "currency_code": "USD"},
                    },
                    {
                        "receipt_id": 3,
                        "create_timestamp": 1767312000,  # 2026-01-02
                        "grandtotal": {"amount": 3000, "divisor": 100, "currency_code": "USD"},
                    },
                ],
            },
        )
    )

    result = await tools["etsy_revenue_report"](
        start="2026-01-01",
        end="2026-01-31",
        group_by="day",
    )

    assert isinstance(result, list)
    assert len(result) == 2
    by_period = {row["period"]: row for row in result}
    assert "2026-01-01" in by_period
    assert "2026-01-02" in by_period
    assert by_period["2026-01-01"]["revenue_cents"] == 4000
    assert by_period["2026-01-01"]["orders"] == 2
    assert by_period["2026-01-02"]["revenue_cents"] == 3000
    assert by_period["2026-01-02"]["orders"] == 1


@respx.mock
async def test_revenue_report_groups_by_month(make_tools):
    tools = make_tools(register_reporting_tools, shop_id="42")
    respx.get(f"{ETSY_API_BASE}/application/shops/42/receipts").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 2,
                "results": [
                    {
                        "create_timestamp": 1767225600,  # 2026-01-01
                        "grandtotal": {"amount": 1000, "divisor": 100, "currency_code": "USD"},
                    },
                    {
                        "create_timestamp": 1769904000,  # 2026-02-01
                        "grandtotal": {"amount": 2000, "divisor": 100, "currency_code": "USD"},
                    },
                ],
            },
        )
    )

    result = await tools["etsy_revenue_report"](
        start="2026-01-01",
        end="2026-02-28",
        group_by="month",
    )

    assert len(result) == 2
    by_period = {row["period"]: row["revenue_cents"] for row in result}
    assert by_period == {"2026-01": 1000, "2026-02": 2000}


@respx.mock
async def test_revenue_report_empty_period(make_tools):
    tools = make_tools(register_reporting_tools, shop_id="42")
    respx.get(f"{ETSY_API_BASE}/application/shops/42/receipts").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    result = await tools["etsy_revenue_report"](
        start="2026-01-01", end="2026-01-31", group_by="day"
    )
    assert result == []


async def test_revenue_report_invalid_group_by(make_tools):
    tools = make_tools(register_reporting_tools, shop_id="42")
    result = await tools["etsy_revenue_report"](
        start="2026-01-01", end="2026-01-31", group_by="hour"
    )
    assert result["code"] == "validation_failed"


async def test_revenue_report_invalid_date(make_tools):
    tools = make_tools(register_reporting_tools, shop_id="42")
    result = await tools["etsy_revenue_report"](
        start="not-a-date", end="2026-01-31", group_by="day"
    )
    assert result["code"] == "validation_failed"


@respx.mock
async def test_top_listings_report_by_revenue(make_tools):
    tools = make_tools(register_reporting_tools, shop_id="42")
    respx.get(f"{ETSY_API_BASE}/application/shops/42/receipts").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 2,
                "results": [
                    {
                        "create_timestamp": 1767225600,
                        "transactions": [
                            {"listing_id": 100, "title": "Cushion A", "quantity": 2, "price": {"amount": 1500, "divisor": 100}},
                            {"listing_id": 200, "title": "Cushion B", "quantity": 1, "price": {"amount": 2500, "divisor": 100}},
                        ],
                    },
                    {
                        "create_timestamp": 1767312000,
                        "transactions": [
                            {"listing_id": 100, "title": "Cushion A", "quantity": 3, "price": {"amount": 1500, "divisor": 100}},
                        ],
                    },
                ],
            },
        )
    )

    result = await tools["etsy_top_listings_report"](
        start="2026-01-01", end="2026-01-31", by="revenue"
    )

    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["listing_id"] == 100
    assert result[0]["revenue_cents"] == 7500
    assert result[0]["units"] == 5
    assert result[1]["listing_id"] == 200
    assert result[1]["revenue_cents"] == 2500


@respx.mock
async def test_top_listings_report_by_units(make_tools):
    tools = make_tools(register_reporting_tools, shop_id="42")
    respx.get(f"{ETSY_API_BASE}/application/shops/42/receipts").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "results": [
                    {
                        "create_timestamp": 1767225600,
                        "transactions": [
                            {"listing_id": 100, "title": "Cheap", "quantity": 10, "price": {"amount": 100, "divisor": 100}},
                            {"listing_id": 200, "title": "Pricy", "quantity": 1, "price": {"amount": 5000, "divisor": 100}},
                        ],
                    },
                ],
            },
        )
    )

    result = await tools["etsy_top_listings_report"](
        start="2026-01-01", end="2026-01-31", by="units"
    )

    assert result[0]["listing_id"] == 100
    assert result[0]["units"] == 10


async def test_top_listings_report_by_views_not_supported(make_tools):
    tools = make_tools(register_reporting_tools, shop_id="42")
    result = await tools["etsy_top_listings_report"](
        start="2026-01-01", end="2026-01-31", by="views"
    )
    assert result["code"] == "validation_failed"
    assert "views" in result["error"].lower()
