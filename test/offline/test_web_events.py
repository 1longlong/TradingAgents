"""SSE event projection, ordering, and reattachment.

Covers REQ-WEB-002, REQ-WEB-007 and REQ-WEB-022.
"""

from __future__ import annotations

import time
import uuid

import pytest

from test.offline.web_fixture_app import (
    FakeGraphRunner,
    build_fixture_tree,
    make_run_client,
    parse_sse,
    wait_terminal,
)

pytestmark = pytest.mark.unit


def _body():
    return {
        "client_request_id": uuid.uuid4().hex,
        "ticker": "NVDA",
        "trade_date": "2026-11-01",
        "analysts": ["market"],
        "research_depth": 1,
        "llm_provider": "openai",
        "quick_think_llm": "gpt-5.6-luna",
        "deep_think_llm": "gpt-5.6",
    }


@pytest.fixture()
def tree_client(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy-secret-1234567890")
    tree = build_fixture_tree(tmp_path)
    return tree, make_run_client(tree, runner_factory=FakeGraphRunner)


def _collect_events(client, run_id, after_seq=0):
    lines = []
    with client.stream(
        "GET", f"/api/runs/{run_id}/events", params={"after_seq": after_seq}
    ) as response:
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            lines.append(line)
            if line.startswith("data:") and any(
                marker in line
                for marker in ("run.completed", "run.failed", "run.cancelled")
            ):
                break
    return parse_sse("\n".join(lines))


def test_event_stream_has_monotonic_sequence_and_expected_types(tree_client):
    _, client = tree_client
    started = client.post("/api/runs", json=_body())
    assert started.status_code == 201, started.text
    run_id = started.json()["run_id"]
    wait_terminal(client, run_id)

    events = _collect_events(client, run_id, after_seq=0)
    types = [event.get("type") for event in events]
    assert "run.started" in types
    assert "agent.status" in types
    assert "message" in types
    assert "tool_call" in types
    assert "report.section" in types
    assert "stats" in types
    assert "run.completed" in types

    seqs = [event["seq"] for event in events if "seq" in event]
    assert seqs == sorted(seqs)
    assert len(seqs) == len(set(seqs))


def test_agent_statuses_do_not_fabricate_error(tree_client):
    _, client = tree_client
    started = client.post("/api/runs", json=_body())
    run_id = started.json()["run_id"]
    wait_terminal(client, run_id)
    events = _collect_events(client, run_id)
    statuses = {
        event["payload"]["status"]
        for event in events
        if event.get("type") == "agent.status"
    }
    assert statuses <= {"pending", "in_progress", "completed"}


def test_report_section_and_stats_payloads_are_present(tree_client):
    _, client = tree_client
    started = client.post("/api/runs", json=_body())
    run_id = started.json()["run_id"]
    wait_terminal(client, run_id)
    events = _collect_events(client, run_id)

    section = next(event for event in events if event.get("type") == "report.section")
    assert section["payload"]["section"] == "market_report"
    assert "content" in section["payload"]

    stats = next(event for event in events if event.get("type") == "stats")
    assert {
        "llm_calls",
        "tool_calls",
        "tokens_in",
        "tokens_out",
        "elapsed",
    } <= set(stats["payload"])


def test_reattach_from_last_sequence_does_not_replay_old_events(tree_client):
    _, client = tree_client
    started = client.post("/api/runs", json=_body())
    run_id = started.json()["run_id"]
    wait_terminal(client, run_id)

    snapshot = client.get(f"/api/runs/{run_id}").json()
    last_seq = snapshot["last_seq"]
    events = _collect_events(client, run_id, after_seq=last_seq)
    assert all(event.get("seq", 0) >= last_seq for event in events)


def test_snapshot_is_available_after_completion(tree_client):
    _, client = tree_client
    started = client.post("/api/runs", json=_body())
    run_id = started.json()["run_id"]
    terminal = wait_terminal(client, run_id)
    assert terminal["status"] == "completed"
    snapshot = client.get(f"/api/runs/{run_id}")
    assert snapshot.status_code == 200
    assert snapshot.json()["last_seq"] >= 1


def test_invalid_after_seq_is_rejected(tree_client):
    _, client = tree_client
    started = client.post("/api/runs", json=_body())
    run_id = started.json()["run_id"]
    bad = client.get(f"/api/runs/{run_id}/events", params={"after_seq": -1})
    assert bad.status_code in {400, 422}
    bad_type = client.get(
        f"/api/runs/{run_id}/events", params={"after_seq": "not-an-int"}
    )
    assert bad_type.status_code in {400, 422}
    wait_terminal(client, run_id)


def test_fake_run_completes_within_local_budget(tree_client):
    _, client = tree_client
    started_at = time.perf_counter()
    started = client.post("/api/runs", json=_body())
    terminal = wait_terminal(client, started.json()["run_id"])
    elapsed = time.perf_counter() - started_at
    assert terminal["status"] == "completed"
    # A fake runner has no provider latency; this is a sanity check, not a
    # substitute for the planned p95 event-latency measurement.
    assert elapsed < 1.0
