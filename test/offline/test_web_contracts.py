"""CLI / Python API compatibility and WebUI contract boundaries.

Covers REQ-WEB-026 and the compatibility portion of the iteration-1 plan. These
tests must fail as ``EXPECTED-UNIMPLEMENTED`` only when the approved WebUI
package is absent; core API changes are real contract failures.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from test.offline.web_fixture_app import (
    build_fixture_tree,
    make_app,
    make_client,
    require_core,
    require_web,
)

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


def test_core_public_signatures_are_unchanged():
    from tradingagents.backtest import run_backtest
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.portfolio import PortfolioContext
    from tradingagents.reporting import write_report_tree

    assert list(inspect.signature(TradingAgentsGraph.propagate).parameters) == [
        "self",
        "company_name",
        "trade_date",
        "asset_type",
        "portfolio",
    ]
    assert list(inspect.signature(run_backtest).parameters) == [
        "tickers",
        "dates",
        "config",
        "asset_type",
        "portfolio",
        "selected_analysts",
        "run_id",
    ]
    assert list(inspect.signature(write_report_tree).parameters) == [
        "final_state",
        "ticker",
        "save_path",
    ]
    assert set(PortfolioContext.model_fields) == {"cash", "currency", "positions"}


def test_core_and_cli_do_not_import_the_web_layer():
    for base in (ROOT / "src" / "tradingagents", ROOT / "src" / "cli"):
        for path in base.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert "tradingagents_web" not in text, path


def test_cli_help_contract_remains_available():
    from typer.testing import CliRunner

    from cli.main import app

    runner = CliRunner()
    assert runner.invoke(app, ["--help"]).exit_code == 0
    assert runner.invoke(app, ["backtest", "--help"]).exit_code == 0


def test_python_api_import_smoke():
    import cli.main  # noqa: F401
    import tradingagents  # noqa: F401
    import tradingagents.backtest  # noqa: F401
    import tradingagents.portfolio  # noqa: F401
    import tradingagents.reporting  # noqa: F401


def test_write_report_tree_layout_is_still_cli_compatible(tmp_path):
    core = require_core()
    state = {
        "market_report": "MKT",
        "news_report": "NEWS",
        "investment_debate_state": {"judge_decision": "RM PLAN"},
        "trader_investment_plan": "TRADE",
        "risk_debate_state": {"judge_decision": "**Rating**: Hold\nPM"},
    }
    out = core.write_report_tree(state, "AAPL", tmp_path)
    assert out.name == "complete_report.md"
    assert (tmp_path / "1_analysts" / "market.md").read_text() == "MKT"
    assert (tmp_path / "2_research" / "manager.md").read_text() == "RM PLAN"
    assert (tmp_path / "3_trading" / "trader.md").read_text() == "TRADE"
    assert (tmp_path / "5_portfolio" / "decision.md").read_text().startswith(
        "**Rating**: Hold"
    )


def test_web_openapi_has_history_and_no_execution_routes(tmp_path):
    tree = build_fixture_tree(tmp_path)
    web = require_web()
    client = make_client(make_app(web, tree))
    response = client.get("/openapi.json")
    assert response.status_code == 200, response.text
    paths = response.json()["paths"]
    assert "/api/history" in paths
    assert "/api/history/{artifact_id}" in paths
    for path in paths:
        lowered = path.lower()
        assert "order" not in lowered
        assert "trade" not in lowered
        assert "execute" not in lowered


def test_history_creates_no_new_database_files(tmp_path):
    tree = build_fixture_tree(tmp_path)
    web = require_web()
    client = make_client(make_app(web, tree))
    response = client.get("/api/history")
    assert response.status_code == 200, response.text
    assert not list(tree.root.rglob("*.db"))
    assert not list(tree.root.rglob("*.sqlite"))


def test_history_does_not_require_a_full_states_log(tmp_path):
    tree = build_fixture_tree(tmp_path)
    # The fixture's state log is intentionally malformed; a CLI-style run must
    # still be readable from message_tool.log and reports/*.md.
    malformed = (
        tree.results_dir
        / "NVDA"
        / "TradingAgentsStrategy_logs"
        / "full_states_log_2026-11-01.json"
    )
    assert malformed.exists()
    web = require_web()
    client = make_client(make_app(web, tree))
    items = client.get("/api/history", params={"limit": 50}).json()["items"]
    item = next(item for item in items if item["source"] == "run" and item["ticker"] == "NVDA")
    response = client.get(f"/api/history/{item['artifact_id']}")
    assert response.status_code == 200, response.text
    assert "MKT content" in response.text
