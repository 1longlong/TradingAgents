"""Offline regression tests for the DQ gate Step 2 follow-up review.

These cover correctness gaps the original tests did not exercise. No network,
no LLM. Each section maps to one review item.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import MappingProxyType

import pandas as pd
import pytest

import tradingagents.dataflows.market_data_validator as validator
import tradingagents.evidence.validate as validate_mod
from tradingagents.evidence import (
    Criticality,
    EvidenceRecord,
    MarketPolicy,
    MetricTolerance,
    QualityStatus,
    ValidationClass,
    ValidationStatus,
    aggregate_category_quality,
    build_gate_decision,
    build_market_evidence_records,
    count_business_days,
    cross_source_consistency_results,
    evaluate_record_quality,
    make_market_evidence_id,
    validate_market_records,
)

RUN_ID = "run-reg"
SYMBOL = "COF"
TARGET = "2026-05-13"
FETCHED = "2026-05-13T12:00:00Z"
CATEGORY = "market"
PRICE_UNIT = "native_quote_currency"
VOLUME_UNIT = "shares"

PRICE_METRICS = ("open", "high", "low", "close")

_DEFAULT = {
    "open": "100", "high": "102", "low": "99", "close": "101", "volume": "1000000",
}


def mk(
    metric: str,
    value,
    *,
    source: str = "yfinance",
    ticker: str = SYMBOL,
    observed_at: str = TARGET,
    target_date: str = TARGET,
    unit: str = PRICE_UNIT,
    criticality=None,
    ticker_input: str | None = None,
) -> EvidenceRecord:
    """Build one market record with configurable identity fields."""
    normalized = None if value is None else Decimal(str(value))
    raw = str(normalized) if normalized is not None else ""
    if metric == "volume":
        unit = VOLUME_UNIT
    crit = criticality or (
        Criticality.CRITICAL if metric in ("close", "volume") else Criticality.IMPORTANT
    )
    return EvidenceRecord.build(
        evidence_id=make_market_evidence_id(RUN_ID, CATEGORY, source, metric, 0),
        run_id=RUN_ID,
        ticker_input=ticker_input or ticker,
        ticker_normalized=ticker,
        asset_type="stock",
        category=CATEGORY,
        metric_name=metric,
        value_raw=raw,
        value_normalized=normalized,
        unit_raw=unit,
        unit_normalized=unit,
        source_name=source,
        source_ref=f"{source}-ref",
        observed_at=observed_at,
        fetched_at=FETCHED,
        target_date=target_date,
        criticality=crit,
        validation_results=[],
    )


def row(source: str = "yfinance", values=None, **overrides) -> list[EvidenceRecord]:
    """A full OHLCV row for one source with optional per-field overrides."""
    values = values or _DEFAULT
    return [mk(m, values[m], source=source, **overrides) for m in PRICE_METRICS] + [
        mk("volume", values["volume"], source=source, **overrides)
    ]


def validate(records, policy=None):
    return validate_market_records(
        records,
        expected_symbol=SYMBOL,
        target_date=TARGET,
        policy=policy,
    )


def group_status(records, policy=None):
    results = validate(records, policy)
    group, statuses = aggregate_category_quality(CATEGORY, records, results, policy=policy)
    return group, statuses


# ---------------------------------------------------------------------------
# 1. Adapter
# ---------------------------------------------------------------------------


def _snapshot(monkeypatch, look_back_days=30):
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


class TestAdapterTruthfulness:
    def test_default_price_unit_is_neutral(self, monkeypatch):
        records = build_market_evidence_records(_snapshot(monkeypatch), RUN_ID)
        by_metric = {r.metric_name: r for r in records}
        assert by_metric["close"].unit_normalized == "native_quote_currency"
        assert by_metric["high"].unit_normalized == "native_quote_currency"
        assert by_metric["volume"].unit_normalized == "shares"

    def test_explicit_price_unit(self, monkeypatch):
        records = build_market_evidence_records(
            _snapshot(monkeypatch), RUN_ID, price_unit="USD"
        )
        by_metric = {r.metric_name: r for r in records}
        assert by_metric["close"].unit_normalized == "USD"
        assert by_metric["volume"].unit_normalized == "shares"

    def test_ticker_input_retained_normalized_from_snapshot(self, monkeypatch):
        records = build_market_evidence_records(
            _snapshot(monkeypatch), RUN_ID, ticker_input="COF.CL"
        )
        for record in records:
            assert record.ticker_input == "COF.CL"
            assert record.ticker_normalized == SYMBOL

    def test_evidence_id_index_stable_across_look_back_days(self, monkeypatch):
        short = build_market_evidence_records(_snapshot(monkeypatch, 5), RUN_ID)
        long = build_market_evidence_records(_snapshot(monkeypatch, 30), RUN_ID)
        assert [r.evidence_id for r in short] == [r.evidence_id for r in long]
        for record in long:
            # Id embeds the authoritative "market" category and the yfinance source.
            assert "/market/yfinance/" in record.evidence_id
            assert record.evidence_id.endswith("/0")


# ---------------------------------------------------------------------------
# 2. Completeness and dates
# ---------------------------------------------------------------------------


class TestCompletenessRequiredFields:
    @pytest.mark.parametrize(
        "field",
        [
            "ticker_normalized",
            "category",
            "metric_name",
            "source_name",
            "observed_at",
            "fetched_at",
            "target_date",
            "value_normalized",
            "unit_raw",
        ],
    )
    def test_missing_each_required_field_fails(self, field):
        records = row()
        close = [r for r in records if r.metric_name == "close"][0]
        # Rebuild the close record with one field blanked out.
        close = EvidenceRecord.build(
            evidence_id=close.evidence_id,
            run_id=close.run_id,
            ticker_input=close.ticker_input,
            ticker_normalized="" if field == "ticker_normalized" else close.ticker_normalized,
            asset_type=close.asset_type,
            category="" if field == "category" else close.category,
            metric_name="" if field == "metric_name" else close.metric_name,
            value_raw="" if field == "unit_raw" else close.value_raw,
            value_normalized=None if field == "value_normalized" else close.value_normalized,
            unit_raw="" if field == "unit_raw" else close.unit_raw,
            unit_normalized=close.unit_normalized,
            source_name="" if field == "source_name" else close.source_name,
            source_ref=close.source_ref,
            observed_at=None if field == "observed_at" else close.observed_at,
            fetched_at=None if field == "fetched_at" else close.fetched_at,
            target_date=None if field == "target_date" else close.target_date,
            criticality=close.criticality,
            validation_results=[],
        )
        records = [r for r in records if r.metric_name != "close"] + [close]
        results = validate(records)
        all_results = results[close.evidence_id]
        asserting = [
            r
            for r in all_results
            if r.validation_class == ValidationClass.COMPLETENESS
            and r.status == ValidationStatus.FAIL
        ]
        assert asserting, f"expected completeness FAIL when {field} missing"
        assert field in asserting[0].message


class TestBusinessDayBoundaries:
    def test_same_day_is_zero_age(self):
        assert count_business_days(date(2026, 5, 13), date(2026, 5, 13)) == 0

    def test_next_business_day_is_one(self):
        # Wed 2026-05-13 -> Thu 2026-05-14 (strictly after observed, through target)
        assert count_business_days(date(2026, 5, 13), date(2026, 5, 14)) == 1

    def test_weekend_not_counted(self):
        # Fri 2026-05-08 -> Mon 2026-05-11: Sun/Sat skipped, so age == 1.
        assert count_business_days(date(2026, 5, 8), date(2026, 5, 11)) == 1

    def test_week_span(self):
        # Wed 2026-05-06 -> Wed 2026-05-13 = 5 business days strictly after.
        assert count_business_days(date(2026, 5, 6), date(2026, 5, 13)) == 5


class TestTargetDateAgreement:
    def test_mismatching_target_date_fails(self):
        records = row(target_date="2026-05-14")
        results = validate(records)
        close = [r for r in records if r.metric_name == "close"][0]
        agreement = [
            r
            for r in results[close.evidence_id]
            if r.rule_id == "market.freshness.target_date_agreement"
        ]
        assert agreement and agreement[0].status == ValidationStatus.FAIL

    def test_malformed_date_fails_not_silently_accepted(self):
        records = row()
        close = [r for r in records if r.metric_name == "close"][0]
        # Malformed target_date on one record.
        records = [r for r in records if r.metric_name != "close"] + [
            mk("close", _DEFAULT["close"], target_date="not-a-date")
        ]
        results = validate(records)
        malformed = [
            r
            for r in results[close.evidence_id]
            if r.rule_id == "market.freshness.malformed_date"
        ]
        assert malformed and malformed[0].status == ValidationStatus.FAIL

    def test_malformed_observed_at_fails(self):
        records = row()
        close = [r for r in records if r.metric_name == "close"][0]
        records = [r for r in records if r.metric_name != "close"] + [
            mk("close", _DEFAULT["close"], observed_at="2026/05/13")
        ]
        results = validate(records)
        malformed = [
            r
            for r in results[close.evidence_id]
            if r.rule_id == "market.freshness.malformed_date"
        ]
        assert malformed and malformed[0].status == ValidationStatus.FAIL


# ---------------------------------------------------------------------------
# 3. Per-metric policy
# ---------------------------------------------------------------------------


class TestPerMetricPolicy:
    def test_price_and_volume_independently_configured(self):
        policy = MarketPolicy(
            metric_tolerances={
                "price": MetricTolerance("0.01", "0.05"),
                "volume": MetricTolerance("0.05", "0.25"),
            }
        )
        assert policy.tolerance_for("close") == MetricTolerance("0.01", "0.05")
        assert policy.tolerance_for("volume") == MetricTolerance("0.05", "0.25")

    def test_dict_form_accepted_and_validated(self):
        policy = MarketPolicy(
            metric_tolerances={"price": {"normal": "0.02", "severe": "0.08"}}
        )
        assert policy.tolerance_for("close") == MetricTolerance("0.02", "0.08")
        # Unknown metric falls back to top-level defaults.
        assert policy.tolerance_for("something") == MetricTolerance("0.02", "0.10")

    def test_defensive_copy_prevents_mutation(self):
        source = {"price": {"normal": "0.01", "severe": "0.05"}}
        policy = MarketPolicy(metric_tolerances=source)
        source["price"]["normal"] = "0.99"
        source["price"] = {"normal": "0.50", "severe": "0.60"}
        assert policy.tolerance_for("close") == MetricTolerance("0.01", "0.05")
        assert isinstance(policy.metric_tolerances, MappingProxyType)

    def test_invalid_cross_constraint_raises_per_metric(self):
        with pytest.raises(ValueError):
            MarketPolicy(metric_tolerances={"price": MetricTolerance("0.05", "0.05")})
        with pytest.raises(ValueError):
            MarketPolicy(metric_tolerances={"volume": {"normal": "0.20", "severe": "0.10"}})

    def test_invalid_metric_tolerance_type_raises(self):
        with pytest.raises(ValueError):
            MarketPolicy(metric_tolerances={"price": "bogus"})


# ---------------------------------------------------------------------------
# 4. OHLC row isolation
# ---------------------------------------------------------------------------


class TestOhlcRowIsolation:
    def test_two_sources_valid_A_invalid_B(self):
        a = row("A")
        b = row("B", values={"open": "100", "high": "90", "low": "99", "close": "101", "volume": "100"})
        records = a + b
        results = validate(records)
        # Source A's OHLC relationship PASSes.
        a_high = [r for r in a if r.metric_name == "high"][0]
        a_rel = [
            r
            for r in results[a_high.evidence_id]
            if r.rule_id == "market.format.ohlc_relationships"
        ]
        assert a_rel and a_rel[0].status == ValidationStatus.PASS
        # Source B's OHLC relationship FAILs (high=90 < close=101 & open=100).
        b_high = [r for r in b if r.metric_name == "high"][0]
        b_rel = [
            r
            for r in results[b_high.evidence_id]
            if r.rule_id == "market.format.ohlc_relationships"
            and r.status == ValidationStatus.FAIL
        ]
        assert b_rel, "source B's invalid OHLC row must fail"

    def test_every_price_record_gets_its_own_row_result(self):
        records = row()
        results = validate(records)
        for metric in PRICE_METRICS:
            rec = [r for r in records if r.metric_name == metric][0]
            rel = [
                r
                for r in results[rec.evidence_id]
                if r.rule_id == "market.format.ohlc_relationships"
            ]
            assert rel, f"price metric {metric} must get an OHLC result"


# ---------------------------------------------------------------------------
# 5. Cross-source consistency
# ---------------------------------------------------------------------------


class TestCrossSourceConsistency:
    def test_input_permutation_invariance(self):
        records = row("A") + row("B")
        rev = list(reversed(records))
        r1 = validate(records)
        r2 = validate(rev)
        for rec in records:
            cross1 = sorted(
                [
                    r.to_dict()
                    for r in r1[rec.evidence_id]
                    if r.validation_class == ValidationClass.CROSS_SOURCE_CONSISTENCY
                ],
                key=lambda d: d["evidence_id"],
            )
            cross2 = sorted(
                [
                    r.to_dict()
                    for r in r2[rec.evidence_id]
                    if r.validation_class == ValidationClass.CROSS_SOURCE_CONSISTENCY
                ],
                key=lambda d: d["evidence_id"],
            )
            assert cross1 == cross2

    def test_three_source_median_reference_retains_outlier(self):
        # close values 100 (A), 101 (B), 130 (C). Median = 101.
        policy = MarketPolicy(severe_conflict_fraction=Decimal("0.10"))
        source_records = [
            mk("close", "100", source="A"),
            mk("close", "101", source="B"),
            mk("close", "130", source="C"),
        ]
        cross = cross_source_consistency_results(source_records, policy)
        by_id = {r.evidence_id: r for r in cross}
        # Outlier C (~28.7% vs median 101) is FAIL; B (0%) and A (~1%) are PASS.
        assert by_id[source_records[2].evidence_id].status == ValidationStatus.FAIL
        assert by_id[source_records[1].evidence_id].status == ValidationStatus.PASS
        assert by_id[source_records[0].evidence_id].status == ValidationStatus.PASS

    def test_pass_emitted_for_every_in_tolerance_record(self):
        records = row("A") + row("B")
        cross = cross_source_consistency_results(records, MarketPolicy())
        assert len(cross) == len(records)
        for record in records:
            rec_results = [r for r in cross if r.evidence_id == record.evidence_id]
            assert rec_results, "every record must get its own cross-source result"
            assert rec_results[0].status == ValidationStatus.PASS

    def test_no_comparison_across_dates(self):
        records = row("A") + row("B", observed_at="2026-05-12")
        cross = cross_source_consistency_results(records, MarketPolicy())
        # Different observed_at -> each date is a separate group of 1 -> NOT_APPLICABLE.
        assert all(r.status == ValidationStatus.NOT_APPLICABLE for r in cross)

    def test_no_comparison_across_units(self):
        records = row("A")
        records += [mk("close", "101", source="B", unit="EUR")]
        cross = cross_source_consistency_results(records, MarketPolicy())
        by_id = {r.evidence_id: r.status for r in cross}
        # Unit differs => groups of 1 => NOT_APPLICABLE for the close records.
        assert all(s == ValidationStatus.NOT_APPLICABLE for s in by_id.values())
        # The other A metrics (USD vs EUR mismatch) are single-source groups too.
        assert len(cross) == len(records)

    def test_no_comparison_across_tickers(self):
        records = row("A")
        records += [mk("close", "101", source="B", ticker="MSFT")]
        cross = cross_source_consistency_results(records, MarketPolicy())
        assert all(r.status == ValidationStatus.NOT_APPLICABLE for r in cross)


# ---------------------------------------------------------------------------
# 6. Quality precedence and High coverage
# ---------------------------------------------------------------------------


class TestQualityPrecedence:
    def test_missing_important_is_low(self):
        # open is important; a missing usable value must be Low, not Blocked.
        records = [r for r in row() if r.metric_name != "open"] + [mk("open", None)]
        open_rec = next(r for r in records if r.metric_name == "open")
        results = validate(records)
        status, _ = evaluate_record_quality(open_rec, results[open_rec.evidence_id])
        assert status == QualityStatus.LOW
        group, _ = group_status(records)
        assert group.quality_status == QualityStatus.LOW

    def test_missing_critical_is_blocked(self):
        # close is critical; a missing usable value must be Blocked.
        records = [r for r in row() if r.metric_name != "close"] + [mk("close", None)]
        close_rec = next(r for r in records if r.metric_name == "close")
        results = validate(records)
        status, _ = evaluate_record_quality(close_rec, results[close_rec.evidence_id])
        assert status == QualityStatus.BLOCKED
        group, _ = group_status(records)
        assert group.quality_status == QualityStatus.BLOCKED

    def test_partial_multi_source_coverage_is_medium_not_high(self):
        # close corroborated by A+B; volume only by A => partial. High needs
        # every critical metric corroborated. B provides a full PRICE row (so its
        # OHLC relationship holds) but deliberately omits volume.
        policy = MarketPolicy(min_independent_sources=2)
        records = row("A")
        records.append(mk("close", "101", source="B"))
        records.append(mk("open", "100", source="B"))
        records.append(mk("high", "102", source="B"))
        records.append(mk("low", "99", source="B"))
        # volume (critical) only has A (single) => partial.
        results = validate(records, policy)
        group, _ = aggregate_category_quality(CATEGORY, records, results, policy=policy)
        assert group.quality_status == QualityStatus.MEDIUM

    def test_fully_corroborated_critical_metrics_is_high(self):
        policy = MarketPolicy(min_independent_sources=2)
        # Close and volume (both critical) each corroborated by 2 sources, and
        # all in tolerance (identical values).
        records = row("A") + row("B")
        results = validate(records, policy)
        group, _ = aggregate_category_quality(CATEGORY, records, results, policy=policy)
        assert group.quality_status == QualityStatus.HIGH


# ---------------------------------------------------------------------------
# 7. Gate determinism
# ---------------------------------------------------------------------------


def _group(status, criticality=Criticality.CRITICAL, category="market", reasons=("code",)):
    from tradingagents.evidence import EvidenceGroupQuality

    return EvidenceGroupQuality(
        category=category,
        quality_status=status,
        criticality=criticality,
        evidence_ids=[f"{RUN_ID}/{category}/yfinance/close/0"],
        source_count=1,
        independent_source_count=1,
        reason_codes=list(reasons),
        human_readable_reason="test",
    )


class TestGateDeterminism:
    def test_decided_at_validated(self):
        with pytest.raises(ValueError):
            build_gate_decision([_group(QualityStatus.HIGH)], decided_at="not-a-date")
        with pytest.raises(ValueError):
            build_gate_decision([_group(QualityStatus.HIGH)], decided_at="")
        # Valid ISO accepted.
        d = build_gate_decision([_group(QualityStatus.HIGH)], decided_at="2026-05-13T12:00:00Z")
        assert d.decided_at == "2026-05-13T12:00:00Z"

    def test_outputs_sorted_deterministically(self):
        from tradingagents.evidence import EvidenceGroupQuality

        g1 = EvidenceGroupQuality(
            category="z_cat",
            quality_status=QualityStatus.HIGH,
            criticality=Criticality.CRITICAL,
            evidence_ids=["z/id"],
            source_count=1,
            independent_source_count=1,
            reason_codes=["z_code"],
            human_readable_reason="z",
        )
        g2 = EvidenceGroupQuality(
            category="a_cat",
            quality_status=QualityStatus.MEDIUM,
            criticality=Criticality.IMPORTANT,
            evidence_ids=["a/id"],
            source_count=1,
            independent_source_count=1,
            reason_codes=["a_code"],
            human_readable_reason="a",
        )
        d1 = build_gate_decision([g1, g2], decided_at="2026-05-13T12:00:00Z")
        d2 = build_gate_decision([g2, g1], decided_at="2026-05-13T12:00:00Z")  # reversed
        assert d1.to_dict() == d2.to_dict()
        assert [g.category for g in d1.group_statuses] == ["a_cat", "z_cat"]

    def test_empty_input_is_blocked_fail_closed(self):
        d = build_gate_decision([], decided_at="2026-05-13T12:00:00Z")
        assert d.decision.value == "blocked"
        assert d.limitations


# ---------------------------------------------------------------------------
# Helper sanity: cross-source via the public validate_market_records grouping
# ---------------------------------------------------------------------------


class TestCrossSourceGroupKeyExact:
    def test_grouping_uses_ticker_metric_date_unit(self):
        # Two records identical except source and observed_at => separate groups.
        records = [
            mk("close", "100", source="A", observed_at="2026-05-13"),
            mk("close", "101", source="B", observed_at="2026-05-12"),
        ]
        cross = cross_source_consistency_results(records, MarketPolicy())
        assert all(r.status == ValidationStatus.NOT_APPLICABLE for r in cross)


# ---------------------------------------------------------------------------
# 8. Review-only fixes: Decimal-only median and symmetric two-source spread
# ---------------------------------------------------------------------------


class TestDecimalMedianNoFloat:
    def test_median_uses_decimal_only_high_precision(self):
        # Values at a magnitude where a float conversion would collapse the
        # trailing tenth-decimal place; a Decimal median must stay exact.
        records = [
            mk("close", Decimal("1000000000000.0000000001"), source="A"),
            mk("close", Decimal("1000000000000.0000000002"), source="B"),
            mk("close", Decimal("1000000000000.0000000003"), source="C"),
        ]
        ref = validate_mod._reference_value(records)
        assert ref == Decimal("1000000000000.0000000002")
        assert isinstance(ref, Decimal)

    def test_even_decimal_median_is_exact_mean(self):
        # Even count (4 sources) -> mean of the two middle Decimals, exact.
        records = [
            mk("close", Decimal("1.0000000000"), source="A"),
            mk("close", Decimal("1.0000000002"), source="B"),
            mk("close", Decimal("1.0000000004"), source="C"),
            mk("close", Decimal("1.0000000006"), source="D"),
        ]
        ref = validate_mod._reference_value(records)
        assert ref == Decimal("1.0000000003")

    def test_unaffected_by_product_of_median_pipeline(self):
        # The 3+ pipeline compares against the Decimal median; verify the
        # returned deviation is derived from exact Decimal division.
        records = [
            mk("close", Decimal("1000000000000.0000000001"), source="A"),
            mk("close", Decimal("1000000000000.0000000002"), source="B"),
            mk("close", Decimal("1000000000000.0000000003"), source="C"),
        ]
        cross = cross_source_consistency_results(records, MarketPolicy())
        by_id = {r.evidence_id: r for r in cross}
        middle = next(r for r in records if r.source_name == "B")
        # The middle record sits exactly on the median -> deviation 0 -> PASS.
        assert by_id[middle.evidence_id].actual == str(Decimal("0.0000"))
        assert by_id[middle.evidence_id].status == ValidationStatus.PASS


class TestTwoSourceSymmetricDeviation:
    def test_two_source_100_and_110_share_spread_and_status(self):
        records = [
            mk("close", "100", source="A"),
            mk("close", "110", source="B"),
        ]
        cross = cross_source_consistency_results(records, MarketPolicy())
        by_id = {r.evidence_id: r for r in cross}
        # Symmetric spread 10/105 = 0.095238... -> quantized 0.0952 for BOTH.
        a = by_id[records[0].evidence_id]
        b = by_id[records[1].evidence_id]
        assert a.actual == str(Decimal("0.0952"))
        assert b.actual == str(Decimal("0.0952"))
        # Both share the same status (above normal 0.02, below severe 0.10).
        assert a.status == ValidationStatus.WARNING
        assert b.status == ValidationStatus.WARNING

    def test_two_zero_values_pass(self):
        records = [
            mk("close", "0", source="A"),
            mk("close", "0", source="B"),
        ]
        cross = cross_source_consistency_results(records, MarketPolicy())
        by_id = {r.evidence_id: r for r in cross}
        assert by_id[records[0].evidence_id].status == ValidationStatus.PASS
        assert by_id[records[1].evidence_id].status == ValidationStatus.PASS
        assert by_id[records[0].evidence_id].actual == str(Decimal("0"))

    def test_unequal_values_with_zero_midpoint_fail(self):
        # a + b == 0 with a != b -> midpoint zero -> FAIL (not N/A, not PASS).
        records = [
            mk("close", "-10", source="A"),
            mk("close", "10", source="B"),
        ]
        cross = cross_source_consistency_results(records, MarketPolicy())
        by_id = {r.evidence_id: r for r in cross}
        assert by_id[records[0].evidence_id].status == ValidationStatus.FAIL
        assert by_id[records[1].evidence_id].status == ValidationStatus.FAIL

    def test_two_source_permutation_invariance(self):
        forward = cross_source_consistency_results(
            [
                mk("close", "100", source="A"),
                mk("close", "110", source="B"),
            ],
            MarketPolicy(),
        )
        backward = cross_source_consistency_results(
            [
                mk("close", "110", source="B"),
                mk("close", "100", source="A"),
            ],
            MarketPolicy(),
        )
        def sig(rr):
            return sorted((r.actual, r.status.value) for r in rr)

        assert sig(forward) == sig(backward)
