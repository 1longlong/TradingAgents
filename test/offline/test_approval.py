"""Human approval gate tests."""

from __future__ import annotations

import itertools
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from safety.engine import SafetyEngine
from trading.approval import HumanApprovalGate
from trading.audit import AuditLog
from trading.models import (
    ApprovalExpiredError,
    ApprovalMismatchError,
    ApprovalRequest,
    DecisionAction,
    DecisionStatus,
    EventType,
    HumanApproval,
    IllegalExecutionStateError,
    MarketQuote,
    SafetyConfig,
    TradeDecision,
)
from trading.portfolio import Portfolio

FIXED_NOW = datetime(2024, 1, 5, 21, 0, tzinfo=timezone.utc)


class _MutableClock:
    def __init__(self, now=FIXED_NOW):
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: int) -> None:
        self._now += timedelta(seconds=seconds)

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
    action=DecisionAction.BUY,
    quantity="30",
    ttl=60,
):
    clock = _MutableClock()
    config = SafetyConfig(approval_ttl_seconds=ttl)
    portfolio = Portfolio(
        Decimal("10000"),
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
    decision = TradeDecision(
        run_id="run-1",
        decision_id="dec-1",
        symbol="NVDA",
        action=action,
        quantity=Decimal(quantity),
    )
    quote = MarketQuote(
        symbol="NVDA",
        price=Decimal("100"),
        as_of=clock.now(),
    )
    evaluation = engine.evaluate(decision, quote)
    return evaluation, gate, engine, portfolio, audit, clock, config


def _event_types(audit: AuditLog) -> list[EventType]:
    return [event.event_type for event in audit.read_all()]


@pytest.mark.unit
def test_fr04_request_pending_creates_expiring_request_and_audit(tmp_path):
    """[FR-04] Pending evaluations receive a TTL-bound approval request."""
    evaluation, gate, _, _, audit, _, _ = _setup(tmp_path, ttl=120)
    assert evaluation.status is DecisionStatus.PENDING_APPROVAL

    request = gate.request(evaluation)

    assert request.request_id == "req-1"
    assert request.evaluation_id == evaluation.evaluation_id
    assert request.decision_id == evaluation.decision.decision_id
    assert request.created_at == FIXED_NOW
    assert request.expires_at == FIXED_NOW + timedelta(seconds=120)

    events = audit.read_all()
    assert events[-1].event_type is EventType.HUMAN_APPROVAL_REQUESTED
    payload = events[-1].payload
    assert payload["request_id"] == "req-1"
    assert payload["evaluation_id"] == evaluation.evaluation_id
    assert payload["decision_id"] == "dec-1"
    assert payload["expires_at"] == request.expires_at.isoformat()


@pytest.mark.unit
def test_fr04_request_rejects_non_pending_and_duplicate_requests(tmp_path):
    """[FR-04] Only one request is allowed, and only while pending."""
    evaluation, gate, _, _, _, _, _ = _setup(tmp_path)
    gate.request(evaluation)
    with pytest.raises(IllegalExecutionStateError):
        gate.request(evaluation)

    approved_eval, _, _, _, _, _, _ = _setup(tmp_path / "approved", quantity="10")
    assert approved_eval.status is DecisionStatus.APPROVED
    with pytest.raises(IllegalExecutionStateError):
        gate.request(approved_eval)

    hold_eval, hold_gate, _, _, _, _, _ = _setup(
        tmp_path / "hold",
        action=DecisionAction.HOLD,
    )
    assert hold_eval.status is DecisionStatus.NO_ACTION
    with pytest.raises(IllegalExecutionStateError):
        hold_gate.request(hold_eval)


@pytest.mark.unit
def test_fr04_approval_request_can_be_approved_and_engine_transitions(tmp_path):
    """[FR-04] An approved request can be applied and executed by the engine."""
    evaluation, gate, engine, portfolio, audit, _, _ = _setup(tmp_path)
    request = gate.request(evaluation)

    approval = gate.decide(
        request,
        approver="supervisor",
        approved=True,
        reason="within risk limits",
    )

    assert isinstance(approval, HumanApproval)
    assert approval.request_id == request.request_id
    assert approval.decision_id == evaluation.decision.decision_id
    assert approval.approved is True
    assert approval.approver == "supervisor"
    assert approval.reason == "within risk limits"
    assert approval.decided_at == FIXED_NOW
    assert approval.expires_at == request.expires_at
    assert _event_types(audit)[-1] is EventType.HUMAN_APPROVAL
    assert audit.read_all()[-1].payload["approved"] is True

    updated = engine.apply_approval(evaluation, approval)
    assert updated.status is DecisionStatus.APPROVED
    result = engine.execute(updated)

    assert result.decision_id == evaluation.decision.decision_id
    assert portfolio.position("NVDA").quantity == Decimal("30.000000")
    assert engine.execution_count == 1


@pytest.mark.unit
def test_fr04_approval_request_can_be_denied_and_engine_rejects(tmp_path):
    """[FR-04] A denied request becomes a REJECTED evaluation."""
    evaluation, gate, engine, portfolio, audit, _, _ = _setup(tmp_path)
    request = gate.request(evaluation)

    approval = gate.decide(
        request,
        approver="supervisor",
        approved=False,
        reason="concentration too high",
    )

    assert approval.approved is False
    assert _event_types(audit)[-1] is EventType.HUMAN_APPROVAL
    assert audit.read_all()[-1].payload["approved"] is False

    updated = engine.apply_approval(evaluation, approval)
    assert updated.status is DecisionStatus.REJECTED
    assert any("concentration too high" in reason for reason in updated.reasons)
    with pytest.raises(IllegalExecutionStateError):
        engine.execute(updated)

    assert engine.execution_count == 0
    assert portfolio.position("NVDA") is None


@pytest.mark.unit
def test_fr04_decision_after_expiry_is_rejected_without_audit(tmp_path):
    """[FR-04] A request cannot be decided at or after its expiry."""
    evaluation, gate, _, _, audit, clock, _ = _setup(tmp_path, ttl=60)
    request = gate.request(evaluation)
    clock.advance(60)

    with pytest.raises(ApprovalExpiredError):
        gate.decide(
            request,
            approver="supervisor",
            approved=True,
            reason="late",
        )

    assert EventType.HUMAN_APPROVAL not in _event_types(audit)


@pytest.mark.unit
def test_fr04_decision_just_before_expiry_is_accepted(tmp_path):
    """[FR-04] A decision made before expiry is accepted."""
    evaluation, gate, _, _, _, clock, _ = _setup(tmp_path, ttl=60)
    request = gate.request(evaluation)
    clock.advance(59)

    approval = gate.decide(
        request,
        approver="supervisor",
        approved=True,
        reason="just in time",
    )

    assert approval.approved is True
    assert approval.decided_at == FIXED_NOW + timedelta(seconds=59)


@pytest.mark.unit
def test_fr04_mismatched_or_foreign_request_is_rejected(tmp_path):
    """[FR-04] Requests are bound to the decision that created them."""
    evaluation, gate, _, _, audit, _, _ = _setup(tmp_path)
    request = gate.request(evaluation)

    wrong_decision = replace(request, decision_id="other-decision")
    with pytest.raises(ApprovalMismatchError):
        gate.decide(
            wrong_decision,
            approver="supervisor",
            approved=True,
            reason="wrong decision",
        )

    foreign = ApprovalRequest(
        request_id="foreign",
        decision_id=evaluation.decision.decision_id,
        evaluation_id=evaluation.evaluation_id,
        created_at=FIXED_NOW,
        expires_at=FIXED_NOW + timedelta(seconds=60),
    )
    with pytest.raises(ApprovalMismatchError):
        gate.decide(
            foreign,
            approver="supervisor",
            approved=True,
            reason="foreign request",
        )

    assert EventType.HUMAN_APPROVAL not in _event_types(audit)


@pytest.mark.unit
def test_fr04_double_decision_is_rejected_with_one_audit_event(tmp_path):
    """[FR-04] An evaluation can only be approved or denied once."""
    evaluation, gate, _, _, audit, _, _ = _setup(tmp_path)
    request = gate.request(evaluation)
    gate.decide(
        request,
        approver="supervisor",
        approved=True,
        reason="first decision",
    )

    with pytest.raises(IllegalExecutionStateError):
        gate.decide(
            request,
            approver="supervisor",
            approved=False,
            reason="second decision",
        )

    events = [event for event in audit.read_all() if event.event_type is EventType.HUMAN_APPROVAL]
    assert len(events) == 1
    assert events[0].payload["approved"] is True


@pytest.mark.unit
def test_fr04_invalid_decision_fields_are_rejected(tmp_path):
    """[FR-04] A decision requires a booleans, an approver, and a reason."""
    evaluation, gate, _, _, audit, _, _ = _setup(tmp_path)
    request = gate.request(evaluation)

    with pytest.raises(ApprovalMismatchError):
        gate.decide(request, approver=" ", approved=True, reason="ok")
    with pytest.raises(ApprovalMismatchError):
        gate.decide(request, approver="supervisor", approved=True, reason=" ")
    with pytest.raises(ApprovalMismatchError):
        gate.decide(request, approver="supervisor", approved=1, reason="ok")

    assert EventType.HUMAN_APPROVAL not in _event_types(audit)
