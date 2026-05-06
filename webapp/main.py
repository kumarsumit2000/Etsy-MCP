"""Etsy Copilot — FastAPI web wizard + dashboard.

Run with:
    python -m webapp

The wizard walks the user through:
  1. Anthropic API key
  2. Etsy app credentials (keystring + shared_secret)
  3. Etsy OAuth (PKCE flow inside an iframe-friendly redirect)
  4. Chrome profile picker → cookie import
  5. Done → /dashboard

Everything stays on the user's machine. Credentials are written to .env,
.tokens.json, .storage_state.json — the same files the MCP server uses.
"""

from __future__ import annotations

import asyncio
import secrets
import sys
import urllib.parse
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env so etsy_request() can find ETSY_SHARED_SECRET, ETSY_SHOP_TIMEZONE,
# etc. via os.environ. We re-load on every status check so newly-saved
# credentials take effect without a process restart.
from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env", override=True)

# Project-internal imports
from etsy_mcp.auth import TokenStore, generate_pkce_pair, ETSY_TOKEN_URL  # noqa: E402
from webapp import alerts, chat as chat_module, state  # noqa: E402

# Try to import cookie helpers; the script lives at scripts/import_cookies_from_chrome.py
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
try:
    import import_cookies_from_chrome as cookie_importer  # noqa: E402
except Exception:  # pragma: no cover
    cookie_importer = None

ETSY_AUTHORIZE_URL = "https://www.etsy.com/oauth/connect"
ETSY_API_BASE = "https://openapi.etsy.com/v3"
SCOPES = [
    "listings_r", "listings_w", "listings_d",
    "shops_r", "shops_w",
    "transactions_r", "transactions_w",
    "feedback_r",
    "email_r", "profile_r", "address_r",
]

app = FastAPI(title="Etsy Copilot")

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# In-memory OAuth state (single-user app — fine to keep this in process memory)
_oauth_state: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _ctx(request: Request, **extra: Any) -> dict[str, Any]:
    """Standard template context: status snapshot + the request object."""
    return {"request": request, "status": state.status(), **extra}


def _redirect_uri(request: Request) -> str:
    """Build the OAuth redirect URI from the incoming request's host.

    Etsy must have this exact URI added to the app's Callback URLs. For
    localhost development that's typically http://localhost:8765/oauth/callback.
    """
    return str(request.url_for("oauth_callback"))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> Any:
    next_step = state.first_incomplete_step()
    if next_step == "done":
        return RedirectResponse(url="/dashboard", status_code=302)
    return RedirectResponse(url=f"/setup/{next_step}", status_code=302)


@app.get("/setup/anthropic", response_class=HTMLResponse)
async def setup_anthropic_get(request: Request) -> Any:
    return templates.TemplateResponse(request, "setup_anthropic.html", _ctx(request))


@app.post("/setup/anthropic")
async def setup_anthropic_post(api_key: str = Form(...)) -> Any:
    api_key = api_key.strip()
    if not api_key.startswith("sk-ant-"):
        return RedirectResponse(
            url="/setup/anthropic?error=Key+must+start+with+sk-ant-", status_code=303
        )
    state.write_anthropic_key(api_key)
    return RedirectResponse(url="/setup/etsy_credentials", status_code=303)


@app.get("/setup/etsy_credentials", response_class=HTMLResponse)
async def setup_etsy_credentials_get(request: Request) -> Any:
    return templates.TemplateResponse(
        request,
        "setup_etsy_credentials.html",
        _ctx(
            request,
            keystring=state.env_value("ETSY_KEYSTRING"),
            shared_secret=state.env_value("ETSY_SHARED_SECRET"),
            timezone=state.env_value("ETSY_SHOP_TIMEZONE") or "America/Denver",
        ),
    )


@app.post("/setup/etsy_credentials")
async def setup_etsy_credentials_post(
    keystring: str = Form(...),
    shared_secret: str = Form(...),
    timezone: str = Form("America/Denver"),
) -> Any:
    if not keystring.strip() or not shared_secret.strip():
        return RedirectResponse(
            url="/setup/etsy_credentials?error=Both+fields+required", status_code=303
        )
    state.write_env_keys(
        {
            "ETSY_KEYSTRING": keystring.strip(),
            "ETSY_SHARED_SECRET": shared_secret.strip(),
            "ETSY_SHOP_TIMEZONE": timezone.strip() or "America/Denver",
        }
    )
    return RedirectResponse(url="/setup/oauth", status_code=303)


@app.get("/setup/oauth", response_class=HTMLResponse)
async def setup_oauth_get(request: Request) -> Any:
    return templates.TemplateResponse(
        request,
        "setup_oauth.html",
        _ctx(request, redirect_uri=_redirect_uri(request)),
    )


@app.post("/setup/oauth/start")
async def setup_oauth_start(request: Request) -> Any:
    keystring = state.env_value("ETSY_KEYSTRING")
    if not keystring:
        return RedirectResponse(url="/setup/etsy_credentials", status_code=303)

    verifier, challenge = generate_pkce_pair()
    csrf_state = secrets.token_urlsafe(24)
    redirect_uri = _redirect_uri(request)

    _oauth_state["verifier"] = verifier
    _oauth_state["state"] = csrf_state
    _oauth_state["redirect_uri"] = redirect_uri

    auth_url = (
        f"{ETSY_AUTHORIZE_URL}?"
        + urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": keystring,
                "redirect_uri": redirect_uri,
                "scope": " ".join(SCOPES),
                "state": csrf_state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
    )
    return RedirectResponse(url=auth_url, status_code=303)


@app.get("/oauth/callback", name="oauth_callback")
async def oauth_callback(request: Request, code: str = "", state_: str | None = None) -> Any:
    # FastAPI doesn't allow underscored param shadowing of `state` (the imported
    # module), so accept it via query param explicitly.
    state_received = request.query_params.get("state", "")
    err = request.query_params.get("error")
    if err:
        return templates.TemplateResponse(
        request,
            "setup_oauth.html",
            _ctx(request, error=f"Etsy returned: {err}", redirect_uri=_redirect_uri(request)),
            status_code=400,
        )
    if not code or state_received != _oauth_state.get("state"):
        return templates.TemplateResponse(
        request,
            "setup_oauth.html",
            _ctx(
                request,
                error="OAuth state mismatch or missing code. Try again.",
                redirect_uri=_redirect_uri(request),
            ),
            status_code=400,
        )

    keystring = state.env_value("ETSY_KEYSTRING")
    shared_secret = state.env_value("ETSY_SHARED_SECRET")
    redirect_uri = _oauth_state.get("redirect_uri") or _redirect_uri(request)

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            ETSY_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": keystring,
                "redirect_uri": redirect_uri,
                "code": code,
                "code_verifier": _oauth_state.get("verifier", ""),
            },
        )
    if resp.status_code != 200:
        return templates.TemplateResponse(
        request,
            "setup_oauth.html",
            _ctx(
                request,
                error=f"Token exchange failed ({resp.status_code}): {resp.text[:200]}",
                redirect_uri=_redirect_uri(request),
            ),
            status_code=400,
        )

    body = resp.json()
    TokenStore(state.TOKENS_PATH).save(
        access_token=body["access_token"],
        refresh_token=body["refresh_token"],
        expires_in=body["expires_in"],
        scope=body.get("scope", " ".join(SCOPES)),
    )

    # Auto-fetch shop_id
    headers = {
        "x-api-key": f"{keystring}:{shared_secret}",
        "Authorization": f"Bearer {body['access_token']}",
    }
    shop_id = ""
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            me = await client.get(f"{ETSY_API_BASE}/application/users/me", headers=headers)
            if me.status_code == 200:
                user_id = me.json()["user_id"]
                shops = await client.get(
                    f"{ETSY_API_BASE}/application/users/{user_id}/shops",
                    headers=headers,
                )
                if shops.status_code == 200:
                    sd = shops.json()
                    shop = sd["results"][0] if "results" in sd else sd
                    shop_id = str(shop.get("shop_id") or shop.get("id") or "")
    except Exception:
        shop_id = ""

    if shop_id:
        state.write_env_keys({"ETSY_SHOP_ID": shop_id})

    return RedirectResponse(url="/setup/cookies", status_code=303)


@app.get("/setup/cookies", response_class=HTMLResponse)
async def setup_cookies_get(request: Request) -> Any:
    profiles: list[dict[str, str]] = []
    if cookie_importer is not None:
        try:
            profiles = cookie_importer._list_profiles()
        except Exception:
            profiles = []
    return templates.TemplateResponse(
        request,
        "setup_cookies.html",
        _ctx(request, profiles=profiles, available=cookie_importer is not None),
    )


@app.post("/setup/cookies/import")
async def setup_cookies_import(email: str = Form(...)) -> Any:
    if cookie_importer is None:
        raise HTTPException(500, "browser_cookie3 not installed.")
    profiles = cookie_importer._list_profiles()
    profile_dir = next((p["dir"] for p in profiles if p["email"].lower() == email.lower()), None)
    if not profile_dir:
        return RedirectResponse(
            url=f"/setup/cookies?error=No+Chrome+profile+for+{urllib.parse.quote(email)}",
            status_code=303,
        )

    try:
        cookie_file = str(cookie_importer.CHROME_USER_DATA_DIR / profile_dir / "Cookies")
        cj = cookie_importer.browser_cookie3.chrome(
            domain_name="etsy.com", cookie_file=cookie_file
        )
        pw_cookies = []
        for c in cj:
            if "etsy.com" in c.domain:
                pw_cookies.append(cookie_importer._to_playwright_cookie(c))
    except Exception as exc:
        return RedirectResponse(
            url=f"/setup/cookies?error=Could+not+read+cookies:+{urllib.parse.quote(str(exc)[:80])}",
            status_code=303,
        )

    if not pw_cookies:
        return RedirectResponse(
            url=f"/setup/cookies?error=No+Etsy+cookies+in+that+Chrome+profile.+Make+sure+you're+logged+into+etsy.com.",
            status_code=303,
        )

    import json
    state.STORAGE_STATE_PATH.write_text(
        json.dumps({"cookies": pw_cookies, "origins": []}, indent=2)
    )
    state.STORAGE_STATE_PATH.chmod(0o600)

    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request) -> Any:
    s = state.status()
    if not all([s["anthropic_key"], s["etsy_credentials"], s["etsy_oauth"], s["browser_cookies"]]):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(request, "dashboard.html", _ctx(request))


# ---------------------------------------------------------------------------
# Alerts API — JSON, polled by the dashboard JS
# ---------------------------------------------------------------------------
@app.get("/api/alerts/snapshot")
async def alerts_snapshot() -> JSONResponse:
    """Return all four alert tiles in one shot. JS polls this every 60s."""
    snap = await alerts.snapshot()
    return JSONResponse(snap)


@app.post("/api/chat")
async def chat_endpoint(request: Request) -> JSONResponse:
    """Run one round of the Claude tool-use loop.

    Request body: {"messages": [{role, content}, ...]}
    Response: {"assistant_message": ..., "trace": [...], "stop_reason": "..."}
    """
    body = await request.json()
    messages = body.get("messages", [])
    if not isinstance(messages, list) or not messages:
        raise HTTPException(400, "messages must be a non-empty list")
    result = await chat_module.chat(messages)
    return JSONResponse(result)


@app.get("/api/alerts/{key}/items")
async def alerts_detail(key: str) -> JSONResponse:
    """Return the items list for a single alert (used by the expand-tile UI)."""
    fn_map = {
        "missed_chats": alerts.alert_missed_chats,
        "new_orders": alerts.alert_new_orders_today,
        "needs_shipping": alerts.alert_needs_shipping,
        "bad_reviews": alerts.alert_bad_reviews,
    }
    fn = fn_map.get(key)
    if not fn:
        raise HTTPException(404, f"Unknown alert key: {key}")
    return JSONResponse(await fn())


def run() -> None:  # pragma: no cover
    """Entry point used by `python -m webapp`."""
    import uvicorn

    port = int(__import__("os").environ.get("ETSY_COPILOT_PORT", "8765"))
    print(f"\n  Etsy Copilot starting at http://localhost:{port}\n")
    print(
        f"  Important: add http://localhost:{port}/oauth/callback to your "
        "Etsy app's Callback URL(s) at https://www.etsy.com/developers/your-apps\n"
    )
    uvicorn.run("webapp.main:app", host="127.0.0.1", port=port, reload=False)
