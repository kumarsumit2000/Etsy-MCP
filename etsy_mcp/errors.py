"""Error codes and exceptions for Etsy MCP.

Every tool returns either the success payload (dict/list) or the result of
structured_error(). Internal code raises EtsyMCPError subclasses; the HTTP
wrapper or tool entrypoint converts them to structured-error dicts.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    AUTH_EXPIRED = "auth_expired"
    AUTH_INVALID = "auth_invalid"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    VALIDATION_FAILED = "validation_failed"
    NETWORK = "network"
    SESSION_EXPIRED = "session_expired"
    SELECTOR_MISSING = "selector_missing"
    UNKNOWN = "unknown"


def structured_error(
    message: str,
    code: ErrorCode,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canonical error dict returned by MCP tools."""
    out: dict[str, Any] = {"error": message, "code": code.value}
    if details is not None:
        out["details"] = details
    return out


class EtsyMCPError(Exception):
    """Base exception for all Etsy MCP errors."""

    code: ErrorCode = ErrorCode.UNKNOWN

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        return structured_error(self.message, self.code, self.details)


class AuthInvalid(EtsyMCPError):
    code = ErrorCode.AUTH_INVALID


class RefreshTokenExpired(EtsyMCPError):
    code = ErrorCode.AUTH_EXPIRED


class RateLimited(EtsyMCPError):
    code = ErrorCode.RATE_LIMITED

    def __init__(
        self,
        message: str,
        retry_after: int | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message, details)
        self.retry_after = retry_after


class NotFound(EtsyMCPError):
    code = ErrorCode.NOT_FOUND


class ValidationFailed(EtsyMCPError):
    code = ErrorCode.VALIDATION_FAILED


class NetworkError(EtsyMCPError):
    code = ErrorCode.NETWORK


def missing_shop_id_error() -> dict[str, Any]:
    """Return the canonical structured error for tools that need ETSY_SHOP_ID
    but find it unset. Used by every Phase 1a module that calls a shop-scoped
    Etsy endpoint.
    """
    return structured_error(
        "ETSY_SHOP_ID is not set. Run scripts/bootstrap_oauth.py and paste "
        "the printed shop_id into your .env.",
        ErrorCode.AUTH_INVALID,
    )
