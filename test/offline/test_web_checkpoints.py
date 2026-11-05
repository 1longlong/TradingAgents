"""Checkpoint controls for the run control plane.

Covers REQ-WEB-003 and the cancellation interaction in REQ-WEB-005/029.
"""

from __future__ import annotations

import pytest

from test.offline.web_fixture_app import (
    FakeGraphRunner,
    build_fixture_tree,
    make_run_client,
    wait_terminal,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def tree_client(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy-secret-1234567890")
    tree = build_fixture_tree(tmp_path)
    return tree, make_run_client(tree, runner_factory=FakeGraphRunner)


def _run_body(checkpoint: bool = False):
    return {
        "client_request_id": f"checkpoint-{checkpoint}",
        "ticker": "NVDA",
        "trade_date": "2026-11-01",
        "analysts": ["market"],
        "checkpoint": checkpoint,
    }


def test_checkpoint_toggle_is_reported_on_the_run(tree_client):
    _, client = tree_client
    response = client.post("/api/runs", json=_run_body(checkpoint=True))
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["checkpoint_enabled"] is True
    wait_terminal(client, payload["run_id"])


def test_clear_requires_explicit_confirmation(tree_client):
    _, client = tree_client
    missing = client.post("/api/checkpoints/clear", json={})
    assert missing.status_code in {400, 422}
    wrong = client.post("/api/checkpoints/clear", json={"confirm": "yes"})
    assert wrong.status_code in {400, 422}
    ok = client.post("/api/checkpoints/clear", json={"confirm": "CLEAR"})
    assert ok.status_code == 200, ok.text
    assert isinstance(ok.json()["cleared"], int)


def test_clear_removes_checkpoint_databases_and_reports_count(tree_client):
    tree, client = tree_client
    checkpoint_dir = tree.data_cache_dir / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    (checkpoint_dir / "NVDA.db").write_bytes(b"fake")
    (checkpoint_dir / "NVDA.db-wal").write_bytes(b"fake")
    (checkpoint_dir / "AAPL.db").write_bytes(b"fake")

    response = client.post("/api/checkpoints/clear", json={"confirm": "CLEAR"})
    assert response.status_code == 200, response.text
    assert response.json()["cleared"] >= 2
    assert not list(checkpoint_dir.glob("*.db"))
    assert not list(checkpoint_dir.glob("*.db-*"))


def test_clear_is_rejected_while_a_run_is_active(tree_client):
    _, _ = tree_client
    fake = FakeGraphRunner(block_after=0)
    # The fixture client already has a runner; this test uses a fresh app with
    # a blocking runner so cancellation can be exercised deterministically.
    client = make_run_client(tree_client[0], runner_factory=fake)
    started = client.post("/api/runs", json=_run_body())
    assert started.status_code == 201, started.text
    assert fake.started.wait(timeout=2.0)

    clear = client.post("/api/checkpoints/clear", json={"confirm": "CLEAR"})
    assert clear.status_code == 409, clear.text

    cancel = client.post(f"/api/runs/{started.json()['run_id']}/cancel")
    assert cancel.status_code in {200, 202}, cancel.text
    wait_terminal(client, started.json()["run_id"])


def test_clear_response_contains_no_server_paths(tree_client):
    tree, client = tree_client
    response = client.post("/api/checkpoints/clear", json={"confirm": "CLEAR"})
    assert response.status_code == 200, response.text
    assert str(tree.data_cache_dir) not in response.text
    assert "/Users/" not in response.text
