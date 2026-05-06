"""Bulk export tools for Etsy MCP.

Exports listings, receipts, and reviews to JSON and/or CSV. JSON is the raw
API response (a flat list of dicts). CSV is one row per resource with nested
fields dot-joined (e.g. price.amount, price.currency_code) and lists JSON-encoded.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from .errors import EtsyMCPError, missing_shop_id_error
from .http import paginate_all


def _flatten_dict(d: dict[str, Any], parent_key: str = "", sep: str = ".") -> dict[str, Any]:
    """Flatten nested dicts using dot-joined keys. Lists are JSON-encoded as
    strings. Nones become empty strings (CSV-safe)."""
    items: dict[str, Any] = {}
    for k, v in d.items():
        key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.update(_flatten_dict(v, key, sep))
        elif isinstance(v, list):
            items[key] = json.dumps(v)
        elif v is None:
            items[key] = ""
        else:
            items[key] = v
    return items


def _write_json(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(rows, indent=2, default=str))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("")
        return
    flat_rows = [_flatten_dict(r) for r in rows]
    # Union of all keys preserves any field that appears in at least one row.
    headers: list[str] = []
    seen: set[str] = set()
    for r in flat_rows:
        for k in r.keys():
            if k not in seen:
                seen.add(k)
                headers.append(k)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for r in flat_rows:
            writer.writerow(r)


def _write_outputs(
    rows: list[dict[str, Any]],
    output_dir: Path,
    base_name: str,
    fmt: str,
) -> list[str]:
    """Write JSON and/or CSV based on fmt. Returns list of file paths written."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    if fmt in ("json", "both"):
        json_path = output_dir / f"{base_name}.json"
        _write_json(json_path, rows)
        written.append(str(json_path))
    if fmt in ("csv", "both"):
        csv_path = output_dir / f"{base_name}.csv"
        _write_csv(csv_path, rows)
        written.append(str(csv_path))
    return written


def register_export_tools(
    mcp: FastMCP,
    *,
    keystring: str,
    tokens_path: str | Path,
    shop_id_getter: Callable[[], str],
) -> dict[str, Callable]:
    """Register bulk-export tools on the given FastMCP instance."""

    @mcp.tool()
    async def etsy_export_all_listings(
        output_dir: str,
        format: str = "both",
        state: str = "active",
    ) -> dict[str, Any]:
        """Paginate every listing in your shop (in the given state) and write
        to JSON and/or CSV files in output_dir.

        Args:
            output_dir: Directory to write output files into. Created if missing.
            format: 'json', 'csv', or 'both'. Default 'both'.
            state: Listing state filter. Default 'active'. Etsy doesn't expose
                an 'all states' query, so to export inactive/draft/expired/sold_out
                you call this tool once per state.
        """
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()
        if format not in ("json", "csv", "both"):
            return {"error": f"Invalid format '{format}'. Use json, csv, or both.", "code": "validation_failed"}

        try:
            rows = await paginate_all(
                "GET",
                f"/application/shops/{shop_id}/listings",
                keystring=keystring,
                tokens_path=str(tokens_path),
                params={"state": state},
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

        files = _write_outputs(rows, Path(output_dir), "listings", format)
        return {"listings_count": len(rows), "files": files}

    @mcp.tool()
    async def etsy_export_all_receipts(
        output_dir: str,
        format: str = "both",
        since: str | None = None,
    ) -> dict[str, Any]:
        """Paginate every receipt in your shop (optionally since an ISO date)
        and write to JSON and/or CSV.

        Args:
            output_dir: Directory to write output files into.
            format: 'json', 'csv', or 'both'. Default 'both'.
            since: ISO date string (YYYY-MM-DD) — only receipts created on or
                after this date. Converted to unix timestamp for Etsy's
                min_created filter.
        """
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()
        if format not in ("json", "csv", "both"):
            return {"error": f"Invalid format '{format}'. Use json, csv, or both.", "code": "validation_failed"}

        params: dict[str, Any] = {}
        if since is not None:
            from .timeutil import parse_local_date
            dt = parse_local_date(since)
            if dt is None:
                return {
                    "error": f"Invalid since='{since}'. Use ISO date format YYYY-MM-DD.",
                    "code": "validation_failed",
                }
            params["min_created"] = int(dt.timestamp())

        try:
            rows = await paginate_all(
                "GET",
                f"/application/shops/{shop_id}/receipts",
                keystring=keystring,
                tokens_path=str(tokens_path),
                params=params,
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

        files = _write_outputs(rows, Path(output_dir), "receipts", format)
        return {"receipts_count": len(rows), "files": files}

    @mcp.tool()
    async def etsy_export_all_reviews(
        output_dir: str,
        format: str = "both",
    ) -> dict[str, Any]:
        """Paginate every review in your shop and write to JSON and/or CSV.

        Args:
            output_dir: Directory to write output files into.
            format: 'json', 'csv', or 'both'. Default 'both'.
        """
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()
        if format not in ("json", "csv", "both"):
            return {"error": f"Invalid format '{format}'. Use json, csv, or both.", "code": "validation_failed"}

        try:
            rows = await paginate_all(
                "GET",
                f"/application/shops/{shop_id}/reviews",
                keystring=keystring,
                tokens_path=str(tokens_path),
                params={},
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

        files = _write_outputs(rows, Path(output_dir), "reviews", format)
        return {"reviews_count": len(rows), "files": files}

    return {
        "etsy_export_all_listings": etsy_export_all_listings,
        "etsy_export_all_receipts": etsy_export_all_receipts,
        "etsy_export_all_reviews": etsy_export_all_reviews,
    }
