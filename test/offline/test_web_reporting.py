"""Run artifact writing, completion summary, and review semantics.

Covers REQ-WEB-008, REQ-WEB-009 and the REVIEW half of REQ-WEB-028.
"""

from __future__ import annotations

import uuid

import pytest

from test.offline.web_fixture_app import (
    FakeGraphRunner,
    build_fixture_tree,
    make_run_client,
    wait_terminal,
)

pytestmark = pytest.mark.unit


def _events(final_decision: str = "**Rating**: Buy\n\nBuy carefully."):
    return [
        {
            "type": "run.started",
            "payload": {"ticker": "AAPL", "trade_date": "2026-11-03"},
        },
        {
            "type": "message",
            "payload": {"timestamp": "12:00:00", "type": "Agent", "content": "working"},
        },
        {
            "type": "report.section",
            "payload": {
                "section": "market_report",
                "title": "Market",
                "content": "# Market\n\nAAPL market.",
            },
        },
        {
            "type": "report.section",
            "payload": {
                "section": "final_trade_decision",
                "title": "Portfolio",
                "content": final_decision,
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
                "elapsed": 0.1,
            },
        },
        {
            "type": "run.completed",
            "payload": {
                "signal": "REVIEW" if "Rating" not in final_decision else "Buy",
                "review": "Rating" not in final_decision,
                "wall_times": {"Market Analyst": 0.1},
                "artifact_ids": [],
            },
        },
    ]


def _body():
    return {
        "client_request_id": uuid.uuid4().hex,
        "ticker": "AAPL",
        "trade_date": "2026-11-03",
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
    return tree, make_run_client(tree, runner_factory=FakeGraphRunner(events=_events()))


def test_run_writes_message_log_sections_and_complete_report(tree_client):
    tree, client = tree_client
    started = client.post("/api/runs", json=_body())
    assert started.status_code == 201, started.text
    run_id = started.json()["run_id"]
    terminal = wait_terminal(client, run_id)
    assert terminal["status"] == "completed"

    run_dir = tree.results_dir / "web_runs" / run_id
    assert (run_dir / "message_tool.log").is_file()
    assert (run_dir / "reports" / "market_report.md").is_file()
    assert (run_dir / "reports" / "final_trade_decision.md").is_file()

    complete_reports = list((tree.results_dir / "reports").glob("AAPL_*/complete_report.md"))
    assert complete_reports, "complete report tree was not auto-saved"
    assert "AAPL" in complete_reports[-1].read_text(encoding="utf-8")


def test_run_does_not_write_full_states_log(tree_client):
    tree, client = tree_client
    started = client.post("/api/runs", json=_body())
    wait_terminal(client, started.json()["run_id"])
    state_logs = list((tree.results_dir / "web_runs").rglob("full_states_log_*.json"))
    assert state_logs == []


def test_completed_run_appears_in_history_and_downloads(tree_client):
    _, client = tree_client
    started = client.post("/api/runs", json=_body())
    run_id = started.json()["run_id"]
    wait_terminal(client, run_id)

    items = client.get("/api/history", params={"limit": 50}).json()["items"]
    item = next(
        item
        for item in items
        if item["source"] == "run" and item["ticker"] == "AAPL" and item["date"] == "2026-11-03"
    )
    detail = client.get(f"/api/history/{item['artifact_id']}")
    assert detail.status_code == 200, detail.text
    assert "market_report" in detail.json()["sections"]

    download = client.get(
        f"/api/history/{item['artifact_id']}/download", params={"kind": "complete"}
    )
    assert download.status_code == 200, download.text
    assert "AAPL" in download.text


def test_review_warning_is_reported_and_not_converted_to_hold(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy-secret-1234567890")
    tree = build_fixture_tree(tmp_path)
    client = make_run_client(
        tree, runner_factory=FakeGraphRunner(events=_events("No rating in this response."))
    )
    started = client.post("/api/runs", json=_body())
    terminal = wait_terminal(client, started.json()["run_id"])
    assert terminal["status"] == "completed"
    assert terminal["review"] is True
    assert terminal["signal"] == "REVIEW"


def test_wall_times_are_present_in_completion(tree_client):
    _, client = tree_client
    started = client.post("/api/runs", json=_body())
    terminal = wait_terminal(client, started.json()["run_id"])
    assert terminal["wall_times"]


def test_report_save_failure_keeps_analysis_result_with_warning(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy-secret-1234567890")
    tree = build_fixture_tree(tmp_path)
    client = make_run_client(tree, runner_factory=FakeGraphRunner(events=_events()))
    import tradingagents_web.runtime.artifacts_writer as writer

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(writer, "write_report_tree", boom)
    started = client.post("/api/runs", json=_body())
    terminal = wait_terminal(client, started.json()["run_id"])
    assert terminal["status"] == "completed"
    assert "report_save_failed" in terminal["warnings"]
