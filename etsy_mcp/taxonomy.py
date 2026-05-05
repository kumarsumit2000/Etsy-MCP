"""Taxonomy lookup for Etsy MCP.

The Etsy seller taxonomy is a tree of ~3000 category nodes. This module
fetches the tree once via getSellerTaxonomyNodes, caches it in-process,
and offers a substring search returning the top 20 matches.

Cache is keyed by keystring so multiple shops in tests don't collide.
The tree changes very rarely; per-process caching is safe.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from .errors import EtsyMCPError
from .http import etsy_request

# Module-level cache: {keystring: list[{taxonomy_id, name, level, full_path}]}
_CACHE: dict[str, list[dict[str, Any]]] = {}


def _flatten(nodes: list[dict[str, Any]], parent_path: str = "") -> list[dict[str, Any]]:
    """Walk the Etsy seller-taxonomy tree, return flat list of nodes with full paths."""
    out: list[dict[str, Any]] = []
    for node in nodes:
        name = node.get("name", "")
        path = f"{parent_path} > {name}" if parent_path else name
        out.append(
            {
                "taxonomy_id": node.get("id"),
                "name": name,
                "level": node.get("level", 0),
                "full_path": path,
            }
        )
        children = node.get("children") or []
        if children:
            out.extend(_flatten(children, path))
    return out


def register_taxonomy_tools(
    mcp: FastMCP,
    *,
    keystring: str,
    tokens_path: str | Path,
) -> dict[str, Callable]:
    """Register taxonomy tools (no shop_id_getter — taxonomy is shop-agnostic)."""

    async def _ensure_tree() -> list[dict[str, Any]]:
        if keystring in _CACHE:
            return _CACHE[keystring]
        tree = await etsy_request(
            "GET",
            "/application/seller-taxonomy/nodes",
            keystring=keystring,
            tokens_path=str(tokens_path),
        )
        nodes = tree.get("results") if isinstance(tree, dict) else None
        if not isinstance(nodes, list):
            return []
        flat = _flatten(nodes)
        _CACHE[keystring] = flat
        return flat

    @mcp.tool()
    async def etsy_taxonomy_search(query: str) -> list[dict[str, Any]]:
        """Find Etsy seller-taxonomy nodes by keyword.

        Substring match (case-insensitive) against the node's name AND its full
        path. Returns the top 20 matches sorted by depth (deeper first — more
        specific categories) then by path length.

        Use the returned taxonomy_id when calling etsy_create_draft_listing.
        """
        try:
            tree = await _ensure_tree()
        except EtsyMCPError as exc:
            return [exc.to_dict()]  # Error path returned as a single-element list for tool consistency.

        needle = query.lower()
        matches = [
            node
            for node in tree
            if needle in node["name"].lower() or needle in node["full_path"].lower()
        ]
        # Deeper matches first (more specific), then alphabetical
        matches.sort(key=lambda n: (-n["level"], n["full_path"]))
        return matches[:20]

    return {"etsy_taxonomy_search": etsy_taxonomy_search}
