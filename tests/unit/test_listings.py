"""Tests for etsy_mcp.listings tools."""

from __future__ import annotations

import httpx
import pytest
import respx

from etsy_mcp.http import ETSY_API_BASE
from etsy_mcp.listings import register_listing_tools


@respx.mock
async def test_list_listings_active_default(make_tools):
    tools = make_tools(register_listing_tools, shop_id="42")
    route = respx.get(f"{ETSY_API_BASE}/application/shops/42/listings").mock(
        return_value=httpx.Response(
            200,
            json={"count": 2, "results": [{"listing_id": 1}, {"listing_id": 2}]},
        )
    )

    result = await tools["etsy_list_listings"]()

    # Verify call params
    assert route.called
    call = route.calls.last
    assert call.request.url.params["state"] == "active"
    assert call.request.url.params["limit"] == "25"
    assert call.request.url.params["offset"] == "0"

    # Verify response shape
    assert result["count"] == 2
    assert len(result["results"]) == 2


@respx.mock
async def test_list_listings_custom_state_and_paging(make_tools):
    tools = make_tools(register_listing_tools, shop_id="42")
    route = respx.get(f"{ETSY_API_BASE}/application/shops/42/listings").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    await tools["etsy_list_listings"](state="draft", limit=50, offset=100)

    call = route.calls.last
    assert call.request.url.params["state"] == "draft"
    assert call.request.url.params["limit"] == "50"
    assert call.request.url.params["offset"] == "100"


async def test_list_listings_missing_shop_id(make_tools):
    tools = make_tools(register_listing_tools, shop_id="")
    result = await tools["etsy_list_listings"]()
    assert result["code"] == "auth_invalid"


@respx.mock
async def test_search_listings_filters_by_keyword_in_title(make_tools):
    tools = make_tools(register_listing_tools, shop_id="42")
    respx.get(f"{ETSY_API_BASE}/application/shops/42/listings").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 3,
                "results": [
                    {"listing_id": 1, "title": "Blue cushion cover", "tags": ["cushion"], "description": ""},
                    {"listing_id": 2, "title": "Red pillow", "tags": ["pillow"], "description": ""},
                    {"listing_id": 3, "title": "Outdoor bench", "tags": ["bench", "cushion"], "description": ""},
                ],
            },
        )
    )

    result = await tools["etsy_search_listings"](keyword="cushion")

    # listings 1 (matches title) + 3 (matches tag) → 2 results
    assert result["count"] == 2
    ids = sorted(r["listing_id"] for r in result["results"])
    assert ids == [1, 3]


@respx.mock
async def test_search_listings_case_insensitive(make_tools):
    tools = make_tools(register_listing_tools, shop_id="42")
    respx.get(f"{ETSY_API_BASE}/application/shops/42/listings").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "results": [
                    {"listing_id": 1, "title": "BLUE Cushion", "tags": [], "description": ""},
                ],
            },
        )
    )

    result = await tools["etsy_search_listings"](keyword="blue")
    assert result["count"] == 1


@respx.mock
async def test_search_listings_matches_description(make_tools):
    tools = make_tools(register_listing_tools, shop_id="42")
    respx.get(f"{ETSY_API_BASE}/application/shops/42/listings").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "results": [
                    {
                        "listing_id": 1,
                        "title": "Generic title",
                        "tags": [],
                        "description": "Made from organic linen",
                    },
                ],
            },
        )
    )

    result = await tools["etsy_search_listings"](keyword="linen")
    assert result["count"] == 1


@respx.mock
async def test_get_listing_no_includes(make_tools):
    tools = make_tools(register_listing_tools, shop_id="42")
    route = respx.get(f"{ETSY_API_BASE}/application/listings/777").mock(
        return_value=httpx.Response(
            200,
            json={"listing_id": 777, "title": "Foo", "state": "active"},
        )
    )

    result = await tools["etsy_get_listing"](listing_id=777)

    assert route.called
    # No `includes` param when none requested
    assert "includes" not in route.calls.last.request.url.params
    assert result["listing_id"] == 777


@respx.mock
async def test_get_listing_with_includes(make_tools):
    tools = make_tools(register_listing_tools, shop_id="42")
    route = respx.get(f"{ETSY_API_BASE}/application/listings/777").mock(
        return_value=httpx.Response(
            200,
            json={"listing_id": 777, "images": [], "inventory": {}},
        )
    )

    await tools["etsy_get_listing"](listing_id=777, includes=["Images", "Inventory"])

    # CSV-joined includes param
    assert route.calls.last.request.url.params["includes"] == "Images,Inventory"


@respx.mock
async def test_get_listing_404_returns_structured_error(make_tools):
    tools = make_tools(register_listing_tools, shop_id="42")
    respx.get(f"{ETSY_API_BASE}/application/listings/999").mock(
        return_value=httpx.Response(404, json={"error": "Listing not found"})
    )

    result = await tools["etsy_get_listing"](listing_id=999)

    assert result["code"] == "not_found"


@respx.mock
async def test_get_listing_inventory_returns_products(make_tools):
    tools = make_tools(register_listing_tools, shop_id="42")
    respx.get(f"{ETSY_API_BASE}/application/listings/777/inventory").mock(
        return_value=httpx.Response(
            200,
            json={
                "products": [
                    {"sku": "A-01", "offerings": [{"price": {"amount": 1500, "currency_code": "USD"}, "quantity": 5}]},
                ],
            },
        )
    )

    result = await tools["etsy_get_listing_inventory"](listing_id=777)

    assert result["products"][0]["sku"] == "A-01"


@respx.mock
async def test_get_listing_images_returns_results(make_tools):
    tools = make_tools(register_listing_tools, shop_id="42")
    respx.get(f"{ETSY_API_BASE}/application/shops/42/listings/777/images").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "results": [
                    {"listing_image_id": 1, "rank": 1, "url_fullxfull": "https://i.etsystatic.com/x.jpg"}
                ],
            },
        )
    )

    result = await tools["etsy_get_listing_images"](listing_id=777)

    assert result["count"] == 1
    assert result["results"][0]["listing_image_id"] == 1


async def test_get_listing_images_missing_shop_id(make_tools):
    tools = make_tools(register_listing_tools, shop_id="")
    result = await tools["etsy_get_listing_images"](listing_id=777)
    assert result["code"] == "auth_invalid"


@respx.mock
async def test_create_draft_listing_required_fields(make_tools):
    tools = make_tools(register_listing_tools, shop_id="42")
    route = respx.post(f"{ETSY_API_BASE}/application/shops/42/listings").mock(
        return_value=httpx.Response(
            201,
            json={"listing_id": 9000, "state": "draft", "url": "https://etsy.com/listing/9000"},
        )
    )

    result = await tools["etsy_create_draft_listing"](
        title="Test cushion",
        description="A test cushion",
        price_usd=49.95,
        quantity=10,
        taxonomy_id=1234,
        who_made="i_did",
        when_made="made_to_order",
        is_supply=False,
        shipping_profile_id=555,
    )

    assert result["listing_id"] == 9000
    # Form-encoded body: parse manually via httpx request content
    sent = dict(httpx.QueryParams(route.calls.last.request.content.decode()))
    assert sent["title"] == "Test cushion"
    assert sent["description"] == "A test cushion"
    assert sent["price"] == "49.95"
    assert sent["quantity"] == "10"
    assert sent["taxonomy_id"] == "1234"
    assert sent["who_made"] == "i_did"
    assert sent["when_made"] == "made_to_order"
    assert sent["is_supply"] == "false"
    assert sent["shipping_profile_id"] == "555"


@respx.mock
async def test_create_draft_listing_with_optional_arrays(make_tools):
    tools = make_tools(register_listing_tools, shop_id="42")
    route = respx.post(f"{ETSY_API_BASE}/application/shops/42/listings").mock(
        return_value=httpx.Response(201, json={"listing_id": 9001})
    )

    await tools["etsy_create_draft_listing"](
        title="Test",
        description="D",
        price_usd=10.0,
        quantity=1,
        taxonomy_id=1,
        who_made="i_did",
        when_made="2020_2025",
        is_supply=False,
        shipping_profile_id=1,
        materials=["cotton", "linen"],
        tags=["modern", "cushion", "blue"],
        return_policy_id=42,
        processing_min=3,
        processing_max=7,
    )

    body = route.calls.last.request.content.decode()
    # Repeated form-keys for arrays (Etsy convention)
    assert body.count("materials=") == 2
    assert body.count("tags=") == 3
    assert "return_policy_id=42" in body
    assert "processing_min=3" in body


async def test_create_draft_listing_missing_shop_id(make_tools):
    tools = make_tools(register_listing_tools, shop_id="")
    result = await tools["etsy_create_draft_listing"](
        title="x", description="x", price_usd=1.0, quantity=1,
        taxonomy_id=1, who_made="i_did", when_made="2020_2025",
        is_supply=False, shipping_profile_id=1,
    )
    assert result["code"] == "auth_invalid"


@respx.mock
async def test_update_listing_sends_only_provided_fields(make_tools):
    tools = make_tools(register_listing_tools, shop_id="42")
    route = respx.patch(f"{ETSY_API_BASE}/application/shops/42/listings/777").mock(
        return_value=httpx.Response(200, json={"listing_id": 777, "title": "New title"})
    )

    result = await tools["etsy_update_listing"](
        listing_id=777,
        title="New title",
        price_usd=29.99,
    )

    body = dict(httpx.QueryParams(route.calls.last.request.content.decode()))
    assert body["title"] == "New title"
    assert body["price"] == "29.99"
    # Fields not passed must NOT appear
    assert "description" not in body
    assert "quantity" not in body
    assert result["title"] == "New title"


@respx.mock
async def test_update_listing_with_array_fields(make_tools):
    tools = make_tools(register_listing_tools, shop_id="42")
    route = respx.patch(f"{ETSY_API_BASE}/application/shops/42/listings/777").mock(
        return_value=httpx.Response(200, json={"listing_id": 777})
    )

    await tools["etsy_update_listing"](
        listing_id=777,
        tags=["tag1", "tag2"],
        materials=["wool"],
    )

    body = route.calls.last.request.content.decode()
    assert body.count("tags=") == 2
    assert body.count("materials=") == 1


async def test_update_listing_missing_shop_id(make_tools):
    tools = make_tools(register_listing_tools, shop_id="")
    result = await tools["etsy_update_listing"](listing_id=777, title="X")
    assert result["code"] == "auth_invalid"


@respx.mock
async def test_delete_listing_without_confirm_refuses(make_tools):
    tools = make_tools(register_listing_tools, shop_id="42")
    # No respx mock — must not hit the network.

    result = await tools["etsy_delete_listing"](listing_id=777)

    assert result["code"] == "validation_failed"
    assert "confirm" in result["error"].lower()


@respx.mock
async def test_delete_listing_with_confirm_calls_api(make_tools):
    tools = make_tools(register_listing_tools, shop_id="42")
    route = respx.delete(f"{ETSY_API_BASE}/application/listings/777").mock(
        return_value=httpx.Response(204)
    )

    result = await tools["etsy_delete_listing"](listing_id=777, confirm=True)

    assert route.called
    assert result == {"deleted": True, "listing_id": 777}


@respx.mock
async def test_delete_listing_404_returns_structured_error(make_tools):
    tools = make_tools(register_listing_tools, shop_id="42")
    respx.delete(f"{ETSY_API_BASE}/application/listings/999").mock(
        return_value=httpx.Response(404, json={"error": "Listing not found"})
    )

    result = await tools["etsy_delete_listing"](listing_id=999, confirm=True)

    assert result["code"] == "not_found"


@respx.mock
async def test_upload_listing_image_uploads_file(make_tools, tmp_path):
    tools = make_tools(register_listing_tools, shop_id="42")
    img = tmp_path / "test.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0fakejpegdata")

    route = respx.post(
        f"{ETSY_API_BASE}/application/shops/42/listings/777/images"
    ).mock(
        return_value=httpx.Response(
            201,
            json={
                "listing_image_id": 5555,
                "rank": 1,
                "url_fullxfull": "https://i.etsystatic.com/x.jpg",
            },
        )
    )

    result = await tools["etsy_upload_listing_image"](
        listing_id=777,
        image_path=str(img),
        rank=1,
        alt_text="A test image",
    )

    assert route.called
    # Verify it was a multipart request
    content_type = route.calls.last.request.headers["content-type"]
    assert content_type.startswith("multipart/form-data")
    body = route.calls.last.request.content
    assert b"test.jpg" in body
    assert b"fakejpegdata" in body
    # rank + alt_text appear as form fields
    assert b'name="rank"' in body
    assert b'name="alt_text"' in body
    assert result["listing_image_id"] == 5555


async def test_upload_listing_image_missing_file(make_tools, tmp_path):
    tools = make_tools(register_listing_tools, shop_id="42")
    result = await tools["etsy_upload_listing_image"](
        listing_id=777,
        image_path=str(tmp_path / "does-not-exist.jpg"),
    )
    assert result["code"] == "validation_failed"
    assert "not found" in result["error"].lower() or "no such file" in result["error"].lower()


async def test_upload_listing_image_missing_shop_id(make_tools, tmp_path):
    tools = make_tools(register_listing_tools, shop_id="")
    img = tmp_path / "x.jpg"
    img.write_bytes(b"x")
    result = await tools["etsy_upload_listing_image"](listing_id=1, image_path=str(img))
    assert result["code"] == "auth_invalid"


@respx.mock
async def test_update_listing_inventory_sends_products_json(make_tools):
    tools = make_tools(register_listing_tools, shop_id="42")
    route = respx.put(f"{ETSY_API_BASE}/application/listings/777/inventory").mock(
        return_value=httpx.Response(
            200,
            json={"products": [{"sku": "A", "offerings": [{"price": {"amount": 1500, "divisor": 100}, "quantity": 5}]}]},
        )
    )

    products = [
        {
            "sku": "A",
            "offerings": [
                {"price": 15.00, "quantity": 5, "is_enabled": True},
            ],
        }
    ]

    result = await tools["etsy_update_listing_inventory"](
        listing_id=777,
        products=products,
    )

    # Verify it was sent as JSON body
    import json as _json
    sent = _json.loads(route.calls.last.request.content)
    assert sent == {"products": products}
    assert "products" in result


async def test_update_listing_inventory_empty_products_rejected(make_tools):
    tools = make_tools(register_listing_tools, shop_id="42")
    result = await tools["etsy_update_listing_inventory"](listing_id=777, products=[])
    assert result["code"] == "validation_failed"
    assert "empty" in result["error"].lower() or "at least one" in result["error"].lower()


@respx.mock
async def test_save_listing_template_writes_portable_fields(make_tools, tmp_path):
    tools = make_tools(register_listing_tools, shop_id="42")
    template_path = tmp_path / "tpl.json"

    respx.get(f"{ETSY_API_BASE}/application/listings/777").mock(
        return_value=httpx.Response(
            200,
            json={
                "listing_id": 777,
                "title": "Original title",
                "description": "A boilerplate footer.",
                "price": {"amount": 1500},
                "quantity": 5,
                "tags": ["modern", "cushion"],
                "materials": ["cotton"],
                "taxonomy_id": 1234,
                "shipping_profile_id": 555,
                "return_policy_id": 9,
                "who_made": "i_did",
                "when_made": "made_to_order",
                "is_supply": False,
                "processing_min": 3,
                "processing_max": 7,
                "url": "https://etsy.com/listing/777",
            },
        )
    )

    result = await tools["etsy_save_listing_template"](
        listing_id=777,
        template_path=str(template_path),
    )

    assert result["template_path"] == str(template_path)

    import json as _json
    saved = _json.loads(template_path.read_text())

    assert saved["description"] == "A boilerplate footer."
    assert saved["tags"] == ["modern", "cushion"]
    assert saved["materials"] == ["cotton"]
    assert saved["taxonomy_id"] == 1234
    assert saved["shipping_profile_id"] == 555
    assert saved["return_policy_id"] == 9
    assert saved["who_made"] == "i_did"
    assert saved["when_made"] == "made_to_order"
    assert saved["is_supply"] is False
    assert saved["processing_min"] == 3
    assert saved["processing_max"] == 7

    # NOT carried
    assert "listing_id" not in saved
    assert "title" not in saved
    assert "price" not in saved
    assert "quantity" not in saved
    assert "url" not in saved


@respx.mock
async def test_save_listing_template_404_returns_error(make_tools, tmp_path):
    tools = make_tools(register_listing_tools, shop_id="42")
    respx.get(f"{ETSY_API_BASE}/application/listings/999").mock(
        return_value=httpx.Response(404, json={"error": "Listing not found"})
    )

    result = await tools["etsy_save_listing_template"](
        listing_id=999,
        template_path=str(tmp_path / "tpl.json"),
    )

    assert result["code"] == "not_found"


@respx.mock
async def test_apply_listing_template_dry_run(make_tools, tmp_path):
    tools = make_tools(register_listing_tools, shop_id="42")
    tpl = tmp_path / "tpl.json"
    import json as _json
    tpl.write_text(_json.dumps({"tags": ["a", "b"], "materials": ["wool"]}))

    result = await tools["etsy_apply_listing_template"](
        template_path=str(tpl),
        target_listing_ids=[1, 2, 3],
    )

    assert result["dry_run"] is True
    assert result["count"] == 3
    assert set(result["fields"]) == {"tags", "materials"}


@respx.mock
async def test_apply_listing_template_apply_calls_patch_per_listing(make_tools, tmp_path):
    tools = make_tools(register_listing_tools, shop_id="42")
    tpl = tmp_path / "tpl.json"
    import json as _json
    tpl.write_text(_json.dumps({"description": "Shared footer"}))

    r1 = respx.patch(f"{ETSY_API_BASE}/application/shops/42/listings/1").mock(
        return_value=httpx.Response(200, json={"listing_id": 1})
    )
    r2 = respx.patch(f"{ETSY_API_BASE}/application/shops/42/listings/2").mock(
        return_value=httpx.Response(200, json={"listing_id": 2})
    )

    result = await tools["etsy_apply_listing_template"](
        template_path=str(tpl),
        target_listing_ids=[1, 2],
        apply=True,
    )

    assert r1.called and r2.called
    assert result["dry_run"] is False
    assert result["updated"] == 2
    assert result["failed"] == []


async def test_apply_listing_template_missing_file(make_tools, tmp_path):
    tools = make_tools(register_listing_tools, shop_id="42")
    result = await tools["etsy_apply_listing_template"](
        template_path=str(tmp_path / "no-such-file.json"),
        target_listing_ids=[1],
        apply=True,
    )
    assert result["code"] == "validation_failed"


@respx.mock
async def test_duplicate_listing_creates_draft_with_source_fields(make_tools):
    tools = make_tools(register_listing_tools, shop_id="42")

    respx.get(f"{ETSY_API_BASE}/application/listings/777").mock(
        return_value=httpx.Response(
            200,
            json={
                "listing_id": 777,
                "title": "Original cushion",
                "description": "Original description",
                "price": {"amount": 1500, "divisor": 100, "currency_code": "USD"},
                "quantity": 5,
                "taxonomy_id": 1234,
                "who_made": "i_did",
                "when_made": "made_to_order",
                "is_supply": False,
                "shipping_profile_id": 555,
                "return_policy_id": 9,
                "tags": ["modern", "cushion"],
                "materials": ["cotton"],
                "processing_min": 3,
                "processing_max": 7,
            },
        )
    )

    create_route = respx.post(
        f"{ETSY_API_BASE}/application/shops/42/listings"
    ).mock(
        return_value=httpx.Response(
            201,
            json={
                "listing_id": 8888,
                "state": "draft",
                "url": "https://etsy.com/listing/8888",
            },
        )
    )

    result = await tools["etsy_duplicate_listing"](listing_id=777)

    assert create_route.called
    sent = dict(httpx.QueryParams(create_route.calls.last.request.content.decode()))
    assert sent["title"] == "Original cushion"
    assert sent["description"] == "Original description"
    assert sent["price"] == "15.00"
    assert sent["quantity"] == "5"
    assert sent["taxonomy_id"] == "1234"
    assert sent["shipping_profile_id"] == "555"
    assert result["new_listing_id"] == 8888


@respx.mock
async def test_duplicate_listing_with_new_title(make_tools):
    tools = make_tools(register_listing_tools, shop_id="42")
    respx.get(f"{ETSY_API_BASE}/application/listings/777").mock(
        return_value=httpx.Response(
            200,
            json={
                "title": "Original",
                "description": "D",
                "price": {"amount": 1000, "divisor": 100},
                "quantity": 1,
                "taxonomy_id": 1,
                "who_made": "i_did",
                "when_made": "made_to_order",
                "is_supply": False,
                "shipping_profile_id": 1,
            },
        )
    )
    create_route = respx.post(
        f"{ETSY_API_BASE}/application/shops/42/listings"
    ).mock(return_value=httpx.Response(201, json={"listing_id": 9999}))

    await tools["etsy_duplicate_listing"](
        listing_id=777,
        new_title="Cloned cushion v2",
    )

    sent = dict(httpx.QueryParams(create_route.calls.last.request.content.decode()))
    assert sent["title"] == "Cloned cushion v2"


async def test_duplicate_listing_missing_shop_id(make_tools):
    tools = make_tools(register_listing_tools, shop_id="")
    result = await tools["etsy_duplicate_listing"](listing_id=777)
    assert result["code"] == "auth_invalid"
