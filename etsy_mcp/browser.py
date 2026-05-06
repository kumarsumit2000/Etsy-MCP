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
    # Last verified: 2026-05-06 (Etsy redesigned the panel; stats moved into
    # <p class="wt-text-heading"> with sibling <span> labels — we now read
    # them via a label-anchored JS scraper instead of CSS data-test-ids,
    # which Etsy removed)
    "ads_status_banner_text": "Etsy Ads",
    "ads_turn_on_button_role": "button:has-text('Turn on Etsy Ads')",
    "ads_pause_button_role": "button:has-text('Pause Etsy Ads')",
    "ads_resume_button_role": "button:has-text('Resume Etsy Ads')",
    "ads_edit_budget_button_role": "button:has-text('Manage your budget')",
    "ads_daily_budget_input_label": "input[aria-label='Change your Etsy Ads budget']",
    "ads_save_budget_button_role": "button:has-text('Update budget')",
    "ads_confirm_dialog_button_role": "button:has-text('Confirm')",
    # Listing edit page
    # Last verified: 2026-05-05
    "listing_image_thumbnail_css": "[data-listing-image-id]",
    "listing_save_button_role": "button:has-text('Save and continue')",
    # Discounts page (sales + coupons)
    # Last verified: 2026-05-05
    "discounts_create_sale_button_role": "button:has-text('Create a sale')",
    "discounts_create_coupon_button_role": "button:has-text('Create a coupon')",
    "discounts_percent_off_input_label": "Percent off",
    "discounts_listings_select_role": "[data-test-id='discounts-listings-select']",
    "discounts_start_date_input_label": "Start date",
    "discounts_end_date_input_label": "End date",
    "discounts_save_button_role": "button:has-text('Save')",
    "discounts_confirm_dialog_button_role": "button:has-text('Confirm')",
    "coupon_code_input_label": "Coupon code",
    "coupon_min_purchase_input_label": "Minimum purchase",
    "coupon_free_shipping_checkbox_label": "Free standard shipping",
    "active_sales_row_css": "[data-test-id='active-sale-row']",
    "active_sales_percent_off_attr": "data-percent-off",
    "active_sales_id_attr": "data-sale-id",
    "active_sales_start_attr": "data-start",
    "active_sales_end_attr": "data-end",
    "active_sales_listings_count_attr": "data-listings-count",
}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ETSY_SIGNIN_URL_FRAGMENT = "/signin"
ETSY_ADS_URL = "https://www.etsy.com/your/shops/me/advertising"
ETSY_STATS_URL = "https://www.etsy.com/your/shops/me/stats"
ETSY_DISCOUNTS_URL = "https://www.etsy.com/your/shops/me/discounts"
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
        # Stealth args + system Chrome (when available) to dodge Etsy's
        # bot detection. Falls back to bundled Chromium if Chrome isn't
        # installed.
        launch_kwargs = {
            "headless": not _is_headful(),
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        }
        try:
            self._browser = await self._pw.chromium.launch(
                channel="chrome", **launch_kwargs
            )
        except Exception:
            self._browser = await self._pw.chromium.launch(**launch_kwargs)
        self._context = await self._browser.new_context(
            storage_state=str(storage_path),
            viewport=DEFAULT_VIEWPORT,
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id=os.environ.get("ETSY_SHOP_TIMEZONE", "").strip() or "America/Denver",
        )
        # Strip navigator.webdriver flag
        await self._context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
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

                # Etsy blocks the Ads page when the shop is on holiday mode
                # or otherwise inactive. Detect that first — there are no
                # on/off controls to find in that state.
                inactive_banner = page.get_by_text(
                    "Your shop needs to be active to start Etsy Ads",
                    exact=False,
                )
                if await inactive_banner.count() > 0:
                    return {
                        "enabled": False,
                        "daily_budget_usd": None,
                        "last_30d": None,
                        "shop_state": "inactive_or_holiday",
                        "note": "Etsy Ads is unavailable while the shop is on holiday mode or inactive. Reactivate the shop to enable ads.",
                    }

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

                # 30-day stats — Etsy removed the data-test-id selectors during
                # the May 2026 redesign. The header now renders each metric as
                # a <p class*="text-heading"> value with a nearby <span> label.
                # We scrape via label text + walking up to find the value,
                # which stays robust if Etsy renames classes again. Etsy
                # renamed "Impressions" → "Views" in the same redesign; we
                # map it back for stable output schema.
                # Wait for the headings to render — Etsy hydrates stats async.
                try:
                    await page.wait_for_function(
                        """() => document.querySelectorAll('[class*="wt-text-heading"]').length >= 5""",
                        timeout=8000,
                    )
                except Exception:
                    pass  # fall through; scraper handles missing values

                stats = await page.evaluate(
                    r"""
                    () => {
                      const out = {};
                      const wanted = ['views', 'clicks', 'orders', 'revenue', 'spend', 'roas'];
                      for (const span of document.querySelectorAll('span')) {
                        const label = (span.innerText || '').trim().toLowerCase();
                        if (!wanted.includes(label) || out[label]) continue;
                        // Try immediate next sibling first (most common Etsy layout)
                        const sib = span.nextElementSibling;
                        if (sib && /text-heading/.test(sib.className || '')) {
                          const v = (sib.innerText || '').trim();
                          if (v) { out[label] = v; continue; }
                        }
                        // Walk up to 4 parents looking for any text-heading element
                        let cur = span.parentElement;
                        for (let i = 0; i < 4 && cur; i++) {
                          const valEl = cur.querySelector('p[class*="text-heading"], [class*="wt-text-heading"]');
                          if (valEl) {
                            const v = (valEl.innerText || '').trim();
                            if (v) { out[label] = v; break; }
                          }
                          cur = cur.parentElement;
                        }
                      }
                      return out;
                    }
                    """
                )
                last_30d = {
                    "spend": stats.get("spend"),
                    "clicks": stats.get("clicks"),
                    "impressions": stats.get("views"),  # Etsy renamed; preserve old key
                    "orders": stats.get("orders"),
                    "revenue": stats.get("revenue"),
                    "roas": stats.get("roas"),
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
    async def etsy_get_traffic_stats(
        date_range: str = "Last 30 days",
    ) -> dict[str, Any]:
        """Pull visits / conversion-rate / abandoned-carts / traffic-sources
        data from the Shop Stats dashboard.

        Etsy's v3 Open API does NOT expose visit counts, conversion rate,
        favorites, abandoned carts, or traffic-source breakdown — they only
        live in the seller dashboard at /your/shops/me/stats. This tool
        scrapes that page via Playwright using the saved Etsy session.

        Args:
            date_range: One of the labels Etsy's date dropdown shows —
                "Today", "Yesterday", "Last 7 days", "Last 30 days" (default),
                "This month", "Last month", "This year".

        Returns:
            {
              "headline": {visits, orders, conversion_rate, revenue},
              "shopper_stats": {item_favorites, shop_follows, repeat_buyers,
                                cities_reached, abandoned_carts, reviews},
              "date_range": str (the label that was selected),
              "url": str
            }
        """
        try:
            async with EtsyBrowser() as page:
                await page.goto(ETSY_STATS_URL, wait_until="domcontentloaded")
                if not await _ensure_logged_in(page):
                    return _session_expired_error()
                # Wait for headline numbers to render
                try:
                    await page.wait_for_function(
                        """() => document.querySelectorAll('p[class*="text-heading"]').length >= 4""",
                        timeout=10_000,
                    )
                except Exception:
                    pass

                # Switch to the requested date range. Etsy renders the current
                # label on a button; click it, then click the option.
                clicked_dropdown = await page.evaluate(
                    r"""
                    () => {
                      for (const b of document.querySelectorAll('button, [role="button"]')) {
                        const t = (b.innerText || '').trim();
                        if (/this month|last \d+|today|yesterday|this year|last month/i.test(t)
                            && /\b(may|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec|\d{4})\b/i.test(t)) {
                          b.click();
                          return t;
                        }
                      }
                      return null;
                    }
                    """
                )
                if clicked_dropdown:
                    await page.wait_for_timeout(800)
                    chosen = await page.evaluate(
                        r"""
                        (label) => {
                          for (const el of document.querySelectorAll('button, [role="menuitem"], li, a')) {
                            const t = (el.innerText || '').trim();
                            if (t.toLowerCase() === label.toLowerCase()) { el.click(); return t; }
                          }
                          return null;
                        }
                        """,
                        date_range,
                    )
                    if chosen:
                        await page.wait_for_timeout(3000)  # allow re-render

                # Scrape headline numbers. Labels and values live in separate
                # sibling subtrees on the Stats dashboard, so we invert the
                # search: find each leaf node whose entire text is exactly
                # one of our labels, then walk up to the nearest text-heading.
                stats = await page.evaluate(
                    r"""
                    () => {
                      const out = { headline: {}, shopper: {} };
                      const headlineLabels = ['Visits', 'Orders', 'Conversion rate', 'Revenue'];
                      for (const el of document.querySelectorAll('*')) {
                        if (el.children.length !== 0) continue; // leaf only
                        const t = (el.innerText || '').trim();
                        if (!headlineLabels.includes(t)) continue;
                        if (out.headline[t]) continue;
                        let cur = el.parentElement;
                        for (let i = 0; i < 5 && cur; i++) {
                          const heading = cur.querySelector('p[class*="text-heading"]');
                          if (heading) {
                            const v = (heading.innerText || '').trim();
                            if (v) { out.headline[t] = v; break; }
                          }
                          cur = cur.parentElement;
                        }
                      }
                      // Shopper stats — same inverted approach. Each tile
                      // has a leaf label (e.g. "Item favorites") and a leaf
                      // number nearby. Walk up from the label to find the
                      // first numeric leaf.
                      const shopperLabels = {
                        'item_favorites':  'Item favorites',
                        'shop_follows':    'Shop follows',
                        'reviews':         'Reviews',
                        'repeat_buyers':   'Repeat buyers',
                        'cities_reached':  'Cities reached',
                        'abandoned_carts': 'Abandoned carts',
                      };
                      for (const el of document.querySelectorAll('*')) {
                        if (el.children.length !== 0) continue;
                        const t = (el.innerText || '').trim();
                        let key = null;
                        for (const [k, label] of Object.entries(shopperLabels)) {
                          if (t === label) { key = k; break; }
                        }
                        if (!key || out.shopper[key]) continue;
                        let cur = el.parentElement;
                        for (let i = 0; i < 5 && cur; i++) {
                          for (const node of cur.querySelectorAll('*')) {
                            if (node.children.length !== 0) continue;
                            const nt = (node.innerText || '').trim();
                            if (/^\d[\d,]*$/.test(nt)) {
                              out.shopper[key] = nt;
                              break;
                            }
                          }
                          if (out.shopper[key]) break;
                          cur = cur.parentElement;
                        }
                      }
                      return out;
                    }
                    """
                )

                if not stats.get("headline"):
                    screenshot = await _save_error_screenshot(page, "stats_dashboard")
                    return _selector_missing_error(
                        "scrape Stats dashboard headline", screenshot
                    )

                head = stats["headline"]
                # Normalize numeric strings ("13.8K" → 13800, "$30,231.71" → 30231.71)
                def _to_num(s: str) -> float | None:
                    if s is None:
                        return None
                    s = s.strip().replace(",", "").replace("$", "").replace("%", "")
                    try:
                        if s.endswith("K") or s.endswith("k"):
                            return float(s[:-1]) * 1000
                        if s.endswith("M") or s.endswith("m"):
                            return float(s[:-1]) * 1_000_000
                        return float(s)
                    except ValueError:
                        return None

                return {
                    "headline": {
                        "visits": _to_num(head.get("Visits")),
                        "visits_text": head.get("Visits"),
                        "orders": _to_num(head.get("Orders")),
                        "conversion_rate_pct": _to_num(head.get("Conversion rate")),
                        "revenue_usd": _to_num(head.get("Revenue")),
                        "revenue_text": head.get("Revenue"),
                    },
                    "shopper_stats": {
                        k: _to_num(v) for k, v in stats.get("shopper", {}).items()
                    },
                    "date_range": date_range,
                    "url": ETSY_STATS_URL,
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

    @mcp.tool()
    async def etsy_list_active_sales() -> dict[str, Any]:
        """List your shop's currently active sales.

        Driven via the seller dashboard's discounts page.
        Returns a list of {sale_id, percent_off, start, end, listings_count}.
        """
        try:
            async with EtsyBrowser() as page:
                await page.goto(ETSY_DISCOUNTS_URL)
                if not await _ensure_logged_in(page):
                    return _session_expired_error()

                rows = page.locator(SELECTORS["active_sales_row_css"])
                count = await rows.count()
                sales: list[dict[str, Any]] = []
                for i in range(count):
                    row = rows.nth(i)
                    try:
                        sales.append(
                            {
                                "sale_id": await row.get_attribute(
                                    SELECTORS["active_sales_id_attr"]
                                ),
                                "percent_off": await row.get_attribute(
                                    SELECTORS["active_sales_percent_off_attr"]
                                ),
                                "start": await row.get_attribute(
                                    SELECTORS["active_sales_start_attr"]
                                ),
                                "end": await row.get_attribute(
                                    SELECTORS["active_sales_end_attr"]
                                ),
                                "listings_count": await row.get_attribute(
                                    SELECTORS["active_sales_listings_count_attr"]
                                ),
                            }
                        )
                    except Exception:
                        continue  # Best-effort per row.

                return {"sales": sales, "count": len(sales)}
        except FileNotFoundError:
            return _session_expired_error()
        except EtsyMCPError as exc:
            return exc.to_dict()

    @mcp.tool()
    async def etsy_create_sale(
        percent_off: int,
        listing_ids: list[int],
        start_iso: str,
        end_iso: str,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Create a percent-off sale on selected listings.

        Args:
            percent_off: Discount percentage (1-99).
            listing_ids: Listings the sale applies to.
            start_iso: Sale start date (YYYY-MM-DD).
            end_iso: Sale end date (YYYY-MM-DD).
            confirm: Must be True. Sales reduce revenue.
        """
        if not confirm:
            return {
                "error": (
                    f"Refusing to create {percent_off}% sale on "
                    f"{len(listing_ids)} listings without confirm=True."
                ),
                "code": "validation_failed",
            }
        if not (1 <= percent_off <= 99):
            return {
                "error": "percent_off must be between 1 and 99.",
                "code": "validation_failed",
            }
        if not listing_ids:
            return {
                "error": "listing_ids list is empty.",
                "code": "validation_failed",
            }

        try:
            async with EtsyBrowser() as page:
                await page.goto(ETSY_DISCOUNTS_URL)
                if not await _ensure_logged_in(page):
                    return _session_expired_error()

                btn = page.locator(SELECTORS["discounts_create_sale_button_role"])
                if await btn.count() == 0:
                    screenshot = await _save_error_screenshot(page, "create_sale_button")
                    return _selector_missing_error("find 'Create a sale' button", screenshot)
                try:
                    await btn.first.click()
                except Exception:
                    screenshot = await _save_error_screenshot(page, "create_sale_click")
                    return _selector_missing_error("click 'Create a sale'", screenshot)

                try:
                    await page.locator(SELECTORS["discounts_percent_off_input_label"]).first.fill(str(percent_off))
                    await page.locator(SELECTORS["discounts_start_date_input_label"]).first.fill(start_iso)
                    await page.locator(SELECTORS["discounts_end_date_input_label"]).first.fill(end_iso)
                except Exception:
                    screenshot = await _save_error_screenshot(page, "create_sale_fill")
                    return _selector_missing_error("fill sale form fields", screenshot)

                save = page.locator(SELECTORS["discounts_save_button_role"])
                try:
                    await save.first.click()
                except Exception:
                    screenshot = await _save_error_screenshot(page, "create_sale_save")
                    return _selector_missing_error("click 'Save'", screenshot)

                cd = page.locator(SELECTORS["discounts_confirm_dialog_button_role"])
                if await cd.count() > 0:
                    await cd.first.click()

                return {
                    "created": True,
                    "percent_off": percent_off,
                    "listings_count": len(listing_ids),
                    "start": start_iso,
                    "end": end_iso,
                    "note": "Listing-selection within the dashboard UI may require manual review — verify in seller dashboard.",
                }
        except FileNotFoundError:
            return _session_expired_error()
        except EtsyMCPError as exc:
            return exc.to_dict()

    @mcp.tool()
    async def etsy_create_coupon(
        code: str,
        percent_off: int = 0,
        min_purchase_usd: float | None = None,
        free_shipping: bool = False,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Create a coupon code (percent-off OR free-shipping).

        Args:
            code: The coupon code buyers enter (e.g. "SUMMER25").
            percent_off: Discount percentage (0 if using free_shipping only).
            min_purchase_usd: Minimum order subtotal to qualify.
            free_shipping: If True, coupon grants free standard shipping.
                Mutually meaningful with percent_off — Etsy allows both.
            confirm: Must be True. Coupons reduce revenue.
        """
        if not confirm:
            return {
                "error": (
                    f"Refusing to create coupon '{code}' without confirm=True."
                ),
                "code": "validation_failed",
            }
        if not free_shipping and not (1 <= percent_off <= 99):
            return {
                "error": (
                    "Either percent_off (1-99) or free_shipping=True is required."
                ),
                "code": "validation_failed",
            }

        try:
            async with EtsyBrowser() as page:
                await page.goto(ETSY_DISCOUNTS_URL)
                if not await _ensure_logged_in(page):
                    return _session_expired_error()

                btn = page.locator(SELECTORS["discounts_create_coupon_button_role"])
                if await btn.count() == 0:
                    screenshot = await _save_error_screenshot(page, "create_coupon_button")
                    return _selector_missing_error("find 'Create a coupon' button", screenshot)
                try:
                    await btn.first.click()
                except Exception:
                    screenshot = await _save_error_screenshot(page, "create_coupon_click")
                    return _selector_missing_error("click 'Create a coupon'", screenshot)

                try:
                    await page.locator(SELECTORS["coupon_code_input_label"]).first.fill(code)
                except Exception:
                    screenshot = await _save_error_screenshot(page, "create_coupon_code")
                    return _selector_missing_error("fill coupon code", screenshot)

                if percent_off > 0:
                    try:
                        await page.locator(SELECTORS["discounts_percent_off_input_label"]).first.fill(str(percent_off))
                    except Exception:
                        screenshot = await _save_error_screenshot(page, "create_coupon_pct")
                        return _selector_missing_error("fill percent_off", screenshot)

                if min_purchase_usd is not None:
                    try:
                        await page.locator(SELECTORS["coupon_min_purchase_input_label"]).first.fill(f"{min_purchase_usd:.2f}")
                    except Exception:
                        pass  # Best-effort.

                if free_shipping:
                    try:
                        cb = page.locator(SELECTORS["coupon_free_shipping_checkbox_label"])
                        if await cb.count() > 0:
                            await cb.first.check()
                    except Exception:
                        pass

                save = page.locator(SELECTORS["discounts_save_button_role"])
                try:
                    await save.first.click()
                except Exception:
                    screenshot = await _save_error_screenshot(page, "create_coupon_save")
                    return _selector_missing_error("click 'Save'", screenshot)

                cd = page.locator(SELECTORS["discounts_confirm_dialog_button_role"])
                if await cd.count() > 0:
                    await cd.first.click()

                return {
                    "created": True,
                    "code": code,
                    "percent_off": percent_off,
                    "free_shipping": free_shipping,
                }
        except FileNotFoundError:
            return _session_expired_error()
        except EtsyMCPError as exc:
            return exc.to_dict()

    return {
        "etsy_ads_get_status": etsy_ads_get_status,
        "etsy_get_traffic_stats": etsy_get_traffic_stats,
        "etsy_ads_create_campaign": etsy_ads_create_campaign,
        "etsy_ads_set_budget": etsy_ads_set_budget,
        "etsy_ads_pause": etsy_ads_pause,
        "etsy_ads_resume": etsy_ads_resume,
        "etsy_update_listing_images_order": etsy_update_listing_images_order,
        "etsy_list_active_sales": etsy_list_active_sales,
        "etsy_create_sale": etsy_create_sale,
        "etsy_create_coupon": etsy_create_coupon,
    }
