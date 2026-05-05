# Etsy MCP — Phase 1a Implementation Plan (Read Tools)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the 12 read-only tools the user actually wants to use day-to-day: list/search/get listings (with inventory + images), list/get receipts (with transactions + ledger), list reviews, and shop info + derived stats. All wired into the existing FastMCP server from Phase 0.

**Architecture:** Each domain (`listings`, `receipts`, `reviews`, `shop`) lives in its own module under `etsy_mcp/`. Each module exposes a `register_<domain>_tools(mcp, *, keystring, tokens_path, shop_id_getter)` function that closes over the dependencies and registers `@mcp.tool()`-decorated coroutines on the given FastMCP instance. `server.py` calls all four registration functions at startup. This keeps tool definitions co-located with their domain logic, makes them testable in isolation (no env-var setup, no module-level globals), and lets `server.py` stay thin.

**Tech Stack:** Same as Phase 0 — Python 3.10+, `mcp[cli]` (FastMCP), `httpx` async, `respx` for tests. No new runtime deps.

**Spec:** `docs/superpowers/specs/2026-05-04-etsy-mcp-design.md` § 5.1
**Predecessor plan:** `docs/superpowers/plans/2026-05-04-etsy-mcp-phase-0.md` (executed)

---

## File Structure (Phase 1a only)

```
~/Desktop/Etsy MCP/
├── etsy_mcp/
│   ├── __init__.py       (unchanged)
│   ├── auth.py           (unchanged)
│   ├── http.py           (unchanged)
│   ├── errors.py         (unchanged)
│   ├── shop.py           NEW — etsy_get_shop, etsy_get_shop_stats
│   ├── listings.py       NEW — 5 listing read tools
│   ├── receipts.py       NEW — 4 receipt/payment read tools
│   └── reviews.py        NEW — etsy_list_reviews
├── tests/
│   └── unit/
│       ├── conftest.py             (already exists at tests/conftest.py — extend if needed)
│       ├── test_shop.py            NEW
│       ├── test_listings.py        NEW
│       ├── test_receipts.py        NEW
│       └── test_reviews.py         NEW
└── server.py             MODIFIED — call register_<domain>_tools(...) for all four
```

**Why this split:** Each module is one Etsy resource family. `listings.py` is the largest at 5 tools (~150 lines) — still well within "one file you can hold in context." The registration-function pattern keeps tool functions free of env-var / module-global coupling, which is the #1 source of brittle FastMCP integrations.

---

## Endpoint Reference (used by tasks below)

All paths are appended to `ETSY_API_BASE = "https://openapi.etsy.com/v3"`.

| Tool | Method | Path | Key params |
|---|---|---|---|
| `etsy_get_shop` | GET | `/application/shops/{shop_id}` | — |
| `etsy_get_shop_stats` | (derived) | `/application/shops/{shop_id}/receipts` | `min_created`, `max_created`, `limit=100` (paginates client-side) |
| `etsy_list_listings` | GET | `/application/shops/{shop_id}/listings` | `state`, `limit`, `offset` |
| `etsy_search_listings` | GET | `/application/shops/{shop_id}/listings` | `state` + client-side keyword filter on title/tags |
| `etsy_get_listing` | GET | `/application/listings/{listing_id}` | `includes` (CSV: Images,Inventory,Videos) |
| `etsy_get_listing_inventory` | GET | `/application/listings/{listing_id}/inventory` | — |
| `etsy_get_listing_images` | GET | `/application/shops/{shop_id}/listings/{listing_id}/images` | — |
| `etsy_list_receipts` | GET | `/application/shops/{shop_id}/receipts` | `min_created`, `max_created`, `was_paid`, `was_shipped`, `limit`, `offset` |
| `etsy_get_receipt` | GET | `/application/shops/{shop_id}/receipts/{receipt_id}` | — |
| `etsy_get_receipt_transactions` | GET | `/application/shops/{shop_id}/receipts/{receipt_id}/transactions` | — |
| `etsy_list_shop_payments` | GET | `/application/shops/{shop_id}/payment-account/ledger-entries` | `min_created`, `max_created`, `limit`, `offset` |
| `etsy_list_reviews` | GET | `/application/shops/{shop_id}/reviews` | `min_created`, `max_created`, `limit`, `offset` |

---

## Task 1: Test infrastructure — register-and-call helper

**Files:**
- Modify: `tests/conftest.py`

This task adds a fixture that wraps the boilerplate every per-tool test will use: create a FastMCP instance, seed `.tokens.json`, call the module's `register_<domain>_tools`, return the dict of tool callables.

- [ ] **Step 1: Inspect current conftest.py**

```bash
cat "/Users/sumit/Desktop/Etsy MCP/tests/conftest.py"
```

You should see the existing `tmp_tokens_path` fixture. Keep it.

- [ ] **Step 2: Append the new fixture**

Open `/Users/sumit/Desktop/Etsy MCP/tests/conftest.py` and replace its entire contents with:

```python
"""Shared pytest fixtures for Etsy MCP tests."""

from __future__ import annotations

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
        scope="listings_r shops_r transactions_r feedback_r",
    )
    return tmp_tokens_path


@pytest.fixture
def make_tools(seeded_tokens_path):
    """Factory: given a register_<domain>_tools function and a shop_id (or None
    for the missing-shop-id error path), return the dict of tool callables.

    Usage:
        from etsy_mcp.listings import register_listing_tools
        tools = make_tools(register_listing_tools, shop_id="123")
        result = await tools["etsy_list_listings"](limit=5)
    """

    def _factory(register_fn, *, shop_id="999"):
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("etsy-test")
        return register_fn(
            mcp,
            keystring="test-keystring",
            tokens_path=seeded_tokens_path,
            shop_id_getter=lambda: shop_id,
        )

    return _factory
```

- [ ] **Step 3: Verify fixtures import cleanly**

```bash
cd "/Users/sumit/Desktop/Etsy MCP"
.venv/bin/python -c "from tests.conftest import make_tools, seeded_tokens_path, tmp_tokens_path; print('OK')"
```

Expected: `OK`. The import-only check confirms no syntax errors. (Pytest will resolve the `seeded_tokens_path` and `tmp_path` dependencies at test time.)

- [ ] **Step 4: Run existing test suite to confirm no regression**

```bash
.venv/bin/pytest -v
```

Expected: 36 passed (Phase 0 baseline).

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py
git commit -m "$(cat <<'EOF'
test: add seeded_tokens_path + make_tools fixtures for Phase 1a

seeded_tokens_path writes a fresh-for-1-hour token file so tool tests
can run without triggering an Etsy refresh. make_tools is a factory
that wraps the register_<domain>_tools(mcp, ...) call boilerplate.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: shop.py — etsy_get_shop (and shared missing-shop-id helper)

**Files:**
- Modify: `etsy_mcp/errors.py` (add `missing_shop_id_error()` helper)
- Create: `etsy_mcp/shop.py`
- Create: `tests/unit/test_shop.py`
- Modify: `tests/unit/test_errors.py` (add helper test)

The `missing_shop_id_error()` helper is defined here once and reused by every Phase 1a module that needs `shop_id`. This avoids duplicating the same 5-line function across 4 modules.

- [ ] **Step 1: Add the helper to `errors.py`**

Open `/Users/sumit/Desktop/Etsy MCP/etsy_mcp/errors.py` and append at the END of the file:

```python


def missing_shop_id_error() -> dict[str, Any]:
    """Return the canonical structured error for tools that need ETSY_SHOP_ID
    but find it unset. Used by every Phase 1a module that calls a shop-scoped
    Etsy endpoint.
    """
    return structured_error(
        "ETSY_SHOP_ID is not set. Run scripts/bootstrap_oauth.py and paste "
        "the printed shop_id into your .env.",
        ErrorCode.AUTH_INVALID,
    )
```

- [ ] **Step 2: Add a test for the helper**

Append to `/Users/sumit/Desktop/Etsy MCP/tests/unit/test_errors.py`:

```python


def test_missing_shop_id_error_shape():
    from etsy_mcp.errors import missing_shop_id_error

    result = missing_shop_id_error()

    assert result["code"] == "auth_invalid"
    assert "ETSY_SHOP_ID" in result["error"]
    assert "bootstrap_oauth.py" in result["error"]
```

- [ ] **Step 3: Verify the errors test passes**

```bash
cd "/Users/sumit/Desktop/Etsy MCP"
.venv/bin/pytest tests/unit/test_errors.py -v
```

Expected: 6 passed (5 existing + 1 new).

- [ ] **Step 4: Write the failing shop test**

Create `/Users/sumit/Desktop/Etsy MCP/tests/unit/test_shop.py`:

```python
"""Tests for etsy_mcp.shop tools."""

from __future__ import annotations

import httpx
import pytest
import respx

from etsy_mcp.http import ETSY_API_BASE
from etsy_mcp.shop import register_shop_tools


@respx.mock
async def test_get_shop_returns_shop_dict(make_tools):
    tools = make_tools(register_shop_tools, shop_id="42")
    respx.get(f"{ETSY_API_BASE}/application/shops/42").mock(
        return_value=httpx.Response(
            200,
            json={"shop_id": 42, "shop_name": "TestShop", "currency_code": "USD"},
        )
    )

    result = await tools["etsy_get_shop"]()

    assert result == {"shop_id": 42, "shop_name": "TestShop", "currency_code": "USD"}


@respx.mock
async def test_get_shop_returns_structured_error_when_shop_id_missing(make_tools):
    tools = make_tools(register_shop_tools, shop_id="")
    # No respx mock — we should never reach the network.

    result = await tools["etsy_get_shop"]()

    assert result["code"] == "auth_invalid"
    assert "ETSY_SHOP_ID" in result["error"]


@respx.mock
async def test_get_shop_wraps_api_error_as_dict(make_tools):
    tools = make_tools(register_shop_tools, shop_id="42")
    respx.get(f"{ETSY_API_BASE}/application/shops/42").mock(
        return_value=httpx.Response(404, json={"error": "Shop not found"})
    )

    result = await tools["etsy_get_shop"]()

    assert result["code"] == "not_found"
    assert "error" in result
```

- [ ] **Step 5: Run shop test to verify failure**

```bash
.venv/bin/pytest tests/unit/test_shop.py -v
```

Expected: FAIL with `ImportError: cannot import name 'register_shop_tools' from 'etsy_mcp.shop'` (module doesn't exist).

- [ ] **Step 6: Write the implementation**

Create `/Users/sumit/Desktop/Etsy MCP/etsy_mcp/shop.py`:

```python
"""Shop-info tools for Etsy MCP.

Exposes:
  - etsy_get_shop: shop dict (name, currency, location, settings)
  - etsy_get_shop_stats: orders + revenue derived from receipts (added in Task 13)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from .errors import EtsyMCPError, missing_shop_id_error
from .http import etsy_request


def register_shop_tools(
    mcp: FastMCP,
    *,
    keystring: str,
    tokens_path: str | Path,
    shop_id_getter: Callable[[], str],
) -> dict[str, Callable]:
    """Register shop-related tools on the given FastMCP instance.

    Returns a dict of tool name → coroutine for direct invocation in tests.
    """

    @mcp.tool()
    async def etsy_get_shop() -> dict[str, Any]:
        """Return your shop's full info: name, currency, policies, status, counts."""
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()
        try:
            return await etsy_request(
                "GET",
                f"/application/shops/{shop_id}",
                keystring=keystring,
                tokens_path=str(tokens_path),
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

    return {"etsy_get_shop": etsy_get_shop}
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/test_shop.py -v
```

Expected: 3 passed.

- [ ] **Step 8: Run full suite for no regressions**

```bash
.venv/bin/pytest -v
```

Expected: 40 passed (36 Phase 0 baseline + 1 new errors test + 3 new shop tests).

- [ ] **Step 9: Commit**

```bash
git add etsy_mcp/errors.py etsy_mcp/shop.py tests/unit/test_errors.py tests/unit/test_shop.py
git commit -m "$(cat <<'EOF'
feat(shop): etsy_get_shop + missing_shop_id_error helper in errors.py

Establishes the Phase 1a pattern every domain module follows:
register_<domain>_tools(mcp, *, keystring, tokens_path, shop_id_getter)
closes over deps and decorates @mcp.tool() functions. Returns a dict
of tool callables for direct test invocation.

The missing_shop_id_error() helper lives in errors.py so all four
Phase 1a modules can share it instead of redefining the same 5-line
function. Tools always return a structured-error dict on EtsyMCPError
or when ETSY_SHOP_ID is unset — never raise past the MCP boundary.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: listings.py — etsy_list_listings

**Files:**
- Create: `etsy_mcp/listings.py`
- Create: `tests/unit/test_listings.py`

- [ ] **Step 1: Write the failing test**

Create `/Users/sumit/Desktop/Etsy MCP/tests/unit/test_listings.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/unit/test_listings.py -v
```

Expected: FAIL with `ImportError: cannot import name 'register_listing_tools'`.

- [ ] **Step 3: Write the implementation**

Create `/Users/sumit/Desktop/Etsy MCP/etsy_mcp/listings.py`:

```python
"""Listing read tools for Etsy MCP.

5 tools (all read-only). Phase 1b will add the corresponding write tools
to this same module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from .errors import EtsyMCPError, missing_shop_id_error
from .http import etsy_request


def register_listing_tools(
    mcp: FastMCP,
    *,
    keystring: str,
    tokens_path: str | Path,
    shop_id_getter: Callable[[], str],
) -> dict[str, Callable]:
    """Register listing tools on the given FastMCP instance."""

    @mcp.tool()
    async def etsy_list_listings(
        state: str = "active",
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List listings in your shop, filtered by state.

        Args:
            state: One of {active, inactive, draft, expired, sold_out}. Default "active".
            limit: Max 100. Default 25.
            offset: For pagination. Default 0.
        """
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()
        try:
            return await etsy_request(
                "GET",
                f"/application/shops/{shop_id}/listings",
                keystring=keystring,
                tokens_path=str(tokens_path),
                params={"state": state, "limit": limit, "offset": offset},
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

    return {"etsy_list_listings": etsy_list_listings}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/test_listings.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 43 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/listings.py tests/unit/test_listings.py
git commit -m "$(cat <<'EOF'
feat(listings): etsy_list_listings tool

Lists listings in the user's shop by state (default active), with limit
and offset for pagination. Maps to GET /shops/{shop_id}/listings.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: listings.py — etsy_search_listings

**Files:**
- Modify: `etsy_mcp/listings.py`
- Modify: `tests/unit/test_listings.py`

Etsy v3 doesn't expose a "search MY shop by keyword" endpoint. We fetch listings via `getListingsByShop` and filter client-side on title + tags + description.

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_listings.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/test_listings.py::test_search_listings_filters_by_keyword_in_title -v
```

Expected: FAIL — `etsy_search_listings` is not a key in the returned tools dict.

- [ ] **Step 3: Extend the implementation**

In `etsy_mcp/listings.py`, INSIDE the `register_listing_tools` function (after `etsy_list_listings` definition, before the `return` statement), add:

```python
    @mcp.tool()
    async def etsy_search_listings(
        keyword: str,
        state: str = "active",
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Search your shop's listings by keyword in title/tags/description.

        Etsy's API doesn't expose a per-shop keyword search, so this fetches
        a page of your listings and filters client-side. For exhaustive
        search across a large shop, paginate by calling repeatedly with
        increasing offset.

        Args:
            keyword: Case-insensitive substring match.
            state: Listing state filter passed to the underlying API.
            limit: Page size to fetch from Etsy. Default 100 (API max).
            offset: Page offset.
        """
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()
        try:
            page = await etsy_request(
                "GET",
                f"/application/shops/{shop_id}/listings",
                keystring=keystring,
                tokens_path=str(tokens_path),
                params={"state": state, "limit": limit, "offset": offset},
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

        if not isinstance(page, dict):
            return {"error": "Etsy listings endpoint returned unexpected shape", "code": "unknown"}

        results = page.get("results") or []
        needle = keyword.lower()

        def _matches(listing: dict[str, Any]) -> bool:
            title = (listing.get("title") or "").lower()
            description = (listing.get("description") or "").lower()
            tags = [str(t).lower() for t in (listing.get("tags") or [])]
            return needle in title or needle in description or any(needle in t for t in tags)

        matched = [r for r in results if _matches(r)]
        return {"count": len(matched), "results": matched}
```

ALSO update the return dict at the bottom of `register_listing_tools` to include the new tool:

```python
    return {
        "etsy_list_listings": etsy_list_listings,
        "etsy_search_listings": etsy_search_listings,
    }
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_listings.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 46 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/listings.py tests/unit/test_listings.py
git commit -m "$(cat <<'EOF'
feat(listings): etsy_search_listings — keyword filter over shop listings

Etsy v3 has no per-shop keyword search. This tool fetches a page of
listings via getListingsByShop and filters client-side on title, tags,
and description (case-insensitive substring). For shops with many
listings, the caller paginates by re-issuing with increasing offset.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: listings.py — etsy_get_listing

**Files:**
- Modify: `etsy_mcp/listings.py`
- Modify: `tests/unit/test_listings.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_listings.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/test_listings.py::test_get_listing_no_includes -v
```

Expected: FAIL — `etsy_get_listing` not in tools dict.

- [ ] **Step 3: Extend the implementation**

INSIDE `register_listing_tools` (after `etsy_search_listings`, before the return dict), add:

```python
    @mcp.tool()
    async def etsy_get_listing(
        listing_id: int,
        includes: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return a single listing by id.

        Args:
            listing_id: The listing's numeric id.
            includes: Optional list of related resources to embed. Valid values:
                Images, Inventory, Videos, Translations, Application.
        """
        params: dict[str, Any] = {}
        if includes:
            params["includes"] = ",".join(includes)
        try:
            return await etsy_request(
                "GET",
                f"/application/listings/{listing_id}",
                keystring=keystring,
                tokens_path=str(tokens_path),
                params=params or None,
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
    }
```

Note: this tool does NOT need `shop_id` — Etsy's `/application/listings/{listing_id}` is shop-agnostic.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_listings.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 49 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/listings.py tests/unit/test_listings.py
git commit -m "$(cat <<'EOF'
feat(listings): etsy_get_listing with optional includes

Maps to GET /listings/{listing_id}. The includes param accepts a list
of related resources (Images, Inventory, Videos, Translations,
Application) and joins them as CSV in the query string per Etsy v3
convention. Listing-id endpoints are shop-agnostic, so this tool does
not need ETSY_SHOP_ID.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: listings.py — etsy_get_listing_inventory

**Files:**
- Modify: `etsy_mcp/listings.py`
- Modify: `tests/unit/test_listings.py`

- [ ] **Step 1: Append failing test**

Append to `tests/unit/test_listings.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/unit/test_listings.py::test_get_listing_inventory_returns_products -v
```

Expected: FAIL — `etsy_get_listing_inventory` not registered.

- [ ] **Step 3: Extend the implementation**

INSIDE `register_listing_tools` (after `etsy_get_listing`, before the return dict), add:

```python
    @mcp.tool()
    async def etsy_get_listing_inventory(listing_id: int) -> dict[str, Any]:
        """Return SKUs, offerings, prices, quantities, and property values for a listing."""
        try:
            return await etsy_request(
                "GET",
                f"/application/listings/{listing_id}/inventory",
                keystring=keystring,
                tokens_path=str(tokens_path),
            )
        except EtsyMCPError as exc:
            return exc.to_dict()
```

UPDATE the return dict:

```python
    return {
        "etsy_list_listings": etsy_list_listings,
        "etsy_search_listings": etsy_search_listings,
        "etsy_get_listing": etsy_get_listing,
        "etsy_get_listing_inventory": etsy_get_listing_inventory,
    }
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_listings.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 50 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/listings.py tests/unit/test_listings.py
git commit -m "$(cat <<'EOF'
feat(listings): etsy_get_listing_inventory

Maps to GET /listings/{listing_id}/inventory. Returns the products
array with SKU, offerings (price + quantity per variant), and
property_values (size/color/etc).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: listings.py — etsy_get_listing_images

**Files:**
- Modify: `etsy_mcp/listings.py`
- Modify: `tests/unit/test_listings.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_listings.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify failure**

```bash
.venv/bin/pytest tests/unit/test_listings.py::test_get_listing_images_returns_results -v
```

Expected: FAIL — `etsy_get_listing_images` not registered.

- [ ] **Step 3: Extend the implementation**

INSIDE `register_listing_tools` (after `etsy_get_listing_inventory`, before the return dict), add:

```python
    @mcp.tool()
    async def etsy_get_listing_images(listing_id: int) -> dict[str, Any]:
        """Return image metadata (id, rank, urls, alt_text) for a listing."""
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()
        try:
            return await etsy_request(
                "GET",
                f"/application/shops/{shop_id}/listings/{listing_id}/images",
                keystring=keystring,
                tokens_path=str(tokens_path),
            )
        except EtsyMCPError as exc:
            return exc.to_dict()
```

UPDATE the return dict:

```python
    return {
        "etsy_list_listings": etsy_list_listings,
        "etsy_search_listings": etsy_search_listings,
        "etsy_get_listing": etsy_get_listing,
        "etsy_get_listing_inventory": etsy_get_listing_inventory,
        "etsy_get_listing_images": etsy_get_listing_images,
    }
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_listings.py -v
```

Expected: 12 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 52 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/listings.py tests/unit/test_listings.py
git commit -m "$(cat <<'EOF'
feat(listings): etsy_get_listing_images

Maps to GET /shops/{shop_id}/listings/{listing_id}/images. Unlike
get_listing, the images endpoint requires shop_id in the path so it
returns the missing-shop-id error when ETSY_SHOP_ID is unset.

Listings module now has 5 read tools — all of Phase 1a's listing surface.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: receipts.py — etsy_list_receipts

**Files:**
- Create: `etsy_mcp/receipts.py`
- Create: `tests/unit/test_receipts.py`

- [ ] **Step 1: Write the failing test**

Create `/Users/sumit/Desktop/Etsy MCP/tests/unit/test_receipts.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/unit/test_receipts.py -v
```

Expected: FAIL with `ImportError: cannot import name 'register_receipt_tools'`.

- [ ] **Step 3: Write the implementation**

Create `/Users/sumit/Desktop/Etsy MCP/etsy_mcp/receipts.py`:

```python
"""Receipt + payment read tools for Etsy MCP.

4 tools (all read-only). Phase 1b will add ship/refund/bulk-ship to this
same module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from .errors import EtsyMCPError, missing_shop_id_error
from .http import etsy_request


def register_receipt_tools(
    mcp: FastMCP,
    *,
    keystring: str,
    tokens_path: str | Path,
    shop_id_getter: Callable[[], str],
) -> dict[str, Callable]:
    """Register receipt/payment tools on the given FastMCP instance."""

    @mcp.tool()
    async def etsy_list_receipts(
        was_paid: bool | None = None,
        was_shipped: bool | None = None,
        min_created: int | None = None,
        max_created: int | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List receipts (orders) for your shop.

        Args:
            was_paid: Filter by payment status. None means no filter.
            was_shipped: Filter by ship status. None means no filter.
            min_created: Unix timestamp (seconds) — only receipts created at or after.
            max_created: Unix timestamp (seconds) — only receipts created at or before.
            limit: Max 100. Default 25.
            offset: For pagination.
        """
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()

        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if was_paid is not None:
            params["was_paid"] = "true" if was_paid else "false"
        if was_shipped is not None:
            params["was_shipped"] = "true" if was_shipped else "false"
        if min_created is not None:
            params["min_created"] = min_created
        if max_created is not None:
            params["max_created"] = max_created

        try:
            return await etsy_request(
                "GET",
                f"/application/shops/{shop_id}/receipts",
                keystring=keystring,
                tokens_path=str(tokens_path),
                params=params,
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

    return {"etsy_list_receipts": etsy_list_receipts}
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_receipts.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 55 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/receipts.py tests/unit/test_receipts.py
git commit -m "$(cat <<'EOF'
feat(receipts): etsy_list_receipts

First receipts tool. Maps to GET /shops/{shop_id}/receipts with the
full set of filter params Etsy supports: was_paid, was_shipped,
min_created/max_created (unix seconds), limit, offset. Bool filters
serialize to the lowercase 'true'/'false' string Etsy expects; None
values are simply not included.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: receipts.py — etsy_get_receipt

**Files:**
- Modify: `etsy_mcp/receipts.py`
- Modify: `tests/unit/test_receipts.py`

- [ ] **Step 1: Append failing test**

Append to `tests/unit/test_receipts.py`:

```python
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
```

- [ ] **Step 2: Run test to verify failure**

```bash
.venv/bin/pytest tests/unit/test_receipts.py::test_get_receipt_returns_receipt -v
```

Expected: FAIL — `etsy_get_receipt` not registered.

- [ ] **Step 3: Extend the implementation**

INSIDE `register_receipt_tools` (after `etsy_list_receipts`, before the return dict), add:

```python
    @mcp.tool()
    async def etsy_get_receipt(receipt_id: int) -> dict[str, Any]:
        """Return a single receipt (order) with buyer info, totals, and shipping."""
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()
        try:
            return await etsy_request(
                "GET",
                f"/application/shops/{shop_id}/receipts/{receipt_id}",
                keystring=keystring,
                tokens_path=str(tokens_path),
            )
        except EtsyMCPError as exc:
            return exc.to_dict()
```

UPDATE return dict:

```python
    return {
        "etsy_list_receipts": etsy_list_receipts,
        "etsy_get_receipt": etsy_get_receipt,
    }
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_receipts.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 56 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/receipts.py tests/unit/test_receipts.py
git commit -m "$(cat <<'EOF'
feat(receipts): etsy_get_receipt

Maps to GET /shops/{shop_id}/receipts/{receipt_id}. Returns the full
receipt: buyer, totals, shipping address, status flags.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: receipts.py — etsy_get_receipt_transactions

**Files:**
- Modify: `etsy_mcp/receipts.py`
- Modify: `tests/unit/test_receipts.py`

- [ ] **Step 1: Append failing test**

Append to `tests/unit/test_receipts.py`:

```python
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
```

- [ ] **Step 2: Verify failure**

```bash
.venv/bin/pytest tests/unit/test_receipts.py::test_get_receipt_transactions_returns_line_items -v
```

Expected: FAIL — `etsy_get_receipt_transactions` not registered.

- [ ] **Step 3: Extend the implementation**

INSIDE `register_receipt_tools` (after `etsy_get_receipt`, before the return), add:

```python
    @mcp.tool()
    async def etsy_get_receipt_transactions(receipt_id: int) -> dict[str, Any]:
        """Return the line items (transactions) for a receipt: SKU, title, quantity, price."""
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()
        try:
            return await etsy_request(
                "GET",
                f"/application/shops/{shop_id}/receipts/{receipt_id}/transactions",
                keystring=keystring,
                tokens_path=str(tokens_path),
            )
        except EtsyMCPError as exc:
            return exc.to_dict()
```

UPDATE the return dict:

```python
    return {
        "etsy_list_receipts": etsy_list_receipts,
        "etsy_get_receipt": etsy_get_receipt,
        "etsy_get_receipt_transactions": etsy_get_receipt_transactions,
    }
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_receipts.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 57 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/receipts.py tests/unit/test_receipts.py
git commit -m "$(cat <<'EOF'
feat(receipts): etsy_get_receipt_transactions

Maps to GET /shops/{shop_id}/receipts/{receipt_id}/transactions.
Returns the line items for a single receipt — listing_id, title,
quantity, price, sku — needed for any per-item analysis.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: receipts.py — etsy_list_shop_payments

**Files:**
- Modify: `etsy_mcp/receipts.py`
- Modify: `tests/unit/test_receipts.py`

This wraps Etsy's payment-account ledger entries endpoint, which is the practical "shop payments" view: charges, credits, fees, refunds.

- [ ] **Step 1: Append failing test**

Append to `tests/unit/test_receipts.py`:

```python
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
```

- [ ] **Step 2: Verify failure**

```bash
.venv/bin/pytest tests/unit/test_receipts.py::test_list_shop_payments_with_date_range -v
```

Expected: FAIL — tool not registered.

- [ ] **Step 3: Extend the implementation**

INSIDE `register_receipt_tools` (after `etsy_get_receipt_transactions`), add:

```python
    @mcp.tool()
    async def etsy_list_shop_payments(
        min_created: int | None = None,
        max_created: int | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List your shop's payment ledger entries: charges, fees, credits, refunds.

        Maps to Etsy's getShopPaymentAccountLedgerEntries. For per-receipt
        payment status use etsy_get_receipt instead.
        """
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()

        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if min_created is not None:
            params["min_created"] = min_created
        if max_created is not None:
            params["max_created"] = max_created

        try:
            return await etsy_request(
                "GET",
                f"/application/shops/{shop_id}/payment-account/ledger-entries",
                keystring=keystring,
                tokens_path=str(tokens_path),
                params=params,
            )
        except EtsyMCPError as exc:
            return exc.to_dict()
```

UPDATE the return dict:

```python
    return {
        "etsy_list_receipts": etsy_list_receipts,
        "etsy_get_receipt": etsy_get_receipt,
        "etsy_get_receipt_transactions": etsy_get_receipt_transactions,
        "etsy_list_shop_payments": etsy_list_shop_payments,
    }
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_receipts.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 59 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/receipts.py tests/unit/test_receipts.py
git commit -m "$(cat <<'EOF'
feat(receipts): etsy_list_shop_payments

Maps to GET /shops/{shop_id}/payment-account/ledger-entries. The
ledger contains every monetary movement: charges, fees, credits,
refunds — the complete picture of what Etsy paid out to the shop.

Receipts module now has 4 tools — all of Phase 1a's receipt surface.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: reviews.py — etsy_list_reviews

**Files:**
- Create: `etsy_mcp/reviews.py`
- Create: `tests/unit/test_reviews.py`

- [ ] **Step 1: Write the failing test**

Create `/Users/sumit/Desktop/Etsy MCP/tests/unit/test_reviews.py`:

```python
"""Tests for etsy_mcp.reviews tools."""

from __future__ import annotations

import httpx
import pytest
import respx

from etsy_mcp.http import ETSY_API_BASE
from etsy_mcp.reviews import register_review_tools


@respx.mock
async def test_list_reviews_default(make_tools):
    tools = make_tools(register_review_tools, shop_id="42")
    route = respx.get(f"{ETSY_API_BASE}/application/shops/42/reviews").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "results": [
                    {"review_id": 1, "rating": 5, "review": "Loved it"},
                ],
            },
        )
    )

    result = await tools["etsy_list_reviews"]()

    assert route.called
    call = route.calls.last
    assert call.request.url.params["limit"] == "25"
    assert call.request.url.params["offset"] == "0"
    assert result["count"] == 1


@respx.mock
async def test_list_reviews_with_date_range(make_tools):
    tools = make_tools(register_review_tools, shop_id="42")
    route = respx.get(f"{ETSY_API_BASE}/application/shops/42/reviews").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    await tools["etsy_list_reviews"](
        min_created=1700000000, max_created=1800000000, limit=100, offset=50
    )

    call = route.calls.last
    assert call.request.url.params["min_created"] == "1700000000"
    assert call.request.url.params["max_created"] == "1800000000"
    assert call.request.url.params["limit"] == "100"
    assert call.request.url.params["offset"] == "50"


async def test_list_reviews_missing_shop_id(make_tools):
    tools = make_tools(register_review_tools, shop_id="")
    result = await tools["etsy_list_reviews"]()
    assert result["code"] == "auth_invalid"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/unit/test_reviews.py -v
```

Expected: FAIL — `register_review_tools` not importable.

- [ ] **Step 3: Write the implementation**

Create `/Users/sumit/Desktop/Etsy MCP/etsy_mcp/reviews.py`:

```python
"""Review read tools for Etsy MCP.

Phase 1a: read-only. Etsy v3 doesn't expose review-write endpoints — sellers
respond via the seller dashboard.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from .errors import EtsyMCPError, missing_shop_id_error
from .http import etsy_request


def register_review_tools(
    mcp: FastMCP,
    *,
    keystring: str,
    tokens_path: str | Path,
    shop_id_getter: Callable[[], str],
) -> dict[str, Callable]:
    """Register review tools on the given FastMCP instance."""

    @mcp.tool()
    async def etsy_list_reviews(
        min_created: int | None = None,
        max_created: int | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List reviews for your shop.

        Args:
            min_created: Unix timestamp (seconds) — only reviews at or after.
            max_created: Unix timestamp (seconds) — only reviews at or before.
            limit: Max 100. Default 25.
            offset: For pagination.
        """
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()

        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if min_created is not None:
            params["min_created"] = min_created
        if max_created is not None:
            params["max_created"] = max_created

        try:
            return await etsy_request(
                "GET",
                f"/application/shops/{shop_id}/reviews",
                keystring=keystring,
                tokens_path=str(tokens_path),
                params=params,
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

    return {"etsy_list_reviews": etsy_list_reviews}
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_reviews.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 62 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/reviews.py tests/unit/test_reviews.py
git commit -m "$(cat <<'EOF'
feat(reviews): etsy_list_reviews

Maps to GET /shops/{shop_id}/reviews. Returns review records (rating,
text, language, timestamps). Etsy v3 has no write endpoints for reviews
— responses happen in the seller dashboard — so this completes the
review surface for Phase 1a.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: shop.py — etsy_get_shop_stats (derived from receipts)

**Files:**
- Modify: `etsy_mcp/shop.py`
- Modify: `tests/unit/test_shop.py`

Etsy v3 has no "stats" endpoint. We aggregate orders + revenue from receipts in the requested date range. visits/favorites are not retrievable via API; we document the gap in the docstring and don't return those fields.

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_shop.py`:

```python
@respx.mock
async def test_get_shop_stats_aggregates_receipts(make_tools):
    tools = make_tools(register_shop_tools, shop_id="42")
    # Single page of 3 receipts spanning the requested window.
    respx.get(f"{ETSY_API_BASE}/application/shops/42/receipts").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 3,
                "results": [
                    {"receipt_id": 1, "grandtotal": {"amount": 1500, "divisor": 100, "currency_code": "USD"}},
                    {"receipt_id": 2, "grandtotal": {"amount": 2500, "divisor": 100, "currency_code": "USD"}},
                    {"receipt_id": 3, "grandtotal": {"amount": 3000, "divisor": 100, "currency_code": "USD"}},
                ],
            },
        )
    )

    result = await tools["etsy_get_shop_stats"](
        min_created=1700000000, max_created=1800000000
    )

    assert result["orders"] == 3
    # 1500 + 2500 + 3000 = 7000 cents = 70 USD
    assert result["revenue"]["amount_cents"] == 7000
    assert result["revenue"]["currency_code"] == "USD"
    assert result["period"]["min_created"] == 1700000000
    assert result["period"]["max_created"] == 1800000000


@respx.mock
async def test_get_shop_stats_handles_empty_period(make_tools):
    tools = make_tools(register_shop_tools, shop_id="42")
    respx.get(f"{ETSY_API_BASE}/application/shops/42/receipts").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    result = await tools["etsy_get_shop_stats"](
        min_created=1700000000, max_created=1800000000
    )

    assert result["orders"] == 0
    assert result["revenue"]["amount_cents"] == 0


async def test_get_shop_stats_missing_shop_id(make_tools):
    tools = make_tools(register_shop_tools, shop_id="")
    result = await tools["etsy_get_shop_stats"](
        min_created=1700000000, max_created=1800000000
    )
    assert result["code"] == "auth_invalid"


@respx.mock
async def test_get_shop_stats_paginates_to_collect_all(make_tools):
    """Receipts paginate. The tool must follow pages until exhausted.

    First page has 100 receipts. Second page has 25. Total: 125 orders.
    """
    tools = make_tools(register_shop_tools, shop_id="42")

    page1 = {
        "count": 125,
        "results": [
            {"receipt_id": i, "grandtotal": {"amount": 100, "divisor": 100, "currency_code": "USD"}}
            for i in range(100)
        ],
    }
    page2 = {
        "count": 125,
        "results": [
            {"receipt_id": i, "grandtotal": {"amount": 100, "divisor": 100, "currency_code": "USD"}}
            for i in range(100, 125)
        ],
    }

    respx.get(f"{ETSY_API_BASE}/application/shops/42/receipts").mock(
        side_effect=[
            httpx.Response(200, json=page1),
            httpx.Response(200, json=page2),
        ]
    )

    result = await tools["etsy_get_shop_stats"](
        min_created=1700000000, max_created=1800000000
    )

    assert result["orders"] == 125
    assert result["revenue"]["amount_cents"] == 12500
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/test_shop.py::test_get_shop_stats_aggregates_receipts -v
```

Expected: FAIL — `etsy_get_shop_stats` not registered.

- [ ] **Step 3: Extend the implementation**

In `etsy_mcp/shop.py`, INSIDE `register_shop_tools` (after `etsy_get_shop`, before the return dict), add:

```python
    @mcp.tool()
    async def etsy_get_shop_stats(
        min_created: int,
        max_created: int,
    ) -> dict[str, Any]:
        """Aggregate orders + revenue for your shop in a date range.

        Etsy's API does not expose visits or favorites — those are only
        visible in the seller dashboard. This tool computes orders and
        revenue from receipts in the requested window by paginating
        /shops/{shop_id}/receipts at limit=100 until exhausted.

        Args:
            min_created: Unix timestamp (seconds) — start of window (inclusive).
            max_created: Unix timestamp (seconds) — end of window (inclusive).

        Returns:
            {
              "orders": int,
              "revenue": {"amount_cents": int, "currency_code": str},
              "period": {"min_created": int, "max_created": int},
              "note": "visits/favorites not available via Etsy Open API v3"
            }
        """
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()

        page_size = 100
        offset = 0
        total_orders = 0
        total_cents = 0
        currency_code: str | None = None

        try:
            while True:
                page = await etsy_request(
                    "GET",
                    f"/application/shops/{shop_id}/receipts",
                    keystring=keystring,
                    tokens_path=str(tokens_path),
                    params={
                        "min_created": min_created,
                        "max_created": max_created,
                        "limit": page_size,
                        "offset": offset,
                    },
                )

                if not isinstance(page, dict):
                    return {"error": "Etsy receipts endpoint returned unexpected shape", "code": "unknown"}

                results = page.get("results") or []
                for r in results:
                    total_orders += 1
                    grandtotal = r.get("grandtotal") or {}
                    amount = grandtotal.get("amount", 0)
                    divisor = grandtotal.get("divisor", 1) or 1
                    # Normalize to cents regardless of Etsy's divisor (usually 100).
                    total_cents += int(amount * 100 / divisor)
                    if currency_code is None:
                        currency_code = grandtotal.get("currency_code") or grandtotal.get("currency_formatted_short")

                if len(results) < page_size:
                    break
                offset += page_size
        except EtsyMCPError as exc:
            return exc.to_dict()

        return {
            "orders": total_orders,
            "revenue": {"amount_cents": total_cents, "currency_code": currency_code or "USD"},
            "period": {"min_created": min_created, "max_created": max_created},
            "note": "visits/favorites not available via Etsy Open API v3",
        }
```

UPDATE the return dict at the bottom of `register_shop_tools`:

```python
    return {
        "etsy_get_shop": etsy_get_shop,
        "etsy_get_shop_stats": etsy_get_shop_stats,
    }
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_shop.py -v
```

Expected: 7 passed (3 original + 4 new).

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 66 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/shop.py tests/unit/test_shop.py
git commit -m "$(cat <<'EOF'
feat(shop): etsy_get_shop_stats — orders + revenue derived from receipts

Etsy v3 has no shop-stats endpoint. This tool paginates the receipts
endpoint at limit=100 over the requested date window and aggregates:
order count = number of receipts; revenue = sum of grandtotal amounts
normalized to cents (handles Etsy's divisor field). Visits + favorites
are documented as unavailable.

Currency_code is captured from the first receipt and falls back to
USD if the response shape is unexpected.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: server.py — wire up all four registration functions

**Files:**
- Modify: `server.py`

- [ ] **Step 1: Read current server.py**

```bash
cat "/Users/sumit/Desktop/Etsy MCP/server.py"
```

You should see the existing module: imports, `mcp = FastMCP("etsy")`, `etsy_whoami`, `etsy_token_status`, `if __name__ == "__main__": mcp.run()`.

- [ ] **Step 2: Modify `server.py` to call the four registration functions**

Open `/Users/sumit/Desktop/Etsy MCP/server.py` and add the following imports near the existing imports (after `from etsy_mcp.http import etsy_request`):

```python
from etsy_mcp.listings import register_listing_tools
from etsy_mcp.receipts import register_receipt_tools
from etsy_mcp.reviews import register_review_tools
from etsy_mcp.shop import register_shop_tools
```

Add this helper just BEFORE `mcp = FastMCP("etsy")`:

```python
def _shop_id() -> str:
    return os.environ.get("ETSY_SHOP_ID", "").strip()
```

Add the four registration calls just AFTER `mcp = FastMCP("etsy")` and BEFORE the `etsy_whoami` definition:

```python
register_shop_tools(
    mcp,
    keystring=KEYSTRING,
    tokens_path=TOKENS_PATH,
    shop_id_getter=_shop_id,
)
register_listing_tools(
    mcp,
    keystring=KEYSTRING,
    tokens_path=TOKENS_PATH,
    shop_id_getter=_shop_id,
)
register_receipt_tools(
    mcp,
    keystring=KEYSTRING,
    tokens_path=TOKENS_PATH,
    shop_id_getter=_shop_id,
)
register_review_tools(
    mcp,
    keystring=KEYSTRING,
    tokens_path=TOKENS_PATH,
    shop_id_getter=_shop_id,
)
```

Leave the existing `etsy_whoami` and `etsy_token_status` definitions UNCHANGED — they continue to be registered via their `@mcp.tool()` decorators.

- [ ] **Step 3: Verify the server module imports cleanly**

```bash
cd "/Users/sumit/Desktop/Etsy MCP"
ETSY_KEYSTRING=test_placeholder .venv/bin/python -c "import server; print('OK')"
```

Expected: `OK` — no traceback.

- [ ] **Step 4: Verify the server starts without crashing**

```bash
ETSY_KEYSTRING=test_placeholder timeout 3 .venv/bin/python server.py 2>&1 | head -20 || true
```

Expected: server starts and waits for stdio input. The `timeout 3` kills it after 3 seconds — that's fine. Any traceback is a problem.

- [ ] **Step 5: Run full test suite**

```bash
.venv/bin/pytest -v
```

Expected: 66 passed (Task 13 baseline; this task adds no tests).

- [ ] **Step 6: Commit**

```bash
git add server.py
git commit -m "$(cat <<'EOF'
feat(server): wire up Phase 1a tools — shop, listings, receipts, reviews

Calls the four register_<domain>_tools(mcp, ...) factories at module
load with the shared keystring + tokens_path + shop_id_getter so all
12 Phase 1a read tools become available on the FastMCP instance.

The phase-0 tools (etsy_whoami, etsy_token_status) remain registered
via their @mcp.tool() decorators on the same FastMCP instance.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: Final verification + push to GitHub

- [ ] **Step 1: Run the full suite one final time**

```bash
cd "/Users/sumit/Desktop/Etsy MCP"
.venv/bin/pytest -v
```

Expected: 66 passed (30 new in Phase 1a + 36 from Phase 0).

- [ ] **Step 2: Confirm no secrets staged or in history**

```bash
git status --ignored | grep -E "\.env$|\.tokens\.json|logs/"
git diff --staged
git log --all --full-history -- .env .tokens.json
```

Expected: ignored files listed (or empty if they don't exist yet); no staged diff; no history of `.env`/`.tokens.json`. STOP if anything appears.

- [ ] **Step 3: Verify all 14 tools are registered on the FastMCP instance**

```bash
ETSY_KEYSTRING=test_placeholder .venv/bin/python <<'PY'
import asyncio
import server

async def main():
    tools = await server.mcp.list_tools()
    names = sorted(t.name for t in tools)
    expected = sorted([
        "etsy_whoami", "etsy_token_status",
        "etsy_get_shop", "etsy_get_shop_stats",
        "etsy_list_listings", "etsy_search_listings", "etsy_get_listing",
        "etsy_get_listing_inventory", "etsy_get_listing_images",
        "etsy_list_receipts", "etsy_get_receipt", "etsy_get_receipt_transactions",
        "etsy_list_shop_payments",
        "etsy_list_reviews",
    ])
    print("registered:", names)
    print("expected:  ", expected)
    assert names == expected, f"missing: {set(expected) - set(names)}; extra: {set(names) - set(expected)}"
    print("OK — all 14 tools registered")

asyncio.run(main())
PY
```

Expected: prints both lists then `OK — all 14 tools registered`.

If the assertion fails, a tool isn't registered — go fix the corresponding module's `register_*_tools` function before continuing.

- [ ] **Step 4: Push to GitHub**

```bash
git push origin main
```

Expected: pushes ~14 new commits (Tasks 1-14) to https://github.com/kumarsumit2000/Etsy-MCP. The remote was set to the SSH-aliased URL `git@github-kumarsumit2000:kumarsumit2000/Etsy-MCP.git` during Phase 0; if that's been changed, restore it with:

```bash
git remote set-url origin git@github-kumarsumit2000:kumarsumit2000/Etsy-MCP.git
git push origin main
```

- [ ] **Step 5: Mark Phase 1a complete**

Phase 1a acceptance criterion (from spec § 7):

> All Tier 1 read tools return real data from Claude.

This requires:
1. Etsy app approved + bootstrap_oauth.py run (manual user step from Phase 0).
2. ETSY_SHOP_ID populated in .env.
3. MCP wired into Claude Code (manual, per SETUP.md).
4. Calling each of the 12 new tools from Claude returns real shop data (or a clearly-shaped error if e.g. a listing_id doesn't exist).

The unit test suite (65 passing) verifies the implementation against mocked Etsy responses. End-to-end verification depends on user-side setup that can't be automated.

---

## Spec coverage check (Phase 1a only)

| Spec requirement (§ 5.1) | Task |
|---|---|
| Listings — read (5 tools) | Tasks 3-7 |
| Receipts (4 tools) | Tasks 8-11 |
| Reviews (1 tool) | Task 12 |
| Shop info + stats (2 tools) | Tasks 2 + 13 |
| Each tool wraps EtsyMCPError → structured error dict | Every Task — verified by `*_missing_shop_id` and `*_404_returns_structured_error` tests |
| Tools call etsy_request, never re-implement HTTP | Every Task |
| ETSY_SHOP_ID injection via shop_id_getter | Tasks 2-13 |
| Tools registered on existing FastMCP instance via `register_<domain>_tools(mcp, ...)` | Task 14 |
| Pagination via limit + offset params | Listings, receipts, reviews, payments tasks |

Out of scope (Phase 1b+):
- Listing write tools (create/update/delete/upload-image/inventory)
- Receipt write tools (mark_shipped, refund)
- Bulk export (Phase 1b)
- Etsy Ads browser tools (Phase 1c)
- Tier 2 (operational) and Tier 3 (advanced) tools
