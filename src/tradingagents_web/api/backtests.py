"""Backtest launch, status, and read-only history endpoints."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.backtest import iter_grid, summarize
from tradingagents.dataflows.symbol_utils import normalize_symbol
from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.graph.analyst_execution import ANALYST_NODE_SPECS
from tradingagents_web.api.portfolio import parse_portfolio
from tradingagents_web.errors import error_response
from tradingagents_web.models.backtest_requests import BacktestRequest
from tradingagents_web.runtime.backtest_runner import serialize_summary
from tradingagents_web.runtime.coordinator import RunConflict

router = APIRouter(prefix="/api", tags=["backtests"])

_KNOWN_ANALYSTS = set(ANALYST_NODE_SPECS)


def _settings(request: Request):
    return request.app.state.settings


def _coordinator(request: Request):
    return request.app.state.coordinator


def _build_config(request: Request) -> dict:
    from tradingagents.default_config import DEFAULT_CONFIG

    config = DEFAULT_CONFIG.copy()
    config.update(
        {
            "results_dir": str(_settings(request).results_dir),
            "memory_log_path": str(_settings(request).memory_log_path),
            "data_cache_dir": str(_settings(request).data_cache_dir),
        }
    )
    return config


def _validated_payload(request: Request, body: BacktestRequest) -> dict:
    try:
        dates = iter_grid(body.start, body.end, body.every)
    except ValueError as exc:
        raise ValueError(str(exc)) from None
    if not dates:
        raise ValueError("the backtest grid has no dates")

    tickers: list[str] = []
    for raw in body.tickers:
        ticker = normalize_symbol(raw)
        safe_ticker_component(ticker)
        if ticker not in tickers:
            tickers.append(ticker)
    if not tickers:
        raise ValueError("at least one ticker is required")

    analysts = list(body.analysts)
    if not analysts or any(name not in _KNOWN_ANALYSTS for name in analysts):
        raise ValueError("at least one known analyst is required")
    if body.asset_type == "crypto":
        analysts = [name for name in analysts if name != "fundamentals"]
        if not analysts:
            raise ValueError(
                "crypto backtest requires at least one non-fundamentals analyst"
            )

    portfolio = None
    fingerprint = None
    if body.portfolio_json:
        portfolio = parse_portfolio(body.portfolio_json)
        fingerprint = portfolio.fingerprint()

    backtest_run_id = None
    if body.run_id:
        backtest_run_id = safe_ticker_component(body.run_id)

    return {
        "run_id": f"bt_{uuid.uuid4().hex[:12]}",
        "backtest_run_id": backtest_run_id,
        "tickers": tickers,
        "dates": dates,
        "start": body.start,
        "end": body.end,
        "every": body.every,
        "asset_type": body.asset_type,
        "selected_analysts": analysts,
        "portfolio": portfolio,
        "portfolio_fingerprint": fingerprint,
        "config": _build_config(request),
    }


def _run_dir(request: Request, run_id: str) -> Path:
    safe = safe_ticker_component(run_id)
    return Path(_settings(request).results_dir) / "backtest" / safe


def _summary_for_dir(request: Request, run_dir: Path) -> dict | None:
    log_path = run_dir / "trading_memory.md"
    if not log_path.is_file():
        return None
    summary = summarize(TradingMemoryLog({"memory_log_path": str(log_path)}))
    return serialize_summary(
        summary,
        log_path=log_path,
        results_dir=Path(_settings(request).results_dir),
    )


def _disk_snapshot(request: Request, run_dir: Path) -> dict | None:
    summary = _summary_for_dir(request, run_dir)
    if summary is None:
        return None
    entries = TradingMemoryLog(
        {"memory_log_path": str(run_dir / "trading_memory.md")}
    ).load_entries()
    tickers = sorted({entry["ticker"] for entry in entries})
    dates = sorted({entry["date"] for entry in entries})
    return {
        "run_id": run_dir.name,
        "kind": "backtest",
        "status": "completed",
        "ticker": ",".join(tickers) or run_dir.name,
        "tickers": tickers,
        "dates": dates,
        "asset_type": "stock",
        "analysts": [],
        "expected_cells": len(tickers) * len(dates),
        "cells_run": len(entries),
        "skipped": 0,
        "started_at": None,
        "finished_at": None,
        "summary": summary,
        "error": None,
    }


@router.post("/backtests")
def start_backtest(request: Request, body: BacktestRequest):
    try:
        payload = _validated_payload(request, body)
    except (ValueError, json.JSONDecodeError) as exc:
        return error_response(422, "validation", str(exc))
    try:
        record = _coordinator(request).start_backtest(payload)
    except RunConflict as exc:
        return error_response(
            409,
            "conflict",
            "a run is already active",
            active_run_id=exc.active_run_id,
        )
    return JSONResponse(status_code=202, content=record.to_snapshot())


@router.get("/backtests")
def list_backtests(request: Request):
    root = Path(_settings(request).results_dir) / "backtest"
    items: list[dict] = []
    seen: set[str] = set()
    if root.is_dir():
        for run_dir in sorted(root.iterdir(), key=lambda path: path.stat().st_mtime, reverse=True):
            if not run_dir.is_dir():
                continue
            snapshot = _disk_snapshot(request, run_dir)
            if snapshot is not None:
                items.append(snapshot)
                seen.add(snapshot["run_id"])
    for snapshot in _coordinator(request).backtest_snapshots():
        if snapshot["status"] in {"starting", "running"} and snapshot["run_id"] not in seen:
            items.append(snapshot)
    return {"items": items}


@router.get("/backtests/{run_id}")
def get_backtest(request: Request, run_id: str):
    record = _coordinator(request).get_backtest(run_id)
    if record is not None:
        return record.to_snapshot()
    try:
        run_dir = _run_dir(request, run_id)
    except ValueError:
        return error_response(404, "not_found", "backtest not found")
    snapshot = _disk_snapshot(request, run_dir)
    if snapshot is None:
        return error_response(404, "not_found", "backtest not found")
    return snapshot
