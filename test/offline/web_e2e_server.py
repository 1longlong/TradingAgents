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
from tradingagents_web.app import create_app
from tradingagents_web.settings import WebSettings


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
