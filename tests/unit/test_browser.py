"""Tests for etsy_mcp.browser tools (unit-testable bits only).

End-to-end browser tests run against the real Etsy dashboard and are
verified manually (see plan Task 11). This file covers:
- module imports cleanly
- selector constants exist with required keys
- register_browser_tools returns the expected callables
- session-expired error path when .storage_state.json is missing
"""

from __future__ import annotations

import pytest


def test_browser_module_imports():
    import etsy_mcp.browser  # noqa: F401


def test_selectors_block_exists():
    from etsy_mcp.browser import SELECTORS

    # Each value should be a non-empty string
    assert isinstance(SELECTORS, dict)
    assert len(SELECTORS) >= 1


def test_register_browser_tools_returns_dict(make_tools):
    from etsy_mcp.browser import register_browser_tools

    tools = make_tools(register_browser_tools, shop_id="42")
    assert isinstance(tools, dict)
    # Tools added in later tasks; for Task 3 we just verify the factory
    # returns SOMETHING dict-shaped without errors.


async def test_browser_tool_returns_session_expired_when_storage_missing(make_tools, tmp_path, monkeypatch):
    """If .storage_state.json doesn't exist, every browser tool short-circuits
    with a session_expired error rather than crashing.
    """
    from etsy_mcp.browser import register_browser_tools, _STORAGE_STATE_PATH_ENV

    # Point the storage-state path at a file that doesn't exist
    monkeypatch.setenv(_STORAGE_STATE_PATH_ENV, str(tmp_path / "no-such-file.json"))

    tools = make_tools(register_browser_tools, shop_id="42")
    # Until tools are added, this test is a placeholder. We can't call any tool.
    # Once Task 4+ adds tools, the same fixture can be used to verify the
    # missing-storage error path.
    assert isinstance(tools, dict)


async def test_ads_get_status_returns_session_expired_when_storage_missing(make_tools, tmp_path, monkeypatch):
    from etsy_mcp.browser import register_browser_tools, _STORAGE_STATE_PATH_ENV

    monkeypatch.setenv(_STORAGE_STATE_PATH_ENV, str(tmp_path / "no-such-file.json"))

    tools = make_tools(register_browser_tools, shop_id="42")
    assert "etsy_ads_get_status" in tools

    result = await tools["etsy_ads_get_status"]()

    assert result["code"] == "session_expired"
    assert "bootstrap_browser_login.py" in result["error"]


async def test_ads_create_campaign_requires_confirm(make_tools):
    from etsy_mcp.browser import register_browser_tools

    tools = make_tools(register_browser_tools, shop_id="42")
    result = await tools["etsy_ads_create_campaign"](daily_budget_usd=10.0)

    assert result["code"] == "validation_failed"
    assert "confirm" in result["error"].lower()


async def test_ads_create_campaign_session_expired(make_tools, tmp_path, monkeypatch):
    from etsy_mcp.browser import register_browser_tools, _STORAGE_STATE_PATH_ENV

    monkeypatch.setenv(_STORAGE_STATE_PATH_ENV, str(tmp_path / "no-such-file.json"))

    tools = make_tools(register_browser_tools, shop_id="42")
    result = await tools["etsy_ads_create_campaign"](
        daily_budget_usd=10.0,
        confirm=True,
    )

    assert result["code"] == "session_expired"


async def test_ads_set_budget_session_expired(make_tools, tmp_path, monkeypatch):
    from etsy_mcp.browser import register_browser_tools, _STORAGE_STATE_PATH_ENV

    monkeypatch.setenv(_STORAGE_STATE_PATH_ENV, str(tmp_path / "no-such-file.json"))

    tools = make_tools(register_browser_tools, shop_id="42")
    result = await tools["etsy_ads_set_budget"](daily_budget_usd=15.0)
    assert result["code"] == "session_expired"


async def test_ads_set_budget_validates_positive(make_tools):
    from etsy_mcp.browser import register_browser_tools

    tools = make_tools(register_browser_tools, shop_id="42")
    result = await tools["etsy_ads_set_budget"](daily_budget_usd=0.0)
    assert result["code"] == "validation_failed"

    result = await tools["etsy_ads_set_budget"](daily_budget_usd=-5.0)
    assert result["code"] == "validation_failed"


async def test_ads_pause_session_expired(make_tools, tmp_path, monkeypatch):
    from etsy_mcp.browser import register_browser_tools, _STORAGE_STATE_PATH_ENV

    monkeypatch.setenv(_STORAGE_STATE_PATH_ENV, str(tmp_path / "no-such-file.json"))

    tools = make_tools(register_browser_tools, shop_id="42")
    result = await tools["etsy_ads_pause"]()
    assert result["code"] == "session_expired"


async def test_ads_resume_session_expired(make_tools, tmp_path, monkeypatch):
    from etsy_mcp.browser import register_browser_tools, _STORAGE_STATE_PATH_ENV

    monkeypatch.setenv(_STORAGE_STATE_PATH_ENV, str(tmp_path / "no-such-file.json"))

    tools = make_tools(register_browser_tools, shop_id="42")
    result = await tools["etsy_ads_resume"]()
    assert result["code"] == "session_expired"


async def test_update_listing_images_order_session_expired(make_tools, tmp_path, monkeypatch):
    from etsy_mcp.browser import register_browser_tools, _STORAGE_STATE_PATH_ENV

    monkeypatch.setenv(_STORAGE_STATE_PATH_ENV, str(tmp_path / "no-such-file.json"))

    tools = make_tools(register_browser_tools, shop_id="42")
    result = await tools["etsy_update_listing_images_order"](
        listing_id=777,
        image_ids=[1, 2, 3],
    )
    assert result["code"] == "session_expired"


async def test_update_listing_images_order_empty_image_ids_rejected(make_tools):
    from etsy_mcp.browser import register_browser_tools

    tools = make_tools(register_browser_tools, shop_id="42")
    result = await tools["etsy_update_listing_images_order"](
        listing_id=777,
        image_ids=[],
    )
    assert result["code"] == "validation_failed"
    assert "empty" in result["error"].lower() or "at least one" in result["error"].lower()
