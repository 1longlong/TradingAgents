"""Simulated executor tests."""

from __future__ import annotations

import itertools
from dataclasses import FrozenInstanceError, dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from trading.audit import AuditLog
from trading.executor import SimulatedExecutor
from trading.models import (
    DecisionAction,
    DuplicateFillError,
    EventType,
    ExecutionAuditError,
    ExecutionAuthorization,
    ExecutionNotAuthorizedError,
    FeeModel,
    IllegalExecutionStateError,
    OrderIntent,
    OrderType,
    PortfolioError,
    Side,
    StaleEvaluationError,
    TradeDecision,
    UnsupportedOrderTypeError,
    quantize_money,
)
from trading.portfolio import Portfolio

FIXED_NOW = datetime(2024, 1, 5, 21, 0, tzinfo=timezone.utc)
TEST_TOKEN = object()


@dataclass(frozen=True)
class _TestAuthorization(ExecutionAuthorization):
    provenance_token: object = field(default=None, repr=False, compare=False)


def _clock() -> datetime:
    return FIXED_NOW


def _seq(prefix: str):
    counter = itertools.count(1)
    return lambda: f"{prefix}-{next(counter)}"


def _portfolio(
    *,
    cash="10000",
    fee_model=None,
    positions=None,
    bankrupt=False,
) -> Portfolio:
    fee_model = fee_model or FeeModel(fee_bps=Decimal("5"), min_fee=Decimal("0"))
    if positions:
        from tradingagents.portfolio import PortfolioContext, Position as ContextPosition

        portfolio = Portfolio.from_context(
            PortfolioContext(
                cash=float(Decimal(cash)),
                positions=[
                    ContextPosition(
                        ticker=symbol,
                        quantity=float(Decimal(quantity)),
                        average_price=float(Decimal(average_price)),
                    )
                    for symbol, quantity, average_price in positions
                ],
            ),
            fee_model=fee_model,
            clock=_clock,
        )
    else:
        portfolio = Portfolio(Decimal(cash), fee_model=fee_model, clock=_clock)
    if bankrupt:
        portfolio.mark_bankrupt(reason="test")
    return portfolio


def _decision(
    *,
    action=DecisionAction.BUY,
    quantity="10",
    symbol="NVDA",
    decision_id="dec-1",
    run_id="run-1",
    order_type=OrderType.MARKET,
) -> TradeDecision:
    return TradeDecision(
        run_id=run_id,
        decision_id=decision_id,
        symbol=symbol,
        action=action,
        quantity=Decimal(quantity) if quantity is not None else None,
        order_type=order_type,
    )


def _intent(decision: TradeDecision, fee_model: FeeModel, *, price="100") -> OrderIntent:
    quantity = decision.quantity
    px = Decimal(price)
    notional = quantize_money(quantity * px)
    return OrderIntent(
        decision_id=decision.decision_id,
        symbol=decision.symbol,
        side=Side.BUY if decision.action is DecisionAction.BUY else Side.SELL,
        quantity=quantity,
        price=px,
        notional=notional,
        fee=fee_model.fee_for(notional),
    )


def _setup(
    tmp_path: Path,
    *,
    action=DecisionAction.BUY,
    quantity="10",
    price="100",
    cash="10000",
    fee_bps="5",
    min_fee="0",
    positions=None,
    audit=None,
    bankrupt=False,
):
    fee_model = FeeModel(fee_bps=Decimal(fee_bps), min_fee=Decimal(min_fee))
    portfolio = _portfolio(
        cash=cash,
        fee_model=fee_model,
        positions=positions,
        bankrupt=bankrupt,
    )
    if audit is None:
        audit = AuditLog(
            tmp_path / "audit.jsonl",
            clock=_clock,
            id_factory=_seq("evt"),
        )
    executor = SimulatedExecutor(
        portfolio,
        audit,
        authorization_token=TEST_TOKEN,
        clock=_clock,
        id_factory=_seq("exec"),
    )
    decision = _decision(action=action, quantity=quantity)
    intent = _intent(decision, fee_model, price=price)
    auth = _TestAuthorization(
        evaluation_id="eval-1",
        decision=decision,
        order_intent=intent,
        portfolio_version=portfolio.version,
        provenance_token=TEST_TOKEN,
    )
    return portfolio, fee_model, audit, executor, auth, decision, intent


class _FakeAudit:
    def __init__(self, fail_on=()):
        self.fail_on = {EventType(event_type) for event_type in fail_on}
        self.events = []

    def append(self, *, run_id, event_type, payload):
        kind = EventType(event_type)
        if kind in self.fail_on:
            raise RuntimeError("audit unavailable")
        event = {
            "run_id": run_id,
            "event_type": kind,
            "payload": payload,
        }
        self.events.append(event)
        return event


@pytest.mark.unit
def test_fr02_executor_applies_approved_buy_and_writes_both_events(tmp_path):
    """[FR-02] An authorized BUY updates cash, position, and audit events."""
    portfolio, _, audit, executor, auth, decision, intent = _setup(tmp_path)

    result = executor.execute(auth)

    assert result.execution_id == "exec-1"
    assert result.order_id == "ord-dec-1"
    assert result.decision_id == "dec-1"
    assert result.order == intent
    assert result.executed_at == FIXED_NOW
    assert portfolio.cash == Decimal("8999.50")
    assert portfolio.position("NVDA").quantity == Decimal("10.000000")
    assert portfolio.position("NVDA").average_cost == Decimal("100.050000")
    assert result.snapshot.total_equity == Decimal("9999.50")
    assert executor.execution_count == 1

    events = audit.read_all()
    assert [event.event_type for event in events] == [
        EventType.EXECUTION_STARTED,
        EventType.ORDER_EXECUTED,
    ]
    for event in events:
        assert event.run_id == decision.run_id
        assert event.timestamp == FIXED_NOW
        assert event.payload["run_id"] == "run-1"
        assert event.payload["decision_id"] == "dec-1"
        assert event.payload["order_id"] == "ord-dec-1"
        assert event.payload["fill_price"] == "100"
        assert event.payload["fee"] == "0.50"

    assert events[0].payload["snapshot"]["cash"] == "10000.00"
    assert events[0].payload["snapshot"]["version"] == 0
    assert events[1].payload["snapshot"]["cash"] == "8999.50"
    assert events[1].payload["snapshot"]["version"] == 1
    assert events[1].payload["snapshot"]["positions"][0]["symbol"] == "NVDA"
    assert events[1].payload["execution_id"] == "exec-1"
    assert events[1].payload["executed_at"] == FIXED_NOW.isoformat()


@pytest.mark.unit
def test_fr02_executor_applies_approved_sell(tmp_path):
    """[FR-02] An authorized SELL reduces the holding and realizes PnL."""
    portfolio, _, audit, executor, auth, _, _ = _setup(
        tmp_path,
        action=DecisionAction.SELL,
        quantity="10",
        price="110",
        cash="10000",
        positions=[("NVDA", "10", "100")],
    )

    result = executor.execute(auth)

    assert portfolio.cash == Decimal("11099.45")
    assert portfolio.position("NVDA") is None
    assert result.snapshot.realized_pnl == Decimal("99.45")
    assert result.snapshot.total_equity == Decimal("11099.45")
    assert executor.execution_count == 1
    assert [event.event_type for event in audit.read_all()] == [
        EventType.EXECUTION_STARTED,
        EventType.ORDER_EXECUTED,
    ]


@pytest.mark.unit
def test_fr02_replay_is_rejected_without_new_audit_or_mutation(tmp_path):
    """[FR-02] The deterministic order id prevents duplicate fills."""
    portfolio, _, audit, executor, auth, _, _ = _setup(tmp_path)
    executor.execute(auth)
    events_after_first = audit.read_all()
    cash_after_first = portfolio.cash

    replay = replace(auth, portfolio_version=portfolio.version)
    with pytest.raises(DuplicateFillError):
        executor.execute(replay)

    assert portfolio.cash == cash_after_first
    assert audit.read_all() == events_after_first
    assert executor.execution_count == 1


@pytest.mark.unit
def test_inv01_stale_authorization_fails_before_audit(tmp_path):
    """[INV-01] A stale portfolio version cannot reach fill application."""
    portfolio, _, audit, executor, auth, _, _ = _setup(tmp_path)
    portfolio.mark({"NVDA": Decimal("101")})

    with pytest.raises(StaleEvaluationError):
        executor.execute(auth)

    assert audit.read_all() == ()
    assert portfolio.cash == Decimal("10000.00")
    assert executor.execution_count == 0


@pytest.mark.unit
def test_fr06_bankrupt_authorization_fails_before_audit(tmp_path):
    """[FR-06] A bankrupt portfolio rejects execution before anything is written."""
    portfolio, _, audit, executor, auth, _, _ = _setup(tmp_path)
    portfolio.mark_bankrupt(reason="test halt")

    with pytest.raises(PortfolioError, match="BANKRUPT"):
        executor.execute(replace(auth, portfolio_version=portfolio.version))

    assert audit.read_all() == ()
    assert executor.execution_count == 0
    assert not portfolio.has_applied("ord-dec-1")


@pytest.mark.unit
def test_inv01_execution_started_audit_failure_leaves_portfolio_untouched(tmp_path):
    """[INV-01] If EXECUTION_STARTED fails, no fill is attempted."""
    audit = _FakeAudit(fail_on={EventType.EXECUTION_STARTED})
    portfolio, _, _, executor, auth, _, _ = _setup(tmp_path, audit=audit)

    with pytest.raises(ExecutionAuditError):
        executor.execute(auth)

    assert portfolio.cash == Decimal("10000.00")
    assert portfolio.version == 0
    assert portfolio.position("NVDA") is None
    assert not portfolio.has_applied("ord-dec-1")
    assert executor.execution_count == 0
    assert audit.events == []


@pytest.mark.unit
def test_inv01_order_executed_audit_failure_records_invariant_violation(tmp_path):
    """[INV-01] A post-mutation audit failure is fatal and explicitly recorded."""
    audit = _FakeAudit(fail_on={EventType.ORDER_EXECUTED})
    portfolio, _, _, executor, auth, _, _ = _setup(tmp_path, audit=audit)

    with pytest.raises(ExecutionAuditError):
        executor.execute(auth)

    assert portfolio.cash == Decimal("8999.50")
    assert portfolio.has_applied("ord-dec-1")
    assert executor.execution_count == 1
    assert [event["event_type"] for event in audit.events] == [
        EventType.EXECUTION_STARTED,
        EventType.INVARIANT_VIOLATION,
    ]
    violation = audit.events[-1]["payload"]
    assert violation["reason"] == "ORDER_EXECUTED audit failed after portfolio mutation"
    assert violation["error_type"] == "RuntimeError"
    assert violation["order_id"] == "ord-dec-1"
    assert violation["snapshot"]["cash"] == "8999.50"


@pytest.mark.unit
def test_inv01_total_audit_outage_still_raises_without_silent_success(tmp_path):
    """[INV-01] A full audit outage is never mistaken for successful execution."""
    audit = _FakeAudit(
        fail_on={
            EventType.EXECUTION_STARTED,
            EventType.ORDER_EXECUTED,
            EventType.INVARIANT_VIOLATION,
        }
    )
    portfolio, _, _, executor, auth, _, _ = _setup(tmp_path, audit=audit)

    with pytest.raises(ExecutionAuditError):
        executor.execute(auth)

    assert portfolio.cash == Decimal("10000.00")
    assert executor.execution_count == 0
    assert audit.events == []


@pytest.mark.unit
@pytest.mark.parametrize(
    "changes,error",
    [
        ({"side": Side.SELL}, IllegalExecutionStateError),
        ({"quantity": Decimal("5")}, IllegalExecutionStateError),
        ({"symbol": "AAPL"}, IllegalExecutionStateError),
        ({"decision_id": "other"}, IllegalExecutionStateError),
        ({"price": Decimal("0")}, IllegalExecutionStateError),
        ({"notional": Decimal("999.00")}, IllegalExecutionStateError),
        ({"fee": Decimal("-1")}, IllegalExecutionStateError),
    ],
)
def test_inv01_inconsistent_order_envelope_is_rejected(tmp_path, changes, error):
    """[INV-01] Malformed order envelopes never reach the fill or audit."""
    _, _, audit, executor, auth, _, intent = _setup(tmp_path)
    tampered = replace(auth, order_intent=replace(intent, **changes))

    with pytest.raises(error):
        executor.execute(tampered)

    assert audit.read_all() == ()
    assert executor.execution_count == 0


@pytest.mark.unit
def test_inv01_non_market_order_is_rejected(tmp_path):
    """[INV-01] The v1 simulator executes market orders only."""
    _, _, audit, executor, auth, decision, intent = _setup(tmp_path)
    tampered_decision = replace(decision, order_type=OrderType.LIMIT)
    tampered = replace(auth, decision=tampered_decision)

    with pytest.raises(UnsupportedOrderTypeError):
        executor.execute(tampered)

    assert audit.read_all() == ()


@pytest.mark.unit
def test_inv01_hold_decision_is_rejected(tmp_path):
    """[INV-01] HOLD is not an executable decision."""
    _, _, audit, executor, auth, decision, intent = _setup(tmp_path)
    hold = replace(decision, action=DecisionAction.HOLD)
    tampered = replace(auth, decision=hold, order_intent=replace(intent, side=Side.BUY))

    with pytest.raises(IllegalExecutionStateError):
        executor.execute(tampered)

    assert audit.read_all() == ()


@pytest.mark.unit
@pytest.mark.parametrize(
    "authorization",
    [
        None,
        object(),
    ],
)
def test_inv01_missing_authorization_is_rejected(tmp_path, authorization):
    """[INV-01] Execution requires an ExecutionAuthorization."""
    _, _, audit, executor, _, _, _ = _setup(tmp_path)
    with pytest.raises(ExecutionNotAuthorizedError):
        executor.execute(authorization)
    assert audit.read_all() == ()


@pytest.mark.unit
def test_inv01_invalid_authorization_fields_are_rejected(tmp_path):
    """[INV-01] Missing evaluation ids or invalid versions fail closed."""
    _, _, audit, executor, auth, _, _ = _setup(tmp_path)

    with pytest.raises(ExecutionNotAuthorizedError):
        executor.execute(replace(auth, evaluation_id=" "))
    with pytest.raises(ExecutionNotAuthorizedError):
        executor.execute(replace(auth, portfolio_version=-1))
    with pytest.raises(ExecutionNotAuthorizedError):
        executor.execute(replace(auth, order_intent=None))
    assert audit.read_all() == ()


@pytest.mark.unit
def test_fr02_fee_mismatch_is_rejected_before_order_executed(tmp_path):
    """[FR-02] The portfolio remains the final authority on fee arithmetic."""
    portfolio, _, audit, executor, auth, _, intent = _setup(tmp_path)
    tampered = replace(auth, order_intent=replace(intent, fee=Decimal("0.00")))

    with pytest.raises(PortfolioError, match="fee"):
        executor.execute(tampered)

    assert [event.event_type for event in audit.read_all()] == [
        EventType.EXECUTION_STARTED
    ]
    assert executor.execution_count == 0
    assert not portfolio.has_applied("ord-dec-1")


@pytest.mark.unit
def test_fr02_zero_notional_after_rounding_is_rejected(tmp_path):
    """[FR-02] Dust orders that round to zero value are rejected."""
    _, _, audit, executor, auth, decision, intent = _setup(tmp_path)
    dust_decision = replace(decision, quantity=Decimal("0.000001"))
    dust_intent = replace(
        intent,
        quantity=Decimal("0.000001"),
        price=Decimal("1"),
        notional=Decimal("0.00"),
        fee=Decimal("0.00"),
    )

    with pytest.raises(IllegalExecutionStateError, match="zero"):
        executor.execute(replace(auth, decision=dust_decision, order_intent=dust_intent))

    assert audit.read_all() == ()


@pytest.mark.unit
def test_fr02_rounding_boundaries_use_decimal_half_up(tmp_path):
    """[FR-02] Fee and notional rounding follow the shared Decimal rules."""
    portfolio, fee_model, _, executor, _, _, _ = _setup(
        tmp_path,
        cash="100",
        quantity="1",
        price="10",
    )
    decision = _decision(quantity="1")
    intent = _intent(decision, fee_model, price="10")
    assert intent.notional == Decimal("10.00")
    assert intent.fee == Decimal("0.01")
    auth = _TestAuthorization(
        evaluation_id="eval-rounding",
        decision=decision,
        order_intent=intent,
        portfolio_version=portfolio.version,
        provenance_token=TEST_TOKEN,
    )

    result = executor.execute(auth)

    assert result.snapshot.total_fees == Decimal("0.01")
    assert portfolio.cash == Decimal("89.99")


@pytest.mark.unit
def test_fr02_notional_rounds_to_the_nearest_cent(tmp_path):
    """[FR-02] A fractional-cent notional is rounded once, before fees."""
    portfolio, _, _, executor, auth, decision, intent = _setup(tmp_path, cash="1000")
    rounded_decision = replace(decision, quantity=Decimal("1.000001"))
    rounded_intent = replace(
        intent,
        quantity=Decimal("1.000001"),
        price=Decimal("100.005"),
        notional=Decimal("100.01"),
        fee=Decimal("0.05"),
    )

    result = executor.execute(
        replace(auth, decision=rounded_decision, order_intent=rounded_intent)
    )

    assert result.order.notional == Decimal("100.01")
    assert result.snapshot.total_fees == Decimal("0.05")
    assert portfolio.cash == Decimal("899.94")


@pytest.mark.unit
def test_fr02_repeated_fresh_executions_are_deterministic(tmp_path):
    """[FR-02] Identical inputs produce identical results and audit payloads."""
    first = _setup(tmp_path / "first")
    second = _setup(tmp_path / "second")

    result_one = first[3].execute(first[4])
    result_two = second[3].execute(second[4])

    assert result_one == result_two
    assert first[0].snapshot() == second[0].snapshot()
    assert first[2].read_all() == second[2].read_all()


@pytest.mark.unit
def test_execution_authorization_is_frozen(tmp_path):
    """[INV-01] An authorization cannot be mutated after it is issued."""
    _, _, _, _, auth, _, _ = _setup(tmp_path)
    with pytest.raises(FrozenInstanceError):
        auth.portfolio_version = 99  # type: ignore[misc]


@pytest.mark.unit
def test_inv02_forged_base_authorization_is_rejected(tmp_path):
    """[INV-02] A direct ExecutionAuthorization lacks engine provenance."""
    portfolio, _, audit, executor, auth, _, _ = _setup(tmp_path)
    forged = ExecutionAuthorization(
        evaluation_id=auth.evaluation_id,
        decision=auth.decision,
        order_intent=auth.order_intent,
        portfolio_version=auth.portfolio_version,
    )

    with pytest.raises(ExecutionNotAuthorizedError):
        executor.execute(forged)

    assert audit.read_all() == ()
    assert portfolio.cash == Decimal("10000.00")
    assert portfolio.version == 0
    assert executor.execution_count == 0


@pytest.mark.unit
def test_inv02_wrong_provenance_token_is_rejected(tmp_path):
    """[INV-02] An authorization carrying the wrong token cannot execute."""
    portfolio, _, audit, executor, auth, _, _ = _setup(tmp_path)
    forged = replace(auth, provenance_token=object())

    with pytest.raises(ExecutionNotAuthorizedError):
        executor.execute(forged)

    assert audit.read_all() == ()
    assert portfolio.cash == Decimal("10000.00")
    assert executor.execution_count == 0
