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

    return {
        "etsy_list_receipts": etsy_list_receipts,
        "etsy_get_receipt": etsy_get_receipt,
        "etsy_get_receipt_transactions": etsy_get_receipt_transactions,
        "etsy_list_shop_payments": etsy_list_shop_payments,
    }
