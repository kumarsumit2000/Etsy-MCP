"""Browser-driven tools for Etsy buyer/seller conversations.

Etsy's v3 Open API does not expose conversations, so these tools drive
https://www.etsy.com/your/conversations via Playwright using the saved
storage_state from scripts/bootstrap_browser_login.py.

Tools:
  - etsy_list_conversations: list inbox threads with optional "missed" filter
  - etsy_get_conversation: full thread for one conversation_id

"Missed" semantics (option C):
  An unread conversation whose last message is older than `min_age_hours`.
  Bounded by `since_hours` so we don't scroll the whole inbox history.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from .browser import (
    EtsyBrowser,
    _ensure_logged_in,
    _save_error_screenshot,
    _selector_missing_error,
    _session_expired_error,
)
from .timeutil import shop_tz

ETSY_CONVERSATIONS_URL = "https://www.etsy.com/messages/inbox"
ETSY_CONVERSATION_THREAD_URL_TEMPLATE = "https://www.etsy.com/messages/{conversation_id}"

# Etsy renders each inbox row's accessible text in a fixed-ish shape:
#   "Select this conversation with <SENDER> from <DATE_OR_RELATIVE>\n
#    <read|unread> message\n
#    <SENDER>\n
#    <PREVIEW...>"
# We capture: conversation_id from the /messages/<id> href, sender + date_text
# from the leading line, unread state from the "unread message" / "read message"
# token, and preview from whatever's left. We deliberately avoid CSS class
# names because Etsy renames them frequently.
_INBOX_SCRAPE_JS = r"""
() => {
  const rows = [];
  const anchors = document.querySelectorAll("a[href*='/messages/']");
  const seen = new Set();
  for (const a of anchors) {
    const href = a.getAttribute('href') || '';
    const m = href.match(/\/messages\/(\d+)/);
    if (!m) continue;
    const cid = m[1];
    if (seen.has(cid)) continue;
    seen.add(cid);

    let row = a.closest("li, [role='listitem'], article, tr");
    if (!row) row = a.parentElement;

    const text = (row.innerText || '').trim();
    rows.push({ conversation_id: cid, raw_text: text.slice(0, 600) });
  }
  return rows;
}
"""


_ROW_HEADER_RE = re.compile(
    r"Select this conversation with (?P<sender>.+?) from (?P<date>.+?)\n", re.S
)
_ABS_DATE_RE = re.compile(r"^(\d{1,2})\s+(\w+),?\s+(\d{4})$")
_RELATIVE_RE = re.compile(
    r"(\d+)\s*(minute|min|hour|hr|day|second|sec)s?\s*ago", re.I
)
_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ]
    )
}
_MONTH_ABBREV = {m[:3]: i for m, i in _MONTHS.items()}


def _parse_etsy_date(text: str, now: datetime) -> datetime | None:
    """Parse the date string Etsy renders next to each conversation row.

    Etsy uses several formats:
      - "01 Aug, 2024"  (absolute, no time)
      - "2 hours ago", "5 minutes ago", "3 days ago"  (relative)
      - "Today at 3:14 PM" / "Yesterday at 9:00 AM"
    Returns timezone-aware datetime in `now`'s tz, or None if unparseable.
    """
    if not text:
        return None
    s = text.strip()

    # Relative form: "2 hours ago", "5 minutes ago"
    m = _RELATIVE_RE.search(s)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        if unit.startswith("sec"):
            return now - timedelta(seconds=n)
        if unit.startswith("min"):
            return now - timedelta(minutes=n)
        if unit.startswith("hr") or unit.startswith("hour"):
            return now - timedelta(hours=n)
        if unit.startswith("day"):
            return now - timedelta(days=n)

    # "Today at 3:14 PM"
    if s.lower().startswith("today"):
        return now.replace(hour=now.hour, minute=now.minute, second=0, microsecond=0)
    if s.lower().startswith("yesterday"):
        return (now - timedelta(days=1)).replace(microsecond=0)

    # Absolute: "01 Aug, 2024" or "01 August 2024"
    parts = re.match(r"(\d{1,2})\s+(\w+),?\s+(\d{4})", s)
    if parts:
        day = int(parts.group(1))
        month_str = parts.group(2)
        year = int(parts.group(3))
        month = _MONTHS.get(month_str) or _MONTH_ABBREV.get(month_str[:3])
        if month:
            return datetime(year, month, day, tzinfo=now.tzinfo)

    return None


def _parse_row(raw_text: str, now: datetime) -> dict[str, Any]:
    """Extract sender, unread flag, last-message datetime, and preview from
    the row's accessible innerText."""
    header = _ROW_HEADER_RE.search(raw_text)
    sender = header.group("sender").strip() if header else None
    date_text = header.group("date").strip() if header else None
    last_dt = _parse_etsy_date(date_text, now) if date_text else None

    unread = bool(re.search(r"\bunread message\b", raw_text, re.I))

    # Preview = whatever follows the sender line that comes after the
    # "<read|unread> message" token
    preview = None
    parts = re.split(r"\b(?:un)?read message\s*\n", raw_text, maxsplit=1)
    if len(parts) == 2:
        # Drop the duplicate sender line that Etsy renders before the preview
        tail = parts[1].lstrip().split("\n", 1)
        preview = tail[1].strip() if len(tail) == 2 else tail[0].strip()
        if preview:
            preview = preview[:300]

    return {
        "sender": sender,
        "date_text": date_text,
        "last_message_at": last_dt,
        "unread": unread,
        "preview": preview,
    }


def _hours_since(dt: datetime, now: datetime) -> float:
    return (now - dt).total_seconds() / 3600.0


def register_message_tools(
    mcp: FastMCP,
    *,
    keystring: str,
    tokens_path: str,
    shop_id_getter: Callable[[], str],
) -> dict[str, Callable]:
    """Register conversation tools on the given FastMCP instance."""

    @mcp.tool()
    async def etsy_list_conversations(
        filter: str = "all",
        since_hours: int = 48,
        min_age_hours: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        """List Etsy inbox conversations from the seller dashboard.

        Args:
            filter: 'all' | 'unread' | 'missed'.
                - 'all': every visible thread.
                - 'unread': only unread threads.
                - 'missed': unread AND last message older than min_age_hours.
            since_hours: ignore threads older than this many hours
                (default 48 = past 2 days). Helps when you don't want to
                paginate the full inbox.
            min_age_hours: for filter='missed', the minimum age of the last
                message. Default 0 (any age).
            limit: cap on returned rows.

        Returns:
            { "rows": [...], "total_scanned": int, "filter": str }
            Each row: {conversation_id, buyer_name, preview, last_message_at,
            last_message_at_text, unread, age_hours}
        """
        if filter not in ("all", "unread", "missed"):
            return {
                "error": f"filter must be 'all', 'unread', or 'missed'; got '{filter}'",
                "code": "validation_failed",
            }

        try:
            async with EtsyBrowser() as page:
                await page.goto(ETSY_CONVERSATIONS_URL)
                if not await _ensure_logged_in(page):
                    return _session_expired_error()

                # Wait for *any* conversation anchor to render. If none ever
                # appear, the page either redesigned or the inbox is empty.
                try:
                    await page.wait_for_selector(
                        "a[href*='/messages/']", timeout=10_000
                    )
                except Exception:
                    # Could be empty inbox (legitimate) or layout change.
                    # Distinguish via page text.
                    body_text = (await page.content()).lower()
                    if "no messages" in body_text or "your inbox is empty" in body_text:
                        return {
                            "rows": [],
                            "total_scanned": 0,
                            "filter": filter,
                            "note": "Inbox is empty.",
                        }
                    screenshot = await _save_error_screenshot(page, "conversations_empty_render")
                    return _selector_missing_error(
                        "render conversation rows", screenshot
                    )

                raw_rows = await page.evaluate(_INBOX_SCRAPE_JS)

                if not raw_rows:
                    screenshot = await _save_error_screenshot(page, "conversations_no_rows")
                    return _selector_missing_error(
                        "extract conversation rows", screenshot
                    )

                now_local = datetime.now(tz=shop_tz())
                processed: list[dict[str, Any]] = []
                for r in raw_rows:
                    parsed = _parse_row(r.get("raw_text", ""), now_local)
                    last_dt = parsed["last_message_at"]
                    age_hours = (
                        _hours_since(last_dt, now_local) if last_dt else None
                    )
                    processed.append(
                        {
                            "conversation_id": r["conversation_id"],
                            "buyer_name": parsed["sender"],
                            "preview": parsed["preview"],
                            "last_message_at": last_dt.isoformat() if last_dt else None,
                            "last_message_at_text": parsed["date_text"],
                            "unread": parsed["unread"],
                            "age_hours": round(age_hours, 2) if age_hours is not None else None,
                        }
                    )

                # Apply since_hours bound (drop rows older than this)
                bounded = [
                    r for r in processed
                    if r["age_hours"] is None or r["age_hours"] <= since_hours
                ]

                if filter == "all":
                    rows = bounded
                elif filter == "unread":
                    rows = [r for r in bounded if r["unread"]]
                else:  # missed
                    rows = [
                        r for r in bounded
                        if r["unread"]
                        and r["age_hours"] is not None
                        and r["age_hours"] >= min_age_hours
                    ]

                return {
                    "rows": rows[:limit],
                    "total_scanned": len(raw_rows),
                    "filter": filter,
                    "since_hours": since_hours,
                    "min_age_hours": min_age_hours,
                }
        except FileNotFoundError:
            return _session_expired_error()

    @mcp.tool()
    async def etsy_get_conversation(conversation_id: str) -> dict[str, Any]:
        """Open a single conversation thread and return its messages.

        Args:
            conversation_id: numeric id from etsy_list_conversations.

        Returns:
            { "conversation_id", "messages": [{from, text, time_iso, time_text}, ...] }
        """
        url = ETSY_CONVERSATION_THREAD_URL_TEMPLATE.format(
            conversation_id=conversation_id
        )
        try:
            async with EtsyBrowser() as page:
                await page.goto(url)
                if not await _ensure_logged_in(page):
                    return _session_expired_error()

                try:
                    await page.wait_for_selector(
                        "[data-test-id*='message'], [class*='message'], article",
                        timeout=10_000,
                    )
                except Exception:
                    screenshot = await _save_error_screenshot(page, "conversation_thread_render")
                    return _selector_missing_error(
                        "render conversation thread", screenshot
                    )

                messages = await page.evaluate(
                    r"""
                () => {
                  const out = [];
                  const seen = new Set();
                  // Try common message containers; bail to <article> if needed
                  const candidates = document.querySelectorAll(
                    "[data-test-id*='message-bubble'], [data-test-id*='message'], [class*='message-bubble'], article"
                  );
                  for (const el of candidates) {
                    const text = (el.innerText || '').trim();
                    if (!text || text.length < 2) continue;
                    if (seen.has(text)) continue;
                    seen.add(text);

                    const timeEl = el.querySelector('time, [datetime]');
                    const time_iso = timeEl ? (timeEl.getAttribute('datetime') || null) : null;
                    const time_text = timeEl ? (timeEl.getAttribute('title') || timeEl.innerText || '').trim() : null;

                    // Sender heuristic: look for "from <name>" patterns or aria-label
                    let from = null;
                    const aria = (el.getAttribute('aria-label') || '').trim();
                    if (aria) from = aria;
                    const nameEl = el.querySelector('h1, h2, h3, h4, [class*=author], [class*=sender]');
                    if (nameEl && !from) from = (nameEl.innerText || '').trim() || null;

                    out.push({ from, text: text.slice(0, 4000), time_iso, time_text });
                  }
                  return out;
                }
                """
                )

                return {
                    "conversation_id": conversation_id,
                    "messages": messages or [],
                    "url": url,
                }
        except FileNotFoundError:
            return _session_expired_error()

    return {
        "etsy_list_conversations": etsy_list_conversations,
        "etsy_get_conversation": etsy_get_conversation,
    }
