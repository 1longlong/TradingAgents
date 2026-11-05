"""Backtest runner and resume tests."""

from __future__ import annotations

import itertools
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from safety.engine import SafetyEngine
from trading.approval import HumanApprovalGate
from trading.audit import AuditLog
from trading.backtest import (
    BacktestRunner,
    MockDecisionProvider,
    MockQuoteProvider,
    WeekdayCalendar,
)
from trading.clock import SimulationClock
from trading.models import (
    DecisionAction,
    EventType,
    SafetyConfig,
)
from trading.persistence import StateStore
from trading.pipeline import SizingPolicy, TradingPipeline
from trading.portfolio import Portfolio


def _seq(prefix: str):
    counter = itertools.count(1)
    return lambda: f"{prefix}-{next(counter)}"


def _setup(
    tmp_path: Path,
    *,
    start_date,
    end_date,
    prices,
    config=None,
    sizing=None,
    initial_cash="10000",
):
    clock = SimulationClock(start_date)
    config = config or SafetyConfig()
    portfolio = Portfolio(
        Decimal(initial_cash),
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
    store = StateStore(
        tmp_path / "state.json",
        fee_model=config.fee_model(),
        clock=clock,
        audit=audit,
        initial_cash=Decimal(initial_cash),
    )
    return clock, config, portfolio, audit, engine, gate, pipeline, store


class _InterruptingProvider:
    def __init__(self, base, interrupt_on):
        self._base = base
        self._interrupt_on = interrupt_on

    def decision_for(self, day):
        if day.date == self._interrupt_on:
            raise RuntimeError("simulated interruption")
        return self._base.decision_for(day)


@pytest.mark.unit
def test_fr05_100_day_mock_run_completes_and_persists_cursor(tmp_path):
    """[FR-05] A 100-day zero-network run completes with persisted progress."""
    calendar = WeekdayCalendar()
    start = date(2024, 1, 1)
    all_days = list(calendar.trading_days(start, date(2024, 12, 31)))
    days = all_days[:100]
    end = days[-1]
    config = SafetyConfig(
        fee_bps=Decimal("0"),
        min_fee=Decimal("0"),
        soft_max_order_notional=Decimal("10000"),
        hard_max_order_notional=Decimal("10000"),
        max_position_fraction=Decimal("1.0"),
    )
    clock, _, portfolio, _, engine, _, pipeline, store = _setup(
        tmp_path,
        start_date=start,
        end_date=end,
        prices=days,
        config=config,
    )
    runner = BacktestRunner(
        pipeline=pipeline,
        engine=engine,
        state_store=store,
        decision_provider=MockDecisionProvider(DecisionAction.BUY),
        quote_provider=MockQuoteProvider({day: Decimal("100") for day in days}),
        calendar=calendar,
        clock=clock,
        portfolio=portfolio,
        symbol="NVDA",
        start_date=start,
        end_date=end,
        run_id="bt-100",
        initial_cash=Decimal("10000"),
    )

    result = runner.run()

    assert result.days_processed == 100
    assert result.days_skipped == 0
    assert result.executions > 0
    assert result.bankrupt is False
    assert result.final_equity > 0
    _, cursor = store.load()
    assert cursor is not None
    assert cursor.last_completed_date == end


@pytest.mark.unit
def test_fr05_resume_continues_after_interrupted_day(tmp_path):
    """[FR-05] An interrupted run resumes after the last saved day."""
    calendar = WeekdayCalendar()
    days = list(calendar.trading_days(date(2024, 1, 1), date(2024, 1, 12)))
    start, end = days[0], days[-1]
    config = SafetyConfig(
        fee_bps=Decimal("0"),
        min_fee=Decimal("0"),
        soft_max_order_notional=Decimal("10000"),
        hard_max_order_notional=Decimal("10000"),
        max_position_fraction=Decimal("1.0"),
    )
    clock, _, portfolio, _, engine, _, pipeline, store = _setup(
        tmp_path,
        start_date=start,
        end_date=end,
        prices=days,
        config=config,
    )
    base_provider = MockDecisionProvider(DecisionAction.BUY)
    first_runner = BacktestRunner(
        pipeline=pipeline,
        engine=engine,
        state_store=store,
        decision_provider=_InterruptingProvider(base_provider, days[3]),
        quote_provider=MockQuoteProvider({day: Decimal("100") for day in days}),
        calendar=calendar,
        clock=clock,
        portfolio=portfolio,
        symbol="NVDA",
        start_date=start,
        end_date=end,
        run_id="bt-resume",
        initial_cash=Decimal("10000"),
    )

    with pytest.raises(RuntimeError, match="interruption"):
        first_runner.run()

    _, interrupted_cursor = store.load()
    assert interrupted_cursor is not None
    assert interrupted_cursor.last_completed_date == days[2]

    resumed_runner = BacktestRunner(
        pipeline=pipeline,
        engine=engine,
        state_store=store,
        decision_provider=base_provider,
        quote_provider=MockQuoteProvider({day: Decimal("100") for day in days}),
        calendar=calendar,
        clock=clock,
        portfolio=portfolio,
        symbol="NVDA",
        start_date=start,
        end_date=end,
        run_id="bt-resume",
        initial_cash=Decimal("10000"),
    )
    result = resumed_runner.run()

    assert result.days_processed == len(days) - 3
    _, cursor = store.load()
    assert cursor is not None
    assert cursor.last_completed_date == end


@pytest.mark.unit
def test_fr06_bankruptcy_rejects_all_subsequent_days(tmp_path):
    """[FR-06] Equity at zero makes every later day reject without execution."""
    days = list(WeekdayCalendar().trading_days(date(2024, 1, 1), date(2024, 1, 3)))
    config = SafetyConfig(
        fee_bps=Decimal("0"),
        min_fee=Decimal("0"),
        soft_max_order_notional=Decimal("1000"),
        hard_max_order_notional=Decimal("1000"),
        max_position_fraction=Decimal("1.0"),
    )
    clock, _, portfolio, audit, engine, _, pipeline, store = _setup(
        tmp_path,
        start_date=days[0],
        end_date=days[-1],
        prices=days,
        config=config,
        sizing=SizingPolicy(Decimal("1.0")),
        initial_cash="1000",
    )
    runner = BacktestRunner(
        pipeline=pipeline,
        engine=engine,
        state_store=store,
        decision_provider=MockDecisionProvider(DecisionAction.BUY),
        quote_provider=MockQuoteProvider(
            {
                days[0]: Decimal("100"),
                days[1]: Decimal("0"),
                days[2]: Decimal("100"),
            }
        ),
        calendar=WeekdayCalendar(),
        clock=clock,
        portfolio=portfolio,
        symbol="NVDA",
        start_date=days[0],
        end_date=days[-1],
        run_id="bt-bankrupt",
        initial_cash=Decimal("1000"),
    )

    result = runner.run()

    assert result.bankrupt is True
    assert result.executions == 1
    assert result.rejections >= 2
    assert portfolio.bankrupt is True
    rejected = [
        event
        for event in audit.read_all()
        if event.event_type is EventType.DECISION_REJECTED
    ]
    assert any("BANKRUPT" in event.payload["reasons"] for event in rejected)
    _, cursor = store.load()
    assert cursor is not None
    assert cursor.last_completed_date == days[-1]


@pytest.mark.unit
def test_fr05_missing_quote_day_is_skipped_and_cursor_advances(tmp_path):
    """[FR-05] A missing quote skips the day but still records completion."""
    days = list(WeekdayCalendar().trading_days(date(2024, 1, 1), date(2024, 1, 3)))
    clock, _, portfolio, _, engine, _, pipeline, store = _setup(
        tmp_path,
        start_date=days[0],
        end_date=days[-1],
        prices=days,
    )
    runner = BacktestRunner(
        pipeline=pipeline,
        engine=engine,
        state_store=store,
        decision_provider=MockDecisionProvider(DecisionAction.BUY),
        quote_provider=MockQuoteProvider(
            {days[0]: Decimal("100"), days[2]: Decimal("100")}
        ),
        calendar=WeekdayCalendar(),
        clock=clock,
        portfolio=portfolio,
        symbol="NVDA",
        start_date=days[0],
        end_date=days[-1],
        run_id="bt-skip",
        initial_cash=Decimal("10000"),
    )

    result = runner.run()

    assert result.days_processed == 3
    assert result.days_skipped == 1
    _, cursor = store.load()
    assert cursor is not None
    assert cursor.last_completed_date == days[-1]
