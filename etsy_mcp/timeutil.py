"""Timezone helpers.

All user-facing dates ("May 1st") are interpreted in the shop's local timezone
configured by $ETSY_SHOP_TIMEZONE (default: America/Denver). Etsy stores
receipt timestamps as Unix epoch seconds (UTC under the hood); these helpers
bridge between the two.

Set ETSY_SHOP_TIMEZONE=America/Phoenix for strict MST (Arizona, no DST).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_DEFAULT_TZ = "America/Denver"


def shop_tz() -> ZoneInfo:
    name = os.environ.get("ETSY_SHOP_TIMEZONE", "").strip() or _DEFAULT_TZ
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo(_DEFAULT_TZ)


def parse_local_date(s: str) -> datetime | None:
    """Parse YYYY-MM-DD as local-midnight in the shop timezone."""
    try:
        return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=shop_tz())
    except ValueError:
        return None


def epoch_to_local(ts: int) -> datetime:
    """Convert a Unix-epoch timestamp to a datetime in the shop timezone."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(shop_tz())
