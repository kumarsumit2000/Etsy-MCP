"""Tests for etsy_mcp.bulk_ops tools."""

from __future__ import annotations

import httpx
import pytest
import respx

from etsy_mcp.bulk_ops import register_bulk_ops_tools
from etsy_mcp.http import ETSY_API_BASE


@respx.mock
async def test_bulk_update_prices_dry_run_does_not_mutate(make_tools):
    tools = make_tools(register_bulk_ops_tools, shop_id="42")
    # No respx mocks for the PATCH endpoint — dry-run must not call it.

    result = await tools["etsy_bulk_update_prices"](
        updates=[
            {"listing_id": 1, "price_usd": 19.99},
            {"listing_id": 2, "price_usd": 29.99},
        ],
        # apply=False is the default
    )

    assert result["dry_run"] is True
    assert result["count"] == 2
    assert result["would_update"][0] == {"listing_id": 1, "price_usd": 19.99}
    assert result["would_update"][1] == {"listing_id": 2, "price_usd": 29.99}


@respx.mock
async def test_bulk_update_prices_apply_calls_patch_per_listing(make_tools):
    tools = make_tools(register_bulk_ops_tools, shop_id="42")
    r1 = respx.patch(f"{ETSY_API_BASE}/application/shops/42/listings/1").mock(
        return_value=httpx.Response(200, json={"listing_id": 1, "price": 19.99})
    )
    r2 = respx.patch(f"{ETSY_API_BASE}/application/shops/42/listings/2").mock(
        return_value=httpx.Response(200, json={"listing_id": 2, "price": 29.99})
    )

    result = await tools["etsy_bulk_update_prices"](
        updates=[
            {"listing_id": 1, "price_usd": 19.99},
            {"listing_id": 2, "price_usd": 29.99},
        ],
        apply=True,
    )

    assert r1.called
    assert r2.called
    assert result["dry_run"] is False
    assert result["updated"] == 2
    assert result["failed"] == []


@respx.mock
async def test_bulk_update_prices_records_failures(make_tools):
    tools = make_tools(register_bulk_ops_tools, shop_id="42")
    respx.patch(f"{ETSY_API_BASE}/application/shops/42/listings/1").mock(
        return_value=httpx.Response(200, json={"listing_id": 1})
    )
    respx.patch(f"{ETSY_API_BASE}/application/shops/42/listings/2").mock(
        return_value=httpx.Response(404, json={"error": "Listing not found"})
    )

    result = await tools["etsy_bulk_update_prices"](
        updates=[
            {"listing_id": 1, "price_usd": 9.99},
            {"listing_id": 2, "price_usd": 19.99},
        ],
        apply=True,
    )

    assert result["updated"] == 1
    assert len(result["failed"]) == 1
    assert result["failed"][0]["listing_id"] == 2


async def test_bulk_update_prices_empty_updates_rejected(make_tools):
    tools = make_tools(register_bulk_ops_tools, shop_id="42")
    result = await tools["etsy_bulk_update_prices"](updates=[], apply=True)
    assert result["code"] == "validation_failed"


@respx.mock
async def test_bulk_update_quantities_dry_run(make_tools):
    tools = make_tools(register_bulk_ops_tools, shop_id="42")

    result = await tools["etsy_bulk_update_quantities"](
        updates=[
            {"listing_id": 1, "sku": "A-01", "quantity": 5},
            {"listing_id": 1, "sku": "A-02", "quantity": 10},
        ],
    )

    assert result["dry_run"] is True
    assert result["count"] == 2


@respx.mock
async def test_bulk_update_quantities_apply_groups_by_listing(make_tools):
    """Two updates targeting the same listing must be merged into ONE
    PUT /inventory call (otherwise the second call would overwrite the first)."""
    tools = make_tools(register_bulk_ops_tools, shop_id="42")

    # Each listing's GET returns its current inventory.
    respx.get(f"{ETSY_API_BASE}/application/listings/1/inventory").mock(
        return_value=httpx.Response(
            200,
            json={
                "products": [
                    {
                        "sku": "A-01",
                        "offerings": [{"price": {"amount": 1500, "divisor": 100}, "quantity": 1, "is_enabled": True}],
                        "property_values": [],
                    },
                    {
                        "sku": "A-02",
                        "offerings": [{"price": {"amount": 1500, "divisor": 100}, "quantity": 1, "is_enabled": True}],
                        "property_values": [],
                    },
                ]
            },
        )
    )

    put_route = respx.put(
        f"{ETSY_API_BASE}/application/listings/1/inventory"
    ).mock(return_value=httpx.Response(200, json={"products": []}))

    result = await tools["etsy_bulk_update_quantities"](
        updates=[
            {"listing_id": 1, "sku": "A-01", "quantity": 5},
            {"listing_id": 1, "sku": "A-02", "quantity": 10},
        ],
        apply=True,
    )

    # ONE PUT, not two
    assert put_route.call_count == 1
    assert result["updated"] == 2
    assert result["failed"] == []


async def test_bulk_update_quantities_empty_rejected(make_tools):
    tools = make_tools(register_bulk_ops_tools, shop_id="42")
    result = await tools["etsy_bulk_update_quantities"](updates=[], apply=True)
    assert result["code"] == "validation_failed"


async def test_bulk_renew_listings_without_confirm_refuses(make_tools):
    tools = make_tools(register_bulk_ops_tools, shop_id="42")
    result = await tools["etsy_bulk_renew_listings"](listing_ids=[1, 2])
    assert result["code"] == "validation_failed"
    assert "confirm" in result["error"].lower()


@respx.mock
async def test_bulk_renew_listings_with_confirm_renews_each(make_tools):
    tools = make_tools(register_bulk_ops_tools, shop_id="42")
    r1 = respx.post(f"{ETSY_API_BASE}/application/listings/1/renew").mock(
        return_value=httpx.Response(200, json={"listing_id": 1, "state": "active"})
    )
    r2 = respx.post(f"{ETSY_API_BASE}/application/listings/2/renew").mock(
        return_value=httpx.Response(200, json={"listing_id": 2, "state": "active"})
    )

    result = await tools["etsy_bulk_renew_listings"](
        listing_ids=[1, 2], confirm=True
    )

    assert r1.called and r2.called
    assert result["renewed"] == 2
    assert result["failed"] == []


@respx.mock
async def test_bulk_renew_listings_records_failures(make_tools):
    tools = make_tools(register_bulk_ops_tools, shop_id="42")
    respx.post(f"{ETSY_API_BASE}/application/listings/1/renew").mock(
        return_value=httpx.Response(200, json={"listing_id": 1})
    )
    respx.post(f"{ETSY_API_BASE}/application/listings/2/renew").mock(
        return_value=httpx.Response(400, json={"error": "Listing already active"})
    )

    result = await tools["etsy_bulk_renew_listings"](
        listing_ids=[1, 2], confirm=True
    )

    assert result["renewed"] == 1
    assert len(result["failed"]) == 1
    assert result["failed"][0]["listing_id"] == 2


async def test_bulk_renew_listings_empty_rejected(make_tools):
    tools = make_tools(register_bulk_ops_tools, shop_id="42")
    result = await tools["etsy_bulk_renew_listings"](listing_ids=[], confirm=True)
    assert result["code"] == "validation_failed"
