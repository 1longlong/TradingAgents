"""Safety-engine state machine and provenance tests."""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from safety.engine import _ENGINE_TOKEN, SafetyEngine
from trading.audit import AuditLog
from trading.executor import SimulatedExecutor
from trading.models import (
    ApprovalExpiredError,
    ApprovalMismatchError,
    DecisionAction,
    DecisionStatus,
    EventType,
    ExecutionAuthorization,
    ExecutionNotAuthorizedError,
    HumanApproval,
    IllegalExecutionStateError,
    MarketQuote,
    SafetyConfig,
    StaleEvaluationError,
    TradeDecision,
)
from trading.portfolio import Portfolio

FIXED_NOW = datetime(2024, 1, 5, 21, 0, tzinfo=timezone.utc)


class _FixedClock:
    def __init__(self, now=FIXED_NOW, *, simulated=False, sim_date=None):
        self._now = now
        self._simulated = simulated
        self._sim_date = sim_date

    def now(self) -> datetime:
        return self._now

    def is_simulated(self) -> bool:
        return self._simulated

    def simulation_date(self):
        return self._sim_date


def _seq(prefix: str):
    counter = itertools.count(1)
    return lambda: f"{prefix}-{next(counter)}"


def _portfolio(
    *,
    cash="10000",
    fee_model=None,
    positions=None,
    clock=None,
) -> Portfolio:
    fee_model = fee_model or SafetyConfig().fee_model()
    clock = clock or _FixedClock()
    if positions:
        from tradingagents.portfolio import PortfolioContext, Position as ContextPosition

        return Portfolio.from_context(
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
            clock=clock.now,
        )
    return Portfolio(Decimal(cash), fee_model=fee_model, clock=clock.now)


def _setup(
    tmp_path: Path,
    *,
    action=DecisionAction.BUY,
    quantity="10",
    price="100",
    cash="10000",
    positions=None,
    config=None,
    clock=None,
    symbol="NVDA",
    decision_id="dec-1",
    run_id="run-1",
):
    config = config or SafetyConfig()
    clock = clock or _FixedClock()
    portfolio = _portfolio(
        cash=cash,
        fee_model=config.fee_model(),
        positions=positions,
        clock=clock,
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
    decision = TradeDecision(
        run_id=run_id,
        decision_id=decision_id,
        symbol=symbol,
        action=action,
        quantity=Decimal(quantity) if quantity is not None else None,
    )
    quote = MarketQuote(
        symbol=symbol,
        price=Decimal(price),
        as_of=clock.now(),
    )
    return engine, portfolio, audit, decision, quote, clock, config


def _approval(
    evaluation,
    *,
    approved=True,
    decision_id=None,
    expires_at=None,
    approver="human-supervisor",
    reason="approved for execution",
):
    return HumanApproval(
        request_id="req-1",
        decision_id=decision_id or evaluation.decision.decision_id,
        approved=approved,
        approver=approver,
        reason=reason,
        decided_at=FIXED_NOW,
        expires_at=expires_at or (FIXED_NOW + timedelta(hours=1)),
    )


def _event_types(audit: AuditLog) -> list[EventType]:
    return [event.event_type for event in audit.read_all()]


@pytest.mark.unit
def test_fr01_approved_state_runs_all_rules_and_policies(tmp_path):
    """[FR-01] A clean BUY is APPROVED after every rule and policy passes."""
    engine, portfolio, audit, decision, quote, _, _ = _setup(tmp_path)

    evaluation = engine.evaluate(decision, quote)

    assert evaluation.status is DecisionStatus.APPROVED
    assert evaluation.evaluation_id == "eval-1"
    assert evaluation.order_intent is not None
    assert {result.rule_id for result in evaluation.rule_results} == {
        f"SR-{number:02d}" for number in range(1, 11)
    }
    assert all(result.passed for result in evaluation.rule_results)
    assert [check.policy_id for check in evaluation.approval_checks] == [
        "AP-01",
        "AP-02",
    ]
    assert all(not check.triggered for check in evaluation.approval_checks)
    assert evaluation.reasons == ()
    assert evaluation.portfolio_version == portfolio.version == 0

    kinds = _event_types(audit)
    assert kinds[0] is EventType.DECISION_RECEIVED
    assert kinds.count(EventType.RULE_EVALUATED) == 10
    assert kinds.count(EventType.APPROVAL_POLICY_EVALUATED) == 2
    assert kinds.count(EventType.DECISION_EVALUATED) == 1
    assert kinds[-1] is EventType.DECISION_APPROVED
    assert EventType.DECISION_REJECTED not in kinds


@pytest.mark.unit
def test_fr02_execute_approved_updates_portfolio_and_audits(tmp_path):
    """[FR-02] The engine is the path from APPROVED evaluation to fill."""
    engine, portfolio, audit, decision, quote, _, _ = _setup(tmp_path)
    evaluation = engine.evaluate(decision, quote)

    result = engine.execute(evaluation)

    assert result.decision_id == decision.decision_id
    assert portfolio.cash == Decimal("8999.50")
    assert portfolio.position("NVDA").quantity == Decimal("10.000000")
    assert engine.execution_count == 1
    kinds = _event_types(audit)
    assert kinds[-2:] == [
        EventType.EXECUTION_STARTED,
        EventType.ORDER_EXECUTED,
    ]


@pytest.mark.unit
def test_fr01_rejected_state_writes_reason_and_cannot_execute(tmp_path):
    """[FR-01] A hard rule failure is REJECTED and never reaches execution."""
    engine, portfolio, audit, decision, quote, _, _ = _setup(tmp_path, cash="10")

    evaluation = engine.evaluate(decision, quote)

    assert evaluation.status is DecisionStatus.REJECTED
    assert "insufficient cash for BUY" in evaluation.reasons
    assert evaluation.approval_checks == ()
    assert len(evaluation.rule_results) == 10
    kinds = _event_types(audit)
    assert EventType.DECISION_REJECTED in kinds
    assert EventType.DECISION_APPROVED not in kinds
    assert EventType.APPROVAL_POLICY_EVALUATED not in kinds

    with pytest.raises(IllegalExecutionStateError):
        engine.execute(evaluation)

    assert engine.execution_count == 0
    assert portfolio.cash == Decimal("10.00")
    assert EventType.EXECUTION_STARTED not in _event_types(audit)


@pytest.mark.unit
def test_fr01_pending_approval_state_does_not_execute(tmp_path):
    """[FR-01] Soft policies route a clean order to PENDING_APPROVAL."""
    engine, portfolio, audit, decision, quote, _, _ = _setup(
        tmp_path,
        quantity="30",
    )

    evaluation = engine.evaluate(decision, quote)

    assert evaluation.status is DecisionStatus.PENDING_APPROVAL
    assert {check.policy_id for check in evaluation.approval_checks if check.triggered} == {
        "AP-01",
        "AP-02",
    }
    assert evaluation.reasons
    kinds = _event_types(audit)
    assert EventType.DECISION_EVALUATED in kinds
    assert EventType.DECISION_APPROVED not in kinds
    assert EventType.DECISION_REJECTED not in kinds

    with pytest.raises(IllegalExecutionStateError):
        engine.execute(evaluation)

    assert engine.execution_count == 0
    assert portfolio.cash == Decimal("10000.00")


@pytest.mark.unit
def test_fr04_apply_approval_can_approve_and_execute(tmp_path):
    """[FR-04] A human approval advances PENDING_APPROVAL to APPROVED."""
    engine, portfolio, audit, decision, quote, _, _ = _setup(
        tmp_path,
        quantity="30",
    )
    pending = engine.evaluate(decision, quote)

    approved = engine.apply_approval(pending, _approval(pending))

    assert approved.status is DecisionStatus.APPROVED
    assert approved.reasons == ()
    assert approved.order_intent is not None
    assert EventType.DECISION_APPROVED in _event_types(audit)

    result = engine.execute(approved)

    assert result.decision_id == decision.decision_id
    assert engine.execution_count == 1
    assert portfolio.position("NVDA").quantity == Decimal("30.000000")


@pytest.mark.unit
def test_fr04_apply_approval_can_reject_and_cannot_execute(tmp_path):
    """[FR-04] A denied approval advances PENDING_APPROVAL to REJECTED."""
    engine, portfolio, audit, decision, quote, _, _ = _setup(
        tmp_path,
        quantity="30",
    )
    pending = engine.evaluate(decision, quote)

    rejected = engine.apply_approval(
        pending,
        _approval(pending, approved=False, reason="risk limit"),
    )

    assert rejected.status is DecisionStatus.REJECTED
    assert any("risk limit" in reason for reason in rejected.reasons)
    assert EventType.DECISION_REJECTED in _event_types(audit)

    with pytest.raises(IllegalExecutionStateError):
        engine.execute(rejected)

    assert engine.execution_count == 0
    assert portfolio.cash == Decimal("10000.00")


@pytest.mark.unit
def test_fr04_apply_approval_rejects_invalid_transitions(tmp_path):
    """[FR-04] Approval is one-shot, decision-bound, and time-bound."""
    engine, _, _, decision, quote, _, _ = _setup(tmp_path)
    approved = engine.evaluate(decision, quote)
    with pytest.raises(IllegalExecutionStateError):
        engine.apply_approval(approved, _approval(approved))

    engine, _, _, decision, quote, _, _ = _setup(
        tmp_path / "pending",
        quantity="30",
    )
    pending = engine.evaluate(decision, quote)
    with pytest.raises(ApprovalMismatchError):
        engine.apply_approval(
            pending,
            _approval(pending, decision_id="other-decision"),
        )
    with pytest.raises(ApprovalExpiredError):
        engine.apply_approval(
            pending,
            _approval(pending, expires_at=FIXED_NOW - timedelta(seconds=1)),
        )
    with pytest.raises(ApprovalMismatchError):
        engine.apply_approval(pending, _approval(pending, approver=" "))

    engine.apply_approval(pending, _approval(pending))
    with pytest.raises(IllegalExecutionStateError):
        engine.apply_approval(pending, _approval(pending))


@pytest.mark.unit
@pytest.mark.parametrize("action", [DecisionAction.HOLD, DecisionAction.REVIEW])
def test_fr01_hold_and_review_are_no_action_and_never_execute(tmp_path, action):
    """[FR-01] HOLD and REVIEW are audited but never executable."""
    engine, portfolio, audit, decision, quote, _, _ = _setup(
        tmp_path,
        action=action,
    )

    evaluation = engine.evaluate(decision, quote)

    assert evaluation.status is DecisionStatus.NO_ACTION
    assert evaluation.order_intent is None
    assert evaluation.rule_results == ()
    assert evaluation.approval_checks == ()
    assert evaluation.reasons
    assert _event_types(audit) == [
        EventType.DECISION_RECEIVED,
        EventType.DECISION_EVALUATED,
    ]

    with pytest.raises(IllegalExecutionStateError):
        engine.execute(evaluation)

    assert engine.execution_count == 0
    assert portfolio.cash == Decimal("10000.00")
    assert EventType.EXECUTION_STARTED not in _event_types(audit)


@pytest.mark.unit
def test_inv01_stale_evaluation_cannot_execute(tmp_path):
    """[INV-01] A portfolio change between evaluation and execution is fatal."""
    engine, portfolio, audit, decision, quote, _, _ = _setup(tmp_path)
    evaluation = engine.evaluate(decision, quote)
    portfolio.mark({"NVDA": Decimal("101")})

    with pytest.raises(StaleEvaluationError):
        engine.execute(evaluation)

    assert engine.execution_count == 0
    assert portfolio.cash == Decimal("10000.00")
    assert EventType.EXECUTION_STARTED not in _event_types(audit)


@pytest.mark.unit
def test_fr06_bankrupt_portfolio_evaluation_is_rejected_with_reason(tmp_path):
    """[FR-06] BANKRUPT is the first hard-rule rejection reason."""
    engine, portfolio, audit, decision, quote, _, _ = _setup(tmp_path)
    portfolio.mark_bankrupt(reason="test halt")

    evaluation = engine.evaluate(decision, quote)

    assert evaluation.status is DecisionStatus.REJECTED
    assert evaluation.reasons[0] == "BANKRUPT"
    assert engine.execution_count == 0
    assert EventType.DECISION_REJECTED in _event_types(audit)


@pytest.mark.unit
def test_inv02_forged_authorization_cannot_bypass_the_engine(tmp_path):
    """[INV-02] Direct executor calls with a forged authorization are rejected."""
    engine, portfolio, audit, decision, quote, clock, _ = _setup(tmp_path)
    evaluation = engine.evaluate(decision, quote)
    direct_audit = AuditLog(
        tmp_path / "direct.jsonl",
        clock=clock.now,
        id_factory=_seq("direct-evt"),
    )
    direct_executor = SimulatedExecutor(
        portfolio,
        direct_audit,
        authorization_token=_ENGINE_TOKEN,
        clock=clock.now,
        id_factory=_seq("direct-exec"),
    )
    forged = ExecutionAuthorization(
        evaluation_id=evaluation.evaluation_id,
        decision=evaluation.decision,
        order_intent=evaluation.order_intent,
        portfolio_version=evaluation.portfolio_version,
    )

    with pytest.raises(ExecutionNotAuthorizedError):
        direct_executor.execute(forged)

    assert direct_audit.read_all() == ()
    assert direct_executor.execution_count == 0
    assert portfolio.cash == Decimal("10000.00")
    assert engine.execution_count == 0

    result = engine.execute(evaluation)
    assert result.decision_id == decision.decision_id
    assert engine.execution_count == 1


@pytest.mark.unit
def test_fr05_simulation_clock_drives_quote_freshness(tmp_path):
    """[FR-05] The engine passes simulated time and date into SR-03."""
    clock = _FixedClock(
        now=FIXED_NOW,
        simulated=True,
        sim_date=FIXED_NOW.date(),
    )
    engine, _, audit, decision, _, _, _ = _setup(tmp_path, clock=clock)
    stale_quote = MarketQuote(
        symbol="NVDA",
        price=Decimal("100"),
        as_of=datetime(2024, 1, 4, 21, 0, tzinfo=timezone.utc),
    )

    evaluation = engine.evaluate(decision, stale_quote)

    assert evaluation.status is DecisionStatus.REJECTED
    assert any("simulated date" in reason for reason in evaluation.reasons)
    assert EventType.DECISION_REJECTED in _event_types(audit)
