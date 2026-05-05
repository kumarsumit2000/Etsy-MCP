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
