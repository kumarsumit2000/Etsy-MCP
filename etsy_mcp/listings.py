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

    return {
        "etsy_list_listings": etsy_list_listings,
        "etsy_search_listings": etsy_search_listings,
        "etsy_get_listing": etsy_get_listing,
        "etsy_get_listing_inventory": etsy_get_listing_inventory,
        "etsy_get_listing_images": etsy_get_listing_images,
        "etsy_create_draft_listing": etsy_create_draft_listing,
    }
