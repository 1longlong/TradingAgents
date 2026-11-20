"""REQ-WEB-008/009/013/024, ADR-002, INV-WEB-003/004/005: safe audit projections."""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path

import pytest

from test.offline.web_fixture_app import (
    FakeGraphRunner,
    build_fixture_tree,
    make_run_client,
    wait_terminal,
)
from tradingagents.report_artifacts import write_report_artifacts
from tradingagents_web.artifacts.audit import AUDIT_FILES, audit_view
from tradingagents_web.artifacts.downloads import ArtifactUnavailable
from tradingagents_web.artifacts.index import Artifact
from tradingagents_web.runtime.artifacts_writer import RunArtifactWriter
from tradingagents_web.settings import WebSettings

pytestmark = pytest.mark.unit


def state():
    return {
        "trade_date": "2026-11-01",
        "data_quality_verdict": "degraded",
        "data_quality_gate_decision": {
            "decision": "degraded",
            "policy_version": "1.0",
            "human_readable_reason": "Optional coverage is insufficient.",
        },
        "data_quality_evidence_records": [
            {
                "evidence_id": "price-1",
                "category": "market",
                "metric_name": "close",
                "observed_at": "2026-11-01",
                "quality_status": "Medium",
                "source_name": "yfinance",
                "value_raw": "100",
                "unit_normalized": "USD",
            }
        ],
        "data_quality_validation_results": {"price-1": []},
    }


def setup(tmp_path, **settings):
    tree = build_fixture_tree(tmp_path)
    client = make_run_client(tree, runner_factory=FakeGraphRunner(), **settings)
    identity = next(
        item["artifact_id"]
        for item in client.get("/api/history").json()["items"]
        if item["ticker"] == "NVDA" and item["source"] == "run"
    )
    return tree, client, f"/api/history/{identity}/audit"


def test_core_families_have_shared_preview_and_download(tmp_path):
    tree, client, url = setup(tmp_path)
    write_report_artifacts(state(), "NVDA", tree.run_dir)
    response = client.get(url)
    assert response.status_code == 200
    data = response.json()
    assert data["artifact_availability"] == "complete"
    assert data["data"]["evidence_manifest"]["verdict"] == "degraded"
    assert data["data"]["evidence_manifest"]["evidence_records"][0]["validation_results"] == []
    assert data["data"]["run_summary"]["whole_run_usage"]["completeness"] == "unknown"
    for kind, filename in AUDIT_FILES.items():
        preview = client.get(f"{url}/artifacts/{kind}")
        download = client.get(f"{url}/artifacts/{kind}?download=true")
        assert preview.status_code == download.status_code == 200
        assert preview.content == download.content
        assert Path(filename).name in download.headers["content-disposition"]
    assert client.get(url.replace("/audit", "/download?kind=complete")).status_code == 404


def test_legacy_partial_and_invalid_are_not_successful_empty_data(tmp_path):
    tree, client, url = setup(tmp_path)
    data = client.get(url).json()
    assert data["artifact_availability"] == "absent" and data["available"] is False
    write_report_artifacts(state(), "NVDA", tree.run_dir)
    (tree.run_dir / AUDIT_FILES["gate_summary"]).unlink()
    (tree.run_dir / AUDIT_FILES["debate_trace"]).write_text('{"route":1,"route":2}')
    data = client.get(url).json()
    assert data["artifact_availability"] == "partial"
    assert {item["kind"]: item["status"] for item in data["artifacts"]} == {
        "evidence_manifest": "available",
        "gate_summary": "missing",
        "debate_trace": "invalid",
        "run_summary": "available",
    }
    assert "debate_trace" not in data["data"]
    assert client.get(url + "/artifacts/debate_trace").status_code == 422


@pytest.mark.parametrize(
    "content",
    ["[]", "{bad", '{"cost":NaN}', '{"cost":1e999}', '{"x":' + "[" * 70 + "0" + "]" * 70 + "}"],
)
def test_invalid_json_and_excessive_nesting_are_explicit(tmp_path, content):
    tree, client, url = setup(tmp_path)
    (tree.run_dir / "run_summary.json").write_text(content)
    response = client.get(url)
    assert response.status_code == 200
    assert response.json()["artifact_availability"] == "unavailable"
    assert client.get(url + "/artifacts/run_summary").status_code == 422


def test_invalid_utf8_is_not_replaced_with_trusted_text(tmp_path):
    tree, client, url = setup(tmp_path)
    (tree.run_dir / "run_summary.json").write_bytes(b"\xff")
    assert client.get(url).json()["artifact_availability"] == "unavailable"
    assert client.get(url + "/artifacts/run_summary").status_code == 422


def test_limits_apply_to_bundle_and_download(tmp_path):
    tree, client, url = setup(tmp_path, max_report_bytes=1000)
    (tree.run_dir / "run_summary.json").write_text(json.dumps({"value": "x" * 1001}))
    assert client.get(url).status_code == 413
    assert client.get(url + "/artifacts/run_summary?download=true").status_code == 413


def test_redaction_covers_exact_secrets_urls_and_server_locations(tmp_path, monkeypatch):
    tree, client, url = setup(tmp_path)
    secret = "unit-private-value-123456"
    monkeypatch.setenv("AUDIT_API_KEY", secret)
    raw = {
        "note": f"{secret}; token=testing123456789; see /tmp/private/audit.json",
        "source_url": "https://user:password@example.test/data?token=private#fragment",
        "location": "C:\\private\\record.json",
        "config": {"api_key": secret},
        "report_paths": {
            "evidence_manifest": "0_quality/evidence_manifest.json",
            "escape": "/Users/private/file",
        },
    }
    (tree.run_dir / "run_summary.json").write_text(json.dumps(raw))
    for response in (client.get(url), client.get(url + "/artifacts/run_summary?download=true")):
        assert response.status_code == 200
        assert secret not in response.text and "/tmp/private" not in response.text
        assert "C:\\\\private" not in response.text and "/Users/private" not in response.text
        assert "user:password" not in response.text and "token=private" not in response.text
        assert "testing123456789" not in response.text
    projected = client.get(url).json()["data"]["run_summary"]
    assert "config" not in projected
    assert projected["report_paths"] == {"evidence_manifest": "0_quality/evidence_manifest.json"}


def test_symlink_family_never_reads_its_target(tmp_path):
    tree, client, url = setup(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text('{"private":"do-not-leak-this"}')
    (tree.run_dir / "run_summary.json").symlink_to(outside)
    response = client.get(url + "/artifacts/run_summary")
    assert response.status_code == 404
    assert "do-not-leak-this" not in response.text


def test_directory_symlinks_and_nonanalysis_roots_are_denied(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "run_summary.json").write_text('{"value":"private"}')
    linked = results / "linked"
    linked.symlink_to(outside, target_is_directory=True)
    settings = WebSettings(
        results_dir=results, memory_log_path=tmp_path / "memory", data_cache_dir=tmp_path / "cache"
    )
    for root in (linked, outside):
        artifact = Artifact(
            "a" * 16, "run", root, "NVDA", "2026-11-01", "completed", "Hold", False, 0, "Run"
        )
        with pytest.raises(ArtifactUnavailable):
            audit_view(artifact, settings)


def test_unknown_ids_families_and_other_sources_are_not_paths(tmp_path):
    _, client, url = setup(tmp_path)
    for path in (
        "/api/history/not-an-id/audit",
        "/api/runs/not-a-run/audit",
        url + "/artifacts/run.json",
        url + "/artifacts/..%2F..%2Fprivate",
    ):
        assert client.get(path).status_code in {404, 400}
    decision = next(
        item["artifact_id"]
        for item in client.get("/api/history").json()["items"]
        if item["source"] == "decision"
    )
    assert client.get(f"/api/history/{decision}/audit").status_code == 404


def test_new_web_runs_retain_audit_families_and_only_safe_metadata(tmp_path):
    tree, client, _ = setup(tmp_path)
    started = client.post(
        "/api/runs",
        json={
            "client_request_id": uuid.uuid4().hex,
            "ticker": "NVDA",
            "trade_date": "2026-11-01",
            "analysts": ["market"],
            "research_depth": 3,
            "output_language": "English",
            "llm_provider": "deepseek",
            "quick_think_llm": "deepseek-flash",
            "deep_think_llm": "deepseek-flash",
        },
    )
    assert started.status_code == 201
    run = wait_terminal(client, started.json()["run_id"])
    assert run["status"] == "completed" and "report_save_failed" not in run["warnings"]
    result = client.get(f"/api/runs/{run['run_id']}/audit")
    assert result.status_code == 200 and result.json()["artifact_availability"] == "complete"
    detail = client.get(f"/api/history/{run['artifact_id']}").json()
    assert detail["metadata"]["llm_provider"] == "deepseek"
    assert detail["metadata"]["research_depth"] == 3
    assert detail["metadata"]["analysts"] == ["market"]
    assert run["output_language"] == "English"
    writer = RunArtifactWriter(
        tree.results_dir,
        "ABC",
        "2026-11-01",
        "r_123456789abc",
        metadata={
            "llm_provider": "deepseek",
            "backend_url": "https://private",
            "portfolio_json": "private",
        },
    )
    metadata = json.loads((writer.run_dir / "run.json").read_text())["metadata"]
    assert metadata == {"llm_provider": "deepseek"}


def test_audit_cutoff_uses_recorded_target_and_inconsistency_fails_closed(tmp_path):
    tree, client, url = setup(tmp_path)
    sample = state()
    sample["data_quality_evidence_records"].append(
        {
            **sample["data_quality_evidence_records"][0],
            "evidence_id": "future-1",
            "observed_at": "2026-11-02",
        }
    )
    write_report_artifacts(sample, "NVDA", tree.run_dir)
    data = client.get(url).json()
    assert data["trade_date"] == "2026-11-01"
    assert data["eligible_evidence_ids"] == ["price-1"]
    summary = tree.run_dir / "run_summary.json"
    payload = json.loads(summary.read_text())
    payload.update(ticker="MSFT", gate_verdict="blocked", trade_date=42)
    summary.write_text(json.dumps(payload))
    data = client.get(url).json()
    assert data["consistency"]["status"] == "inconsistent"
    assert set(data["consistency"]["issues"]) == {
        "ticker_mismatch",
        "gate_verdict_mismatch",
        "invalid_trade_date",
    }
    assert data["eligible_evidence_ids"] == []


def test_duplicate_evidence_does_not_silently_select_last_status(tmp_path):
    tree, client, url = setup(tmp_path)
    path = tree.run_dir / "0_quality" / "evidence_manifest.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps(
            {
                "evidence_records": [
                    {
                        "evidence_id": "duplicate",
                        "quality_status": "Low",
                        "observed_at": "2026-11-01",
                    },
                    {
                        "evidence_id": "duplicate",
                        "quality_status": "High",
                        "observed_at": "2026-11-01",
                    },
                ]
            }
        )
    )
    data = client.get(url).json()
    assert "duplicate_evidence_id" in data["consistency"]["issues"]
    assert data["eligible_evidence_ids"] == []


def test_saved_folder_date_never_becomes_an_invented_analysis_cutoff(tmp_path):
    tree, client, _ = setup(tmp_path)
    identity = next(
        item["artifact_id"]
        for item in client.get("/api/history").json()["items"]
        if item["source"] == "saved" and item["ticker"] == "AAPL"
    )
    sample = state()
    sample.pop("trade_date")
    write_report_artifacts(sample, "AAPL", tree.saved_dir)
    data = client.get(f"/api/history/{identity}/audit").json()
    assert data["recorded_date"] == "2026-11-01"
    assert data["trade_date"] is None and data["eligible_evidence_ids"] == []
    assert "invalid_trade_date" in data["consistency"]["issues"]


def test_writer_retains_only_structured_origin_attempt_and_conflict_descriptors(tmp_path):
    writer = RunArtifactWriter(tmp_path / "results", "NVDA", "2026-11-01", "r_123456789abc")
    sample = state()
    sample.update(
        data_quality_origin_metadata={
            "price-1": {"availability_date": "2026-11-01", "raw_arguments": "private-origin"}
        },
        data_quality_source_attempts=[
            {"source": "yfinance", "result_status": "success", "arguments": "private-attempt"}
        ],
        investment_debate_state={
            "conflicts": [
                {
                    "conflict_id": "c-1",
                    "kind": "numeric",
                    "status": "open",
                    "bull_claim": "private-claim",
                    "topic": "private-topic",
                    "evidence_ids": ["price-1"],
                }
            ]
        },
    )
    writer.complete(sample)
    manifest = json.loads((writer.run_dir / AUDIT_FILES["evidence_manifest"]).read_text())
    trace = json.loads((writer.run_dir / AUDIT_FILES["debate_trace"]).read_text())
    assert manifest["web_context"]["data_quality_origin_metadata"]["price-1"] == {
        "availability_date": "2026-11-01"
    }
    assert manifest["web_context"]["data_quality_source_attempts"] == [
        {"source": "yfinance", "result_status": "success"}
    ]
    assert trace["web_context"]["conflicts"] == [
        {"conflict_id": "c-1", "kind": "numeric", "status": "open", "evidence_ids": ["price-1"]}
    ]
    assert "private-" not in json.dumps([manifest, trace])


def test_active_run_audit_reports_runtime_lifecycle_without_inventing_final_families(tmp_path):
    started = threading.Event()

    class WaitingRunner:
        def run(self, request, emit, cancel_event):
            emit({"type": "run.started", "payload": {}})
            started.set()
            cancel_event.wait(3)

    tree = build_fixture_tree(tmp_path)
    client = make_run_client(tree, runner_factory=WaitingRunner())
    response = client.post(
        "/api/runs",
        json={
            "client_request_id": uuid.uuid4().hex,
            "ticker": "NVDA",
            "trade_date": "2026-11-01",
            "analysts": ["market"],
            "llm_provider": "deepseek",
            "quick_think_llm": "deepseek-flash",
            "deep_think_llm": "deepseek-flash",
        },
    )
    assert response.status_code == 201 and started.wait(2)
    run_id = response.json()["run_id"]
    try:
        audit = client.get(f"/api/runs/{run_id}/audit").json()
        assert audit["status"] == "running"
        assert audit["available"] is False and audit["data"] == {}
        assert audit["artifact_availability"] == "absent"
    finally:
        client.post(f"/api/runs/{run_id}/cancel")
        assert wait_terminal(client, run_id)["status"] == "cancelled"
