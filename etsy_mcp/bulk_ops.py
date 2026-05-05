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

    return {
        "etsy_bulk_update_prices": etsy_bulk_update_prices,
        "etsy_bulk_update_quantities": etsy_bulk_update_quantities,
        "etsy_bulk_renew_listings": etsy_bulk_renew_listings,
    }
