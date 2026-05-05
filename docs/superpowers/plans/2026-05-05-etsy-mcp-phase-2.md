# Etsy MCP — Phase 2 Implementation Plan (Tier 2 Operational Tools)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the operational write tools the user runs as part of daily seller workflow: marking receipts shipped (single + bulk via CSV), issuing refunds, managing shop config (shipping profiles, sections, return policies, production partners), and bulk inventory updates (prices, quantities, listing renewal).

**Architecture:** Three new domain modules on the established Phase-1 pattern. `orders.py` extends receipt operations (write side); `shop_config.py` collects all four shop-resource families; `bulk_ops.py` adds dry-run-by-default mass-edit tools that internally drive other tools / endpoints. All write tools follow the boundary contract — wrap `EtsyMCPError` to a structured-error dict, never raise past the MCP boundary. Destructive or money-moving tools (`issue_refund`, `bulk_renew_listings`) require `confirm=True`. Mass-edit tools default to `apply=False` (dry-run preview) and only mutate when explicitly opted in.

**Tech Stack:** Same as Phase 0/1 — Python 3.10+, FastMCP, httpx, respx, csv (stdlib). No new runtime deps.

**Spec:** `docs/superpowers/specs/2026-05-04-etsy-mcp-design.md` § 5.2
**Predecessor plans:** Phase 0, 1a, 1b, 1c (all executed and shipped).

---

## File Structure (Phase 2 only)

```
~/Desktop/Etsy MCP/
├── etsy_mcp/
│   ├── orders.py         NEW — mark_receipt_shipped, bulk_mark_shipped, issue_refund (3 tools)
│   ├── shop_config.py    NEW — shipping profiles, sections, return policies, production partners (10 tools)
│   └── bulk_ops.py       NEW — bulk_update_prices, bulk_update_quantities, bulk_renew_listings (3 tools)
├── tests/
│   └── unit/
│       ├── test_orders.py        NEW
│       ├── test_shop_config.py   NEW
│       └── test_bulk_ops.py      NEW
└── server.py             MODIFIED — register the 3 new factories
```

**Why this split:** Each module has one cohesive responsibility:
- `orders.py` mutates receipts (ship, refund). Reads are already in `receipts.py` from Phase 1a — Phase 1a/1b are read+write per resource, but receipts.py is already large enough that splitting writes out keeps both files focused.
- `shop_config.py` covers four resource families that all describe shop-level metadata and are typically managed together (e.g., creating a listing requires picking a shipping profile + return policy).
- `bulk_ops.py` is fundamentally different — these tools coordinate many calls across listings with dry-run safety. Living in their own module makes that batch-orchestration nature obvious.

---

## Etsy v3 endpoint reference

| Tool | Method | Path | Body / params |
|---|---|---|---|
| `etsy_mark_receipt_shipped` | POST | `/application/shops/{shop_id}/receipts/{receipt_id}/tracking` | form: `tracking_code`, `carrier_name`, `send_bcc` |
| `etsy_bulk_mark_shipped` | (loops) | (calls `/tracking` per row) | CSV columns: `receipt_id, tracking_code, carrier_name` |
| `etsy_issue_refund` | POST | `/application/shops/{shop_id}/receipts/{receipt_id}/refunds` | form: `amount` (cents), `reason` |
| Shipping profile list | GET | `/application/shops/{shop_id}/shipping-profiles` | — |
| Shipping profile create | POST | `/application/shops/{shop_id}/shipping-profiles` | form: title, origin_country_iso, primary_cost, secondary_cost, min_processing_time, max_processing_time, processing_time_unit, destination_country_iso? or destination_region |
| Shipping profile update | PATCH | `/application/shops/{shop_id}/shipping-profiles/{shipping_profile_id}` | form: any subset |
| Shop section list | GET | `/application/shops/{shop_id}/sections` | — |
| Shop section create | POST | `/application/shops/{shop_id}/sections` | form: `title` |
| Shop section update | PATCH | `/application/shops/{shop_id}/sections/{shop_section_id}` | form: `title` |
| Return policy list | GET | `/application/shops/{shop_id}/policies/return` | — |
| Return policy create | POST | `/application/shops/{shop_id}/policies/return` | form: `accepts_returns`, `accepts_exchanges`, `return_deadline` |
| Production partner list | GET | `/application/shops/{shop_id}/production-partners` | — |
| Production partner create | POST | `/application/shops/{shop_id}/production-partners` | form: `partner_name`, `location` |
| Bulk update prices | (loops) | (calls `/listings/{id}` PATCH per item) | uses Phase 1b `etsy_update_listing` |
| Bulk update quantities | (loops) | (calls `/listings/{id}/inventory` PUT per item) | uses Phase 1b `etsy_update_listing_inventory` |
| Listing renew | POST | `/application/listings/{listing_id}/renew` | — (renews expired listing) |

---

## Task 1: orders.py — etsy_mark_receipt_shipped

**Files:**
- Create: `etsy_mcp/orders.py`
- Create: `tests/unit/test_orders.py`

- [ ] **Step 1: Write the failing test**

Create `/Users/sumit/Desktop/Etsy MCP/tests/unit/test_orders.py`:

```python
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
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd "/Users/sumit/Desktop/Etsy MCP"
.venv/bin/pytest tests/unit/test_orders.py -v
```

Expected: FAIL — `cannot import name 'register_order_tools' from 'etsy_mcp.orders'`.

- [ ] **Step 3: Write the implementation**

Create `/Users/sumit/Desktop/Etsy MCP/etsy_mcp/orders.py`:

```python
"""Order/receipt write tools for Etsy MCP.

3 tools: mark_receipt_shipped, bulk_mark_shipped (CSV-driven), issue_refund.
Reads on receipts live in receipts.py (Phase 1a).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from .errors import EtsyMCPError, missing_shop_id_error
from .http import etsy_request


def register_order_tools(
    mcp: FastMCP,
    *,
    keystring: str,
    tokens_path: str | Path,
    shop_id_getter: Callable[[], str],
) -> dict[str, Callable]:
    """Register order-write tools on the given FastMCP instance."""

    @mcp.tool()
    async def etsy_mark_receipt_shipped(
        receipt_id: int,
        tracking_code: str,
        carrier_name: str,
        send_bcc: bool = False,
    ) -> dict[str, Any]:
        """Mark a receipt shipped with tracking info.

        Args:
            receipt_id: The receipt to mark.
            tracking_code: Carrier tracking number.
            carrier_name: Carrier slug (Etsy accepts: ups, usps, fedex, dhl,
                canada-post, royal-mail, australia-post, plus more — Etsy
                publishes the full list).
            send_bcc: If True, BCC yourself on the buyer notification.
        """
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()

        try:
            return await etsy_request(
                "POST",
                f"/application/shops/{shop_id}/receipts/{receipt_id}/tracking",
                keystring=keystring,
                tokens_path=str(tokens_path),
                data={
                    "tracking_code": tracking_code,
                    "carrier_name": carrier_name,
                    "send_bcc": "true" if send_bcc else "false",
                },
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

    return {"etsy_mark_receipt_shipped": etsy_mark_receipt_shipped}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/test_orders.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 111 passed (108 baseline + 3 new).

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/orders.py tests/unit/test_orders.py
git commit -m "$(cat <<'EOF'
feat(orders): etsy_mark_receipt_shipped

First Phase 2 tool — POST /shops/{shop_id}/receipts/{receipt_id}/tracking
with form-encoded tracking_code, carrier_name, send_bcc. Bool serialized
as 'true'/'false' string per Etsy convention. Returns Etsy's response
which contains {shipped, notification_sent} fields.

The new orders.py module hosts receipt-write tools (Phase 1a's
receipts.py is read-only).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: orders.py — etsy_bulk_mark_shipped (CSV-driven)

**Files:**
- Modify: `etsy_mcp/orders.py`
- Modify: `tests/unit/test_orders.py`

Reads a CSV with columns `receipt_id, tracking_code, carrier_name` and calls `etsy_mark_receipt_shipped` for each row. Returns a per-row success/failure report.

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_orders.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify failure**

```bash
.venv/bin/pytest tests/unit/test_orders.py::test_bulk_mark_shipped_processes_all_rows -v
```

Expected: FAIL — tool not registered.

- [ ] **Step 3: Add the tool**

In `etsy_mcp/orders.py`, INSIDE `register_order_tools` (after `etsy_mark_receipt_shipped`, before the return dict), add:

```python
    @mcp.tool()
    async def etsy_bulk_mark_shipped(csv_path: str) -> dict[str, Any]:
        """Mark many receipts shipped from a CSV file.

        CSV columns (header row required):
            receipt_id, tracking_code, carrier_name

        Each row is processed independently. Failures are recorded in the
        result; successful rows are still committed to Etsy.

        Returns:
            {
              "succeeded": int,
              "failed": [{"receipt_id": int, "error": str, "code": str}],
            }
        """
        import csv as _csv
        from pathlib import Path as _Path

        path = _Path(csv_path)
        if not path.is_file():
            return {
                "error": f"CSV file not found at {csv_path}",
                "code": "validation_failed",
            }

        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()

        with path.open("r", newline="") as f:
            reader = _csv.DictReader(f)
            required = {"receipt_id", "tracking_code", "carrier_name"}
            missing = required - set(reader.fieldnames or [])
            if missing:
                return {
                    "error": f"CSV missing required columns: {sorted(missing)}",
                    "code": "validation_failed",
                }
            rows = list(reader)

        succeeded = 0
        failed: list[dict[str, Any]] = []

        for row in rows:
            try:
                receipt_id = int(row["receipt_id"])
            except (ValueError, TypeError):
                failed.append(
                    {
                        "receipt_id": row.get("receipt_id"),
                        "error": "receipt_id is not an integer",
                        "code": "validation_failed",
                    }
                )
                continue

            try:
                resp = await etsy_request(
                    "POST",
                    f"/application/shops/{shop_id}/receipts/{receipt_id}/tracking",
                    keystring=keystring,
                    tokens_path=str(tokens_path),
                    data={
                        "tracking_code": row["tracking_code"],
                        "carrier_name": row["carrier_name"],
                        "send_bcc": "false",
                    },
                )
                if isinstance(resp, dict) and resp.get("error"):
                    failed.append(
                        {
                            "receipt_id": receipt_id,
                            "error": resp["error"],
                            "code": resp.get("code", "unknown"),
                        }
                    )
                else:
                    succeeded += 1
            except EtsyMCPError as exc:
                failed.append(
                    {
                        "receipt_id": receipt_id,
                        "error": exc.message,
                        "code": exc.code.value,
                    }
                )

        return {"succeeded": succeeded, "failed": failed}
```

UPDATE the return dict at the bottom of `register_order_tools`:

```python
    return {
        "etsy_mark_receipt_shipped": etsy_mark_receipt_shipped,
        "etsy_bulk_mark_shipped": etsy_bulk_mark_shipped,
    }
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_orders.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 115 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/orders.py tests/unit/test_orders.py
git commit -m "$(cat <<'EOF'
feat(orders): etsy_bulk_mark_shipped (CSV-driven)

Reads a CSV with columns receipt_id, tracking_code, carrier_name and
calls /receipts/{id}/tracking for each row. Failures (non-integer
receipt_id, 404, network errors) are collected per-row rather than
short-circuiting the batch — successful rows are still committed.

Pre-flight checks: file exists, header has the 3 required columns.
Returns {succeeded: int, failed: [{receipt_id, error, code}]}.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: orders.py — etsy_issue_refund (with confirm guard)

**Files:**
- Modify: `etsy_mcp/orders.py`
- Modify: `tests/unit/test_orders.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_orders.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify failure**

```bash
.venv/bin/pytest tests/unit/test_orders.py::test_issue_refund_without_confirm_refuses -v
```

Expected: FAIL.

- [ ] **Step 3: Add the tool**

INSIDE `register_order_tools` (after `etsy_bulk_mark_shipped`, before the return), add:

```python
    @mcp.tool()
    async def etsy_issue_refund(
        receipt_id: int,
        amount_cents: int,
        reason: str,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Issue a refund on a receipt. Requires confirm=True (real money).

        Args:
            receipt_id: The receipt to refund.
            amount_cents: Refund amount in the shop's currency, in cents
                (e.g. 1500 for $15.00). Must be positive.
            reason: Free-text reason. Visible in the seller dashboard.
            confirm: Must be True. Prevents accidental refunds.

        Note: Etsy's refund endpoint may reject the request depending on
        payment method (Etsy Payments only) and order status. Errors
        propagate as the structured error dict from the API response.
        """
        if not confirm:
            return {
                "error": (
                    f"Refusing to issue refund of {amount_cents} cents on receipt "
                    f"{receipt_id} without confirm=True. This moves real money."
                ),
                "code": "validation_failed",
            }
        if amount_cents <= 0:
            return {
                "error": "amount_cents must be > 0.",
                "code": "validation_failed",
            }

        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()

        try:
            return await etsy_request(
                "POST",
                f"/application/shops/{shop_id}/receipts/{receipt_id}/refunds",
                keystring=keystring,
                tokens_path=str(tokens_path),
                data={
                    "amount": amount_cents,
                    "reason": reason,
                },
            )
        except EtsyMCPError as exc:
            return exc.to_dict()
```

UPDATE the return dict to include `etsy_issue_refund`.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_orders.py -v
```

Expected: 11 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 119 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/orders.py tests/unit/test_orders.py
git commit -m "$(cat <<'EOF'
feat(orders): etsy_issue_refund (with confirm guard)

Maps to POST /shops/{shop_id}/receipts/{receipt_id}/refunds. Triple-
guarded — confirm=True required (real money), amount_cents must be
positive, shop_id must be set. Etsy's API may reject depending on
payment method (Etsy Payments only) and order state — those errors
surface as the standard structured-error dict.

Orders module now has 3 tools — all of Phase 2's order-ops surface.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: shop_config.py — shipping profiles (list/create/update)

**Files:**
- Create: `etsy_mcp/shop_config.py`
- Create: `tests/unit/test_shop_config.py`

- [ ] **Step 1: Write the failing tests**

Create `/Users/sumit/Desktop/Etsy MCP/tests/unit/test_shop_config.py`:

```python
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
```

- [ ] **Step 2: Run test to verify failure**

```bash
.venv/bin/pytest tests/unit/test_shop_config.py -v
```

Expected: FAIL — `cannot import name 'register_shop_config_tools'`.

- [ ] **Step 3: Write the implementation**

Create `/Users/sumit/Desktop/Etsy MCP/etsy_mcp/shop_config.py`:

```python
"""Shop config tools for Etsy MCP.

Four resource families share this module because they're all shop-level
configuration and are typically managed together (creating a listing
needs a shipping profile + return policy):

- Shipping profiles (list/create/update)
- Shop sections (list/create/update)
- Return policies (list/create)
- Production partners (list/create)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from .errors import EtsyMCPError, missing_shop_id_error
from .http import etsy_request


def register_shop_config_tools(
    mcp: FastMCP,
    *,
    keystring: str,
    tokens_path: str | Path,
    shop_id_getter: Callable[[], str],
) -> dict[str, Callable]:
    """Register shop-config tools on the given FastMCP instance."""

    @mcp.tool()
    async def etsy_list_shipping_profiles() -> dict[str, Any]:
        """List your shop's shipping profiles."""
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()
        try:
            return await etsy_request(
                "GET",
                f"/application/shops/{shop_id}/shipping-profiles",
                keystring=keystring,
                tokens_path=str(tokens_path),
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

    @mcp.tool()
    async def etsy_create_shipping_profile(
        title: str,
        origin_country_iso: str,
        primary_cost_cents: int,
        secondary_cost_cents: int,
        min_processing_days: int,
        max_processing_days: int,
        destination_country_iso: str | None = None,
        destination_region: str | None = None,
    ) -> dict[str, Any]:
        """Create a new shipping profile.

        Args:
            title: Display name for the profile.
            origin_country_iso: ISO country code where you ship from (e.g. "US").
            primary_cost_cents: Base shipping cost in cents.
            secondary_cost_cents: Each-additional-item cost in cents.
            min_processing_days: Min days to process before shipping.
            max_processing_days: Max days to process before shipping.
            destination_country_iso: Specific destination country, or
                pass destination_region instead for a regional profile.
            destination_region: One of {europe_union, none} for region-based
                profiles. Provide either this or destination_country_iso.
        """
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()
        if not destination_country_iso and not destination_region:
            return {
                "error": "Either destination_country_iso or destination_region is required.",
                "code": "validation_failed",
            }

        data: dict[str, Any] = {
            "title": title,
            "origin_country_iso": origin_country_iso,
            "primary_cost": primary_cost_cents,
            "secondary_cost": secondary_cost_cents,
            "min_processing_time": min_processing_days,
            "max_processing_time": max_processing_days,
            "processing_time_unit": "business_days",
        }
        if destination_country_iso:
            data["destination_country_iso"] = destination_country_iso
        if destination_region:
            data["destination_region"] = destination_region

        try:
            return await etsy_request(
                "POST",
                f"/application/shops/{shop_id}/shipping-profiles",
                keystring=keystring,
                tokens_path=str(tokens_path),
                data=data,
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

    @mcp.tool()
    async def etsy_update_shipping_profile(
        shipping_profile_id: int,
        title: str | None = None,
        primary_cost_cents: int | None = None,
        secondary_cost_cents: int | None = None,
        min_processing_days: int | None = None,
        max_processing_days: int | None = None,
    ) -> dict[str, Any]:
        """Partial update of a shipping profile (PATCH)."""
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()

        data: dict[str, Any] = {}
        if title is not None:
            data["title"] = title
        if primary_cost_cents is not None:
            data["primary_cost"] = primary_cost_cents
        if secondary_cost_cents is not None:
            data["secondary_cost"] = secondary_cost_cents
        if min_processing_days is not None:
            data["min_processing_time"] = min_processing_days
        if max_processing_days is not None:
            data["max_processing_time"] = max_processing_days

        if not data:
            return {
                "error": "No fields provided to update.",
                "code": "validation_failed",
            }

        try:
            return await etsy_request(
                "PATCH",
                f"/application/shops/{shop_id}/shipping-profiles/{shipping_profile_id}",
                keystring=keystring,
                tokens_path=str(tokens_path),
                data=data,
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

    return {
        "etsy_list_shipping_profiles": etsy_list_shipping_profiles,
        "etsy_create_shipping_profile": etsy_create_shipping_profile,
        "etsy_update_shipping_profile": etsy_update_shipping_profile,
    }
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_shop_config.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 123 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/shop_config.py tests/unit/test_shop_config.py
git commit -m "$(cat <<'EOF'
feat(shop_config): shipping profile list/create/update

First Phase 2 shop-config module. Three tools:
- list: GET /shops/{shop_id}/shipping-profiles
- create: POST same path with form-encoded title, origin_country_iso,
  primary_cost (cents), secondary_cost (cents), min/max_processing_time,
  processing_time_unit='business_days', and either
  destination_country_iso or destination_region (mutually-exclusive
  with a structured-error guard if both missing)
- update: PATCH /shipping-profiles/{id} with only the fields the
  caller passes; refuses no-op calls

Costs are exposed to the caller as integer cents (per project
convention) and sent to Etsy as 'primary_cost'/'secondary_cost' as
cents — matching Etsy's int-cents amount field convention.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: shop_config.py — shop sections (list/create/update)

**Files:**
- Modify: `etsy_mcp/shop_config.py`
- Modify: `tests/unit/test_shop_config.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_shop_config.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify failure**

```bash
.venv/bin/pytest tests/unit/test_shop_config.py::test_list_shop_sections -v
```

Expected: FAIL — tool not registered.

- [ ] **Step 3: Add the tools**

INSIDE `register_shop_config_tools` (after `etsy_update_shipping_profile`, before the return), add:

```python
    @mcp.tool()
    async def etsy_list_shop_sections() -> dict[str, Any]:
        """List your shop's sections (used to organize listings on your shop page)."""
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()
        try:
            return await etsy_request(
                "GET",
                f"/application/shops/{shop_id}/sections",
                keystring=keystring,
                tokens_path=str(tokens_path),
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

    @mcp.tool()
    async def etsy_create_shop_section(title: str) -> dict[str, Any]:
        """Create a new shop section (a category bucket on your shop page).

        Args:
            title: Display name (max 24 chars per Etsy).
        """
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()
        try:
            return await etsy_request(
                "POST",
                f"/application/shops/{shop_id}/sections",
                keystring=keystring,
                tokens_path=str(tokens_path),
                data={"title": title},
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

    @mcp.tool()
    async def etsy_update_shop_section(
        shop_section_id: int,
        title: str,
    ) -> dict[str, Any]:
        """Rename a shop section."""
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()
        try:
            return await etsy_request(
                "PATCH",
                f"/application/shops/{shop_id}/sections/{shop_section_id}",
                keystring=keystring,
                tokens_path=str(tokens_path),
                data={"title": title},
            )
        except EtsyMCPError as exc:
            return exc.to_dict()
```

UPDATE the return dict:

```python
    return {
        "etsy_list_shipping_profiles": etsy_list_shipping_profiles,
        "etsy_create_shipping_profile": etsy_create_shipping_profile,
        "etsy_update_shipping_profile": etsy_update_shipping_profile,
        "etsy_list_shop_sections": etsy_list_shop_sections,
        "etsy_create_shop_section": etsy_create_shop_section,
        "etsy_update_shop_section": etsy_update_shop_section,
    }
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_shop_config.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 126 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/shop_config.py tests/unit/test_shop_config.py
git commit -m "$(cat <<'EOF'
feat(shop_config): shop section list/create/update

Three section tools mapping to /shops/{shop_id}/sections. Used for
organizing listings on your shop's storefront page (e.g. "Outdoor
Cushions", "Bench Pads"). Title only — Etsy's section model has
no other editable fields.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: shop_config.py — return policies (list/create)

**Files:**
- Modify: `etsy_mcp/shop_config.py`
- Modify: `tests/unit/test_shop_config.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_shop_config.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify failure**

```bash
.venv/bin/pytest tests/unit/test_shop_config.py::test_list_return_policies -v
```

Expected: FAIL.

- [ ] **Step 3: Add the tools**

INSIDE `register_shop_config_tools` (after `etsy_update_shop_section`, before the return), add:

```python
    @mcp.tool()
    async def etsy_list_return_policies() -> dict[str, Any]:
        """List your shop's return policies."""
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()
        try:
            return await etsy_request(
                "GET",
                f"/application/shops/{shop_id}/policies/return",
                keystring=keystring,
                tokens_path=str(tokens_path),
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

    @mcp.tool()
    async def etsy_create_return_policy(
        accepts_returns: bool,
        accepts_exchanges: bool,
        return_deadline_days: int,
    ) -> dict[str, Any]:
        """Create a new return policy.

        Args:
            accepts_returns: Whether returns are accepted.
            accepts_exchanges: Whether exchanges are accepted.
            return_deadline_days: How many days the buyer has to start a
                return. Etsy accepts: 7, 14, 21, 30, 45, 60, 90.
        """
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()
        try:
            return await etsy_request(
                "POST",
                f"/application/shops/{shop_id}/policies/return",
                keystring=keystring,
                tokens_path=str(tokens_path),
                data={
                    "accepts_returns": "true" if accepts_returns else "false",
                    "accepts_exchanges": "true" if accepts_exchanges else "false",
                    "return_deadline": return_deadline_days,
                },
            )
        except EtsyMCPError as exc:
            return exc.to_dict()
```

UPDATE the return dict to include `etsy_list_return_policies` and `etsy_create_return_policy`.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_shop_config.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 128 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/shop_config.py tests/unit/test_shop_config.py
git commit -m "$(cat <<'EOF'
feat(shop_config): return policy list/create

Two tools mapping to /shops/{shop_id}/policies/return. Used to define
the buyer-facing return rules a listing references via
return_policy_id (Phase 1b create_draft_listing parameter).

Etsy v3 doesn't expose update or delete for return policies — sellers
deprecate by creating a new policy and updating listings to reference
it.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: shop_config.py — production partners (list/create)

**Files:**
- Modify: `etsy_mcp/shop_config.py`
- Modify: `tests/unit/test_shop_config.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_shop_config.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify failure**

```bash
.venv/bin/pytest tests/unit/test_shop_config.py::test_list_production_partners -v
```

Expected: FAIL.

- [ ] **Step 3: Add the tools**

INSIDE `register_shop_config_tools` (after `etsy_create_return_policy`, before the return), add:

```python
    @mcp.tool()
    async def etsy_list_production_partners() -> dict[str, Any]:
        """List your shop's declared production partners (third-party
        manufacturers)."""
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()
        try:
            return await etsy_request(
                "GET",
                f"/application/shops/{shop_id}/production-partners",
                keystring=keystring,
                tokens_path=str(tokens_path),
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

    @mcp.tool()
    async def etsy_create_production_partner(
        partner_name: str,
        location: str,
    ) -> dict[str, Any]:
        """Declare a third-party production partner (required by Etsy if any
        of your listings are made by someone other than you).

        Args:
            partner_name: Name of the manufacturer.
            location: Country or region (free text).
        """
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()
        try:
            return await etsy_request(
                "POST",
                f"/application/shops/{shop_id}/production-partners",
                keystring=keystring,
                tokens_path=str(tokens_path),
                data={"partner_name": partner_name, "location": location},
            )
        except EtsyMCPError as exc:
            return exc.to_dict()
```

UPDATE the return dict to include both new tools. Final dict has 10 tools.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_shop_config.py -v
```

Expected: 11 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 130 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/shop_config.py tests/unit/test_shop_config.py
git commit -m "$(cat <<'EOF'
feat(shop_config): production partner list/create

Two tools mapping to /shops/{shop_id}/production-partners. Etsy
requires sellers to declare third-party manufacturers when listings
are made by someone other than the seller (who_made='someone_else').

Shop config module now has 10 tools — all of Phase 2's shop-config
surface.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: bulk_ops.py — etsy_bulk_update_prices (with dry-run)

**Files:**
- Create: `etsy_mcp/bulk_ops.py`
- Create: `tests/unit/test_bulk_ops.py`

Mass-edit prices across many listings. Dry-run by default — `apply=True` opt-in to actually mutate.

- [ ] **Step 1: Write failing tests**

Create `/Users/sumit/Desktop/Etsy MCP/tests/unit/test_bulk_ops.py`:

```python
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
```

- [ ] **Step 2: Run test to verify failure**

```bash
.venv/bin/pytest tests/unit/test_bulk_ops.py -v
```

Expected: FAIL — `cannot import name 'register_bulk_ops_tools'`.

- [ ] **Step 3: Write the implementation**

Create `/Users/sumit/Desktop/Etsy MCP/etsy_mcp/bulk_ops.py`:

```python
"""Bulk write operations for Etsy MCP.

Three tools that coordinate many calls across listings. All mass-edit
tools default to apply=False (dry-run preview); the caller must pass
apply=True to actually mutate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from .errors import EtsyMCPError, missing_shop_id_error
from .http import etsy_request


def register_bulk_ops_tools(
    mcp: FastMCP,
    *,
    keystring: str,
    tokens_path: str | Path,
    shop_id_getter: Callable[[], str],
) -> dict[str, Callable]:
    """Register bulk-operation tools on the given FastMCP instance."""

    @mcp.tool()
    async def etsy_bulk_update_prices(
        updates: list[dict[str, Any]],
        apply: bool = False,
    ) -> dict[str, Any]:
        """Mass-update prices on many listings.

        Args:
            updates: List of {"listing_id": int, "price_usd": float} dicts.
            apply: Default False — returns a dry-run preview without
                hitting the API. Pass True to actually update.

        Returns (dry-run):
            {"dry_run": True, "count": int, "would_update": [...]}

        Returns (apply=True):
            {"dry_run": False, "updated": int,
             "failed": [{"listing_id": int, "error": str, "code": str}]}
        """
        if not updates:
            return {
                "error": "updates list is empty — pass at least one entry.",
                "code": "validation_failed",
            }

        if not apply:
            return {
                "dry_run": True,
                "count": len(updates),
                "would_update": list(updates),
            }

        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()

        updated = 0
        failed: list[dict[str, Any]] = []

        for upd in updates:
            try:
                listing_id = int(upd["listing_id"])
                price_usd = float(upd["price_usd"])
            except (KeyError, ValueError, TypeError) as exc:
                failed.append(
                    {
                        "listing_id": upd.get("listing_id"),
                        "error": f"Invalid update entry: {exc}",
                        "code": "validation_failed",
                    }
                )
                continue

            try:
                await etsy_request(
                    "PATCH",
                    f"/application/shops/{shop_id}/listings/{listing_id}",
                    keystring=keystring,
                    tokens_path=str(tokens_path),
                    data={"price": f"{price_usd:.2f}"},
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

    return {"etsy_bulk_update_prices": etsy_bulk_update_prices}
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_bulk_ops.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 134 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/bulk_ops.py tests/unit/test_bulk_ops.py
git commit -m "$(cat <<'EOF'
feat(bulk_ops): etsy_bulk_update_prices (dry-run by default)

Iterates a list of {listing_id, price_usd} dicts and calls
PATCH /shops/{shop_id}/listings/{listing_id} per entry. Defaults to
apply=False (dry-run): returns a {"dry_run": true, "count", "would_update"}
preview with no API calls. Pass apply=True to actually mutate.

Per-row failures (bad input, 404, network) collected in {"failed": [...]}
without short-circuiting the batch — typical use is repricing a few
hundred listings; one bad row shouldn't cancel the rest.

First Phase 2 bulk-ops tool, establishing the dry-run-by-default pattern.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: bulk_ops.py — etsy_bulk_update_quantities (with dry-run)

**Files:**
- Modify: `etsy_mcp/bulk_ops.py`
- Modify: `tests/unit/test_bulk_ops.py`

Note: quantity updates go through the listing-inventory PUT endpoint, not the listing PATCH. The Phase 1b pattern was: get current inventory, replace the offerings array. For Phase 2 we accept simple `{listing_id, sku, quantity}` triples and look up + update inventory in two calls per listing.

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_bulk_ops.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify failure**

```bash
.venv/bin/pytest tests/unit/test_bulk_ops.py::test_bulk_update_quantities_dry_run -v
```

Expected: FAIL.

- [ ] **Step 3: Add the tool**

INSIDE `register_bulk_ops_tools` (after `etsy_bulk_update_prices`, before the return), add:

```python
    @mcp.tool()
    async def etsy_bulk_update_quantities(
        updates: list[dict[str, Any]],
        apply: bool = False,
    ) -> dict[str, Any]:
        """Mass-update offering quantities on many listings, by SKU.

        Updates targeting the same listing_id are merged into a single
        PUT /inventory call so each listing is rewritten exactly once
        (Etsy's inventory PUT replaces the entire products array; calling
        it twice for the same listing would clobber the first update).

        Args:
            updates: List of {"listing_id": int, "sku": str, "quantity": int}.
            apply: Default False (dry-run). Pass True to actually update.

        Returns (dry-run): {"dry_run": True, "count": int}
        Returns (apply=True): {"dry_run": False, "updated": int,
                               "failed": [{"listing_id", "sku?", "error", "code"}]}
        """
        if not updates:
            return {
                "error": "updates list is empty — pass at least one entry.",
                "code": "validation_failed",
            }

        if not apply:
            return {"dry_run": True, "count": len(updates)}

        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()

        # Group updates by listing_id so each listing's inventory is rewritten once.
        by_listing: dict[int, dict[str, int]] = {}
        for upd in updates:
            try:
                listing_id = int(upd["listing_id"])
                sku = str(upd["sku"])
                qty = int(upd["quantity"])
            except (KeyError, ValueError, TypeError):
                continue
            by_listing.setdefault(listing_id, {})[sku] = qty

        updated = 0
        failed: list[dict[str, Any]] = []

        for listing_id, sku_to_qty in by_listing.items():
            # Fetch current inventory
            try:
                inv = await etsy_request(
                    "GET",
                    f"/application/listings/{listing_id}/inventory",
                    keystring=keystring,
                    tokens_path=str(tokens_path),
                )
            except EtsyMCPError as exc:
                for sku in sku_to_qty:
                    failed.append(
                        {
                            "listing_id": listing_id,
                            "sku": sku,
                            "error": exc.message,
                            "code": exc.code.value,
                        }
                    )
                continue

            if not isinstance(inv, dict) or "products" not in inv:
                for sku in sku_to_qty:
                    failed.append(
                        {
                            "listing_id": listing_id,
                            "sku": sku,
                            "error": "Etsy /inventory returned unexpected shape.",
                            "code": "unknown",
                        }
                    )
                continue

            # Mutate quantity on offerings whose product.sku matches
            products = inv["products"]
            applied_skus: set[str] = set()
            for product in products:
                product_sku = product.get("sku")
                if product_sku in sku_to_qty:
                    new_qty = sku_to_qty[product_sku]
                    for offering in product.get("offerings", []):
                        offering["quantity"] = new_qty
                    applied_skus.add(product_sku)

            # Skus that didn't match any product — flag as failures
            for sku in sku_to_qty:
                if sku not in applied_skus:
                    failed.append(
                        {
                            "listing_id": listing_id,
                            "sku": sku,
                            "error": f"SKU '{sku}' not found in listing inventory.",
                            "code": "not_found",
                        }
                    )

            if not applied_skus:
                continue  # Nothing to PUT for this listing.

            try:
                await etsy_request(
                    "PUT",
                    f"/application/listings/{listing_id}/inventory",
                    keystring=keystring,
                    tokens_path=str(tokens_path),
                    json_body={"products": products},
                )
                updated += len(applied_skus)
            except EtsyMCPError as exc:
                for sku in applied_skus:
                    failed.append(
                        {
                            "listing_id": listing_id,
                            "sku": sku,
                            "error": exc.message,
                            "code": exc.code.value,
                        }
                    )

        return {"dry_run": False, "updated": updated, "failed": failed}
```

UPDATE the return dict to include `etsy_bulk_update_quantities`.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_bulk_ops.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 137 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/bulk_ops.py tests/unit/test_bulk_ops.py
git commit -m "$(cat <<'EOF'
feat(bulk_ops): etsy_bulk_update_quantities

Mass-update offering quantities by SKU across many listings. Updates
for the same listing_id are merged into a single PUT /inventory so
the products array is rewritten once (Etsy's PUT replaces, not
patches — calling twice would clobber).

Implementation: group updates by listing → GET current inventory →
mutate matching SKUs' quantities → PUT back. Per-listing failures
(GET error, PUT error, SKU not in product list) recorded in
failed[]; successful SKUs counted in updated.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: bulk_ops.py — etsy_bulk_renew_listings (with confirm guard)

**Files:**
- Modify: `etsy_mcp/bulk_ops.py`
- Modify: `tests/unit/test_bulk_ops.py`

Etsy charges a small renewal fee per listing — confirm guard required to prevent accidental cost.

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_bulk_ops.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify failure**

```bash
.venv/bin/pytest tests/unit/test_bulk_ops.py::test_bulk_renew_listings_without_confirm_refuses -v
```

Expected: FAIL.

- [ ] **Step 3: Add the tool**

INSIDE `register_bulk_ops_tools` (after `etsy_bulk_update_quantities`, before the return), add:

```python
    @mcp.tool()
    async def etsy_bulk_renew_listings(
        listing_ids: list[int],
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Renew expired or expiring listings. Each renewal costs Etsy's
        per-listing fee — confirm=True required to prevent accidental cost.

        Args:
            listing_ids: List of listing ids to renew.
            confirm: Must be True. Etsy charges a fee per renewal.

        Returns:
            {"renewed": int, "failed": [{"listing_id", "error", "code"}]}
        """
        if not confirm:
            return {
                "error": (
                    f"Refusing to renew {len(listing_ids)} listings without "
                    "confirm=True. Each renewal costs Etsy's per-listing fee."
                ),
                "code": "validation_failed",
            }
        if not listing_ids:
            return {
                "error": "listing_ids list is empty — pass at least one id.",
                "code": "validation_failed",
            }

        renewed = 0
        failed: list[dict[str, Any]] = []

        for listing_id in listing_ids:
            try:
                await etsy_request(
                    "POST",
                    f"/application/listings/{listing_id}/renew",
                    keystring=keystring,
                    tokens_path=str(tokens_path),
                )
                renewed += 1
            except EtsyMCPError as exc:
                failed.append(
                    {
                        "listing_id": listing_id,
                        "error": exc.message,
                        "code": exc.code.value,
                    }
                )

        return {"renewed": renewed, "failed": failed}
```

UPDATE the return dict to include `etsy_bulk_renew_listings`. Final dict has 3 tools.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_bulk_ops.py -v
```

Expected: 11 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 141 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/bulk_ops.py tests/unit/test_bulk_ops.py
git commit -m "$(cat <<'EOF'
feat(bulk_ops): etsy_bulk_renew_listings (with confirm guard)

POST /listings/{listing_id}/renew per listing in a list. Each renewal
costs Etsy's per-listing fee, so confirm=True is required (the error
message explicitly cites the fee so an LLM can't blow through it
without acknowledging cost).

Per-listing failures (already-active 400, network) collected in
failed[] without short-circuiting. Bulk_ops module now has 3 tools
— all of Phase 2's bulk surface.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: server.py — register the 3 new factories

**Files:**
- Modify: `server.py`

- [ ] **Step 1: Add the imports**

Open `/Users/sumit/Desktop/Etsy MCP/server.py`. Find the existing import block:

```python
from etsy_mcp.browser import register_browser_tools
from etsy_mcp.exports import register_export_tools
from etsy_mcp.listings import register_listing_tools
from etsy_mcp.receipts import register_receipt_tools
from etsy_mcp.reviews import register_review_tools
from etsy_mcp.shop import register_shop_tools
from etsy_mcp.taxonomy import register_taxonomy_tools
```

REPLACE with (alphabetical, 3 new lines):

```python
from etsy_mcp.browser import register_browser_tools
from etsy_mcp.bulk_ops import register_bulk_ops_tools
from etsy_mcp.exports import register_export_tools
from etsy_mcp.listings import register_listing_tools
from etsy_mcp.orders import register_order_tools
from etsy_mcp.receipts import register_receipt_tools
from etsy_mcp.reviews import register_review_tools
from etsy_mcp.shop import register_shop_tools
from etsy_mcp.shop_config import register_shop_config_tools
from etsy_mcp.taxonomy import register_taxonomy_tools
```

- [ ] **Step 2: Add the register calls**

Find the existing register-calls block. The last call is currently:

```python
register_browser_tools(
    mcp,
    keystring=KEYSTRING,
    tokens_path=TOKENS_PATH,
    shop_id_getter=_shop_id,
)
```

APPEND immediately after it:

```python
register_order_tools(
    mcp,
    keystring=KEYSTRING,
    tokens_path=TOKENS_PATH,
    shop_id_getter=_shop_id,
)
register_shop_config_tools(
    mcp,
    keystring=KEYSTRING,
    tokens_path=TOKENS_PATH,
    shop_id_getter=_shop_id,
)
register_bulk_ops_tools(
    mcp,
    keystring=KEYSTRING,
    tokens_path=TOKENS_PATH,
    shop_id_getter=_shop_id,
)
```

- [ ] **Step 3: Verify imports**

```bash
cd "/Users/sumit/Desktop/Etsy MCP"
ETSY_KEYSTRING=test_placeholder .venv/bin/python -c "import server; print('OK')"
```

Expected: `OK`.

- [ ] **Step 4: Verify the server starts**

```bash
ETSY_KEYSTRING=test_placeholder timeout 3 .venv/bin/python server.py 2>&1 | head -20 || true
```

Expected: starts and waits for stdio. No traceback.

- [ ] **Step 5: Run full test suite**

```bash
.venv/bin/pytest -v 2>&1 | tail -3
```

Expected: 141 passed.

- [ ] **Step 6: Commit**

```bash
git add server.py
git commit -m "$(cat <<'EOF'
feat(server): wire up Phase 2 tools — orders, shop config, bulk ops

Adds three new register_* calls at module load. After this change the
FastMCP instance exposes all 45 tools across phases 0/1a/1b/1c/2:
- 29 from prior phases
- +3 from orders.py (mark_shipped, bulk_mark_shipped, issue_refund)
- +10 from shop_config.py (shipping profiles, sections, return
  policies, production partners — list/create/update where applicable)
- +3 from bulk_ops.py (bulk_update_prices, bulk_update_quantities,
  bulk_renew_listings — all dry-run-by-default or confirm-guarded)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Final verification

- [ ] **Step 1: Run the full test suite**

```bash
cd "/Users/sumit/Desktop/Etsy MCP"
.venv/bin/pytest -v 2>&1 | tail -3
```

Expected: 141 passed (33 new from Phase 2 on top of 108 from prior phases).

- [ ] **Step 2: Verify all 45 tools register on the FastMCP instance**

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
        # Phase 1c
        "etsy_ads_get_status", "etsy_ads_create_campaign", "etsy_ads_set_budget",
        "etsy_ads_pause", "etsy_ads_resume",
        "etsy_update_listing_images_order",
        # Phase 2 — orders
        "etsy_mark_receipt_shipped", "etsy_bulk_mark_shipped", "etsy_issue_refund",
        # Phase 2 — shop config
        "etsy_list_shipping_profiles", "etsy_create_shipping_profile", "etsy_update_shipping_profile",
        "etsy_list_shop_sections", "etsy_create_shop_section", "etsy_update_shop_section",
        "etsy_list_return_policies", "etsy_create_return_policy",
        "etsy_list_production_partners", "etsy_create_production_partner",
        # Phase 2 — bulk ops
        "etsy_bulk_update_prices", "etsy_bulk_update_quantities", "etsy_bulk_renew_listings",
    ])
    print(f"registered count: {len(names)}")
    print(f"expected count:   {len(expected)}")
    assert names == expected, f"missing: {set(expected) - set(names)}; extra: {set(names) - set(expected)}"
    print("OK — all 45 tools registered")

asyncio.run(main())
PY
```

Expected: `OK — all 45 tools registered`.

- [ ] **Step 3: Confirm no secrets staged or in history**

```bash
git status --ignored | grep -E "\.env$|\.tokens\.json|logs/|\.storage_state" || true
git diff --staged
git log --all --full-history -- .env .tokens.json .storage_state.json
```

Expected: ignored files listed; no staged diff; no history of secrets. STOP if any leak.

- [ ] **Step 4: List local commits ahead of origin**

```bash
git log --oneline origin/main..HEAD
```

Expected: ~12 new commits (Tasks 1-11). Wait for the user to say "push" before running `git push origin main`.

- [ ] **Step 5: Phase 2 acceptance summary**

Phase 2 ships when:
1. ✓ `pytest` is green (141 passing).
2. ✓ All 45 tools registered.
3. (Manual, post-Etsy-approval) Mark a real receipt shipped via `etsy_mark_receipt_shipped`.
4. (Manual) Bulk update prices on 3 real listings via `etsy_bulk_update_prices(updates=[...], apply=True)`.

Items 1-2 are the bar for shipping the code.

---

## Spec coverage check (Phase 2 only)

| Spec § 5.2 requirement | Task |
|---|---|
| Order ops (3 tools) | Tasks 1, 2, 3 |
| Shop config — shipping profiles list/create/update | Task 4 |
| Shop config — shop sections list/create/update | Task 5 |
| Shop config — return policies list/create | Task 6 |
| Shop config — production partners list/create | Task 7 |
| Bulk inventory — bulk_update_prices | Task 8 |
| Bulk inventory — bulk_update_quantities | Task 9 |
| Bulk inventory — bulk_renew_listings | Task 10 |
| Confirm guard for issue_refund + bulk_renew_listings | Tasks 3 + 10 |
| Dry-run-by-default for bulk_update_prices + bulk_update_quantities | Tasks 8 + 9 |
| Tools wrap EtsyMCPError → structured error dict | Every task |

**Out of scope for Phase 2 (Phase 3+):**
- Listing duplicate / templates (Tier 3)
- Sales / coupons (Tier 3 — browser)
- Reporting (Tier 3 — derived from receipts)
- Listing image reorder (already done in Phase 1c)
