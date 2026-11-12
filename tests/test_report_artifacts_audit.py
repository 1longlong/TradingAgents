"""Milestone 3 audit-export regressions (2026-11-06 review finding 3).

The independent review reproduced an audit gap: ``data_quality_validation_results``
carried 5 evidence entries, but every exported ``evidence_manifest`` record had an
empty ``validation_results`` because the manifest did not export the separate
validation map. ``run_summary`` also omitted run_id, asset_type, snapshot ID,
per-record quality counts, tool calls, and separate input/output token counts.

These tests are deterministic and offline: they build structured state directly
and write/read the artifacts, checking persistence, association-by-evidence-ID,
honest unavailable values (never fabricated), redaction, and legacy safety.

Traceability: FR-DQG-005 (shared deterministic redacted artifacts), NFR-AUD-001
(auditability); supports INV-4 (acyclic JSON-safe serialization) and INV-6
(auditability of every decision).
"""

from __future__ import annotations

import json

from tradingagents.report_artifacts import (
    build_run_summary_section,
    write_report_artifacts,
)
from tradingagents.reporting import write_report_tree

_REDACTED = "[REDACTED]"

RECORDS = [
    {
        "evidence_id": "run:1",
        "run_id": "2026-05-13/COF",
        "asset_type": "stock",
        "category": "market",
        "metric_name": "close",
        "quality_status": "High",
        "observed_at": "2026-05-01",
        "value_raw": "190",
        "source_name": "yfinance",
        "source_ref": "yfinance",
    },
    {
        "evidence_id": "run:2",
        "run_id": "2026-05-13/COF",
        "asset_type": "stock",
        "category": "market",
        "metric_name": "volume",
        "quality_status": "Medium",
        "observed_at": "2026-05-01",
        "value_raw": "1000",
        "source_name": "yfinance",
        "source_ref": "yfinance",
    },
    {
        "evidence_id": "run:3",
        "run_id": "2026-05-13/COF",
        "asset_type": "stock",
        "category": "market",
        "metric_name": "open",
        "quality_status": "Low",
        "observed_at": "2026-05-01",
        "value_raw": "189",
        "source_name": "yfinance",
        "source_ref": "yfinance",
    },
]

VALIDATIONS = {
    "run:1": [{"evidence_id": "run:1", "validation_class": "format", "passed": True}],
    "run:2": [
        {"evidence_id": "run:2", "validation_class": "freshness", "passed": True},
        {"evidence_id": "run:2", "validation_class": "cross_source", "passed": False},
    ],
    # run:3 deliberately has no entry -> empty list, never another record's map.
}


def _state():
    return {
        "trade_date": "2026-05-13",
        "company_of_interest": "COF",
        "asset_type": "stock",
        "data_quality_verdict": "degraded",
        "data_quality_gate_decision": {
            "decision": "degraded",
            "decided_at": "2026-05-13T12:00:00Z",
            "policy_version": "2.0",
            "human_readable_reason": "Gate degraded.",
        },
        "data_quality_group_statuses": [],
        "data_quality_evidence_records": [dict(r) for r in RECORDS],
        "data_quality_validation_results": {k: [dict(v) for v in vs] for k, vs in VALIDATIONS.items()},
        "debate_usage": {"calls": 2, "tokens": 1500, "seconds": 12.0, "estimated": True},
        "debate_termination_decision": {
            "route": "summarize",
            "stop_reason": "no_new_evidence",
            "trace": [],
        },
        "investment_debate_state": {"round_metrics": [], "budget": {}},
    }


class TestManifestExportsValidations:
    def test_each_record_carries_its_own_validations(self, tmp_path):
        write_report_artifacts(_state(), "COF", tmp_path)
        manifest = json.loads((tmp_path / "0_quality" / "evidence_manifest.json").read_text())
        by_id = {r["evidence_id"]: r for r in manifest["evidence_records"]}
        assert len(by_id["run:1"]["validation_results"]) == 1
        assert len(by_id["run:2"]["validation_results"]) == 2
        # A record with no validation map entry gets an empty list, never a
        # sibling's results.
        assert by_id["run:3"]["validation_results"] == []
        # Every attached validation is associated by its own evidence_id.
        for record in manifest["evidence_records"]:
            for validation in record["validation_results"]:
                assert validation["evidence_id"] == record["evidence_id"]

    def test_separate_validation_map_is_exported(self, tmp_path):
        write_report_artifacts(_state(), "COF", tmp_path)
        manifest = json.loads((tmp_path / "0_quality" / "evidence_manifest.json").read_text())
        exported = manifest["validation_results_by_evidence_id"]
        assert set(exported) == {"run:1", "run:2"}
        assert len(exported["run:2"]) == 2

    def test_legacy_missing_validation_map_yields_empty(self, tmp_path):
        state = _state()
        state.pop("data_quality_validation_results")
        write_report_artifacts(state, "COF", tmp_path)
        manifest = json.loads((tmp_path / "0_quality" / "evidence_manifest.json").read_text())
        for record in manifest["evidence_records"]:
            assert record["validation_results"] == []
        assert manifest["validation_results_by_evidence_id"] == {}

    def test_legacy_embedded_validations_preserved_when_map_absent(self, tmp_path):
        # A legacy record carries its own validation_results and there is no
        # separate map: the embedded validations must be preserved, not wiped.
        state = _state()
        state.pop("data_quality_validation_results")
        state["data_quality_evidence_records"][0]["validation_results"] = [
            {"evidence_id": "run:1", "validation_class": "format", "passed": True},
            {"evidence_id": "run:1", "validation_class": "freshness", "passed": False},
        ]
        write_report_artifacts(state, "COF", tmp_path)
        manifest = json.loads((tmp_path / "0_quality" / "evidence_manifest.json").read_text())
        by_id = {r["evidence_id"]: r for r in manifest["evidence_records"]}
        assert len(by_id["run:1"]["validation_results"]) == 2
        assert {v["validation_class"] for v in by_id["run:1"]["validation_results"]} == {
            "format",
            "freshness",
        }
        # A record with neither a map entry nor embedded validations is [].
        assert by_id["run:2"]["validation_results"] == []

    def test_authoritative_map_overrides_embedded(self, tmp_path):
        # When the separate map has an entry, it is authoritative over a stale
        # embedded value on the record.
        state = _state()
        state["data_quality_evidence_records"][0]["validation_results"] = [
            {"evidence_id": "run:1", "validation_class": "stale", "passed": True}
        ]
        write_report_artifacts(state, "COF", tmp_path)
        manifest = json.loads((tmp_path / "0_quality" / "evidence_manifest.json").read_text())
        by_id = {r["evidence_id"]: r for r in manifest["evidence_records"]}
        classes = [v["validation_class"] for v in by_id["run:1"]["validation_results"]]
        assert classes == ["format"]  # from the authoritative map, not "stale"

    def test_embedded_legacy_single_dict_normalized(self, tmp_path):
        state = _state()
        state.pop("data_quality_validation_results")
        state["data_quality_evidence_records"][0]["validation_results"] = {
            "evidence_id": "run:1",
            "validation_class": "format",
            "passed": True,
        }
        write_report_artifacts(state, "COF", tmp_path)
        manifest = json.loads((tmp_path / "0_quality" / "evidence_manifest.json").read_text())
        by_id = {r["evidence_id"]: r for r in manifest["evidence_records"]}
        assert len(by_id["run:1"]["validation_results"]) == 1

    def test_map_order_is_authoritative_and_shuffle_invariant(self, tmp_path):
        # Two runs whose map validation results are ordered differently must
        # preserve their own authoritative order, but the exported artifact's
        # record and map key ordering must be deterministic (sorted IDs).
        state_a = _state()
        state_b = _state()
        state_b["data_quality_validation_results"] = {
            "run:2": list(reversed(VALIDATIONS["run:2"])),
            "run:1": list(VALIDATIONS["run:1"]),
        }
        a = tmp_path / "a"
        b = tmp_path / "b"
        write_report_artifacts(state_a, "COF", a)
        write_report_artifacts(state_b, "COF", b)
        ma = json.loads((a / "0_quality" / "evidence_manifest.json").read_text())
        mb = json.loads((b / "0_quality" / "evidence_manifest.json").read_text())
        # Stable record order and stable map key order across shuffles.
        assert [r["evidence_id"] for r in ma["evidence_records"]] == [
            r["evidence_id"] for r in mb["evidence_records"]
        ]
        assert list(ma["validation_results_by_evidence_id"]) == list(
            mb["validation_results_by_evidence_id"]
        )
        # Each run keeps its own authoritative per-ID validation order.
        assert [
            v["validation_class"] for v in ma["validation_results_by_evidence_id"]["run:2"]
        ] == ["freshness", "cross_source"]
        assert [
            v["validation_class"] for v in mb["validation_results_by_evidence_id"]["run:2"]
        ] == ["cross_source", "freshness"]

    def test_validation_redaction_applied(self, tmp_path):
        state = _state()
        state["data_quality_validation_results"]["run:1"][0]["detail"] = "sk-leaked123456789"
        write_report_artifacts(state, "COF", tmp_path)
        raw = (tmp_path / "0_quality" / "evidence_manifest.json").read_text()
        assert "leaked123456789" not in raw
        assert _REDACTED in raw


class TestExplicitEmptyMapEntryOverridesEmbedded:
    """Regression (2026-11-10): an explicit empty authoritative entry wins.

    ``_validation_map`` previously dropped a *present* but explicitly empty
    ``{evidence_id: []}`` entry, so ``_records_with_validations`` fell through to
    the record's stale embedded ``validation_results`` and preserved an old
    ``passed: True`` check the gate had actually cleared. A present map entry is
    authoritative even when it is empty; an ABSENT entry keeps the legacy
    embedded fallback.
    """

    def test_validation_map_keeps_explicit_empty_entry(self):
        from tradingagents.report_artifacts import _validation_map

        state = {"data_quality_validation_results": {"run:1": []}}
        assert _validation_map(state) == {"run:1": []}

    def test_records_helper_present_empty_overrides_embedded(self):
        from tradingagents.report_artifacts import (
            _records_with_validations,
            _validation_map,
        )

        state = {"data_quality_validation_results": {"run:1": []}}
        records = [
            {
                "evidence_id": "run:1",
                "validation_results": [
                    {"evidence_id": "run:1", "validation_class": "stale", "passed": True}
                ],
            }
        ]
        out = _records_with_validations(records, _validation_map(state))
        assert out[0]["validation_results"] == []

    def test_records_helper_absent_entry_keeps_embedded_fallback(self):
        from tradingagents.report_artifacts import (
            _records_with_validations,
            _validation_map,
        )

        # No entry at all for run:2 -> legacy embedded fallback preserved.
        state = {"data_quality_validation_results": {"run:1": []}}
        records = [
            {
                "evidence_id": "run:2",
                "validation_results": [
                    {"evidence_id": "run:2", "validation_class": "format", "passed": True}
                ],
            }
        ]
        out = _records_with_validations(records, _validation_map(state))
        assert [v["validation_class"] for v in out[0]["validation_results"]] == ["format"]

    def test_records_helper_empty_override_does_not_leak_across_ids(self):
        from tradingagents.report_artifacts import (
            _records_with_validations,
            _validation_map,
        )

        state = {
            "data_quality_validation_results": {
                "run:1": [],
                "run:2": [{"evidence_id": "run:2", "validation_class": "format", "passed": True}],
            }
        }
        records = [
            {
                "evidence_id": "run:1",
                "validation_results": [
                    {"evidence_id": "run:1", "validation_class": "stale", "passed": True}
                ],
            },
            {
                "evidence_id": "run:2",
                "validation_results": [
                    {"evidence_id": "run:2", "validation_class": "stale", "passed": True}
                ],
            },
        ]
        out = _records_with_validations(records, _validation_map(state))
        by_id = {r["evidence_id"]: r for r in out}
        assert by_id["run:1"]["validation_results"] == []
        assert [v["validation_class"] for v in by_id["run:2"]["validation_results"]] == [
            "format"
        ]

    def test_nonempty_map_still_overrides_embedded(self):
        from tradingagents.report_artifacts import (
            _records_with_validations,
            _validation_map,
        )

        state = {
            "data_quality_validation_results": {
                "run:1": [{"evidence_id": "run:1", "validation_class": "format", "passed": False}]
            }
        }
        records = [
            {
                "evidence_id": "run:1",
                "validation_results": [
                    {"evidence_id": "run:1", "validation_class": "stale", "passed": True}
                ],
            }
        ]
        out = _records_with_validations(records, _validation_map(state))
        assert [v["validation_class"] for v in out[0]["validation_results"]] == ["format"]
        assert out[0]["validation_results"][0]["passed"] is False

    def test_malformed_map_value_is_treated_as_empty_authoritative(self):
        from tradingagents.report_artifacts import (
            _records_with_validations,
            _validation_map,
        )

        # A present entry that is neither a dict nor a list cannot carry a
        # validation, so it is an authoritative "no validations" ([]), never a
        # fall-through to the stale embedded value.
        state = {"data_quality_validation_results": {"run:1": "garbage"}}
        map_ = _validation_map(state)
        assert map_ == {"run:1": []}
        records = [
            {
                "evidence_id": "run:1",
                "validation_results": [
                    {"evidence_id": "run:1", "validation_class": "stale", "passed": True}
                ],
            }
        ]
        out = _records_with_validations(records, map_)
        assert out[0]["validation_results"] == []

    def test_saved_manifest_present_empty_overrides_stale_embedded(self, tmp_path):
        # End-to-end through the saved artifact: the gate cleared run:1's
        # validations ({}), but the record still carries a stale embedded pass.
        state = _state()
        state["data_quality_validation_results"] = {"run:1": []}
        state["data_quality_evidence_records"][0]["validation_results"] = [
            {"evidence_id": "run:1", "validation_class": "stale", "passed": True}
        ]
        write_report_artifacts(state, "COF", tmp_path)
        manifest = json.loads(
            (tmp_path / "0_quality" / "evidence_manifest.json").read_text()
        )
        by_id = {r["evidence_id"]: r for r in manifest["evidence_records"]}
        assert by_id["run:1"]["validation_results"] == []
        # The separate map is exported verbatim with the explicit empty entry.
        assert manifest["validation_results_by_evidence_id"]["run:1"] == []

    def test_saved_manifest_order_and_redaction_preserved(self, tmp_path):
        # The empty-entry change must not reorder IDs or skip redaction.
        state = _state()
        state["data_quality_validation_results"]["run:3"] = []
        state["data_quality_validation_results"]["run:1"][0]["detail"] = "sk-leaked123456789"
        write_report_artifacts(state, "COF", tmp_path)
        manifest = json.loads(
            (tmp_path / "0_quality" / "evidence_manifest.json").read_text()
        )
        assert list(manifest["validation_results_by_evidence_id"]) == [
            "run:1",
            "run:2",
            "run:3",
        ]
        assert "leaked123456789" not in (
            tmp_path / "0_quality" / "evidence_manifest.json"
        ).read_text()


class TestRunSummaryAuditFields:
    def _summary(self, tmp_path, state=None):
        write_report_artifacts(state or _state(), "COF", tmp_path)
        return json.loads((tmp_path / "run_summary.json").read_text())

    def test_identity_fields_present(self, tmp_path):
        summary = self._summary(tmp_path)
        assert summary["run_id"] == "2026-05-13/COF"
        assert summary["asset_type"] == "stock"
        assert "snapshot_id" in summary  # explicit key, null when unavailable

    def test_quality_counts(self, tmp_path):
        summary = self._summary(tmp_path)
        counts = summary["quality_counts"]
        assert counts["High"] == 1
        assert counts["Medium"] == 1
        assert counts["Low"] == 1
        assert counts["Blocked"] == 0

    def test_usage_provenance_does_not_conflate_debate_with_total(self, tmp_path):
        summary = self._summary(tmp_path)
        prov = summary["usage_provenance"]
        assert prov["debate_calls"] == 2
        assert prov["debate_tokens"] == 1500
        assert prov["estimated"] is True
        # Not tracked -> explicit None, never fabricated or conflated.
        assert prov["total_run_calls"] is None
        assert prov["tool_calls"] is None
        assert prov["input_tokens"] is None
        assert prov["output_tokens"] is None
        assert "debate calls" in prov["unavailable_reason"]

    def test_identity_null_when_absent(self, tmp_path):
        state = _state()
        state["data_quality_evidence_records"] = []
        summary = self._summary(tmp_path, state)
        assert summary["run_id"] is None
        assert summary["snapshot_id"] is None
        # Absent is not ambiguous.
        assert summary["identity_ambiguous"] == {
            "run_id": False,
            "asset_type": False,
            "snapshot_id": False,
        }

    def test_disagreeing_run_id_is_ambiguous_not_first(self, tmp_path):
        state = _state()
        state["data_quality_evidence_records"][2]["run_id"] = "2026-05-14/COF"
        summary = self._summary(tmp_path, state)
        # Do not silently choose a first identity; mark it unavailable.
        assert summary["run_id"] is None
        assert summary["identity_ambiguous"]["run_id"] is True

    def test_disagreeing_snapshot_id_is_ambiguous(self, tmp_path):
        state = _state()
        state["data_quality_evidence_records"][0]["snapshot_id"] = "snap-A"
        state["data_quality_evidence_records"][1]["snapshot_id"] = "snap-B"
        summary = self._summary(tmp_path, state)
        assert summary["snapshot_id"] is None
        assert summary["identity_ambiguous"]["snapshot_id"] is True

    def test_agreeing_snapshot_id_is_reported(self, tmp_path):
        state = _state()
        for r in state["data_quality_evidence_records"]:
            r["snapshot_id"] = "snap-A"
        summary = self._summary(tmp_path, state)
        assert summary["snapshot_id"] == "snap-A"
        assert summary["identity_ambiguous"]["snapshot_id"] is False

    def test_default_snapshot_id_is_null(self, tmp_path):
        # The adapter does not mint a snapshot_id today; null is expected.
        summary = self._summary(tmp_path)
        assert summary["snapshot_id"] is None
        assert summary["identity_ambiguous"]["snapshot_id"] is False

    def test_run_summary_section_notes_debate_only(self):
        section = build_run_summary_section(
            _state(), "COF", {"evidence_manifest": "0_quality/evidence_manifest.json"}
        )
        assert "Run id: 2026-05-13/COF" in section
        assert "not total-run calls" in section
        # No snapshot_id on the records -> explicit "unavailable", not invented.
        assert "Snapshot id: unavailable" in section


class TestReportPersistenceRoundtrip:
    def test_json_artifacts_roundtrip_and_are_deterministic(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        write_report_artifacts(_state(), "COF", a)
        write_report_artifacts(_state(), "COF", b)
        for name in (
            "0_quality/evidence_manifest.json",
            "2_research/debate_trace.json",
            "run_summary.json",
        ):
            text_a = (a / name).read_text()
            text_b = (b / name).read_text()
            assert text_a == text_b, f"{name} must be byte-deterministic"
            json.loads(text_a)  # valid JSON roundtrip

    def test_report_tree_persists_audit_manifest(self, tmp_path):
        write_report_tree(_state(), "COF", tmp_path)
        manifest = json.loads((tmp_path / "0_quality" / "evidence_manifest.json").read_text())
        assert manifest["validation_results_by_evidence_id"]["run:2"]
        summary = json.loads((tmp_path / "run_summary.json").read_text())
        assert summary["quality_counts"]["High"] == 1
        assert "usage_provenance" in summary

    def test_no_analyst_prose_in_manifest(self, tmp_path):
        state = _state()
        state["market_report"] = "SECRET CHAIN OF THOUGHT reasoning"
        write_report_artifacts(state, "COF", tmp_path)
        raw = (tmp_path / "0_quality" / "evidence_manifest.json").read_text()
        assert "CHAIN OF THOUGHT" not in raw


class TestMeasuredProvenanceAndParticipation:
    """FR-DQG-005 / NFR-AUD-001 / INV-6: measured provenance and participation
    truth surfaced in the report artifacts (DEBT-021/033 repair)."""

    def _summary(self, tmp_path, state=None):
        write_report_artifacts(state or _state(), "COF", tmp_path)
        return json.loads((tmp_path / "run_summary.json").read_text())

    def test_measured_provenance_surfaced(self, tmp_path):
        state = _state()
        state["debate_usage"] = {
            "calls": 2,
            "tokens": 300,
            "seconds": 4.5,
            "estimated": False,
            "provenance": {
                "tokens": "provider",
                "seconds": "measured",
                "input_tokens": "provider",
                "output_tokens": "provider",
            },
            "clock": "measured",
            "failed_calls": 0,
            "transport_attempts": None,
            "input_tokens": 200,
            "output_tokens": 100,
        }
        prov = self._summary(tmp_path, state)["usage_provenance"]
        assert prov["tokens_source"] == "provider"
        assert prov["seconds_source"] == "measured"
        assert prov["clock"] == "measured"
        assert prov["input_tokens"] == 200
        assert prov["output_tokens"] == 100
        assert prov["estimated"] is False

    def test_partial_split_reported_null(self, tmp_path):
        state = _state()
        state["debate_usage"] = {
            "calls": 1,
            "tokens": 150,
            "seconds": 1.0,
            "estimated": True,
            "provenance": {"tokens": "estimated", "seconds": "measured", "tokens_partial": True},
            "input_tokens": 100,
            "input_tokens_partial": True,
        }
        prov = self._summary(tmp_path, state)["usage_provenance"]
        # A partial split is never presented as a complete provider total.
        assert prov["input_tokens"] is None
        assert prov["input_tokens_partial"] is True

    def test_participation_reported_in_summary_and_trace(self, tmp_path):
        state = _state()
        state["investment_debate_state"] = {
            "round_metrics": [],
            "budget": {},
            "turns": [{"speaker": "Bull", "content": "b"}],
            "bull_history": "b",
            "bear_history": "",
            "history": "b",
        }
        state["debate_termination_decision"] = {
            "route": "summarize",
            "stop_reason": "budget_exhausted",
            "refused_speaker": "Bear",
            "trace": [],
        }
        write_report_artifacts(state, "COF", tmp_path)
        summary = json.loads((tmp_path / "run_summary.json").read_text())
        assert summary["debate_stop_reason"] == "budget_exhausted"
        trace = json.loads((tmp_path / "2_research" / "debate_trace.json").read_text())
        part = trace["participation"]
        assert part["status"] == "one"
        assert part["executed_speakers"] == ["Bull"]
        assert "Bear" in part["skipped_speakers"]
        # run_summary.json must ALSO carry the same top-level-aware participation
        # (not only the trace), and the Markdown summary must state it too.
        sp = summary["participation"]
        assert sp["status"] == "one"
        assert sp["executed_speakers"] == ["Bull"]
        assert "Bear" in sp["skipped_speakers"]
        assert sp["skip_reason"]
        md = build_run_summary_section(state, "COF", {})
        assert "Debate participation: status=one" in md
        assert "skip_reason=" in md

    def test_conflict_originals_survive_report_json(self, tmp_path):
        state = _state()
        state["debate_usage"] = {
            "calls": 1,
            "tokens": 112,
            "seconds": 1.0,
            "estimated": False,
            "provenance": {
                "tokens": "derived_conflicted",
                "seconds": "measured",
                "tokens_conflict": True,
                "tokens_conflict_originals": [
                    {"source": "usage_metadata", "input_tokens": 100, "output_tokens": 10, "total_tokens": 110, "call_index": 0},
                    {"source": "response_metadata.token_usage", "input_tokens": 101, "output_tokens": 11, "total_tokens": 112, "call_index": 0},
                ],
            },
            "clock": "measured",
            "failed_calls": 0,
            "transport_attempts": None,
        }
        write_report_artifacts(state, "COF", tmp_path)
        trace = json.loads((tmp_path / "2_research" / "debate_trace.json").read_text())
        prov = trace["usage_provenance"]
        assert prov["tokens_conflict"] is True
        # Source-labelled originals remain in the persisted trace usage dict.
        stored = trace["usage"]["provenance"]["tokens_conflict_originals"]
        by_source = {o["source"]: o for o in stored}
        assert by_source["usage_metadata"]["total_tokens"] == 110
        assert by_source["response_metadata.token_usage"]["total_tokens"] == 112
