"""Etsy MCP — FastMCP server entrypoint.

Run: python server.py

Phase 0 tools:
- etsy_whoami: verify auth, return user + shop info
- etsy_token_status: report access-token expiry + refresh-token age

Future phases register more tools here by importing from etsy_mcp/<domain>.py.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from etsy_mcp.auth import TokenStore
from etsy_mcp.errors import EtsyMCPError
from etsy_mcp.http import etsy_request
from etsy_mcp.browser import register_browser_tools
from etsy_mcp.bulk_ops import register_bulk_ops_tools
from etsy_mcp.exports import register_export_tools
from etsy_mcp.listings import register_listing_tools
from etsy_mcp.messages import register_message_tools
from etsy_mcp.orders import register_order_tools
from etsy_mcp.receipts import register_receipt_tools
from etsy_mcp.reporting import register_reporting_tools
from etsy_mcp.reviews import register_review_tools
from etsy_mcp.shop import register_shop_tools
from etsy_mcp.shop_config import register_shop_config_tools
from etsy_mcp.taxonomy import register_taxonomy_tools

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

KEYSTRING = os.environ.get("ETSY_KEYSTRING", "").strip()
TOKENS_PATH = ROOT / ".tokens.json"

if not KEYSTRING:
    raise RuntimeError(
        "ETSY_KEYSTRING is not set. Copy .env.example to .env and fill it in."
    )


def _shop_id() -> str:
    return os.environ.get("ETSY_SHOP_ID", "").strip()


mcp = FastMCP("etsy")

register_shop_tools(
    mcp,
    keystring=KEYSTRING,
    tokens_path=TOKENS_PATH,
    shop_id_getter=_shop_id,
)
register_listing_tools(
    mcp,
    keystring=KEYSTRING,
    tokens_path=TOKENS_PATH,
    shop_id_getter=_shop_id,
)
register_receipt_tools(
    mcp,
    keystring=KEYSTRING,
    tokens_path=TOKENS_PATH,
    shop_id_getter=_shop_id,
)
register_review_tools(
    mcp,
    keystring=KEYSTRING,
    tokens_path=TOKENS_PATH,
    shop_id_getter=_shop_id,
)
register_taxonomy_tools(
    mcp,
    keystring=KEYSTRING,
    tokens_path=TOKENS_PATH,
)
register_export_tools(
    mcp,
    keystring=KEYSTRING,
    tokens_path=TOKENS_PATH,
    shop_id_getter=_shop_id,
)
register_browser_tools(
    mcp,
    keystring=KEYSTRING,
    tokens_path=TOKENS_PATH,
    shop_id_getter=_shop_id,
)
register_order_tools(
    mcp,
    keystring=KEYSTRING,
    tokens_path=TOKENS_PATH,
    shop_id_getter=_shop_id,
)
register_shop_config_tools(
    mcp,
    keystring=KEYSTRING,
    tokens_path=TOKENS_PATH,
    shop_id_getter=_shop_id,
)
register_bulk_ops_tools(
    mcp,
    keystring=KEYSTRING,
    tokens_path=TOKENS_PATH,
    shop_id_getter=_shop_id,
)
register_reporting_tools(
    mcp,
    keystring=KEYSTRING,
    tokens_path=TOKENS_PATH,
    shop_id_getter=_shop_id,
)
register_message_tools(
    mcp,
    keystring=KEYSTRING,
    tokens_path=TOKENS_PATH,
    shop_id_getter=_shop_id,
)


def _err_to_dict(exc: EtsyMCPError) -> dict[str, Any]:
    return exc.to_dict()


@mcp.tool()
async def etsy_whoami() -> dict[str, Any]:
    """Return the authenticated user + their shop.

    Verifies that .tokens.json is valid and the API is reachable. Use this
    as your first call after running the OAuth bootstrap.
    """
    try:
        me = await etsy_request(
            "GET",
            "/application/users/me",
            keystring=KEYSTRING,
            tokens_path=str(TOKENS_PATH),
        )
        if not isinstance(me, dict) or "user_id" not in me:
            return {
                "error": "Etsy /users/me returned unexpected shape (no user_id).",
                "code": "unknown",
                "details": {"response": me},
            }
        user_id = me["user_id"]

        shops_resp = await etsy_request(
            "GET",
            f"/application/users/{user_id}/shops",
            keystring=KEYSTRING,
            tokens_path=str(TOKENS_PATH),
        )
    except EtsyMCPError as exc:
        return _err_to_dict(exc)

    # Etsy may return {"results": [...]} or a bare object — normalize.
    if isinstance(shops_resp, dict) and "results" in shops_resp:
        results = shops_resp.get("results") or []
        if not results:
            return {
                "error": "Authenticated user has no shops.",
                "code": "not_found",
            }
        shop = results[0]
    elif isinstance(shops_resp, dict):
        shop = shops_resp
    else:
        return {
            "error": "Etsy /shops returned unexpected shape (not a dict).",
            "code": "unknown",
            "details": {"response_type": type(shops_resp).__name__},
        }

    if not isinstance(shop, dict):
        return {
            "error": "Etsy /shops returned a non-dict shop entry.",
            "code": "unknown",
        }

    return {
        "user_id": user_id,
        "login_name": me.get("login_name"),
        "primary_email": me.get("primary_email"),
        "shop_id": shop.get("shop_id") or shop.get("id"),
        "shop_name": shop.get("shop_name") or shop.get("name"),
    }


@mcp.tool()
async def etsy_token_status() -> dict[str, Any]:
    """Show access-token expiry and refresh-token age.

    Refresh tokens expire after 90 days. If refresh_age_days exceeds ~85,
    plan to re-run scripts/bootstrap_oauth.py soon.
    """
    try:
        tokens = TokenStore(TOKENS_PATH).load()
    except FileNotFoundError:
        return {
            "error": "No .tokens.json found. Run scripts/bootstrap_oauth.py first.",
            "code": "auth_invalid",
        }

    now = time.time()
    access_remaining = max(0, int(tokens["expires_at"] - now))
    refresh_age_days = int((now - tokens["obtained_at"]) / 86400)
    return {
        "access_expires_in_seconds": access_remaining,
        "refresh_age_days": refresh_age_days,
        "refresh_expires_in_days_estimate": max(0, 90 - refresh_age_days),
        "scope": tokens.get("scope", ""),
    }


if __name__ == "__main__":
    mcp.run()
