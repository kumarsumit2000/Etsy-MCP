"""Tests for etsy_mcp.shop_config tools."""

from __future__ import annotations

import httpx
import pytest
import respx

from etsy_mcp.http import ETSY_API_BASE
from etsy_mcp.shop_config import register_shop_config_tools


@respx.mock
async def test_list_shipping_profiles(make_tools):
    tools = make_tools(register_shop_config_tools, shop_id="42")
    respx.get(f"{ETSY_API_BASE}/application/shops/42/shipping-profiles").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 2,
                "results": [
                    {"shipping_profile_id": 1, "title": "USA"},
                    {"shipping_profile_id": 2, "title": "International"},
                ],
            },
        )
    )

    result = await tools["etsy_list_shipping_profiles"]()
    assert result["count"] == 2


@respx.mock
async def test_create_shipping_profile(make_tools):
    tools = make_tools(register_shop_config_tools, shop_id="42")
    route = respx.post(
        f"{ETSY_API_BASE}/application/shops/42/shipping-profiles"
    ).mock(
        return_value=httpx.Response(
            201, json={"shipping_profile_id": 99, "title": "Domestic standard"}
        )
    )

    result = await tools["etsy_create_shipping_profile"](
        title="Domestic standard",
        origin_country_iso="US",
        primary_cost_cents=500,
        secondary_cost_cents=200,
        min_processing_days=1,
        max_processing_days=3,
        destination_country_iso="US",
    )

    sent = dict(httpx.QueryParams(route.calls.last.request.content.decode()))
    assert sent["title"] == "Domestic standard"
    assert sent["origin_country_iso"] == "US"
    assert sent["primary_cost"] == "500"
    assert sent["secondary_cost"] == "200"
    assert sent["destination_country_iso"] == "US"
    assert result["shipping_profile_id"] == 99


@respx.mock
async def test_update_shipping_profile_partial(make_tools):
    tools = make_tools(register_shop_config_tools, shop_id="42")
    route = respx.patch(
        f"{ETSY_API_BASE}/application/shops/42/shipping-profiles/99"
    ).mock(
        return_value=httpx.Response(
            200, json={"shipping_profile_id": 99, "title": "Renamed"}
        )
    )

    await tools["etsy_update_shipping_profile"](
        shipping_profile_id=99,
        title="Renamed",
    )

    sent = dict(httpx.QueryParams(route.calls.last.request.content.decode()))
    assert sent["title"] == "Renamed"
    assert "primary_cost" not in sent  # not passed → not sent


async def test_list_shipping_profiles_missing_shop_id(make_tools):
    tools = make_tools(register_shop_config_tools, shop_id="")
    result = await tools["etsy_list_shipping_profiles"]()
    assert result["code"] == "auth_invalid"


@respx.mock
async def test_list_shop_sections(make_tools):
    tools = make_tools(register_shop_config_tools, shop_id="42")
    respx.get(f"{ETSY_API_BASE}/application/shops/42/sections").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 2,
                "results": [
                    {"shop_section_id": 1, "title": "Cushions"},
                    {"shop_section_id": 2, "title": "Pillows"},
                ],
            },
        )
    )

    result = await tools["etsy_list_shop_sections"]()
    assert result["count"] == 2


@respx.mock
async def test_create_shop_section(make_tools):
    tools = make_tools(register_shop_config_tools, shop_id="42")
    route = respx.post(f"{ETSY_API_BASE}/application/shops/42/sections").mock(
        return_value=httpx.Response(
            201, json={"shop_section_id": 99, "title": "Bench Cushions"}
        )
    )

    result = await tools["etsy_create_shop_section"](title="Bench Cushions")

    sent = dict(httpx.QueryParams(route.calls.last.request.content.decode()))
    assert sent["title"] == "Bench Cushions"
    assert result["shop_section_id"] == 99


@respx.mock
async def test_update_shop_section(make_tools):
    tools = make_tools(register_shop_config_tools, shop_id="42")
    route = respx.patch(f"{ETSY_API_BASE}/application/shops/42/sections/99").mock(
        return_value=httpx.Response(
            200, json={"shop_section_id": 99, "title": "Renamed Section"}
        )
    )

    await tools["etsy_update_shop_section"](
        shop_section_id=99, title="Renamed Section"
    )

    sent = dict(httpx.QueryParams(route.calls.last.request.content.decode()))
    assert sent["title"] == "Renamed Section"


@respx.mock
async def test_list_return_policies(make_tools):
    tools = make_tools(register_shop_config_tools, shop_id="42")
    respx.get(f"{ETSY_API_BASE}/application/shops/42/policies/return").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "results": [
                    {
                        "return_policy_id": 1,
                        "accepts_returns": True,
                        "return_deadline": 14,
                    }
                ],
            },
        )
    )

    result = await tools["etsy_list_return_policies"]()
    assert result["count"] == 1


@respx.mock
async def test_create_return_policy(make_tools):
    tools = make_tools(register_shop_config_tools, shop_id="42")
    route = respx.post(
        f"{ETSY_API_BASE}/application/shops/42/policies/return"
    ).mock(
        return_value=httpx.Response(
            201,
            json={
                "return_policy_id": 99,
                "accepts_returns": True,
                "accepts_exchanges": True,
                "return_deadline": 30,
            },
        )
    )

    result = await tools["etsy_create_return_policy"](
        accepts_returns=True,
        accepts_exchanges=True,
        return_deadline_days=30,
    )

    sent = dict(httpx.QueryParams(route.calls.last.request.content.decode()))
    assert sent["accepts_returns"] == "true"
    assert sent["accepts_exchanges"] == "true"
    assert sent["return_deadline"] == "30"
    assert result["return_policy_id"] == 99


@respx.mock
async def test_list_production_partners(make_tools):
    tools = make_tools(register_shop_config_tools, shop_id="42")
    respx.get(
        f"{ETSY_API_BASE}/application/shops/42/production-partners"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "results": [
                    {
                        "production_partner_id": 1,
                        "partner_name": "Cushion Co",
                        "location": "Vietnam",
                    }
                ],
            },
        )
    )

    result = await tools["etsy_list_production_partners"]()
    assert result["count"] == 1


@respx.mock
async def test_create_production_partner(make_tools):
    tools = make_tools(register_shop_config_tools, shop_id="42")
    route = respx.post(
        f"{ETSY_API_BASE}/application/shops/42/production-partners"
    ).mock(
        return_value=httpx.Response(
            201,
            json={
                "production_partner_id": 99,
                "partner_name": "Acme Mfg",
                "location": "China",
            },
        )
    )

    result = await tools["etsy_create_production_partner"](
        partner_name="Acme Mfg", location="China"
    )

    sent = dict(httpx.QueryParams(route.calls.last.request.content.decode()))
    assert sent["partner_name"] == "Acme Mfg"
    assert sent["location"] == "China"
    assert result["production_partner_id"] == 99
