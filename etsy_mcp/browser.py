"""Browser-driven tools for Etsy MCP.

Etsy's seller dashboard exposes features the public API doesn't:
  - Etsy Ads campaign create/edit/pause/resume/stats
  - Listing image reordering

This module wraps Playwright's async Chromium API behind a single
EtsyBrowser context manager. Each tool acquires the browser, navigates,
reads / clicks, and returns a structured dict.

ALL SELECTORS LIVE IN THE SELECTORS DICT BELOW. Each entry has a
'Last verified: YYYY-MM-DD' comment. When Etsy redesigns the dashboard
the only place to update is that block.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from .errors import EtsyMCPError, missing_shop_id_error

# ---------------------------------------------------------------------------
# Selectors (centralized — update here when Etsy redesigns)
# ---------------------------------------------------------------------------
# Each selector value can be either a CSS selector or, preferred, a
# Playwright role/label/text string fed to page.get_by_role / get_by_label /
# get_by_text. The browser tools use the appropriate getter based on the
# selector key suffix (_role, _label, _text, _css).
SELECTORS: dict[str, str] = {
    # Ads page
    # Last verified: 2026-05-05
    "ads_status_banner_text": "Etsy Ads",  # text on the page when ads section loads
    "ads_turn_on_button_role": "button:has-text('Turn on Etsy Ads')",
    "ads_pause_button_role": "button:has-text('Pause')",
    "ads_resume_button_role": "button:has-text('Resume')",
    "ads_edit_budget_button_role": "button:has-text('Edit budget')",
    "ads_daily_budget_input_label": "Daily budget",
    "ads_save_budget_button_role": "button:has-text('Save')",
    "ads_confirm_dialog_button_role": "button:has-text('Confirm')",
    "ads_30d_spend_text": "[data-test-id='ads-30d-spend']",
    "ads_30d_clicks_text": "[data-test-id='ads-30d-clicks']",
    "ads_30d_impressions_text": "[data-test-id='ads-30d-impressions']",
    "ads_30d_orders_text": "[data-test-id='ads-30d-orders']",
    "ads_30d_revenue_text": "[data-test-id='ads-30d-revenue']",
    # Listing edit page
    # Last verified: 2026-05-05
    "listing_image_thumbnail_css": "[data-listing-image-id]",
    "listing_save_button_role": "button:has-text('Save and continue')",
}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ETSY_SIGNIN_URL_FRAGMENT = "/signin"
ETSY_ADS_URL = "https://www.etsy.com/your/shops/me/advertising"
ETSY_LISTING_EDIT_URL_TEMPLATE = "https://www.etsy.com/your/shops/me/tools/listings/{listing_id}/edit"
ETSY_DASHBOARD_URL_FRAGMENT = "/your/shops/me/"

DEFAULT_VIEWPORT = {"width": 1440, "height": 900}
NAV_TIMEOUT_MS = 30_000
ACTION_TIMEOUT_MS = 10_000

# Env-var name for overriding the storage-state path (used in tests)
_STORAGE_STATE_PATH_ENV = "ETSY_BROWSER_STORAGE_STATE"


def _storage_state_path() -> Path:
    """Resolve the storage-state file path. Tests can override via env."""
    override = os.environ.get(_STORAGE_STATE_PATH_ENV)
    if override:
        return Path(override)
    # Default: <project root>/.storage_state.json
    return Path(__file__).resolve().parent.parent / ".storage_state.json"


def _is_headful() -> bool:
    return os.environ.get("ETSY_ADS_HEADFUL", "0").strip() in ("1", "true", "yes")


def _session_expired_error() -> dict[str, Any]:
    return {
        "error": (
            "Etsy browser session is missing or expired. Re-run "
            "scripts/bootstrap_browser_login.py to create a fresh session."
        ),
        "code": "session_expired",
    }


def _selector_missing_error(step: str, screenshot_path: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "error": (
            f"Etsy dashboard layout changed at step '{step}'. "
            "The selectors block in etsy_mcp/browser.py needs an update."
        ),
        "code": "selector_missing",
    }
    if screenshot_path:
        out["screenshot_path"] = screenshot_path
    return out


# ---------------------------------------------------------------------------
# EtsyBrowser context manager
# ---------------------------------------------------------------------------
class EtsyBrowser:
    """Async context manager that yields a Playwright Page bound to a fresh
    Chromium context loaded with the saved storage_state.

    Usage:
        async with EtsyBrowser() as page:
            await page.goto(ETSY_ADS_URL)
            ...

    Raises FileNotFoundError if .storage_state.json is missing (caller
    surfaces _session_expired_error()).
    """

    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    async def __aenter__(self):
        # Lazy import so 'import etsy_mcp.browser' works even if Playwright
        # binaries aren't installed yet (the CI env or unit tests).
        from playwright.async_api import async_playwright

        storage_path = _storage_state_path()
        if not storage_path.is_file():
            raise FileNotFoundError(str(storage_path))

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=not _is_headful())
        self._context = await self._browser.new_context(
            storage_state=str(storage_path),
            viewport=DEFAULT_VIEWPORT,
        )
        self._context.set_default_navigation_timeout(NAV_TIMEOUT_MS)
        self._context.set_default_timeout(ACTION_TIMEOUT_MS)
        self._page = await self._context.new_page()
        return self._page

    async def __aexit__(self, *exc) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()


async def _ensure_logged_in(page) -> bool:
    """After navigation, check whether Etsy redirected us to /signin. Returns
    True if we're on a logged-in page, False if redirected to signin."""
    return ETSY_SIGNIN_URL_FRAGMENT not in page.url


async def _save_error_screenshot(page, label: str) -> str:
    """Save a screenshot of the current page state for selector-missing
    debugging. Returns the path."""
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = f"/tmp/etsy_browser_error_{label}_{ts}.png"
    try:
        await page.screenshot(path=path, full_page=True)
    except Exception:
        return ""  # Best-effort; don't crash the error path.
    return path


# ---------------------------------------------------------------------------
# Tool registration (tools are added in Tasks 4-8)
# ---------------------------------------------------------------------------
def register_browser_tools(
    mcp: FastMCP,
    *,
    keystring: str,
    tokens_path: str | Path,
    shop_id_getter: Callable[[], str],
) -> dict[str, Callable]:
    """Register browser-driven tools on the given FastMCP instance.

    keystring/tokens_path are accepted for signature symmetry with other
    register_*_tools factories but are unused here — browser tools don't
    hit the Etsy API.
    """
    # Tools added in later tasks
    return {}
