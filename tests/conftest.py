"""Shared pytest fixtures for Etsy MCP tests."""

import pytest


@pytest.fixture
def tmp_tokens_path(tmp_path):
    """Provide a temp path for .tokens.json that's isolated per test."""
    return tmp_path / "tokens.json"
