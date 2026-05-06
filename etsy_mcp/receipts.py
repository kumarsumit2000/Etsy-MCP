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

    return {
        "etsy_list_receipts": etsy_list_receipts,
        "etsy_get_receipt": etsy_get_receipt,
        "etsy_get_receipt_transactions": etsy_get_receipt_transactions,
        "etsy_list_shop_payments": etsy_list_shop_payments,
        "etsy_returns_summary": etsy_returns_summary,
    }
