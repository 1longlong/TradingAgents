"""Standalone CLI inspection and reset tests."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from trading.audit import AuditLog
from trading.cli import main
from trading.models import EventType
from trading.runtime import RuntimeConfig, build_runtime

FIXED_NOW = datetime(2024, 1, 5, 21, 0, tzinfo=timezone.utc)


class _FixedClock:
    def now(self) -> datetime:
        return FIXED_NOW

    def is_simulated(self) -> bool:
        return False

    def simulation_date(self):
        return None


def _paths(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "state.json", tmp_path / "audit.jsonl"


def _read_audit(path: Path) -> tuple:
    return AuditLog(path, clock=lambda: FIXED_NOW).read_all()


@pytest.mark.unit
def test_fr06_cli_reset_clears_state_and_prints_summary(tmp_path, capsys):
    """[FR-06] --reset clears state and prints the fresh portfolio summary."""
    state_path, audit_path = _paths(tmp_path)
    config = RuntimeConfig(
        state_path=state_path,
        audit_path=audit_path,
        initial_cash=Decimal("10000"),
    )
    runtime = build_runtime(config, _FixedClock())
    runtime.portfolio.mark_bankrupt(reason="cli test")
    runtime.store.save(runtime.portfolio)

    code = main(
        [
            "--state",
            str(state_path),
            "--audit",
            str(audit_path),
            "--initial-cash",
            "5000",
            "--reset",
        ]
    )
    output = capsys.readouterr().out

    assert code == 0
    assert "State reset." in output
    assert "Cash: 5000.00" in output
    assert "Equity: 5000.00" in output
    assert "Bankrupt: no" in output
    assert state_path.exists()

    events = _read_audit(audit_path)
    assert events[-1].event_type is EventType.STATE_RESET
    assert events[-1].payload["initial_cash"] == "5000.00"


@pytest.mark.unit
def test_fr06_cli_without_reset_loads_and_prints_without_trading(tmp_path, capsys):
    """[FR-06] Inspection loads state, prints it, and never executes a trade."""
    state_path, audit_path = _paths(tmp_path)
    reset_code = main(
        [
            "--state",
            str(state_path),
            "--audit",
            str(audit_path),
            "--initial-cash",
            "2500",
            "--reset",
        ]
    )
    assert reset_code == 0
    capsys.readouterr()

    code = main(
        [
            "--state",
            str(state_path),
            "--audit",
            str(audit_path),
        ]
    )
    output = capsys.readouterr().out

    assert code == 0
    assert "State reset." not in output
    assert "Cash: 2500.00" in output
    assert "Equity: 2500.00" in output
    assert "Bankrupt: no" in output
    events = _read_audit(audit_path)
    assert EventType.EXECUTION_STARTED not in {event.event_type for event in events}
    assert EventType.ORDER_EXECUTED not in {event.event_type for event in events}


@pytest.mark.unit
def test_fr06_cli_reset_uses_default_cash_when_not_specified(tmp_path, capsys):
    """[FR-06] The CLI default matches the runtime default initial cash."""
    state_path, audit_path = _paths(tmp_path)

    code = main(
        [
            "--state",
            str(state_path),
            "--audit",
            str(audit_path),
            "--reset",
        ]
    )
    output = capsys.readouterr().out

    assert code == 0
    assert "Cash: 100000.00" in output
    assert "Equity: 100000.00" in output


@pytest.mark.unit
def test_fr06_cli_corrupt_state_returns_nonzero_without_reset(tmp_path, capsys):
    """[FR-06] Corrupt state is reported instead of silently replaced."""
    state_path, audit_path = _paths(tmp_path)
    state_path.write_text("{not-json", encoding="utf-8")

    code = main(
        [
            "--state",
            str(state_path),
            "--audit",
            str(audit_path),
        ]
    )
    captured = capsys.readouterr()

    assert code == 1
    assert "error:" in captured.err
    assert captured.out == ""
