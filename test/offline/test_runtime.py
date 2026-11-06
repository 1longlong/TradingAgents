"""Startup composition tests."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from safety.engine import SafetyEngine
from trading.approval import HumanApprovalGate
from trading.audit import AuditLog
from trading.models import EventType
from trading.persistence import StateStore
from trading.pipeline import TradingPipeline
from trading.portfolio import Portfolio
from trading.runtime import (
    DEFAULT_INITIAL_CASH,
    RuntimeConfig,
    TradingRuntime,
    build_runtime,
)

FIXED_NOW = datetime(2024, 1, 5, 21, 0, tzinfo=timezone.utc)


class _FixedClock:
    def now(self) -> datetime:
        return FIXED_NOW

    def is_simulated(self) -> bool:
        return False

    def simulation_date(self):
        return None


def _config(tmp_path: Path, **overrides) -> RuntimeConfig:
    values = {
        "state_path": tmp_path / "state.json",
        "audit_path": tmp_path / "audit.jsonl",
    }
    values.update(overrides)
    return RuntimeConfig(**values)


@pytest.mark.unit
def test_fr06_build_runtime_constructs_all_components(tmp_path):
    """[FR-06] Startup wires audit, state, engine, gate, and pipeline."""
    runtime = build_runtime(_config(tmp_path), _FixedClock())

    assert isinstance(runtime, TradingRuntime)
    assert isinstance(runtime.portfolio, Portfolio)
    assert isinstance(runtime.audit, AuditLog)
    assert isinstance(runtime.store, StateStore)
    assert isinstance(runtime.engine, SafetyEngine)
    assert isinstance(runtime.gate, HumanApprovalGate)
    assert isinstance(runtime.pipeline, TradingPipeline)
    assert runtime.cursor is None
    assert runtime.portfolio.cash == DEFAULT_INITIAL_CASH
    assert runtime.portfolio.bankrupt is False
    assert runtime.audit.path.exists()
    assert runtime.audit.read_all() == ()


@pytest.mark.unit
def test_fr06_fresh_state_uses_configured_initial_cash(tmp_path):
    """[FR-06] A missing state file starts at the configured cash amount."""
    runtime = build_runtime(
        _config(tmp_path, initial_cash=Decimal("1234.56")),
        _FixedClock(),
    )
    assert runtime.portfolio.cash == Decimal("1234.56")
    assert runtime.portfolio.snapshot().total_equity == Decimal("1234.56")
    assert runtime.cursor is None


@pytest.mark.unit
def test_fr06_reset_clears_bankruptcy_and_preserves_audit(tmp_path):
    """[FR-06] Reset restores cash, clears BANKRUPT, and keeps audit history."""
    config = _config(tmp_path, initial_cash=Decimal("10000"))
    runtime = build_runtime(config, _FixedClock())
    runtime.audit.append(
        run_id="before-reset",
        event_type=EventType.STATE_LOADED,
        payload={"note": "existing history"},
    )
    runtime.portfolio.mark_bankrupt(reason="test halt")
    runtime.store.save(runtime.portfolio)

    reset_runtime = build_runtime(config, _FixedClock(), reset=True)

    assert reset_runtime.portfolio.cash == Decimal("10000.00")
    assert reset_runtime.portfolio.bankrupt is False
    assert reset_runtime.portfolio.applied_order_ids == frozenset()
    assert reset_runtime.cursor is None

    events = reset_runtime.audit.read_all()
    assert [event.event_type for event in events] == [
        EventType.STATE_LOADED,
        EventType.STATE_RESET,
    ]
    assert events[-1].payload["reason"] == "runtime reset"


@pytest.mark.unit
def test_fr06_runtime_loads_existing_bankruptcy_without_reset(tmp_path):
    """[FR-06] Startup without reset restores prior state unchanged."""
    config = _config(tmp_path, initial_cash=Decimal("10000"))
    first = build_runtime(config, _FixedClock())
    first.portfolio.mark_bankrupt(reason="persisted halt")
    first.store.save(first.portfolio)

    loaded = build_runtime(config, _FixedClock())

    assert loaded.portfolio.bankrupt is True
    assert loaded.portfolio.bankruptcy_reason == "persisted halt"
    assert loaded.portfolio.cash == Decimal("10000.00")


@pytest.mark.unit
def test_fr06_runtime_rejects_negative_initial_cash():
    """[FR-06] Invalid startup cash is rejected before any file is written."""
    with pytest.raises(ValueError):
        RuntimeConfig(
            state_path=Path("state.json"),
            audit_path=Path("audit.jsonl"),
            initial_cash=Decimal("-1"),
        )
