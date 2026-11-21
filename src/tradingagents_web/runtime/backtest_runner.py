"""Backtest execution wrapper with isolated artifacts.

The wrapper calls the existing ``run_backtest`` and ``summarize`` functions. It
never points a backtest at the live decision log: the run gets its own
``results_dir/backtest/<run_id>`` directory and ``trading_memory.md``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path

from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.backtest import (
    BacktestSummary,
    observe_backtest_progress,
    run_backtest,
    summarize,
)
from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents_web.settings import WebSettings


def serialize_summary(
    summary: BacktestSummary,
    *,
    log_path: Path,
    results_dir: Path,
    failures=None,
    settlement_failures=None,
) -> dict:
    by_rating = {
        rating: {
            "count": score.count,
            "hit_rate": score.hit_rate,
            "mean_alpha": score.mean_alpha,
        }
        for rating, score in summary.by_rating.items()
    }
    run_dir = log_path.parent
    try:
        relative = run_dir.resolve().relative_to(Path(results_dir).resolve())
    except ValueError:
        relative = run_dir
    return {
        "resolved": summary.resolved,
        "pending": summary.pending,
        "unscored": summary.unscored,
        "holding": summary.holding,
        "by_rating": by_rating,
        "failures": [list(item) for item in (failures or [])],
        "settlement_failures": [
            list(item) for item in (settlement_failures or [])
        ],
        "log_artifact_id": sha256(f"{relative}".encode()).hexdigest()[:16],
    }


class BacktestRunner:
    """Execute one backtest request and return its serialized summary."""

    def __init__(self, settings: WebSettings):
        self.settings = settings

    def execute(self, request: dict, on_progress: Callable[[dict], None] | None = None) -> dict:
        run_id = safe_ticker_component(str(request["run_id"]))
        run_dir = Path(self.settings.results_dir) / "backtest" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        config = dict(request["config"])
        config["results_dir"] = str(self.settings.results_dir)
        config["memory_log_path"] = str(run_dir / "trading_memory.md")

        def publish(event: dict):
            if on_progress:
                try:
                    on_progress(event)
                except Exception:
                    logging.getLogger(__name__).warning("Backtest progress observer failed")

        with observe_backtest_progress(publish):
            result = run_backtest(
                list(request["tickers"]),
                list(request["dates"]),
                config,
                asset_type=request.get("asset_type", "stock"),
                portfolio=request.get("portfolio"),
                selected_analysts=tuple(request.get("selected_analysts") or ()),
                run_id=request.get("backtest_run_id"),
            )
        publish({"event": "summarizing"})
        log_path = Path(result.log_path)
        summary = summarize(
            TradingMemoryLog({"memory_log_path": str(log_path)})
        )
        return {
            "summary": serialize_summary(
                summary,
                log_path=log_path,
                results_dir=Path(self.settings.results_dir),
                failures=result.failures,
                settlement_failures=result.settlement_failures,
            ),
            "cells_run": result.cells_run,
            "skipped": result.skipped,
        }
