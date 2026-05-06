"""Import Etsy cookies from your running Chrome → Playwright storage_state.json.

Use this when Etsy's bot detection blocks the normal
bootstrap_browser_login.py flow. You log into Etsy in your regular
Chrome browser (which doesn't get bot-detected), then run this script
to copy the cookies into Playwright's storage_state format.

Usage:
    python scripts/import_cookies_from_chrome.py
    python scripts/import_cookies_from_chrome.py --profile "Profile 2"
    python scripts/import_cookies_from_chrome.py --email user@example.com
    python scripts/import_cookies_from_chrome.py --list

Prerequisites:
    - You are logged into Etsy in your regular Chrome browser
    - macOS Keychain access is granted when prompted (Chrome stores
      cookies encrypted; the decryption key lives in Keychain)

Output:
    Writes .storage_state.json at the project root. Runtime browser
    tools then use this exactly as if you'd run bootstrap_browser_login.py.

Notes:
    - Chrome can stay open during this. browser_cookie3 copies the
      cookies DB to a temp location to avoid file-lock issues.
    - Re-run any time your Etsy session expires or after manual logout.
    - If you have multiple Chrome profiles, pass --profile or --email
      to target the right one. Use --list to see all profiles.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import browser_cookie3

ROOT = Path(__file__).resolve().parent.parent
STORAGE_PATH = ROOT / ".storage_state.json"

ETSY_DOMAINS = {".etsy.com", "www.etsy.com", "etsy.com"}

CHROME_USER_DATA_DIR = Path.home() / "Library/Application Support/Google/Chrome"


def _list_profiles() -> list[dict[str, str]]:
    """Return [{dir, name, email}] for every Chrome profile. Empty on failure."""
    local_state = CHROME_USER_DATA_DIR / "Local State"
    if not local_state.is_file():
        return []
    try:
        data = json.loads(local_state.read_text())
    except (ValueError, OSError):
        return []
    info_cache = data.get("profile", {}).get("info_cache", {})
    out = []
    for dir_name, info in info_cache.items():
        out.append(
            {
                "dir": dir_name,
                "name": info.get("name") or "",
                "email": info.get("user_name") or info.get("gaia_name") or "",
            }
        )
    return out


def _resolve_profile_dir(args: argparse.Namespace) -> str | None:
    """Map --profile or --email args to a Chrome profile directory name.
    Returns the dir name (e.g. 'Default' or 'Profile 2') or None if not found.
    """
    profiles = _list_profiles()
    if args.profile:
        for p in profiles:
            if p["dir"] == args.profile or p["name"] == args.profile:
                return p["dir"]
        return None
    if args.email:
        for p in profiles:
            if p["email"].lower() == args.email.lower():
                return p["dir"]
        return None
    return None  # No profile arg → caller falls back to default behavior


def _to_playwright_cookie(cj_cookie) -> dict:
    """Convert a CookieJar cookie (from browser_cookie3) to Playwright format."""
    expires = float(cj_cookie.expires) if cj_cookie.expires else -1.0
    same_site_raw = (cj_cookie._rest or {}).get("SameSite", "")
    if same_site_raw and isinstance(same_site_raw, str):
        ss = same_site_raw.capitalize()
        if ss not in ("Strict", "Lax", "None"):
            ss = "Lax"
    else:
        ss = "Lax"
    return {
        "name": cj_cookie.name,
        "value": cj_cookie.value or "",
        "domain": cj_cookie.domain,
        "path": cj_cookie.path or "/",
        "expires": expires,
        "httpOnly": bool(cj_cookie._rest.get("HttpOnly")) if cj_cookie._rest else False,
        "secure": bool(cj_cookie.secure),
        "sameSite": ss,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import Etsy cookies from a Chrome profile."
    )
    parser.add_argument(
        "--profile",
        help="Chrome profile dir name (e.g. 'Default', 'Profile 2') or display name",
    )
    parser.add_argument(
        "--email",
        help="Match Chrome profile by signed-in Google account email",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all Chrome profiles and exit (don't import)",
    )
    args = parser.parse_args()

    if args.list:
        profiles = _list_profiles()
        if not profiles:
            print("No Chrome profiles found.")
            return 0
        print(f"Found {len(profiles)} Chrome profile(s):\n")
        for p in profiles:
            print(f"  dir='{p['dir']}'  name='{p['name']}'  email='{p['email']}'")
        return 0

    cookie_file: str | None = None
    if args.profile or args.email:
        profile_dir = _resolve_profile_dir(args)
        if not profile_dir:
            print(
                f"ERROR: could not find Chrome profile matching --profile='{args.profile}' "
                f"--email='{args.email}'. Use --list to see profiles.",
                file=sys.stderr,
            )
            return 4
        cookie_file = str(CHROME_USER_DATA_DIR / profile_dir / "Cookies")
        print(f"Reading Etsy cookies from Chrome profile '{profile_dir}'...")
    else:
        print("Reading Etsy cookies from Chrome (default profile)...")

    try:
        kwargs = {"domain_name": "etsy.com"}
        if cookie_file:
            kwargs["cookie_file"] = cookie_file
        cj = browser_cookie3.chrome(**kwargs)
    except Exception as exc:
        print(
            f"ERROR: could not read Chrome cookies: {exc}\n"
            "If macOS prompted for Keychain access, click Always Allow and rerun.",
            file=sys.stderr,
        )
        return 2

    pw_cookies = []
    for c in cj:
        # Filter to etsy domains only — sanity check, browser_cookie3 should
        # already filter via domain_name= but defense in depth.
        if any(d in c.domain for d in ("etsy.com",)):
            pw_cookies.append(_to_playwright_cookie(c))

    if not pw_cookies:
        print(
            "ERROR: no Etsy cookies found in Chrome. Make sure you're logged "
            "into etsy.com in your Chrome browser, then rerun.",
            file=sys.stderr,
        )
        return 3

    storage_state = {"cookies": pw_cookies, "origins": []}

    STORAGE_PATH.write_text(json.dumps(storage_state, indent=2))
    # 0600 — same security posture as .tokens.json
    STORAGE_PATH.chmod(0o600)

    print(f"Wrote {len(pw_cookies)} cookies to {STORAGE_PATH}")
    print()
    print("=" * 60)
    print("  Done. Browser tools can now use this session.")
    print("  Test it: from Claude, ask 'Call etsy_ads_get_status'.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
