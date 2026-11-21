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


@pytest.mark.parametrize(
    "kind,category",
    [
        ("internal", "internal"),
        ("config", "config"),
        ("missing_key", "config"),
        ("authentication", "authentication"),
        ("provider_limit", "rate_limit"),
        ("market_limit", "market_data_rate_limit"),
    ],
)
def test_backtest_failures_are_logged_safely_and_release_the_slot(
    tree_client, monkeypatch, caplog, kind, category
):
    """REQ-WEB-011/013, INV-WEB-003/014: diagnostics never replace failures or leak secrets."""
    from openai import OpenAIError
    from yfinance.exceptions import YFRateLimitError

    tree, client = tree_client
    secret = "temporary-backtest-provider-secret-1234567890"
    private_path = "/private/test/provider/credentials.json"
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)
    raw = f"provider failed with {secret} at {private_path}"
    error = RuntimeError(raw)
    if kind == "config":
        error = ValueError(raw)
    elif kind == "missing_key":
        error = OpenAIError("The api_key client option must be set " + raw)
    elif kind == "market_limit":
        error = YFRateLimitError()
    elif kind in {"authentication", "provider_limit"}:
        error.status_code = 401 if kind == "authentication" else 429
    before = hashlib.sha256(tree.memory_log_path.read_bytes()).hexdigest()
    _install_fake(monkeypatch, error=error)
    _, run_id = _start(client)
    terminal = _wait_terminal(client, run_id)
    assert terminal["status"] == "failed"
    failure = terminal["error"]
    assert failure["category"] == category
    assert failure["phase"] == "backtest"
    assert re.fullmatch(r"c_[a-f0-9]{12}", failure["correlation_id"])
    assert f"Backtest {failure['correlation_id']} failed during backtest" in caplog.text
    assert "Traceback (most recent call last)" in caplog.text
    assert secret not in caplog.text
    public = json.dumps(terminal)
    assert secret not in public
    assert private_path not in public
    assert raw not in public
    assert "Traceback" not in public
    if kind == "internal":
        assert failure["message"].startswith("Backtest failed")
    elif kind == "missing_key":
        assert "server's default model provider" in failure["message"]
        assert "not analysis-wizard selections" in failure["message"]
    assert hashlib.sha256(tree.memory_log_path.read_bytes()).hexdigest() == before
    deadline = time.monotonic() + 5
    while client.get("/api/runs/active").json().get("run_id") and time.monotonic() < deadline:
        time.sleep(0.01)
    assert client.get("/api/runs/active").json()["run_id"] is None
    _install_fake(monkeypatch)
    _, next_id = _start(client)
    assert _wait_terminal(client, next_id)["status"] == "completed"



def test_backtests_keep_environment_model_defaults(tree_client, monkeypatch):
    """REQ-WEB-011/013: editable analysis selection does not replace server backtest defaults."""
    from copy import deepcopy

    from tradingagents.default_config import DEFAULT_CONFIG

    before = deepcopy(DEFAULT_CONFIG)
    monkeypatch.setenv("TRADINGAGENTS_LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("TRADINGAGENTS_QUICK_THINK_LLM", "deepseek-flash")
    monkeypatch.setenv("TRADINGAGENTS_DEEP_THINK_LLM", "deepseek-flash")
    _, client = tree_client
    calls = []
    _install_fake(monkeypatch, calls=calls)
    _, run_id = _start(client)
    assert _wait_terminal(client, run_id)["status"] == "completed"
    assert calls[0]["config"]["llm_provider"] == "deepseek"
    assert calls[0]["config"]["quick_think_llm"] == "deepseek-flash"
    assert calls[0]["config"]["deep_think_llm"] == "deepseek-flash"
    assert before == DEFAULT_CONFIG


@pytest.mark.parametrize("fail_second", [False, True])
def test_real_core_progress_is_visible_before_completion_and_while_settling(tree_client, monkeypatch, fail_second):
    """REQ-WEB-007/011/026, INV-WEB-014: observe the actual loop, never infer progress from disk."""
    import tradingagents.backtest as core
    import tradingagents_web.runtime.backtest_runner as web

    tree, client = tree_client
    in_cell, release_cell = threading.Event(), threading.Event()
    in_settlement, release_settlement = threading.Event(), threading.Event()

    class Graph:
        def __init__(self, analysts, config):
            self.memory_log = TradingMemoryLog(config)

        def propagate(self, ticker, date, asset_type, portfolio=None):
            if date == "2026-06-08":
                in_cell.set()
                assert release_cell.wait(5)
                if fail_second:
                    raise RuntimeError("offline cell failure")
            self.memory_log.store_decision(ticker, date, "**Rating**: Buy")

        def settle_pending(self, ticker):
            in_settlement.set()
            assert release_settlement.wait(5)

    monkeypatch.setattr(core, "TradingAgentsGraph", Graph)
    monkeypatch.setattr(web, "run_backtest", core.run_backtest)
    try:
        _, run_id = _start(client, _body(tickers=["NVDA"]))
        assert in_cell.wait(5)
        path = f"/api/backtests/{run_id}"
        active = client.get(path).json()
        p = active["progress"]
        assert active["status"] == "running"
        assert p["phase"] == "analyzing" and p["current_date"] == "2026-06-08"
        assert p["processed"] == 1 and p["total"] == 2
        assert [row["status"] for row in p["cells"]] == ["completed", "running"]
        assert p["cells"][1]["elapsed_seconds"] >= 0
        reloaded = client.get(path).json()["progress"]
        assert [row["status"] for row in reloaded["cells"]] == ["completed", "running"]
        paged = client.get(path + "?cells_offset=1&cells_limit=1").json()["progress"]
        assert paged["offset"] == 1 and len(paged["cells"]) == 1
        assert paged["cells"][0]["date"] == "2026-06-08"
        for query in ("cells_offset=-1", "cells_limit=0", "cells_limit=101"):
            assert client.get(path + "?" + query).status_code == 422
        release_cell.set()
        assert in_settlement.wait(5)
        settling = client.get(path).json()
        assert settling["status"] == "running"
        assert settling["progress"]["processed"] == 2
        assert settling["progress"]["phase"] == "settling"
        assert settling["progress"]["failed"] == int(fail_second)
        listing = client.get("/api/backtests").json()["items"]
        assert next(row for row in listing if row["run_id"] == run_id)["status"] == "running"
        release_settlement.set()
        finished = _wait_terminal(client, run_id)
        assert finished["progress"]["phase"] == "completed"
        assert finished["progress"]["completed"] == 2 - int(fail_second)
        assert finished["progress"]["settlements_completed"] == 1
        assert len(finished["summary"]["failures"]) == int(fail_second)
        legacy = client.get(f"/api/backtests/{tree.backtest_run_id}").json()
        assert legacy.get("progress") is None
    finally:
        release_cell.set()
        release_settlement.set()


def test_progress_rejects_invalid_transitions_and_bounds_snapshots():
    """REQ-WEB-011/021, INV-WEB-003/014: duplicate/foreign observations cannot inflate completion."""
    from tradingagents_web.runtime.backtest_progress import BacktestProgress

    p = BacktestProgress(["NVDA"], [f"2026-06-{index:02}" for index in range(1, 29)])
    for event in [
        {"event": "cell.completed", "ticker": "NVDA", "date": "2026-06-01"},
        {"event": "cell.started", "ticker": "OTHER", "date": "2026-06-01"},
        {"event": "settlement.started", "ticker": "NVDA"},
        {"event": "summarizing"},
    ]:
        p.update(event)
    assert p.snapshot()["processed"] == 0 and p.phase == "preparing"
    for date in p.dates:
        p.update({"event": "cell.skipped", "ticker": "NVDA", "date": date})
        p.update({"event": "cell.completed", "ticker": "NVDA", "date": date})
    snapshot = p.snapshot()
    assert snapshot["processed"] == 28 and snapshot["skipped"] == 28
    assert snapshot["offset"] == 25 and len(snapshot["cells"]) == 3
    assert len(p.snapshot(0, 1000)["cells"]) <= 100
    p.finish("completed")
    p.update({"event": "cell.started", "ticker": "NVDA", "date": p.dates[0]})
    assert p.snapshot()["phase"] == "completed"
