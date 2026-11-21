"""WebUI permission and secret boundaries.

Covers REQ-WEB-020 (loopback/no auth), REQ-WEB-023 (secrets), REQ-WEB-024
(no paths), REQ-WEB-025 (untrusted-content policy) and
INV-WEB-002/003/004/005/012/013. Server-only key status is deferred to the
configuration/wizard iteration and is not claimed here.
"""

from __future__ import annotations

import json
import re
import time
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from test.offline.web_fixture_app import (
    SECRET,
    FakeGraphRunner,
    build_fixture_tree,
    find_item,
    json_text,
    make_app,
    make_client,
    make_iteration3_client,
    make_run_client,
    require_web,
    wait_terminal,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def web_client(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    tree = build_fixture_tree(tmp_path)
    web = require_web()
    app = make_app(web, tree)
    return tree, make_client(app)


def _items(client):
    response = client.get("/api/history", params={"limit": 50})
    assert response.status_code == 200, response.text
    return response.json()["items"]


def test_bind_address_is_loopback_only(tmp_path):
    tree = build_fixture_tree(tmp_path)
    web = require_web()
    with pytest.raises((ValueError, RuntimeError)):
        make_app(web, tree, host="0.0.0.0")


def test_non_loopback_host_header_is_rejected(web_client):
    _, client = web_client
    response = client.get("/api/health", headers={"Host": "evil.example"})
    assert response.status_code == 400, response.text


def test_localhost_host_header_is_allowed(web_client):
    _, client = web_client
    response = client.get("/api/health", headers={"Host": "localhost:8000"})
    assert response.status_code == 200, response.text


def test_no_wildcard_cors(web_client):
    _, client = web_client
    response = client.options(
        "/api/history",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    allow_origin = response.headers.get("access-control-allow-origin")
    assert allow_origin != "*"
    assert allow_origin in {None, ""} or response.status_code in {403, 405}


def test_csp_and_security_headers(web_client):
    _, client = web_client
    response = client.get("/api/health")
    assert response.status_code == 200, response.text
    csp = response.headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "script-src" in csp
    assert "unsafe-eval" not in csp
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("referrer-policy") == "no-referrer"


def test_no_authentication_is_required_on_loopback(web_client):
    _, client = web_client
    response = client.get("/api/history")
    assert response.status_code == 200, response.text
    assert "www-authenticate" not in response.headers


def test_secrets_never_serialized(web_client):
    _, client = web_client
    for response in (
        client.get("/api/health"),
        client.get("/api/history"),
        client.get("/api/history/0000000000000000"),
        client.get("/openapi.json"),
    ):
        assert SECRET not in response.text


def test_secret_is_redacted_from_artifact_downloads(web_client):
    _, client = web_client
    item = find_item(_items(client), "run", "NVDA")
    response = client.get(
        f"/api/history/{item['artifact_id']}/download",
        params={"kind": "section", "section": "market_report"},
    )
    assert response.status_code == 200, response.text
    assert SECRET not in response.text
    assert "***" in response.text or "[REDACTED]" in response.text


def test_secret_is_redacted_inside_archive(web_client):
    _, client = web_client
    item = find_item(_items(client), "run", "NVDA")
    response = client.get(
        f"/api/history/{item['artifact_id']}/download", params={"kind": "archive"}
    )
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        for name in archive.namelist():
            text = archive.read(name).decode("utf-8", errors="ignore")
            assert SECRET not in text, name


def test_responses_contain_no_filesystem_paths(web_client):
    tree, client = web_client
    item = find_item(_items(client), "run", "NVDA")
    responses = [
        client.get("/api/history"),
        client.get(f"/api/history/{item['artifact_id']}"),
        client.get(
            f"/api/history/{item['artifact_id']}/download", params={"kind": "archive"}
        ),
    ]
    for response in responses:
        assert str(tree.root) not in response.text
        assert str(tree.results_dir) not in response.text
        assert "/Users/" not in response.text
        assert "/private/" not in response.text


def test_archive_entries_are_relative_and_do_not_escape(web_client):
    _, client = web_client
    item = find_item(_items(client), "run", "NVDA")
    response = client.get(
        f"/api/history/{item['artifact_id']}/download", params={"kind": "archive"}
    )
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        for name in archive.namelist():
            assert not name.startswith("/")
            assert ".." not in name.split("/")
            assert "\\" not in name


def test_artifact_ids_are_opaque(web_client):
    _, client = web_client
    ids = [item["artifact_id"] for item in _items(client)]
    assert ids
    assert all(re.fullmatch(r"[0-9a-f]{16}", value) for value in ids)


@pytest.mark.parametrize(
    "path",
    ["/api/orders", "/api/trades", "/api/execute", "/api/positions"],
)
def test_no_execution_endpoint_exists(web_client, path):
    _, client = web_client
    response = client.post(path, json={})
    assert response.status_code in {404, 405}


def test_history_mutations_are_rejected(web_client):
    _, client = web_client
    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)("/api/history")
        assert response.status_code in {404, 405}


def test_errors_are_redacted(web_client):
    tree, client = web_client
    response = client.get("/api/history/does-not-exist")
    assert response.status_code == 404
    assert SECRET not in response.text
    assert str(tree.results_dir) not in response.text
    assert "Traceback" not in response.text


def test_oversized_report_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    tree = build_fixture_tree(tmp_path)
    web = require_web()
    app = make_app(web, tree, max_report_bytes=10)
    client = make_client(app)
    item = find_item(_items(client), "run", "NVDA")
    response = client.get(
        f"/api/history/{item['artifact_id']}/download",
        params={"kind": "section", "section": "market_report"},
    )
    assert response.status_code == 413, response.text


def test_missing_static_assets_fail_loudly(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    tree = build_fixture_tree(tmp_path)
    empty_static = tmp_path / "empty-static"
    empty_static.mkdir()
    web = require_web()
    app = make_app(web, tree, static_dir=empty_static)
    client = make_client(app)
    response = client.get("/")
    assert response.status_code in {404, 503}, response.text
    body = response.text.lower()
    assert "build" in body or "frontend" in body
    assert client.get("/api/health").status_code == 200


def test_openapi_has_history_and_no_execution_paths(web_client):
    _, client = web_client
    response = client.get("/openapi.json")
    assert response.status_code == 200, response.text
    paths = response.json()["paths"]
    assert "/api/history" in paths
    assert "/api/history/{artifact_id}" in paths
    forbidden = ("order", "trade", "execute", "position")
    assert not any(
        any(word in path.lower() for word in forbidden) for path in paths
    ), paths


def test_history_json_contains_no_secret_after_detail(web_client):
    _, client = web_client
    item = find_item(_items(client), "run", "NVDA")
    response = client.get(f"/api/history/{item['artifact_id']}")
    assert response.status_code == 200, response.text
    assert SECRET not in json_text(response)


def _run_body():
    return {
        "client_request_id": "csrf-test",
        "ticker": "NVDA",
        "trade_date": "2026-11-01",
        "analysts": ["market"],
        "research_depth": 1,
        "llm_provider": "openai",
        "quick_think_llm": "gpt-5.6-luna",
        "deep_think_llm": "gpt-5.6",
    }


def test_session_issues_a_csrf_token(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    tree = build_fixture_tree(tmp_path)
    client = make_run_client(tree, runner_factory=FakeGraphRunner)
    response = client.get("/api/session")
    assert response.status_code == 200, response.text
    token = response.json()["csrf_token"]
    assert isinstance(token, str)
    assert len(token) >= 16


def test_post_without_csrf_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    tree = build_fixture_tree(tmp_path)
    client = make_run_client(tree, runner_factory=FakeGraphRunner, csrf=False)
    response = client.post("/api/runs", json=_run_body())
    assert response.status_code == 403, response.text
    assert client.get("/api/runs/active").json().get("run_id") is None


def test_post_with_wrong_csrf_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    tree = build_fixture_tree(tmp_path)
    client = make_run_client(tree, runner_factory=FakeGraphRunner, csrf=False)
    response = client.post(
        "/api/runs", json=_run_body(), headers={"X-CSRF-Token": "wrong"}
    )
    assert response.status_code == 403, response.text


def test_cross_origin_post_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    tree = build_fixture_tree(tmp_path)
    client = make_run_client(tree, runner_factory=FakeGraphRunner)
    response = client.post(
        "/api/runs",
        json=_run_body(),
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403, response.text


def test_checkpoint_clear_requires_csrf(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    tree = build_fixture_tree(tmp_path)
    client = make_run_client(tree, runner_factory=FakeGraphRunner, csrf=False)
    response = client.post("/api/checkpoints/clear", json={"confirm": "CLEAR"})
    assert response.status_code == 403, response.text


def test_run_snapshot_does_not_expose_secret_or_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    tree = build_fixture_tree(tmp_path)
    client = make_run_client(tree, runner_factory=FakeGraphRunner)
    started = client.post("/api/runs", json=_run_body())
    assert started.status_code == 201, started.text
    text = json.dumps(started.json())
    assert SECRET not in text
    assert str(tree.results_dir) not in text
    wait_terminal(client, started.json()["run_id"])


def _backtest_body():
    return {
        "tickers": ["NVDA"],
        "start": "2026-06-01",
        "end": "2026-06-01",
        "every": 7,
        "analysts": ["market"],
        "asset_type": "stock",
        "portfolio_json": None,
        "run_id": None,
    }


def _install_backtest_fake(monkeypatch):
    import tradingagents_web.runtime.backtest_runner as module
    from tradingagents.agents.utils.memory import TradingMemoryLog
    from tradingagents.backtest import BacktestResult

    def fake(tickers, dates, config, **kwargs):
        log = TradingMemoryLog({"memory_log_path": str(config["memory_log_path"])})
        for ticker in tickers:
            for date in dates:
                log.store_decision(ticker, date, "**Rating**: Buy\n\nSecurity cell.\n")
                log.update_with_outcome(
                    ticker,
                    date,
                    raw_return=0.02,
                    alpha_return=0.01,
                    holding_days=5,
                    reflection="Security reflection.",
                    resolution_date="2026-06-08",
                )
        return BacktestResult(run_id="bt_security", log_path=config["memory_log_path"])

    monkeypatch.setattr(module, "run_backtest", fake)


def test_backtest_post_requires_csrf(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    tree = build_fixture_tree(tmp_path)
    client = make_iteration3_client(tree, csrf=False)
    response = client.post("/api/backtests", json=_backtest_body())
    assert response.status_code == 403, response.text
    assert client.get("/api/backtests").status_code == 200


def test_backtest_cross_origin_post_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    tree = build_fixture_tree(tmp_path)
    client = make_iteration3_client(tree)
    response = client.post(
        "/api/backtests",
        json=_backtest_body(),
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403, response.text


def test_backtest_snapshot_does_not_expose_secret_or_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    tree = build_fixture_tree(tmp_path)
    client = make_iteration3_client(tree)
    _install_backtest_fake(monkeypatch)
    started = client.post("/api/backtests", json=_backtest_body())
    assert started.status_code in {201, 202}, started.text
    run_id = started.json().get("run_id") or started.json().get("backtest_id")

    deadline = time.monotonic() + 5
    terminal = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/backtests/{run_id}")
        if response.status_code == 200:
            terminal = response.json()
            if terminal.get("status") in {"completed", "failed"}:
                break
        time.sleep(0.02)
    assert terminal and terminal["status"] == "completed"
    text = started.text + json.dumps(terminal)
    assert SECRET not in text
    assert str(tree.results_dir) not in text
    assert "/Users/" not in text


def test_announcement_html_is_escaped(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    tree = build_fixture_tree(tmp_path)
    client = make_iteration3_client(tree)
    import tradingagents_web.api.announcements as module

    monkeypatch.setattr(
        module,
        "fetch_announcements",
        lambda *args, **kwargs: {
            "announcements": ["<script>alert(1)</script>", "<img src=x onerror=1>"],
            "require_attention": False,
        },
    )
    response = client.get("/api/announcements")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    assert "text/html" not in response.headers["content-type"]

    component = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "tradingagents_web"
        / "frontend"
        / "src"
        / "components"
        / "Announcements.tsx"
    )
    assert component.is_file(), "EXPECTED-UNIMPLEMENTED: Announcements.tsx is missing"
    source = component.read_text(encoding="utf-8")
    assert "dangerouslySetInnerHTML" not in source
    assert "<script" not in source.lower()
