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

    return {
        "etsy_list_shipping_profiles": etsy_list_shipping_profiles,
        "etsy_create_shipping_profile": etsy_create_shipping_profile,
        "etsy_update_shipping_profile": etsy_update_shipping_profile,
        "etsy_list_shop_sections": etsy_list_shop_sections,
        "etsy_create_shop_section": etsy_create_shop_section,
        "etsy_update_shop_section": etsy_update_shop_section,
        "etsy_list_return_policies": etsy_list_return_policies,
        "etsy_create_return_policy": etsy_create_return_policy,
        "etsy_list_production_partners": etsy_list_production_partners,
        "etsy_create_production_partner": etsy_create_production_partner,
    }
