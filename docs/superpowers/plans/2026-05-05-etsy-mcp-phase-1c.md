# Etsy MCP — Phase 1c Implementation Plan (Browser Automation)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cover the seller dashboard tasks Etsy doesn't expose through the public API: enabling/managing Etsy Ads (4 tools) and reordering listing images (1 tool deferred from Phase 1b). Both share a Playwright session that's bootstrapped once interactively, then reused headlessly for runtime calls.

**Architecture:** New module `etsy_mcp/browser.py` exposes a single `EtsyBrowser` async context manager and a `register_browser_tools(mcp, ...)` factory. The browser uses Playwright's persistent `storage_state` (cookies + localStorage) saved during a one-time `scripts/bootstrap_browser_login.py` run. Selectors are centralized in a constants block at the top of `browser.py`, each annotated with a `Last verified:` date. On detected session expiry the tools return `{code: "session_expired"}`; on selector failure they return `{code: "selector_missing"}` with a screenshot path. `ETSY_ADS_HEADFUL=1` env switches to a visible browser for debugging.

**Tech Stack:** Python 3.10+, `playwright` (Chromium async API). The `playwright` Python package is a new runtime dependency. After `pip install`, the browser binary is fetched via `playwright install chromium` (one-time, ~150 MB).

**Spec:** `docs/superpowers/specs/2026-05-04-etsy-mcp-design.md` § 4.2, § 5.1 (Etsy Ads tools), § 9 (selector strategy)
**Predecessor plans:** `docs/superpowers/plans/2026-05-04-etsy-mcp-phase-0.md`, `docs/superpowers/plans/2026-05-05-etsy-mcp-phase-1a.md`, `docs/superpowers/plans/2026-05-05-etsy-mcp-phase-1b.md`

---

## Spec deviations

1. **Module name:** spec § 3.2 calls the module `ads_browser.py`. We name it `browser.py` because it also hosts `etsy_update_listing_images_order` (deferred from Phase 1b). All browser-driven tools share one module so the Playwright boilerplate (`EtsyBrowser` context manager, storage_state path, env-var handling, selector constants) lives in one place.
2. **Bootstrap script name:** spec § 4.2 calls it `bootstrap_ads_login.py`. Renamed to `bootstrap_browser_login.py` for the same reason — the saved session works for any seller-dashboard-driven tool, not just ads.
3. **Phase-1c scope addition:** the spec § 7 listed Phase 1c as "Etsy Ads browser (4 tools)". We add `etsy_update_listing_images_order` (5th tool, deferred from Phase 1b) since Etsy v3 has no rank-only image-update endpoint.

These are naming and bundling tweaks, not contract changes. The 4 ads tools, their signatures, and the storage-state file path (`.storage_state.json`) remain exactly as the spec specifies.

---

## Testability disclaimer

Browser-driven tools can't be meaningfully unit-tested against the real Etsy dashboard — Etsy's HTML changes, requires login, and has no public test environment. Per spec § 6.5, **browser tests are marked manual and skipped by default**. What we DO unit-test:

- Module imports cleanly
- Tools register on the FastMCP instance
- Storage-state-missing returns `session_expired` error
- Selector constants exist with the documented `Last verified:` comments
- Bootstrap script imports cleanly + preflight error path

Runtime correctness is verified manually after Etsy app approval (covered in Task 11).

---

## File Structure (Phase 1c only)

```
~/Desktop/Etsy MCP/
├── etsy_mcp/
│   └── browser.py        NEW — EtsyBrowser + register_browser_tools (5 tools)
├── scripts/
│   └── bootstrap_browser_login.py    NEW — one-time interactive login
├── tests/
│   └── unit/
│       └── test_browser.py    NEW — unit-testable bits only (selectors exist, error paths)
├── requirements.txt      MODIFIED — add playwright
├── .env.example          MODIFIED — add ETSY_ADS_HEADFUL hint
├── SETUP.md              MODIFIED — add Playwright install step + bootstrap browser login section
└── server.py             MODIFIED — register_browser_tools(...)
```

---

## Etsy seller dashboard URL reference

| Tool | URL |
|---|---|
| Sign-in (bootstrap) | `https://www.etsy.com/signin` |
| Dashboard root (login redirect target) | `https://www.etsy.com/your/shops/me/dashboard` |
| Etsy Ads | `https://www.etsy.com/your/shops/me/advertising` |
| Listing edit page (image reorder) | `https://www.etsy.com/your/shops/me/tools/listings/{listing_id}/edit` |

---

## Task 1: Add Playwright to deps + .env.example

**Files:**
- Modify: `requirements.txt`
- Modify: `.env.example`

- [ ] **Step 1: Read current requirements.txt**

```bash
cat "/Users/sumit/Desktop/Etsy MCP/requirements.txt"
```

You should see three lines (mcp, httpx, python-dotenv).

- [ ] **Step 2: Add playwright to requirements.txt**

Open `/Users/sumit/Desktop/Etsy MCP/requirements.txt` and append `playwright>=1.40.0`. The full file should be:

```
mcp[cli]>=1.2.0
httpx>=0.27.0
python-dotenv>=1.0.0
playwright>=1.40.0
```

- [ ] **Step 3: Install Playwright Python package and the Chromium binary**

```bash
cd "/Users/sumit/Desktop/Etsy MCP"
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Expected: pip installs playwright; `playwright install` downloads ~150 MB Chromium binary. The download is one-time per machine.

- [ ] **Step 4: Verify Playwright import works**

```bash
.venv/bin/python -c "from playwright.async_api import async_playwright; print('OK')"
```

Expected: `OK`.

- [ ] **Step 5: Add ETSY_ADS_HEADFUL hint to .env.example**

Open `/Users/sumit/Desktop/Etsy MCP/.env.example` and append (after the existing `ETSY_OAUTH_REDIRECT_PORT` line):

```

# Browser automation (Phase 1c). Set to 1 to launch a visible browser
# instead of headless — useful for debugging when selectors break.
ETSY_ADS_HEADFUL=0
```

- [ ] **Step 6: Run the test suite to confirm no regression**

```bash
.venv/bin/pytest -v 2>&1 | tail -3
```

Expected: 95 passed (Phase 1b baseline; this task adds no new tests).

- [ ] **Step 7: Commit**

```bash
git add requirements.txt .env.example
git commit -m "$(cat <<'EOF'
chore(deps): add playwright for Phase 1c browser automation

Bumps requirements.txt with playwright>=1.40.0. The browser binary
itself is fetched via 'playwright install chromium' as a one-time
~150MB download — documented in SETUP.md (next task).

ETSY_ADS_HEADFUL=0 added to .env.example as a hint for the env-var
that switches the runtime browser to visible mode for debugging.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Bootstrap browser login script

**Files:**
- Create: `scripts/bootstrap_browser_login.py`

This is a CLI script the user runs ONCE to log into Etsy interactively. It opens a visible Chromium window via Playwright, waits until the URL indicates a successful login (any `/your/shops/me/...` page), then saves cookies + localStorage to `.storage_state.json` for runtime tools to reuse.

- [ ] **Step 1: Write `scripts/bootstrap_browser_login.py`**

Create with this exact content:

```python
"""One-time Etsy seller-dashboard login bootstrap.

Usage:
    python scripts/bootstrap_browser_login.py

What happens:
    1. Launches a visible Chromium window via Playwright.
    2. Navigates to https://www.etsy.com/signin.
    3. Waits up to 5 minutes for you to log in (handle 2FA, captcha, etc.).
    4. Detects success when the URL contains '/your/shops/me/'.
    5. Saves cookies + localStorage to .storage_state.json.
    6. Closes the browser.

Re-run any time the saved session expires (cookies typically last weeks).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
STORAGE_PATH = ROOT / ".storage_state.json"

ETSY_SIGNIN_URL = "https://www.etsy.com/signin"
LOGIN_SUCCESS_URL_FRAGMENT = "/your/shops/me/"
TIMEOUT_SECONDS = 300  # 5 min for the user to handle 2FA / captcha


async def _wait_for_login(page) -> bool:
    """Poll page.url until it contains /your/shops/me/ or timeout elapses."""
    deadline = asyncio.get_event_loop().time() + TIMEOUT_SECONDS
    while asyncio.get_event_loop().time() < deadline:
        url = page.url
        if LOGIN_SUCCESS_URL_FRAGMENT in url:
            return True
        await asyncio.sleep(1.0)
    return False


async def main() -> int:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        print(f"Opening {ETSY_SIGNIN_URL} ...")
        await page.goto(ETSY_SIGNIN_URL)
        print()
        print("=" * 60)
        print("  Log into Etsy in the browser window.")
        print(f"  This script will detect success and exit when the URL")
        print(f"  contains '{LOGIN_SUCCESS_URL_FRAGMENT}'.")
        print(f"  Timeout: {TIMEOUT_SECONDS} seconds.")
        print("=" * 60)
        print()

        ok = await _wait_for_login(page)
        if not ok:
            print(
                f"ERROR: timed out waiting for login (URL never contained "
                f"'{LOGIN_SUCCESS_URL_FRAGMENT}'). Closing browser.",
                file=sys.stderr,
            )
            await context.close()
            await browser.close()
            return 2

        print(f"Login detected. Saving session to {STORAGE_PATH} ...")
        await context.storage_state(path=str(STORAGE_PATH))

        await context.close()
        await browser.close()

        print("Done. Browser tools can now run in headless mode.")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 2: Verify the script imports cleanly**

```bash
cd "/Users/sumit/Desktop/Etsy MCP"
.venv/bin/python -c "import scripts.bootstrap_browser_login; print('OK')"
```

Expected: `OK`.

- [ ] **Step 3: Run the full test suite to ensure no regression**

```bash
.venv/bin/pytest -v 2>&1 | tail -3
```

Expected: 95 passed.

- [ ] **Step 4: Commit**

```bash
git add scripts/bootstrap_browser_login.py
git commit -m "$(cat <<'EOF'
feat(scripts): one-time browser-login bootstrap for Phase 1c

Launches a visible Chromium window via Playwright, navigates to
etsy.com/signin, polls page.url until the user has reached any
/your/shops/me/ page (success), then saves cookies + localStorage
to .storage_state.json. Times out after 5 minutes if the user
doesn't complete login.

The interactive login lets the user handle 2FA + captcha
themselves; subsequent runtime browser tools use the saved
storage_state to launch headless without human interaction.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: browser.py — EtsyBrowser context manager + selector constants

**Files:**
- Create: `etsy_mcp/browser.py`
- Create: `tests/unit/test_browser.py`

This task scaffolds the module: the `EtsyBrowser` async context manager, the centralized selector constants block, and the `register_browser_tools` factory (with no tools yet — they're added in Tasks 4-8).

- [ ] **Step 1: Write the failing test**

Create `/Users/sumit/Desktop/Etsy MCP/tests/unit/test_browser.py`:

```python
"""Tests for etsy_mcp.browser tools (unit-testable bits only).

End-to-end browser tests run against the real Etsy dashboard and are
verified manually (see plan Task 11). This file covers:
- module imports cleanly
- selector constants exist with required keys
- register_browser_tools returns the expected callables
- session-expired error path when .storage_state.json is missing
"""

from __future__ import annotations

import pytest


def test_browser_module_imports():
    import etsy_mcp.browser  # noqa: F401


def test_selectors_block_exists():
    from etsy_mcp.browser import SELECTORS

    # Each value should be a non-empty string
    assert isinstance(SELECTORS, dict)
    assert len(SELECTORS) >= 1


def test_register_browser_tools_returns_dict(make_tools):
    from etsy_mcp.browser import register_browser_tools

    tools = make_tools(register_browser_tools, shop_id="42")
    assert isinstance(tools, dict)
    # Tools added in later tasks; for Task 3 we just verify the factory
    # returns SOMETHING dict-shaped without errors.


async def test_browser_tool_returns_session_expired_when_storage_missing(make_tools, tmp_path, monkeypatch):
    """If .storage_state.json doesn't exist, every browser tool short-circuits
    with a session_expired error rather than crashing.
    """
    from etsy_mcp.browser import register_browser_tools, _STORAGE_STATE_PATH_ENV

    # Point the storage-state path at a file that doesn't exist
    monkeypatch.setenv(_STORAGE_STATE_PATH_ENV, str(tmp_path / "no-such-file.json"))

    tools = make_tools(register_browser_tools, shop_id="42")
    # Until tools are added, this test is a placeholder. We can't call any tool.
    # Once Task 4+ adds tools, the same fixture can be used to verify the
    # missing-storage error path.
    assert isinstance(tools, dict)
```

- [ ] **Step 2: Run test to verify failure**

```bash
.venv/bin/pytest tests/unit/test_browser.py -v
```

Expected: FAIL — `cannot import name 'register_browser_tools' from 'etsy_mcp.browser'` (module doesn't exist).

- [ ] **Step 3: Write `etsy_mcp/browser.py`**

Create with this exact content:

```python
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
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_browser.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 99 passed (95 baseline + 4 new).

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/browser.py tests/unit/test_browser.py
git commit -m "$(cat <<'EOF'
feat(browser): EtsyBrowser context manager + selector constants block

New module scaffolding for Phase 1c browser-driven tools. EtsyBrowser
is an async context manager that launches Chromium (headless by
default; ETSY_ADS_HEADFUL=1 makes it visible), loads the saved
.storage_state.json cookies, and yields a Page object.

SELECTORS dict centralizes every selector with 'Last verified: DATE'
comments — the only place to update when Etsy redesigns the dashboard.

Helpers _session_expired_error and _selector_missing_error return
the structured error shape every tool uses on the two main failure
paths. _save_error_screenshot dumps the current page on selector
failure so the user has visual evidence of what changed.

register_browser_tools factory exists with no tools yet — they're
added in tasks 4-8. The factory accepts keystring/tokens_path for
signature symmetry with other register_*_tools factories even though
browser tools don't hit the API.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: etsy_ads_get_status

**Files:**
- Modify: `etsy_mcp/browser.py`
- Modify: `tests/unit/test_browser.py`

This is the simplest read-only ads tool — it just navigates to the ads page and reads the current state. No clicks, no input, no confirmation.

- [ ] **Step 1: Append failing test**

Append to `tests/unit/test_browser.py`:

```python
async def test_ads_get_status_returns_session_expired_when_storage_missing(make_tools, tmp_path, monkeypatch):
    from etsy_mcp.browser import register_browser_tools, _STORAGE_STATE_PATH_ENV

    monkeypatch.setenv(_STORAGE_STATE_PATH_ENV, str(tmp_path / "no-such-file.json"))

    tools = make_tools(register_browser_tools, shop_id="42")
    assert "etsy_ads_get_status" in tools

    result = await tools["etsy_ads_get_status"]()

    assert result["code"] == "session_expired"
    assert "bootstrap_browser_login.py" in result["error"]
```

- [ ] **Step 2: Run tests to verify failure**

```bash
.venv/bin/pytest tests/unit/test_browser.py::test_ads_get_status_returns_session_expired_when_storage_missing -v
```

Expected: FAIL — `etsy_ads_get_status` not in tools dict.

- [ ] **Step 3: Add the tool**

In `/Users/sumit/Desktop/Etsy MCP/etsy_mcp/browser.py`, REPLACE the `register_browser_tools` body (currently `return {}`) with:

```python
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

    return {
        "etsy_ads_get_status": etsy_ads_get_status,
    }
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_browser.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 100 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/browser.py tests/unit/test_browser.py
git commit -m "$(cat <<'EOF'
feat(browser): etsy_ads_get_status

First Phase 1c browser tool. Navigates to /your/shops/me/advertising,
detects ads on/off by checking for either "Turn on Etsy Ads" or
"Pause" button, reads the daily budget input when enabled, and
best-effort reads the last-30d stats panel (spend, clicks, impressions,
orders, revenue) from data-test-id selectors.

Returns session_expired if .storage_state.json is missing or Etsy
redirects to /signin; selector_missing with a screenshot path if
neither on/off button can be detected (UI changed).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: etsy_ads_create_campaign

**Files:**
- Modify: `etsy_mcp/browser.py`
- Modify: `tests/unit/test_browser.py`

Turns Etsy Ads on with a specified daily budget. Refuses unless `confirm=True`.

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_browser.py`:

```python
async def test_ads_create_campaign_requires_confirm(make_tools):
    from etsy_mcp.browser import register_browser_tools

    tools = make_tools(register_browser_tools, shop_id="42")
    result = await tools["etsy_ads_create_campaign"](daily_budget_usd=10.0)

    assert result["code"] == "validation_failed"
    assert "confirm" in result["error"].lower()


async def test_ads_create_campaign_session_expired(make_tools, tmp_path, monkeypatch):
    from etsy_mcp.browser import register_browser_tools, _STORAGE_STATE_PATH_ENV

    monkeypatch.setenv(_STORAGE_STATE_PATH_ENV, str(tmp_path / "no-such-file.json"))

    tools = make_tools(register_browser_tools, shop_id="42")
    result = await tools["etsy_ads_create_campaign"](
        daily_budget_usd=10.0,
        confirm=True,
    )

    assert result["code"] == "session_expired"
```

- [ ] **Step 2: Run tests to verify failure**

```bash
.venv/bin/pytest tests/unit/test_browser.py::test_ads_create_campaign_requires_confirm -v
```

Expected: FAIL — `etsy_ads_create_campaign` not registered.

- [ ] **Step 3: Add the tool**

INSIDE `register_browser_tools` (after `etsy_ads_get_status`, before the return dict), add:

```python
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
```

UPDATE the return dict to include `etsy_ads_create_campaign`.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_browser.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 102 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/browser.py tests/unit/test_browser.py
git commit -m "$(cat <<'EOF'
feat(browser): etsy_ads_create_campaign

Enables Etsy Ads with a specified daily budget. Three guards:
- confirm=True required (real money, prevent accidental enable)
- daily_budget_usd must be positive
- if 'Turn on Etsy Ads' button is absent (ads already on), returns
  a clear error pointing the caller at etsy_ads_set_budget

Each click/fill is wrapped: failure → screenshot + selector_missing
error so the user sees exactly which step broke when Etsy redesigns
the dashboard.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: etsy_ads_set_budget

**Files:**
- Modify: `etsy_mcp/browser.py`
- Modify: `tests/unit/test_browser.py`

Modifies the daily budget on an already-enabled Etsy Ads campaign.

- [ ] **Step 1: Append failing test**

Append to `tests/unit/test_browser.py`:

```python
async def test_ads_set_budget_session_expired(make_tools, tmp_path, monkeypatch):
    from etsy_mcp.browser import register_browser_tools, _STORAGE_STATE_PATH_ENV

    monkeypatch.setenv(_STORAGE_STATE_PATH_ENV, str(tmp_path / "no-such-file.json"))

    tools = make_tools(register_browser_tools, shop_id="42")
    result = await tools["etsy_ads_set_budget"](daily_budget_usd=15.0)
    assert result["code"] == "session_expired"


async def test_ads_set_budget_validates_positive(make_tools):
    from etsy_mcp.browser import register_browser_tools

    tools = make_tools(register_browser_tools, shop_id="42")
    result = await tools["etsy_ads_set_budget"](daily_budget_usd=0.0)
    assert result["code"] == "validation_failed"

    result = await tools["etsy_ads_set_budget"](daily_budget_usd=-5.0)
    assert result["code"] == "validation_failed"
```

- [ ] **Step 2: Run tests to verify failure**

```bash
.venv/bin/pytest tests/unit/test_browser.py::test_ads_set_budget_session_expired -v
```

Expected: FAIL.

- [ ] **Step 3: Add the tool**

INSIDE `register_browser_tools` (after `etsy_ads_create_campaign`, before the return), add:

```python
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
```

UPDATE the return dict to include `etsy_ads_set_budget`.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_browser.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 104 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/browser.py tests/unit/test_browser.py
git commit -m "$(cat <<'EOF'
feat(browser): etsy_ads_set_budget

Modifies the daily budget on an already-enabled Etsy Ads campaign.
Refuses non-positive budgets. If "Edit budget" button is absent
(meaning ads are off), returns a clear error pointing the caller
to etsy_ads_create_campaign.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: etsy_ads_pause + etsy_ads_resume

**Files:**
- Modify: `etsy_mcp/browser.py`
- Modify: `tests/unit/test_browser.py`

Two tools — pause and resume — share the same dashboard pattern (click a single button, no input).

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_browser.py`:

```python
async def test_ads_pause_session_expired(make_tools, tmp_path, monkeypatch):
    from etsy_mcp.browser import register_browser_tools, _STORAGE_STATE_PATH_ENV

    monkeypatch.setenv(_STORAGE_STATE_PATH_ENV, str(tmp_path / "no-such-file.json"))

    tools = make_tools(register_browser_tools, shop_id="42")
    result = await tools["etsy_ads_pause"]()
    assert result["code"] == "session_expired"


async def test_ads_resume_session_expired(make_tools, tmp_path, monkeypatch):
    from etsy_mcp.browser import register_browser_tools, _STORAGE_STATE_PATH_ENV

    monkeypatch.setenv(_STORAGE_STATE_PATH_ENV, str(tmp_path / "no-such-file.json"))

    tools = make_tools(register_browser_tools, shop_id="42")
    result = await tools["etsy_ads_resume"]()
    assert result["code"] == "session_expired"
```

- [ ] **Step 2: Run tests to verify failure**

```bash
.venv/bin/pytest tests/unit/test_browser.py::test_ads_pause_session_expired -v
```

Expected: FAIL.

- [ ] **Step 3: Add the tools**

INSIDE `register_browser_tools` (after `etsy_ads_set_budget`, before the return), add:

```python
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
```

UPDATE the return dict to include both tools.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_browser.py -v
```

Expected: 11 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 106 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/browser.py tests/unit/test_browser.py
git commit -m "$(cat <<'EOF'
feat(browser): etsy_ads_pause + etsy_ads_resume

Toggle Etsy Ads on/off by clicking the Pause/Resume button on the
seller dashboard. Both share a private _toggle_ads helper so the
pattern (navigate → ensure-logged-in → locate button → click →
optional confirm dialog) lives in exactly one place.

If the expected button is absent (e.g. trying to Pause when ads
are already off), returns validation_failed rather than crashing —
common case for users who don't know the current state.

Etsy Ads tooling for Phase 1c is now complete: get_status,
create_campaign, set_budget, pause, resume.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: etsy_update_listing_images_order

**Files:**
- Modify: `etsy_mcp/browser.py`
- Modify: `tests/unit/test_browser.py`

Reorders images on a listing via the seller-dashboard listing-edit page. Etsy v3 has no rank-only update endpoint, so this is the only Phase 1b/c path.

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_browser.py`:

```python
async def test_update_listing_images_order_session_expired(make_tools, tmp_path, monkeypatch):
    from etsy_mcp.browser import register_browser_tools, _STORAGE_STATE_PATH_ENV

    monkeypatch.setenv(_STORAGE_STATE_PATH_ENV, str(tmp_path / "no-such-file.json"))

    tools = make_tools(register_browser_tools, shop_id="42")
    result = await tools["etsy_update_listing_images_order"](
        listing_id=777,
        image_ids=[1, 2, 3],
    )
    assert result["code"] == "session_expired"


async def test_update_listing_images_order_empty_image_ids_rejected(make_tools):
    from etsy_mcp.browser import register_browser_tools

    tools = make_tools(register_browser_tools, shop_id="42")
    result = await tools["etsy_update_listing_images_order"](
        listing_id=777,
        image_ids=[],
    )
    assert result["code"] == "validation_failed"
    assert "empty" in result["error"].lower() or "at least one" in result["error"].lower()
```

- [ ] **Step 2: Run tests to verify failure**

```bash
.venv/bin/pytest tests/unit/test_browser.py::test_update_listing_images_order_session_expired -v
```

Expected: FAIL.

- [ ] **Step 3: Add the tool**

INSIDE `register_browser_tools` (after `etsy_ads_resume`, before the return), add:

```python
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
```

UPDATE the return dict to include `etsy_update_listing_images_order`.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_browser.py -v
```

Expected: 13 passed.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 108 passed.

- [ ] **Step 6: Commit**

```bash
git add etsy_mcp/browser.py tests/unit/test_browser.py
git commit -m "$(cat <<'EOF'
feat(browser): etsy_update_listing_images_order

Reorders images on a listing via the seller-dashboard edit page —
the only path because Etsy v3 has no rank-only image-update endpoint.
Implementation evaluates in-page JavaScript to rearrange DOM nodes
keyed by data-listing-image-id, then clicks "Save and continue".
DOM rearrangement is more reliable than simulating drag-and-drop
(which Etsy's UI debounces heavily).

This was deferred from Phase 1b. Browser module now has 5 tools:
4 ads + this one image-reorder.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: server.py — register browser tools

**Files:**
- Modify: `server.py`

- [ ] **Step 1: Add the import**

Open `/Users/sumit/Desktop/Etsy MCP/server.py`. Find the import block:

```python
from etsy_mcp.exports import register_export_tools
from etsy_mcp.listings import register_listing_tools
from etsy_mcp.receipts import register_receipt_tools
from etsy_mcp.reviews import register_review_tools
from etsy_mcp.shop import register_shop_tools
from etsy_mcp.taxonomy import register_taxonomy_tools
```

REPLACE with (alphabetical):

```python
from etsy_mcp.browser import register_browser_tools
from etsy_mcp.exports import register_export_tools
from etsy_mcp.listings import register_listing_tools
from etsy_mcp.receipts import register_receipt_tools
from etsy_mcp.reviews import register_review_tools
from etsy_mcp.shop import register_shop_tools
from etsy_mcp.taxonomy import register_taxonomy_tools
```

- [ ] **Step 2: Add the register call**

Find the existing register-calls block. The last call is currently:

```python
register_export_tools(
    mcp,
    keystring=KEYSTRING,
    tokens_path=TOKENS_PATH,
    shop_id_getter=_shop_id,
)
```

APPEND immediately after it:

```python
register_browser_tools(
    mcp,
    keystring=KEYSTRING,
    tokens_path=TOKENS_PATH,
    shop_id_getter=_shop_id,
)
```

- [ ] **Step 3: Verify imports**

```bash
cd "/Users/sumit/Desktop/Etsy MCP"
ETSY_KEYSTRING=test_placeholder .venv/bin/python -c "import server; print('OK')"
```

Expected: `OK`.

- [ ] **Step 4: Verify the server starts without crashing**

```bash
ETSY_KEYSTRING=test_placeholder timeout 3 .venv/bin/python server.py 2>&1 | head -20 || true
```

Expected: starts and waits for stdio. No traceback.

- [ ] **Step 5: Run full test suite**

```bash
.venv/bin/pytest -v
```

Expected: 108 passed.

- [ ] **Step 6: Commit**

```bash
git add server.py
git commit -m "$(cat <<'EOF'
feat(server): wire up Phase 1c browser tools

Calls register_browser_tools at module load alongside the existing
six register factories. After this change the FastMCP instance
exposes all 28 tools across phases 0/1a/1b/1c: 23 API-driven from
prior phases + 5 browser-driven (4 Etsy Ads + 1 listing image
reorder).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: SETUP.md — Phase 1c installation + bootstrap walkthrough

**Files:**
- Modify: `SETUP.md`

- [ ] **Step 1: Append the Phase 1c section to SETUP.md**

Open `/Users/sumit/Desktop/Etsy MCP/SETUP.md` and append at the END:

```markdown

## 7. Browser tools (Phase 1c)

Five tools require a Playwright-driven session because Etsy doesn't expose
their data through the public API:
- `etsy_ads_get_status`, `etsy_ads_create_campaign`, `etsy_ads_set_budget`,
  `etsy_ads_pause`, `etsy_ads_resume`
- `etsy_update_listing_images_order`

### One-time setup

1. Install the Chromium binary (after `pip install -r requirements.txt`):
   ```bash
   playwright install chromium
   ```
   Downloads ~150 MB. One-time per machine.

2. Run the browser-login bootstrap:
   ```bash
   source .venv/bin/activate
   python scripts/bootstrap_browser_login.py
   ```
   - A real Chromium window opens at https://www.etsy.com/signin.
   - Log in normally. Handle 2FA / captcha as Etsy presents them.
   - When the URL switches to a `/your/shops/me/...` page the script
     detects success and saves the session to `.storage_state.json`.
   - The window closes automatically.

3. From this point, runtime browser tools launch headless Chromium with
   the saved cookies. Re-run the bootstrap whenever a tool returns
   `{"code": "session_expired", ...}` (typically every few weeks).

### Debugging selector failures

If a tool returns `{"code": "selector_missing", "screenshot_path": "/tmp/..."}`,
Etsy redesigned that part of the dashboard. The screenshot shows the new
layout; update the relevant entry in `SELECTORS` at the top of
`etsy_mcp/browser.py` and bump the `Last verified:` date.

You can also rerun any browser tool with a visible browser by setting:

```
ETSY_ADS_HEADFUL=1
```

in `.env`, which makes the runtime browser non-headless so you can watch
exactly what's happening.
```

- [ ] **Step 2: Verify SETUP.md is well-formed**

```bash
cat "/Users/sumit/Desktop/Etsy MCP/SETUP.md" | tail -50
```

You should see the new section.

- [ ] **Step 3: Run the test suite to confirm no regression**

```bash
cd "/Users/sumit/Desktop/Etsy MCP"
.venv/bin/pytest -v 2>&1 | tail -3
```

Expected: 108 passed.

- [ ] **Step 4: Commit**

```bash
git add SETUP.md
git commit -m "$(cat <<'EOF'
docs(setup): Phase 1c — Playwright install + browser-login walkthrough

New section 7 covers:
- 'playwright install chromium' (one-time ~150MB download)
- bootstrap_browser_login.py interactive login flow
- session_expired error → re-run bootstrap
- selector_missing error → update SELECTORS in browser.py
- ETSY_ADS_HEADFUL=1 for visible-browser debugging

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Final verification + push

- [ ] **Step 1: Run the full test suite**

```bash
cd "/Users/sumit/Desktop/Etsy MCP"
.venv/bin/pytest -v 2>&1 | tail -3
```

Expected: 108 passed (13 new from Phase 1c on top of 95 from prior phases).

- [ ] **Step 2: Verify all 28 tools register on the FastMCP instance**

```bash
ETSY_KEYSTRING=test_placeholder .venv/bin/python <<'PY'
import asyncio
import server

async def main():
    tools = await server.mcp.list_tools()
    names = sorted(t.name for t in tools)
    expected = sorted([
        # Phase 0
        "etsy_whoami", "etsy_token_status",
        # Phase 1a
        "etsy_get_shop", "etsy_get_shop_stats",
        "etsy_list_listings", "etsy_search_listings", "etsy_get_listing",
        "etsy_get_listing_inventory", "etsy_get_listing_images",
        "etsy_list_receipts", "etsy_get_receipt", "etsy_get_receipt_transactions",
        "etsy_list_shop_payments",
        "etsy_list_reviews",
        # Phase 1b
        "etsy_create_draft_listing", "etsy_update_listing", "etsy_delete_listing",
        "etsy_upload_listing_image", "etsy_update_listing_inventory",
        "etsy_taxonomy_search",
        "etsy_export_all_listings", "etsy_export_all_receipts", "etsy_export_all_reviews",
        # Phase 1c
        "etsy_ads_get_status", "etsy_ads_create_campaign", "etsy_ads_set_budget",
        "etsy_ads_pause", "etsy_ads_resume",
        "etsy_update_listing_images_order",
    ])
    print(f"registered count: {len(names)}")
    print(f"expected count:   {len(expected)}")
    assert names == expected, f"missing: {set(expected) - set(names)}; extra: {set(names) - set(expected)}"
    print("OK — all 28 tools registered")

asyncio.run(main())
PY
```

Expected: prints `OK — all 28 tools registered`.

- [ ] **Step 3: Confirm no secrets staged or in history**

```bash
git status --ignored | grep -E "\.env$|\.tokens\.json|logs/|\.storage_state" || true
git diff --staged
git log --all --full-history -- .env .tokens.json .storage_state.json
```

Expected: ignored files listed; no staged diff; no history of secrets. STOP if any leak.

- [ ] **Step 4: List local commits ahead of origin**

```bash
git log --oneline origin/main..HEAD
```

Expected: 10 new commits (Tasks 1-10). Wait for the user to say "push" before running `git push origin main`.

- [ ] **Step 5: Manual acceptance criteria (post-Etsy-approval)**

Phase 1c is fully accepted when:

1. ✓ `pytest` is green (108 passing) — verified by Step 1
2. ✓ All 28 tools registered — verified by Step 2
3. (Manual) `python scripts/bootstrap_browser_login.py` completes; `.storage_state.json` is created
4. (Manual) From Claude: `etsy_ads_get_status` returns the real status of your Etsy Ads
5. (Manual) From Claude: `etsy_ads_create_campaign(daily_budget_usd=1.00, confirm=True)` enables ads with a $1 daily budget (you can pause immediately afterward to avoid spend)
6. (Manual) From Claude: `etsy_ads_pause()` then `etsy_ads_resume()` toggles state correctly
7. (Manual) From Claude: `etsy_update_listing_images_order(listing_id=<real_id>, image_ids=[<id2>, <id1>])` reorders the first two images on a real listing

Items 1–2 are the bar for shipping the code. Items 3–7 unlock when the
Etsy app is approved AND the user has run the browser-login bootstrap.
If any of items 4–7 fails with `selector_missing`, the screenshot in
`/tmp/etsy_browser_error_*.png` shows what changed; update SELECTORS at
the top of `etsy_mcp/browser.py` and bump `Last verified:` to today's date.

---

## Spec coverage check (Phase 1c only)

| Spec § 5.1 / § 4.2 / § 7 requirement | Task |
|---|---|
| `etsy_ads_get_status` | Task 4 |
| `etsy_ads_create_campaign(daily_budget_usd, confirm=False)` | Task 5 |
| `etsy_ads_set_budget(daily_budget_usd)` | Task 6 |
| `etsy_ads_pause` / `etsy_ads_resume` | Task 7 |
| `etsy_update_listing_images_order` (deferred from Phase 1b) | Task 8 |
| Bootstrap script writes `.storage_state.json` after interactive login | Task 2 |
| Selectors centralized with `Last verified:` comments | Task 3 (`SELECTORS` block) |
| `getByRole`/`getByLabel`/text selectors preferred over CSS classes | Task 3 (selectors use `:has-text()` / labels / data-test-id) |
| `session_expired` error when redirected to /signin | Task 3 (`_ensure_logged_in`) |
| `selector_missing` error includes screenshot path | Task 3 (`_save_error_screenshot`) |
| `ETSY_ADS_HEADFUL=1` switches to visible browser | Task 3 (`_is_headful`) |
| `confirm=True` required for `etsy_ads_create_campaign` | Task 5 |
| Tools wrap any internal exception → structured-error dict | Every browser task |

**Out of scope for Phase 1c (Phase 2+):**
- Mark-shipped, refund, bulk-ship (Tier 2)
- Shipping profiles / shop sections / return policies (Tier 2)
- Bulk inventory updates (Tier 2)
- Listing duplicate / templates (Tier 3)
- Sales / coupons (Tier 3)
- Reporting (Tier 3)
