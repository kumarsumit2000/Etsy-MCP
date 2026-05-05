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

    return {
        "etsy_get_shop": etsy_get_shop,
        "etsy_get_shop_stats": etsy_get_shop_stats,
    }
