"""Receipt + payment read tools for Etsy MCP.

4 tools (all read-only). Phase 1b will add ship/refund/bulk-ship to this
same module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from .errors import EtsyMCPError, missing_shop_id_error
from .http import etsy_request, paginate_all
from .timeutil import shop_tz


def register_receipt_tools(
    mcp: FastMCP,
    *,
    keystring: str,
    tokens_path: str | Path,
    shop_id_getter: Callable[[], str],
) -> dict[str, Callable]:
    """Register receipt/payment tools on the given FastMCP instance."""

    @mcp.tool()
    async def etsy_list_receipts(
        was_paid: bool | None = None,
        was_shipped: bool | None = None,
        min_created: int | None = None,
        max_created: int | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List receipts (orders) for your shop.

        Args:
            was_paid: Filter by payment status. None means no filter.
            was_shipped: Filter by ship status. None means no filter.
            min_created: Unix timestamp (seconds) — only receipts created at or after.
            max_created: Unix timestamp (seconds) — only receipts created at or before.
            limit: Max 100. Default 25.
            offset: For pagination.
        """
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()

        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if was_paid is not None:
            params["was_paid"] = "true" if was_paid else "false"
        if was_shipped is not None:
            params["was_shipped"] = "true" if was_shipped else "false"
        if min_created is not None:
            params["min_created"] = min_created
        if max_created is not None:
            params["max_created"] = max_created

        try:
            return await etsy_request(
                "GET",
                f"/application/shops/{shop_id}/receipts",
                keystring=keystring,
                tokens_path=str(tokens_path),
                params=params,
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

    @mcp.tool()
    async def etsy_get_receipt(receipt_id: int) -> dict[str, Any]:
        """Return a single receipt (order) with buyer info, totals, and shipping."""
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()
        try:
            return await etsy_request(
                "GET",
                f"/application/shops/{shop_id}/receipts/{receipt_id}",
                keystring=keystring,
                tokens_path=str(tokens_path),
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

    @mcp.tool()
    async def etsy_get_receipt_transactions(receipt_id: int) -> dict[str, Any]:
        """Return the line items (transactions) for a receipt: SKU, title, quantity, price."""
        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()
        try:
            return await etsy_request(
                "GET",
                f"/application/shops/{shop_id}/receipts/{receipt_id}/transactions",
                keystring=keystring,
                tokens_path=str(tokens_path),
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

    @mcp.tool()
    async def etsy_list_shop_payments(
        min_created: int | None = None,
        max_created: int | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List your shop's payment ledger entries: charges, fees, credits, refunds.

        Maps to Etsy's getShopPaymentAccountLedgerEntries. For per-receipt
        payment status use etsy_get_receipt instead.
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
                f"/application/shops/{shop_id}/payment-account/ledger-entries",
                keystring=keystring,
                tokens_path=str(tokens_path),
                params=params,
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

    @mcp.tool()
    async def etsy_returns_summary(
        min_created: int | None = None,
        max_created: int | None = None,
        days: int = 30,
    ) -> dict[str, Any]:
        """Aggregate cancellations + refunds from receipts in a date range.

        Etsy's per-receipt status field (Paid / Completed / Canceled /
        Partially Refunded) and the receipt's `refunds[]` array contain
        the real return data. The legacy `was_canceled` / `total_refunded`
        fields on receipts are unreliable — they're often null even on
        cancelled orders. This tool aggregates the true picture.

        Args:
            min_created: Unix epoch start (inclusive). If None, computed
                from `days` (default last 30 days in shop tz).
            max_created: Unix epoch end (inclusive). If None, defaults to
                now.
            days: Lookback window when min_created is not set. Default 30.

        Returns:
            {
              "period": { "min_created": int, "max_created": int, "days": int },
              "total_receipts": int,
              "by_status": { "Paid": int, "Canceled": int, ... },
              "cancellation_rate_pct": float,
              "refund_count": int,
              "refund_total_usd": float,
              "refund_rate_pct": float,
              "reasons_grouped": { "<reason>": <count>, ... },
              "top_3_reasons": [{"reason": str, "count": int, "pct": float}, ...],
              "sample_refunds": [{receipt_id, name, reason, amount_usd, created_iso, note_excerpt}, ...]
            }
        """
        from datetime import datetime, timedelta

        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()

        if min_created is None or max_created is None:
            now_local = datetime.now(tz=shop_tz()).replace(hour=0, minute=0, second=0, microsecond=0)
            start = now_local - timedelta(days=days)
            end = now_local + timedelta(days=1) - timedelta(seconds=1)
            min_created = int(start.timestamp()) if min_created is None else min_created
            max_created = int(end.timestamp()) if max_created is None else max_created

        try:
            receipts = await paginate_all(
                "GET",
                f"/application/shops/{shop_id}/receipts",
                keystring=keystring,
                tokens_path=str(tokens_path),
                params={"min_created": min_created, "max_created": max_created},
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

        by_status: dict[str, int] = {}
        refund_count = 0
        refund_total_usd = 0.0
        reasons_grouped: dict[str, int] = {}
        sample_refunds: list[dict[str, Any]] = []

        for r in receipts:
            status = r.get("status") or "Unknown"
            by_status[status] = by_status.get(status, 0) + 1
            refunds = r.get("refunds") or []
            if not refunds:
                continue
            refund_count += 1
            for rf in refunds:
                amt = rf.get("amount") or {}
                usd = 0.0
                if isinstance(amt, dict) and amt.get("amount") is not None:
                    usd = amt["amount"] / max(amt.get("divisor", 1), 1)
                refund_total_usd += usd
                reason = rf.get("reason") or "(no reason given)"
                reasons_grouped[reason] = reasons_grouped.get(reason, 0) + 1
                if len(sample_refunds) < 10:
                    ts = rf.get("created_timestamp") or r.get("create_timestamp") or 0
                    note = rf.get("note_from_issuer") or ""
                    sample_refunds.append({
                        "receipt_id": r.get("receipt_id"),
                        "name": r.get("name"),
                        "reason": reason,
                        "amount_usd": round(usd, 2),
                        "created_iso": datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else None,
                        "note_excerpt": note[:120],
                    })

        total = len(receipts)
        cancelled = by_status.get("Canceled", 0) + by_status.get("Partially Refunded", 0)
        cancel_rate = (cancelled / total * 100) if total else 0.0
        refund_rate = (refund_count / total * 100) if total else 0.0

        # Top 3 reasons by count
        top_3 = sorted(reasons_grouped.items(), key=lambda kv: kv[1], reverse=True)[:3]
        total_refund_events = sum(reasons_grouped.values()) or 1
        top_3_struct = [
            {"reason": k, "count": v, "pct": round(v / total_refund_events * 100, 1)}
            for k, v in top_3
        ]

        return {
            "period": {
                "min_created": min_created,
                "max_created": max_created,
                "days": days,
            },
            "total_receipts": total,
            "by_status": by_status,
            "cancellation_rate_pct": round(cancel_rate, 2),
            "refund_count": refund_count,
            "refund_total_usd": round(refund_total_usd, 2),
            "refund_rate_pct": round(refund_rate, 2),
            "reasons_grouped": reasons_grouped,
            "top_3_reasons": top_3_struct,
            "sample_refunds": sample_refunds,
        }

    @mcp.tool()
    async def etsy_per_listing_return_rate(
        min_created: int | None = None,
        max_created: int | None = None,
        days: int = 30,
        min_orders: int = 2,
    ) -> dict[str, Any]:
        """Per-listing return / cancellation rate over a date range.

        Walks every receipt in the window with embedded transactions, then
        attributes each line-item to its listing_id. Computes:
          - total_orders per listing (line items, not unique receipts)
          - cancellations per listing (line items on Canceled or
            Partially Refunded receipts)
          - return_rate_pct = cancellations / total_orders

        Args:
            min_created / max_created: Unix epoch range. If None, uses
                the last `days` days in shop tz.
            days: lookback window when range is not given. Default 30.
            min_orders: drop listings with fewer than N orders to avoid
                noise from one-off cancels (1/1 = 100% would dominate).
                Default 2.

        Returns:
            {
              "period": {min_created, max_created, days},
              "min_orders_filter": int,
              "listing_count_total": int (after filter),
              "by_listing": [
                  {listing_id, title, total_orders, total_units,
                   cancellations, return_rate_pct, refunded_amount_usd},
                  ...
              ] sorted by return_rate_pct desc, then cancellations desc,
              "rolled_up": {total_orders, total_cancellations,
                            overall_return_rate_pct}
            }
        """
        from datetime import datetime, timedelta

        shop_id = shop_id_getter()
        if not shop_id:
            return missing_shop_id_error()

        if min_created is None or max_created is None:
            now_local = datetime.now(tz=shop_tz()).replace(hour=0, minute=0, second=0, microsecond=0)
            start = now_local - timedelta(days=days)
            end = now_local + timedelta(days=1) - timedelta(seconds=1)
            min_created = int(start.timestamp()) if min_created is None else min_created
            max_created = int(end.timestamp()) if max_created is None else max_created

        try:
            receipts = await paginate_all(
                "GET",
                f"/application/shops/{shop_id}/receipts",
                keystring=keystring,
                tokens_path=str(tokens_path),
                params={
                    "min_created": min_created,
                    "max_created": max_created,
                    "includes": "Transactions",
                },
            )
        except EtsyMCPError as exc:
            return exc.to_dict()

        # Build per-listing aggregates
        agg: dict[int, dict[str, Any]] = {}
        for r in receipts:
            status = r.get("status") or ""
            is_cancel = status in ("Canceled", "Partially Refunded")
            # Sum refund USD on this receipt for proportional attribution
            receipt_refund_usd = 0.0
            for rf in r.get("refunds") or []:
                amt = rf.get("amount") or {}
                if isinstance(amt, dict) and amt.get("amount") is not None:
                    receipt_refund_usd += amt["amount"] / max(amt.get("divisor", 1), 1)

            txs = r.get("transactions") or []
            for tx in txs:
                lid = tx.get("listing_id")
                if lid is None:
                    continue
                qty = int(tx.get("quantity") or 0)
                price = tx.get("price") or {}
                unit_usd = 0.0
                if isinstance(price, dict) and price.get("amount") is not None:
                    unit_usd = price["amount"] / max(price.get("divisor", 1), 1)
                line_usd = unit_usd * qty
                entry = agg.setdefault(
                    lid,
                    {
                        "listing_id": lid,
                        "title": tx.get("title") or "",
                        "total_orders": 0,
                        "total_units": 0,
                        "cancellations": 0,
                        "refunded_amount_usd": 0.0,
                        # transient: track total order_value for proportional refund split
                        "_gross_value": 0.0,
                    },
                )
                entry["total_orders"] += 1
                entry["total_units"] += qty
                entry["_gross_value"] += line_usd
                if is_cancel:
                    entry["cancellations"] += 1

        # Distribute receipt-level refund $ proportionally across that
        # receipt's line items, then roll into the per-listing aggregates.
        for r in receipts:
            txs = r.get("transactions") or []
            if not txs:
                continue
            receipt_refund_usd = 0.0
            for rf in r.get("refunds") or []:
                amt = rf.get("amount") or {}
                if isinstance(amt, dict) and amt.get("amount") is not None:
                    receipt_refund_usd += amt["amount"] / max(amt.get("divisor", 1), 1)
            if receipt_refund_usd <= 0:
                continue
            # Compute receipt's total line value to apportion
            line_values: list[tuple[int, float]] = []
            for tx in txs:
                lid = tx.get("listing_id")
                if lid is None:
                    continue
                price = tx.get("price") or {}
                qty = int(tx.get("quantity") or 0)
                unit_usd = 0.0
                if isinstance(price, dict) and price.get("amount") is not None:
                    unit_usd = price["amount"] / max(price.get("divisor", 1), 1)
                line_values.append((lid, unit_usd * qty))
            total_line_value = sum(v for _, v in line_values) or 1.0
            for lid, line_usd in line_values:
                share = (line_usd / total_line_value) * receipt_refund_usd
                if lid in agg:
                    agg[lid]["refunded_amount_usd"] += share

        # Filter, compute rates, sort
        rows: list[dict[str, Any]] = []
        for lid, e in agg.items():
            if e["total_orders"] < min_orders:
                continue
            rate = (e["cancellations"] / e["total_orders"] * 100) if e["total_orders"] else 0.0
            e.pop("_gross_value", None)
            e["return_rate_pct"] = round(rate, 2)
            e["refunded_amount_usd"] = round(e["refunded_amount_usd"], 2)
            rows.append(e)
        rows.sort(key=lambda r: (r["return_rate_pct"], r["cancellations"]), reverse=True)

        total_orders = sum(e["total_orders"] for e in agg.values())
        total_cancels = sum(e["cancellations"] for e in agg.values())
        overall_rate = (total_cancels / total_orders * 100) if total_orders else 0.0

        return {
            "period": {
                "min_created": min_created,
                "max_created": max_created,
                "days": days,
            },
            "min_orders_filter": min_orders,
            "listing_count_total": len(rows),
            "by_listing": rows,
            "rolled_up": {
                "total_orders": total_orders,
                "total_cancellations": total_cancels,
                "overall_return_rate_pct": round(overall_rate, 2),
            },
        }

    return {
        "etsy_list_receipts": etsy_list_receipts,
        "etsy_get_receipt": etsy_get_receipt,
        "etsy_get_receipt_transactions": etsy_get_receipt_transactions,
        "etsy_list_shop_payments": etsy_list_shop_payments,
        "etsy_returns_summary": etsy_returns_summary,
        "etsy_per_listing_return_rate": etsy_per_listing_return_rate,
    }
