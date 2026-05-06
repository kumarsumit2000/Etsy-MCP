"""Alert composers — wrap MCP tools and shape their output for the dashboard.

Each alert function is async, returns a dict with a stable shape:

    {
        "count": int,                 # for the badge / headline number
        "headline": str,              # short summary line for the tile
        "severity": "info"|"warn"|"alert",
        "items": list[dict],          # detail rows
        "error": Optional[str],       # set if the underlying call failed
        "stale_seconds": int,         # how many seconds since this was computed
    }

The snapshot composer fans these out in parallel and merges the results.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
import sys

sys.path.insert(0, str(PROJECT_ROOT))

from etsy_mcp.http import etsy_request, paginate_all  # noqa: E402
from etsy_mcp.timeutil import shop_tz, parse_local_date  # noqa: E402
from webapp import state  # noqa: E402

# 5-minute cache on the messages alert because each call spins up a browser.
_MESSAGES_CACHE_TTL = 300


def _shop_id() -> str:
    return state.env_value("ETSY_SHOP_ID")


def _keystring() -> str:
    # The MCP wrapper expects a keystring; the http layer handles the
    # combined `<keystring>:<shared_secret>` from env on its own.
    return state.env_value("ETSY_KEYSTRING")


def _today_epoch_range() -> tuple[int, int]:
    """Return (min_created, max_created) for today in the shop's timezone."""
    now = datetime.now(tz=shop_tz())
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return int(start.timestamp()), int(end.timestamp()) - 1


# ---------------------------------------------------------------------------
# 1. Missed chats — uses the browser-driven conversations scraper
# ---------------------------------------------------------------------------
_messages_cache: dict[str, Any] = {"computed_at": 0.0, "result": None}


async def alert_missed_chats(force: bool = False) -> dict[str, Any]:
    """Unread + age >= 2h messages in the last 48h. Cached 5 min."""
    now = time.time()
    if (
        not force
        and _messages_cache["result"] is not None
        and now - _messages_cache["computed_at"] < _MESSAGES_CACHE_TTL
    ):
        return {**_messages_cache["result"], "stale_seconds": int(now - _messages_cache["computed_at"])}

    # Lazy-import — the browser tool is heavy.
    from mcp.server.fastmcp import FastMCP
    from etsy_mcp.messages import register_message_tools

    m = FastMCP("alerts")
    tools = register_message_tools(
        m,
        keystring=_keystring(),
        tokens_path=str(state.TOKENS_PATH),
        shop_id_getter=_shop_id,
    )
    try:
        r = await tools["etsy_list_conversations"](
            filter="missed", since_hours=48, min_age_hours=2, limit=50
        )
    except Exception as exc:
        return {"count": 0, "headline": "—", "severity": "info", "items": [],
                "error": f"Could not load messages: {exc}", "stale_seconds": 0}

    if isinstance(r, dict) and r.get("error"):
        result = {"count": 0, "headline": "—", "severity": "info", "items": [],
                  "error": r["error"], "stale_seconds": 0}
    else:
        rows = r.get("rows", [])
        items = [
            {
                "id": row["conversation_id"],
                "title": row.get("buyer_name") or "(unknown buyer)",
                "subtitle": row.get("preview") or "",
                "age": f"{row['age_hours']:.1f}h" if row.get("age_hours") else "?",
                "url": f"https://www.etsy.com/messages/{row['conversation_id']}",
            }
            for row in rows
        ]
        count = len(items)
        result = {
            "count": count,
            "headline": (
                "All caught up" if count == 0
                else f"{count} buyer{'' if count == 1 else 's'} waiting > 2h"
            ),
            "severity": "info" if count == 0 else "alert" if count >= 5 else "warn",
            "items": items,
            "error": None,
            "stale_seconds": 0,
        }

    # Only cache successful results — errors retry on the next poll instead
    # of freezing the tile in a stale error state for 5 minutes.
    if result.get("error") is None:
        _messages_cache["result"] = result
        _messages_cache["computed_at"] = now
    return result


# ---------------------------------------------------------------------------
# 2. New orders today
# ---------------------------------------------------------------------------
async def alert_new_orders_today() -> dict[str, Any]:
    shop_id = _shop_id()
    if not shop_id:
        return {"count": 0, "headline": "—", "severity": "info", "items": [],
                "error": "ETSY_SHOP_ID not set", "stale_seconds": 0}

    min_c, max_c = _today_epoch_range()
    try:
        receipts = await paginate_all(
            "GET",
            f"/application/shops/{shop_id}/receipts",
            keystring=_keystring(),
            tokens_path=str(state.TOKENS_PATH),
            params={"min_created": min_c, "max_created": max_c},
        )
    except Exception as exc:
        return {"count": 0, "headline": "—", "severity": "info", "items": [],
                "error": f"API error: {exc}", "stale_seconds": 0}

    total_cents = 0
    items = []
    currency = "USD"
    for r in receipts:
        gt = r.get("grandtotal") or {}
        amt = int(gt.get("amount", 0) * 100 / max(gt.get("divisor", 1), 1))
        total_cents += amt
        currency = gt.get("currency_code", currency)
        items.append(
            {
                "id": r["receipt_id"],
                "title": r.get("name") or "(unknown buyer)",
                "subtitle": f"${amt/100:.2f} · {'paid' if r.get('was_paid') else 'unpaid'} · "
                            f"{'shipped' if r.get('was_shipped') else 'unshipped'}",
                "url": f"https://www.etsy.com/your/orders/{r['receipt_id']}",
            }
        )

    count = len(receipts)
    return {
        "count": count,
        "headline": f"{count} order{'' if count == 1 else 's'} · ${total_cents/100:,.2f} {currency}",
        "severity": "info",
        "items": items,
        "error": None,
        "stale_seconds": 0,
    }


# ---------------------------------------------------------------------------
# 3. Needs shipping — paid but not shipped
# ---------------------------------------------------------------------------
async def alert_needs_shipping() -> dict[str, Any]:
    shop_id = _shop_id()
    if not shop_id:
        return {"count": 0, "headline": "—", "severity": "info", "items": [],
                "error": "ETSY_SHOP_ID not set", "stale_seconds": 0}

    try:
        page = await etsy_request(
            "GET",
            f"/application/shops/{shop_id}/receipts",
            keystring=_keystring(),
            tokens_path=str(state.TOKENS_PATH),
            params={"was_paid": True, "was_shipped": False, "limit": 50},
        )
    except Exception as exc:
        return {"count": 0, "headline": "—", "severity": "info", "items": [],
                "error": f"API error: {exc}", "stale_seconds": 0}

    rows = page.get("results", []) if isinstance(page, dict) else []
    total_count = page.get("count", len(rows)) if isinstance(page, dict) else len(rows)
    items = []
    now = datetime.now(tz=shop_tz())
    for r in rows:
        ts = r.get("create_timestamp")
        age_days = (now - datetime.fromtimestamp(ts, tz=shop_tz())).days if ts else None
        gt = r.get("grandtotal") or {}
        amt = int(gt.get("amount", 0) * 100 / max(gt.get("divisor", 1), 1))
        items.append(
            {
                "id": r["receipt_id"],
                "title": r.get("name") or "(unknown buyer)",
                "subtitle": f"${amt/100:.2f}" + (f" · {age_days}d old" if age_days is not None else ""),
                "url": f"https://www.etsy.com/your/orders/{r['receipt_id']}",
            }
        )

    severity = "alert" if total_count >= 20 else "warn" if total_count > 0 else "info"
    return {
        "count": total_count,
        "headline": (
            "Nothing pending" if total_count == 0
            else f"{total_count} paid order{'' if total_count == 1 else 's'} unshipped"
        ),
        "severity": severity,
        "items": items[:20],
        "error": None,
        "stale_seconds": 0,
    }


# ---------------------------------------------------------------------------
# 4. Bad reviews — last 7 days, rating <= 3
# ---------------------------------------------------------------------------
async def alert_bad_reviews() -> dict[str, Any]:
    shop_id = _shop_id()
    if not shop_id:
        return {"count": 0, "headline": "—", "severity": "info", "items": [],
                "error": "ETSY_SHOP_ID not set", "stale_seconds": 0}

    seven_days_ago = int(time.time()) - 7 * 86400
    try:
        page = await etsy_request(
            "GET",
            f"/application/shops/{shop_id}/reviews",
            keystring=_keystring(),
            tokens_path=str(state.TOKENS_PATH),
            params={"min_created": seven_days_ago, "limit": 100},
        )
    except Exception as exc:
        return {"count": 0, "headline": "—", "severity": "info", "items": [],
                "error": f"API error: {exc}", "stale_seconds": 0}

    rows = page.get("results", []) if isinstance(page, dict) else []
    bad = [r for r in rows if (r.get("rating") or 5) <= 3]
    items = [
        {
            "id": r.get("transaction_id") or r.get("listing_id"),
            "title": f"★ {r.get('rating')} · {r.get('language', 'en')}",
            "subtitle": (r.get("review") or "")[:160],
            "url": f"https://www.etsy.com/your/orders/{r.get('transaction_id', '')}",
        }
        for r in bad
    ]
    count = len(bad)
    return {
        "count": count,
        "headline": (
            "No bad reviews this week" if count == 0
            else f"{count} review{'' if count == 1 else 's'} ≤ 3★ in 7 days"
        ),
        "severity": "info" if count == 0 else "alert",
        "items": items,
        "error": None,
        "stale_seconds": 0,
    }


# ---------------------------------------------------------------------------
# Snapshot composer
# ---------------------------------------------------------------------------
async def snapshot() -> dict[str, Any]:
    """Run all four alerts in parallel; return a merged dashboard snapshot."""
    chats, orders, shipping, reviews = await asyncio.gather(
        alert_missed_chats(),
        alert_new_orders_today(),
        alert_needs_shipping(),
        alert_bad_reviews(),
        return_exceptions=False,
    )
    return {
        "alerts": {
            "missed_chats": chats,
            "new_orders": orders,
            "needs_shipping": shipping,
            "bad_reviews": reviews,
        },
        "computed_at": int(time.time()),
    }
