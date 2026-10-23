"""Tests for the evidence foundation schemas (#DQ gate step 1).

Offline: no network. These cover the locked field counts/order and enum
values, ``SourceAttempt`` separation, acyclic JSON-safe ``Decimal``
serialization, and the authoritative ``GateDecision`` output fields.
"""

from __future__ import annotations

import json
from dataclasses import fields
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from tradingagents.evidence.models import (
    Criticality,
    EvidenceGroupQuality,
    EvidenceRecord,
    GateDecision,
    GateVerdict,
    QualityStatus,
    SourceAttempt,
    SourceResultStatus,
    ValidationClass,
    ValidationResult,
    ValidationStatus,
    quantize_decimal,
)

# Exactly the locked 20 fields, in order.
LOCKED_EVIDENCE_FIELDS = [
    "evidence_id",
    "run_id",
    "ticker_input",
    "ticker_normalized",
    "asset_type",
    "category",
    "metric_name",
    "value_raw",
    "value_normalized",
    "unit_raw",
    "unit_normalized",
    "source_name",
    "source_ref",
    "observed_at",
    "fetched_at",
    "target_date",
    "criticality",
    "validation_results",
    "quality_status",
    "quality_reasons",
]

# Exactly the locked 7 fields, in order.
LOCKED_SOURCE_ATTEMPT_FIELDS = [
    "source",
    "tool",
    "started_at",
    "duration",
    "result_status",
    "error_type",
    "error_message",
]


def _sample_validation() -> ValidationResult:
    return ValidationResult(
        rule_id="freshness.basic",
        validation_class=ValidationClass.FRESHNESS_LOOKAHEAD,
        status=ValidationStatus.PASS,
        expected="within 7 days",
        actual="2 days",
        message="ok",
        evidence_id="run:1",
    )


def _sample_record() -> EvidenceRecord:
    return EvidenceRecord.build(
        evidence_id="run:1",
        run_id="run",
        ticker_input="COF",
        ticker_normalized="COF",
        asset_type="stock",
        category="market_ohlcv",
        metric_name="close",
        value_raw="105.50",
        value_normalized=Decimal("105.50"),
        unit_raw="USD",
        unit_normalized="USD",
        source_name="yfinance",
        source_ref="OHLCV cache",
        observed_at="2026-05-13",
        fetched_at="2026-05-13T12:00:00Z",
        target_date="2026-05-13",
        criticality=Criticality.CRITICAL,
        validation_results=[_sample_validation()],
    )


class TestEvidenceRecordFields:
    def test_exact_20_fields_in_order(self):
        names = [f.name for f in fields(EvidenceRecord)]
        assert names == LOCKED_EVIDENCE_FIELDS
        assert len(names) == 20

    def test_no_extra_fields(self):
        assert len(fields(EvidenceRecord)) == 20


class TestSourceAttemptSeparation:
    def test_exact_7_fields_in_order(self):
        names = [f.name for f in fields(SourceAttempt)]
        assert names == LOCKED_SOURCE_ATTEMPT_FIELDS
        assert len(names) == 7

    def test_source_attempt_not_embedded_in_evidence_record(self):
        evidence_names = {f.name for f in fields(EvidenceRecord)}
        attempt_names = {f.name for f in fields(SourceAttempt)}
        # No SourceAttempt-only field is duplicated inside EvidenceRecord, and
        # SourceAttempt carries no evidence field.
        assert not (evidence_names & attempt_names)

    def test_source_attempt_is_separate_record(self):
        attempt = SourceAttempt(
            source="yfinance",
            tool="load_ohlcv",
            started_at="2026-05-13T12:00:00Z",
            duration=0.4,
            result_status=SourceResultStatus.SUCCESS,
            error_type=None,
            error_message=None,
        )
        assert attempt.source == "yfinance"
        assert attempt.result_status == SourceResultStatus.SUCCESS


class TestEnums:
    def test_criticality_values(self):
        assert [c.value for c in Criticality] == [
            "critical", "important", "supporting",
        ]

    def test_quality_status_values(self):
        assert [q.value for q in QualityStatus] == [
            "High", "Medium", "Low", "Blocked",
        ]

    def test_gate_verdict_values(self):
        assert [g.value for g in GateVerdict] == ["normal", "degraded", "blocked"]

    def test_validation_status_values(self):
        assert [v.value for v in ValidationStatus] == [
            "pass", "warning", "fail", "not_applicable",
        ]

    def test_validation_class_values(self):
        assert [v.value for v in ValidationClass] == [
            "completeness",
            "freshness_lookahead",
            "format_numeric",
            "asset_applicability",
            "cross_source_consistency",
        ]


class TestDecimalQuantization:
    def test_quantize_decimal_half_up(self):
        assert quantize_decimal("105.505") == Decimal("105.5050000000")
        assert quantize_decimal(0.1 + 0.2) == Decimal("0.3000000000")
        assert quantize_decimal("abc") is None
        assert quantize_decimal(True) is None
        assert quantize_decimal(float("nan")) is None
        assert quantize_decimal(1e999) is None

    def test_value_normalized_is_decimals_and_quantized(self):
        rec = EvidenceRecord.build(
            evidence_id="run:2",
            run_id="run",
            ticker_input="AAPL",
            ticker_normalized="AAPL",
            asset_type="stock",
            category="market_ohlcv",
            metric_name="close",
            value_raw="189.5",
            value_normalized=Decimal("189.5"),
            unit_raw="USD",
            unit_normalized="USD",
            source_name="yfinance",
            source_ref="cache",
            observed_at="2026-05-13",
            fetched_at="2026-05-13T12:00:00Z",
            target_date="2026-05-13",
            criticality=Criticality.IMPORTANT,
            validation_results=[],
        )
        assert isinstance(rec.value_normalized, Decimal)
        assert rec.value_normalized == Decimal("189.5000000000")


class TestValidationResult:
    def test_retains_authoritative_fields(self):
        v = _sample_validation()
        d = v.to_dict()
        assert d["rule_id"] == "freshness.basic"
        assert d["validation_class"] == "freshness_lookahead"
        assert d["status"] == "pass"
        assert d["expected"] == "within 7 days"
        assert d["actual"] == "2 days"
        assert d["message"] == "ok"
        assert d["evidence_id"] == "run:1"

    def test_round_trip(self):
        v = _sample_validation()
        assert ValidationResult.from_dict(v.to_dict()) == v

    def test_rejects_unknown_validation_class(self):
        with pytest.raises(ValueError):
            ValidationResult(
                rule_id="x",
                validation_class="bogus",  # type: ignore[arg-type]
                status=ValidationStatus.PASS,
            )


class TestEvidenceJSON:
    def test_json_safe_deterministic_round_trip(self):
        rec = _sample_record()
        d = rec.to_dict()
        # JSON-safe: dumps must not raise, and Decimal must pin to string.
        payload = json.dumps(d, sort_keys=True)
        assert isinstance(json.loads(payload), dict)
        assert isinstance(d["value_normalized"], str)
        assert d["value_normalized"] == "105.5000000000"

        restored = EvidenceRecord.from_dict(rec.to_dict())
        assert restored.to_dict() == rec.to_dict()
        # Deterministic across two serializations.
        assert json.dumps(rec.to_dict(), sort_keys=True) == payload

    def test_validation_inlined_not_circular(self):
        d = _sample_record().to_dict()
        assert isinstance(d["validation_results"], list)
        assert d["validation_results"][0]["evidence_id"] == "run:1"

    def test_datetime_and_enum_serialization(self):
        v = ValidationResult(
            rule_id="r",
            validation_class=ValidationClass.FORMAT_NUMERIC,
            status=ValidationStatus.FAIL,
            expected=Decimal("1.5"),
            actual="not-a-number",
            message="bad",
            evidence_id="e",
        )
        d = v.to_dict()
        assert d["expected"] == "1.5000000000"
        assert json.dumps(d)  # JSON-safe

    def test_text_evidence_value_normalized_none(self):
        rec = EvidenceRecord.build(
            evidence_id="run:3",
            run_id="run",
            ticker_input="COF",
            ticker_normalized="COF",
            asset_type="stock",
            category="news",
            metric_name="headline",
            value_raw="Dividend raised",
            value_normalized=None,
            unit_raw="text",
            unit_normalized=None,
            source_name="news",
            source_ref="article",
            observed_at="2026-05-13",
            fetched_at="2026-05-13T12:00:00Z",
            target_date="2026-05-13",
            criticality=Criticality.SUPPORTING,
            validation_results=[],
        )
        assert rec.value_normalized is None
        assert rec.value_raw == "Dividend raised"
        assert rec.to_dict()["value_normalized"] is None


class TestGateDecision:
    def test_authoritative_output_fields(self):
        gd = GateDecision(
            decision=GateVerdict.DEGRADED,
            decided_at="2026-05-13T12:00:00Z",
            group_statuses=[
                EvidenceGroupQuality(
                    category="market_ohlcv",
                    quality_status=QualityStatus.MEDIUM,
                    criticality=Criticality.CRITICAL,
                    evidence_ids=["run:1"],
                    source_count=1,
                    independent_source_count=1,
                    reason_codes=["low_source_coverage"],
                    human_readable_reason="Only one source.",
                )
            ],
            critical_evidence_ids=["run:1"],
            limitations=["confidence capped at Medium"],
            reason_codes=["low_source_coverage"],
            human_readable_reason="Degraded: only one source.",
            policy_version="1.0",
        )
        d = gd.to_dict()
        assert d["decision"] == "degraded"
        assert d["decided_at"] == "2026-05-13T12:00:00Z"
        assert d["group_statuses"][0]["quality_status"] == "Medium"
        assert d["critical_evidence_ids"] == ["run:1"]
        assert d["limitations"] == ["confidence capped at Medium"]
        assert d["reason_codes"] == ["low_source_coverage"]
        assert d["human_readable_reason"] == "Degraded: only one source."
        assert d["policy_version"] == "1.0"

    def test_gate_decision_round_trip(self):
        gd = GateDecision(
            decision=GateVerdict.BLOCKED,
            decided_at="2026-05-13T12:00:00Z",
            group_statuses=[],
            critical_evidence_ids=[],
            limitations=["no evidence"],
            reason_codes=["no_critical_evidence"],
            human_readable_reason="Blocked.",
            policy_version="1.0",
        )
        assert GateDecision.from_dict(gd.to_dict()).to_dict() == gd.to_dict()


class TestDatetimeIso:
    def test_aware_datetime_renders_utc(self):
        from tradingagents.evidence.models import _format_datetime

        dt = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
        assert _format_datetime(dt) == "2026-05-13T12:00:00Z"


class TestPolicyExports:
    def test_metric_tolerance_is_exported_and_frozen(self):
        from dataclasses import FrozenInstanceError

        from tradingagents.evidence import MetricTolerance

        tol = MetricTolerance(Decimal("0.02"), Decimal("0.10"))
        assert tol.normal_conflict_fraction == Decimal("0.02")
        assert tol.severe_conflict_fraction == Decimal("0.10")
        with pytest.raises(FrozenInstanceError):
            tol.normal_conflict_fraction = Decimal("0.03")  # type: ignore[misc]

    def test_metric_tolerance_cross_constraint_validated(self):
        from tradingagents.evidence import MetricTolerance

        with pytest.raises(ValueError):
            MetricTolerance(Decimal("0.10"), Decimal("0.05"))
