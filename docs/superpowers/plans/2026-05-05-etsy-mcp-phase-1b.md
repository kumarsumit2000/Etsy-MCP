# Etsy MCP — Phase 1b Implementation Plan (Listing Writes + Taxonomy + Bulk Export)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Round out Tier 1 by giving the user write access to listings (create, update, delete, upload images, update inventory), keyword-based taxonomy lookup (so creates aren't blind), and bulk export of listings/receipts/reviews to JSON+CSV.

**Architecture:** Five new write tools extend the existing `register_listing_tools()` factory in `etsy_mcp/listings.py`. Two new factories — `register_taxonomy_tools` and `register_export_tools` — live in new modules. A small `paginate_all()` helper in `etsy_mcp/http.py` is shared by all three export tools. CSV flattening (dot-joined nested keys) lives in a private helper inside `exports.py`. `server.py` adds two new register calls.

**Tech Stack:** Same as Phase 0/1a — Python 3.10+, FastMCP, httpx, respx for tests. No new runtime deps. The taxonomy tree is fetched once and cached in-process.

**Spec:** `docs/superpowers/specs/2026-05-04-etsy-mcp-design.md` § 5.1 (Tier 1 — listings write, taxonomy, bulk export)
**Predecessor plans:** `docs/superpowers/plans/2026-05-04-etsy-mcp-phase-0.md`, `docs/superpowers/plans/2026-05-05-etsy-mcp-phase-1a.md`

---

## Scope deviation from spec

**Dropped from Phase 1b:** `etsy_update_listing_images_order`. Etsy Open API v3 has no rank-only image-update endpoint — `uploadListingImage` with `overwrite=true` requires the image binary, not just a new rank. Image reordering is therefore deferred (user can do it in the seller dashboard, or we can solve it in Phase 1c via browser automation).

**Phase 1b ships 9 tools:** 5 listing writes + 1 taxonomy search + 3 bulk export.

---

## File Structure (Phase 1b only)

```
~/Desktop/Etsy MCP/
├── etsy_mcp/
│   ├── http.py           MODIFIED — add paginate_all() helper
│   ├── listings.py       MODIFIED — add 5 write tools to existing factory
│   ├── taxonomy.py       NEW — register_taxonomy_tools + tree cache
│   └── exports.py        NEW — register_export_tools + CSV helpers
├── tests/
│   ├── conftest.py       MODIFIED — make_tools handles modules with no shop_id_getter
│   └── unit/
│       ├── test_http.py        MODIFIED — add paginate_all tests
│       ├── test_listings.py    MODIFIED — add 5 write tool tests
│       ├── test_taxonomy.py    NEW
│       └── test_exports.py     NEW
└── server.py             MODIFIED — register taxonomy + export tools
```

**Why this split:** `taxonomy.py` and `exports.py` each have one cohesive responsibility (taxonomy tree lookup, multi-resource bulk dump). `paginate_all` lives in `http.py` because it's transport-level concern shared across exports. CSV flattening stays inside `exports.py` because it's only used by export tools.

---

## Etsy v3 endpoint reference

| Tool | Method | Path | Body / params |
|---|---|---|---|
| `etsy_create_draft_listing` | POST | `/application/shops/{shop_id}/listings` | form-encoded; arrays as repeated keys (`tags=a&tags=b`) |
| `etsy_update_listing` | PATCH | `/application/shops/{shop_id}/listings/{listing_id}` | form-encoded; only fields user passes |
| `etsy_delete_listing` | DELETE | `/application/listings/{listing_id}` | — |
| `etsy_upload_listing_image` | POST | `/application/shops/{shop_id}/listings/{listing_id}/images` | multipart: `image=<file>`, `rank`, `alt_text` |
| `etsy_update_listing_inventory` | PUT | `/application/listings/{listing_id}/inventory` | JSON body `{products: [...]}` |
| `etsy_taxonomy_search` | (helper) | `/application/seller-taxonomy/nodes` | full tree fetched once, filtered client-side |
| `etsy_export_all_listings` | (helper) | `/application/shops/{shop_id}/listings` | paginated `state` + `limit=100` + `offset` |
| `etsy_export_all_receipts` | (helper) | `/application/shops/{shop_id}/receipts` | paginated `min_created` + `limit=100` + `offset` |
| `etsy_export_all_reviews` | (helper) | `/application/shops/{shop_id}/reviews` | paginated `limit=100` + `offset` |

---

## Task 1: paginate_all helper in http.py

**Files:**
- Modify: `etsy_mcp/http.py` — add `paginate_all` async function
- Modify: `tests/unit/test_http.py` — add 2 tests

The helper paginates an Etsy GET endpoint at `limit=100` until a page returns fewer results, then returns the concatenated list. All three export tools and any future bulk-read code use it.

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_http.py`:

```python
from etsy_mcp.http import paginate_all


@respx.mock
async def test_paginate_all_concatenates_pages_until_short(tmp_tokens_path):
    _seed_tokens(tmp_tokens_path)
    page1 = {"count": 250, "results": [{"id": i} for i in range(100)]}
    page2 = {"count": 250, "results": [{"id": i} for i in range(100, 200)]}
    page3 = {"count": 250, "results": [{"id": i} for i in range(200, 250)]}  # short page → stop

    respx.get(f"{ETSY_API_BASE}/application/shops/42/widgets").mock(
        side_effect=[
            httpx.Response(200, json=page1),
            httpx.Response(200, json=page2),
            httpx.Response(200, json=page3),
        ]
    )

    results = await paginate_all(
        "GET",
        "/application/shops/42/widgets",
        keystring="kkey",
        tokens_path=str(tmp_tokens_path),
        params={"state": "active"},
        page_size=100,
    )

    assert len(results) == 250
    assert results[0]["id"] == 0
    assert results[-1]["id"] == 249


@respx.mock
async def test_paginate_all_empty_first_page_returns_empty_list(tmp_tokens_path):
    _seed_tokens(tmp_tokens_path)
    respx.get(f"{ETSY_API_BASE}/application/shops/42/widgets").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    results = await paginate_all(
        "GET",
        "/application/shops/42/widgets",
        keystring="kkey",
        tokens_path=str(tmp_tokens_path),
        params={},
        page_size=100,
    )

    assert results == []
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd "<project root>"
.venv/bin/pytest tests/unit/test_http.py::test_paginate_all_concatenates_pages_until_short -v
```

Expected: FAIL — `cannot import name 'paginate_all' from 'etsy_mcp.http'`.

- [ ] **Step 3: Append `paginate_all` to `etsy_mcp/http.py`**

Append at the END of `etsy_mcp/http.py` (after the existing `_safe_json` function):

```python


async def paginate_all(
    method: str,
    path: str,
    *,
    keystring: str,
    tokens_path: str,
    params: dict | None = None,
    page_size: int = 100,
    results_key: str = "results",
) -> list[dict]:
    """Fetch every page of an Etsy paginated endpoint, return concatenated results.

    Calls etsy_request repeatedly with increasing offset until a page returns
    fewer than page_size items (or zero). Any EtsyMCPError raised by the
    underlying request propagates — the caller wraps it.

    Args:
        method: HTTP method (typically "GET").
        path: Etsy API path (relative or absolute).
        keystring: Etsy app keystring.
        tokens_path: Path to .tokens.json.
        params: Query parameters added to every request. `limit` and `offset`
            are managed by this function — do not include them.
        page_size: Items per page. Etsy max is 100.
        results_key: The key under which the page's items live. Etsy uses
            "results" universally; the param exists for forward-compatibility.

    Returns:
        Flat list of all items across all pages.
    """
    base_params = dict(params or {})
    offset = 0
    out: list[dict] = []

    while True:
        page_params = {**base_params, "limit": page_size, "offset": offset}
        page = await etsy_request(
            method,
            path,
            keystring=keystring,
            tokens_path=tokens_path,
            params=page_params,
        )
        if not isinstance(page, dict):
            return out  # Defensive — etsy_request normally returns dict for paginated endpoints.

        items = page.get(results_key) or []
        out.extend(items)

        if len(items) < page_size:
            break
        offset += page_size

    return out
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_http.py -v
```

Expected: 14 passed (12 existing + 2 new).

- [ ] **Step 5: Run full suite for no regressions**

```bash
.venv/bin/pytest -v
```

Expected: 68 passed (66 baseline + 2 new).

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/http.py tests/unit/test_http.py
git commit -m "$(cat <<'EOF'
feat(http): paginate_all helper for bulk reads

Single async function that iterates an Etsy paginated endpoint at
limit=100 + offset until a short page is seen, then returns the
concatenated results list. Used by Phase 1b bulk-export tools and
future bulk-read code.

Caller passes base params (state, min_created, etc.); the helper
manages limit/offset. Errors from the underlying etsy_request
propagate so callers wrap with the standard try/except EtsyMCPError.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: conftest.py — make_tools handles modules without shop_id_getter

**Files:**
- Modify: `tests/conftest.py`

`register_taxonomy_tools` will not accept `shop_id_getter` (taxonomy is shop-agnostic). The existing `make_tools` factory always passes that kwarg, which would cause a TypeError. Update it to introspect the register function's signature and only pass kwargs it accepts.

- [ ] **Step 1: Update `tests/conftest.py`**

Open `<project root>/tests/conftest.py` and replace the `make_tools` fixture body. The full file should be:

```python
"""Shared pytest fixtures for Etsy MCP tests."""

from __future__ import annotations

import inspect

import pytest

from etsy_mcp.auth import TokenStore


@pytest.fixture
def tmp_tokens_path(tmp_path):
    """Provide a temp path for .tokens.json that's isolated per test."""
    return tmp_path / "tokens.json"


@pytest.fixture
def seeded_tokens_path(tmp_tokens_path):
    """A tokens file that's already valid for ~1 hour. Tools can be called without
    triggering a refresh against Etsy."""
    TokenStore(tmp_tokens_path).save(
        access_token="test-acc",
        refresh_token="test-ref",
        expires_in=3600,
        scope="listings_r listings_w listings_d shops_r transactions_r feedback_r",
    )
    return tmp_tokens_path


@pytest.fixture
def make_tools(seeded_tokens_path):
    """Factory: given a register_<domain>_tools function, return the dict of
    tool callables. Inspects the register function's signature to only pass
    kwargs it accepts, so modules without shop_id_getter (e.g. taxonomy) work.

    Usage:
        tools = make_tools(register_listing_tools, shop_id="123")
        result = await tools["etsy_list_listings"](limit=5)
    """

    def _factory(register_fn, *, shop_id="999"):
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("etsy-test")
        sig = inspect.signature(register_fn)
        kwargs = {
            "keystring": "test-keystring",
            "tokens_path": seeded_tokens_path,
        }
        if "shop_id_getter" in sig.parameters:
            kwargs["shop_id_getter"] = lambda: shop_id
        return register_fn(mcp, **kwargs)

    return _factory
```

- [ ] **Step 2: Verify the existing test suite still passes**

```bash
cd "<project root>"
.venv/bin/pytest -v 2>&1 | tail -3
```

Expected: 68 passed (no regression).

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "$(cat <<'EOF'
test: make_tools fixture skips shop_id_getter for shop-agnostic modules

Inspects register_fn's signature; only passes shop_id_getter when the
function accepts it. Lets taxonomy tests (and any future shop-agnostic
modules) reuse the fixture without errors.

Also widens the seeded scope string to cover Phase 1b write scopes
(listings_w, listings_d) so test setup mirrors what bootstrap requests.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: listings.py — etsy_create_draft_listing

**Files:**
- Modify: `etsy_mcp/listings.py` — add the new tool to the existing `register_listing_tools` factory
- Modify: `tests/unit/test_listings.py` — add tests

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_listings.py`:

```python
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
```

- [ ] **Step 2: Run test to verify failure**

```bash
.venv/bin/pytest tests/unit/test_listings.py::test_create_draft_listing_required_fields -v
```

Expected: FAIL — `etsy_create_draft_listing` not in tools dict.

- [ ] **Step 3: Add the tool to `register_listing_tools`**

In `<project root>/etsy_mcp/listings.py`, INSIDE `register_listing_tools` (after `etsy_get_listing_images`, before the return dict), add:

```python
    @mcp.tool()
    async def etsy_create_draft_listing(
        title: str,
        description: str,
        price_usd: float,
        quantity: int,
        taxonomy_id: int,
        who_made: str,
        when_made: str,
        is_supply: bool,
        shipping_profile_id: int,
        return_policy_id: int | None = None,
        materials: list[str] | None = None,
        tags: list[str] | None = None,
        processing_min: int | None = None,
        processing_max: int | None = None,
    ) -> dict[str, Any]:
        """Create a draft listing in your shop.

        Args:
            title: Listing title (max 140 chars).
            description: Body description.
            price_usd: Price as a float in shop currency (Etsy interprets this in your shop's currency).
            quantity: Available quantity.
            taxonomy_id: Etsy seller taxonomy id. Look up via etsy_taxonomy_search.
            who_made: One of {i_did, someone_else, collective}.
            when_made: One of {made_to_order, 2020_2025, 2010_2019, 2006_2009, before_2006, ...}.
            is_supply: True if this is a craft supply.
            shipping_profile_id: Required. Look up via etsy_list_shipping_profiles (Tier 2).
            return_policy_id: Optional return policy id.
            materials: Up to 13 strings.
            tags: Up to 13 strings.
            processing_min: Min days to process (for made-to-order).
            processing_max: Max days to process.
        """
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()

        data: dict[str, Any] = {
            "title": title,
            "description": description,
            "price": f"{price_usd:.2f}",
            "quantity": quantity,
            "taxonomy_id": taxonomy_id,
            "who_made": who_made,
            "when_made": when_made,
            "is_supply": "true" if is_supply else "false",
            "shipping_profile_id": shipping_profile_id,
        }
        if return_policy_id is not None:
            data["return_policy_id"] = return_policy_id
        if materials:
            data["materials"] = materials  # httpx serializes lists as repeated keys
        if tags:
            data["tags"] = tags
        if processing_min is not None:
            data["processing_min"] = processing_min
        if processing_max is not None:
            data["processing_max"] = processing_max

        try:
            return await etsy_request(
                "POST",
                f"/application/shops/{shop_id}/listings",
                keystring=keystring,
                tokens_path=str(tokens_path),
                data=data,
            )
        except EtsyMCPError as exc:
            return exc.to_dict()
```

UPDATE the return dict at the bottom of `register_listing_tools`:

```python
    return {
        "etsy_list_listings": etsy_list_listings,
        "etsy_search_listings": etsy_search_listings,
        "etsy_get_listing": etsy_get_listing,
        "etsy_get_listing_inventory": etsy_get_listing_inventory,
        "etsy_get_listing_images": etsy_get_listing_images,
        "etsy_create_draft_listing": etsy_create_draft_listing,
    }
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_listings.py -v
```

Expected: 15 passed (12 existing + 3 new).

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 71 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/listings.py tests/unit/test_listings.py
git commit -m "$(cat <<'EOF'
feat(listings): etsy_create_draft_listing

Maps to POST /shops/{shop_id}/listings with form-encoded body. Sends
the 9 required Etsy fields (title, description, price, quantity,
taxonomy_id, who_made, when_made, is_supply, shipping_profile_id)
plus 5 optionals (return_policy_id, materials[], tags[],
processing_min, processing_max). Bool serialized as 'true'/'false';
arrays as repeated form keys per Etsy convention; price as 2-decimal
string in shop currency.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: listings.py — etsy_update_listing (PATCH)

**Files:**
- Modify: `etsy_mcp/listings.py`
- Modify: `tests/unit/test_listings.py`

Etsy v3 uses **PATCH** (not PUT) for partial listing updates. Only fields the user passes are sent.

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_listings.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify failure**

```bash
.venv/bin/pytest tests/unit/test_listings.py::test_update_listing_sends_only_provided_fields -v
```

Expected: FAIL.

- [ ] **Step 3: Add the tool**

INSIDE `register_listing_tools` (after `etsy_create_draft_listing`, before the return), add:

```python
    @mcp.tool()
    async def etsy_update_listing(
        listing_id: int,
        title: str | None = None,
        description: str | None = None,
        price_usd: float | None = None,
        quantity: int | None = None,
        state: str | None = None,
        tags: list[str] | None = None,
        materials: list[str] | None = None,
        taxonomy_id: int | None = None,
        return_policy_id: int | None = None,
        shipping_profile_id: int | None = None,
    ) -> dict[str, Any]:
        """Partial update of a listing. Only fields you pass are sent (PATCH).

        Args:
            listing_id: The listing to update.
            title: New title.
            description: New description.
            price_usd: New price (shop currency).
            quantity: New quantity.
            state: One of {active, inactive, draft}. Used to publish a draft or unlist.
            tags: Replace tag set. Up to 13.
            materials: Replace material set. Up to 13.
            taxonomy_id: Move to a different category.
            return_policy_id: Change return policy.
            shipping_profile_id: Change shipping profile.
        """
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()

        data: dict[str, Any] = {}
        if title is not None:
            data["title"] = title
        if description is not None:
            data["description"] = description
        if price_usd is not None:
            data["price"] = f"{price_usd:.2f}"
        if quantity is not None:
            data["quantity"] = quantity
        if state is not None:
            data["state"] = state
        if tags is not None:
            data["tags"] = tags
        if materials is not None:
            data["materials"] = materials
        if taxonomy_id is not None:
            data["taxonomy_id"] = taxonomy_id
        if return_policy_id is not None:
            data["return_policy_id"] = return_policy_id
        if shipping_profile_id is not None:
            data["shipping_profile_id"] = shipping_profile_id

        if not data:
            return {
                "error": "No fields provided to update.",
                "code": "validation_failed",
            }

        try:
            return await etsy_request(
                "PATCH",
                f"/application/shops/{shop_id}/listings/{listing_id}",
                keystring=keystring,
                tokens_path=str(tokens_path),
                data=data,
            )
        except EtsyMCPError as exc:
            return exc.to_dict()
```

UPDATE the return dict to include `etsy_update_listing`.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_listings.py -v
```

Expected: 18 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 74 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/listings.py tests/unit/test_listings.py
git commit -m "$(cat <<'EOF'
feat(listings): etsy_update_listing — partial updates via PATCH

PATCH /shops/{shop_id}/listings/{listing_id} with only the fields the
caller actually passes. Useful for re-pricing, re-tagging, publishing
drafts (state='active'), or unlisting (state='inactive') without
re-sending the full listing payload.

Returns a structured 'no fields provided' error when called with just
listing_id and no updates — prevents accidental no-op API calls.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: listings.py — etsy_delete_listing (with confirm guard)

**Files:**
- Modify: `etsy_mcp/listings.py`
- Modify: `tests/unit/test_listings.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_listings.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify failure**

```bash
.venv/bin/pytest tests/unit/test_listings.py::test_delete_listing_without_confirm_refuses -v
```

Expected: FAIL — `etsy_delete_listing` not registered.

- [ ] **Step 3: Add the tool**

INSIDE `register_listing_tools` (after `etsy_update_listing`, before the return), add:

```python
    @mcp.tool()
    async def etsy_delete_listing(
        listing_id: int,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Delete a listing permanently. Requires confirm=True as a safety guard.

        Etsy's delete endpoint is shop-agnostic, so this does not need
        ETSY_SHOP_ID — but the listing must belong to your shop or Etsy
        rejects with 403/404.
        """
        if not confirm:
            return {
                "error": (
                    f"Refusing to delete listing {listing_id} without confirm=True. "
                    "This action is permanent."
                ),
                "code": "validation_failed",
            }

        try:
            await etsy_request(
                "DELETE",
                f"/application/listings/{listing_id}",
                keystring=keystring,
                tokens_path=str(tokens_path),
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

        return {"deleted": True, "listing_id": listing_id}
```

UPDATE the return dict to include `etsy_delete_listing`.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_listings.py -v
```

Expected: 21 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 77 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/listings.py tests/unit/test_listings.py
git commit -m "$(cat <<'EOF'
feat(listings): etsy_delete_listing with confirm=True guard

Maps to DELETE /listings/{listing_id} (shop-agnostic). The confirm
flag must be explicitly true; otherwise the tool returns a clear
validation_failed error and never hits the network — preventing an
LLM (or a human in a hurry) from deleting a listing without an
explicit acknowledgment.

Returns {deleted: true, listing_id} on success rather than the raw
204-empty response so the caller has something to verify against.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: listings.py — etsy_upload_listing_image (multipart)

**Files:**
- Modify: `etsy_mcp/listings.py`
- Modify: `tests/unit/test_listings.py`

Multipart file upload uses `httpx`'s `files=` kwarg, which `etsy_request` already passes through.

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_listings.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify failure**

```bash
.venv/bin/pytest tests/unit/test_listings.py::test_upload_listing_image_uploads_file -v
```

Expected: FAIL.

- [ ] **Step 3: Add the tool**

INSIDE `register_listing_tools` (after `etsy_delete_listing`, before the return), add:

```python
    @mcp.tool()
    async def etsy_upload_listing_image(
        listing_id: int,
        image_path: str,
        rank: int = 1,
        alt_text: str | None = None,
    ) -> dict[str, Any]:
        """Upload an image to a listing. Reads the file from disk.

        Args:
            listing_id: The listing to attach the image to.
            image_path: Absolute or relative filesystem path to a .jpg/.png/.gif.
            rank: Display order (1 = first). Default 1.
            alt_text: Accessibility text. Optional but recommended.
        """
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()

        path_obj = Path(image_path)
        if not path_obj.is_file():
            return {
                "error": f"Image file not found at {image_path}",
                "code": "validation_failed",
            }

        try:
            with path_obj.open("rb") as f:
                file_bytes = f.read()
            files = {"image": (path_obj.name, file_bytes, "application/octet-stream")}
            data: dict[str, Any] = {"rank": rank}
            if alt_text is not None:
                data["alt_text"] = alt_text

            return await etsy_request(
                "POST",
                f"/application/shops/{shop_id}/listings/{listing_id}/images",
                keystring=keystring,
                tokens_path=str(tokens_path),
                files=files,
                data=data,
            )
        except EtsyMCPError as exc:
            return exc.to_dict()
        except OSError as exc:
            return {
                "error": f"Could not read image file: {exc}",
                "code": "validation_failed",
            }
```

UPDATE the return dict to include `etsy_upload_listing_image`.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_listings.py -v
```

Expected: 24 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 80 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/listings.py tests/unit/test_listings.py
git commit -m "$(cat <<'EOF'
feat(listings): etsy_upload_listing_image (multipart)

POST /shops/{shop_id}/listings/{listing_id}/images with multipart
form-data. Reads the file from disk, sends as 'image' part with
rank + alt_text as form fields. etsy_request already supports
httpx's files= kwarg so no transport changes were needed.

Pre-flight checks the file exists and returns a clear
validation_failed error if missing rather than letting the OS
exception escape — keeps the boundary contract.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: listings.py — etsy_update_listing_inventory

**Files:**
- Modify: `etsy_mcp/listings.py`
- Modify: `tests/unit/test_listings.py`

PUT JSON body to `/application/listings/{listing_id}/inventory` (shop-agnostic).

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_listings.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify failure**

```bash
.venv/bin/pytest tests/unit/test_listings.py::test_update_listing_inventory_sends_products_json -v
```

Expected: FAIL.

- [ ] **Step 3: Add the tool**

INSIDE `register_listing_tools` (after `etsy_upload_listing_image`, before the return), add:

```python
    @mcp.tool()
    async def etsy_update_listing_inventory(
        listing_id: int,
        products: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Replace the listing's inventory products array.

        Args:
            listing_id: The listing whose inventory you're updating.
            products: List of product dicts. Each is:
                {
                  "sku": str,
                  "offerings": [{"price": float, "quantity": int, "is_enabled": bool}],
                  "property_values": [...]   # optional, for variants
                }
        """
        if not products:
            return {
                "error": "products list is empty — pass at least one product entry.",
                "code": "validation_failed",
            }

        try:
            return await etsy_request(
                "PUT",
                f"/application/listings/{listing_id}/inventory",
                keystring=keystring,
                tokens_path=str(tokens_path),
                json_body={"products": products},
            )
        except EtsyMCPError as exc:
            return exc.to_dict()
```

UPDATE the return dict to include `etsy_update_listing_inventory`.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_listings.py -v
```

Expected: 26 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 82 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/listings.py tests/unit/test_listings.py
git commit -m "$(cat <<'EOF'
feat(listings): etsy_update_listing_inventory

PUT /listings/{listing_id}/inventory with JSON body {products: [...]}.
Each product carries SKU, offerings (price + quantity + is_enabled),
and optional property_values for variants (size, color).

Refuses an empty products list as a guard — replacing inventory
with [] would remove every variant and is almost certainly a bug.

Listings module now has 5 write tools (Phase 1b minus the deferred
images-order tool) on top of the 5 read tools from Phase 1a.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: taxonomy.py — etsy_taxonomy_search

**Files:**
- Create: `etsy_mcp/taxonomy.py`
- Create: `tests/unit/test_taxonomy.py`

Etsy seller taxonomy endpoint returns the entire tree. We fetch once, cache in a module-level dict keyed by keystring, then search the flat list of `(taxonomy_id, name, full_path, level)` tuples client-side.

- [ ] **Step 1: Write failing tests**

Create `<project root>/tests/unit/test_taxonomy.py`:

```python
"""Tests for etsy_mcp.taxonomy tools."""

from __future__ import annotations

import httpx
import pytest
import respx

from etsy_mcp.http import ETSY_API_BASE
from etsy_mcp.taxonomy import register_taxonomy_tools, _CACHE


@pytest.fixture(autouse=True)
def clear_taxonomy_cache():
    """Each test starts with a fresh taxonomy cache."""
    _CACHE.clear()
    yield
    _CACHE.clear()


_FAKE_TREE = {
    "results": [
        {
            "id": 1,
            "name": "Home & Living",
            "level": 0,
            "children": [
                {
                    "id": 11,
                    "name": "Bedding",
                    "level": 1,
                    "children": [
                        {"id": 111, "name": "Cushions", "level": 2, "children": []},
                        {"id": 112, "name": "Pillows", "level": 2, "children": []},
                    ],
                },
                {
                    "id": 12,
                    "name": "Outdoor & Gardening",
                    "level": 1,
                    "children": [],
                },
            ],
        },
        {
            "id": 2,
            "name": "Jewelry",
            "level": 0,
            "children": [],
        },
    ],
}


@respx.mock
async def test_taxonomy_search_matches_node_name(make_tools):
    tools = make_tools(register_taxonomy_tools)
    respx.get(f"{ETSY_API_BASE}/application/seller-taxonomy/nodes").mock(
        return_value=httpx.Response(200, json=_FAKE_TREE)
    )

    result = await tools["etsy_taxonomy_search"](query="cushion")

    # "Cushions" should be the top match
    assert result[0]["taxonomy_id"] == 111
    assert result[0]["name"] == "Cushions"
    assert result[0]["full_path"] == "Home & Living > Bedding > Cushions"
    assert result[0]["level"] == 2


@respx.mock
async def test_taxonomy_search_matches_full_path(make_tools):
    tools = make_tools(register_taxonomy_tools)
    respx.get(f"{ETSY_API_BASE}/application/seller-taxonomy/nodes").mock(
        return_value=httpx.Response(200, json=_FAKE_TREE)
    )

    result = await tools["etsy_taxonomy_search"](query="bedding")

    # Bedding itself + its 2 descendants all match (descendants via path containing "Bedding")
    ids = sorted(r["taxonomy_id"] for r in result)
    assert ids == [11, 111, 112]


@respx.mock
async def test_taxonomy_search_caches_tree(make_tools):
    """Two calls should result in only ONE network fetch — tree is cached."""
    tools = make_tools(register_taxonomy_tools)
    route = respx.get(f"{ETSY_API_BASE}/application/seller-taxonomy/nodes").mock(
        return_value=httpx.Response(200, json=_FAKE_TREE)
    )

    await tools["etsy_taxonomy_search"](query="cushion")
    await tools["etsy_taxonomy_search"](query="jewelry")

    assert route.call_count == 1


@respx.mock
async def test_taxonomy_search_no_matches_returns_empty_list(make_tools):
    tools = make_tools(register_taxonomy_tools)
    respx.get(f"{ETSY_API_BASE}/application/seller-taxonomy/nodes").mock(
        return_value=httpx.Response(200, json=_FAKE_TREE)
    )

    result = await tools["etsy_taxonomy_search"](query="nonexistent-thing-xyz")

    assert result == []
```

- [ ] **Step 2: Run test to verify failure**

```bash
.venv/bin/pytest tests/unit/test_taxonomy.py -v
```

Expected: FAIL — `cannot import name 'register_taxonomy_tools' from 'etsy_mcp.taxonomy'`.

- [ ] **Step 3: Write the implementation**

Create `<project root>/etsy_mcp/taxonomy.py`:

```python
"""Taxonomy lookup for Etsy MCP.

The Etsy seller taxonomy is a tree of ~3000 category nodes. This module
fetches the tree once via getSellerTaxonomyNodes, caches it in-process,
and offers a substring search returning the top 20 matches.

Cache is keyed by keystring so multiple shops in tests don't collide.
The tree changes very rarely; per-process caching is safe.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from .errors import EtsyMCPError
from .http import etsy_request

# Module-level cache: {keystring: list[{taxonomy_id, name, level, full_path}]}
_CACHE: dict[str, list[dict[str, Any]]] = {}


def _flatten(nodes: list[dict[str, Any]], parent_path: str = "") -> list[dict[str, Any]]:
    """Walk the Etsy seller-taxonomy tree, return flat list of nodes with full paths."""
    out: list[dict[str, Any]] = []
    for node in nodes:
        name = node.get("name", "")
        path = f"{parent_path} > {name}" if parent_path else name
        out.append(
            {
                "taxonomy_id": node.get("id"),
                "name": name,
                "level": node.get("level", 0),
                "full_path": path,
            }
        )
        children = node.get("children") or []
        if children:
            out.extend(_flatten(children, path))
    return out


def register_taxonomy_tools(
    mcp: FastMCP,
    *,
    keystring: str,
    tokens_path: str | Path,
) -> dict[str, Callable]:
    """Register taxonomy tools (no shop_id_getter — taxonomy is shop-agnostic)."""

    async def _ensure_tree() -> list[dict[str, Any]]:
        if keystring in _CACHE:
            return _CACHE[keystring]
        tree = await etsy_request(
            "GET",
            "/application/seller-taxonomy/nodes",
            keystring=keystring,
            tokens_path=str(tokens_path),
        )
        nodes = tree.get("results") if isinstance(tree, dict) else None
        if not isinstance(nodes, list):
            return []
        flat = _flatten(nodes)
        _CACHE[keystring] = flat
        return flat

    @mcp.tool()
    async def etsy_taxonomy_search(query: str) -> list[dict[str, Any]]:
        """Find Etsy seller-taxonomy nodes by keyword.

        Substring match (case-insensitive) against the node's name AND its full
        path. Returns the top 20 matches sorted by depth (deeper first — more
        specific categories) then by path length.

        Use the returned taxonomy_id when calling etsy_create_draft_listing.
        """
        try:
            tree = await _ensure_tree()
        except EtsyMCPError as exc:
            return [exc.to_dict()]  # Error path returned as a single-element list for tool consistency.

        needle = query.lower()
        matches = [
            node
            for node in tree
            if needle in node["name"].lower() or needle in node["full_path"].lower()
        ]
        # Deeper matches first (more specific), then alphabetical
        matches.sort(key=lambda n: (-n["level"], n["full_path"]))
        return matches[:20]

    return {"etsy_taxonomy_search": etsy_taxonomy_search}
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_taxonomy.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 86 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/taxonomy.py tests/unit/test_taxonomy.py
git commit -m "$(cat <<'EOF'
feat(taxonomy): etsy_taxonomy_search with in-process tree cache

Fetches the seller-taxonomy tree (~3000 nodes) once via
GET /application/seller-taxonomy/nodes, flattens to a list of
{taxonomy_id, name, level, full_path}, caches in a module-level
dict keyed by keystring (so test scenarios with different
keystrings don't collide), and serves a case-insensitive substring
search over name + full_path. Top 20 results, deepest matches first.

Required input for etsy_create_draft_listing's taxonomy_id field —
without this tool the user would have to scrape the seller
dashboard or hard-code IDs.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: exports.py — etsy_export_all_listings (with CSV flatten helper)

**Files:**
- Create: `etsy_mcp/exports.py`
- Create: `tests/unit/test_exports.py`

This task introduces the export module + the shared CSV flattening helper. Subsequent tasks (10, 11) reuse the helper.

- [ ] **Step 1: Write failing tests**

Create `<project root>/tests/unit/test_exports.py`:

```python
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
```

- [ ] **Step 2: Run test to verify failure**

```bash
.venv/bin/pytest tests/unit/test_exports.py -v
```

Expected: FAIL — `cannot import name 'register_export_tools'`.

- [ ] **Step 3: Write the implementation**

Create `<project root>/etsy_mcp/exports.py`:

```python
"""Bulk export tools for Etsy MCP.

Exports listings, receipts, and reviews to JSON and/or CSV. JSON is the raw
API response (a flat list of dicts). CSV is one row per resource with nested
fields dot-joined (e.g. price.amount, price.currency_code) and lists JSON-encoded.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from .errors import EtsyMCPError, missing_shop_id_error
from .http import paginate_all


def _flatten_dict(d: dict[str, Any], parent_key: str = "", sep: str = ".") -> dict[str, Any]:
    """Flatten nested dicts using dot-joined keys. Lists are JSON-encoded as
    strings. Nones become empty strings (CSV-safe)."""
    items: dict[str, Any] = {}
    for k, v in d.items():
        key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.update(_flatten_dict(v, key, sep))
        elif isinstance(v, list):
            items[key] = json.dumps(v)
        elif v is None:
            items[key] = ""
        else:
            items[key] = v
    return items


def _write_json(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(rows, indent=2, default=str))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("")
        return
    flat_rows = [_flatten_dict(r) for r in rows]
    # Union of all keys preserves any field that appears in at least one row.
    headers: list[str] = []
    seen: set[str] = set()
    for r in flat_rows:
        for k in r.keys():
            if k not in seen:
                seen.add(k)
                headers.append(k)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for r in flat_rows:
            writer.writerow(r)


def _write_outputs(
    rows: list[dict[str, Any]],
    output_dir: Path,
    base_name: str,
    fmt: str,
) -> list[str]:
    """Write JSON and/or CSV based on fmt. Returns list of file paths written."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    if fmt in ("json", "both"):
        json_path = output_dir / f"{base_name}.json"
        _write_json(json_path, rows)
        written.append(str(json_path))
    if fmt in ("csv", "both"):
        csv_path = output_dir / f"{base_name}.csv"
        _write_csv(csv_path, rows)
        written.append(str(csv_path))
    return written


def register_export_tools(
    mcp: FastMCP,
    *,
    keystring: str,
    tokens_path: str | Path,
    shop_id_getter: Callable[[], str],
) -> dict[str, Callable]:
    """Register bulk-export tools on the given FastMCP instance."""

    @mcp.tool()
    async def etsy_export_all_listings(
        output_dir: str,
        format: str = "both",
        state: str = "active",
    ) -> dict[str, Any]:
        """Paginate every listing in your shop (in the given state) and write
        to JSON and/or CSV files in output_dir.

        Args:
            output_dir: Directory to write output files into. Created if missing.
            format: 'json', 'csv', or 'both'. Default 'both'.
            state: Listing state filter. Default 'active'. Etsy doesn't expose
                an 'all states' query, so to export inactive/draft/expired/sold_out
                you call this tool once per state.
        """
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()
        if format not in ("json", "csv", "both"):
            return {"error": f"Invalid format '{format}'. Use json, csv, or both.", "code": "validation_failed"}

        try:
            rows = await paginate_all(
                "GET",
                f"/application/shops/{shop_id}/listings",
                keystring=keystring,
                tokens_path=str(tokens_path),
                params={"state": state},
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

        files = _write_outputs(rows, Path(output_dir), "listings", format)
        return {"listings_count": len(rows), "files": files}

    return {"etsy_export_all_listings": etsy_export_all_listings}
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_exports.py -v
```

Expected: 6 passed (3 helper tests + 3 listings export tests).

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 92 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/exports.py tests/unit/test_exports.py
git commit -m "$(cat <<'EOF'
feat(exports): etsy_export_all_listings + CSV flatten helper

New exports module with:
- _flatten_dict: dot-joins nested keys, JSON-encodes lists, blanks Nones
- _write_json / _write_csv / _write_outputs: writes per the requested format
- etsy_export_all_listings: paginates /shops/{shop_id}/listings via the
  Phase 1b paginate_all helper, then dumps to JSON/CSV in output_dir

State defaults to 'active' since Etsy has no 'all states' query — caller
passes state='draft' (etc.) for other states. Empty input writes an
empty CSV (no header), preserving idempotency.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: exports.py — etsy_export_all_receipts (since→unix conversion)

**Files:**
- Modify: `etsy_mcp/exports.py`
- Modify: `tests/unit/test_exports.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_exports.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify failure**

```bash
.venv/bin/pytest tests/unit/test_exports.py::test_export_all_receipts_with_since -v
```

Expected: FAIL.

- [ ] **Step 3: Add the tool**

In `etsy_mcp/exports.py`, INSIDE `register_export_tools` (after `etsy_export_all_listings`, before the return), add:

```python
    @mcp.tool()
    async def etsy_export_all_receipts(
        output_dir: str,
        format: str = "both",
        since: str | None = None,
    ) -> dict[str, Any]:
        """Paginate every receipt in your shop (optionally since an ISO date)
        and write to JSON and/or CSV.

        Args:
            output_dir: Directory to write output files into.
            format: 'json', 'csv', or 'both'. Default 'both'.
            since: ISO date string (YYYY-MM-DD) — only receipts created on or
                after this date. Converted to unix timestamp for Etsy's
                min_created filter.
        """
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()
        if format not in ("json", "csv", "both"):
            return {"error": f"Invalid format '{format}'. Use json, csv, or both.", "code": "validation_failed"}

        params: dict[str, Any] = {}
        if since is not None:
            from datetime import datetime, timezone
            try:
                dt = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                return {
                    "error": f"Invalid since='{since}'. Use ISO date format YYYY-MM-DD.",
                    "code": "validation_failed",
                }
            params["min_created"] = int(dt.timestamp())

        try:
            rows = await paginate_all(
                "GET",
                f"/application/shops/{shop_id}/receipts",
                keystring=keystring,
                tokens_path=str(tokens_path),
                params=params,
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

        files = _write_outputs(rows, Path(output_dir), "receipts", format)
        return {"receipts_count": len(rows), "files": files}
```

UPDATE the return dict at the bottom of `register_export_tools`:

```python
    return {
        "etsy_export_all_listings": etsy_export_all_listings,
        "etsy_export_all_receipts": etsy_export_all_receipts,
    }
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_exports.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 94 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/exports.py tests/unit/test_exports.py
git commit -m "$(cat <<'EOF'
feat(exports): etsy_export_all_receipts with ISO since→unix conversion

Paginates /shops/{shop_id}/receipts via paginate_all, optionally
filtered by min_created. The since= parameter is an ISO date
(YYYY-MM-DD) for ergonomics; converted to a UTC midnight unix
timestamp before being sent to Etsy. Invalid formats return a
validation_failed error before any network call.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: exports.py — etsy_export_all_reviews

**Files:**
- Modify: `etsy_mcp/exports.py`
- Modify: `tests/unit/test_exports.py`

- [ ] **Step 1: Append failing test**

Append to `tests/unit/test_exports.py`:

```python
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
```

- [ ] **Step 2: Run test to verify failure**

```bash
.venv/bin/pytest tests/unit/test_exports.py::test_export_all_reviews_writes_csv -v
```

Expected: FAIL.

- [ ] **Step 3: Add the tool**

INSIDE `register_export_tools` (after `etsy_export_all_receipts`, before the return), add:

```python
    @mcp.tool()
    async def etsy_export_all_reviews(
        output_dir: str,
        format: str = "both",
    ) -> dict[str, Any]:
        """Paginate every review in your shop and write to JSON and/or CSV.

        Args:
            output_dir: Directory to write output files into.
            format: 'json', 'csv', or 'both'. Default 'both'.
        """
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()
        if format not in ("json", "csv", "both"):
            return {"error": f"Invalid format '{format}'. Use json, csv, or both.", "code": "validation_failed"}

        try:
            rows = await paginate_all(
                "GET",
                f"/application/shops/{shop_id}/reviews",
                keystring=keystring,
                tokens_path=str(tokens_path),
                params={},
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

        files = _write_outputs(rows, Path(output_dir), "reviews", format)
        return {"reviews_count": len(rows), "files": files}
```

UPDATE the return dict:

```python
    return {
        "etsy_export_all_listings": etsy_export_all_listings,
        "etsy_export_all_receipts": etsy_export_all_receipts,
        "etsy_export_all_reviews": etsy_export_all_reviews,
    }
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_exports.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 95 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/exports.py tests/unit/test_exports.py
git commit -m "$(cat <<'EOF'
feat(exports): etsy_export_all_reviews

Paginates /shops/{shop_id}/reviews via paginate_all. No filter params
— Etsy's reviews endpoint doesn't accept date filtering at the API
level for the seller view, so the export is always 'everything since
the shop opened'. Caller can post-filter the JSON/CSV by created_at if
needed.

Exports module now has 3 tools — all of Phase 1b's bulk-export surface.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: server.py — register taxonomy + export tools

**Files:**
- Modify: `server.py`

- [ ] **Step 1: Read current server.py to confirm location**

```bash
cd "<project root>"
grep -n "register_" server.py
```

You should see four existing register calls (shop, listings, receipts, reviews).

- [ ] **Step 2: Add the two new imports**

Open `<project root>/server.py`. Find the existing block:

```python
from etsy_mcp.listings import register_listing_tools
from etsy_mcp.receipts import register_receipt_tools
from etsy_mcp.reviews import register_review_tools
from etsy_mcp.shop import register_shop_tools
```

Replace with (alphabetical):

```python
from etsy_mcp.exports import register_export_tools
from etsy_mcp.listings import register_listing_tools
from etsy_mcp.receipts import register_receipt_tools
from etsy_mcp.reviews import register_review_tools
from etsy_mcp.shop import register_shop_tools
from etsy_mcp.taxonomy import register_taxonomy_tools
```

- [ ] **Step 3: Add the two new register calls**

Find the existing register calls block (after `mcp = FastMCP("etsy")`). It currently ends with:

```python
register_review_tools(
    mcp,
    keystring=KEYSTRING,
    tokens_path=TOKENS_PATH,
    shop_id_getter=_shop_id,
)
```

APPEND these two calls right after it:

```python
register_taxonomy_tools(
    mcp,
    keystring=KEYSTRING,
    tokens_path=TOKENS_PATH,
)
register_export_tools(
    mcp,
    keystring=KEYSTRING,
    tokens_path=TOKENS_PATH,
    shop_id_getter=_shop_id,
)
```

Note `register_taxonomy_tools` does NOT take `shop_id_getter` (taxonomy is shop-agnostic).

- [ ] **Step 4: Verify the server module imports cleanly**

```bash
ETSY_KEYSTRING=test_placeholder .venv/bin/python -c "import server; print('OK')"
```

Expected: `OK`.

- [ ] **Step 5: Verify the server starts without crashing**

```bash
ETSY_KEYSTRING=test_placeholder timeout 3 .venv/bin/python server.py 2>&1 | head -10 || true
```

Expected: starts and waits for stdio. No traceback.

- [ ] **Step 6: Run the full test suite**

```bash
.venv/bin/pytest -v
```

Expected: 95 passed (no new tests in this task — only wires existing tools onto the FastMCP instance).

- [ ] **Step 7: Commit**

```bash
git add server.py
git commit -m "$(cat <<'EOF'
feat(server): wire up Phase 1b tools — taxonomy + bulk export

Calls register_taxonomy_tools and register_export_tools at module
load alongside the existing four phase-1a register factories.
Taxonomy is shop-agnostic so it does not receive shop_id_getter.

After this change the FastMCP instance exposes all 23 tools across
phases 0/1a/1b: 2 auth + 2 shop + 10 listing (5 read + 5 write) +
4 receipt + 1 review + 1 taxonomy + 3 export.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Final verification

- [ ] **Step 1: Run the full suite**

```bash
cd "<project root>"
.venv/bin/pytest -v 2>&1 | tail -3
```

Expected: 95 passed (29 new in Phase 1b on top of 66 from Phase 0+1a).

- [ ] **Step 2: Verify all 23 tools register on the FastMCP instance**

```bash
ETSY_KEYSTRING=test_placeholder .venv/bin/python <<'PY'
import asyncio
import server

async def main():
    tools = await server.mcp.list_tools()
    names = sorted(t.name for t in tools)
    expected = sorted([
        # Phase 0
        "etsy_whoami", "etsy_token_status",
        # Phase 1a
        "etsy_get_shop", "etsy_get_shop_stats",
        "etsy_list_listings", "etsy_search_listings", "etsy_get_listing",
        "etsy_get_listing_inventory", "etsy_get_listing_images",
        "etsy_list_receipts", "etsy_get_receipt", "etsy_get_receipt_transactions",
        "etsy_list_shop_payments",
        "etsy_list_reviews",
        # Phase 1b
        "etsy_create_draft_listing", "etsy_update_listing", "etsy_delete_listing",
        "etsy_upload_listing_image", "etsy_update_listing_inventory",
        "etsy_taxonomy_search",
        "etsy_export_all_listings", "etsy_export_all_receipts", "etsy_export_all_reviews",
    ])
    print("registered:", names)
    print("expected:  ", expected)
    assert names == expected, f"missing: {set(expected) - set(names)}; extra: {set(names) - set(expected)}"
    print("OK — all 23 tools registered")

asyncio.run(main())
PY
```

Expected: `OK — all 23 tools registered`.

- [ ] **Step 3: Confirm no secrets staged or in history**

```bash
git status --ignored | grep -E "\.env$|\.tokens\.json|logs/" || true
git diff --staged
git log --all --full-history -- .env .tokens.json .storage_state.json
```

Expected: ignored files listed if present; no staged diff; no history of secrets. STOP if any leak appears.

- [ ] **Step 4: Confirm we're ready to push (do NOT push without explicit user OK)**

```bash
git log --oneline origin/main..HEAD
```

Expected: ~13 new commits (Tasks 1-12). Wait for the user to say "push" before running `git push origin main`.

- [ ] **Step 5: Phase 1b acceptance summary**

Phase 1b is complete when:
1. `pytest` is green (95 passing).
2. All 23 tools are registered on the FastMCP instance.
3. (Manual, post-Etsy-approval) `etsy_create_draft_listing` creates a draft visible at etsy.com/your/shops/me/tools/listings/draft.
4. (Manual, post-Etsy-approval) `etsy_upload_listing_image` adds an image to that draft.
5. (Manual, post-Etsy-approval) `etsy_export_all_listings(format='csv', output_dir='/tmp/etsy-test')` produces a populated CSV.

Items 1 + 2 are the bar for shipping the code. Items 3-5 unlock when the Etsy app is approved and the user runs the bootstrap.

---

## Spec coverage check (Phase 1b only)

| Spec § 5.1 requirement | Task |
|---|---|
| `etsy_create_draft_listing` | Task 3 |
| `etsy_update_listing` | Task 4 (PATCH per Etsy v3, not PUT as spec said) |
| `etsy_delete_listing` (with confirm guard) | Task 5 |
| `etsy_upload_listing_image` (multipart) | Task 6 |
| `etsy_update_listing_inventory` | Task 7 |
| `etsy_update_listing_images_order` | **DEFERRED — Etsy v3 lacks rank-only image-update endpoint. See "Scope deviation" at top of plan.** |
| `etsy_taxonomy_search` | Task 8 |
| `etsy_export_all_listings(format, output_dir)` | Task 9 |
| `etsy_export_all_receipts(format, output_dir, since)` | Task 10 |
| `etsy_export_all_reviews(format, output_dir)` | Task 11 |
| CSV columns dot-joined for nested fields | Task 9 (`_flatten_dict`) |
| Pagination via `limit=100` + `offset` | Task 1 (`paginate_all`) — used by Tasks 9, 10, 11 |
| Tools call existing `etsy_request` (no new HTTP impl) | Every task |
| EtsyMCPError → structured error dict | Every task |

**Out of scope (Phase 1c+):**
- Etsy Ads browser automation
- Listing image reordering (deferred)
- Bulk listing edits (Tier 2)
- Mark-shipped, refund, shipping profiles (Tier 2)
- Sales/coupons (Tier 3)
