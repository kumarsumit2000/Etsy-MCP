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
        try:
            return await etsy_request(
                "GET",
                f"/application/listings/{listing_id}/images",
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

    @mcp.tool()
    async def etsy_update_listing(
        listing_id: int,
        title: str | None = None,
        description: str | None = None,
        price_usd: float | None = None,
        quantity: int | None = None,
        state: str | None = None,
        tags: list[str] | None = None,
        materials: list[str] | None = None,
        taxonomy_id: int | None = None,
        return_policy_id: int | None = None,
        shipping_profile_id: int | None = None,
    ) -> dict[str, Any]:
        """Partial update of a listing. Only fields you pass are sent (PATCH).

        Args:
            listing_id: The listing to update.
            title: New title.
            description: New description.
            price_usd: New price (shop currency).
            quantity: New quantity.
            state: One of {active, inactive, draft}. Used to publish a draft or unlist.
            tags: Replace tag set. Up to 13.
            materials: Replace material set. Up to 13.
            taxonomy_id: Move to a different category.
            return_policy_id: Change return policy.
            shipping_profile_id: Change shipping profile.
        """
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()

        data: dict[str, Any] = {}
        if title is not None:
            data["title"] = title
        if description is not None:
            data["description"] = description
        if price_usd is not None:
            data["price"] = f"{price_usd:.2f}"
        if quantity is not None:
            data["quantity"] = quantity
        if state is not None:
            data["state"] = state
        if tags is not None:
            data["tags"] = tags
        if materials is not None:
            data["materials"] = materials
        if taxonomy_id is not None:
            data["taxonomy_id"] = taxonomy_id
        if return_policy_id is not None:
            data["return_policy_id"] = return_policy_id
        if shipping_profile_id is not None:
            data["shipping_profile_id"] = shipping_profile_id

        if not data:
            return {
                "error": "No fields provided to update.",
                "code": "validation_failed",
            }

        try:
            return await etsy_request(
                "PATCH",
                f"/application/shops/{shop_id}/listings/{listing_id}",
                keystring=keystring,
                tokens_path=str(tokens_path),
                data=data,
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

    @mcp.tool()
    async def etsy_delete_listing(
        listing_id: int,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Delete a listing permanently. Requires confirm=True as a safety guard.

        Etsy's delete endpoint is shop-agnostic, so this does not need
        ETSY_SHOP_ID — but the listing must belong to your shop or Etsy
        rejects with 403/404.
        """
        if not confirm:
            return {
                "error": (
                    f"Refusing to delete listing {listing_id} without confirm=True. "
                    "This action is permanent."
                ),
                "code": "validation_failed",
            }

        try:
            await etsy_request(
                "DELETE",
                f"/application/listings/{listing_id}",
                keystring=keystring,
                tokens_path=str(tokens_path),
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

        return {"deleted": True, "listing_id": listing_id}

    @mcp.tool()
    async def etsy_upload_listing_image(
        listing_id: int,
        image_path: str,
        rank: int = 1,
        alt_text: str | None = None,
    ) -> dict[str, Any]:
        """Upload an image to a listing. Reads the file from disk.

        Args:
            listing_id: The listing to attach the image to.
            image_path: Absolute or relative filesystem path to a .jpg/.png/.gif.
            rank: Display order (1 = first). Default 1.
            alt_text: Accessibility text. Optional but recommended.
        """
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()

        path_obj = Path(image_path)
        if not path_obj.is_file():
            return {
                "error": f"Image file not found at {image_path}",
                "code": "validation_failed",
            }

        try:
            with path_obj.open("rb") as f:
                file_bytes = f.read()
            files = {"image": (path_obj.name, file_bytes, "application/octet-stream")}
            data: dict[str, Any] = {"rank": rank}
            if alt_text is not None:
                data["alt_text"] = alt_text

            return await etsy_request(
                "POST",
                f"/application/shops/{shop_id}/listings/{listing_id}/images",
                keystring=keystring,
                tokens_path=str(tokens_path),
                files=files,
                data=data,
            )
        except EtsyMCPError as exc:
            return exc.to_dict()
        except OSError as exc:
            return {
                "error": f"Could not read image file: {exc}",
                "code": "validation_failed",
            }

    @mcp.tool()
    async def etsy_update_listing_inventory(
        listing_id: int,
        products: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Replace the listing's inventory products array.

        Args:
            listing_id: The listing whose inventory you're updating.
            products: List of product dicts. Each is:
                {
                  "sku": str,
                  "offerings": [{"price": float, "quantity": int, "is_enabled": bool}],
                  "property_values": [...]   # optional, for variants
                }
        """
        if not products:
            return {
                "error": "products list is empty — pass at least one product entry.",
                "code": "validation_failed",
            }

        try:
            return await etsy_request(
                "PUT",
                f"/application/listings/{listing_id}/inventory",
                keystring=keystring,
                tokens_path=str(tokens_path),
                json_body={"products": products},
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

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

    return {
        "etsy_list_listings": etsy_list_listings,
        "etsy_search_listings": etsy_search_listings,
        "etsy_get_listing": etsy_get_listing,
        "etsy_get_listing_inventory": etsy_get_listing_inventory,
        "etsy_get_listing_images": etsy_get_listing_images,
        "etsy_create_draft_listing": etsy_create_draft_listing,
        "etsy_update_listing": etsy_update_listing,
        "etsy_delete_listing": etsy_delete_listing,
        "etsy_upload_listing_image": etsy_upload_listing_image,
        "etsy_update_listing_inventory": etsy_update_listing_inventory,
        "etsy_save_listing_template": etsy_save_listing_template,
        "etsy_apply_listing_template": etsy_apply_listing_template,
        "etsy_duplicate_listing": etsy_duplicate_listing,
    }
