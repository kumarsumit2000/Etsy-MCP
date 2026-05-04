"""Tests for etsy_mcp.errors."""

from etsy_mcp.errors import (
    ErrorCode,
    structured_error,
    EtsyMCPError,
    RefreshTokenExpired,
    RateLimited,
)


def test_structured_error_basic():
    result = structured_error("Something broke", ErrorCode.UNKNOWN)
    assert result == {
        "error": "Something broke",
        "code": "unknown",
    }


def test_structured_error_with_details():
    result = structured_error(
        "Field invalid",
        ErrorCode.VALIDATION_FAILED,
        details={"field": "price", "reason": "must be > 0"},
    )
    assert result == {
        "error": "Field invalid",
        "code": "validation_failed",
        "details": {"field": "price", "reason": "must be > 0"},
    }


def test_error_code_values():
    # Codes used across the project — verify they exist with expected string values.
    assert ErrorCode.AUTH_EXPIRED.value == "auth_expired"
    assert ErrorCode.AUTH_INVALID.value == "auth_invalid"
    assert ErrorCode.NOT_FOUND.value == "not_found"
    assert ErrorCode.RATE_LIMITED.value == "rate_limited"
    assert ErrorCode.VALIDATION_FAILED.value == "validation_failed"
    assert ErrorCode.NETWORK.value == "network"
    assert ErrorCode.SESSION_EXPIRED.value == "session_expired"
    assert ErrorCode.SELECTOR_MISSING.value == "selector_missing"
    assert ErrorCode.UNKNOWN.value == "unknown"


def test_refresh_token_expired_is_etsy_mcp_error():
    err = RefreshTokenExpired("expired")
    assert isinstance(err, EtsyMCPError)
    assert err.code == ErrorCode.AUTH_EXPIRED


def test_rate_limited_carries_retry_after():
    err = RateLimited("429", retry_after=5)
    assert err.retry_after == 5
    assert err.code == ErrorCode.RATE_LIMITED
