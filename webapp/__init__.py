"""Etsy Copilot — a self-hosted web dashboard wrapping the Etsy MCP."""

from pathlib import Path

# Load .env on package import so any submodule (state, alerts, main) sees
# ETSY_SHARED_SECRET / ETSY_SHOP_TIMEZONE / etc. via os.environ. Idempotent.
from dotenv import load_dotenv as _load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_load_dotenv(_PROJECT_ROOT / ".env", override=False)
