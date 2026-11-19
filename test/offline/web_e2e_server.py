"""Fake-backend server for Playwright E2E tests.

It serves the built SPA and the real WebUI API, but replaces the graph runner
with a deterministic fake. No model/data provider is called.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import uvicorn

from test.offline.web_fixture_app import build_fixture_tree
from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.backtest import BacktestResult
from tradingagents_web.app import create_app
from tradingagents_web.settings import WebSettings


def fake_run_backtest(
    tickers,
    dates,
    config,
    asset_type="stock",
    portfolio=None,
    selected_analysts=("market", "social", "news", "fundamentals"),
    run_id=None,
):
    log = TradingMemoryLog({"memory_log_path": str(config["memory_log_path"])})
    for ticker in tickers:
        for date in dates:
            log.store_decision(ticker, date, "**Rating**: Buy\n\nE2E backtest cell.\n")
            log.update_with_outcome(
                ticker,
                date,
                raw_return=0.02,
                alpha_return=0.01,
                holding_days=5,
                reflection="E2E backtest reflection.",
                resolution_date=date,
            )
    return BacktestResult(
        run_id=run_id or "bt_e2e",
        log_path=Path(config["memory_log_path"]),
        cells_run=len(tickers) * len(dates),
    )


def fake_fetch_announcements(*args, **kwargs):
    return {
        "announcements": ["E2E announcement"],
        "require_attention": False,
    }


class E2ERunner:
    def run(self, request, emit, cancel_event) -> None:
        ticker = str(request["ticker"])
        emit(
            {
                "type": "run.started",
                "payload": {"ticker": ticker, "trade_date": request["trade_date"]},
            }
        )
        events = [
            {
                "type": "agent.status",
                "payload": {"agent": "Market Analyst", "status": "in_progress"},
            },
            {
                "type": "message",
                "payload": {
                    "timestamp": "12:00:00",
                    "type": "Agent",
                    "content": "E2E working",
                },
            },
            {
                "type": "report.section",
                "payload": {
                    "section": "market_report",
                    "title": "Market",
                    "content": "# Market\n\nE2E market report.",
                },
            },
            {
                "type": "report.section",
                "payload": {
                    "section": "final_trade_decision",
                    "title": "Portfolio",
                    "content": "**Rating**: Buy\n\nE2E decision.",
                },
            },
            {
                "type": "stats",
                "payload": {
                    "agents_completed": 1,
                    "agents_total": 1,
                    "llm_calls": 1,
                    "tool_calls": 1,
                    "tokens_in": 10,
                    "tokens_out": 20,
                    "reports_completed": 1,
                    "reports_total": 1,
                    "elapsed": 0.5,
                },
            },
        ]
        for event in events:
            if cancel_event.is_set():
                return
            emit(event)
            time.sleep(0.6)

        if ticker.upper() == "AAPL":
            while not cancel_event.is_set():
                time.sleep(0.02)
            return

        emit(
            {
                "type": "run.completed",
                "payload": {
                    "signal": "Buy",
                    "review": False,
                    "wall_times": {"Market Analyst": 0.5},
                },
            }
        )


def create_e2e_app():
    root = Path(tempfile.mkdtemp(prefix="tradingagents-e2e-"))
    tree = build_fixture_tree(root)

    import cli.prefs as prefs_module

    prefs_module._PREFS_PATH = root / "cli_prefs.json"

    import tradingagents_web.api.announcements as announcements_module
    import tradingagents_web.runtime.backtest_runner as backtest_module

    backtest_module.run_backtest = fake_run_backtest
    announcements_module.fetch_announcements = fake_fetch_announcements

    settings = WebSettings(
        results_dir=tree.results_dir,
        memory_log_path=tree.memory_log_path,
        data_cache_dir=tree.data_cache_dir,
        host="127.0.0.1",
    )
    return create_app(settings, runner_factory=E2ERunner)


def main() -> None:
    uvicorn.run(create_e2e_app(), host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
