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
