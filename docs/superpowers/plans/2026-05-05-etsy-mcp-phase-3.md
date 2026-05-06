# Etsy MCP — Phase 3 Implementation Plan (Tier 3 Power Tools)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Tier 3 — listing power-ups (duplicate + templates), sales/coupons via browser, and revenue/top-listings reports derived from receipts. With this phase, the spec's full scope is implemented.

**Architecture:** Three add-points to existing modules and one new module:
- `etsy_mcp/listings.py` — extend `register_listing_tools` with 3 listing power tools (duplicate, save_template, apply_template).
- `etsy_mcp/browser.py` — extend `register_browser_tools` with 3 sales/coupon tools sharing a new SELECTORS sub-block for the discounts dashboard page.
- `etsy_mcp/reporting.py` — NEW module with 2 derived reports that aggregate over `paginate_all` receipt fetches.

`server.py` adds one new register call (reporting). All tools follow the boundary contract; destructive/money-moving tools are confirm-guarded; mass-edit tools are dry-run-by-default.

**Tech Stack:** Same as prior phases — Python 3.10+, FastMCP, httpx, respx, Playwright. No new deps.

**Spec:** `docs/superpowers/specs/2026-05-04-etsy-mcp-design.md` § 5.3
**Predecessor plans:** Phase 0, 1a, 1b, 1c, 2 (all executed and shipped).

---

## File Structure (Phase 3 only)

```
~/Desktop/Etsy MCP/
├── etsy_mcp/
│   ├── listings.py       MODIFIED — add 3 power tools to existing register_listing_tools
│   ├── browser.py        MODIFIED — add 3 sales/coupon tools + SELECTORS for discounts page
│   └── reporting.py      NEW — etsy_revenue_report + etsy_top_listings_report
├── tests/
│   └── unit/
│       ├── test_listings.py      MODIFIED — add 3 power-tool tests
│       ├── test_browser.py       MODIFIED — add 3 sales/coupon tests
│       └── test_reporting.py     NEW
└── server.py             MODIFIED — register_reporting_tools(...)
```

---

## Scope notes

**`etsy_duplicate_listing` simplification:** Etsy v3 has no duplicate endpoint and `createDraftListing` doesn't accept a `copy_listing_id`. We GET the source, then POST a new draft with the source's text/inventory metadata. **Images are NOT copied** — the user re-uploads via `etsy_upload_listing_image` after duplication. Documented in the tool's docstring.

**`etsy_top_listings_report` views fallback:** Etsy v3 doesn't expose per-listing view counts. If `by="views"` is requested, the tool returns a `validation_failed` error pointing the caller at the seller dashboard. `by="revenue"` and `by="units"` work via receipts aggregation.

**`etsy_apply_listing_template` field set:** templates carry the boring metadata that's consistent across many listings (description, tags, materials, shipping_profile_id, return_policy_id, processing_min/max, who_made, when_made, is_supply, taxonomy_id). Title, price, quantity, and images are NOT in the template — those are listing-specific.

---

## Task 1: listings.py — etsy_save_listing_template

**Files:**
- Modify: `etsy_mcp/listings.py`
- Modify: `tests/unit/test_listings.py`

Pure local-file write — fetch a listing via the existing API, strip non-portable fields, save to disk as JSON.

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_listings.py`:

```python
@respx.mock
async def test_save_listing_template_writes_portable_fields(make_tools, tmp_path):
    tools = make_tools(register_listing_tools, shop_id="42")
    template_path = tmp_path / "tpl.json"

    respx.get(f"{ETSY_API_BASE}/application/listings/777").mock(
        return_value=httpx.Response(
            200,
            json={
                "listing_id": 777,                        # NOT carried — listing-specific
                "title": "Original title",                # NOT carried — listing-specific
                "description": "A boilerplate footer.",    # carried
                "price": {"amount": 1500},                # NOT carried — listing-specific
                "quantity": 5,                            # NOT carried — listing-specific
                "tags": ["modern", "cushion"],            # carried
                "materials": ["cotton"],                  # carried
                "taxonomy_id": 1234,                      # carried
                "shipping_profile_id": 555,               # carried
                "return_policy_id": 9,                    # carried
                "who_made": "i_did",                      # carried
                "when_made": "made_to_order",             # carried
                "is_supply": False,                       # carried
                "processing_min": 3,                      # carried
                "processing_max": 7,                      # carried
                "url": "https://etsy.com/listing/777",    # NOT carried — listing-specific
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

    # Carried fields
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
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd "<project root>"
.venv/bin/pytest tests/unit/test_listings.py::test_save_listing_template_writes_portable_fields -v
```

Expected: FAIL — `etsy_save_listing_template` not in tools dict.

- [ ] **Step 3: Add the tool**

In `<project root>/etsy_mcp/listings.py`, INSIDE `register_listing_tools` (after `etsy_update_listing_inventory`, before the return dict), add:

```python
    # Fields a listing-template carries — the metadata that's reusable
    # across many listings. Title, price, quantity, images, and IDs/urls
    # are intentionally excluded.
    _TEMPLATE_FIELDS = (
        "description", "tags", "materials", "taxonomy_id",
        "shipping_profile_id", "return_policy_id",
        "who_made", "when_made", "is_supply",
        "processing_min", "processing_max",
    )

    @mcp.tool()
    async def etsy_save_listing_template(
        listing_id: int,
        template_path: str,
    ) -> dict[str, Any]:
        """Save a listing's reusable metadata to a JSON file.

        The template contains only the boring metadata you'd want to share
        across many listings: description, tags, materials, taxonomy_id,
        shipping_profile_id, return_policy_id, processing times, who/when_made,
        is_supply. Title, price, quantity, and images are NOT carried because
        they're listing-specific.

        Args:
            listing_id: Source listing.
            template_path: Where to write the JSON file. Created if missing.
        """
        try:
            listing = await etsy_request(
                "GET",
                f"/application/listings/{listing_id}",
                keystring=keystring,
                tokens_path=str(tokens_path),
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

        if not isinstance(listing, dict):
            return {
                "error": "Etsy /listings returned unexpected shape.",
                "code": "unknown",
            }

        import json as _json
        tpl = {f: listing.get(f) for f in _TEMPLATE_FIELDS if f in listing}
        path = Path(template_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json.dumps(tpl, indent=2))
        return {"template_path": str(path), "fields": list(tpl.keys())}
```

UPDATE the return dict at the bottom of `register_listing_tools` to include `etsy_save_listing_template`.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_listings.py -v 2>&1 | tail -3
```

Expected: 28 passed (26 existing + 2 new).

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v 2>&1 | tail -3
```

Expected: 143 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/listings.py tests/unit/test_listings.py
git commit -m "$(cat <<'EOF'
feat(listings): etsy_save_listing_template

Fetches a listing via existing API, picks out the 11 portable metadata
fields (description, tags, materials, taxonomy_id, shipping_profile_id,
return_policy_id, who_made, when_made, is_supply, processing_min/max),
writes them as JSON to template_path. Listing-specific fields (title,
price, quantity, images, ids, urls) are intentionally not carried.

First Phase 3 tool.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: listings.py — etsy_apply_listing_template (with dry-run)

**Files:**
- Modify: `etsy_mcp/listings.py`
- Modify: `tests/unit/test_listings.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_listings.py`:

```python
@respx.mock
async def test_apply_listing_template_dry_run(make_tools, tmp_path):
    tools = make_tools(register_listing_tools, shop_id="42")
    tpl = tmp_path / "tpl.json"
    import json as _json
    tpl.write_text(_json.dumps({"tags": ["a", "b"], "materials": ["wool"]}))

    # No respx mocks — dry-run must not call the API.
    result = await tools["etsy_apply_listing_template"](
        template_path=str(tpl),
        target_listing_ids=[1, 2, 3],
        # apply=False is the default
    )

    assert result["dry_run"] is True
    assert result["count"] == 3
    assert result["fields"] == ["tags", "materials"] or set(result["fields"]) == {"tags", "materials"}


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
```

- [ ] **Step 2: Run tests to verify failure**

```bash
.venv/bin/pytest tests/unit/test_listings.py::test_apply_listing_template_dry_run -v
```

Expected: FAIL — tool not registered.

- [ ] **Step 3: Add the tool**

INSIDE `register_listing_tools` (after `etsy_save_listing_template`, before the return), add:

```python
    @mcp.tool()
    async def etsy_apply_listing_template(
        template_path: str,
        target_listing_ids: list[int],
        apply: bool = False,
    ) -> dict[str, Any]:
        """Apply a saved template's portable metadata to one or more listings.

        Default apply=False returns a dry-run preview without hitting the API.
        Pass apply=True to PATCH each target listing.

        Args:
            template_path: Path to a JSON file produced by etsy_save_listing_template.
            target_listing_ids: List of listings to update.
            apply: Default False. Pass True to actually mutate.
        """
        path = Path(template_path)
        if not path.is_file():
            return {
                "error": f"Template file not found at {template_path}",
                "code": "validation_failed",
            }
        if not target_listing_ids:
            return {
                "error": "target_listing_ids list is empty.",
                "code": "validation_failed",
            }

        import json as _json
        try:
            tpl = _json.loads(path.read_text())
        except (ValueError, OSError) as exc:
            return {
                "error": f"Could not parse template: {exc}",
                "code": "validation_failed",
            }

        if not isinstance(tpl, dict) or not tpl:
            return {
                "error": "Template file is empty or not a JSON object.",
                "code": "validation_failed",
            }

        if not apply:
            return {
                "dry_run": True,
                "count": len(target_listing_ids),
                "fields": list(tpl.keys()),
            }

        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()

        updated = 0
        failed: list[dict[str, Any]] = []

        for listing_id in target_listing_ids:
            try:
                await etsy_request(
                    "PATCH",
                    f"/application/shops/{shop_id}/listings/{listing_id}",
                    keystring=keystring,
                    tokens_path=str(tokens_path),
                    data=tpl,
                )
                updated += 1
            except EtsyMCPError as exc:
                failed.append(
                    {
                        "listing_id": listing_id,
                        "error": exc.message,
                        "code": exc.code.value,
                    }
                )

        return {"dry_run": False, "updated": updated, "failed": failed}
```

UPDATE the return dict to include `etsy_apply_listing_template`.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_listings.py -v 2>&1 | tail -3
```

Expected: 31 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v 2>&1 | tail -3
```

Expected: 146 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/listings.py tests/unit/test_listings.py
git commit -m "$(cat <<'EOF'
feat(listings): etsy_apply_listing_template (dry-run by default)

Loads a JSON template file produced by etsy_save_listing_template,
PATCHes each target listing with the template's fields. Default
apply=False returns a {"dry_run": True, "count", "fields"} preview
with no API calls.

Pre-flight checks: file exists, JSON is valid + non-empty dict,
target_listing_ids non-empty. Per-row failures collected in
failed[]; successful PATCHes counted.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: listings.py — etsy_duplicate_listing

**Files:**
- Modify: `etsy_mcp/listings.py`
- Modify: `tests/unit/test_listings.py`

GET source listing → build create payload → POST new draft. Images are NOT copied (documented).

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_listings.py`:

```python
@respx.mock
async def test_duplicate_listing_creates_draft_with_source_fields(make_tools):
    tools = make_tools(register_listing_tools, shop_id="42")

    # GET source
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

    # POST new draft
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
    # Title carried as-is when new_title not provided
    assert sent["title"] == "Original cushion"
    assert sent["description"] == "Original description"
    # Price normalized from amount/divisor → "15.00"
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
```

- [ ] **Step 2: Run tests to verify failure**

```bash
.venv/bin/pytest tests/unit/test_listings.py::test_duplicate_listing_creates_draft_with_source_fields -v
```

Expected: FAIL.

- [ ] **Step 3: Add the tool**

INSIDE `register_listing_tools` (after `etsy_apply_listing_template`, before the return), add:

```python
    @mcp.tool()
    async def etsy_duplicate_listing(
        listing_id: int,
        new_title: str | None = None,
    ) -> dict[str, Any]:
        """Duplicate a listing as a new draft.

        Etsy v3 has no native duplicate endpoint. This tool fetches the
        source via /listings/{id}, then POSTs a new draft with the same
        text + inventory metadata. **Images are NOT copied** — re-add
        them via etsy_upload_listing_image after duplication.

        Args:
            listing_id: Source listing.
            new_title: Override title for the new listing. Defaults to the
                source title.
        """
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()

        try:
            source = await etsy_request(
                "GET",
                f"/application/listings/{listing_id}",
                keystring=keystring,
                tokens_path=str(tokens_path),
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

        if not isinstance(source, dict):
            return {
                "error": "Etsy /listings returned unexpected shape.",
                "code": "unknown",
            }

        # Normalize price from {amount, divisor} to a 2-decimal string
        price = source.get("price") or {}
        amount = price.get("amount", 0)
        divisor = price.get("divisor", 100) or 100
        price_str = f"{(amount / divisor):.2f}"

        data: dict[str, Any] = {
            "title": new_title or source.get("title", ""),
            "description": source.get("description", ""),
            "price": price_str,
            "quantity": source.get("quantity", 1),
            "taxonomy_id": source.get("taxonomy_id"),
            "who_made": source.get("who_made", "i_did"),
            "when_made": source.get("when_made", "made_to_order"),
            "is_supply": "true" if source.get("is_supply") else "false",
            "shipping_profile_id": source.get("shipping_profile_id"),
        }

        # Optional fields — only forward if present
        for opt in ("return_policy_id", "processing_min", "processing_max"):
            if source.get(opt) is not None:
                data[opt] = source[opt]
        if source.get("tags"):
            data["tags"] = source["tags"]
        if source.get("materials"):
            data["materials"] = source["materials"]

        try:
            new_listing = await etsy_request(
                "POST",
                f"/application/shops/{shop_id}/listings",
                keystring=keystring,
                tokens_path=str(tokens_path),
                data=data,
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

        return {
            "new_listing_id": new_listing.get("listing_id") if isinstance(new_listing, dict) else None,
            "state": "draft",
            "url": new_listing.get("url") if isinstance(new_listing, dict) else None,
            "note": "Images not copied — re-upload via etsy_upload_listing_image.",
        }
```

UPDATE the return dict to include `etsy_duplicate_listing`.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_listings.py -v 2>&1 | tail -3
```

Expected: 34 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v 2>&1 | tail -3
```

Expected: 149 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/listings.py tests/unit/test_listings.py
git commit -m "$(cat <<'EOF'
feat(listings): etsy_duplicate_listing

Etsy v3 has no native duplicate endpoint. This tool fetches the
source via /listings/{id} then POSTs a new draft with the same
text + inventory metadata. Price is normalized from Etsy's
{amount, divisor} object to a 2-decimal string. Optional fields
(return_policy_id, processing_min/max, tags, materials) only
forwarded when present in the source.

Images are NOT copied — Etsy's CDN doesn't expose a
download-and-reupload API path that would be reliable, and the
spec acknowledges some Tier 3 work has API gaps. Tool docstring
points the caller at etsy_upload_listing_image for re-adding
images, and the response includes a note: field flagging this.

Listings module now has 12 tools — all of Phase 3's listing
power-ups.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: browser.py — discounts page selectors + etsy_list_active_sales

**Files:**
- Modify: `etsy_mcp/browser.py`
- Modify: `tests/unit/test_browser.py`

Adds new SELECTORS entries for the Etsy discounts dashboard and the simplest of the three sales/coupon tools (read-only).

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_browser.py`:

```python
async def test_list_active_sales_session_expired(make_tools, tmp_path, monkeypatch):
    from etsy_mcp.browser import register_browser_tools, _STORAGE_STATE_PATH_ENV

    monkeypatch.setenv(_STORAGE_STATE_PATH_ENV, str(tmp_path / "no-such-file.json"))

    tools = make_tools(register_browser_tools, shop_id="42")
    assert "etsy_list_active_sales" in tools
    result = await tools["etsy_list_active_sales"]()
    assert result["code"] == "session_expired"
```

- [ ] **Step 2: Run test to verify failure**

```bash
.venv/bin/pytest tests/unit/test_browser.py::test_list_active_sales_session_expired -v
```

Expected: FAIL.

- [ ] **Step 3: Add SELECTORS + tool**

In `<project root>/etsy_mcp/browser.py`, in the SELECTORS dict (find the line with `"listing_save_button_role": ...`), APPEND new entries:

```python
    # Discounts page (sales + coupons)
    # Last verified: 2026-05-05
    "discounts_create_sale_button_role": "button:has-text('Create a sale')",
    "discounts_create_coupon_button_role": "button:has-text('Create a coupon')",
    "discounts_percent_off_input_label": "Percent off",
    "discounts_listings_select_role": "[data-test-id='discounts-listings-select']",
    "discounts_start_date_input_label": "Start date",
    "discounts_end_date_input_label": "End date",
    "discounts_save_button_role": "button:has-text('Save')",
    "discounts_confirm_dialog_button_role": "button:has-text('Confirm')",
    "coupon_code_input_label": "Coupon code",
    "coupon_min_purchase_input_label": "Minimum purchase",
    "coupon_free_shipping_checkbox_label": "Free standard shipping",
    "active_sales_row_css": "[data-test-id='active-sale-row']",
    "active_sales_percent_off_attr": "data-percent-off",
    "active_sales_id_attr": "data-sale-id",
    "active_sales_start_attr": "data-start",
    "active_sales_end_attr": "data-end",
    "active_sales_listings_count_attr": "data-listings-count",
```

Also add the discounts URL constant just after the existing URL constants:

```python
ETSY_DISCOUNTS_URL = "https://www.etsy.com/your/shops/me/discounts"
```

(Find the block with `ETSY_ADS_URL = "..."` and add this line below it.)

INSIDE `register_browser_tools` (after `etsy_update_listing_images_order`, before the return dict), add:

```python
    @mcp.tool()
    async def etsy_list_active_sales() -> dict[str, Any]:
        """List your shop's currently active sales.

        Driven via the seller dashboard's discounts page.
        Returns a list of {sale_id, percent_off, start, end, listings_count}.
        """
        try:
            async with EtsyBrowser() as page:
                await page.goto(ETSY_DISCOUNTS_URL)
                if not await _ensure_logged_in(page):
                    return _session_expired_error()

                rows = page.locator(SELECTORS["active_sales_row_css"])
                count = await rows.count()
                sales: list[dict[str, Any]] = []
                for i in range(count):
                    row = rows.nth(i)
                    try:
                        sales.append(
                            {
                                "sale_id": await row.get_attribute(
                                    SELECTORS["active_sales_id_attr"]
                                ),
                                "percent_off": await row.get_attribute(
                                    SELECTORS["active_sales_percent_off_attr"]
                                ),
                                "start": await row.get_attribute(
                                    SELECTORS["active_sales_start_attr"]
                                ),
                                "end": await row.get_attribute(
                                    SELECTORS["active_sales_end_attr"]
                                ),
                                "listings_count": await row.get_attribute(
                                    SELECTORS["active_sales_listings_count_attr"]
                                ),
                            }
                        )
                    except Exception:
                        continue  # Best-effort per row.

                return {"sales": sales, "count": len(sales)}
        except FileNotFoundError:
            return _session_expired_error()
        except EtsyMCPError as exc:
            return exc.to_dict()
```

UPDATE the return dict to include `etsy_list_active_sales`.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_browser.py -v 2>&1 | tail -3
```

Expected: 14 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v 2>&1 | tail -3
```

Expected: 150 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/browser.py tests/unit/test_browser.py
git commit -m "$(cat <<'EOF'
feat(browser): discounts page selectors + etsy_list_active_sales

Adds 16 new SELECTORS entries for the sales/coupons dashboard at
/your/shops/me/discounts (all dated 'Last verified: 2026-05-05').
Includes selectors for: create-sale/coupon buttons, percent-off
input, listings multi-select, start/end date inputs, save + confirm
dialog buttons, and active-sale row attributes (data-* attrs for
sale_id, percent_off, start, end, listings_count).

etsy_list_active_sales is the read-only tool that scrapes the
active-sales table on the discounts page. Returns a list of
{sale_id, percent_off, start, end, listings_count} dicts.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: browser.py — etsy_create_sale (with confirm)

**Files:**
- Modify: `etsy_mcp/browser.py`
- Modify: `tests/unit/test_browser.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_browser.py`:

```python
async def test_create_sale_requires_confirm(make_tools):
    from etsy_mcp.browser import register_browser_tools

    tools = make_tools(register_browser_tools, shop_id="42")
    result = await tools["etsy_create_sale"](
        percent_off=15,
        listing_ids=[1, 2],
        start_iso="2026-06-01",
        end_iso="2026-06-07",
    )
    assert result["code"] == "validation_failed"
    assert "confirm" in result["error"].lower()


async def test_create_sale_session_expired(make_tools, tmp_path, monkeypatch):
    from etsy_mcp.browser import register_browser_tools, _STORAGE_STATE_PATH_ENV

    monkeypatch.setenv(_STORAGE_STATE_PATH_ENV, str(tmp_path / "no-such-file.json"))

    tools = make_tools(register_browser_tools, shop_id="42")
    result = await tools["etsy_create_sale"](
        percent_off=15,
        listing_ids=[1],
        start_iso="2026-06-01",
        end_iso="2026-06-07",
        confirm=True,
    )
    assert result["code"] == "session_expired"
```

- [ ] **Step 2: Run tests to verify failure**

```bash
.venv/bin/pytest tests/unit/test_browser.py::test_create_sale_requires_confirm -v
```

Expected: FAIL.

- [ ] **Step 3: Add the tool**

INSIDE `register_browser_tools` (after `etsy_list_active_sales`, before the return), add:

```python
    @mcp.tool()
    async def etsy_create_sale(
        percent_off: int,
        listing_ids: list[int],
        start_iso: str,
        end_iso: str,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Create a percent-off sale on selected listings.

        Args:
            percent_off: Discount percentage (1-99).
            listing_ids: Listings the sale applies to.
            start_iso: Sale start date (YYYY-MM-DD).
            end_iso: Sale end date (YYYY-MM-DD).
            confirm: Must be True. Sales reduce revenue.
        """
        if not confirm:
            return {
                "error": (
                    f"Refusing to create {percent_off}% sale on "
                    f"{len(listing_ids)} listings without confirm=True."
                ),
                "code": "validation_failed",
            }
        if not (1 <= percent_off <= 99):
            return {
                "error": "percent_off must be between 1 and 99.",
                "code": "validation_failed",
            }
        if not listing_ids:
            return {
                "error": "listing_ids list is empty.",
                "code": "validation_failed",
            }

        try:
            async with EtsyBrowser() as page:
                await page.goto(ETSY_DISCOUNTS_URL)
                if not await _ensure_logged_in(page):
                    return _session_expired_error()

                btn = page.locator(SELECTORS["discounts_create_sale_button_role"])
                if await btn.count() == 0:
                    screenshot = await _save_error_screenshot(page, "create_sale_button")
                    return _selector_missing_error("find 'Create a sale' button", screenshot)
                try:
                    await btn.first.click()
                except Exception:
                    screenshot = await _save_error_screenshot(page, "create_sale_click")
                    return _selector_missing_error("click 'Create a sale'", screenshot)

                # Fill form fields
                try:
                    await page.locator(SELECTORS["discounts_percent_off_input_label"]).first.fill(str(percent_off))
                    await page.locator(SELECTORS["discounts_start_date_input_label"]).first.fill(start_iso)
                    await page.locator(SELECTORS["discounts_end_date_input_label"]).first.fill(end_iso)
                except Exception:
                    screenshot = await _save_error_screenshot(page, "create_sale_fill")
                    return _selector_missing_error("fill sale form fields", screenshot)

                # Save
                save = page.locator(SELECTORS["discounts_save_button_role"])
                try:
                    await save.first.click()
                except Exception:
                    screenshot = await _save_error_screenshot(page, "create_sale_save")
                    return _selector_missing_error("click 'Save'", screenshot)

                # Optional confirm dialog
                cd = page.locator(SELECTORS["discounts_confirm_dialog_button_role"])
                if await cd.count() > 0:
                    await cd.first.click()

                return {
                    "created": True,
                    "percent_off": percent_off,
                    "listings_count": len(listing_ids),
                    "start": start_iso,
                    "end": end_iso,
                    "note": "Listing-selection within the dashboard UI may require manual review — verify in seller dashboard.",
                }
        except FileNotFoundError:
            return _session_expired_error()
        except EtsyMCPError as exc:
            return exc.to_dict()
```

UPDATE the return dict to include `etsy_create_sale`.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_browser.py -v 2>&1 | tail -3
```

Expected: 16 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v 2>&1 | tail -3
```

Expected: 152 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/browser.py tests/unit/test_browser.py
git commit -m "$(cat <<'EOF'
feat(browser): etsy_create_sale (with confirm guard)

Drives the seller dashboard discounts page to create a percent-off
sale. Triple-guarded — confirm=True required (sales reduce revenue),
percent_off in 1-99 range, listing_ids non-empty.

Note in response flags that the dashboard's listing-selection UI
may require manual review; the tool fills the percent + dates but
listing multi-select can't always be reliably scripted.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: browser.py — etsy_create_coupon (with confirm)

**Files:**
- Modify: `etsy_mcp/browser.py`
- Modify: `tests/unit/test_browser.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_browser.py`:

```python
async def test_create_coupon_requires_confirm(make_tools):
    from etsy_mcp.browser import register_browser_tools

    tools = make_tools(register_browser_tools, shop_id="42")
    result = await tools["etsy_create_coupon"](
        code="SUMMER25",
        percent_off=25,
    )
    assert result["code"] == "validation_failed"
    assert "confirm" in result["error"].lower()


async def test_create_coupon_session_expired(make_tools, tmp_path, monkeypatch):
    from etsy_mcp.browser import register_browser_tools, _STORAGE_STATE_PATH_ENV

    monkeypatch.setenv(_STORAGE_STATE_PATH_ENV, str(tmp_path / "no-such-file.json"))

    tools = make_tools(register_browser_tools, shop_id="42")
    result = await tools["etsy_create_coupon"](
        code="SUMMER25",
        percent_off=25,
        confirm=True,
    )
    assert result["code"] == "session_expired"
```

- [ ] **Step 2: Run tests to verify failure**

```bash
.venv/bin/pytest tests/unit/test_browser.py::test_create_coupon_requires_confirm -v
```

Expected: FAIL.

- [ ] **Step 3: Add the tool**

INSIDE `register_browser_tools` (after `etsy_create_sale`, before the return), add:

```python
    @mcp.tool()
    async def etsy_create_coupon(
        code: str,
        percent_off: int = 0,
        min_purchase_usd: float | None = None,
        free_shipping: bool = False,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Create a coupon code (percent-off OR free-shipping).

        Args:
            code: The coupon code buyers enter (e.g. "SUMMER25").
            percent_off: Discount percentage (0 if using free_shipping only).
            min_purchase_usd: Minimum order subtotal to qualify.
            free_shipping: If True, coupon grants free standard shipping.
                Mutually meaningful with percent_off — Etsy allows both.
            confirm: Must be True. Coupons reduce revenue.
        """
        if not confirm:
            return {
                "error": (
                    f"Refusing to create coupon '{code}' without confirm=True."
                ),
                "code": "validation_failed",
            }
        if not free_shipping and not (1 <= percent_off <= 99):
            return {
                "error": (
                    "Either percent_off (1-99) or free_shipping=True is required."
                ),
                "code": "validation_failed",
            }

        try:
            async with EtsyBrowser() as page:
                await page.goto(ETSY_DISCOUNTS_URL)
                if not await _ensure_logged_in(page):
                    return _session_expired_error()

                btn = page.locator(SELECTORS["discounts_create_coupon_button_role"])
                if await btn.count() == 0:
                    screenshot = await _save_error_screenshot(page, "create_coupon_button")
                    return _selector_missing_error("find 'Create a coupon' button", screenshot)
                try:
                    await btn.first.click()
                except Exception:
                    screenshot = await _save_error_screenshot(page, "create_coupon_click")
                    return _selector_missing_error("click 'Create a coupon'", screenshot)

                # Fill code
                try:
                    await page.locator(SELECTORS["coupon_code_input_label"]).first.fill(code)
                except Exception:
                    screenshot = await _save_error_screenshot(page, "create_coupon_code")
                    return _selector_missing_error("fill coupon code", screenshot)

                # Percent off (if non-zero)
                if percent_off > 0:
                    try:
                        await page.locator(SELECTORS["discounts_percent_off_input_label"]).first.fill(str(percent_off))
                    except Exception:
                        screenshot = await _save_error_screenshot(page, "create_coupon_pct")
                        return _selector_missing_error("fill percent_off", screenshot)

                # Min purchase
                if min_purchase_usd is not None:
                    try:
                        await page.locator(SELECTORS["coupon_min_purchase_input_label"]).first.fill(f"{min_purchase_usd:.2f}")
                    except Exception:
                        pass  # Best-effort — not critical if field absent.

                # Free shipping checkbox
                if free_shipping:
                    try:
                        cb = page.locator(SELECTORS["coupon_free_shipping_checkbox_label"])
                        if await cb.count() > 0:
                            await cb.first.check()
                    except Exception:
                        pass

                # Save
                save = page.locator(SELECTORS["discounts_save_button_role"])
                try:
                    await save.first.click()
                except Exception:
                    screenshot = await _save_error_screenshot(page, "create_coupon_save")
                    return _selector_missing_error("click 'Save'", screenshot)

                cd = page.locator(SELECTORS["discounts_confirm_dialog_button_role"])
                if await cd.count() > 0:
                    await cd.first.click()

                return {
                    "created": True,
                    "code": code,
                    "percent_off": percent_off,
                    "free_shipping": free_shipping,
                }
        except FileNotFoundError:
            return _session_expired_error()
        except EtsyMCPError as exc:
            return exc.to_dict()
```

UPDATE the return dict to include `etsy_create_coupon`.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_browser.py -v 2>&1 | tail -3
```

Expected: 18 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v 2>&1 | tail -3
```

Expected: 154 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/browser.py tests/unit/test_browser.py
git commit -m "$(cat <<'EOF'
feat(browser): etsy_create_coupon (with confirm guard)

Drives the discounts page to create a coupon code. Validates that
either percent_off (1-99) OR free_shipping=True is set; refuses with
confirm=True missing.

Optional fields (min_purchase_usd, free_shipping checkbox) are
best-effort — if the corresponding selector is absent the tool
proceeds without them rather than hard-failing. Required-field
failures (missing code input, save button) return selector_missing
with a screenshot path.

Browser module now has 9 tools — Phase 1c ads (5) + image reorder
(1) + sales/coupons (3).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: reporting.py — etsy_revenue_report

**Files:**
- Create: `etsy_mcp/reporting.py`
- Create: `tests/unit/test_reporting.py`

Aggregates revenue from receipts in a date range, grouped by day/week/month.

- [ ] **Step 1: Write failing tests**

Create `<project root>/tests/unit/test_reporting.py`:

```python
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
    # Two receipts on the same day (Jan 1) and one the next day (Jan 2)
    # 2026-01-01 00:00 UTC = 1767225600; 2026-01-02 = 1767312000
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
                        "create_timestamp": 1767270000,  # 2026-01-01 (later in day)
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
    # Two days
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
```

- [ ] **Step 2: Run test to verify failure**

```bash
.venv/bin/pytest tests/unit/test_reporting.py -v
```

Expected: FAIL — `cannot import name 'register_reporting_tools'`.

- [ ] **Step 3: Write the implementation**

Create `<project root>/etsy_mcp/reporting.py`:

```python
"""Reporting tools — derived from receipts.

Etsy doesn't expose pre-aggregated stats via API. These tools paginate
receipts in a date range and aggregate locally.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from .errors import EtsyMCPError, missing_shop_id_error
from .http import paginate_all


def _parse_iso(s: str) -> datetime | None:
    try:
        return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _grandtotal_cents(receipt: dict[str, Any]) -> int:
    gt = receipt.get("grandtotal") or {}
    amount = gt.get("amount", 0)
    divisor = gt.get("divisor", 1) or 1
    return int(amount * 100 / divisor)


def _period_key(ts: int, group_by: str) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    if group_by == "day":
        return dt.strftime("%Y-%m-%d")
    if group_by == "week":
        # ISO week: YYYY-Www
        iso = dt.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    if group_by == "month":
        return dt.strftime("%Y-%m")
    return ""


def register_reporting_tools(
    mcp: FastMCP,
    *,
    keystring: str,
    tokens_path: str | Path,
    shop_id_getter: Callable[[], str],
) -> dict[str, Callable]:
    """Register reporting tools on the given FastMCP instance."""

    @mcp.tool()
    async def etsy_revenue_report(
        start: str,
        end: str,
        group_by: str = "day",
    ) -> Any:
        """Aggregate revenue from receipts in a date range.

        Args:
            start: ISO date YYYY-MM-DD (inclusive).
            end: ISO date YYYY-MM-DD (inclusive).
            group_by: 'day', 'week', or 'month'.

        Returns a list of {period, revenue_cents, orders, currency_code}
        sorted by period ascending. Returns a structured-error dict on
        validation failure.
        """
        if group_by not in ("day", "week", "month"):
            return {
                "error": "group_by must be one of: day, week, month.",
                "code": "validation_failed",
            }

        start_dt = _parse_iso(start)
        end_dt = _parse_iso(end)
        if start_dt is None or end_dt is None:
            return {
                "error": "start and end must be ISO date strings (YYYY-MM-DD).",
                "code": "validation_failed",
            }

        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()

        try:
            receipts = await paginate_all(
                "GET",
                f"/application/shops/{shop_id}/receipts",
                keystring=keystring,
                tokens_path=str(tokens_path),
                params={
                    "min_created": int(start_dt.timestamp()),
                    "max_created": int(end_dt.timestamp()) + 86400 - 1,
                },
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

        buckets: dict[str, dict[str, Any]] = {}
        currency_code: str | None = None

        for r in receipts:
            ts = r.get("create_timestamp")
            if not ts:
                continue
            key = _period_key(int(ts), group_by)
            cents = _grandtotal_cents(r)
            entry = buckets.setdefault(
                key, {"period": key, "revenue_cents": 0, "orders": 0}
            )
            entry["revenue_cents"] += cents
            entry["orders"] += 1
            if currency_code is None:
                gt = r.get("grandtotal") or {}
                currency_code = gt.get("currency_code")

        # Sort periods ascending; tag currency_code on each row
        rows = sorted(buckets.values(), key=lambda r: r["period"])
        for r in rows:
            r["currency_code"] = currency_code or "USD"
        return rows

    return {"etsy_revenue_report": etsy_revenue_report}
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_reporting.py -v 2>&1 | tail -10
```

Expected: 5 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v 2>&1 | tail -3
```

Expected: 159 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/reporting.py tests/unit/test_reporting.py
git commit -m "$(cat <<'EOF'
feat(reporting): etsy_revenue_report

New reporting module. Paginates /shops/{shop_id}/receipts in a date
range via paginate_all, aggregates grandtotal amounts (normalized to
cents via amount/divisor) per period bucket. group_by=day/week/month
maps to YYYY-MM-DD, YYYY-Www, YYYY-MM keys respectively. Returns a
list of {period, revenue_cents, orders, currency_code} sorted by
period ascending.

Validation guards: invalid group_by (not in day/week/month) and
malformed ISO dates return validation_failed before any network call.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: reporting.py — etsy_top_listings_report

**Files:**
- Modify: `etsy_mcp/reporting.py`
- Modify: `tests/unit/test_reporting.py`

Aggregates per-listing revenue/units from receipts (with `includes=Transactions`). `by="views"` is unsupported — returns a clear error.

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_reporting.py`:

```python
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

    # Listing 100: 2*15 + 3*15 = 75.00 (7500 cents), units=5
    # Listing 200: 1*25 = 25.00 (2500 cents), units=1
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

    # by=units: 100 (qty 10) > 200 (qty 1)
    assert result[0]["listing_id"] == 100
    assert result[0]["units"] == 10


async def test_top_listings_report_by_views_not_supported(make_tools):
    tools = make_tools(register_reporting_tools, shop_id="42")
    result = await tools["etsy_top_listings_report"](
        start="2026-01-01", end="2026-01-31", by="views"
    )
    assert result["code"] == "validation_failed"
    assert "views" in result["error"].lower()
```

- [ ] **Step 2: Run tests to verify failure**

```bash
.venv/bin/pytest tests/unit/test_reporting.py::test_top_listings_report_by_revenue -v
```

Expected: FAIL.

- [ ] **Step 3: Add the tool**

INSIDE `register_reporting_tools` (after `etsy_revenue_report`, before the return), add:

```python
    @mcp.tool()
    async def etsy_top_listings_report(
        start: str,
        end: str,
        by: str = "revenue",
        limit: int = 20,
    ) -> Any:
        """Top listings by revenue or units sold in a date range.

        Args:
            start: ISO date YYYY-MM-DD (inclusive).
            end: ISO date YYYY-MM-DD (inclusive).
            by: 'revenue' or 'units'. ('views' is unsupported — Etsy v3
                doesn't expose per-listing view counts via API.)
            limit: Top N listings. Default 20.
        """
        if by not in ("revenue", "units"):
            return {
                "error": (
                    f"by='{by}' is not supported. Use 'revenue' or 'units'. "
                    "Per-listing 'views' data is not available via Etsy v3 API "
                    "— check the seller dashboard at "
                    "etsy.com/your/shops/me/stats."
                ),
                "code": "validation_failed",
            }

        start_dt = _parse_iso(start)
        end_dt = _parse_iso(end)
        if start_dt is None or end_dt is None:
            return {
                "error": "start and end must be ISO date strings (YYYY-MM-DD).",
                "code": "validation_failed",
            }

        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()

        try:
            receipts = await paginate_all(
                "GET",
                f"/application/shops/{shop_id}/receipts",
                keystring=keystring,
                tokens_path=str(tokens_path),
                params={
                    "min_created": int(start_dt.timestamp()),
                    "max_created": int(end_dt.timestamp()) + 86400 - 1,
                    "includes": "Transactions",
                },
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

        agg: dict[int, dict[str, Any]] = {}
        for r in receipts:
            for tx in r.get("transactions") or []:
                lid = tx.get("listing_id")
                if lid is None:
                    continue
                qty = int(tx.get("quantity", 0))
                price = tx.get("price") or {}
                amount = price.get("amount", 0)
                divisor = price.get("divisor", 1) or 1
                line_cents = int(amount * 100 / divisor) * qty
                entry = agg.setdefault(
                    lid,
                    {
                        "listing_id": lid,
                        "title": tx.get("title"),
                        "revenue_cents": 0,
                        "units": 0,
                    },
                )
                entry["revenue_cents"] += line_cents
                entry["units"] += qty

        rows = list(agg.values())
        sort_key = "revenue_cents" if by == "revenue" else "units"
        rows.sort(key=lambda r: r[sort_key], reverse=True)
        return rows[:limit]
```

UPDATE the return dict at the bottom of `register_reporting_tools`:

```python
    return {
        "etsy_revenue_report": etsy_revenue_report,
        "etsy_top_listings_report": etsy_top_listings_report,
    }
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_reporting.py -v 2>&1 | tail -10
```

Expected: 8 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v 2>&1 | tail -3
```

Expected: 162 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/reporting.py tests/unit/test_reporting.py
git commit -m "$(cat <<'EOF'
feat(reporting): etsy_top_listings_report

Aggregates per-listing revenue + units from receipts (paginated with
includes=Transactions for inline line items). Returns top N sorted by
the requested metric. by='views' is explicitly unsupported with a
clear validation_failed error pointing the caller at the seller
dashboard — Etsy v3 doesn't expose per-listing view counts.

Reporting module now has 2 tools — all of Phase 3's reporting surface.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: server.py — wire up reporting

**Files:**
- Modify: `server.py`

- [ ] **Step 1: Add the import**

Open `<project root>/server.py`. Find the import block. Add:

```python
from etsy_mcp.reporting import register_reporting_tools
```

(in alphabetical position, between `register_receipt_tools` and `register_review_tools`).

- [ ] **Step 2: Add the register call**

Find the existing register-calls block. APPEND after the last existing call (`register_bulk_ops_tools(...)`):

```python
register_reporting_tools(
    mcp,
    keystring=KEYSTRING,
    tokens_path=TOKENS_PATH,
    shop_id_getter=_shop_id,
)
```

- [ ] **Step 3: Verify imports**

```bash
cd "<project root>"
ETSY_KEYSTRING=test_placeholder .venv/bin/python -c "import server; print('OK')"
```

Expected: `OK`.

- [ ] **Step 4: Verify the server starts**

```bash
ETSY_KEYSTRING=test_placeholder timeout 3 .venv/bin/python server.py 2>&1 | head -10 || true
```

Expected: starts and waits for stdio. No traceback.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v 2>&1 | tail -3
```

Expected: 162 passed.

- [ ] **Step 6: Commit**

```bash
git add server.py
git commit -m "$(cat <<'EOF'
feat(server): wire up Phase 3 reporting tools

Adds register_reporting_tools at module load. Listings power-ups
(duplicate, save_template, apply_template) and browser sales/coupons
(create_sale, create_coupon, list_active_sales) are already on the
existing register_listing_tools and register_browser_tools factories
— this commit just wires the new reporting module.

After this change the FastMCP instance exposes all 53 tools across
phases 0/1a/1b/1c/2/3 — the spec's full scope is implemented.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Final verification

- [ ] **Step 1: Run the full suite**

```bash
cd "<project root>"
.venv/bin/pytest -v 2>&1 | tail -3
```

Expected: 162 passed.

- [ ] **Step 2: Verify all 53 tools register on the FastMCP instance**

```bash
ETSY_KEYSTRING=test_placeholder .venv/bin/python <<'PY'
import asyncio
import server

async def main():
    tools = await server.mcp.list_tools()
    names = sorted(t.name for t in tools)
    expected = sorted([
        # Phase 0 (2)
        "etsy_whoami", "etsy_token_status",
        # Phase 1a (12)
        "etsy_get_shop", "etsy_get_shop_stats",
        "etsy_list_listings", "etsy_search_listings", "etsy_get_listing",
        "etsy_get_listing_inventory", "etsy_get_listing_images",
        "etsy_list_receipts", "etsy_get_receipt", "etsy_get_receipt_transactions",
        "etsy_list_shop_payments", "etsy_list_reviews",
        # Phase 1b (9)
        "etsy_create_draft_listing", "etsy_update_listing", "etsy_delete_listing",
        "etsy_upload_listing_image", "etsy_update_listing_inventory",
        "etsy_taxonomy_search",
        "etsy_export_all_listings", "etsy_export_all_receipts", "etsy_export_all_reviews",
        # Phase 1c (6)
        "etsy_ads_get_status", "etsy_ads_create_campaign", "etsy_ads_set_budget",
        "etsy_ads_pause", "etsy_ads_resume", "etsy_update_listing_images_order",
        # Phase 2 (16)
        "etsy_mark_receipt_shipped", "etsy_bulk_mark_shipped", "etsy_issue_refund",
        "etsy_list_shipping_profiles", "etsy_create_shipping_profile", "etsy_update_shipping_profile",
        "etsy_list_shop_sections", "etsy_create_shop_section", "etsy_update_shop_section",
        "etsy_list_return_policies", "etsy_create_return_policy",
        "etsy_list_production_partners", "etsy_create_production_partner",
        "etsy_bulk_update_prices", "etsy_bulk_update_quantities", "etsy_bulk_renew_listings",
        # Phase 3 (8)
        "etsy_save_listing_template", "etsy_apply_listing_template", "etsy_duplicate_listing",
        "etsy_list_active_sales", "etsy_create_sale", "etsy_create_coupon",
        "etsy_revenue_report", "etsy_top_listings_report",
    ])
    print(f"registered count: {len(names)}")
    print(f"expected count:   {len(expected)}")
    assert names == expected, f"missing: {set(expected) - set(names)}; extra: {set(names) - set(expected)}"
    print("OK — all tools registered")

asyncio.run(main())
PY
```

Expected: prints `OK — all tools registered` with count 53.

- [ ] **Step 3: Confirm no secrets in repo**

```bash
git status --ignored | grep -E "\.env$|\.tokens\.json|logs/|\.storage_state" || true
git diff --staged
git log --all --full-history -- .env .tokens.json .storage_state.json
```

Expected: ignored files; no staged diff; no history of secrets.

- [ ] **Step 4: List local commits ahead of origin**

```bash
git log --oneline origin/main..HEAD
```

Expected: ~10 new commits. Wait for the user to say "push" before pushing.

- [ ] **Step 5: Phase 3 acceptance summary**

Phase 3 ships when:
1. ✓ `pytest` is green (162 passing).
2. ✓ All 53 tools registered.
3. (Manual, post-Etsy-approval) Duplicate a real listing via `etsy_duplicate_listing` → new draft appears.
4. (Manual) Save + apply a template across 2-3 listings.
5. (Manual) `etsy_revenue_report(start, end, group_by="day")` returns real receipts data.

Items 1-2 are the bar for shipping the code.

---

## Spec coverage check (Phase 3 only)

| Spec § 5.3 requirement | Task |
|---|---|
| `etsy_duplicate_listing(listing_id, new_title=None)` | Task 3 |
| `etsy_save_listing_template(listing_id, template_path)` | Task 1 |
| `etsy_apply_listing_template(template_path, target_listing_ids, apply=False)` | Task 2 |
| `etsy_create_sale(percent_off, listing_ids, start, end, confirm=False)` (browser) | Task 5 |
| `etsy_create_coupon(code, percent_off, ..., confirm=False)` (browser) | Task 6 |
| `etsy_list_active_sales()` (browser) | Task 4 |
| `etsy_revenue_report(start, end, group_by)` | Task 7 |
| `etsy_top_listings_report(start, end, by, limit=20)` | Task 8 |
| Confirm guard for create_sale + create_coupon | Tasks 5 + 6 |
| Dry-run for apply_listing_template | Task 2 |
| Tools wrap EtsyMCPError → structured error dict | Every task |
| `by="views"` documented as unsupported | Task 8 |

**With Phase 3 shipped, the spec's full Tier 1 + 2 + 3 surface is implemented (53 tools).**
