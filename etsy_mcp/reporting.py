"""Reporting tools — derived from receipts.

Etsy doesn't expose pre-aggregated stats via API. These tools paginate
receipts in a date range and aggregate locally.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from .errors import EtsyMCPError, missing_shop_id_error
from .http import paginate_all


def _parse_iso(s: str) -> datetime | None:
    try:
        return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _grandtotal_cents(receipt: dict[str, Any]) -> int:
    gt = receipt.get("grandtotal") or {}
    amount = gt.get("amount", 0)
    divisor = gt.get("divisor", 1) or 1
    return int(amount * 100 / divisor)


def _period_key(ts: int, group_by: str) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    if group_by == "day":
        return dt.strftime("%Y-%m-%d")
    if group_by == "week":
        iso = dt.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    if group_by == "month":
        return dt.strftime("%Y-%m")
    return ""


def register_reporting_tools(
    mcp: FastMCP,
    *,
    keystring: str,
    tokens_path: str | Path,
    shop_id_getter: Callable[[], str],
) -> dict[str, Callable]:
    """Register reporting tools on the given FastMCP instance."""

    @mcp.tool()
    async def etsy_revenue_report(
        start: str,
        end: str,
        group_by: str = "day",
    ) -> Any:
        """Aggregate revenue from receipts in a date range.

        Args:
            start: ISO date YYYY-MM-DD (inclusive).
            end: ISO date YYYY-MM-DD (inclusive).
            group_by: 'day', 'week', or 'month'.

        Returns a list of {period, revenue_cents, orders, currency_code}
        sorted by period ascending. Returns a structured-error dict on
        validation failure.
        """
        if group_by not in ("day", "week", "month"):
            return {
                "error": "group_by must be one of: day, week, month.",
                "code": "validation_failed",
            }

        start_dt = _parse_iso(start)
        end_dt = _parse_iso(end)
        if start_dt is None or end_dt is None:
            return {
                "error": "start and end must be ISO date strings (YYYY-MM-DD).",
                "code": "validation_failed",
            }

        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()

        try:
            receipts = await paginate_all(
                "GET",
                f"/application/shops/{shop_id}/receipts",
                keystring=keystring,
                tokens_path=str(tokens_path),
                params={
                    "min_created": int(start_dt.timestamp()),
                    "max_created": int(end_dt.timestamp()) + 86400 - 1,
                },
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

        buckets: dict[str, dict[str, Any]] = {}
        currency_code: str | None = None

        for r in receipts:
            ts = r.get("create_timestamp")
            if not ts:
                continue
            key = _period_key(int(ts), group_by)
            cents = _grandtotal_cents(r)
            entry = buckets.setdefault(
                key, {"period": key, "revenue_cents": 0, "orders": 0}
            )
            entry["revenue_cents"] += cents
            entry["orders"] += 1
            if currency_code is None:
                gt = r.get("grandtotal") or {}
                currency_code = gt.get("currency_code")

        rows = sorted(buckets.values(), key=lambda r: r["period"])
        for r in rows:
            r["currency_code"] = currency_code or "USD"
        return rows

    @mcp.tool()
    async def etsy_top_listings_report(
        start: str,
        end: str,
        by: str = "revenue",
        limit: int = 20,
    ) -> Any:
        """Top listings by revenue or units sold in a date range.

        Args:
            start: ISO date YYYY-MM-DD (inclusive).
            end: ISO date YYYY-MM-DD (inclusive).
            by: 'revenue' or 'units'. ('views' is unsupported — Etsy v3
                doesn't expose per-listing view counts via API.)
            limit: Top N listings. Default 20.
        """
        if by not in ("revenue", "units"):
            return {
                "error": (
                    f"by='{by}' is not supported. Use 'revenue' or 'units'. "
                    "Per-listing 'views' data is not available via Etsy v3 API "
                    "— check the seller dashboard at "
                    "etsy.com/your/shops/me/stats."
                ),
                "code": "validation_failed",
            }

        start_dt = _parse_iso(start)
        end_dt = _parse_iso(end)
        if start_dt is None or end_dt is None:
            return {
                "error": "start and end must be ISO date strings (YYYY-MM-DD).",
                "code": "validation_failed",
            }

        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()

        try:
            receipts = await paginate_all(
                "GET",
                f"/application/shops/{shop_id}/receipts",
                keystring=keystring,
                tokens_path=str(tokens_path),
                params={
                    "min_created": int(start_dt.timestamp()),
                    "max_created": int(end_dt.timestamp()) + 86400 - 1,
                    "includes": "Transactions",
                },
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

        agg: dict[int, dict[str, Any]] = {}
        for r in receipts:
            for tx in r.get("transactions") or []:
                lid = tx.get("listing_id")
                if lid is None:
                    continue
                qty = int(tx.get("quantity", 0))
                price = tx.get("price") or {}
                amount = price.get("amount", 0)
                divisor = price.get("divisor", 1) or 1
                line_cents = int(amount * 100 / divisor) * qty
                entry = agg.setdefault(
                    lid,
                    {
                        "listing_id": lid,
                        "title": tx.get("title"),
                        "revenue_cents": 0,
                        "units": 0,
                    },
                )
                entry["revenue_cents"] += line_cents
                entry["units"] += qty

        rows = list(agg.values())
        sort_key = "revenue_cents" if by == "revenue" else "units"
        rows.sort(key=lambda r: r[sort_key], reverse=True)
        return rows[:limit]

    return {
        "etsy_revenue_report": etsy_revenue_report,
        "etsy_top_listings_report": etsy_top_listings_report,
    }
