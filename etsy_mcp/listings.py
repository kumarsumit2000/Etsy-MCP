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

    return {
        "etsy_list_listings": etsy_list_listings,
        "etsy_search_listings": etsy_search_listings,
    }
