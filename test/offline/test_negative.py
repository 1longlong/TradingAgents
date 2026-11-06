"""Required negative tests for safety, execution, audit, and bypass attempts."""

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


def _setup(tmp_path: Path, *, config=None):
    clock = _FixedClock()
    config = config or SafetyConfig()
    portfolio = Portfolio(
        Decimal("10000"),
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
    return engine, portfolio, audit, pipeline


def _final_state(text="**Rating**: Buy"):
    return {
        "final_trade_decision": text,
        "company_of_interest": "NVDA",
        "trade_date": "2024-01-05",
    }


def _quote(price="100") -> MarketQuote:
    return MarketQuote(symbol="NVDA", price=Decimal(price), as_of=FIXED_NOW)


@pytest.mark.unit
def test_fr01_llm_decision_violating_rule_is_rejected(tmp_path):
    """[FR-01] A rule violation from the graph becomes REJECTED with audit."""
    config = SafetyConfig(allowed_symbols=frozenset({"AAPL"}))
    _, _, audit, pipeline = _setup(tmp_path, config=config)

    result = pipeline.process(_final_state(), _quote(), run_id="run-1")

    assert result.evaluation.status is DecisionStatus.REJECTED
    assert any("allowlist" in reason for reason in result.evaluation.reasons)
    assert EventType.DECISION_REJECTED in {
        event.event_type for event in audit.read_all()
    }


@pytest.mark.unit
def test_inv01_rejected_decision_never_reaches_executor(tmp_path):
    """[INV-01] A REJECTED evaluation produces no execution or mutation."""
    config = SafetyConfig(allowed_symbols=frozenset({"AAPL"}))
    engine, portfolio, audit, pipeline = _setup(tmp_path, config=config)

    result = pipeline.process(_final_state(), _quote(), run_id="run-1")

    assert result.evaluation.status is DecisionStatus.REJECTED
    assert result.execution is None
    assert engine.execution_count == 0
    assert portfolio.position("NVDA") is None
    kinds = {event.event_type for event in audit.read_all()}
    assert EventType.EXECUTION_STARTED not in kinds
    assert EventType.ORDER_EXECUTED not in kinds


@pytest.mark.unit
def test_inv03_attempt_to_modify_audit_fails(tmp_path):
    """[INV-03] Modifying an existing audit entry is detected."""
    audit = _audit(tmp_path)
    audit.append(
        run_id="run-1",
        event_type=EventType.DECISION_RECEIVED,
        payload={"decision_id": "dec-1"},
    )
    lines = audit.path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["payload"]["decision_id"] = "tampered"
    lines[0] = json.dumps(record, sort_keys=True, separators=(",", ":"))
    audit.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(AuditIntegrityError):
        audit.verify_integrity()


@pytest.mark.unit
def test_inv02_attempt_to_bypass_rule_engine_fails(tmp_path):
    """[INV-02] A forged authorization cannot execute directly."""
    engine, portfolio, _, _ = _setup(tmp_path)
    decision = TradeDecision(
        run_id="run-1",
        decision_id="dec-1",
        symbol="NVDA",
        action=DecisionAction.BUY,
        quantity=Decimal("5"),
    )
    evaluation = engine.evaluate(decision, _quote())
    assert evaluation.status is DecisionStatus.APPROVED
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
    assert direct_audit.read_all() == ()
    assert portfolio.position("NVDA") is None
    assert engine.execution_count == 0
