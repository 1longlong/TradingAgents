"""Single-run lifecycle, validation, cancellation, and failure handling.

Covers REQ-WEB-005, REQ-WEB-006, REQ-WEB-007 (API side), REQ-WEB-029 and the
run-state half of REQ-WEB-031.
"""

from __future__ import annotations

import json
import uuid

import pytest

from test.offline.web_fixture_app import (
    FakeGraphRunner,
    build_fixture_tree,
    make_run_client,
    wait_terminal,
)

pytestmark = pytest.mark.unit


def _body(**overrides):
    body = {
        "client_request_id": uuid.uuid4().hex,
        "ticker": "NVDA",
        "trade_date": "2026-11-01",
        "asset_type": "stock",
        "output_language": "English",
        "analysts": ["market", "social", "news", "fundamentals"],
        "research_depth": 1,
        "llm_provider": "openai",
        "quick_think_llm": "gpt-5.6-luna",
        "deep_think_llm": "gpt-5.6",
        "checkpoint": False,
    }
    body.update(overrides)
    return body


@pytest.fixture()
def tree_client(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy-secret-1234567890")
    tree = build_fixture_tree(tmp_path)
    return tree, make_run_client(tree, runner_factory=FakeGraphRunner)


def test_start_run_returns_snapshot_and_active_run(tree_client):
    tree, _ = tree_client
    fake = FakeGraphRunner(block_after=0)
    client = make_run_client(tree, runner_factory=fake)
    response = client.post("/api/runs", json=_body())
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["run_id"]
    assert payload["status"] in {"starting", "running"}
    assert "portfolio_fingerprint" in payload

    active = client.get("/api/runs/active")
    assert active.status_code == 200, active.text
    assert active.json()["run_id"] == payload["run_id"]

    client.post(f"/api/runs/{payload['run_id']}/cancel")
    wait_terminal(client, payload["run_id"])

    text = json.dumps(payload)
    assert str(tree.results_dir) not in text
    assert str(tree.root) not in text


def test_second_run_is_rejected_without_queueing(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy-secret-1234567890")
    tree = build_fixture_tree(tmp_path)
    fake = FakeGraphRunner(block_after=0)
    client = make_run_client(tree, runner_factory=fake)
    first = client.post("/api/runs", json=_body())
    assert first.status_code == 201, first.text
    assert fake.started.wait(timeout=2.0)

    second = client.post("/api/runs", json=_body())
    assert second.status_code == 409, second.text
    assert second.json()["error"]["fields"]["active_run_id"] == first.json()["run_id"]

    cancel = client.post(f"/api/runs/{first.json()['run_id']}/cancel")
    assert cancel.status_code in {200, 202}, cancel.text
    wait_terminal(client, first.json()["run_id"])


@pytest.mark.parametrize(
    "overrides",
    [
        {"ticker": "../etc/passwd"},
        {"trade_date": "not-a-date"},
        {"trade_date": "2999-01-01"},
        {"analysts": []},
        {"analysts": ["unknown"]},
        {"research_depth": 2},
        {"llm_provider": "not-a-provider"},
        {"config": {"results_dir": "/tmp"}},
    ],
)
def test_invalid_run_requests_are_rejected_without_starting(tree_client, overrides):
    _, client = tree_client
    response = client.post("/api/runs", json=_body(**overrides))
    assert response.status_code in {400, 422}, response.text
    assert client.get("/api/runs/active").json().get("run_id") is None


def test_cancel_preserves_memory_and_checkpoint_and_writes_no_decision(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy-secret-1234567890")
    tree = build_fixture_tree(tmp_path)
    before = tree.memory_log_path.read_text(encoding="utf-8")
    fake = FakeGraphRunner(block_after=0)
    client = make_run_client(tree, runner_factory=fake)

    started = client.post("/api/runs", json=_body(checkpoint=True))
    assert started.status_code == 201, started.text
    assert fake.started.wait(timeout=2.0)

    cancel = client.post(f"/api/runs/{started.json()['run_id']}/cancel")
    assert cancel.status_code in {200, 202}, cancel.text
    terminal = wait_terminal(client, started.json()["run_id"])
    assert terminal["status"] == "cancelled"
    assert tree.memory_log_path.read_text(encoding="utf-8") == before
    checkpoint_dir = tree.data_cache_dir / "checkpoints"
    assert not list(checkpoint_dir.glob("*.db"))


def test_cancel_keeps_already_written_partial_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy-secret-1234567890")
    tree = build_fixture_tree(tmp_path)
    fake = FakeGraphRunner(block_after=4)  # after report.section
    client = make_run_client(tree, runner_factory=fake)

    started = client.post("/api/runs", json=_body())
    assert started.status_code == 201, started.text
    assert fake.started.wait(timeout=2.0)

    report = tree.results_dir / "NVDA" / "2026-11-01" / "reports" / "market_report.md"
    for _ in range(200):
        if report.is_file():
            break
        import time

        time.sleep(0.01)
    assert report.is_file(), "report.section was not written to the run directory"

    client.post(f"/api/runs/{started.json()['run_id']}/cancel")
    terminal = wait_terminal(client, started.json()["run_id"])
    assert terminal["status"] == "cancelled"
    assert report.is_file()


def test_missing_key_allows_start_then_fails_safely(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    tree = build_fixture_tree(tmp_path)
    failed_event = {
        "type": "run.failed",
        "payload": {"category": "config", "message": "provider key not configured"},
    }
    fake = FakeGraphRunner(events=[failed_event])
    client = make_run_client(tree, runner_factory=fake)

    started = client.post("/api/runs", json=_body())
    assert started.status_code == 201, started.text
    terminal = wait_terminal(client, started.json()["run_id"])
    assert terminal["status"] == "failed"
    assert terminal["error"]["category"] in {"config", "upstream"}


def test_unknown_run_and_cancel_are_404(tree_client):
    _, client = tree_client
    assert client.get("/api/runs/does-not-exist").status_code == 404
    assert client.post("/api/runs/does-not-exist/cancel").status_code == 404


def test_run_snapshot_does_not_expose_secret_or_paths(tree_client, monkeypatch):
    tree, client = tree_client
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy-secret-1234567890")
    started = client.post("/api/runs", json=_body())
    assert started.status_code == 201, started.text
    text = json.dumps(started.json())
    assert "sk-test-dummy-secret-1234567890" not in text
    assert str(tree.results_dir) not in text
    wait_terminal(client, started.json()["run_id"])
