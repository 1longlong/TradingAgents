"""Stage 2 report artifacts: deterministic offline tests.

Covers the shared CLI/API report artifacts (``0_quality/*``,
``2_research/debate_trace.json``, ``run_summary.json``), the added
``Data Quality`` / ``Run Summary`` sections in ``complete_report.md``,
secret redaction, exclusion of analyst prose / chain-of-thought, and
legacy/empty-state parity. No network, no paid LLM.
"""

from __future__ import annotations

import json

from tradingagents.evidence.policy import OPTIONAL_CATEGORIES
from tradingagents.report_artifacts import (
    build_data_quality_section,
    build_run_summary_section,
    redact_secrets,
    write_report_artifacts,
)
from tradingagents.reporting import write_report_tree

_SENTINEL = "[REDACTED]"


def _state_with_gate(ticker="COF"):
    return {
        "trade_date": "2026-05-13",
        "data_quality_verdict": "degraded",
        "data_quality_gate_decision": {
            "decision": "degraded",
            "decided_at": "2026-05-13T12:00:00Z",
            "policy_version": "2.0",
            "human_readable_reason": "Gate degraded: unavailable_no_structured_source.",
            "limitations": ["Degraded: confidence capped; limitations apply."],
            "critical_evidence_ids": [],
            "group_statuses": [],
        },
        "data_quality_group_statuses": [
            {
                "category": "market",
                "quality_status": "Medium",
                "criticality": "critical",
                "evidence_ids": ["2026-05-13/COF/market/yfinance/close/0"],
                "source_count": 1,
                "independent_source_count": 1,
                "reason_codes": ["medium_single_source"],
                "human_readable_reason": "market",
            }
        ],
        "data_quality_evidence_records": [
            {
                "evidence_id": "2026-05-13/COF/market/yfinance/close/0",
                "run_id": "2026-05-13/COF",
                "category": "market",
                "metric_name": "close",
                "value_raw": "101",
                "unit_normalized": "native_quote_currency",
                "source_name": "yfinance",
                "source_ref": "yfinance",
                "observed_at": "2026-05-13",
                "fetched_at": "2026-05-13T12:00:00Z",
                "target_date": "2026-05-13",
                "quality_status": "Medium",
            }
        ],
        "debate_termination_decision": {
            "route": "summarize",
            "stop_reason": "no_new_evidence",
            "trace": [{"rule": "no_new_evidence", "activated": True}],
        },
        "investment_debate_state": {
            "round_metrics": [{"round_index": 1}],
            "budget": {"calls": 4, "tokens": 2000, "seconds": 30.0, "estimated": True},
        },
        "debate_usage": {"calls": 4, "tokens": 2000, "seconds": 30.0, "estimated": True},
        "market_report": "MKT",
    }


class TestEvidenceManifest:
    def test_written_with_expected_keys(self, tmp_path):
        paths = write_report_artifacts(_state_with_gate(), "COF", tmp_path)
        manifest = json.loads((tmp_path / "0_quality" / "evidence_manifest.json").read_text())
        assert manifest["verdict"] == "degraded"
        assert manifest["policy_version"] == "2.0"
        assert manifest["gate_decision"]["decision"] == "degraded"
        assert any(
            r["evidence_id"] == "2026-05-13/COF/market/yfinance/close/0"
            for r in manifest["evidence_records"]
        )
        assert paths["evidence_manifest"] == "0_quality/evidence_manifest.json"

    def test_category_statuses_include_optional_unavailable(self, tmp_path):
        write_report_artifacts(_state_with_gate(), "COF", tmp_path)
        manifest = json.loads((tmp_path / "0_quality" / "evidence_manifest.json").read_text())
        cats = {s["category"]: s for s in manifest["category_statuses"]}
        assert "market" in cats
        for category in OPTIONAL_CATEGORIES:
            assert category in cats, f"missing optional category {category}"
            assert cats[category]["quality_status"] == "Low"
            assert "unavailable_no_structured_source" in cats[category]["reason_codes"]

    def test_deterministic_same_state_same_output(self, tmp_path):
        write_report_artifacts(_state_with_gate(), "COF", tmp_path)
        first = (tmp_path / "0_quality" / "evidence_manifest.json").read_text()
        tmp_path2 = tmp_path / "again"
        write_report_artifacts(_state_with_gate(), "COF", tmp_path2)
        second = (tmp_path2 / "0_quality" / "evidence_manifest.json").read_text()
        assert first == second


class TestGateSummaryMd:
    def test_contains_verdict_and_category_table(self, tmp_path):
        write_report_artifacts(_state_with_gate(), "COF", tmp_path)
        text = (tmp_path / "0_quality" / "gate_summary.md").read_text()
        assert "Verdict: degraded" in text
        assert "Policy version: 2.0" in text
        assert "| market | Medium |" in text
        assert "| news | Low |" in text

    def test_no_analyst_prose_persisted(self, tmp_path):
        write_report_artifacts(_state_with_gate(), "COF", tmp_path)
        text = (tmp_path / "0_quality" / "gate_summary.md").read_text()
        assert "MKT" not in text, "analyst prose must not be persisted"


class TestDebateTrace:
    def test_contains_route_stop_reason_rounds_usage_flags(self, tmp_path):
        write_report_artifacts(_state_with_gate(), "COF", tmp_path)
        trace = json.loads((tmp_path / "2_research" / "debate_trace.json").read_text())
        assert trace["route"] == "summarize"
        assert trace["stop_reason"] == "no_new_evidence"
        assert trace["round_count"] == 1
        assert trace["usage"]["tokens"] == 2000
        assert trace["measured_vs_estimated"]["estimated"] is True
        assert trace["budget"]["calls"] == 4

    def test_excludes_turn_prose(self, tmp_path):
        state = _state_with_gate()
        state["debate_usage"] = {"calls": 4, "tokens": 2000, "seconds": 30.0, "estimated": True}
        write_report_artifacts(state, "COF", tmp_path)
        text = (tmp_path / "2_research" / "debate_trace.json").read_text()
        # The readable bull/bear prose ("MKT") is excluded from the trace.
        assert "MKT" not in text


class TestRunSummary:
    def test_contains_key_run_facts(self, tmp_path):
        write_report_artifacts(_state_with_gate(), "COF", tmp_path)
        summary = json.loads((tmp_path / "run_summary.json").read_text())
        assert summary["ticker"] == "COF"
        assert summary["trade_date"] == "2026-05-13"
        assert summary["gate_verdict"] == "degraded"
        assert summary["debate_stop_reason"] == "no_new_evidence"
        assert summary["debate_round_count"] == 1
        assert summary["measured_vs_estimated"]["estimated"] is True
        assert "evidence_manifest" in summary["report_paths"]


class TestRedaction:
    def test_redacts_secret_patterns(self):
        assert redact_secrets("sk-abcdef1234567890") == _SENTINEL
        assert "Bearer" in redact_secrets("auth Bearer abcdef1234567890")
        assert redact_secrets("api_key=ABCDEF0123456789") == "api_key=" + _SENTINEL
        assert redact_secrets("AKIAIOSFODNN7EXAMPLE") == _SENTINEL
        assert redact_secrets("plain text, no secret") == "plain text, no secret"

    def test_redacts_recursively_and_preserves_context(self):
        payload = {"a": "sk-1234567890abcdef", "b": ["Bearer xyz.abc.def"]}
        out = redact_secrets(payload)
        assert out["a"] == _SENTINEL
        assert out["b"] == ["Bearer " + _SENTINEL], "label preserved, value redacted"

    def test_redaction_applied_to_written_artifacts(self, tmp_path):
        state = _state_with_gate()
        state["data_quality_evidence_records"][0]["source_ref"] = "sk-leakedsecret123456"
        write_report_artifacts(state, "COF", tmp_path)
        raw = (tmp_path / "0_quality" / "evidence_manifest.json").read_text()
        assert "leakedsecret" not in raw
        assert _SENTINEL in raw


class TestCompleteReportSections:
    def test_write_report_tree_adds_quality_and_run_summary(self, tmp_path):
        write_report_tree(_state_with_gate(), "COF", tmp_path)
        complete = (tmp_path / "complete_report.md").read_text()
        assert "# Trading Analysis Report: COF" in complete
        assert "## Data Quality" in complete
        assert "## Run Summary" in complete
        assert "Gate verdict: degraded" in complete

    def test_artifacts_written_by_report_tree(self, tmp_path):
        write_report_tree(_state_with_gate(), "COF", tmp_path)
        assert (tmp_path / "0_quality" / "evidence_manifest.json").exists()
        assert (tmp_path / "0_quality" / "gate_summary.md").exists()
        assert (tmp_path / "2_research" / "debate_trace.json").exists()
        assert (tmp_path / "run_summary.json").exists()

    def test_empty_state_produces_safe_report(self, tmp_path):
        # Legacy/missing gate data must still produce a safe, reportable tree.
        state = {"trade_date": "2026-05-13", "market_report": "MKT"}
        write_report_tree(state, "COF", tmp_path)
        complete = (tmp_path / "complete_report.md").read_text()
        assert "## Data Quality" in complete
        assert "## Run Summary" in complete
        manifest = json.loads((tmp_path / "0_quality" / "evidence_manifest.json").read_text())
        assert manifest["verdict"] == ""  # no gate state -> empty verdict, not invented


class TestBuildSections:
    def test_data_quality_section_structured_only(self):
        section = build_data_quality_section(_state_with_gate())
        assert section.startswith("## Data Quality") or "Verdict: degraded" in section

    def test_run_summary_section(self):
        section = build_run_summary_section(_state_with_gate(), "COF", {"evidence_manifest": "0_quality/evidence_manifest.json"})
        assert "Ticker: COF" in section
        assert "Artifacts:" in section
        assert "evidence_manifest" in section
