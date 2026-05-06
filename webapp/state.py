"""Setup state — reads/writes .env, .tokens.json, .storage_state.json.

The wizard's source of truth is the same files the MCP server already uses.
We don't introduce a separate database. A step is "done" iff its target
file/key on disk has the expected content.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
ENV_EXAMPLE_PATH = PROJECT_ROOT / ".env.example"
TOKENS_PATH = PROJECT_ROOT / ".tokens.json"
STORAGE_STATE_PATH = PROJECT_ROOT / ".storage_state.json"
ANTHROPIC_KEY_FILE = PROJECT_ROOT / ".anthropic_key"


def _read_env() -> dict[str, str]:
    if ENV_PATH.is_file():
        return {k: v or "" for k, v in dotenv_values(ENV_PATH).items()}
    if ENV_EXAMPLE_PATH.is_file():
        # Seed .env from example so we have a writable file
        shutil.copy(ENV_EXAMPLE_PATH, ENV_PATH)
        ENV_PATH.chmod(0o600)
        return {k: v or "" for k, v in dotenv_values(ENV_PATH).items()}
    return {}


def write_env_keys(updates: dict[str, str]) -> None:
    """Merge updates into .env, preserving comment lines and ordering."""
    if not ENV_PATH.is_file():
        if ENV_EXAMPLE_PATH.is_file():
            shutil.copy(ENV_EXAMPLE_PATH, ENV_PATH)
        else:
            ENV_PATH.touch()
        ENV_PATH.chmod(0o600)

    lines = ENV_PATH.read_text().splitlines()
    seen: set[str] = set()
    out_lines: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw:
            out_lines.append(raw)
            continue
        key = raw.split("=", 1)[0].strip()
        if key in updates:
            out_lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out_lines.append(raw)

    # Append any keys that weren't already present
    for key, val in updates.items():
        if key not in seen:
            out_lines.append(f"{key}={val}")

    ENV_PATH.write_text("\n".join(out_lines) + "\n")
    ENV_PATH.chmod(0o600)

    # Mirror updates into os.environ so any code reading the env (etsy_request
    # for ETSY_SHARED_SECRET, timeutil for ETSY_SHOP_TIMEZONE, etc.) picks up
    # new values without a process restart.
    for k, v in updates.items():
        os.environ[k] = v


def read_anthropic_key() -> str:
    """Anthropic key lives in its own file (not .env) so we don't accidentally
    expose it to the MCP subprocess as an env var."""
    if ANTHROPIC_KEY_FILE.is_file():
        return ANTHROPIC_KEY_FILE.read_text().strip()
    return ""


def write_anthropic_key(key: str) -> None:
    ANTHROPIC_KEY_FILE.write_text(key.strip())
    ANTHROPIC_KEY_FILE.chmod(0o600)


def read_tokens() -> dict[str, Any] | None:
    if not TOKENS_PATH.is_file():
        return None
    try:
        return json.loads(TOKENS_PATH.read_text())
    except (ValueError, OSError):
        return None


def storage_state_exists() -> bool:
    return STORAGE_STATE_PATH.is_file()


def status() -> dict[str, Any]:
    """Return a structured snapshot of which setup steps are done."""
    env = _read_env()
    tokens = read_tokens()
    return {
        "anthropic_key": bool(read_anthropic_key()),
        "etsy_credentials": bool(env.get("ETSY_KEYSTRING")) and bool(env.get("ETSY_SHARED_SECRET")),
        "etsy_oauth": tokens is not None and bool(tokens.get("access_token")),
        "etsy_shop_id": bool(env.get("ETSY_SHOP_ID")),
        "browser_cookies": storage_state_exists(),
        "shop_timezone": env.get("ETSY_SHOP_TIMEZONE", "America/Denver"),
    }


def first_incomplete_step() -> str:
    s = status()
    if not s["anthropic_key"]:
        return "anthropic"
    if not s["etsy_credentials"]:
        return "etsy_credentials"
    if not s["etsy_oauth"] or not s["etsy_shop_id"]:
        return "oauth"
    if not s["browser_cookies"]:
        return "cookies"
    return "done"


def env_value(key: str) -> str:
    return _read_env().get(key, "")
