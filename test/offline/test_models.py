"""Shared model, config, and fee-model tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from trading.models import (
    AuditEvent,
    ConfigValidationError,
    DecisionAction,
    DecisionValidationError,
    EventType,
    FeeModel,
    MarketQuote,
    OrderIntent,
    OrderType,
    PortfolioSnapshot,
    Position,
    SafetyConfig,
    Side,
    TradeDecision,
    quantize_money,
    to_decimal,
)


@pytest.mark.unit
def test_fr01_decimal_accepts_supported_types_and_rejects_floats():
    """[FR-01] Decisions are converted without binary floating-point drift."""
    assert to_decimal("1.25") == Decimal("1.25")
    assert to_decimal(3) == Decimal("3")
    assert to_decimal(Decimal("4.50")) == Decimal("4.50")

    with pytest.raises(DecisionValidationError):
        to_decimal(1.25)
    with pytest.raises(DecisionValidationError):
        to_decimal("")
    with pytest.raises(DecisionValidationError):
        to_decimal("not-a-number")
    with pytest.raises(DecisionValidationError):
        to_decimal(Decimal("NaN"))
    with pytest.raises(DecisionValidationError):
        to_decimal(True)


@pytest.mark.unit
def test_fr01_fee_model_uses_bps_minimum_and_money_rounding():
    """[FR-01] Fees are deterministic and never depend on wall-clock state."""
    model = FeeModel(fee_bps=Decimal("5"), min_fee=Decimal("1.00"))
    assert model.fee_for(Decimal("10000")) == Decimal("5.00")
    assert model.fee_for(Decimal("100")) == Decimal("1.00")

    without_minimum = FeeModel(fee_bps=Decimal("5"), min_fee=Decimal("0"))
    assert without_minimum.fee_for(Decimal("100")) == Decimal("0.05")
    assert quantize_money(Decimal("0.005")) == Decimal("0.01")


@pytest.mark.unit
def test_fr01_fee_model_rejects_negative_notional_and_bad_config():
    """[FR-01] Invalid fee inputs fail loudly."""
    with pytest.raises(DecisionValidationError):
        FeeModel().fee_for(Decimal("-1"))
    with pytest.raises(ConfigValidationError):
        FeeModel(fee_bps=Decimal("-1"))
    with pytest.raises(ConfigValidationError):
        FeeModel(min_fee=Decimal("-0.01"))


@pytest.mark.unit
def test_fr01_safety_config_defaults_and_normalisation():
    """[FR-01] Approved safety defaults are stable and symbols are normalised."""
    config = SafetyConfig(allowed_symbols=frozenset({"nvda", " aapl "}))
    assert config.hard_max_order_notional == Decimal("10000.00")
    assert config.soft_max_order_notional == Decimal("2500.00")
    assert config.max_position_fraction == Decimal("0.20")
    assert config.allowed_symbols == frozenset({"NVDA", "AAPL"})
    assert config.fee_model().fee_for(Decimal("10000")) == Decimal("5.00")


@pytest.mark.unit
@pytest.mark.parametrize(
    "kwargs",
    [
        {"soft_max_order_notional": Decimal("10001")},
        {"max_position_fraction": Decimal("0")},
        {"max_position_fraction": Decimal("1.01")},
        {"max_quote_age_seconds": 0},
        {"approval_ttl_seconds": 0},
        {"fee_bps": Decimal("-1")},
        {"min_fee": Decimal("-1")},
        {"bankrupt_rejection_reason": "  "},
    ],
)
def test_fr01_safety_config_rejects_invalid_values(kwargs):
    """[FR-01] Invalid safety configuration cannot silently weaken the engine."""
    with pytest.raises(ConfigValidationError):
        SafetyConfig(**kwargs)


@pytest.mark.unit
def test_fr01_market_quote_requires_timezone_aware_timestamp():
    """[FR-01] Quote freshness cannot be evaluated against a naive timestamp."""
    with pytest.raises(DecisionValidationError):
        MarketQuote(symbol="NVDA", price=Decimal("100"), as_of=datetime(2024, 1, 5, 21, 0))

    quote = MarketQuote(
        symbol="NVDA",
        price=Decimal("100.125"),
        as_of=datetime(2024, 1, 5, 21, 0, tzinfo=timezone.utc),
    )
    assert quote.price == Decimal("100.125")
    assert quote.as_of.tzinfo is timezone.utc


@pytest.mark.unit
def test_fr01_trade_decision_coerces_decimals_and_allows_policy_validation_later():
    """[FR-01] Structural models preserve malformed identity fields for audit."""
    decision = TradeDecision(
        run_id="run-1",
        decision_id="dec-1",
        symbol="",
        action="BUY",
        quantity="2.5",
        order_type="MARKET",
    )
    assert decision.action is DecisionAction.BUY
    assert decision.order_type is OrderType.MARKET
    assert decision.quantity == Decimal("2.5")
    assert decision.symbol == ""

    with pytest.raises(DecisionValidationError):
        TradeDecision(
            run_id="run-1",
            decision_id="dec-1",
            symbol="NVDA",
            action=DecisionAction.BUY,
            quantity=2.5,
        )


@pytest.mark.unit
def test_fr03_order_intent_and_snapshot_quantize_money():
    """[FR-03] Ledger values are shared at a fixed money precision."""
    intent = OrderIntent(
        decision_id="dec-1",
        symbol="NVDA",
        side="BUY",
        quantity="1",
        price="100.005",
        notional="100.005",
        fee="0.005",
    )
    assert intent.side is Side.BUY
    assert intent.notional == Decimal("100.005")

    snapshot = PortfolioSnapshot(
        cash="999.999",
        positions=(
            Position(
                symbol="NVDA",
                quantity="1",
                average_cost="100",
                market_price="101",
                market_value="101",
                unrealized_pnl="1",
            ),
        ),
        realized_pnl="0",
        unrealized_pnl="1",
        total_fees="0.005",
        total_equity="1100.999",
        bankrupt=False,
        version=1,
        as_of=datetime(2024, 1, 5, 21, 0, tzinfo=timezone.utc),
    )
    assert snapshot.cash == Decimal("1000.00")
    assert snapshot.total_fees == Decimal("0.01")
    assert snapshot.total_equity == Decimal("1101.00")
    assert snapshot.positions[0].market_value == Decimal("101.00")


@pytest.mark.unit
def test_fr04_event_types_include_persistence_and_bankruptcy_events():
    """[FR-04] Audit vocabulary covers the new lifecycle events."""
    assert EventType.STATE_RESET.value == "STATE_RESET"
    assert EventType.STATE_SAVED.value == "STATE_SAVED"
    assert EventType.BANKRUPT.value == "BANKRUPT"
    assert EventType.BACKTEST_DAY_COMPLETED.value == "BACKTEST_DAY_COMPLETED"


@pytest.mark.unit
def test_fr04_audit_event_rejects_naive_timestamp():
    """[FR-04] Audit timestamps must be unambiguous."""
    with pytest.raises(DecisionValidationError):
        AuditEvent(
            event_id="evt-1",
            run_id="run-1",
            timestamp=datetime(2024, 1, 5, 21, 0),
            event_type=EventType.STATE_LOADED,
            payload={},
        )


@pytest.mark.unit
def test_fr01_models_are_immutable():
    """[FR-01] Decisions and configuration cannot be mutated after validation."""
    decision = TradeDecision(
        run_id="run-1",
        decision_id="dec-1",
        symbol="NVDA",
        action=DecisionAction.BUY,
        quantity=Decimal("1"),
    )
    with pytest.raises(FrozenInstanceError):
        decision.quantity = Decimal("2")  # type: ignore[misc]

    config = SafetyConfig()
    with pytest.raises(FrozenInstanceError):
        config.fee_bps = Decimal("1")  # type: ignore[misc]
