"""Portfolio JSON validation without persisting uploads or paths."""

from __future__ import annotations

import json

from fastapi import APIRouter

from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.portfolio import PortfolioContext
from tradingagents_web.errors import error_response
from tradingagents_web.models.requests import PortfolioValidationRequest

router = APIRouter(prefix="/api", tags=["portfolio"])


def parse_portfolio(text: str) -> PortfolioContext:
    data = json.loads(text)
    if not isinstance(data, dict) or not data:
        raise ValueError("portfolio must be a non-empty JSON object")
    context = PortfolioContext.model_validate(data)
    for position in context.positions:
        safe_ticker_component(position.ticker)
    return context


@router.post("/portfolio/validate")
def validate_portfolio(request: PortfolioValidationRequest):
    try:
        context = parse_portfolio(request.json_text)
    except (ValueError, json.JSONDecodeError) as exc:
        return error_response(422, "validation", f"invalid portfolio: {exc}")
    return {
        "valid": True,
        "fingerprint": context.fingerprint(),
        "summary": {
            "cash": context.cash,
            "currency": context.currency,
            "position_count": len(context.positions),
            "has_cash": context.cash is not None,
        },
    }
