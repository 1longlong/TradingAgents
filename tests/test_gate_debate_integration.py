"""Real gate -> manifest -> researcher -> evaluator -> report integration.

Reproduces and locks the 2026-11-06 review finding 2: the multi-category gate
engine validated and aggregated the market category correctly, but serialized
the *provisional* adapter records (``quality_status=Low``,
``quality_reasons=['unvalidated']``) because the aggregator's per-record status
map was discarded. As a result a normal gate with a Medium market group produced
an empty ``EvidenceManifest.valid_ids``, an empty citation allowlist, and a
debate that terminated after round 1 with ``new_valid_evidence_count=0`` even
when a researcher cited and linked a real gate evidence ID.

These tests use the *actual* ``create_data_quality_gate_node`` and the actual
manifest/researcher/evaluator/report code paths with the deterministic fixed
dataframe and the explicit structured optional-category contract. No network, no
paid LLM. They prove per-record quality is applied and that genuinely
Low/Blocked/future evidence still never counts.

Traceability: FR-DQG-004 (multi-category gate engine); exercises the
manifest/allowlist boundary of FR-DDT-002 on the real gate path.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

import tradingagents.dataflows.market_data_validator as validator
from tradingagents.agents.researchers.bear_researcher import create_bear_researcher
from tradingagents.agents.researchers.bull_researcher import create_bull_researcher
from tradingagents.agents.utils.rating import extract_rating
from tradingagents.debate.budget import empty_usage
from tradingagents.debate.config import DebateTerminationConfig
from tradingagents.debate.evaluator_node import create_debate_evaluator_node
from tradingagents.debate.evidence_manifest import (
    EvidenceManifest,
    build_citation_allowlist,
    is_valid_new_evidence,
)
from tradingagents.evidence import (
    Criticality,
    EvidenceGroupQuality,
    QualityStatus,
)
from tradingagents.evidence.adapter import build_market_evidence_records
from tradingagents.evidence.multi_category_gate import evaluate_multi_category_gate
from tradingagents.evidence.policy import OPTIONAL_CATEGORIES
from tradingagents.graph.data_quality_gate import (
    GATE_EVIDENCE_RECORDS_KEY,
    GATE_OPTIONAL_EVIDENCE_KEY,
    create_data_quality_gate_node,
)
from tradingagents.report_artifacts import write_report_artifacts

SYMBOL = "COF"
TARGET = "2026-05-13"
FETCHED = "2026-05-13T12:00:00Z"


# ---------------------------------------------------------------------------
# Deterministic fixtures (mirror the gate graph tests, no external services)
# ---------------------------------------------------------------------------


def _fixed_dataframe(future: bool = False) -> pd.DataFrame:
    end = "2026-06-20" if future else "2026-05-20"
    dates = pd.bdate_range("2026-04-01", end)
    closes = [100 + i for i in range(len(dates))]
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": [c - 0.5 for c in closes],
            "High": [c + 1.0 for c in closes],
            "Low": [c - 1.0 for c in closes],
            "Close": closes,
            "Volume": [1_000_000 + i for i in range(len(dates))],
        }
    )


@pytest.fixture
def fixed_snapshot(monkeypatch):
    monkeypatch.setattr(
        validator, "load_ohlcv", lambda s, d, fill_gaps=True: _fixed_dataframe()
    )


def _high_optional_group(category: str) -> dict:
    return EvidenceGroupQuality(
        category=category,
        quality_status=QualityStatus.HIGH,
        criticality=Criticality.IMPORTANT,
        evidence_ids=[f"structured://{category}/1"],
        source_count=2,
        independent_source_count=2,
        reason_codes=["high"],
        human_readable_reason="ok",
    ).to_dict()


def _all_high_optional() -> dict:
    return {c: _high_optional_group(c) for c in OPTIONAL_CATEGORIES}


def _real_gate_state(optional: dict | None = None) -> dict:
    """Run the real gate node with the fixed snapshot and structured optionals."""
    node = create_data_quality_gate_node(now_provider=lambda: FETCHED)
    return node(
        {
            "company_of_interest": SYMBOL,
            "trade_date": TARGET,
            "asset_type": "stock",
            GATE_OPTIONAL_EVIDENCE_KEY: optional if optional is not None else _all_high_optional(),
        }
    )


def _market_record_ids(state: dict) -> list[str]:
    return [
        str(r["evidence_id"])
        for r in state[GATE_EVIDENCE_RECORDS_KEY]
        if str(r.get("category")) == "market"
    ]


# ---------------------------------------------------------------------------
# Gate outputs apply each record's own computed classification
# ---------------------------------------------------------------------------


class TestGateAppliesPerRecordQuality:
    def test_normal_gate_records_carry_computed_status_and_validations(self, fixed_snapshot):
        state = _real_gate_state()
        assert state["data_quality_verdict"] == "normal"
        groups = {g["category"]: g["quality_status"] for g in state["data_quality_group_statuses"]}
        assert groups["market"] == "Medium"

        records = state[GATE_EVIDENCE_RECORDS_KEY]
        assert records, "the gate must serialize its market evidence records"
        for record in records:
            # The provisional adapter values are replaced by the per-record
            # classification, not left as Low/unvalidated.
            assert record["quality_status"] == "Medium", record
            assert record["quality_status"] != "Low"
            assert "unvalidated" not in record["quality_reasons"]
            assert record["quality_reasons"] == ["medium_single_source"]
            # The record's own validation results are attached by evidence id.
            assert record["validation_results"], record
            for result in record["validation_results"]:
                assert result["evidence_id"] == record["evidence_id"]

    def test_manifest_and_allowlist_expose_validated_ids(self, fixed_snapshot):
        state = _real_gate_state()
        manifest = EvidenceManifest.from_records(state[GATE_EVIDENCE_RECORDS_KEY])
        assert manifest.valid_ids, "Medium market evidence must be citable"
        assert set(manifest.valid_ids) == set(_market_record_ids(state))

        allowlist = build_citation_allowlist(
            state[GATE_EVIDENCE_RECORDS_KEY], TARGET
        )
        assert "No validated, on-or-before-target evidence IDs" not in allowlist
        for evidence_id in manifest.valid_ids:
            assert evidence_id in allowlist

    def test_report_quality_counts_reflect_medium_not_five_low(self, fixed_snapshot, tmp_path):
        state = _real_gate_state()
        write_report_artifacts(state, SYMBOL, tmp_path / "artifacts")
        run_summary = json.loads(
            (Path(tmp_path) / "artifacts" / "run_summary.json").read_text(encoding="utf-8")
        )
        counts = run_summary["quality_counts"]
        assert counts["Medium"] == len(state[GATE_EVIDENCE_RECORDS_KEY])
        assert counts["Low"] == 0
        assert counts["Blocked"] == 0


# ---------------------------------------------------------------------------
# Real gate -> researcher -> evaluator: new valid evidence counts
# ---------------------------------------------------------------------------


def _fake_llm(content: str):
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=None)
    llm.invoke = MagicMock(return_value=MagicMock(content=content))
    return llm


def _citing_turn_content(evidence_id: str) -> str:
    return (
        "The validated close and volume support the growth case.\n"
        "DEBATE_METADATA: stance=Buy; confidence=0.7; "
        f"cited={evidence_id}; new_claims=margin expansion durably supported|{evidence_id};"
    )


def _run_round(state: dict, bull_content: str, bear_content: str) -> dict:
    """Run Bull then Bear then the real evaluator over the gate-produced state."""
    debate_state = {"turns": [], "count": 0, "history": "", "current_response": ""}
    base = {
        "company_of_interest": SYMBOL,
        "trade_date": TARGET,
        "asset_type": "stock",
        "market_report": "",
        "sentiment_report": "",
        "news_report": "",
        "fundamentals_report": "",
        "investment_debate_state": debate_state,
        "data_quality_evidence_records": state[GATE_EVIDENCE_RECORDS_KEY],
        "data_quality_context": "[Data Quality Gate] Verdict: normal.",
        "data_quality_verdict": state["data_quality_verdict"],
        "data_quality_group_statuses": state["data_quality_group_statuses"],
        "debate_usage": empty_usage(),
    }

    bull_out = create_bull_researcher(_fake_llm(bull_content))(dict(base))
    base["investment_debate_state"] = bull_out["investment_debate_state"]
    base["debate_usage"] = bull_out["debate_usage"]

    bear_out = create_bear_researcher(_fake_llm(bear_content))(dict(base))
    base["investment_debate_state"] = bear_out["investment_debate_state"]
    base["debate_usage"] = bear_out["debate_usage"]

    cfg = DebateTerminationConfig.from_dict(
        {
            "max_debate_rounds": 3,
            "max_calls": 1000,
            "max_tokens": 100000,
            "max_time": 600.0,
            "reserved_summary_tokens": 100,
            "next_round_estimate_tokens": 200,
        }
    )
    eval_out = create_debate_evaluator_node(config=cfg)(dict(base))
    return eval_out


class TestRealGateToEvaluatorNewEvidence:
    def test_citing_a_real_gate_id_counts_as_new_valid_evidence(self, fixed_snapshot):
        state = _real_gate_state()
        real_id = _market_record_ids(state)[0]
        out = _run_round(
            state,
            _citing_turn_content(real_id),
            _citing_turn_content(real_id),
        )
        metrics = out["investment_debate_state"]["round_metrics"][-1]
        assert metrics["new_valid_evidence_count"] > 0, (
            "a real Medium gate evidence ID, cited and linked, must count as new"
        )
        assert real_id in metrics["new_valid_evidence_ids"]

    def test_low_evidence_never_counts_as_new(self):
        # A record that is genuinely Low must not be promoted just because the
        # market category rated the group Medium.
        low_records = [
            {
                "evidence_id": "run:low",
                "quality_status": "Low",
                "quality_reasons": ["low_material_failure"],
                "observed_at": "2026-05-01",
                "target_date": TARGET,
                "value_raw": "100",
                "metric_name": "close",
                "unit_normalized": "USD",
                "validation_results": [],
            }
        ]
        state = {
            "data_quality_verdict": "normal",
            "data_quality_group_statuses": [],
            GATE_EVIDENCE_RECORDS_KEY: low_records,
        }
        out = _run_round(
            state,
            _citing_turn_content("run:low"),
            _citing_turn_content("run:low"),
        )
        metrics = out["investment_debate_state"]["round_metrics"][-1]
        assert metrics["new_valid_evidence_count"] == 0
        assert "run:low" not in metrics["new_valid_evidence_ids"]

    def test_future_evidence_never_counts_as_new(self):
        future_records = [
            {
                "evidence_id": "run:future",
                "quality_status": "Medium",
                "quality_reasons": ["medium_single_source"],
                "observed_at": "2026-06-01",  # after TARGET
                "target_date": TARGET,
                "value_raw": "100",
                "metric_name": "close",
                "unit_normalized": "USD",
                "validation_results": [],
            }
        ]
        state = {
            "data_quality_verdict": "normal",
            "data_quality_group_statuses": [],
            GATE_EVIDENCE_RECORDS_KEY: future_records,
        }
        out = _run_round(
            state,
            _citing_turn_content("run:future"),
            _citing_turn_content("run:future"),
        )
        metrics = out["investment_debate_state"]["round_metrics"][-1]
        assert metrics["new_valid_evidence_count"] == 0
        # The allowlist filters future evidence out entirely.
        allowlist = build_citation_allowlist(future_records, TARGET)
        assert "run:future" not in allowlist

    def test_blocked_evidence_never_counts_as_new(self):
        blocked_records = [
            {
                "evidence_id": "run:blocked",
                "quality_status": "Blocked",
                "quality_reasons": ["blocked_lookahead"],
                "observed_at": "2026-05-01",
                "target_date": TARGET,
                "value_raw": "100",
                "metric_name": "close",
                "unit_normalized": "USD",
                "validation_results": [],
            }
        ]
        manifest = EvidenceManifest.from_records(blocked_records)
        assert is_valid_new_evidence(
            evidence_id="run:blocked",
            previously_cited=set(),
            currently_linked=True,
            manifest=manifest,
            target_date=TARGET,
        ) is False


# ---------------------------------------------------------------------------
# Mismatched ids and locked-field integrity
# ---------------------------------------------------------------------------


class TestPerRecordApplicationIntegrity:
    def test_classification_uses_own_results_not_a_mismatched_record(self, fixed_snapshot):
        # Two records in a run: one real valid snapshot record and one injected
        # record whose validation results do not belong to it. The engine must
        # classify each record by *its own* results keyed by evidence_id; a
        # result with a foreign evidence_id must never be applied to another
        # record.
        import tradingagents.dataflows.market_data_validator as vd

        snapshot = vd.build_verified_market_snapshot_data(
            SYMBOL, TARGET, look_back_days=30
        )
        records = build_market_evidence_records(
            snapshot, f"{TARGET}/{SYMBOL}", ticker_input=SYMBOL
        )
        results_by_id = {
            r.evidence_id: [] for r in records
        }
        result = evaluate_multi_category_gate(
            trade_date=TARGET,
            symbol=SYMBOL,
            snapshot_builder=lambda *a, **k: snapshot,
            record_builder=lambda *a, **k: list(records),
            validator=lambda *a, **k: results_by_id,
            now_provider=lambda: FETCHED,
            optional_category_groups={},
        )
        # Every serialized record keeps the locked 20 fields.
        locked = {
            "evidence_id", "run_id", "ticker_input", "ticker_normalized",
            "asset_type", "category", "metric_name", "value_raw",
            "value_normalized", "unit_raw", "unit_normalized", "source_name",
            "source_ref", "observed_at", "fetched_at", "target_date",
            "criticality", "validation_results", "quality_status",
            "quality_reasons",
        }
        for record in result.evidence_records:
            assert set(record) == locked
        assert len({r["evidence_id"] for r in result.evidence_records}) == len(
            result.evidence_records
        )


def test_bull_researcher_can_parse_rating_from_citing_turn(fixed_snapshot):
    # Sanity: the citing reply is a normal, parseable bull argument (not a Hold),
    # so the round is a genuine directional debate with new evidence.
    state = _real_gate_state()
    real_id = _market_record_ids(state)[0]
    content = _citing_turn_content(real_id)
    assert extract_rating(content) == "Buy"
