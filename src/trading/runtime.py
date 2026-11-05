"""Startup composition for the simulated trading subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from safety.engine import SafetyEngine
from trading.approval import HumanApprovalGate
from trading.audit import AuditLog
from trading.clock import Clock
from trading.models import SafetyConfig, to_decimal
from trading.persistence import BacktestCursor, StateStore
from trading.pipeline import TradingPipeline
from trading.portfolio import Portfolio

DEFAULT_INITIAL_CASH = Decimal("100000.00")


@dataclass(frozen=True)
class RuntimeConfig:
    state_path: Path
    audit_path: Path
    initial_cash: Decimal = DEFAULT_INITIAL_CASH
    safety: SafetyConfig = field(default_factory=SafetyConfig)

    def __post_init__(self) -> None:
        initial_cash = to_decimal(self.initial_cash, field="initial_cash")
        if initial_cash < 0:
            raise ValueError("initial_cash must be non-negative")
        object.__setattr__(self, "state_path", Path(self.state_path))
        object.__setattr__(self, "audit_path", Path(self.audit_path))
        object.__setattr__(self, "initial_cash", initial_cash)


@dataclass
class TradingRuntime:
    portfolio: Portfolio
    audit: AuditLog
    store: StateStore
    engine: SafetyEngine
    gate: HumanApprovalGate
    pipeline: TradingPipeline
    cursor: BacktestCursor | None = None


def build_runtime(
    config: RuntimeConfig,
    clock: Clock,
    reset: bool = False,
) -> TradingRuntime:
    """Construct a fully wired runtime, loading or resetting persisted state."""
    if not isinstance(config, RuntimeConfig):
        raise TypeError("config must be a RuntimeConfig")
    fee_model = config.safety.fee_model()
    audit = AuditLog(config.audit_path, clock=clock.now)
    store = StateStore(
        config.state_path,
        fee_model=fee_model,
        clock=clock,
        audit=audit,
        initial_cash=config.initial_cash,
    )

    if reset:
        portfolio = store.reset(
            initial_cash=config.initial_cash,
            reason="runtime reset",
        )
        cursor = None
    else:
        portfolio, cursor = store.load(initial_cash=config.initial_cash)

    engine = SafetyEngine(
        config.safety,
        portfolio,
        audit,
        clock=clock,
    )
    gate = HumanApprovalGate(
        audit,
        config.safety,
        clock=clock,
    )
    pipeline = TradingPipeline(
        engine,
        gate,
        portfolio,
        config.safety,
    )
    return TradingRuntime(
        portfolio=portfolio,
        audit=audit,
        store=store,
        engine=engine,
        gate=gate,
        pipeline=pipeline,
        cursor=cursor,
    )
