"""WebUI backtest contracts.

Covers REQ-WEB-011 and the isolation half of REQ-WEB-030. Backtests use a fake
runner that writes an isolated memory log; no model or data provider is called.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time

import pytest

from test.offline.web_fixture_app import (
    FakeGraphRunner,
    build_fixture_tree,
    make_iteration3_client,
    require_iteration3_modules,
    wait_terminal,
)
from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.backtest import BacktestResult

pytestmark = pytest.mark.unit


def _body(**overrides):
    body = {
        "tickers": ["NVDA", "AAPL"],
        "start": "2026-06-01",
        "end": "2026-06-08",
        "every": 7,
        "analysts": ["market", "news"],
        "asset_type": "stock",
        "portfolio_json": None,
        "run_id": None,
    }
    body.update(overrides)
    return body


def _run_body():
    return {
        "client_request_id": "backtest-conflict",
        "ticker": "NVDA",
        "trade_date": "2026-11-01",
        "analysts": ["market"],
        "research_depth": 1,
        "llm_provider": "openai",
        "quick_think_llm": "gpt-5.6-luna",
        "deep_think_llm": "gpt-5.6",
    }


def _write_backtest_log(config, tickers, dates):
    log_path = config["memory_log_path"]
    log = TradingMemoryLog({"memory_log_path": str(log_path)})
    for ticker in tickers:
        for date in dates:
            log.store_decision(ticker, date, "**Rating**: Buy\n\nBacktest cell.\n")
            log.update_with_outcome(
                ticker,
                date,
                raw_return=0.02,
                alpha_return=0.01,
                holding_days=5,
                reflection="Backtest reflection.",
                resolution_date="2026-06-15",
            )
    return log_path


def _install_fake(
    monkeypatch,
    calls=None,
    block=False,
    error=None,
    failures=None,
    settlement_failures=None,
):
    import tradingagents_web.runtime.backtest_runner as module

    started = threading.Event()
    release = threading.Event()

    def fake(
        tickers,
        dates,
        config,
        asset_type="stock",
        portfolio=None,
        selected_analysts=("market", "social", "news", "fundamentals"),
        run_id=None,
    ):
        if calls is not None:
            calls.append(
                {
                    "tickers": list(tickers),
                    "dates": list(dates),
                    "asset_type": asset_type,
                    "portfolio": portfolio,
                    "selected_analysts": list(selected_analysts),
                    "run_id": run_id,
                    "config": dict(config),
                }
            )
        started.set()
        if block:
            release.wait(timeout=5)
        if error is not None:
            raise error
        log_path = _write_backtest_log(config, tickers, dates)
        return BacktestResult(
            run_id=run_id or "bt_fake",
            log_path=log_path,
            cells_run=len(tickers) * len(dates),
            failures=list(failures or []),
            settlement_failures=list(settlement_failures or []),
        )

    monkeypatch.setattr(module, "run_backtest", fake)
    return started, release


def _wait_terminal(client, run_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/backtests/{run_id}")
        if response.status_code == 200:
            last = response.json()
            if last.get("status") in {"completed", "failed"}:
                return last
        time.sleep(0.02)
    pytest.fail(f"backtest {run_id} did not finish; last={last!r}", pytrace=False)


def _start(client, body=None):
    response = client.post("/api/backtests", json=body or _body())
    assert response.status_code in {201, 202}, response.text
    run_id = response.json().get("run_id") or response.json().get("backtest_id")
    assert run_id
    return response, run_id


@pytest.fixture()
def tree_client(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy-secret-1234567890")
    require_iteration3_modules()
    tree = build_fixture_tree(tmp_path)
    return tree, make_iteration3_client(tree)


def test_backtest_parameters_match_cli(tree_client, monkeypatch):
    tree, client = tree_client
    calls: list[dict] = []
    _install_fake(monkeypatch, calls=calls)

    response, run_id = _start(client)
    terminal = _wait_terminal(client, run_id)
    assert terminal["status"] == "completed"

    assert calls
    call = calls[0]
    assert call["tickers"] == ["NVDA", "AAPL"]
    assert call["dates"] == ["2026-06-01", "2026-06-08"]
    assert call["selected_analysts"] == ["market", "news"]
    assert call["asset_type"] == "stock"
    assert call["portfolio"] is None
    assert call["run_id"] is None
    assert call["config"]["results_dir"] == str(tree.results_dir)

    assert str(tree.results_dir) not in response.text
    assert str(tree.results_dir) not in str(terminal)


def test_summary_fields_match_cli(tree_client, monkeypatch):
    _, client = tree_client
    _install_fake(
        monkeypatch,
        failures=[("NVDA", "2026-06-08", "vendor unavailable")],
        settlement_failures=[("AAPL", "settlement unavailable")],
    )

    _, run_id = _start(client)
    terminal = _wait_terminal(client, run_id)
    assert terminal["status"] == "completed"

    summary = terminal["summary"]
    assert {
        "resolved",
        "pending",
        "unscored",
        "by_rating",
        "holding",
        "failures",
        "settlement_failures",
        "log_artifact_id",
    } <= set(summary)
    assert summary["resolved"] >= 1
    assert summary["by_rating"]["Buy"]["count"] >= 1
    assert summary["by_rating"]["Buy"]["hit_rate"] is not None
    assert isinstance(summary["by_rating"]["Buy"]["mean_alpha"], float)
    assert summary["failures"]
    assert summary["settlement_failures"]
    assert re.fullmatch(r"[0-9a-f]{16}", summary["log_artifact_id"])


def test_backtest_log_is_downloadable_by_artifact_id(tree_client, monkeypatch):
    _, client = tree_client
    _install_fake(monkeypatch)
    _, run_id = _start(client)
    summary = _wait_terminal(client, run_id)["summary"]

    response = client.get(
        f"/api/history/{summary['log_artifact_id']}/download",
        params={"kind": "log"},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/markdown")
    assert "Backtest cell" in response.text
    assert str(client.app.state.settings.results_dir) not in response.text


def test_backtest_does_not_write_live_memory(tree_client, monkeypatch):
    tree, client = tree_client
    before = hashlib.sha256(tree.memory_log_path.read_bytes()).hexdigest()
    _install_fake(monkeypatch)

    _, run_id = _start(client)
    _wait_terminal(client, run_id)

    after = hashlib.sha256(tree.memory_log_path.read_bytes()).hexdigest()
    assert after == before
    logs = list((tree.results_dir / "backtest").glob("*/trading_memory.md"))
    assert logs
    assert all(log != tree.memory_log_path for log in logs)


def test_portfolio_json_is_validated_and_forwarded(tree_client, monkeypatch):
    _, client = tree_client
    calls: list[dict] = []
    _install_fake(monkeypatch, calls=calls)

    absent_response, absent_id = _start(client, _body())
    _wait_terminal(client, absent_id)
    assert calls[0]["portfolio"] is None

    empty_response = client.post(
        "/api/backtests",
        json=_body(portfolio_json=json.dumps({"cash": 0, "positions": []})),
    )
    assert empty_response.status_code in {201, 202}, empty_response.text
    empty_id = empty_response.json().get("run_id") or empty_response.json().get(
        "backtest_id"
    )
    _wait_terminal(client, empty_id)
    assert calls[1]["portfolio"] is not None
    assert calls[1]["portfolio"].fingerprint() != ""
    assert absent_response.json().get("portfolio_fingerprint") is None


def test_run_id_is_forwarded_for_resume(tree_client, monkeypatch):
    _, client = tree_client
    calls: list[dict] = []
    _install_fake(monkeypatch, calls=calls)
    _start(client, _body(run_id="bt_resume"))
    assert calls[0]["run_id"] == "bt_resume"


def test_second_backtest_is_rejected(tree_client, monkeypatch):
    _, client = tree_client
    started, release = _install_fake(monkeypatch, block=True)
    _, first_id = _start(client)
    assert started.wait(timeout=2)

    second = client.post("/api/backtests", json=_body())
    assert second.status_code == 409, second.text

    release.set()
    _wait_terminal(client, first_id)


def test_backtest_and_analysis_share_one_slot(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy-secret-1234567890")
    require_iteration3_modules()
    tree = build_fixture_tree(tmp_path)
    client = make_iteration3_client(tree, runner_factory=FakeGraphRunner)

    started, release = _install_fake(monkeypatch, block=True)
    _, backtest_id = _start(client)
    assert started.wait(timeout=2)
    analysis = client.post("/api/runs", json=_run_body())
    assert analysis.status_code == 409, analysis.text
    release.set()
    _wait_terminal(client, backtest_id)

    runner = FakeGraphRunner(block_after=0)
    client.app.state.coordinator.runner_factory = runner
    response = client.post("/api/runs", json=_run_body())
    assert response.status_code == 201, response.text
    assert runner.started.wait(timeout=2)
    blocked = client.post("/api/backtests", json=_body())
    assert blocked.status_code == 409, blocked.text

    client.post(f"/api/runs/{response.json()['run_id']}/cancel")
    wait_terminal(client, response.json()["run_id"])


def test_backtest_failure_preserves_live_memory(tree_client, monkeypatch):
    tree, client = tree_client
    before = hashlib.sha256(tree.memory_log_path.read_bytes()).hexdigest()
    _install_fake(monkeypatch, error=RuntimeError("fake backtest failure"))
    _, run_id = _start(client)
    terminal = _wait_terminal(client, run_id)
    assert terminal["status"] == "failed"
    assert hashlib.sha256(tree.memory_log_path.read_bytes()).hexdigest() == before


def test_no_backtest_cancel_route(tree_client, monkeypatch):
    _, client = tree_client
    _install_fake(monkeypatch)
    _, run_id = _start(client)
    cancel = client.post(f"/api/backtests/{run_id}/cancel")
    assert cancel.status_code in {404, 405}
    _wait_terminal(client, run_id)


def test_unknown_backtest_is_404(tree_client):
    _, client = tree_client
    assert client.get("/api/backtests/does-not-exist").status_code == 404


def test_backtest_history_is_read_only(tree_client):
    tree, client = tree_client
    listing = client.get("/api/backtests")
    assert listing.status_code == 200, listing.text
    items = listing.json()["items"]
    assert any(item.get("run_id") == tree.backtest_run_id for item in items)
    assert str(tree.results_dir) not in listing.text

    detail = client.get(f"/api/backtests/{tree.backtest_run_id}")
    assert detail.status_code == 200, detail.text
    assert "log_path" not in detail.text

    before = {
        path: (path.stat().st_size, path.stat().st_mtime_ns)
        for path in tree.results_dir.rglob("*")
        if path.is_file()
    }
    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)(f"/api/backtests/{tree.backtest_run_id}")
        assert response.status_code in {404, 405}
    after = {
        path: (path.stat().st_size, path.stat().st_mtime_ns)
        for path in tree.results_dir.rglob("*")
        if path.is_file()
    }
    assert after == before


@pytest.mark.parametrize(
    "overrides",
    [
        {"tickers": []},
        {"tickers": ["../etc/passwd"]},
        {"start": "2026-08-01", "end": "2026-06-01"},
        {"start": "not-a-date"},
        {"every": 0},
        {"analysts": []},
        {"analysts": ["unknown"]},
        {"asset_type": "bond"},
        {"portfolio_json": "{not json"},
        {"run_id": "../escape"},
    ],
)
def test_invalid_backtest_requests_are_rejected(tree_client, overrides):
    _, client = tree_client
    response = client.post("/api/backtests", json=_body(**overrides))
    assert response.status_code in {400, 422}, response.text
    assert client.get("/api/runs/active").json().get("run_id") is None
