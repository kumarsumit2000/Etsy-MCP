"""Order/receipt write tools for Etsy MCP.

3 tools: mark_receipt_shipped, bulk_mark_shipped (CSV-driven), issue_refund.
Reads on receipts live in receipts.py (Phase 1a).
"""

from __future__ import annotations

import csv as _csv
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
        path = Path(csv_path)
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

    return {
        "etsy_mark_receipt_shipped": etsy_mark_receipt_shipped,
        "etsy_bulk_mark_shipped": etsy_bulk_mark_shipped,
        "etsy_issue_refund": etsy_issue_refund,
    }
