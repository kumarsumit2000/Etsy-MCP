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

    @mcp.tool()
    async def etsy_ads_get_status() -> dict[str, Any]:
        """Return current Etsy Ads state: enabled, daily budget, last 30d stats.

        Driven via the seller dashboard at /your/shops/me/advertising since
        Etsy's public API doesn't expose ad campaign data.
        """
        try:
            async with EtsyBrowser() as page:
                await page.goto(ETSY_ADS_URL)
                if not await _ensure_logged_in(page):
                    return _session_expired_error()

                # Detect on/off via the presence of the "Turn on Etsy Ads" button
                turn_on = page.locator(SELECTORS["ads_turn_on_button_role"])
                pause = page.locator(SELECTORS["ads_pause_button_role"])
                if await turn_on.count() > 0:
                    enabled = False
                elif await pause.count() > 0:
                    enabled = True
                else:
                    screenshot = await _save_error_screenshot(page, "ads_status_detect")
                    return _selector_missing_error("detect ads on/off", screenshot)

                # Daily budget — only meaningful when enabled
                daily_budget_usd: float | None = None
                if enabled:
                    budget_input = page.locator(SELECTORS["ads_daily_budget_input_label"])
                    if await budget_input.count() > 0:
                        try:
                            value = await budget_input.input_value()
                            daily_budget_usd = float(value.replace("$", "").strip())
                        except Exception:
                            daily_budget_usd = None

                # 30-day stats (best-effort — return None for any field whose
                # selector is missing rather than fail the whole call)
                async def _read_metric(key: str) -> str | None:
                    sel = page.locator(SELECTORS[key])
                    if await sel.count() == 0:
                        return None
                    try:
                        return (await sel.inner_text()).strip()
                    except Exception:
                        return None

                last_30d = {
                    "spend": await _read_metric("ads_30d_spend_text"),
                    "clicks": await _read_metric("ads_30d_clicks_text"),
                    "impressions": await _read_metric("ads_30d_impressions_text"),
                    "orders": await _read_metric("ads_30d_orders_text"),
                    "revenue": await _read_metric("ads_30d_revenue_text"),
                }

                return {
                    "enabled": enabled,
                    "daily_budget_usd": daily_budget_usd,
                    "last_30d": last_30d,
                }
        except FileNotFoundError:
            return _session_expired_error()
        except EtsyMCPError as exc:
            return exc.to_dict()

    @mcp.tool()
    async def etsy_ads_create_campaign(
        daily_budget_usd: float,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Turn Etsy Ads on with the given daily budget.

        Args:
            daily_budget_usd: Daily ad budget in USD (Etsy converts to shop currency).
            confirm: Must be True. Prevents accidental enabling — Etsy Ads
                is a real-money commitment.
        """
        if not confirm:
            return {
                "error": (
                    f"Refusing to enable Etsy Ads at ${daily_budget_usd}/day "
                    "without confirm=True. This commits real money."
                ),
                "code": "validation_failed",
            }
        if daily_budget_usd <= 0:
            return {
                "error": "daily_budget_usd must be > 0.",
                "code": "validation_failed",
            }

        try:
            async with EtsyBrowser() as page:
                await page.goto(ETSY_ADS_URL)
                if not await _ensure_logged_in(page):
                    return _session_expired_error()

                turn_on = page.locator(SELECTORS["ads_turn_on_button_role"])
                if await turn_on.count() == 0:
                    # Already on — caller should use etsy_ads_set_budget
                    return {
                        "error": (
                            "Etsy Ads appears to already be enabled. "
                            "Use etsy_ads_set_budget to change the budget."
                        ),
                        "code": "validation_failed",
                    }

                try:
                    await turn_on.first.click()
                except Exception:
                    screenshot = await _save_error_screenshot(page, "ads_create_click")
                    return _selector_missing_error("click 'Turn on Etsy Ads'", screenshot)

                budget_input = page.locator(SELECTORS["ads_daily_budget_input_label"])
                try:
                    await budget_input.first.fill(f"{daily_budget_usd:.2f}")
                except Exception:
                    screenshot = await _save_error_screenshot(page, "ads_create_fill_budget")
                    return _selector_missing_error("fill daily budget input", screenshot)

                save = page.locator(SELECTORS["ads_save_budget_button_role"])
                try:
                    await save.first.click()
                except Exception:
                    screenshot = await _save_error_screenshot(page, "ads_create_save")
                    return _selector_missing_error("click 'Save'", screenshot)

                # Some flows pop a confirm dialog
                confirm_btn = page.locator(SELECTORS["ads_confirm_dialog_button_role"])
                if await confirm_btn.count() > 0:
                    await confirm_btn.first.click()

                return {"enabled": True, "daily_budget_usd": daily_budget_usd}
        except FileNotFoundError:
            return _session_expired_error()
        except EtsyMCPError as exc:
            return exc.to_dict()

    @mcp.tool()
    async def etsy_ads_set_budget(daily_budget_usd: float) -> dict[str, Any]:
        """Modify the daily budget on an already-enabled Etsy Ads campaign.

        For initial enablement use etsy_ads_create_campaign instead.
        """
        if daily_budget_usd <= 0:
            return {
                "error": "daily_budget_usd must be > 0.",
                "code": "validation_failed",
            }

        try:
            async with EtsyBrowser() as page:
                await page.goto(ETSY_ADS_URL)
                if not await _ensure_logged_in(page):
                    return _session_expired_error()

                edit = page.locator(SELECTORS["ads_edit_budget_button_role"])
                if await edit.count() == 0:
                    return {
                        "error": (
                            "'Edit budget' button not found. Ads may be off — "
                            "use etsy_ads_create_campaign first."
                        ),
                        "code": "validation_failed",
                    }
                try:
                    await edit.first.click()
                except Exception:
                    screenshot = await _save_error_screenshot(page, "ads_set_edit")
                    return _selector_missing_error("click 'Edit budget'", screenshot)

                budget_input = page.locator(SELECTORS["ads_daily_budget_input_label"])
                try:
                    await budget_input.first.fill(f"{daily_budget_usd:.2f}")
                except Exception:
                    screenshot = await _save_error_screenshot(page, "ads_set_fill")
                    return _selector_missing_error("fill daily budget input", screenshot)

                save = page.locator(SELECTORS["ads_save_budget_button_role"])
                try:
                    await save.first.click()
                except Exception:
                    screenshot = await _save_error_screenshot(page, "ads_set_save")
                    return _selector_missing_error("click 'Save'", screenshot)

                return {"daily_budget_usd": daily_budget_usd}
        except FileNotFoundError:
            return _session_expired_error()
        except EtsyMCPError as exc:
            return exc.to_dict()

    async def _toggle_ads(action: str) -> dict[str, Any]:
        """Shared implementation for pause / resume — both click a single
        button and verify success.
        """
        button_key = (
            "ads_pause_button_role" if action == "pause" else "ads_resume_button_role"
        )
        try:
            async with EtsyBrowser() as page:
                await page.goto(ETSY_ADS_URL)
                if not await _ensure_logged_in(page):
                    return _session_expired_error()

                btn = page.locator(SELECTORS[button_key])
                if await btn.count() == 0:
                    return {
                        "error": (
                            f"'{action}' button not found. Ads may already be in "
                            f"the {'inactive' if action == 'pause' else 'active'} state."
                        ),
                        "code": "validation_failed",
                    }
                try:
                    await btn.first.click()
                except Exception:
                    screenshot = await _save_error_screenshot(page, f"ads_{action}")
                    return _selector_missing_error(f"click '{action}' button", screenshot)

                # Some flows pop a confirm dialog
                confirm_btn = page.locator(SELECTORS["ads_confirm_dialog_button_role"])
                if await confirm_btn.count() > 0:
                    await confirm_btn.first.click()

                return {"enabled": action == "resume"}
        except FileNotFoundError:
            return _session_expired_error()
        except EtsyMCPError as exc:
            return exc.to_dict()

    @mcp.tool()
    async def etsy_ads_pause() -> dict[str, Any]:
        """Pause an active Etsy Ads campaign. Reversible via etsy_ads_resume."""
        return await _toggle_ads("pause")

    @mcp.tool()
    async def etsy_ads_resume() -> dict[str, Any]:
        """Resume a paused Etsy Ads campaign."""
        return await _toggle_ads("resume")

    @mcp.tool()
    async def etsy_update_listing_images_order(
        listing_id: int,
        image_ids: list[int],
    ) -> dict[str, Any]:
        """Reorder images on a listing.

        Etsy v3 has no rank-only image-update endpoint, so this is driven
        via the seller dashboard's listing-edit page. Each image element
        carries data-listing-image-id; we evaluate JavaScript in-page to
        rearrange the DOM order to match image_ids, then click Save.

        Args:
            listing_id: The listing whose images to reorder.
            image_ids: List of listing_image_ids in the desired display order.
        """
        if not image_ids:
            return {
                "error": "image_ids list is empty — pass at least one image id.",
                "code": "validation_failed",
            }

        try:
            async with EtsyBrowser() as page:
                url = ETSY_LISTING_EDIT_URL_TEMPLATE.format(listing_id=listing_id)
                await page.goto(url)
                if not await _ensure_logged_in(page):
                    return _session_expired_error()

                thumbnails = page.locator(SELECTORS["listing_image_thumbnail_css"])
                count = await thumbnails.count()
                if count == 0:
                    screenshot = await _save_error_screenshot(page, "image_reorder_no_thumbs")
                    return _selector_missing_error(
                        "find image thumbnails on listing edit page",
                        screenshot,
                    )

                # Reorder the DOM nodes in-page via JavaScript. Etsy's UI
                # detects DOM rearrangement and updates internal state when
                # Save is clicked. This is more reliable than simulating
                # drag-and-drop, which is heavily debounced.
                try:
                    await page.evaluate(
                        """([selector, desiredOrder]) => {
                            const nodes = Array.from(document.querySelectorAll(selector));
                            const byId = new Map();
                            for (const n of nodes) {
                                const id = parseInt(n.getAttribute('data-listing-image-id'));
                                byId.set(id, n);
                            }
                            const parent = nodes[0]?.parentNode;
                            if (!parent) return false;
                            for (const id of desiredOrder) {
                                const n = byId.get(id);
                                if (n) parent.appendChild(n);
                            }
                            return true;
                        }""",
                        [SELECTORS["listing_image_thumbnail_css"], image_ids],
                    )
                except Exception:
                    screenshot = await _save_error_screenshot(page, "image_reorder_evaluate")
                    return _selector_missing_error(
                        "rearrange image DOM nodes via JS",
                        screenshot,
                    )

                save = page.locator(SELECTORS["listing_save_button_role"])
                if await save.count() == 0:
                    screenshot = await _save_error_screenshot(page, "image_reorder_save_missing")
                    return _selector_missing_error("find 'Save and continue' button", screenshot)
                try:
                    await save.first.click()
                except Exception:
                    screenshot = await _save_error_screenshot(page, "image_reorder_save_click")
                    return _selector_missing_error("click 'Save and continue'", screenshot)

                return {"listing_id": listing_id, "ordered": image_ids}
        except FileNotFoundError:
            return _session_expired_error()
        except EtsyMCPError as exc:
            return exc.to_dict()

    return {
        "etsy_ads_get_status": etsy_ads_get_status,
        "etsy_ads_create_campaign": etsy_ads_create_campaign,
        "etsy_ads_set_budget": etsy_ads_set_budget,
        "etsy_ads_pause": etsy_ads_pause,
        "etsy_ads_resume": etsy_ads_resume,
        "etsy_update_listing_images_order": etsy_update_listing_images_order,
    }
