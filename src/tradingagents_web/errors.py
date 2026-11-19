"""Safe error payloads for the WebUI.

Errors never include stack traces, absolute paths, or credential values.
"""

from __future__ import annotations

import logging
import traceback
import uuid
from typing import Any

from fastapi.responses import JSONResponse
from yfinance.exceptions import YFRateLimitError

from tradingagents.dataflows.errors import (
    NoMarketDataError,
    VendorNotConfiguredError,
    VendorRateLimitError,
)
from tradingagents_web.security import redact_text


def run_failure(exc: Exception, phase: str) -> dict:
    """Log redacted diagnostics; expose safe failure categories (INV-WEB-003)."""
    correlation_id = f"c_{uuid.uuid4().hex[:12]}"
    category, message = (
        "internal",
        "Analysis failed during execution. Check the server log using the reference ID.",
    )
    fields: dict[str, Any] = {}
    status = getattr(exc, "status_code", None)
    if isinstance(exc, YFRateLimitError):
        category, message = (
            "market_data_rate_limit",
            "Yahoo Finance rate-limited the market-data request after retries. "
            "This is a market-data failure, not an LLM authentication error. "
            "Wait before retrying, or explicitly configure another supported data vendor.",
        )
        fields = {"source": "yfinance", "retryable": True}
    elif isinstance(exc, VendorRateLimitError):
        category, message = (
            "market_data_unavailable",
            "The configured market-data vendors are rate-limited or temporarily unavailable. "
            "Wait before retrying, or check the server's market-data configuration.",
        )
        fields = {"source": "market_data", "retryable": True}
    elif isinstance(exc, NoMarketDataError):
        category, message = (
            "market_data_unavailable",
            "No usable market data was returned. Check the symbol, analysis date and data coverage.",
        )
        fields = {"source": "market_data", "retryable": False}
    elif isinstance(exc, VendorNotConfiguredError):
        category, message = (
            "market_data_config",
            "A configured market-data vendor is missing server credentials or configuration.",
        )
        fields = {"source": "market_data", "retryable": False}
    elif isinstance(exc, ValueError):
        category, message = (
            "config",
            "Check the provider, model IDs, endpoint and server credentials.",
        )
    elif status in {401, 403}:
        category, message = (
            "authentication",
            "The provider rejected authentication. Check server credentials.",
        )
    elif status == 429:
        category, message = "rate_limit", "The provider rate or quota limit was reached."
    elif status == 404:
        category, message = "config", "The provider endpoint or model was not found."
    elif isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower():
        category, message = "timeout", "The provider request timed out."
    elif isinstance(exc, OSError) and phase == "artifacts":
        category, message = (
            "storage",
            "Cannot write analysis artifacts. Check server storage and permissions.",
        )
    logging.getLogger(__name__).error(
        "Analysis %s failed during %s:\n%s",
        correlation_id,
        phase,
        redact_text(traceback.format_exc()),
    )
    return {
        "category": category,
        "message": message,
        "phase": phase,
        "correlation_id": correlation_id,
        **fields,
    }


def error_payload(category: str, message: str, **fields) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "error": {
            "category": category,
            "message": message,
            "correlation_id": f"c_{uuid.uuid4().hex[:12]}",
        }
    }
    if fields:
        payload["error"]["fields"] = fields
    return payload


def error_response(status_code: int, category: str, message: str, **fields) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_payload(category, message, **fields),
    )
