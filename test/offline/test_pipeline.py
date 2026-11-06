"""Graph adapter, sizing, and trading pipeline tests."""

from __future__ import annotations

import itertools
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from safety.engine import SafetyEngine
from trading.approval import HumanApprovalGate
from trading.audit import AuditLog
from trading.models import (
    ConfigValidationError,
    DecisionAction,
    DecisionStatus,
    DecisionValidationError,
    EventType,
    MarketQuote,
    OrderType,
    SafetyConfig,
)
from trading.pipeline import (
    SizingPolicy,
    TradingPipeline,
    decision_from_final_state,
)
from trading.portfolio import Portfolio

FIXED_NOW = datetime(2024, 1, 5, 21, 0, tzinfo=timezone.utc)


class _FixedClock:
    def now(self) -> datetime:
        return FIXED_NOW

    def is_simulated(self) -> bool:
        return False

    def simulation_date(self):
        return None


def _seq(prefix: str):
    counter = itertools.count(1)
    return lambda: f"{prefix}-{next(counter)}"


def _setup(
    tmp_path: Path,
    *,
    cash="10000",
    config=None,
    sizing=None,
):
    clock = _FixedClock()
    config = config or SafetyConfig()
    portfolio = Portfolio(
        Decimal(cash),
        fee_model=config.fee_model(),
        clock=clock.now,
    )
    audit = AuditLog(
        tmp_path / "audit.jsonl",
        clock=clock.now,
        id_factory=_seq("evt"),
    )
    engine = SafetyEngine(
        config,
        portfolio,
        audit,
        clock=clock,
        evaluation_id_factory=_seq("eval"),
        execution_id_factory=_seq("exec"),
    )
    gate = HumanApprovalGate(
        audit,
        config,
        clock=clock,
        id_factory=_seq("req"),
    )
    pipeline = TradingPipeline(
        engine,
        gate,
        portfolio,
        config,
        sizing=sizing,
    )
    return pipeline, engine, portfolio, audit, clock, config


def _quote(price="100", symbol="NVDA"):
    return MarketQuote(
        symbol=symbol,
        price=Decimal(price),
        as_of=FIXED_NOW,
    )


def _final_state(
    decision="**Rating**: Buy\n\nEnter the position.",
    *,
    symbol="NVDA",
    trade_date="2024-01-05",
    **extra,
):
    state = {
        "final_trade_decision": decision,
        "company_of_interest": symbol,
        "trade_date": trade_date,
    }
    state.update(extra)
    return state


def _advisory_decision(text="**Rating**: Buy"):
    return decision_from_final_state(
        {"final_trade_decision": text},
        "run-1",
        "NVDA",
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "text,expected",
    [
        ("**Rating**: Buy", DecisionAction.BUY),
        ("Rating: Overweight", DecisionAction.BUY),
        ("Rating: Sell", DecisionAction.SELL),
        ("Rating: Underweight", DecisionAction.SELL),
        ("Rating: Hold", DecisionAction.HOLD),
        ("No directional call here.", DecisionAction.REVIEW),
        ("", DecisionAction.REVIEW),
    ],
)
def test_fr01_adapter_maps_ratings_and_unparseable_output(text, expected):
    """[FR-01] Graph prose maps to the advisory decision enum."""
    decision = decision_from_final_state(
        {"final_trade_decision": text},
        "run-1",
        "NVDA",
    )
    assert decision.action is expected
    assert decision.quantity is None
    assert decision.order_type is OrderType.MARKET
    assert decision.limit_price is None
    assert decision.run_id == "run-1"
    assert decision.symbol == "NVDA"
    assert decision.decision_id == "run-1:NVDA"


@pytest.mark.unit
def test_fr01_adapter_ignores_llm_supplied_numbers():
    """[FR-01] LLM quantities and prices never become order fields."""
    final_state = _final_state(
        "**Rating**: Buy\n\nBuy 999 shares at $1.00 immediately.",
        quantity=999,
        entry_price=1.0,
        position_sizing="100% of portfolio",
    )

    decision = decision_from_final_state(final_state, "run-1", "NVDA")

    assert decision.action is DecisionAction.BUY
    assert decision.quantity is None
    assert decision.limit_price is None
    assert decision.order_type is OrderType.MARKET


@pytest.mark.unit
def test_fr01_adapter_includes_trade_date_and_rejects_non_mapping():
    """[FR-01] Decision identity is deterministic and input shape is validated."""
    decision = decision_from_final_state(_final_state(), "run-1", "NVDA")
    assert decision.decision_id == "run-1:NVDA:2024-01-05"

    with pytest.raises(DecisionValidationError):
        decision_from_final_state([], "run-1", "NVDA")


@pytest.mark.unit
def test_fr01_adapter_missing_decision_key_is_review():
    """[FR-01] A missing decision is REVIEW, never a fabricated Hold."""
    decision = decision_from_final_state({}, "run-1", "NVDA")
    assert decision.action is DecisionAction.REVIEW


@pytest.mark.unit
def test_fr02_sizing_uses_equity_fraction_and_overrides_llm_quantity():
    """[FR-02] Size is deterministic and replaces any advisory quantity."""
    policy = SizingPolicy(Decimal("0.05"))
    decision = replace(_advisory_decision(), quantity=Decimal("999"))

    sized = policy.size(
        decision,
        _quote("100"),
        total_equity=Decimal("10000"),
        hard_max_order_notional=Decimal("10000"),
    )

    assert sized.quantity == Decimal("5.000000")


@pytest.mark.unit
def test_fr02_sizing_caps_at_hard_maximum_notional():
    """[FR-02] The notional cap overrides the target fraction."""
    policy = SizingPolicy(Decimal("0.05"))
    sized = policy.size(
        _advisory_decision(),
        _quote("100"),
        total_equity=Decimal("10000"),
        hard_max_order_notional=Decimal("300"),
    )

    assert sized.quantity == Decimal("3.000000")


@pytest.mark.unit
def test_fr02_sizing_quantizes_to_six_decimal_places():
    """[FR-02] Fractional shares are floored to the supported precision."""
    policy = SizingPolicy(Decimal("0.05"))
    sized = policy.size(
        _advisory_decision(),
        _quote("3"),
        total_equity=Decimal("10000"),
        hard_max_order_notional=Decimal("10000"),
    )

    assert sized.quantity == Decimal("166.666666")


@pytest.mark.unit
def test_fr02_sizing_handles_zero_equity_price_and_non_executable_actions():
    """[FR-02] Invalid valuation or non-executable actions produce no trade."""
    policy = SizingPolicy(Decimal("0.05"))
    zero_equity = policy.size(
        _advisory_decision(),
        _quote("100"),
        total_equity=Decimal("0"),
        hard_max_order_notional=Decimal("10000"),
    )
    zero_price = policy.size(
        _advisory_decision(),
        _quote("0"),
        total_equity=Decimal("10000"),
        hard_max_order_notional=Decimal("10000"),
    )
    hold = decision_from_final_state(
        {"final_trade_decision": "Rating: Hold"},
        "run-1",
        "NVDA",
    )
    held = policy.size(
        hold,
        _quote("100"),
        total_equity=Decimal("10000"),
        hard_max_order_notional=Decimal("10000"),
    )

    assert zero_equity.quantity == Decimal("0")
    assert zero_price.quantity == Decimal("0")
    assert held is hold
    assert held.quantity is None


@pytest.mark.unit
@pytest.mark.parametrize("fraction", ["0", "-0.1", "1.01"])
def test_fr02_sizing_rejects_invalid_target_fraction(fraction):
    """[FR-02] Sizing cannot be configured outside (0, 1]."""
    with pytest.raises(ConfigValidationError):
        SizingPolicy(Decimal(fraction))


@pytest.mark.unit
def test_fr02_pipeline_happy_path_sizes_evaluates_and_executes(tmp_path):
    """[FR-02] An approved decision flows through sizing to simulated execution."""
    pipeline, engine, portfolio, audit, _, _ = _setup(tmp_path)

    result = pipeline.process(
        _final_state(),
        _quote("100"),
        run_id="run-1",
    )

    assert result.evaluation.status is DecisionStatus.APPROVED
    assert result.approval_request is None
    assert result.execution is not None
    assert result.decision.quantity == Decimal("5.000000")
    assert result.execution.order.quantity == Decimal("5.000000")
    assert portfolio.position("NVDA").quantity == Decimal("5.000000")
    assert portfolio.cash == Decimal("9499.75")
    assert engine.execution_count == 1
    events = [event.event_type for event in audit.read_all()]
    assert events[-2:] == [EventType.EXECUTION_STARTED, EventType.ORDER_EXECUTED]


@pytest.mark.unit
def test_fr01_pipeline_ignores_llm_numbers_and_uses_deterministic_size(tmp_path):
    """[FR-01] LLM numbers cannot influence the executed quantity."""
    pipeline, _, portfolio, _, _, _ = _setup(tmp_path)
    final_state = _final_state(
        "**Rating**: Buy\n\nBuy 999 shares at $1.00.",
        quantity=999,
        entry_price=1.0,
    )

    result = pipeline.process(final_state, _quote("100"), run_id="run-1")

    assert result.decision.quantity == Decimal("5.000000")
    assert result.execution is not None
    assert result.execution.order.quantity == Decimal("5.000000")
    assert portfolio.position("NVDA").quantity == Decimal("5.000000")


@pytest.mark.unit
def test_fr01_pipeline_pending_returns_request_without_execution(tmp_path):
    """[FR-01] A soft-policy trigger returns an approval request and no fill."""
    config = SafetyConfig(
        soft_max_order_notional=Decimal("100"),
        hard_max_order_notional=Decimal("10000"),
    )
    pipeline, engine, portfolio, audit, _, _ = _setup(tmp_path, config=config)

    result = pipeline.process(_final_state(), _quote("100"), run_id="run-1")

    assert result.evaluation.status is DecisionStatus.PENDING_APPROVAL
    assert result.approval_request is not None
    assert result.approval_request.decision_id == result.decision.decision_id
    assert result.execution is None
    assert engine.execution_count == 0
    assert portfolio.position("NVDA") is None
    events = [event.event_type for event in audit.read_all()]
    assert EventType.HUMAN_APPROVAL_REQUESTED in events
    assert EventType.EXECUTION_STARTED not in events


@pytest.mark.unit
def test_fr01_pipeline_rejected_decision_does_not_execute(tmp_path):
    """[FR-01] A hard-rule rejection stops before the executor."""
    config = SafetyConfig(allowed_symbols=frozenset({"AAPL"}))
    pipeline, engine, portfolio, audit, _, _ = _setup(tmp_path, config=config)

    result = pipeline.process(_final_state(), _quote("100"), run_id="run-1")

    assert result.evaluation.status is DecisionStatus.REJECTED
    assert result.execution is None
    assert result.approval_request is None
    assert engine.execution_count == 0
    assert portfolio.position("NVDA") is None
    events = [event.event_type for event in audit.read_all()]
    assert EventType.DECISION_REJECTED in events
    assert EventType.EXECUTION_STARTED not in events


@pytest.mark.unit
def test_fr01_pipeline_hold_returns_no_action_without_execution(tmp_path):
    """[FR-01] HOLD is audited as NO_ACTION and never executed."""
    pipeline, engine, portfolio, _, _, _ = _setup(tmp_path)

    result = pipeline.process(
        _final_state("**Rating**: Hold\n\nStay flat."),
        _quote("100"),
        run_id="run-1",
    )

    assert result.evaluation.status is DecisionStatus.NO_ACTION
    assert result.execution is None
    assert result.approval_request is None
    assert engine.execution_count == 0
    assert portfolio.position("NVDA") is None


@pytest.mark.unit
def test_fr02_pipeline_respects_hard_max_and_derives_symbol(tmp_path):
    """[FR-02] The pipeline caps size and can derive the symbol from state."""
    config = SafetyConfig(
        soft_max_order_notional=Decimal("300"),
        hard_max_order_notional=Decimal("300"),
    )
    pipeline, _, portfolio, _, _, _ = _setup(tmp_path, config=config)

    result = pipeline.process(_final_state(), _quote("100"), run_id="run-1")

    assert result.decision.symbol == "NVDA"
    assert result.decision.quantity == Decimal("3.000000")
    assert result.evaluation.status is DecisionStatus.APPROVED
    assert portfolio.position("NVDA").quantity == Decimal("3.000000")
