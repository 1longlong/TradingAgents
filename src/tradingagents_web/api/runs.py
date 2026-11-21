"""Analysis requests: REQ-WEB-005/013, ADR-001, INV-WEB-001/009."""

from __future__ import annotations

import json
import os

from fastapi import APIRouter, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.routing import APIRoute

from cli.utils import _llm_provider_table
from tradingagents.dataflows.symbol_utils import normalize_symbol
from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.graph.analyst_execution import ANALYST_NODE_SPECS
from tradingagents.graph.trading_graph import _validate_trade_date
from tradingagents.llm_clients.api_key_env import PROVIDER_API_KEY_ENV
from tradingagents_web.api.config import MODEL_DEFAULT_KEYS, effective_defaults
from tradingagents_web.api.portfolio import parse_portfolio
from tradingagents_web.errors import error_response
from tradingagents_web.models.requests import RunRequest
from tradingagents_web.runtime.coordinator import RunConflict
from tradingagents_web.runtime.debate_policy import configure_debate_policy, public_debate_policy


class AnalysisRoute(APIRoute):
    """INV-WEB-003/013: reject bad typed inputs without echoing their values."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def validated(request: Request):
            try:
                return await handler(request)
            except RequestValidationError:
                return error_response(
                    422, "validation", "Invalid analysis request fields or types."
                )

        return validated


router = APIRouter(prefix="/api", tags=["runs"], route_class=AnalysisRoute)

_KNOWN_ANALYSTS = set(ANALYST_NODE_SPECS)
_KNOWN_PROVIDERS = {key for _, key, _ in _llm_provider_table()} | set(PROVIDER_API_KEY_ENV)


def _settings(request: Request):
    return request.app.state.settings


def _coordinator(request: Request):
    return request.app.state.coordinator


def _build_config(request, req: RunRequest) -> dict:
    """Resolve editable model defaults and enforced limits (REQ-WEB-013, ADR-001-choice.md)."""
    config = effective_defaults()
    default_provider = str(config["llm_provider"]).lower()
    config.update(
        {
            "results_dir": str(request.app.state.settings.results_dir),
            "memory_log_path": str(request.app.state.settings.memory_log_path),
            "data_cache_dir": str(request.app.state.settings.data_cache_dir),
        }
    )
    supplied = req.model_dump(exclude_unset=True, exclude_none=True)
    for key in (
        "llm_provider",
        "backend_url",
        "quick_think_llm",
        "deep_think_llm",
        "google_thinking_level",
        "openai_reasoning_effort",
        "anthropic_effort",
        "output_language",
    ):
        if key in supplied:
            config[key] = supplied[key]
    if "checkpoint" in supplied:
        config["checkpoint_enabled"] = req.checkpoint
    selection = {key: config[key] for key in MODEL_DEFAULT_KEYS}
    switched = str(selection["llm_provider"]).lower() != default_provider
    if switched and any(not supplied.get(key) for key in MODEL_DEFAULT_KEYS[1:]):
        raise ValueError("Select both quick and deep models when changing the provider.")
    # Policy resolution enforces the remaining environment settings.
    config = configure_debate_policy(
        config,
        overrides=req.debate_termination.model_dump(exclude_unset=True)
        if req.debate_termination is not None
        else None,
        legacy_depth=req.research_depth if "research_depth" in supplied else None,
        risk_rounds=req.max_risk_discuss_rounds,
    )
    config.update(selection)
    config["llm_provider"] = config["llm_provider"].lower()
    if switched:
        # INV-WEB-003: never pair a new provider's key with an inherited endpoint.
        for key in (
            "backend_url",
            "google_thinking_level",
            "openai_reasoning_effort",
            "anthropic_effort",
        ):
            config[key] = supplied.get(key)
    return config


def _validated_payload(request: Request, req: RunRequest) -> dict:
    config = _build_config(request, req)
    ticker = normalize_symbol(req.ticker)
    safe_ticker_component(ticker)
    trade_date = _validate_trade_date(req.trade_date)

    analysts = list(req.analysts)
    if not analysts or any(name not in _KNOWN_ANALYSTS for name in analysts):
        raise ValueError("at least one known analyst is required")
    if req.asset_type == "crypto":
        analysts = [name for name in analysts if name != "fundamentals"]
        if not analysts:
            raise ValueError("crypto analysis requires at least one non-fundamentals analyst")

    if (
        req.debate_termination is None
        and req.research_depth not in {1, 3, 5}
        and not os.environ.get("TRADINGAGENTS_MAX_DEBATE_ROUNDS")
    ):
        raise ValueError("research_depth must be 1, 3, or 5")
    if config["llm_provider"] not in _KNOWN_PROVIDERS:
        raise ValueError("unknown LLM provider")
    for model_id in (config.get("quick_think_llm"), config.get("deep_think_llm")):
        if model_id is not None and not model_id.strip():
            raise ValueError("model IDs must not be blank")

    portfolio = None
    fingerprint = None
    if req.portfolio_json:
        portfolio = parse_portfolio(req.portfolio_json)
        fingerprint = portfolio.fingerprint()

    return {
        "ticker": ticker,
        "trade_date": trade_date,
        "asset_type": req.asset_type,
        "analysts": analysts,
        "research_depth": config["max_debate_rounds"],
        "debate_termination": public_debate_policy(config),
        "max_risk_discuss_rounds": config["max_risk_discuss_rounds"],
        "llm_provider": config["llm_provider"],
        "quick_think_llm": config["quick_think_llm"],
        "deep_think_llm": config["deep_think_llm"],
        "checkpoint_enabled": config["checkpoint_enabled"],
        "output_language": config["output_language"],
        "portfolio": portfolio,
        "portfolio_fingerprint": fingerprint,
        "config": config,
    }


@router.post("/runs")
def start_run(request: Request, body: RunRequest):
    try:
        payload = _validated_payload(request, body)
    except (ValueError, json.JSONDecodeError) as exc:
        return error_response(422, "validation", str(exc))
    try:
        record = _coordinator(request).start(payload, body.client_request_id)
    except RunConflict as exc:
        return error_response(
            409,
            "conflict",
            "a run is already active",
            active_run_id=exc.active_run_id,
        )
    return JSONResponse(status_code=201, content=record.to_snapshot())


@router.get("/runs/active")
def active_run(request: Request):
    active = _coordinator(request).active_snapshot()
    return active if active is not None else {"run_id": None}


@router.get("/runs/{run_id}")
def get_run(request: Request, run_id: str):
    record = _coordinator(request).get(run_id)
    if record is None:
        return error_response(404, "not_found", "run not found")
    return record.to_snapshot()


@router.post("/runs/{run_id}/cancel")
def cancel_run(request: Request, run_id: str):
    record = _coordinator(request).cancel(run_id)
    if record is None:
        return error_response(404, "not_found", "run not found")
    return record.to_snapshot()


@router.get("/runs/{run_id}/events")
async def run_events(
    request: Request,
    run_id: str,
    after_seq: int = Query(0, ge=0),
):
    coordinator = _coordinator(request)
    if coordinator.get(run_id) is None:
        return error_response(404, "not_found", "run not found")

    async def generate():
        async for event in coordinator.stream(run_id, after_seq):
            yield (
                f"id: {event['seq']}\n"
                f"event: {event['type']}\n"
                f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            )

    return StreamingResponse(generate(), media_type="text/event-stream")
