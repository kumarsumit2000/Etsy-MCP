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
