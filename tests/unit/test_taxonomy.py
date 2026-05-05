"""Tests for etsy_mcp.taxonomy tools."""

from __future__ import annotations

import httpx
import pytest
import respx

from etsy_mcp.http import ETSY_API_BASE
from etsy_mcp.taxonomy import register_taxonomy_tools, _CACHE


@pytest.fixture(autouse=True)
def clear_taxonomy_cache():
    """Each test starts with a fresh taxonomy cache."""
    _CACHE.clear()
    yield
    _CACHE.clear()


_FAKE_TREE = {
    "results": [
        {
            "id": 1,
            "name": "Home & Living",
            "level": 0,
            "children": [
                {
                    "id": 11,
                    "name": "Bedding",
                    "level": 1,
                    "children": [
                        {"id": 111, "name": "Cushions", "level": 2, "children": []},
                        {"id": 112, "name": "Pillows", "level": 2, "children": []},
                    ],
                },
                {
                    "id": 12,
                    "name": "Outdoor & Gardening",
                    "level": 1,
                    "children": [],
                },
            ],
        },
        {
            "id": 2,
            "name": "Jewelry",
            "level": 0,
            "children": [],
        },
    ],
}


@respx.mock
async def test_taxonomy_search_matches_node_name(make_tools):
    tools = make_tools(register_taxonomy_tools)
    respx.get(f"{ETSY_API_BASE}/application/seller-taxonomy/nodes").mock(
        return_value=httpx.Response(200, json=_FAKE_TREE)
    )

    result = await tools["etsy_taxonomy_search"](query="cushion")

    # "Cushions" should be the top match
    assert result[0]["taxonomy_id"] == 111
    assert result[0]["name"] == "Cushions"
    assert result[0]["full_path"] == "Home & Living > Bedding > Cushions"
    assert result[0]["level"] == 2


@respx.mock
async def test_taxonomy_search_matches_full_path(make_tools):
    tools = make_tools(register_taxonomy_tools)
    respx.get(f"{ETSY_API_BASE}/application/seller-taxonomy/nodes").mock(
        return_value=httpx.Response(200, json=_FAKE_TREE)
    )

    result = await tools["etsy_taxonomy_search"](query="bedding")

    # Bedding itself + its 2 descendants all match (descendants via path containing "Bedding")
    ids = sorted(r["taxonomy_id"] for r in result)
    assert ids == [11, 111, 112]


@respx.mock
async def test_taxonomy_search_caches_tree(make_tools):
    """Two calls should result in only ONE network fetch — tree is cached."""
    tools = make_tools(register_taxonomy_tools)
    route = respx.get(f"{ETSY_API_BASE}/application/seller-taxonomy/nodes").mock(
        return_value=httpx.Response(200, json=_FAKE_TREE)
    )

    await tools["etsy_taxonomy_search"](query="cushion")
    await tools["etsy_taxonomy_search"](query="jewelry")

    assert route.call_count == 1


@respx.mock
async def test_taxonomy_search_no_matches_returns_empty_list(make_tools):
    tools = make_tools(register_taxonomy_tools)
    respx.get(f"{ETSY_API_BASE}/application/seller-taxonomy/nodes").mock(
        return_value=httpx.Response(200, json=_FAKE_TREE)
    )

    result = await tools["etsy_taxonomy_search"](query="nonexistent-thing-xyz")

    assert result == []
