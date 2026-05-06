# Etsy MCP — Design Spec

**Date:** 2026-05-04
**Owner:** Sumit (<owner>)
**Project root:** `<project root>/`
**Status:** Approved for planning

## 1. Goal

Build a Python MCP server for managing an Etsy shop end-to-end from Claude. Mirrors the existing Shopify MCP (`~/Desktop/ZIPC MCP/shopify-mcp/`) in stack and ergonomics, with two key differences:

1. **OAuth 2.0 PKCE** auth (Etsy's required model) instead of Shopify's static admin token.
2. **Hybrid API + browser automation**: Etsy's Open API v3 covers listings, receipts, reviews, shop config; Etsy Ads and sales/coupons require Playwright-driven browser automation because Etsy does not expose those resources through their public API.

The MCP must let the user perform *most* operations they would otherwise do in the Etsy seller dashboard — listing CRUD, order management, ad campaign control, bulk data export — without leaving Claude.

## 2. Non-Goals

- Multi-shop / multi-tenant. Single Etsy shop only.
- Buyer-side functionality (cart, favorites, browsing).
- Real-time webhooks / event listeners.
- Hosting the MCP remotely. Runs locally on user's Mac.
- Replacing the Etsy seller dashboard for tasks the API already supports well via the dashboard (e.g. complex shop branding settings).

## 3. Architecture

### 3.1 Stack

- **Language:** Python 3.10+
- **MCP framework:** `mcp` SDK with `FastMCP` (matches Shopify MCP)
- **HTTP client:** `httpx` async
- **Config:** `python-dotenv`
- **OAuth:** `authlib` (PKCE flow)
- **Browser automation:** `playwright` (Chromium)
- **Logging:** `structlog` to file with daily rotation

### 3.2 Project Layout

```
~/Desktop/Etsy MCP/
├── etsy_mcp/
│   ├── __init__.py
│   ├── auth.py          # OAuth PKCE bootstrap + runtime token refresh
│   ├── http.py          # httpx client wrapper, rate-limit + retry, structured errors
│   ├── listings.py      # listing read/write tools (11 tools)
│   ├── receipts.py      # orders, transactions, ship, refund (7 tools)
│   ├── reviews.py       # reviews read (1 tool)
│   ├── shop.py          # shop info, shipping profiles, sections, return policies, partners (10+ tools)
│   ├── exports.py       # bulk export → JSON + CSV (3 tools)
│   ├── ads_browser.py   # Playwright tools for Etsy Ads + sales/coupons (7 tools)
│   ├── taxonomy.py      # category lookup (1 tool)
│   └── reporting.py     # derived reports from receipts (2 tools)
├── scripts/
│   ├── bootstrap_oauth.py    # one-time OAuth PKCE flow → .tokens.json
│   └── bootstrap_ads_login.py # one-time Playwright login → .storage_state.json
├── tests/
│   ├── unit/                  # no network, pure logic
│   └── integration/           # gated by RUN_LIVE_TESTS=1
├── logs/                      # rotated daily, 7-day retention, gitignored
├── server.py                  # FastMCP entrypoint, registers all tools
├── .env                       # gitignored
├── .env.example
├── .tokens.json               # gitignored
├── .storage_state.json        # gitignored
├── .gitignore
├── requirements.txt
├── README.md
└── SETUP.md                   # walkthrough for first-time Etsy dev account + app creation
```

**Why modular instead of single-file:** Etsy MCP totals ~44 tools across 3 tiers. A single 2000+ line file becomes painful to navigate and edit reliably. Each domain owns its module; `server.py` imports and registers tools.

## 4. Authentication

Two independent auth setups: one for the Etsy API, one for the Etsy Ads browser session.

### 4.1 Etsy API — OAuth 2.0 PKCE

**One-time manual setup** (documented in `SETUP.md`):
1. Create Etsy developer account at `apps.etsy.com`.
2. Register a new app, get `keystring` (API key) + `shared_secret`.
3. Set redirect URI to `http://localhost:3003/callback`.
4. Note required scopes: `listings_r listings_w listings_d shops_r shops_w transactions_r transactions_w feedback_r email_r profile_r address_r`.

**Bootstrap script** (`scripts/bootstrap_oauth.py`):
1. Reads `ETSY_KEYSTRING` from `.env`.
2. Generates PKCE code verifier + challenge.
3. Spins up localhost HTTP server on :3003.
4. Opens user's browser to Etsy's authorize URL with PKCE challenge + scopes.
5. User clicks "Allow" → Etsy redirects to `localhost:3003/callback?code=...`.
6. Script exchanges code → `{access_token, refresh_token, expires_in}` → writes to `.tokens.json` with absolute `expires_at` timestamp.
7. Script calls `/users/me` to fetch user_id, then `/users/{user_id}/shops` to fetch shop_id, prints shop_id and instructs user to add it to `.env` as `ETSY_SHOP_ID`.

**Runtime token refresh** (`etsy_mcp/auth.py`):
- Single `get_access_token()` async function. Every API call goes through this.
- Reads `.tokens.json`. If `expires_at - now < 60s`, calls refresh endpoint, writes new tokens back atomically (write to `.tokens.json.tmp` then rename).
- **Refresh tokens rotate on use** — the new refresh token must replace the old one. Failing to do this is the #1 footgun and must be unit-tested.
- If refresh fails with `invalid_grant` (refresh token expired after 90 days or revoked), raises `RefreshTokenExpired` — caller surfaces structured error: `{"error": "Refresh token expired. Re-run scripts/bootstrap_oauth.py", "code": "auth_expired"}`.

**`.env` keys:**
```
ETSY_KEYSTRING=...
ETSY_SHARED_SECRET=...
ETSY_SHOP_ID=...
ETSY_LOG_LEVEL=INFO
ETSY_ADS_HEADFUL=0   # set to 1 to debug ads browser visibly
```

**`.tokens.json` shape:**
```json
{
  "access_token": "...",
  "refresh_token": "...",
  "expires_at": 1714838400,
  "obtained_at": 1714834800,
  "scope": "listings_r listings_w ..."
}
```

### 4.2 Etsy Ads — Playwright Session

**One-time manual setup** (`scripts/bootstrap_ads_login.py`):
1. Launches a real (non-headless) Chromium window via Playwright.
2. Navigates to `https://www.etsy.com/signin`.
3. User logs in manually — handles password, 2FA, captcha, whatever Etsy throws.
4. Script polls until URL contains `/your/shops/me/dashboard` (logged-in marker).
5. Dumps `context.storage_state()` to `.storage_state.json`.
6. Closes browser.

**Runtime** (`etsy_mcp/ads_browser.py`):
- `EtsyAdsBrowser` async context manager launches headless Chromium loaded with `storage_state=".storage_state.json"`.
- Each tool entry calls `_ensure_logged_in()` which checks for redirect to signin page; if seen, raises `SessionExpired` → tool returns `{"error": "Etsy ads session expired. Re-run scripts/bootstrap_ads_login.py", "code": "session_expired"}`.
- All selectors centralized in a constants block at the top of `ads_browser.py`, each with `# Last verified: YYYY-MM-DD` comment.
- Selector preference: `getByRole`, `getByLabel`, `data-test-id` over CSS class names.
- On selector failure: tool returns `{"error": "Etsy dashboard layout changed at step <name>", "code": "selector_missing", "screenshot_path": "/tmp/etsy_ads_error_<timestamp>.png"}`.
- `ETSY_ADS_HEADFUL=1` env switches to visible browser for debugging.

## 5. Tool Inventory

**Total: ~52 tools across 3 tiers.** Each section below lists tools with arguments and brief return contract. Counts are approximate — the implementation plan for each phase will finalize exact tool surface.

### 5.1 Tier 1 — Essentials (~28 tools)

#### Auth & meta (3)

| Tool | Args | Returns |
|------|------|---------|
| `etsy_whoami` | — | `{user_id, login_name, primary_email, shop_id, shop_name}` |
| `etsy_token_status` | — | `{access_expires_in_seconds, refresh_age_days, refresh_expires_in_days_estimate}` |
| `etsy_taxonomy_search` | `query: str` | `[{taxonomy_id, name, level, full_path}]` (top 20 matches) |

#### Listings — read (5)

| Tool | Args | Returns |
|------|------|---------|
| `etsy_list_listings` | `state: str = "active"`, `limit: int = 25`, `offset: int = 0` | `{count, results: [...]}` |
| `etsy_search_listings` | `keyword: str`, `limit`, `offset` | `{count, results: [...]}` |
| `etsy_get_listing` | `listing_id: int`, `includes: list[str] = []` (subset of `images`, `inventory`, `videos`, `translations`) | listing dict with included sub-resources |
| `etsy_get_listing_inventory` | `listing_id: int` | `{products: [{sku, offerings: [{price, quantity}], property_values: [...]}]}` |
| `etsy_get_listing_images` | `listing_id: int` | `[{listing_image_id, url_fullxfull, rank, alt_text}]` |

#### Listings — write (6)

| Tool | Args | Returns |
|------|------|---------|
| `etsy_create_draft_listing` | `title, description, price_usd, quantity, taxonomy_id, who_made ∈ {i_did, someone_else, collective}, when_made ∈ {made_to_order, ...}, is_supply: bool, shipping_profile_id, return_policy_id?, materials?, tags?, processing_min?, processing_max?` | `{listing_id, state: "draft", url}` |
| `etsy_update_listing` | `listing_id`, `**fields` (any updatable field) | updated listing dict |
| `etsy_delete_listing` | `listing_id`, `confirm: bool = False` | `{deleted: true}` or guard error |
| `etsy_upload_listing_image` | `listing_id`, `image_path: str`, `rank: int = 1`, `alt_text?: str` | `{listing_image_id, url_fullxfull, rank}` |
| `etsy_update_listing_inventory` | `listing_id`, `products: [{sku, offerings: [{price, quantity, is_enabled}], property_values?}]` | updated inventory |
| `etsy_update_listing_images_order` | `listing_id`, `image_ids: list[int]` | `{ok: true}` |

#### Receipts (4)

| Tool | Args | Returns |
|------|------|---------|
| `etsy_list_receipts` | `was_paid?: bool, was_shipped?: bool, min_created?: ISO date, max_created?: ISO date, limit, offset` | `{count, results: [...]}` |
| `etsy_get_receipt` | `receipt_id: int` | full receipt dict |
| `etsy_get_receipt_transactions` | `receipt_id: int` | `[{transaction_id, listing_id, title, quantity, price, sku, ...}]` |
| `etsy_list_shop_payments` | `min_created?, max_created?` | `[{payment_id, amount_gross, amount_fees, amount_net, ...}]` |

#### Reviews + shop (3)

| Tool | Args | Returns |
|------|------|---------|
| `etsy_list_reviews` | `min_created?, max_created?, limit, offset` | `{count, results: [...]}` |
| `etsy_get_shop` | — | shop dict |
| `etsy_get_shop_stats` | `start_date: ISO, end_date: ISO` | `{visits, favorites, orders, revenue_usd}` (some fields may be unavailable depending on Etsy API exposure) |

#### Bulk export (3)

| Tool | Args | Returns |
|------|------|---------|
| `etsy_export_all_listings` | `format ∈ {json, csv, both} = "both"`, `output_dir: str` | `{listings_count, files: [paths]}` |
| `etsy_export_all_receipts` | `format`, `output_dir`, `since?: ISO date` | `{receipts_count, files: [paths]}` |
| `etsy_export_all_reviews` | `format`, `output_dir` | `{reviews_count, files: [paths]}` |

CSV columns are flat-mapped from the API response with nested fields dot-joined (e.g. `price.amount`, `price.currency_code`). JSON is the raw API response array.

#### Etsy Ads — browser (4)

| Tool | Args | Returns |
|------|------|---------|
| `etsy_ads_get_status` | — | `{enabled: bool, daily_budget_usd, last_30d: {spend_usd, clicks, impressions, orders, revenue_usd}}` |
| `etsy_ads_create_campaign` | `daily_budget_usd: float`, `confirm: bool = False` | `{enabled: true, daily_budget_usd}` |
| `etsy_ads_set_budget` | `daily_budget_usd: float` | `{daily_budget_usd}` |
| `etsy_ads_pause` / `etsy_ads_resume` | — | `{enabled: bool}` |

### 5.2 Tier 2 — Operational (~16 tools)

#### Order ops (3)

| Tool | Args | Returns |
|------|------|---------|
| `etsy_mark_receipt_shipped` | `receipt_id, tracking_code, carrier_name, send_bcc: bool = false` | `{shipped: true, notification_sent: bool}` |
| `etsy_issue_refund` | `receipt_id, amount_cents: int, reason: str, confirm: bool = False` | `{refund_id, amount_cents, status}` |
| `etsy_bulk_mark_shipped` | `csv_path: str` (columns: receipt_id, tracking_code, carrier_name) | `{succeeded: int, failed: [{receipt_id, error}]}` |

#### Shop config (4)

- `etsy_list_shipping_profiles` / `etsy_create_shipping_profile` / `etsy_update_shipping_profile`
- `etsy_list_shop_sections` / `etsy_create_shop_section` / `etsy_update_shop_section`
- `etsy_list_return_policies` / `etsy_create_return_policy`
- `etsy_list_production_partners` / `etsy_create_production_partner`

#### Inventory bulk (3)

| Tool | Args | Returns |
|------|------|---------|
| `etsy_bulk_update_prices` | `updates: [{listing_id, price_usd}]`, `apply: bool = False` | dry-run report or applied report |
| `etsy_bulk_update_quantities` | `updates: [{listing_id, sku, quantity}]`, `apply: bool = False` | dry-run report or applied report |
| `etsy_bulk_renew_listings` | `listing_ids: list[int]`, `confirm: bool = False` | `{renewed: int, failed: [{listing_id, error}]}` |

### 5.3 Tier 3 — Advanced (~8 tools)

#### Listing power tools (3)

| Tool | Args | Returns |
|------|------|---------|
| `etsy_duplicate_listing` | `listing_id`, `new_title?: str` | `{new_listing_id, state: "draft", url}` (clones images + inventory + tags + materials) |
| `etsy_save_listing_template` | `listing_id`, `template_path: str` | `{template_path}` |
| `etsy_apply_listing_template` | `template_path: str`, `target_listing_ids: list[int]`, `apply: bool = False` | dry-run report or applied report |

#### Sales & promos — browser (3)

| Tool | Args | Returns |
|------|------|---------|
| `etsy_create_sale` | `percent_off: int`, `listing_ids: list[int]`, `start_iso, end_iso`, `confirm: bool = False` | `{sale_id, listings_count}` |
| `etsy_create_coupon` | `code: str, percent_off: int, min_purchase_usd?, free_shipping: bool = False, confirm: bool = False` | `{coupon_id, code}` |
| `etsy_list_active_sales` | — | `[{sale_id, percent_off, start, end, listings_count}]` |

#### Reporting (2)

| Tool | Args | Returns |
|------|------|---------|
| `etsy_revenue_report` | `start: ISO, end: ISO, group_by ∈ {day, week, month}` | `[{period, revenue_usd, orders, units}]` |
| `etsy_top_listings_report` | `start, end, by ∈ {revenue, units, views}, limit: int = 20` | `[{listing_id, title, value}]` |

## 6. Cross-Cutting Concerns

### 6.1 Rate Limits & Retries

- Etsy API: 10 req/sec, 10,000/day per app.
- `http.py` exposes a single `etsy_request(method, path, **kwargs)` that all tools call.
- Token-bucket limiter at 10/s in-process.
- On `429`: read `Retry-After` header (default 2s), sleep, retry up to 3 times.
- On `5xx`: exponential backoff (1s, 2s, 4s), retry up to 3 times.
- On network error (`httpx.RequestError`): retry once after 1s.
- After retries exhausted, return structured error.

### 6.2 Error Contract

Every tool returns either:

- **Success:** the data dict/list directly (mirrors Shopify MCP convention).
- **Failure:** `{"error": "<human readable>", "code": "<machine code>", "details": {...}}`

Codes:
- `auth_expired` — refresh token dead, user must re-bootstrap.
- `auth_invalid` — keystring/shared_secret wrong.
- `not_found` — 404 from Etsy.
- `rate_limited` — 429 after retries exhausted.
- `validation_failed` — 400 with field errors (details includes Etsy's error body).
- `network` — connection-level failure after retries.
- `session_expired` — Playwright detected login redirect.
- `selector_missing` — Playwright couldn't find expected element.
- `unknown` — fallback.

### 6.3 Logging

- `structlog` configured to write JSON lines to `logs/etsy_mcp.log`.
- Daily rotation, 7-day retention.
- Log level via `ETSY_LOG_LEVEL` (default `INFO`).
- Every API call logs `{endpoint, method, status, duration_ms, retry_count}`.
- **Never log:** access_token, refresh_token, shared_secret, OAuth code, full receipt PII (buyer email, address). Log receipt_id only.

### 6.4 Safety Guards (write tools)

These tools require an explicit `confirm: bool = True` argument or fail closed:
- `etsy_delete_listing`
- `etsy_issue_refund` (also prints amount + receipt summary in error if confirm missing)
- `etsy_ads_create_campaign`
- `etsy_create_sale`, `etsy_create_coupon`
- `etsy_bulk_renew_listings`

These tools default to `apply: bool = False` (dry-run), returning a preview report:
- `etsy_bulk_update_prices`
- `etsy_bulk_update_quantities`
- `etsy_apply_listing_template`

### 6.5 Testing

- `tests/unit/` — pure logic, no network. Covers token refresh rotation, retry/rate-limit math, CSV export formatting, taxonomy search, dry-run reports.
- `tests/integration/` — gated by `RUN_LIVE_TESTS=1`. One read test per resource against the real shop. No mocking — we want real Etsy responses.
- `tests/browser/` — Playwright tests against ads dashboard, marked `manual`, run via `pytest -m manual` only. Skipped in CI/default runs.
- Critical test: `test_refresh_token_rotates_on_use` — use a fake token endpoint, verify new refresh token is persisted and old one discarded.

## 7. Phased Rollout

Each phase ships independently with its own implementation plan + verification checkpoint.

| Phase | Scope | Acceptance |
|-------|-------|------------|
| 0 | Project scaffold, `auth.py`, `http.py`, `bootstrap_oauth.py`, `server.py` skeleton with `etsy_whoami` + `etsy_token_status` | OAuth bootstrap completes, `etsy_whoami` returns shop info from Claude |
| 1a | Listings/receipts/reviews/shop **read** tools | All Tier 1 read tools return real data from Claude |
| 1b | Listings **write** tools, taxonomy search, bulk export | Create draft listing + upload image, export listings to CSV |
| 1c | `bootstrap_ads_login.py`, Etsy Ads browser tools | `etsy_ads_get_status` works, can flip ads on/off |
| 2 | Order ops (ship, refund, bulk-ship), shop config, inventory bulk | Mark receipt shipped, bulk price update on 3 listings |
| 3 | Listing duplicate/templates, sales/coupons (browser), reporting | Create sale on 5 listings via browser, generate revenue report |

Phase 0 is foundational and blocking. Phases 1a/1b/1c can technically be parallelized but the spec assumes serial execution for simplicity. Phases 2 and 3 are independent.

## 8. Out-of-Scope / Future Work

- Webhooks (Etsy supports them; revisit if needed).
- Multi-shop support.
- Caching layer (none for now — every call hits Etsy live).
- A web dashboard UI on top of the MCP.
- Scheduled exports (could be added later via cron + a CLI wrapper).
- Translation/multi-language listing support.

## 9. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Etsy dashboard layout changes break ads selectors | Selectors centralized + dated; selector_missing error includes screenshot path |
| Refresh token expires after 90 days unnoticed | `etsy_token_status` exposes refresh age; user can monitor |
| Refresh-token-rotation bug bricks auth | Unit-tested explicitly; atomic file write prevents partial state |
| Headless Chromium hits Cloudflare bot detection | `ETSY_ADS_HEADFUL=1` fallback to visible browser |
| Bulk write tools silently corrupt many listings | Default dry-run + `apply=True` opt-in |
| Tokens / credentials accidentally committed | `.gitignore` covers `.env`, `.tokens.json`, `.storage_state.json`, `logs/` |

## 10. Open Questions

None at spec time. Each phase plan may surface implementation-specific questions to resolve at that point.
