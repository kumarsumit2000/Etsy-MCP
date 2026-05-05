"""Tests for etsy_mcp.exports tools."""

from __future__ import annotations

import csv
import json

import httpx
import pytest
import respx

from etsy_mcp.exports import register_export_tools, _flatten_dict
from etsy_mcp.http import ETSY_API_BASE


def test_flatten_dict_dot_joins_nested_keys():
    flat = _flatten_dict({"a": 1, "b": {"c": 2, "d": {"e": 3}}})
    assert flat == {"a": 1, "b.c": 2, "b.d.e": 3}


def test_flatten_dict_serializes_lists_as_json():
    flat = _flatten_dict({"tags": ["a", "b", "c"]})
    assert flat == {"tags": '["a", "b", "c"]'}


def test_flatten_dict_handles_none():
    flat = _flatten_dict({"x": None, "y": {"z": None}})
    assert flat == {"x": "", "y.z": ""}


@respx.mock
async def test_export_all_listings_writes_json_and_csv(make_tools, tmp_path):
    tools = make_tools(register_export_tools, shop_id="42")
    page1 = {
        "count": 2,
        "results": [
            {"listing_id": 1, "title": "A", "price": {"amount": 1500, "currency_code": "USD"}, "tags": ["x"]},
            {"listing_id": 2, "title": "B", "price": {"amount": 2500, "currency_code": "USD"}, "tags": ["y", "z"]},
        ],
    }
    respx.get(f"{ETSY_API_BASE}/application/shops/42/listings").mock(
        return_value=httpx.Response(200, json=page1)
    )

    result = await tools["etsy_export_all_listings"](
        format="both",
        output_dir=str(tmp_path),
    )

    assert result["listings_count"] == 2
    json_path = tmp_path / "listings.json"
    csv_path = tmp_path / "listings.csv"
    assert json_path.exists()
    assert csv_path.exists()
    assert str(json_path) in result["files"]
    assert str(csv_path) in result["files"]

    # JSON: raw list
    payload = json.loads(json_path.read_text())
    assert len(payload) == 2
    assert payload[0]["listing_id"] == 1

    # CSV: flattened headers
    rows = list(csv.DictReader(csv_path.open()))
    assert len(rows) == 2
    assert "price.amount" in rows[0]
    assert rows[0]["price.amount"] == "1500"
    assert rows[0]["price.currency_code"] == "USD"
    assert rows[1]["tags"] == '["y", "z"]'


@respx.mock
async def test_export_all_listings_csv_only(make_tools, tmp_path):
    tools = make_tools(register_export_tools, shop_id="42")
    respx.get(f"{ETSY_API_BASE}/application/shops/42/listings").mock(
        return_value=httpx.Response(200, json={"count": 1, "results": [{"listing_id": 1, "title": "A"}]})
    )

    result = await tools["etsy_export_all_listings"](
        format="csv",
        output_dir=str(tmp_path),
    )

    assert result["listings_count"] == 1
    assert (tmp_path / "listings.csv").exists()
    assert not (tmp_path / "listings.json").exists()


async def test_export_all_listings_missing_shop_id(make_tools, tmp_path):
    tools = make_tools(register_export_tools, shop_id="")
    result = await tools["etsy_export_all_listings"](output_dir=str(tmp_path))
    assert result["code"] == "auth_invalid"


@respx.mock
async def test_export_all_receipts_with_since(make_tools, tmp_path):
    tools = make_tools(register_export_tools, shop_id="42")
    route = respx.get(f"{ETSY_API_BASE}/application/shops/42/receipts").mock(
        return_value=httpx.Response(
            200,
            json={"count": 1, "results": [{"receipt_id": 1, "status": "Paid"}]},
        )
    )

    result = await tools["etsy_export_all_receipts"](
        output_dir=str(tmp_path),
        format="json",
        since="2026-01-01",
    )

    assert result["receipts_count"] == 1
    # since converted to unix timestamp (2026-01-01 UTC = 1767225600)
    assert route.calls.last.request.url.params["min_created"] == "1767225600"
    assert (tmp_path / "receipts.json").exists()


@respx.mock
async def test_export_all_receipts_invalid_since_format(make_tools, tmp_path):
    tools = make_tools(register_export_tools, shop_id="42")
    result = await tools["etsy_export_all_receipts"](
        output_dir=str(tmp_path),
        since="not-a-date",
    )
    assert result["code"] == "validation_failed"
    assert "since" in result["error"].lower()


@respx.mock
async def test_export_all_reviews_writes_csv(make_tools, tmp_path):
    tools = make_tools(register_export_tools, shop_id="42")
    respx.get(f"{ETSY_API_BASE}/application/shops/42/reviews").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 2,
                "results": [
                    {"review_id": 1, "rating": 5, "review": "Great"},
                    {"review_id": 2, "rating": 4, "review": "Good"},
                ],
            },
        )
    )

    result = await tools["etsy_export_all_reviews"](
        output_dir=str(tmp_path),
        format="csv",
    )

    assert result["reviews_count"] == 2
    assert (tmp_path / "reviews.csv").exists()
