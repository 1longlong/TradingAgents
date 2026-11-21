"""Fake-backend server for Playwright E2E tests.

It serves the built SPA and the real WebUI API, but replaces the graph runner
with a deterministic fake. No model/data provider is called.
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import uvicorn

from test.offline.web_fixture_app import SECRET, build_fixture_tree
from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.backtest import BacktestResult, _notify_backtest_progress
from tradingagents.report_artifacts import write_report_artifacts
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
    _notify_backtest_progress("initializing")
    log = TradingMemoryLog({"memory_log_path": str(config["memory_log_path"])})
    for ticker in tickers:
        for date in dates:
            _notify_backtest_progress("cell.started", ticker, date)
            time.sleep(2.5 if ticker == "PROGRESS" else 0.05)
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
            _notify_backtest_progress("cell.completed", ticker, date)
    for ticker in tickers:
        _notify_backtest_progress("settlement.started", ticker)
        if ticker == "PROGRESS":
            time.sleep(3)
        _notify_backtest_progress("settlement.completed", ticker)
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
        # REQ-WEB-002/007/021: exercise recorded stage transitions and tool data.
        events[1]["payload"]["stage"] = "analysts"
        events[2:2] = [
            {
                "type": "tool_call",
                "payload": {
                    "name": "get_stock_data",
                    "arguments": {"symbol": ticker},
                    "stage": "analysts",
                },
            },
            {
                "type": "message",
                "payload": {"type": "Data", "content": "E2E price data", "stage": "analysts"},
            },
        ]
        final_index = next(
            i
            for i, event in enumerate(events)
            if event["type"] == "report.section"
            and event["payload"]["section"] == "final_trade_decision"
        )
        events[final_index:final_index] = [
            {"type": "agent.status", "payload": {"agent": "Market Analyst", "status": "completed"}},
            {
                "type": "agent.status",
                "payload": {"agent": "Research Team", "status": "in_progress"},
            },
            {
                "type": "message",
                "payload": {
                    "type": "Agent",
                    "speaker": "Bull researcher",
                    "content": "E2E research argument",
                    "stage": "research",
                },
            },
            {
                "type": "report.section",
                "payload": {"section": "investment_plan", "content": "E2E research conclusion"},
            },
            {"type": "agent.status", "payload": {"agent": "Research Team", "status": "completed"}},
            {"type": "agent.status", "payload": {"agent": "Trader", "status": "in_progress"}},
            {
                "type": "message",
                "payload": {"type": "Agent", "content": "E2E trader working", "stage": "trading"},
            },
            {
                "type": "report.section",
                "payload": {"section": "trader_investment_plan", "content": "E2E trading proposal"},
            },
            {"type": "agent.status", "payload": {"agent": "Trader", "status": "completed"}},
            {"type": "agent.status", "payload": {"agent": "Risk Team", "status": "in_progress"}},
            {
                "type": "message",
                "payload": {"type": "Agent", "content": "E2E risk argument", "stage": "risk"},
            },
        ]
        for event in events:
            if cancel_event.is_set():
                return
            emit(event)
            if event["type"] == "agent.status" and event["payload"] == {
                "agent": "Market Analyst",
                "status": "completed",
            }:
                emit(
                    {"type": "analyst.timing", "payload": {"wall_times": {"Market Analyst": 1.25}}}
                )
            if (
                ticker.upper() == "MSFT"
                and event["type"] == "message"
                and event["payload"].get("type") == "Data"
            ):
                emit(
                    {
                        "type": "run.failed",
                        "payload": {
                            "message": "E2E market request failed",
                            "category": "market_data",
                            "correlation_id": "c_e2e",
                        },
                    }
                )
                return
            # Keep each short fixture stage observable by browser assertions.
            time.sleep(
                1.0
                if event["type"] == "message"
                and event["payload"].get("stage") in {"research", "trading"}
                else 0.35
            )

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
                    "wall_times": {"Market Analyst": 1.25},
                },
            }
        )


def create_e2e_app():
    root = Path(tempfile.mkdtemp(prefix="tradingagents-e2e-"))
    tree = build_fixture_tree(root)
    # Structured audit fixture through the real core serializer, never provider calls.
    write_report_artifacts(
        {
            "trade_date": "2026-11-01",
            "data_quality_verdict": "degraded",
            "data_quality_gate_decision": {
                "decision": "degraded",
                "policy_version": "1.0",
                "human_readable_reason": "Optional coverage is insufficient.",
            },
            "data_quality_evidence_records": [
                {
                    "evidence_id": "e2e-price",
                    "category": "market",
                    "metric_name": "close",
                    "observed_at": "2026-11-01",
                    "quality_status": "Medium",
                    "source_name": "yfinance",
                    "value_raw": "100",
                    "unit_normalized": "USD",
                },
                {
                    "evidence_id": "e2e-future",
                    "category": "news",
                    "metric_name": "headline",
                    "observed_at": "2026-11-02",
                    "quality_status": "Low",
                    "source_name": "fixture",
                },
            ],
        },
        "AAPL",
        tree.saved_dir,
    )
    # The fixture embeds a dummy credential; make it visible to the server's
    # redaction layer exactly as a real provider key would be.
    os.environ["OPENAI_API_KEY"] = SECRET

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
