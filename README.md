# Etsy MCP

**Connect Claude to your Etsy shop and run everything from a chat.** Listings, orders, ads, exports, refunds, sales, reports — all of it, in plain English, from inside Claude.

This is a Python [MCP](https://modelcontextprotocol.io) server that exposes **57 tools** to Claude. Most use Etsy's Open API v3; a few drive the seller dashboard via Playwright for things the API doesn't expose (Etsy Ads, sales/coupons, listing image reorder, buyer messages).

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-162%20passing-brightgreen.svg)](#development)
[![Status](https://img.shields.io/badge/status-feature%20complete-success.svg)](#status)

---

## Why

Etsy's seller dashboard is fine for one-off actions but slow for batch work, anything cross-listing, or anything you want to do at 11pm on a Tuesday by typing one sentence. With this MCP installed, Claude becomes your Etsy operator.

A few sentences you can actually say to Claude once it's running:

- *"List my top 10 active listings"*
- *"Search my shop for cushion covers"*
- *"Export every receipt from January to /tmp/etsy-q1 as CSV"*
- *"Mark receipt 12345 shipped with tracking 1Z999AA via UPS"*
- *"Issue a $5 refund on receipt 67890 — buyer reported damage"*
- *"Show me revenue by month for 2026"*
- *"Top 20 listings by units sold this quarter"*
- *"Bulk update price on these 50 listings — dry run first"*
- *"Pause Etsy Ads"*
- *"Save listing 999 as a template, then apply it to the 20 new draft listings"*
- *"Create a 15% off sale on my outdoor cushion line, June 1 to June 7"*

Every tool returns structured JSON Claude can read back, chain into the next call, or summarize for you. Destructive operations (delete, refund, turn ads on, bulk renew, create sale/coupon) require an explicit `confirm=True` flag — Claude can't accidentally spend your money. Mass-edit tools default to dry-run, so Claude shows you the preview before anything mutates.

---

## Status

**Feature complete** against the design spec. All 57 tools across 6 phases are implemented and tested live against an approved Etsy app:

| Phase | Scope | Tools | Tests |
|---|---|---|---|
| 0 | Auth foundation (OAuth 2.0 PKCE, refresh, rate-limited HTTP) | 2 | 22 |
| 1a | Read-only API tools (listings, receipts, reviews, shop) | 12 | 30 |
| 1b | Listing writes, taxonomy lookup, bulk export (JSON + CSV) | 9 | 23 |
| 1c | Etsy Ads + listing image reorder (browser-driven) | 6 | 13 |
| 2 | Operational ops (ship, refund, shop config, bulk inventory) | 16 | 33 |
| 3 | Power tools (templates, sales/coupons, reports) | 8 | 21 |
| 4 | Buyer/seller conversations (browser-driven) | 2 | — |
| **Total** | | **57** | **162** |

---

## Quick start

```bash
# 1. Clone + install
git clone git@github.com:kumarsumit2000/Etsy-MCP.git
cd Etsy-MCP
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Install Chromium for browser-driven tools (one-time, ~150 MB)
playwright install chromium

# 3. Configure credentials
cp .env.example .env
# Edit .env and fill in:
#   ETSY_KEYSTRING        — from https://www.etsy.com/developers/your-apps
#   ETSY_SHARED_SECRET    — same page
#   ETSY_SHOP_TIMEZONE    — your shop's home tz (default America/Denver)
# Leave ETSY_SHOP_ID blank for now — step 4 prints it.

# 4. Bootstrap OAuth (opens browser, you click Allow, prints shop_id)
python scripts/bootstrap_oauth.py
# Paste the printed shop_id into .env as ETSY_SHOP_ID.

# 5. Import Etsy session cookies from your Chrome profile.
#    The 11 browser-driven tools (messages, ads, sales, coupons, image reorder)
#    need Etsy.com session cookies — they cannot use the OAuth tokens because
#    Etsy's seller dashboard isn't part of the public API.
#
#    First, log into etsy.com in your normal Chrome browser using the seller
#    account you want this MCP to act on (e.g. your Shop Manager login).
#    Then import those cookies — pass --email to target the right Chrome profile:
python scripts/import_cookies_from_chrome.py --email you@yourshop.com

# (Use --list to see all detected Chrome profiles if unsure which email to use.)

# 6. Wire into Claude Code (one command, no config file needed):
claude mcp add etsy -s user -- /absolute/path/to/Etsy-MCP/.venv/bin/python /absolute/path/to/Etsy-MCP/server.py

# Restart Claude Code, then ask: "Call etsy_whoami". You should see your shop info.
```

Full step-by-step walkthrough with screenshots: [SETUP.md](SETUP.md).

### Recurring checks (alerts on a schedule)

This MCP doesn't ship its own alerter. The intended workflow is: open Claude (Code or Desktop) and ask things like *"Any unread Etsy messages older than 2 hours? Any unshipped paid orders? Anything 1- or 2-star from the last 24 hours?"* — Claude calls the right tools and tells you.

If you want this on a schedule (e.g. a 9am daily summary), use Claude Code's [`/schedule`](https://docs.claude.com/en/docs/claude-code/scheduled-tasks) skill (or any cron job that pipes a prompt to `claude`). Combined with a connected Gmail / Slack MCP on Claude's side, the same prompt can also email or DM the result. Example:

```
/schedule daily 9am "Run an Etsy morning check: list unread buyer messages > 2h old,
paid orders that are still unshipped, and any reviews from the last 24h with
rating ≤ 3. If any of those are non-empty, email a summary to sales@yourshop.com
via the Gmail connector."
```

Setup of `/schedule` and Gmail/Slack connectors is on Claude's side, not in this repo. We just provide the Etsy tools — the rest is composition.

### Alternate: interactive browser login (if you'd rather not import cookies)

```bash
python scripts/bootstrap_browser_login.py
# Opens visible Chromium → you log in manually (handle 2FA / captcha) →
# script auto-detects success and saves .storage_state.json.
```

Note: Etsy aggressively bot-detects Playwright login flows. If this fails or
loops at captcha, fall back to `import_cookies_from_chrome.py` — it's
strictly more reliable because cookies come from your real Chrome.

---

## Tool reference (all 57)

### Auth & meta (2)

| Tool | What it does |
|---|---|
| `etsy_whoami` | Verify auth — return user_id, login_name, shop_id, shop_name |
| `etsy_token_status` | Show access token expiry + refresh token age (re-bootstrap before 90 days) |

### Shop (2)

| Tool | What it does |
|---|---|
| `etsy_get_shop` | Full shop info (name, currency, policies, status) |
| `etsy_get_shop_stats(start, end)` | Aggregate orders + revenue from receipts in a date range |

### Listings — read (5)

| Tool | What it does |
|---|---|
| `etsy_list_listings(state="active", limit, offset)` | List shop listings filtered by state |
| `etsy_search_listings(keyword, state, limit, offset)` | Client-side substring filter over your listings |
| `etsy_get_listing(listing_id, includes=["Images","Inventory","Videos"])` | Single listing with optional embedded resources |
| `etsy_get_listing_inventory(listing_id)` | SKUs, offerings (price + qty), property values |
| `etsy_get_listing_images(listing_id)` | Image metadata (id, rank, urls, alt_text) |

### Listings — write (5)

| Tool | What it does |
|---|---|
| `etsy_create_draft_listing(title, description, price_usd, quantity, taxonomy_id, who_made, when_made, is_supply, shipping_profile_id, ...)` | Create draft with required + optional fields |
| `etsy_update_listing(listing_id, **fields)` | Partial update via PATCH (title, price, state, tags, etc.) |
| `etsy_delete_listing(listing_id, confirm=True)` | Permanent delete — requires confirm |
| `etsy_upload_listing_image(listing_id, image_path, rank=1, alt_text=None)` | Multipart upload from a local file |
| `etsy_update_listing_inventory(listing_id, products)` | Replace products array (SKUs, offerings, variants) |

### Listings — power tools (3)

| Tool | What it does |
|---|---|
| `etsy_save_listing_template(listing_id, template_path)` | Save 11 portable metadata fields to a JSON file |
| `etsy_apply_listing_template(template_path, target_listing_ids, apply=False)` | Apply saved template across listings (dry-run by default) |
| `etsy_duplicate_listing(listing_id, new_title=None)` | Clone source as new draft (images NOT copied — re-upload separately) |

### Receipts / orders (4)

| Tool | What it does |
|---|---|
| `etsy_list_receipts(was_paid, was_shipped, min_created, max_created, limit, offset)` | Filter orders by status + date |
| `etsy_get_receipt(receipt_id)` | Full receipt with buyer, totals, shipping, status |
| `etsy_get_receipt_transactions(receipt_id)` | Line items per receipt |
| `etsy_list_shop_payments(min_created, max_created, limit, offset)` | Payment ledger entries (charges, fees, credits, refunds) |
| `etsy_returns_summary(min_created, max_created, days=30)` | Aggregate cancellations + refunds: by_status counts, cancellation_rate, refund_total_usd, top_3_reasons grouped, sample refund rows |

### Order operations (3)

| Tool | What it does |
|---|---|
| `etsy_mark_receipt_shipped(receipt_id, tracking_code, carrier_name, send_bcc=False)` | Mark shipped with tracking |
| `etsy_bulk_mark_shipped(csv_path)` | Batch ship from CSV (cols: receipt_id, tracking_code, carrier_name) |
| `etsy_issue_refund(receipt_id, amount_cents, reason, confirm=True)` | Issue refund — requires confirm; Etsy may reject by payment method |

### Reviews (1)

| Tool | What it does |
|---|---|
| `etsy_list_reviews(min_created, max_created, limit, offset)` | List shop reviews with optional date range |

### Shop config (10)

| Tool | What it does |
|---|---|
| `etsy_list_shipping_profiles` / `etsy_create_shipping_profile` / `etsy_update_shipping_profile` | Shipping profile CRUD (no delete in v3) |
| `etsy_list_shop_sections` / `etsy_create_shop_section` / `etsy_update_shop_section` | Shop sections (storefront category buckets) |
| `etsy_list_return_policies` / `etsy_create_return_policy` | List + create (Etsy v3 has no update/delete for return policies) |
| `etsy_list_production_partners` / `etsy_create_production_partner` | Required by Etsy when `who_made="someone_else"` |

### Taxonomy (1)

| Tool | What it does |
|---|---|
| `etsy_taxonomy_search(query)` | Find taxonomy IDs by keyword across the seller-taxonomy tree (cached in-process) |

### Bulk export (3)

| Tool | What it does |
|---|---|
| `etsy_export_all_listings(output_dir, format="both", state="active")` | Paginate + write JSON and/or CSV |
| `etsy_export_all_receipts(output_dir, format="both", since=None)` | Same, with optional ISO date filter |
| `etsy_export_all_reviews(output_dir, format="both")` | Same, all-time |

CSVs use dot-joined keys for nested fields (e.g. `price.amount`, `price.currency_code`) and JSON-encode lists.

### Bulk operations (3)

| Tool | What it does |
|---|---|
| `etsy_bulk_update_prices(updates, apply=False)` | Mass-update prices; `apply=False` returns dry-run preview |
| `etsy_bulk_update_quantities(updates, apply=False)` | Mass-update SKU quantities; merges per-listing PUTs to avoid clobbering |
| `etsy_bulk_renew_listings(listing_ids, confirm=True)` | Renew expired listings — requires confirm (each renewal costs Etsy's fee) |

### Etsy Ads — browser (5)

| Tool | What it does |
|---|---|
| `etsy_ads_get_status` | Read current ads state, daily budget, last 30d stats |
| `etsy_ads_create_campaign(daily_budget_usd, confirm=True)` | Turn ads on with a budget — requires confirm (real money) |
| `etsy_ads_set_budget(daily_budget_usd)` | Modify daily budget on active campaign |
| `etsy_ads_pause` / `etsy_ads_resume` | Toggle ads on/off |

### Sales & coupons — browser (3)

| Tool | What it does |
|---|---|
| `etsy_list_active_sales` | List active sales scraped from the discounts page |
| `etsy_create_sale(percent_off, listing_ids, start_iso, end_iso, confirm=True)` | Create percent-off sale — requires confirm |
| `etsy_create_coupon(code, percent_off, min_purchase_usd, free_shipping, confirm=True)` | Create coupon code — requires confirm |

### Listing image reorder — browser (1)

| Tool | What it does |
|---|---|
| `etsy_update_listing_images_order(listing_id, image_ids)` | Reorder images via dashboard JS (Etsy v3 has no rank-only API) |

### Reporting (2)

| Tool | What it does |
|---|---|
| `etsy_revenue_report(start, end, group_by="day"\|"week"\|"month")` | Bucket revenue from receipts (in shop's local timezone — see `ETSY_SHOP_TIMEZONE`) |
| `etsy_top_listings_report(start, end, by="revenue"\|"units", limit=20)` | Top listings (by="views" unsupported — Etsy v3 doesn't expose) |

### Traffic & shop stats — browser (1)

| Tool | What it does |
|---|---|
| `etsy_get_traffic_stats(date_range="Last 30 days")` | Scrape visits, conversion rate, abandoned-carts, item favorites, shop follows, repeat buyers, cities reached from `/your/shops/me/stats`. The Etsy v3 API does **not** expose any of these — they only exist on the seller dashboard. |

Accepts any label the date dropdown shows: `"Today"`, `"Yesterday"`, `"Last 7 days"`, `"Last 30 days"`, `"This month"`, `"Last month"`, `"This year"`. Returns headline (visits, orders, conversion_rate_pct, revenue_usd) plus shopper_stats (item_favorites, shop_follows, reviews, repeat_buyers, cities_reached, abandoned_carts).

### Conversations — browser (2)

| Tool | What it does |
|---|---|
| `etsy_list_conversations(filter="all"\|"unread"\|"missed", since_hours=48, min_age_hours=0, limit=50)` | List inbox threads. `filter='missed'` = unread + older than `min_age_hours` |
| `etsy_get_conversation(conversation_id)` | Open a single thread and return its messages |

Etsy's v3 Open API doesn't expose conversations, so these tools drive
`etsy.com/messages/inbox` via Playwright using the saved `.storage_state.json`.
Note: opening a thread auto-marks it read on Etsy's side.

---

## Usage examples (from inside Claude)

> *Show me my shop info and current ads status*

Claude calls `etsy_whoami` and `etsy_ads_get_status` in parallel.

> *Export every receipt from 2026-01-01 to /tmp/etsy-q1*

Claude calls `etsy_export_all_receipts(output_dir="/tmp/etsy-q1", since="2026-01-01", format="both")`.

> *Bulk update price on listings 100, 200, 300 to $19.99 — dry run first*

Claude calls `etsy_bulk_update_prices(updates=[...], apply=False)` and shows the preview. You then say "apply it" and Claude reruns with `apply=True`.

> *Create a draft listing for "Outdoor cushion - blue, 18x18" at $39.99, 10 in stock, in the cushions category*

Claude calls `etsy_taxonomy_search("cushion")` to find the right `taxonomy_id`, then `etsy_list_shipping_profiles` for a `shipping_profile_id`, then `etsy_create_draft_listing(...)` with the resolved IDs.

> *Mark these 50 orders shipped from this CSV*

Claude calls `etsy_bulk_mark_shipped(csv_path="/path/to/shipped.csv")` and reports the per-row results.

---

## Architecture

```
~/Desktop/Etsy MCP/
├── etsy_mcp/             # Python package — one module per Etsy domain
│   ├── auth.py           # OAuth 2.0 PKCE: bootstrap, refresh w/ rotation, asyncio.Lock
│   ├── http.py           # etsy_request wrapper: rate limiter, retries, 401-refresh-once,
│   │                     # paginate_all helper for bulk reads
│   ├── errors.py         # ErrorCode enum + EtsyMCPError hierarchy + missing_shop_id_error
│   ├── shop.py           # Shop info + shop_stats (derived from receipts)
│   ├── listings.py       # 13 tools — read, write, power-ups (templates, duplicate)
│   ├── receipts.py       # 4 read tools (Phase 1a)
│   ├── orders.py         # 3 write tools — ship, bulk_ship, refund (Phase 2)
│   ├── reviews.py        # 1 read tool
│   ├── shop_config.py    # 10 tools — shipping profiles, sections, return policies, partners
│   ├── taxonomy.py       # 1 tool with in-process tree cache
│   ├── exports.py        # 3 tools — paginate + JSON/CSV with dot-flatten helper
│   ├── bulk_ops.py       # 3 tools — bulk price/qty/renew with dry-run-by-default
│   ├── browser.py        # 9 tools — Playwright-driven (ads, sales/coupons, image reorder)
│   ├── messages.py       # 2 tools — Playwright-driven inbox scraper (filter='missed')
│   ├── timeutil.py       # shop_tz() helper — interprets dates in ETSY_SHOP_TIMEZONE
│   └── reporting.py      # 2 tools — revenue + top-listings derived from receipts
├── scripts/
│   ├── bootstrap_oauth.py            # one-time OAuth PKCE flow → .tokens.json
│   ├── bootstrap_browser_login.py    # interactive login → .storage_state.json
│   └── import_cookies_from_chrome.py # PREFERRED: import Etsy session from Chrome profile
├── tests/unit/           # 162 unit tests (respx for HTTP, pytest-asyncio)
├── docs/superpowers/     # specs/ + plans/ — every phase's design + implementation plan
├── server.py             # FastMCP entrypoint, registers all factories
├── .env.example          # ETSY_KEYSTRING, ETSY_SHARED_SECRET, ETSY_SHOP_ID, ETSY_ADS_HEADFUL
└── SETUP.md              # 7-section walkthrough (Etsy app, OAuth, browser bootstrap, Claude Code wiring)
```

### Design patterns

**Module boundary:** every domain module exposes a `register_<domain>_tools(mcp, *, keystring, tokens_path, shop_id_getter)` factory. The factory closes over deps and decorates tool functions with `@mcp.tool()`. Returns a dict of tool callables for direct test invocation.

**Boundary contract:** every tool returns either the success dict directly OR a structured-error dict `{"error": str, "code": str, "details"?: dict}`. Tools never raise past the MCP boundary — internal `EtsyMCPError` exceptions are caught and converted.

**Confirm guards** for destructive / money-moving tools:
- `etsy_delete_listing(confirm=True)`
- `etsy_issue_refund(confirm=True)`
- `etsy_ads_create_campaign(confirm=True)`
- `etsy_create_sale(confirm=True)`
- `etsy_create_coupon(confirm=True)`
- `etsy_bulk_renew_listings(confirm=True)`

**Dry-run by default** for mass-edit tools:
- `etsy_bulk_update_prices(apply=False)`
- `etsy_bulk_update_quantities(apply=False)`
- `etsy_apply_listing_template(apply=False)`

**Browser tools** use a single `EtsyBrowser` async context manager that loads `.storage_state.json`. All selectors centralized in a `SELECTORS` dict at the top of `browser.py` with `Last verified: YYYY-MM-DD` comments — when Etsy redesigns, that's the only place to update. Selector failures dump a screenshot to `/tmp/etsy_browser_error_*.png`.

### OAuth & token handling

- PKCE per RFC 7636 (S256), 64-char URL-safe verifier
- `.tokens.json` written atomically (write to `.tmp`, `chmod 0600`, `os.replace`) so tokens are never world-readable on disk
- Refresh tokens **rotate** on every refresh — new token persisted, old one discarded
- Concurrent refreshes serialized via `asyncio.Lock` to avoid the second coroutine sending a now-invalidated token
- Refresh token expires after 90 days; `etsy_token_status` reports the age so you can re-bootstrap before it dies

### HTTP wrapper guarantees

`etsy_request()` is the single transport point every API tool calls. It guarantees:
- Rate limit: token-bucket, 10 req/s (matches Etsy's per-app limit)
- 429 → honor `Retry-After`, retry up to `max_retries` (default 3)
- 5xx → exponential backoff, retry up to `max_retries`
- Network errors (any `httpx.TransportError`) → retry once
- 401 → automatic refresh + retry once (independent of retry budget)
- 404 → `NotFound`; 400 → `ValidationFailed`
- Headers always include both `x-api-key` AND `Authorization: Bearer ...` (Etsy requires both)
- `x-api-key` is sent as `<keystring>:<shared_secret>` — Etsy's approved-app endpoints reject the bare keystring with `"Shared secret is required in x-api-key header."`

---

## Configuration

`.env` keys (see `.env.example`):

| Key | Purpose | Required |
|---|---|---|
| `ETSY_KEYSTRING` | Etsy app keystring (API key) | ✅ |
| `ETSY_SHARED_SECRET` | Etsy app shared secret | ✅ |
| `ETSY_SHOP_ID` | Your shop's numeric ID (printed by `bootstrap_oauth.py`) | ✅ for shop-scoped tools |
| `ETSY_SHOP_TIMEZONE` | Shop's home tz for date inputs / day bucketing — default `America/Denver` | optional but recommended |
| `ETSY_LOG_LEVEL` | Logging verbosity | optional |
| `ETSY_OAUTH_REDIRECT_PORT` | Port for OAuth callback (default 3003) | optional |
| `ETSY_OAUTH_REDIRECT_URI` | Override the full redirect URI (e.g. Cloudflare tunnel public URL) | optional |
| `ETSY_ADS_HEADFUL` | Set `1` to show the runtime browser (debugging) | optional |
| `ETSY_BROWSER_STORAGE_STATE` | Override path to Playwright storage_state.json | optional (tests use it) |

Files ignored by git (`.gitignore`):

```
.env, .env.local
.tokens.json, .tokens.json.tmp
.storage_state.json
logs/
.venv/
```

---

## Required Etsy OAuth scopes

The bootstrap requests:

```
listings_r listings_w listings_d
shops_r shops_w
transactions_r transactions_w
feedback_r
email_r profile_r address_r
```

Tier 2 refund + Tier 3 sale/coupon tools may rely on browser cookies for actions Etsy v3 doesn't fully expose.

---

## Development

```bash
# Setup
pip install -r requirements-dev.txt

# Run all 162 tests
pytest

# Focused
pytest tests/unit/test_listings.py -v
pytest -k "ads"

# Run only one file with full output
pytest tests/unit/test_orders.py -v -s
```

### Test design

- **Unit tests** mock the transport layer via `respx` (HTTP) — never hit Etsy or the file system
- **Browser tools** are partially unit-tested (selector existence, error paths, registration) but full E2E verification against the real Etsy dashboard is manual — that's the unavoidable cost of dashboard scraping
- Test counts per phase shown in the [Status](#status) table

### Adding a new tool

The pattern (matching all existing tools):

1. In the appropriate `etsy_mcp/<domain>.py`, add a function inside the existing `register_<domain>_tools` factory
2. Decorate with `@mcp.tool()` so FastMCP discovers it
3. Wrap any `EtsyMCPError` → return `exc.to_dict()`
4. Return success dict or structured-error dict
5. Add it to the factory's return dict (for direct test invocation)
6. Write unit tests in `tests/unit/test_<domain>.py` using respx mocks
7. If it touches the dashboard (not the API), follow the `browser.py` pattern with selectors centralized + dated

### Adding a new domain module

1. Create `etsy_mcp/<new_domain>.py` with `register_<new_domain>_tools(mcp, *, keystring, tokens_path, shop_id_getter)` factory
2. Add `from etsy_mcp.<new_domain> import register_<new_domain>_tools` to `server.py`
3. Add the `register_<new_domain>_tools(mcp, ...)` call after the existing register block
4. Create `tests/unit/test_<new_domain>.py` using the `make_tools` fixture from `tests/conftest.py`

---

## When things break

| Error code | What it means | Fix |
|---|---|---|
| `auth_invalid` | Keystring wrong, scopes missing, or `ETSY_SHOP_ID` unset | Check `.env`, re-run bootstrap if needed |
| `auth_expired` | Refresh token expired (90+ days) | Re-run `python scripts/bootstrap_oauth.py` |
| `session_expired` | Browser tools — storage_state missing or expired | Re-run `python scripts/bootstrap_browser_login.py` |
| `selector_missing` | Browser tools — Etsy redesigned the dashboard | Open the screenshot at `/tmp/etsy_browser_error_*.png`, update `SELECTORS` in `browser.py`, bump the `Last verified:` date |
| `rate_limited` | Hit 429 after retries exhausted | Wait, then retry. Etsy limit is 10 req/s + 10k req/day per app |
| `not_found` | Resource doesn't exist (or doesn't belong to your shop) | Verify the ID is correct |
| `validation_failed` | Bad input (missing required field, confirm guard, dry-run preview) | Read the `error` message |
| `network` | Connection failure after retries | Check internet; Etsy may be having issues |

---

## Project history

The project was built phase-by-phase using a brainstorm → spec → plan → execute (TDD) workflow — every phase has a design spec in `docs/superpowers/specs/` and an implementation plan in `docs/superpowers/plans/`. All implementation tracked via TDD with full test coverage at every step.

Phase chronology (May 4-5, 2026):
- Phase 0 → Phase 1a → Phase 1b → Phase 1c → Phase 2 → Phase 3
- Each phase: brainstorm → spec → plan → execute (inline TDD) → push to GitHub
- ~50 commits, all passing CI-equivalent checks

---

## License

Personal-use project. No license declared.

---

## Acknowledgements

Built on the [Model Context Protocol](https://modelcontextprotocol.io) Python SDK and FastMCP. HTTP via [httpx](https://www.python-httpx.org/), browser automation via [Playwright](https://playwright.dev/python/), tests via [respx](https://lundberg.github.io/respx/) + [pytest-asyncio](https://pytest-asyncio.readthedocs.io/).
