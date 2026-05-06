# Etsy MCP — Setup Walkthrough

Step-by-step guide for getting this running on a fresh machine. Should
take about 10 minutes end-to-end.

## Prerequisites

- macOS or Linux (Windows works for the API tools, but the Chrome
  cookie-import script targets macOS first; Linux/WSL has separate
  paths in `browser_cookie3` that should still work)
- **Python 3.10+** — verify with `python3 --version`
- **Google Chrome** with the seller account already logged into etsy.com
  (the same account whose shop you want this MCP to act on)
- **Claude Code** — `brew install --cask claude` or download from
  https://claude.com/download

---

## 1. Clone & install

```bash
cd ~/Desktop
git clone https://github.com/kumarsumit2000/Etsy-MCP.git
cd Etsy-MCP

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Chromium for the browser-driven tools (one-time download, ~150 MB)
playwright install chromium
```

---

## 2. Create an Etsy developer app

1. Go to https://www.etsy.com/developers/your-apps and sign in.
2. Accept the API terms if prompted.
3. Click **Create a New App** and fill in:
   - **Name:** anything (e.g. *"Etsy MCP — Personal"*)
   - **Description:** *"Personal MCP server for managing my shop"*
   - **Website:** any URL you control (or `http://localhost`)
   - **What kind of app:** *"I'm building an app for myself"*
4. After creation you'll see a **Keystring** and a **Shared Secret**. Copy both — you'll paste them into `.env` in the next step.
5. Click **Edit** on the app, scroll to **Callback URL(s)**, and add this exact value:
   ```
   http://localhost:3003/callback
   ```
   No trailing slash. Must be `http://`, not `https://`. Save.

If Etsy rejects `http://localhost:...` URIs on your account, you can
use a public Cloudflare quick tunnel instead — see
[§ "Using a Cloudflare tunnel for OAuth"](#using-a-cloudflare-tunnel-for-oauth)
at the bottom.

---

## 3. Configure `.env`

```bash
cp .env.example .env
```

Open `.env` and fill in:

```env
ETSY_KEYSTRING=<paste keystring from step 2>
ETSY_SHARED_SECRET=<paste shared secret from step 2>

# Leave blank for now — step 4 will print this and you'll come back
ETSY_SHOP_ID=

# Your shop's home timezone — used to bucket "today" / "this week" reports.
# Default: America/Denver (Mountain Time, with DST). Use America/Phoenix for
# Arizona (strict MST, no DST). Other examples: America/New_York,
# Europe/London, Asia/Kolkata, Australia/Sydney.
ETSY_SHOP_TIMEZONE=America/Denver
```

---

## 4. Run the OAuth bootstrap

```bash
source .venv/bin/activate
python scripts/bootstrap_oauth.py
```

What happens:

1. Script generates a PKCE challenge and starts a localhost callback server on port 3003.
2. Your default browser opens to Etsy's authorize page.
3. You click **Allow Access**.
4. Etsy redirects to `localhost:3003/callback` with an auth code; the script captures it.
5. Code is exchanged for an access + refresh token, written to `.tokens.json`.
6. Script calls `/users/me` and `/users/{id}/shops` to look up your numeric `shop_id` and prints it.

Take the printed `shop_id` and paste it into `.env`:

```env
ETSY_SHOP_ID=<paste here>
```

---

## 5. Connect your Etsy session (for browser-driven tools)

Some features (buyer messages, Etsy Ads, sales/coupons, image reorder)
aren't in Etsy's public API at all — they only exist on the seller
dashboard. We drive that via Playwright using your existing Etsy
session cookies.

**Easiest path: pull cookies from Chrome.**

1. Make sure Chrome is logged into etsy.com with the seller account
   (verify by visiting https://www.etsy.com/your/shops/me/dashboard).
2. List your Chrome profiles:
   ```bash
   python scripts/import_cookies_from_chrome.py --list
   ```
3. Import cookies from the right profile (matched by signed-in Google email):
   ```bash
   python scripts/import_cookies_from_chrome.py --email you@yourcompany.com
   ```
4. macOS will prompt for **Keychain access** (Chrome's cookies are encrypted; we need the local key to read them). Click **Always Allow**.
5. Script writes `.storage_state.json` and confirms `Wrote N cookies`.

**Alternate path:** if Chrome import fails or you'd rather log in
manually, run:

```bash
python scripts/bootstrap_browser_login.py
```

A real Chromium window opens; log into Etsy normally (handle 2FA /
captcha as Etsy presents them); when you land on the dashboard the
script auto-detects success and saves the session.

Note: Etsy aggressively bot-detects Playwright login flows and may
loop you at captcha — the cookie-import path is strictly more reliable.

---

## 6. Register with Claude Code

One command, no config files:

```bash
claude mcp add etsy -s user -- "$(pwd)/.venv/bin/python" "$(pwd)/server.py"
```

(Run this from inside the `Etsy-MCP` directory so `$(pwd)` resolves correctly.)

`-s user` registers it globally for your account; drop that flag if you only want it in the current project.

Verify:

```bash
claude mcp list
```

You should see:

```
etsy: /Users/.../Etsy-MCP/.venv/bin/python /Users/.../Etsy-MCP/server.py - ✓ Connected
```

---

## 7. Restart Claude Code and test

Quit Claude Code completely, then reopen. In any chat, ask:

> *Call etsy_whoami*

You should see something like:

```json
{
  "user_id": 12345678,
  "shop_id": 31937130,
  "shop_name": "YourShop"
}
```

That's it — the 55 tools are now available in every Claude Code chat
on this machine.

---

## Things to ask Claude once it's running

- *"How many orders today and total revenue?"*
- *"Any unread buyer messages older than 2 hours?"*
- *"Show me my top 10 listings by units this month"*
- *"Export every receipt from January to /tmp/etsy-q1 as CSV"*
- *"Mark receipt 12345 shipped with tracking 1Z999AA via UPS"*
- *"Bulk update price on these 50 listings to $19.99 — dry run first"*
- *"Create a 15% off sale on my outdoor cushion line, June 1 to June 7"*
- *"Pause Etsy Ads"*

Destructive operations (delete, refund, turn ads on, create sale) require an
explicit `confirm=True` — Claude can't accidentally spend your money.

---

## Recurring checks (alerts on a schedule)

This MCP doesn't ship its own alerter. If you want passive daily
summaries, use Claude Code's `/schedule` skill combined with a
connected Gmail / Slack MCP on Claude's side. Example:

```
/schedule daily 9am "Run an Etsy morning check: list unread buyer
messages > 2h old, paid orders that are still unshipped, and any
reviews from the last 24h with rating ≤ 3. If any of those are
non-empty, email a summary to sales@yourshop.com via the Gmail
connector."
```

Setup of `/schedule` and Gmail/Slack connectors is on Claude's side, not in this repo.

---

## When things expire

Two things expire periodically and need re-bootstrapping. Tools will tell you with a clear error message — you don't have to track this manually.

| Error you'll see | Fix |
|---|---|
| `{"code": "auth_expired"}` from API tools (every ~90 days) | `python scripts/bootstrap_oauth.py` — takes 30 seconds |
| `{"code": "session_expired"}` from browser tools (every few weeks) | `python scripts/import_cookies_from_chrome.py --email you@yourcompany.com` |

---

## Common gotchas

| Symptom | Fix |
|---|---|
| OAuth fails with *"redirect URL not permitted"* | Callback URL on the Etsy app page must be **exactly** `http://localhost:3003/callback` — no trailing slash, no `https`. Save and retry. |
| `etsy_whoami` returns *"Shared secret is required in x-api-key header"* | You're on an old version. Run `git pull` and reinstall — the auth header fix is in commit `5fc1cd3`. |
| `import_cookies_from_chrome.py` finds 0 cookies | Make sure Chrome is logged into etsy.com with the seller account before running. The login session must exist in Chrome's cookie store. |
| Browser tools return `selector_missing` with a screenshot path | Etsy redesigned the dashboard. Open the screenshot at the path printed; update the `SELECTORS` dict at the top of `etsy_mcp/browser.py`. |
| `claude mcp list` shows etsy but `etsy_whoami` isn't available in chat | Restart Claude Code — MCP tool definitions are loaded at session start. |

---

## Using a Cloudflare tunnel for OAuth

If Etsy rejects `http://localhost:3003/callback` on your app's allowed
list (rare, but happens for some accounts), you can swap to a public
HTTPS tunnel:

```bash
# Install once
brew install cloudflared

# Start a quick tunnel — prints a https://<random>.trycloudflare.com URL
cloudflared tunnel --url http://localhost:3003
```

Add `https://<random>.trycloudflare.com/callback` to the Etsy app's
Callback URLs, then run the bootstrap pointing at the public URL:

```bash
ETSY_OAUTH_REDIRECT_URI="https://<random>.trycloudflare.com/callback" \
  python scripts/bootstrap_oauth.py
```

The tunnel only needs to live for the OAuth handshake — kill it once
the script writes `.tokens.json`. The MCP itself never needs incoming
traffic, only outbound API calls.

---

## Privacy note

Everything (`.env`, `.tokens.json`, `.storage_state.json`) lives on
your local machine. The MCP makes outbound calls to Etsy's API and
seller dashboard — no data is sent to us, Anthropic, or any third
party. The `.gitignore` keeps these files out of git so you can clone
this repo onto multiple machines without leaking credentials.
