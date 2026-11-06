"""Ultimate INV-01, INV-02, and INV-03 defense tests."""

from __future__ import annotations

import itertools
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from safety.engine import _ENGINE_TOKEN, SafetyEngine
from trading.approval import HumanApprovalGate
from trading.audit import AuditLog
from trading.executor import SimulatedExecutor
from trading.models import (
    AuditIntegrityError,
    DecisionAction,
    DecisionStatus,
    EventType,
    ExecutionAuthorization,
    ExecutionNotAuthorizedError,
    MarketQuote,
    SafetyConfig,
    TradeDecision,
)
from trading.pipeline import TradingPipeline
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


def _audit(tmp_path: Path, name="audit.jsonl") -> AuditLog:
    return AuditLog(tmp_path / name, clock=lambda: FIXED_NOW, id_factory=_seq("evt"))


def _setup(tmp_path: Path, *, config=None, cash="10000"):
    clock = _FixedClock()
    config = config or SafetyConfig()
    portfolio = Portfolio(
        Decimal(cash),
        fee_model=config.fee_model(),
        clock=clock.now,
    )
    audit = _audit(tmp_path)
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
    pipeline = TradingPipeline(engine, gate, portfolio, config)
    return engine, portfolio, audit, pipeline, gate


def _final_state(text="**Rating**: Buy"):
    return {
        "final_trade_decision": text,
        "company_of_interest": "NVDA",
        "trade_date": "2024-01-05",
    }


def _quote(price="100") -> MarketQuote:
    return MarketQuote(
        symbol="NVDA",
        price=Decimal(price),
        as_of=FIXED_NOW,
    )


def _event_types(audit: AuditLog) -> list[EventType]:
    return [event.event_type for event in audit.read_all()]


@pytest.mark.unit
@pytest.mark.parametrize(
    "case",
    ["rejected", "pending", "hold", "review", "bankrupt"],
)
def test_inv01_non_approved_outcomes_never_reach_execution(tmp_path, case):
    """[INV-01] Zero executions occur for every non-APPROVED outcome."""
    config = SafetyConfig()
    final_state = _final_state()
    if case == "rejected":
        config = SafetyConfig(allowed_symbols=frozenset({"AAPL"}))
    elif case == "pending":
        config = SafetyConfig(soft_max_order_notional=Decimal("100"))
    elif case == "hold":
        final_state = _final_state("**Rating**: Hold")
    elif case == "review":
        final_state = _final_state("No directional call.")
    elif case == "bankrupt":
        pass

    engine, portfolio, audit, pipeline, _ = _setup(
        tmp_path / case,
        config=config,
    )
    if case == "bankrupt":
        portfolio.mark_bankrupt(reason="test halt")

    result = pipeline.process(final_state, _quote(), run_id="run-1")

    assert result.evaluation.status is not DecisionStatus.APPROVED
    assert result.execution is None
    assert engine.execution_count == 0
    assert portfolio.position("NVDA") is None
    kinds = _event_types(audit)
    assert EventType.EXECUTION_STARTED not in kinds
    assert EventType.ORDER_EXECUTED not in kinds


@pytest.mark.unit
def test_inv01_approved_is_the_only_path_that_executes(tmp_path):
    """[INV-01] The approved path executes exactly once and is audited."""
    engine, portfolio, audit, pipeline, _ = _setup(tmp_path)

    result = pipeline.process(_final_state(), _quote(), run_id="run-1")

    assert result.evaluation.status is DecisionStatus.APPROVED
    assert result.execution is not None
    assert engine.execution_count == 1
    kinds = _event_types(audit)
    assert kinds.count(EventType.EXECUTION_STARTED) == 1
    assert kinds.count(EventType.ORDER_EXECUTED) == 1
    executed = [
        event for event in audit.read_all() if event.event_type is EventType.ORDER_EXECUTED
    ][0]
    approvals = [
        event
        for event in audit.read_all()
        if event.event_type is EventType.DECISION_APPROVED
        and event.payload["decision_id"] == executed.payload["decision_id"]
    ]
    assert len(approvals) == 1
    assert approvals[0].timestamp <= executed.timestamp
    assert portfolio.position("NVDA") is not None


@pytest.mark.unit
def test_inv02_forged_authorization_is_rejected_without_mutation(tmp_path):
    """[INV-02] A tokenless authorization cannot bypass the engine."""
    engine, portfolio, audit, _, _ = _setup(tmp_path)
    decision = TradeDecision(
        run_id="run-1",
        decision_id="dec-1",
        symbol="NVDA",
        action=DecisionAction.BUY,
        quantity=Decimal("5"),
    )
    evaluation = engine.evaluate(decision, _quote())
    assert evaluation.status is DecisionStatus.APPROVED
    before_version = portfolio.version
    before_cash = portfolio.cash

    direct_audit = _audit(tmp_path, name="direct-audit.jsonl")
    direct_executor = SimulatedExecutor(
        portfolio,
        direct_audit,
        authorization_token=_ENGINE_TOKEN,
        clock=lambda: FIXED_NOW,
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

    assert direct_executor.execution_count == 0
    assert portfolio.version == before_version
    assert portfolio.cash == before_cash
    assert portfolio.position("NVDA") is None
    assert direct_audit.read_all() == ()
    assert engine.execution_count == 0
    assert EventType.EXECUTION_STARTED not in _event_types(audit)


@pytest.mark.unit
@pytest.mark.parametrize("tamper", ["modify", "truncate", "delete"])
def test_inv03_audit_tampering_is_detected(tmp_path, tamper):
    """[INV-03] Modification, truncation, and deletion all fail integrity."""
    audit = _audit(tmp_path / tamper)
    audit.append(
        run_id="run-1",
        event_type=EventType.DECISION_RECEIVED,
        payload={"n": 1},
    )
    audit.append(
        run_id="run-1",
        event_type=EventType.DECISION_EVALUATED,
        payload={"n": 2},
    )

    if tamper == "modify":
        lines = audit.path.read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[0])
        record["payload"]["n"] = 999
        lines[0] = json.dumps(record, sort_keys=True, separators=(",", ":"))
        audit.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    elif tamper == "truncate":
        lines = audit.path.read_text(encoding="utf-8").splitlines(keepends=True)
        audit.path.write_text("".join(lines[:-1]), encoding="utf-8")
    else:
        audit.path.unlink()

    with pytest.raises(AuditIntegrityError):
        audit.verify_integrity()
