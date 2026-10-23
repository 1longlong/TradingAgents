"""Offline tests for the DQ gate Step 2 core (adapter, validator, policy,
quality, gate). No network, no LLM.

Covers, per the authoritative design: adapter traceability; missing required
field; future observed_at (look-ahead); stale boundary; NaN/nonfinite or
negative volume; invalid OHLC relationships; asset mismatch; single-source
Medium; two-source in-tolerance High; normal conflict Low; severe critical
conflict Blocked; and Gate scenarios A (normal), B (degraded), C (blocked).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

import tradingagents.dataflows.market_data_validator as validator
from tradingagents.evidence import (
    Criticality,
    EvidenceGroupQuality,
    EvidenceRecord,
    GateVerdict,
    MarketPolicy,
    MetricTolerance,
    QualityStatus,
    ValidationClass,
    ValidationStatus,
    aggregate_category_quality,
    build_gate_decision,
    build_market_evidence_records,
    count_business_days,
    evaluate_record_quality,
    validate_market_records,
)

CATEGORY = "market_ohlcv"
RUN_ID = "run-1"
SYMBOL = "COF"
TARGET = "2026-05-13"
FETCHED = "2026-05-13T12:00:00Z"

METRICS = ("open", "high", "low", "close", "volume")
_VALID = {"open": "100", "high": "102", "low": "99", "close": "101", "volume": "1000000"}
_UNIT = {"open": "USD", "high": "USD", "low": "USD", "close": "USD", "volume": "shares"}


def make_record(
    metric: str,
    *,
    value: str | Decimal | None = None,
    source: str = "yfinance",
    observed_at: str | None = "2026-05-13",
    target_date: str | None = TARGET,
    ticker: str = SYMBOL,
    asset_type: str = "stock",
    criticality=None,
    evidence_id: str | None = None,
    value_raw: str | None = None,
) -> EvidenceRecord:
    """Build one market OHLCV record with sane defaults, then override."""
    normalized = None if value is None else Decimal(str(value))
    raw_value = value_raw if value_raw is not None else (
        str(normalized) if normalized is not None else ""
    )
    metric_criticality = criticality or (
        Criticality.CRITICAL if metric in ("close", "volume") else Criticality.IMPORTANT
    )
    raw = raw_value
    rid = evidence_id or f"{RUN_ID}/{CATEGORY}/{source}/{metric}/0"
    return EvidenceRecord.build(
        evidence_id=rid,
        run_id=RUN_ID,
        ticker_input=ticker,
        ticker_normalized=ticker,
        asset_type=asset_type,
        category=CATEGORY,
        metric_name=metric,
        value_raw=raw,
        value_normalized=normalized,
        unit_raw=_UNIT[metric],
        unit_normalized=_UNIT[metric],
        source_name=source,
        source_ref=f"{source}-ref",
        observed_at=observed_at,
        fetched_at=FETCHED,
        target_date=target_date,
        criticality=metric_criticality,
        validation_results=[],
    )


def valid_row(source: str = "yfinance") -> list[EvidenceRecord]:
    """A complete, valid OHLCV row (5 records) for one source."""
    return [make_record(m, value=_VALID[m], source=source) for m in METRICS]


def validate(records):
    return validate_market_records(
        records, expected_symbol=SYMBOL, target_date=TARGET
    )


def aggregate(category_records, results=None):
    results = results if results is not None else validate(category_records)
    group, _status = aggregate_category_quality(
        CATEGORY, category_records, results
    )
    return group


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


def _snapshot(monkeypatch):
    dates = pd.bdate_range("2026-04-01", "2026-05-20")
    closes = [100 + i for i in range(len(dates))]
    df = pd.DataFrame(
        {
            "Date": dates,
            "Open": [c - 0.5 for c in closes],
            "High": [c + 1.0 for c in closes],
            "Low": [c - 1.0 for c in closes],
            "Close": closes,
            "Volume": [1_000_000 + i for i in range(len(dates))],
        }
    )
    monkeypatch.setattr(
        validator, "load_ohlcv", lambda s, d, fill_gaps=True: df
    )
    return validator.build_verified_market_snapshot_data(
        SYMBOL, TARGET, fetched_at=FETCHED
    )


class TestAdapter:
    def test_produces_five_records_one_per_metric(self, monkeypatch):
        records = build_market_evidence_records(_snapshot(monkeypatch), RUN_ID)
        assert [r.metric_name for r in records] == list(METRICS)

    def test_truthful_provenance_single_source(self, monkeypatch):
        records = build_market_evidence_records(_snapshot(monkeypatch), RUN_ID)
        for record in records:
            assert record.source_name == "yfinance"
            assert record.source_ref == "load_ohlcv"
        # Never claims a second independent source.
        assert {r.source_name for r in records} == {"yfinance"}

    def test_units_and_criticality(self, monkeypatch):
        records = build_market_evidence_records(_snapshot(monkeypatch), RUN_ID)
        by_metric = {r.metric_name: r for r in records}
        assert by_metric["close"].criticality == Criticality.CRITICAL
        assert by_metric["volume"].criticality == Criticality.CRITICAL
        assert by_metric["open"].criticality == Criticality.IMPORTANT
        # Truthful neutral price unit (snapshot knows no quote currency).
        assert by_metric["close"].unit_normalized == "native_quote_currency"
        assert by_metric["volume"].unit_normalized == "shares"

    def test_observed_at_and_target_date(self, monkeypatch):
        records = build_market_evidence_records(_snapshot(monkeypatch), RUN_ID)
        for record in records:
            assert record.observed_at == "2026-05-13"
            assert record.target_date == TARGET

    def test_evidence_ids_are_stable_and_deterministic(self, monkeypatch):
        snap = _snapshot(monkeypatch)
        a = build_market_evidence_records(snap, RUN_ID)
        b = build_market_evidence_records(snap, RUN_ID)
        assert [r.evidence_id for r in a] == [r.evidence_id for r in b]
        # Category is the authoritative "market", index is fixed 0.
        close = next(r for r in a if r.metric_name == "close")
        assert close.evidence_id.startswith(f"{RUN_ID}/market/yfinance/close/")
        assert close.evidence_id.endswith("/0")

    def test_uses_structured_values_not_markdown(self, monkeypatch):
        snap = _snapshot(monkeypatch)
        records = build_market_evidence_records(snap, RUN_ID)
        close = next(r for r in records if r.metric_name == "close")
        assert close.value_normalized == snap.latest_ohlcv.close.value

    def test_value_normalized_is_quantized_decimal(self, monkeypatch):
        records = build_market_evidence_records(_snapshot(monkeypatch), RUN_ID)
        assert all(isinstance(r.value_normalized, Decimal) for r in records)


# ---------------------------------------------------------------------------
# Validation: completeness
# ---------------------------------------------------------------------------


class TestCompleteness:
    def test_missing_required_field(self):
        # Force a missing value_normalized on close.
        records = valid_row()
        records[3] = make_record("close", value=None)
        results = validate(records)
        close_results = results[records[3].evidence_id]
        failing = [
            r
            for r in close_results
            if r.validation_class == ValidationClass.COMPLETENESS
            and r.status == ValidationStatus.FAIL
        ]
        assert failing, "expected a completeness FAIL for missing value_normalized"
        assert "value_normalized" in failing[0].message

    def test_sentinel_no_data_available_fails(self):
        records = valid_row()
        records[3] = make_record(
            "close", value=None, value_raw="NO_DATA_AVAILABLE"
        )
        results = validate(records)
        close_results = results[records[3].evidence_id]
        sentinel = [
            r
            for r in close_results
            if r.rule_id == "market.completeness.sentinel"
        ]
        assert sentinel and sentinel[0].status == ValidationStatus.FAIL
        status, _ = evaluate_record_quality(records[3], close_results)
        assert status == QualityStatus.BLOCKED


# ---------------------------------------------------------------------------
# Validation: freshness / look-ahead
# ---------------------------------------------------------------------------


class TestFreshnessLookahead:
    def test_future_observed_at_is_lookahead(self):
        records = valid_row()
        records[3] = make_record("close", value=_VALID["close"], observed_at="2026-05-20")
        results = validate(records)
        close_results = results[records[3].evidence_id]
        lookahead = [
            r
            for r in close_results
            if r.rule_id == "market.freshness.lookahead"
        ]
        assert lookahead and lookahead[0].status == ValidationStatus.FAIL
        status, reasons = evaluate_record_quality(records[3], close_results)
        assert status == QualityStatus.BLOCKED
        assert "blocked_lookahead" in reasons

    def test_stale_data_boundary_fresh(self):
        # Wednesday 2026-05-13 -> same day: 0 business days, within width.
        records = valid_row()
        results = validate(records)
        stale = [
            r
            for r in results[records[3].evidence_id]
            if r.rule_id == "market.freshness.stale"
        ]
        assert stale and stale[0].status == ValidationStatus.PASS

    def test_stale_data_exceeds_width(self):
        # 2026-05-13 target, observed 2026-05-06 (5 business days earlier).
        # A narrow policy (width=1) makes this stale.
        policy = MarketPolicy(freshness_width=Decimal("1"))
        records = valid_row()
        records[3] = make_record("close", value=_VALID["close"], observed_at="2026-05-06")
        results = validate_market_records(
            records, expected_symbol=SYMBOL, target_date=TARGET, policy=policy
        )
        close_results = results[records[3].evidence_id]
        stale = [r for r in close_results if r.rule_id == "market.freshness.stale"]
        assert stale and stale[0].status == ValidationStatus.FAIL
        assert int(stale[0].actual.split()[0]) > 1


# ---------------------------------------------------------------------------
# Validation: format / numeric
# ---------------------------------------------------------------------------


class TestFormatNumeric:
    def test_nan_nonfinite_volume_fails(self):
        records = valid_row()
        records[4] = make_record(
            "volume", value=None, value_raw="NaN"
        )
        # value_normalized None for NaN string -> completeness/format fail.
        results = validate(records)
        vol_results = results[records[4].evidence_id]
        numeric = [
            r
            for r in vol_results
            if r.validation_class == ValidationClass.FORMAT_NUMERIC
            and r.status == ValidationStatus.FAIL
        ]
        assert numeric, "expected a format FAIL for non-finite/missing volume"

    def test_negative_volume_fails(self):
        records = valid_row()
        records[4] = make_record("volume", value=Decimal("-5"))
        results = validate(records)
        vol_results = results[records[4].evidence_id]
        numeric = [
            r
            for r in vol_results
            if r.validation_class == ValidationClass.FORMAT_NUMERIC
            and r.status == ValidationStatus.FAIL
        ]
        assert numeric
        assert "Negative volume" in numeric[0].message

    def test_nonpositive_close_fails(self):
        records = valid_row()
        records[3] = make_record("close", value=Decimal("0"))
        results = validate(records)
        close_results = results[records[3].evidence_id]
        numeric = [
            r
            for r in close_results
            if r.validation_class == ValidationClass.FORMAT_NUMERIC
            and r.status == ValidationStatus.FAIL
        ]
        assert numeric
        assert "Non-positive" in numeric[0].message


class TestOhlcRelationships:
    def test_invalid_high_below_close_fails(self):
        records = valid_row()
        # high=90 < close=101 and < open=100 -> violates.
        records[1] = make_record("high", value=Decimal("90"))
        results = validate(records)
        high_results = results[records[1].evidence_id]
        invalid = [
            r
            for r in high_results
            if r.rule_id == "market.format.ohlc_relationships"
            and r.status == ValidationStatus.FAIL
        ]
        assert invalid, "expected an OHLC relationship FAIL"

    def test_valid_relationship_passes(self):
        records = valid_row()
        results = validate(records)
        for metric in ("open", "high", "low", "close"):
            rec = next(r for r in records if r.metric_name == metric)
            ok = [
                r
                for r in results[rec.evidence_id]
                if r.rule_id == "market.format.ohlc_relationships"
                and r.status == ValidationStatus.PASS
            ]
            assert ok, f"expected OHLC relationship PASS for {metric}"


# ---------------------------------------------------------------------------
# Validation: asset applicability
# ---------------------------------------------------------------------------


class TestAssetApplicability:
    def test_ticker_mismatch_fails(self):
        # A complete MSFT row (all four price metrics) so the only failure is the
        # ticker mismatch; a lone mismatched metric would also isolate the row.
        records = valid_row()
        for i, m in enumerate(("open", "high", "low", "close")):
            records[i] = make_record(m, value=_VALID[m], ticker="MSFT")
        results = validate(records)
        close = next(r for r in records if r.metric_name == "close")
        close_results = results[close.evidence_id]
        mismatch = [
            r
            for r in close_results
            if r.rule_id == "market.asset.ticker_match"
            and r.status == ValidationStatus.FAIL
        ]
        assert mismatch
        status, reasons = evaluate_record_quality(close, close_results)
        assert status == QualityStatus.BLOCKED
        assert "blocked_ticker_mismatch" in reasons


# ---------------------------------------------------------------------------
# Quality: per-record and category
# ---------------------------------------------------------------------------


class TestQuality:
    def test_single_source_medium(self):
        records = valid_row()
        group = aggregate(records)
        assert group.quality_status == QualityStatus.MEDIUM
        assert group.independent_source_count == 1

    def test_two_source_in_tolerance_high(self):
        policy = MarketPolicy(min_independent_sources=2)
        records = valid_row("yfinance") + valid_row("alpha")
        results = validate_market_records(
            records, expected_symbol=SYMBOL, target_date=TARGET, policy=policy
        )
        group, _ = aggregate_category_quality(CATEGORY, records, results, policy=policy)
        assert group.quality_status == QualityStatus.HIGH
        assert group.independent_source_count == 2

    def test_normal_conflict_low(self):
        # Two sources that agree on open/high/low/volume but differ on the
        # critical close by ~5% (above normal 2%, below severe 10%) -> warning.
        policy = MarketPolicy(normal_conflict_fraction=Decimal("0.02"))
        records = valid_row("yfinance")
        records.append(make_record("close", value=Decimal("106.05"), source="alpha"))
        records.append(make_record("open", value=Decimal("100"), source="alpha"))
        records.append(make_record("high", value=Decimal("107"), source="alpha"))
        records.append(make_record("low", value=Decimal("99"), source="alpha"))
        records.append(make_record("volume", value=Decimal("1000000"), source="alpha"))
        results = validate_market_records(
            records, expected_symbol=SYMBOL, target_date=TARGET, policy=policy
        )
        group, _ = aggregate_category_quality(CATEGORY, records, results, policy=policy)
        assert group.quality_status == QualityStatus.LOW

    def test_severe_critical_conflict_blocked(self):
        # Two sources where the critical close differs by ~28.7% (>= severe).
        policy = MarketPolicy(severe_conflict_fraction=Decimal("0.10"))
        records = valid_row("yfinance")
        records.append(make_record("close", value=Decimal("130"), source="alpha"))
        records.append(make_record("open", value=Decimal("100"), source="alpha"))
        records.append(make_record("high", value=Decimal("135"), source="alpha"))
        records.append(make_record("low", value=Decimal("99"), source="alpha"))
        records.append(make_record("volume", value=Decimal("1000000"), source="alpha"))
        results = validate_market_records(
            records, expected_symbol=SYMBOL, target_date=TARGET, policy=policy
        )
        group, statuses = aggregate_category_quality(
            CATEGORY, records, results, policy=policy
        )
        assert group.quality_status == QualityStatus.BLOCKED


# ---------------------------------------------------------------------------
# Gate scenarios
# ---------------------------------------------------------------------------


def _group(status: QualityStatus, criticality=Criticality.CRITICAL, category="market_ohlcv"):
    return EvidenceGroupQuality(
        category=category,
        quality_status=status,
        criticality=criticality,
        evidence_ids=[f"{RUN_ID}/{category}/yfinance/close/0"],
        source_count=1,
        independent_source_count=1,
        reason_codes=["test_code"],
        human_readable_reason="test",
    )


class TestGate:
    def test_scenario_a_normal(self):
        decision = build_gate_decision(
            [_group(QualityStatus.HIGH)],
            decided_at="2026-05-13T12:00:00Z",
        )
        assert decision.decision == GateVerdict.NORMAL
        assert decision.decided_at == "2026-05-13T12:00:00Z"
        assert decision.policy_version == "1.0"
        assert decision.limitations == []

    def test_scenario_a_normal_with_medium(self):
        # Critical group Medium is sufficient -> normal.
        decision = build_gate_decision(
            [_group(QualityStatus.MEDIUM)],
            decided_at="2026-05-13T12:00:00Z",
        )
        assert decision.decision == GateVerdict.NORMAL

    def test_scenario_b_degraded_important_low(self):
        decision = build_gate_decision(
            [
                _group(QualityStatus.HIGH, Criticality.CRITICAL),
                _group(QualityStatus.LOW, Criticality.IMPORTANT, "market_indicators"),
            ],
            decided_at="2026-05-13T12:00:00Z",
        )
        assert decision.decision == GateVerdict.DEGRADED
        assert decision.limitations

    def test_scenario_b_degraded_insufficient_coverage(self):
        # A critical group that is only Low => insufficient coverage.
        decision = build_gate_decision(
            [_group(QualityStatus.LOW, Criticality.CRITICAL)],
            decided_at="2026-05-13T12:00:00Z",
        )
        assert decision.decision == GateVerdict.DEGRADED

    def test_scenario_c_blocked(self):
        decision = build_gate_decision(
            [_group(QualityStatus.BLOCKED, Criticality.CRITICAL)],
            decided_at="2026-05-13T12:00:00Z",
        )
        assert decision.decision == GateVerdict.BLOCKED
        assert decision.critical_evidence_ids
        assert decision.limitations

    def test_injectable_decided_at_deterministic(self):
        d1 = build_gate_decision([_group(QualityStatus.HIGH)], decided_at="2026-05-13T00:00:00Z")
        d2 = build_gate_decision([_group(QualityStatus.HIGH)], decided_at="2026-05-13T00:00:00Z")
        assert d1.to_dict() == d2.to_dict()

    def test_gate_fails_closed_on_bad_input(self):

        with pytest.raises(ValueError):
            build_gate_decision(["not-a-group"], decided_at="x")  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# Focused regression coverage (Step 2 review fixes)
# ---------------------------------------------------------------------------


def _snapshot_at(monkeypatch, look_back_days: int = 30):
    """A verified snapshot built with an explicit look_back_days."""
    dates = pd.bdate_range("2026-04-01", "2026-05-20")
    closes = [100 + i for i in range(len(dates))]
    df = pd.DataFrame(
        {
            "Date": dates,
            "Open": [c - 0.5 for c in closes],
            "High": [c + 1.0 for c in closes],
            "Low": [c - 1.0 for c in closes],
            "Close": closes,
            "Volume": [1_000_000 + i for i in range(len(dates))],
        }
    )
    monkeypatch.setattr(validator, "load_ohlcv", lambda s, d, fill_gaps=True: df)
    return validator.build_verified_market_snapshot_data(
        SYMBOL, TARGET, look_back_days=look_back_days, fetched_at=FETCHED
    )


class TestAdapterDetail:
    def test_neutral_price_unit_and_original_ticker_retention(self, monkeypatch):
        snap = _snapshot_at(monkeypatch)
        records = build_market_evidence_records(
            snap, RUN_ID, price_unit="EUR", ticker_input="COF.OL"
        )
        by_metric = {r.metric_name: r for r in records}
        # Explicit non-USD price unit is honoured; volume stays shares.
        assert by_metric["close"].unit_normalized == "EUR"
        assert by_metric["open"].unit_normalized == "EUR"
        assert by_metric["volume"].unit_normalized == "shares"
        # Original ticker is retained; normalized stays from the snapshot.
        assert by_metric["close"].ticker_input == "COF.OL"
        assert by_metric["close"].ticker_normalized == snap.symbol_normalized

    def test_evidence_id_invariant_under_look_back_days(self, monkeypatch):
        short = build_market_evidence_records(_snapshot_at(monkeypatch, 5), RUN_ID)
        long = build_market_evidence_records(_snapshot_at(monkeypatch, 30), RUN_ID)
        assert [r.evidence_id for r in short] == [r.evidence_id for r in long]


class TestFreshnessBoundary:
    def test_same_day_age_zero(self):
        assert count_business_days(date(2026, 5, 13), date(2026, 5, 13)) == 0

    def test_exact_freshness_boundary(self):
        # 2026-05-06 -> 2026-05-13 is exactly 5 business days.
        assert count_business_days(date(2026, 5, 6), date(2026, 5, 13)) == 5
        policy = MarketPolicy(freshness_width=Decimal("5"))
        records = valid_row()
        records[3] = make_record("close", value=_VALID["close"], observed_at="2026-05-06")
        results = validate_market_records(
            records, expected_symbol=SYMBOL, target_date=TARGET, policy=policy
        )
        stale = [r for r in results[records[3].evidence_id] if r.rule_id == "market.freshness.stale"]
        assert stale and stale[0].status == ValidationStatus.PASS
        # One business day past the boundary is stale.
        narrower = MarketPolicy(freshness_width=Decimal("4"))
        results_narrow = validate_market_records(
            records, expected_symbol=SYMBOL, target_date=TARGET, policy=narrower
        )
        stale_narrow = [
            r for r in results_narrow[records[3].evidence_id] if r.rule_id == "market.freshness.stale"
        ]
        assert stale_narrow and stale_narrow[0].status == ValidationStatus.FAIL


class TestCompletenessRequiredFields:
    def test_each_common_required_field_missing_fails(self):
        from dataclasses import replace

        from tradingagents.evidence.validate import REQUIRED_FIELDS

        for field in REQUIRED_FIELDS:
            base = make_record("close", value=_VALID["close"])
            records = valid_row()
            records[3] = replace(base, **{field: ""})
            results = validate(records)
            close_results = results[records[3].evidence_id]
            failing = [
                r
                for r in close_results
                if r.validation_class == ValidationClass.COMPLETENESS
                and r.status == ValidationStatus.FAIL
            ]
            assert failing, f"expected completeness FAIL when {field} is blank"
            assert field in failing[0].actual

    def test_all_required_fields_present_passes(self):
        records = valid_row()
        results = validate(records)
        for metric in METRICS:
            rec = next(r for r in records if r.metric_name == metric)
            ok = [
                r
                for r in results[rec.evidence_id]
                if r.validation_class == ValidationClass.COMPLETENESS
                and r.status == ValidationStatus.PASS
            ]
            assert ok, f"expected completeness PASS for {metric}"

    def test_target_date_mismatch_fails(self):
        records = valid_row()
        records[3] = make_record("close", value=_VALID["close"], target_date="2026-05-14")
        results = validate(records)
        close_results = results[records[3].evidence_id]
        mismatch = [
            r
            for r in close_results
            if r.rule_id == "market.freshness.target_date_agreement"
            and r.status == ValidationStatus.FAIL
        ]
        assert mismatch, "expected target_date agreement FAIL"

    def test_malformed_dates_fail(self):
        records = valid_row()
        records[3] = make_record("close", value=_VALID["close"], observed_at="not-a-date")
        results = validate(records)
        close_results = results[records[3].evidence_id]
        malformed = [
            r
            for r in close_results
            if r.rule_id == "market.freshness.malformed_date"
            and r.status == ValidationStatus.FAIL
        ]
        assert malformed, "expected malformed observed_at to FAIL"


class TestOhlcPerRowIsolation:
    def test_two_isolated_source_rows_independent(self):
        # Source A row is internally valid; Source B row has high < close.
        row_a = [
            make_record(m, value=v, source="srcA")
            for m, v in (("open", "100"), ("high", "102"), ("low", "99"), ("close", "101"))
        ]
        row_b = [
            make_record(m, value=v, source="srcB")
            for m, v in (("open", "100"), ("high", "90"), ("low", "99"), ("close", "101"))
        ]
        results = validate(row_a + row_b)
        for rec in row_a:
            oh = [r for r in results[rec.evidence_id] if r.rule_id == "market.format.ohlc_relationships"]
            assert len(oh) == 1 and oh[0].status == ValidationStatus.PASS
        for rec in row_b:
            oh = [r for r in results[rec.evidence_id] if r.rule_id == "market.format.ohlc_relationships"]
            assert len(oh) == 1 and oh[0].status == ValidationStatus.FAIL


class TestCrossSourceConsistency:
    def _full_two_source(self):
        return [
            make_record(m, value=v, source=s)
            for s in ("yfinance", "alpha")
            for m, v in _VALID.items()
        ]

    def test_pass_on_every_record_two_agreeing_sources(self):
        records = self._full_two_source()
        results = validate(records)
        for rec in records:
            cs = [
                r for r in results[rec.evidence_id] if r.rule_id == "market.cross_source.consistency"
            ]
            assert len(cs) == 1, "exactly one consistency result per record"
            assert cs[0].status == ValidationStatus.PASS

    def test_permutation_invariance(self):
        records = self._full_two_source()
        forward = validate(records)
        backward = validate(list(reversed(records)))

        def sig(res):
            return {
                k: sorted((x.rule_id, x.status.value) for x in v)
                for k, v in res.items()
            }

        assert sig(forward) == sig(backward)

    def test_three_source_median_and_outlier_retained(self):
        records = [
            make_record("close", value="100", source="a"),
            make_record("close", value="102", source="b"),
            make_record("close", value="105", source="c"),
        ]
        results = validate(records)
        # Median reference = 102. Source a -> 1.96% (PASS), b -> 0 (PASS),
        # c -> 2.94% (WARNING): every record gets a result, outliers retained.
        by_source = {r.source_name: r for r in records}
        a = [r for r in results[by_source["a"].evidence_id] if r.rule_id == "market.cross_source.consistency"]
        b = [r for r in results[by_source["b"].evidence_id] if r.rule_id == "market.cross_source.consistency"]
        c = [r for r in results[by_source["c"].evidence_id] if r.rule_id == "market.cross_source.consistency"]
        assert len(a) == 1 and a[0].status == ValidationStatus.PASS
        assert len(b) == 1 and b[0].status == ValidationStatus.PASS
        assert len(c) == 1 and c[0].status == ValidationStatus.WARNING

    def test_no_comparison_across_dates_units_or_tickers(self):
        # Two close records differing only in a grouping dimension must NOT be
        # cross-compared (each isolated single-source bucket => N/A).
        def close_record(source, observed, unit, ticker):
            return EvidenceRecord.build(
                evidence_id=f"x/{source}", run_id=RUN_ID, ticker_input=ticker,
                ticker_normalized=ticker, asset_type="stock", category=CATEGORY,
                metric_name="close", value_raw="100", value_normalized=Decimal("100"),
                unit_raw=unit, unit_normalized=unit, source_name=source,
                source_ref=source, observed_at=observed, fetched_at=FETCHED,
                target_date=TARGET, criticality=Criticality.CRITICAL,
                validation_results=[],
            )

        base = close_record("yf", "2026-05-13", "USD", SYMBOL)
        other_date = close_record("alpha", "2026-05-12", "USD", SYMBOL)
        other_unit = close_record("alpha", "2026-05-13", "EUR", SYMBOL)
        other_ticker = close_record("alpha", "2026-05-13", "USD", "MSFT")

        results = validate([base, other_date])
        for rec in (base, other_date):
            cs = [
                r for r in results[rec.evidence_id] if r.rule_id == "market.cross_source.consistency"
            ]
            assert len(cs) == 1 and cs[0].status == ValidationStatus.NOT_APPLICABLE

        results_unit = validate([base, other_unit])
        for rec in (base, other_unit):
            cs = [
                r for r in results_unit[rec.evidence_id]
                if r.rule_id == "market.cross_source.consistency"
            ]
            assert len(cs) == 1 and cs[0].status == ValidationStatus.NOT_APPLICABLE

        results_ticker = validate([base, other_ticker])
        for rec in (base, other_ticker):
            cs = [
                r for r in results_ticker[rec.evidence_id]
                if r.rule_id == "market.cross_source.consistency"
            ]
            assert len(cs) == 1 and cs[0].status == ValidationStatus.NOT_APPLICABLE


class TestPolicyTolerances:
    def test_independent_price_and_volume_thresholds(self):
        policy = MarketPolicy(
            metric_tolerances={
                "price": MetricTolerance(Decimal("0.05"), Decimal("0.20")),
                "volume": MetricTolerance(Decimal("0.01"), Decimal("0.05")),
            }
        )
        assert policy.tolerance_for("close").normal_conflict_fraction == Decimal("0.05")
        assert policy.tolerance_for("open").normal_conflict_fraction == Decimal("0.05")
        assert policy.tolerance_for("volume").normal_conflict_fraction == Decimal("0.01")
        # Unconfigured metric falls back to the top-level default.
        assert policy.tolerance_for("other").normal_conflict_fraction == Decimal("0.02")

    def test_invalid_per_metric_cross_constraint_raises(self):
        with pytest.raises(ValueError):
            MetricTolerance(Decimal("0.10"), Decimal("0.05"))
        with pytest.raises(ValueError):
            MarketPolicy(
                metric_tolerances={"volume": MetricTolerance(Decimal("0.10"), Decimal("0.05"))}
            )

    def test_defensive_copy_and_read_only_mapping(self):
        source = {"price": {"normal": Decimal("0.05"), "severe": Decimal("0.20")}}
        policy = MarketPolicy(metric_tolerances=source)
        original = policy.tolerance_for("close").normal_conflict_fraction
        source["price"]["normal"] = Decimal("0.50")
        assert policy.tolerance_for("close").normal_conflict_fraction == original
        with pytest.raises(TypeError):
            policy.metric_tolerances["price"] = None  # type: ignore[index]


class TestQualityCriticality:
    def test_important_missing_low_vs_critical_blocked(self):
        open_missing = make_record("open", value=None)
        close_missing = make_record("close", value=None)
        assert evaluate_record_quality(open_missing, [])[0] == QualityStatus.LOW
        assert evaluate_record_quality(close_missing, [])[0] == QualityStatus.BLOCKED

    def test_partial_critical_corroboration_medium(self):
        policy = MarketPolicy(min_independent_sources=2)
        records = valid_row("yfinance")
        records += [
            make_record(m, value=v, source="alpha")
            for m, v in (("open", "100"), ("high", "102"), ("low", "99"), ("close", "101"))
        ]
        # volume exists only for yfinance => not fully corroborated.
        results = validate_market_records(
            records, expected_symbol=SYMBOL, target_date=TARGET, policy=policy
        )
        group, _ = aggregate_category_quality(CATEGORY, records, results, policy=policy)
        assert group.quality_status == QualityStatus.MEDIUM

    def test_fully_corroborated_critical_metrics_high(self):
        policy = MarketPolicy(min_independent_sources=2)
        records = valid_row("yfinance") + valid_row("alpha")
        results = validate_market_records(
            records, expected_symbol=SYMBOL, target_date=TARGET, policy=policy
        )
        group, _ = aggregate_category_quality(CATEGORY, records, results, policy=policy)
        assert group.quality_status == QualityStatus.HIGH


class TestGateValidation:
    def test_invalid_decided_at_raises(self):
        with pytest.raises(ValueError):
            build_gate_decision([_group(QualityStatus.HIGH)], decided_at="not-a-timestamp")

    def test_empty_input_is_blocked_not_normal(self):
        decision = build_gate_decision([], decided_at="2026-05-13T12:00:00Z")
        assert decision.decision == GateVerdict.BLOCKED
        assert decision.limitations

    def test_outputs_are_deterministically_sorted(self):
        groups = [
            _group(QualityStatus.HIGH, Criticality.CRITICAL, "zeta"),
            _group(QualityStatus.MEDIUM, Criticality.IMPORTANT, "alpha"),
        ]
        d1 = build_gate_decision(list(reversed(groups)), decided_at="2026-05-13T12:00:00Z")
        d2 = build_gate_decision(groups, decided_at="2026-05-13T12:00:00Z")
        assert d1.to_dict() == d2.to_dict()
        categories = [g.category for g in d1.group_statuses]
        assert categories == sorted(categories)
