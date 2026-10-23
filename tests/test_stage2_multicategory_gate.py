"""Stage 2 multi-category gate: deterministic offline tests.

Covers the multi-category gate decision, the optional-category
unavailable/insufficient results, and the pure evaluation engine. No network, no
paid LLM; the market snapshot is monkeypatched for the engine tests and the
decision/group tests construct records directly.

Sections:
- Multi-category gate verdict precedence (blocked > degraded > normal).
- Optional-category unavailable/insufficient explicit result.
- Versioned policy degrade-on-unavailable behavior.
- Point-in-time / deterministic-ID integrity.
- Legacy compatibility (single-category gate decision unchanged).
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pytest

import tradingagents.dataflows.market_data_validator as validator
from tradingagents.evidence import (
    CATEGORY_FUNDAMENTALS,
    CATEGORY_MARKET,
    CATEGORY_NEWS,
    CATEGORY_SENTIMENT,
    OPTIONAL_CATEGORIES,
    Criticality,
    EvidenceGroupQuality,
    EvidenceRecord,
    QualityStatus,
    build_multi_category_gate_decision,
    build_unavailable_category,
)
from tradingagents.evidence.multi_category_gate import (
    build_multi_category_run_id,
    evaluate_multi_category_gate,
)
from tradingagents.evidence.policy import (
    DEFAULT_MULTI_CATEGORY_POLICY,
    REASON_INSUFFICIENT_STRUCTURED_EVIDENCE,
    REASON_UNAVAILABLE_NO_STRUCTURED_SOURCE,
    CategoryPolicy,
    MultiCategoryPolicy,
)

SYMBOL = "COF"
TARGET = "2026-05-13"
FETCHED = "2026-05-13T12:00:00Z"


def _market(status: QualityStatus, *, criticality: Criticality = Criticality.CRITICAL) -> EvidenceGroupQuality:
    return EvidenceGroupQuality(
        category=CATEGORY_MARKET,
        quality_status=status,
        criticality=criticality,
        evidence_ids=["2026-05-13/COF/market/yfinance/close/0"],
        source_count=2,
        independent_source_count=2,
        reason_codes=["high"] if status == QualityStatus.HIGH else ["code"],
        human_readable_reason="market",
    )


def _optional(category: str, status: QualityStatus = QualityStatus.LOW) -> EvidenceGroupQuality:
    return build_unavailable_category(category) if status == QualityStatus.LOW else EvidenceGroupQuality(
        category=category,
        quality_status=status,
        criticality=Criticality.IMPORTANT,
        evidence_ids=[],
        source_count=1,
        independent_source_count=1,
        reason_codes=["high"],
        human_readable_reason="optional",
    )


def _all_optional(status: QualityStatus = QualityStatus.LOW) -> list[EvidenceGroupQuality]:
    return [_optional(c, status) for c in OPTIONAL_CATEGORIES]


# ---------------------------------------------------------------------------
# build_unavailable_category
# ---------------------------------------------------------------------------


class TestUnavailableCategory:
    def test_explicit_no_structured_source(self):
        group = build_unavailable_category(CATEGORY_NEWS)
        assert group.category == CATEGORY_NEWS
        assert group.quality_status == QualityStatus.LOW
        assert group.source_count == 0
        assert group.independent_source_count == 0
        assert group.evidence_ids == []
        assert REASON_UNAVAILABLE_NO_STRUCTURED_SOURCE in group.reason_codes
        assert "no trustworthy structured evidence" in group.human_readable_reason

    def test_insufficient_reason_and_message(self):
        group = build_unavailable_category(
            CATEGORY_FUNDAMENTALS,
            reason=REASON_INSUFFICIENT_STRUCTURED_EVIDENCE,
        )
        assert REASON_INSUFFICIENT_STRUCTURED_EVIDENCE in group.reason_codes
        message = "Lacking evidence"
        assert build_unavailable_category(CATEGORY_SENTIMENT, message=message).human_readable_reason == message

    def test_deterministic_and_json_safe(self):
        a = build_unavailable_category(CATEGORY_NEWS)
        b = build_unavailable_category(CATEGORY_NEWS)
        assert a.to_dict() == b.to_dict()
        import json
        assert json.loads(json.dumps(a.to_dict())) == a.to_dict()


# ---------------------------------------------------------------------------
# Multi-category gate verdict precedence
# ---------------------------------------------------------------------------


class TestMultiCategoryVerdict:
    def test_market_high_with_degrade_off_is_normal(self):
        policy = MultiCategoryPolicy(optional={
            c: CategoryPolicy(category=c, degrade_on_unavailable=False) for c in OPTIONAL_CATEGORIES
        })
        decision = build_multi_category_gate_decision(
            [_market(QualityStatus.HIGH)] + _all_optional(),
            decided_at=FETCHED,
            policy=policy,
        )
        assert decision.decision.value == "normal"

    def test_market_high_with_degrade_on_is_degraded(self):
        decision = build_multi_category_gate_decision(
            [_market(QualityStatus.HIGH)] + _all_optional(),
            decided_at=FETCHED,
            policy=DEFAULT_MULTI_CATEGORY_POLICY,
        )
        assert decision.decision.value == "degraded"
        assert any(reason for g in decision.group_statuses for reason in g.reason_codes if reason == REASON_UNAVAILABLE_NO_STRUCTURED_SOURCE)

    def test_market_medium_is_normal_not_degraded(self):
        policy = MultiCategoryPolicy(optional={
            c: CategoryPolicy(category=c, degrade_on_unavailable=False) for c in OPTIONAL_CATEGORIES
        })
        decision = build_multi_category_gate_decision(
            [_market(QualityStatus.MEDIUM)] + _all_optional(),
            decided_at=FETCHED,
            policy=policy,
        )
        assert decision.decision.value == "normal"

    def test_market_low_is_degraded(self):
        policy = MultiCategoryPolicy(optional={
            c: CategoryPolicy(category=c, degrade_on_unavailable=False) for c in OPTIONAL_CATEGORIES
        })
        decision = build_multi_category_gate_decision(
            [_market(QualityStatus.LOW)] + _all_optional(),
            decided_at=FETCHED,
            policy=policy,
        )
        assert decision.decision.value == "degraded"

    def test_market_blocked_is_blocked_fail_closed(self):
        policy = MultiCategoryPolicy(optional={
            c: CategoryPolicy(category=c, degrade_on_unavailable=False) for c in OPTIONAL_CATEGORIES
        })
        # Optional categories degrade but never block; market blocked -> blocked.
        decision = build_multi_category_gate_decision(
            [_market(QualityStatus.BLOCKED)] + _all_optional(),
            decided_at=FETCHED,
            policy=policy,
        )
        assert decision.decision.value == "blocked"
        assert decision.limitations

    def test_no_market_group_is_blocked_fail_closed(self):
        policy = MultiCategoryPolicy(optional={
            c: CategoryPolicy(category=c, degrade_on_unavailable=False) for c in OPTIONAL_CATEGORIES
        })
        decision = build_multi_category_gate_decision(
            [_optional(CATEGORY_NEWS, QualityStatus.HIGH)],
            decided_at=FETCHED,
            policy=policy,
        )
        assert decision.decision.value == "blocked"

    def test_optional_categories_never_block(self):
        # A degraded optional category with a market High group and degrade OFF
        # must not block; and a blocked optional category must still not block.
        policy = MultiCategoryPolicy(optional={
            c: CategoryPolicy(category=c, degrade_on_unavailable=False) for c in OPTIONAL_CATEGORIES
        })
        decision = build_multi_category_gate_decision(
            [_market(QualityStatus.HIGH), _optional(CATEGORY_NEWS, QualityStatus.BLOCKED)],
            decided_at=FETCHED,
            policy=policy,
        )
        assert decision.decision.value == "normal"

    def test_groups_sorted_deterministically(self):
        decision = build_multi_category_gate_decision(
            [_market(QualityStatus.HIGH)] + _all_optional(),
            decided_at=FETCHED,
            policy=DEFAULT_MULTI_CATEGORY_POLICY,
        )
        categories = [g.category for g in decision.group_statuses]
        assert categories == sorted(categories)

    def test_invalid_group_type_raises(self):
        with pytest.raises(ValueError):
            build_multi_category_gate_decision(["not-a-group"], decided_at=FETCHED)

    def test_invalid_decided_at_raises(self):
        with pytest.raises(ValueError):
            build_multi_category_gate_decision(
                [_market(QualityStatus.HIGH)], decided_at="not-a-date"
            )


# ---------------------------------------------------------------------------
# Versioned policy degrade-on-unavailable
# ---------------------------------------------------------------------------


class TestVersionedPolicy:
    def test_default_degrades_on_unavailable(self):
        assert DEFAULT_MULTI_CATEGORY_POLICY.policy_version == "2.0"
        assert all(
            DEFAULT_MULTI_CATEGORY_POLICY.optional[c].degrade_on_unavailable
            for c in OPTIONAL_CATEGORIES
        )

    def test_missing_optional_category_treated_as_optional_not_critical(self):
        policy = DEFAULT_MULTI_CATEGORY_POLICY
        assert policy.category_role(CATEGORY_MARKET).value == "critical"
        assert policy.category_role(CATEGORY_NEWS).value == "optional"
        # Unknown category never escalates to critical.
        assert policy.category_role("macro").value == "optional"

    def test_category_policy_requires_optional_role(self):
        with pytest.raises(ValueError):
            CategoryPolicy(category="x", role=Criticality.CRITICAL)  # type: ignore[arg-type]

    def test_category_policy_validates_min_sources(self):
        with pytest.raises(ValueError):
            CategoryPolicy(category="news", min_independent_sources=0)

    def test_multicategory_policy_defensive_copy(self):
        source = {"news": {"min_independent_sources": 2}}
        policy = MultiCategoryPolicy(optional=source)
        source["news"]["min_independent_sources"] = 99
        assert policy.optional["news"].min_independent_sources == 2

    def test_market_role_must_be_critical(self):
        with pytest.raises(ValueError):
            MultiCategoryPolicy(market_role=Criticality.IMPORTANT)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Engine + point-in-time / deterministic IDs
# ---------------------------------------------------------------------------


def _df():
    dates = pd.bdate_range("2026-04-01", "2026-05-20")
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
def snapshot(monkeypatch):
    monkeypatch.setattr(validator, "load_ohlcv", lambda s, d, fill_gaps=True: _df())


class TestEngine:
    def test_market_only_structured_optional_unavailable(self, snapshot):
        result = evaluate_multi_category_gate(
            trade_date=TARGET,
            symbol=SYMBOL,
            now_provider=lambda: FETCHED,
        )
        assert result.verdict == "degraded"
        cats = {g["category"]: g for g in result.groups}
        assert set(cats) == {CATEGORY_MARKET, *OPTIONAL_CATEGORIES}
        assert cats[CATEGORY_MARKET]["quality_status"] in ("High", "Medium", "Low")
        for category in OPTIONAL_CATEGORIES:
            assert cats[category]["quality_status"] == "Low"
            assert REASON_UNAVAILABLE_NO_STRUCTURED_SOURCE in cats[category]["reason_codes"]
        assert result.gate_decision.policy_version == "2.0"
        assert result.error is None

    def test_deterministic_run_id_derived_from_inputs(self):
        assert build_multi_category_run_id(TARGET, "COF") == f"{TARGET}/COF"
        assert build_multi_category_run_id("2026-05-13", "COF") == "2026-05-13/COF"

    def test_engine_deterministic_for_fixed_snapshot(self, snapshot):
        a = evaluate_multi_category_gate(trade_date=TARGET, symbol=SYMBOL, now_provider=lambda: FETCHED)
        b = evaluate_multi_category_gate(trade_date=TARGET, symbol=SYMBOL, now_provider=lambda: FETCHED)
        assert a.to_dict() == b.to_dict()

    def test_engine_json_serializable(self, snapshot):
        import json
        result = evaluate_multi_category_gate(trade_date=TARGET, symbol=SYMBOL, now_provider=lambda: FETCHED)
        payload = result.to_dict()
        assert json.loads(json.dumps(payload)) == payload

    def test_point_in_time_lookahead_blocks_market(self):
        # A market record observed after the target date is a look-ahead hard
        # blocker; it must land the market group on Blocked and the whole gate on
        # blocked (fail closed), no matter what an optional category claims.
        future = "2026-05-14"
        from tradingagents.evidence import (
            aggregate_category_quality,
            make_market_evidence_id,
            validate_market_records,
        )
        record = EvidenceRecord.build(
            evidence_id=make_market_evidence_id("2026-05-13/COF", CATEGORY_MARKET, "yfinance", "close", 0),
            run_id="2026-05-13/COF",
            ticker_input=SYMBOL,
            ticker_normalized=SYMBOL,
            asset_type="stock",
            category=CATEGORY_MARKET,
            metric_name="close",
            value_raw="101",
            value_normalized=Decimal("101"),
            unit_raw="native_quote_currency",
            unit_normalized="native_quote_currency",
            source_name="yfinance",
            source_ref="yfinance",
            observed_at=future,  # after TARGET -> look-ahead
            fetched_at=FETCHED,
            target_date=TARGET,
            criticality=Criticality.CRITICAL,
            validation_results=[],
        )
        results = validate_market_records(
            [record], expected_symbol=SYMBOL, target_date=TARGET
        )
        group, _ = aggregate_category_quality(CATEGORY_MARKET, [record], results)
        assert group.quality_status == QualityStatus.BLOCKED
        policy = MultiCategoryPolicy(optional={
            c: CategoryPolicy(category=c, degrade_on_unavailable=False) for c in OPTIONAL_CATEGORIES
        })
        decision = build_multi_category_gate_decision(
            [group] + _all_optional(),
            decided_at=FETCHED,
            policy=policy,
        )
        assert decision.decision.value == "blocked"

    def test_engine_snapshot_is_point_in_time(self, snapshot):
        result = evaluate_multi_category_gate(
            trade_date=TARGET, symbol=SYMBOL, now_provider=lambda: FETCHED
        )
        records = result.evidence_records
        assert records, "market evidence records present"
        for record in records:
            assert record["observed_at"] <= TARGET, "no record observed after target"


# ---------------------------------------------------------------------------
# Legacy compatibility: single-category build_gate_decision unchanged
# ---------------------------------------------------------------------------


class TestLegacyCompatibility:
    def test_single_category_decision_still_works(self):
        from tradingagents.evidence import build_gate_decision

        policy = MultiCategoryPolicy(optional={
            c: CategoryPolicy(category=c, degrade_on_unavailable=False) for c in OPTIONAL_CATEGORIES
        })
        legacy = build_gate_decision(
            [_market(QualityStatus.HIGH)],
            decided_at=FETCHED,
        )
        assert legacy.decision.value == "normal"
        # The multi-category builder behaves identically for a market-only input
        # with no optional categories configured.
        multi = build_multi_category_gate_decision(
            [_market(QualityStatus.HIGH)],
            decided_at=FETCHED,
            policy=policy,
        )
        assert multi.decision.value == "normal"
