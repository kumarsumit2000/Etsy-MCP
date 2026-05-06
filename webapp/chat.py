"""Claude chat — runs an agentic tool-use loop over the Etsy MCP tools.

Registers every MCP tool factory onto a FastMCP instance, extracts the
list of tools as Anthropic tool definitions, and uses Claude to drive
multi-step queries ("what's my revenue this week?", "any low-star
reviews recently?", "draft a 15% sale on the cushion line").

The user's Anthropic key is read from `.anthropic_key` (written by the
setup wizard). Each request creates a fresh `anthropic.Anthropic` client.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import anthropic

PROJECT_ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from etsy_mcp.browser import register_browser_tools  # noqa: E402
from etsy_mcp.bulk_ops import register_bulk_ops_tools  # noqa: E402
from etsy_mcp.exports import register_export_tools  # noqa: E402
from etsy_mcp.listings import register_listing_tools  # noqa: E402
from etsy_mcp.messages import register_message_tools  # noqa: E402
from etsy_mcp.orders import register_order_tools  # noqa: E402
from etsy_mcp.receipts import register_receipt_tools  # noqa: E402
from etsy_mcp.reporting import register_reporting_tools  # noqa: E402
from etsy_mcp.reviews import register_review_tools  # noqa: E402
from etsy_mcp.shop import register_shop_tools  # noqa: E402
from etsy_mcp.shop_config import register_shop_config_tools  # noqa: E402
from etsy_mcp.taxonomy import register_taxonomy_tools  # noqa: E402

from webapp import state  # noqa: E402

CLAUDE_MODEL = "claude-sonnet-4-6"
MAX_TURNS = 12  # safety bound on the tool-use loop
MAX_TOKENS = 4096

SYSTEM_PROMPT = """You are an assistant for an Etsy shop owner. You have access \
to a set of tools that read and write to the user's Etsy shop.

Guidelines:
- For destructive operations (delete listing, issue refund, turn ads on, create \
  sale/coupon, bulk renew, ship orders), confirm with the user before calling. \
  These tools have a `confirm` or `apply` parameter — show the dry-run / \
  preview first when available.
- Today's date is in the user's local shop timezone. When they say "today" or \
  "this week", interpret accordingly.
- When you call a tool that returns lots of rows, summarize the highlights \
  rather than dumping the whole list.
- If a tool returns `{"error": ...}`, tell the user what went wrong instead of \
  pretending it worked.
- Format numerical data as compact tables when it helps readability.
- Be concise and helpful — this is a busy seller, not a chat partner.
"""


_mcp_instance: FastMCP | None = None
_tool_definitions: list[dict[str, Any]] | None = None


def _build_mcp() -> FastMCP:
    """Lazily register every tool factory once on a process-wide FastMCP."""
    global _mcp_instance
    if _mcp_instance is not None:
        return _mcp_instance

    m = FastMCP("etsy-chat")
    keystring = state.env_value("ETSY_KEYSTRING")
    tokens_path = str(state.TOKENS_PATH)
    shop_id_getter = lambda: state.env_value("ETSY_SHOP_ID")

    common = {
        "keystring": keystring,
        "tokens_path": tokens_path,
        "shop_id_getter": shop_id_getter,
    }
    register_shop_tools(m, **common)
    register_listing_tools(m, **common)
    register_receipt_tools(m, **common)
    register_review_tools(m, **common)
    register_taxonomy_tools(m, keystring=keystring, tokens_path=tokens_path)
    register_export_tools(m, **common)
    register_browser_tools(m, **common)
    register_order_tools(m, **common)
    register_shop_config_tools(m, **common)
    register_bulk_ops_tools(m, **common)
    register_reporting_tools(m, **common)
    register_message_tools(m, **common)
    _mcp_instance = m
    return m


async def _list_tools_for_anthropic() -> list[dict[str, Any]]:
    """Extract Anthropic-shaped tool definitions from the FastMCP instance."""
    global _tool_definitions
    if _tool_definitions is not None:
        return _tool_definitions
    m = _build_mcp()
    tools = await m.list_tools()
    out = []
    for t in tools:
        out.append(
            {
                "name": t.name,
                "description": (t.description or "")[:1024],
                "input_schema": t.inputSchema,
            }
        )
    _tool_definitions = out
    return out


async def _run_tool(name: str, args: dict[str, Any]) -> str:
    """Invoke a tool by name; return a JSON-string result for Claude."""
    m = _build_mcp()
    try:
        result = await m.call_tool(name, args)
    except Exception as exc:
        return json.dumps({"error": f"Tool '{name}' raised: {exc}", "code": "exception"})
    # FastMCP returns a list of TextContent (or similar). Concatenate text parts.
    if isinstance(result, list):
        parts = []
        for r in result:
            if hasattr(r, "text"):
                parts.append(r.text)
            else:
                parts.append(str(r))
        return "\n".join(parts) or "(empty)"
    return str(result)


async def chat(messages: list[dict[str, Any]], anthropic_key: str | None = None) -> dict[str, Any]:
    """Run the agentic tool-use loop.

    Args:
        messages: full conversation history in Anthropic message format
            ([{role: 'user'|'assistant', content: str | list}]).
        anthropic_key: override the on-disk key (used for testing).

    Returns:
        {
          "assistant_message": dict,    # the final Anthropic message object
          "trace": list[dict],          # per-turn record: tool calls + results
          "stop_reason": str,
        }
    """
    api_key = (anthropic_key or state.read_anthropic_key() or "").strip()
    if not api_key:
        return {
            "assistant_message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Anthropic API key not configured. Re-run setup."}],
            },
            "trace": [],
            "stop_reason": "error",
        }

    client = anthropic.Anthropic(api_key=api_key)
    tool_defs = await _list_tools_for_anthropic()

    convo = list(messages)
    trace: list[dict[str, Any]] = []

    for turn in range(MAX_TURNS):
        try:
            resp = await asyncio.to_thread(
                client.messages.create,
                model=CLAUDE_MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                tools=tool_defs,
                messages=convo,
            )
        except anthropic.AuthenticationError as exc:
            return {
                "assistant_message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": (
                        "Anthropic rejected the API key. Re-check it on the "
                        "setup page (`/setup/anthropic`)."
                    )}],
                },
                "trace": trace,
                "stop_reason": "auth_error",
            }
        except anthropic.APIError as exc:
            return {
                "assistant_message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": f"Anthropic API error: {exc}"}],
                },
                "trace": trace,
                "stop_reason": "api_error",
            }

        # Append the assistant turn to the conversation
        assistant_content = [block.model_dump() for block in resp.content]
        convo.append({"role": "assistant", "content": assistant_content})

        if resp.stop_reason != "tool_use":
            return {
                "assistant_message": {"role": "assistant", "content": assistant_content},
                "trace": trace,
                "stop_reason": resp.stop_reason,
            }

        # Run every tool_use block, append a single user turn carrying all
        # tool_result blocks (Anthropic's spec)
        tool_results: list[dict[str, Any]] = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            name = block.name
            args = block.input or {}
            result_text = await _run_tool(name, args)
            trace.append(
                {
                    "tool": name,
                    "args": args,
                    "result_preview": result_text[:400],
                }
            )
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text[:50_000],  # safety cap on tool output size
                }
            )

        convo.append({"role": "user", "content": tool_results})

    return {
        "assistant_message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "Hit max tool-use turns; please rephrase."}],
        },
        "trace": trace,
        "stop_reason": "max_turns",
    }
