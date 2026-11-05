"""Shared fixtures for the iteration-1 WebUI tests.

This module is **test support**, not product code. It builds artifact trees with
the existing CLI/API writers so the WebUI reader is exercised against the real
formats instead of hand-written approximations.

Failure classification used by the WebUI tests:
- ``EXPECTED-UNIMPLEMENTED``: the approved WebUI package/module does not exist.
- ``TEST-ENV``: the approved dev/web test dependencies are not installed.
- Any other failure is a test defect or a contract mismatch to review.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

SECRET = "sk-test-dummy-secret-1234567890"


@dataclass(frozen=True)
class FixtureTree:
    """Artifact tree shared by the read-only history tests."""

    root: Path
    results_dir: Path
    data_cache_dir: Path
    memory_log_path: Path
    static_dir: Path
    run_dir: Path
    partial_run_dir: Path
    saved_dir: Path
    backtest_dir: Path
    backtest_run_id: str


def _fail_env(exc: ModuleNotFoundError) -> None:
    pytest.fail(
        f"TEST-ENV: missing dependency {exc.name!r}; install the approved "
        "dev/web extras before running WebUI tests",
        pytrace=False,
    )


def require_core():
    """Import the existing core writers used to build compatible fixtures."""
    try:
        from tradingagents.agents.utils.memory import TradingMemoryLog
        from tradingagents.backtest import summarize
        from tradingagents.reporting import write_report_tree
    except ModuleNotFoundError as exc:
        _fail_env(exc)
    return SimpleNamespace(
        TradingMemoryLog=TradingMemoryLog,
        summarize=summarize,
        write_report_tree=write_report_tree,
    )


def require_web():
    """Import the approved WebUI entry points, or fail as unimplemented."""
    try:
        import fastapi  # noqa: F401
        import httpx  # noqa: F401
    except ModuleNotFoundError as exc:
        _fail_env(exc)
    try:
        import tradingagents_web.app as app_module
        import tradingagents_web.settings as settings_module
    except ModuleNotFoundError as exc:
        pytest.fail(
            f"EXPECTED-UNIMPLEMENTED: {exc.name!r}; the approved WebUI package "
            "is not implemented yet",
            pytrace=False,
        )
    return SimpleNamespace(
        create_app=app_module.create_app,
        WebSettings=settings_module.WebSettings,
    )


def require_frontend_file(relative: str) -> Path:
    """Resolve a frontend contract file, or fail as unimplemented."""
    root = Path(__file__).resolve().parents[2] / "src" / "tradingagents_web" / "frontend"
    path = root / relative
    if not path.is_file():
        pytest.fail(
            f"EXPECTED-UNIMPLEMENTED: missing frontend contract file {path}",
            pytrace=False,
        )
    return path


def build_fixture_tree(root: Path) -> FixtureTree:
    """Build four read-only sources using existing CLI/API formats.

    Sources:
    - a CLI-style run directory (no ``full_states_log``),
    - a saved report tree written by ``write_report_tree``,
    - a backtest run log written by ``TradingMemoryLog``,
    - a decision-memory log written by ``TradingMemoryLog``.
    """
    core = require_core()

    results_dir = root / "results"
    data_cache_dir = root / "cache"
    memory_log_path = root / "memory" / "trading_memory.md"
    static_dir = root / "static"
    for directory in (results_dir, data_cache_dir, static_dir):
        directory.mkdir(parents=True, exist_ok=True)
    (static_dir / "index.html").write_text(
        '<!doctype html><html><body><div id="root"></div></body></html>\n',
        encoding="utf-8",
    )

    # 1. CLI-style run directory: message log + per-section reports, no state log.
    run_dir = results_dir / "NVDA" / "2026-11-01"
    reports_dir = run_dir / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "market_report.md").write_text(
        f"# Market Analysis\n\nMKT content. Internal marker: {SECRET}\n",
        encoding="utf-8",
    )
    (reports_dir / "fundamentals_report.md").write_text(
        "# Fundamentals\n\nFUND content.\n", encoding="utf-8"
    )
    (reports_dir / "final_trade_decision.md").write_text(
        f"**Rating**: Buy\n\n**Executive Summary**: buy carefully.\n\n"
        f"**Investment Thesis**: thesis with a secret {SECRET}.\n",
        encoding="utf-8",
    )
    (run_dir / "message_tool.log").write_text(
        "12:00:00 [System] Selected ticker: NVDA\n"
        "12:00:01 [Tool Call] get_stock_data(ticker=NVDA, date=2026-11-01)\n",
        encoding="utf-8",
    )

    # Optional state log is present but malformed: readers must ignore it, not 500.
    state_dir = results_dir / "NVDA" / "TradingAgentsStrategy_logs"
    state_dir.mkdir(parents=True)
    (state_dir / "full_states_log_2026-11-01.json").write_text(
        "{not valid json", encoding="utf-8"
    )

    # A second run with only one section: status must be partial.
    partial_run_dir = results_dir / "MSFT" / "2026-11-02"
    (partial_run_dir / "reports").mkdir(parents=True)
    (partial_run_dir / "reports" / "market_report.md").write_text(
        "# Market\n\nMSFT partial.\n", encoding="utf-8"
    )

    # 2. Saved report tree through the shared writer.
    saved_dir = results_dir / "reports" / "AAPL_20261101_120000"
    final_state = {
        "market_report": f"# Market\n\nAAPL market. {SECRET}\n",
        "sentiment_report": "# Sentiment\n\nNeutral.\n",
        "news_report": "# News\n\nNo material news.\n",
        "fundamentals_report": "# Fundamentals\n\nSolid.\n",
        "investment_debate_state": {
            "bull_history": "Bull case.\n",
            "bear_history": "Bear case.\n",
            "judge_decision": "Research Manager plan.\n",
        },
        "trader_investment_plan": "Trader plan.\n",
        "risk_debate_state": {
            "aggressive_history": "Aggressive view.\n",
            "conservative_history": "Conservative view.\n",
            "neutral_history": "Neutral view.\n",
            "judge_decision": "**Rating**: Overweight\n\nPM decision.\n",
        },
    }
    core.write_report_tree(final_state, "AAPL", saved_dir)

    # 3. Backtest run log using the existing memory writer.
    backtest_run_id = "bt_001"
    backtest_dir = results_dir / "backtest" / backtest_run_id
    backtest_dir.mkdir(parents=True)
    backtest_log = core.TradingMemoryLog(
        {"memory_log_path": str(backtest_dir / "trading_memory.md")}
    )
    backtest_log.store_decision(
        "NVDA", "2026-10-01", "**Rating**: Buy\n\nBacktest NVDA.\n"
    )
    backtest_log.update_with_outcome(
        "NVDA",
        "2026-10-01",
        raw_return=0.02,
        alpha_return=0.01,
        holding_days=5,
        reflection="NVDA backtest reflection.",
        resolution_date="2026-10-08",
    )
    backtest_log.store_decision(
        "AAPL", "2026-10-01", "**Rating**: Hold\n\nBacktest AAPL.\n"
    )
    backtest_log.update_with_outcome(
        "AAPL",
        "2026-10-01",
        raw_return=0.00,
        alpha_return=-0.01,
        holding_days=5,
        reflection="AAPL backtest reflection.",
        resolution_date="2026-10-08",
    )

    # 4. Decision memory using the existing writer.
    memory_log_path.parent.mkdir(parents=True, exist_ok=True)
    memory_log = core.TradingMemoryLog({"memory_log_path": str(memory_log_path)})
    memory_log.store_decision(
        "MSFT", "2026-09-01", "**Rating**: Overweight\n\nMSFT decision.\n"
    )
    memory_log.update_with_outcome(
        "MSFT",
        "2026-09-01",
        raw_return=0.03,
        alpha_return=0.02,
        holding_days=5,
        reflection="MSFT reflection.",
        resolution_date="2026-09-08",
    )

    return FixtureTree(
        root=root,
        results_dir=results_dir,
        data_cache_dir=data_cache_dir,
        memory_log_path=memory_log_path,
        static_dir=static_dir,
        run_dir=run_dir,
        partial_run_dir=partial_run_dir,
        saved_dir=saved_dir,
        backtest_dir=backtest_dir,
        backtest_run_id=backtest_run_id,
    )


def make_settings(web, tree: FixtureTree, *, host: str = "127.0.0.1", static_dir=None, **overrides):
    """Build the approved ``WebSettings`` contract for a temp tree."""
    kwargs = {
        "results_dir": str(tree.results_dir),
        "memory_log_path": str(tree.memory_log_path),
        "data_cache_dir": str(tree.data_cache_dir),
        "host": host,
    }
    if static_dir is not None:
        kwargs["static_dir"] = str(static_dir)
    kwargs.update(overrides)
    try:
        return web.WebSettings(**kwargs)
    except TypeError as exc:
        pytest.fail(
            f"CONTRACT: WebSettings must accept {sorted(kwargs)}: {exc}",
            pytrace=False,
        )


def make_app(web, tree: FixtureTree, **settings_kwargs):
    settings = make_settings(web, tree, **settings_kwargs)
    try:
        return web.create_app(settings)
    except TypeError as exc:
        pytest.fail(
            f"CONTRACT: create_app(settings) is the approved factory: {exc}",
            pytrace=False,
        )


def make_client(app):
    from fastapi.testclient import TestClient

    return TestClient(app, base_url="http://127.0.0.1:8000")


def find_item(items, source: str, ticker: str | None = None):
    for item in items:
        if item.get("source") != source:
            continue
        if ticker is not None and item.get("ticker") != ticker:
            continue
        return item
    raise AssertionError(
        f"history did not expose source={source!r} ticker={ticker!r}: {items!r}"
    )


def json_text(response) -> str:
    return json.dumps(response.json(), ensure_ascii=False, sort_keys=True)
