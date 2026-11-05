"""Backtest calendar and provider tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from safety.rules import DEFAULT_SAFETY_RULES
from trading.backtest import (
    DecisionProvider,
    HistoricalQuoteProvider,
    MockDecisionProvider,
    MockQuoteProvider,
    QuoteProvider,
    RealDecisionProvider,
    SimulationDay,
    TradingCalendar,
    WeekdayCalendar,
)
from trading.clock import SimulationClock
from trading.models import (
    DecisionAction,
    RuleContext,
    SafetyConfig,
    SimulationError,
)
from trading.portfolio import Portfolio

FIXED_DATE = date(2024, 1, 5)


def _simulation_day(
    day=FIXED_DATE,
    *,
    symbol="NVDA",
    run_id="run-1",
    clock=None,
) -> SimulationDay:
    clock = clock or SimulationClock(day)
    clock.set_date(day)
    portfolio = Portfolio(
        Decimal("10000"),
        fee_model=SafetyConfig().fee_model(),
        clock=clock.now,
    )
    return SimulationDay(
        run_id=run_id,
        symbol=symbol,
        date=day,
        clock=clock,
        portfolio=portfolio,
        portfolio_context=portfolio.to_context(),
    )


def _rule(rule_id: str):
    return next(rule for rule in DEFAULT_SAFETY_RULES if rule.rule_id == rule_id)


class _FakeGraph:
    def __init__(self, final_decision="**Rating**: Buy"):
        self.final_decision = final_decision
        self.calls = []

    def propagate(
        self,
        company_name,
        trade_date,
        *,
        asset_type="stock",
        portfolio=None,
    ):
        self.calls.append((company_name, trade_date, asset_type, portfolio))
        return (
            {
                "company_of_interest": company_name,
                "trade_date": trade_date,
                "final_trade_decision": self.final_decision,
            },
            "Buy",
        )


@pytest.mark.unit
def test_fr05_weekday_calendar_skips_weekends_and_is_inclusive():
    """[FR-05] Calendar iteration yields weekdays only, inclusive of bounds."""
    days = list(
        WeekdayCalendar().trading_days(
            date(2024, 1, 5),
            date(2024, 1, 8),
        )
    )
    assert days == [date(2024, 1, 5), date(2024, 1, 8)]
    assert isinstance(WeekdayCalendar(), TradingCalendar)


@pytest.mark.unit
def test_fr05_weekday_calendar_honours_holidays_and_rejects_reversed_range():
    """[FR-05] Explicit holidays are skipped and invalid ranges fail."""
    calendar = WeekdayCalendar(holidays=frozenset({date(2024, 1, 8)}))
    assert list(calendar.trading_days(date(2024, 1, 5), date(2024, 1, 9))) == [
        date(2024, 1, 5),
        date(2024, 1, 9),
    ]
    with pytest.raises(ValueError):
        list(calendar.trading_days(date(2024, 1, 9), date(2024, 1, 5)))


@pytest.mark.unit
def test_fr05_mock_decision_provider_fixed_action_is_instant_and_deterministic():
    """[FR-05] A fixed mock decision needs no network or graph."""
    day = _simulation_day()
    provider = MockDecisionProvider(
        DecisionAction.BUY,
        quantity=Decimal("2.5"),
    )

    first = provider.decision_for(day)
    second = provider.decision_for(day)

    assert isinstance(provider, DecisionProvider)
    assert first == second
    assert first.action is DecisionAction.BUY
    assert first.quantity == Decimal("2.5")
    assert first.run_id == "run-1"
    assert first.symbol == "NVDA"
    assert first.decision_id == "run-1:NVDA:2024-01-05"
    assert first.source == "mock"


@pytest.mark.unit
def test_fr05_mock_decision_provider_schedule_and_default():
    """[FR-05] Date schedules override the default action."""
    provider = MockDecisionProvider(
        {date(2024, 1, 5): DecisionAction.SELL},
        default_action=DecisionAction.HOLD,
    )

    sell = provider.decision_for(_simulation_day(date(2024, 1, 5)))
    missing = provider.decision_for(_simulation_day(date(2024, 1, 8)))

    assert sell.action is DecisionAction.SELL
    assert missing.action is DecisionAction.HOLD
    assert missing.quantity is None


@pytest.mark.unit
def test_fr05_mock_quote_provider_aligns_with_simulation_clock():
    """[FR-05] Mock quotes use simulated time and satisfy SR-03."""
    day = _simulation_day()
    provider = MockQuoteProvider({day.date: Decimal("100.00")})

    quote = provider.quote_for(day.symbol, day.date, day.clock)

    assert isinstance(provider, QuoteProvider)
    assert quote is not None
    assert quote.symbol == "NVDA"
    assert quote.price == Decimal("100.00")
    assert quote.as_of == day.clock.now()
    assert quote.as_of.date() == day.date

    decision = MockDecisionProvider(
        DecisionAction.BUY,
        quantity=Decimal("1"),
    ).decision_for(day)
    context = RuleContext(
        decision=decision,
        quote=quote,
        config=SafetyConfig(),
        portfolio=day.portfolio.snapshot(),
        order_intent=None,
        now=day.clock.now(),
        is_simulated=day.clock.is_simulated(),
    )
    assert _rule("SR-03").evaluate(context).passed is True


@pytest.mark.unit
def test_fr05_mock_quote_provider_fixed_price_and_missing_day():
    """[FR-05] Fixed prices repeat; a sparse schedule reports no quote."""
    day = _simulation_day()
    fixed = MockQuoteProvider(Decimal("50"))
    sparse = MockQuoteProvider({date(2024, 1, 8): Decimal("50")})

    assert fixed.quote_for("NVDA", day.date, day.clock).price == Decimal("50")
    assert sparse.quote_for("NVDA", day.date, day.clock) is None
    with pytest.raises(SimulationError):
        sparse.quote_for("NVDA", date(2024, 1, 8), day.clock)


@pytest.mark.unit
def test_fr05_real_decision_provider_uses_factory_and_simulated_date():
    """[FR-05] The real provider passes the simulated date and holdings to the graph."""
    fake = _FakeGraph()
    created = []

    def factory():
        created.append(True)
        return fake

    day = _simulation_day(date(2024, 1, 8))
    provider = RealDecisionProvider(factory, asset_type="stock")

    decision = provider.decision_for(day)

    assert created == [True]
    assert fake.calls == [
        ("NVDA", "2024-01-08", "stock", day.portfolio_context)
    ]
    assert decision.action is DecisionAction.BUY
    assert decision.run_id == "run-1"
    assert decision.symbol == "NVDA"
    assert decision.quantity is None

    provider.decision_for(day)
    assert created == [True]
    assert len(fake.calls) == 2
    assert isinstance(provider, DecisionProvider)


@pytest.mark.unit
def test_fr05_real_decision_provider_unparseable_output_is_review():
    """[FR-01] An unparseable graph decision stays non-executable REVIEW."""
    fake = _FakeGraph("No clear call in this report.")
    provider = RealDecisionProvider(lambda: fake)

    decision = provider.decision_for(_simulation_day())

    assert decision.action is DecisionAction.REVIEW
    assert decision.quantity is None


@pytest.mark.unit
def test_fr05_historical_quote_provider_reads_only_requested_day():
    """[FR-05] Historical lookups receive exactly the simulation date, no look-ahead."""
    calls = []

    def fetch_close(symbol, day):
        calls.append((symbol, day))
        return Decimal("100.00")

    day = _simulation_day(date(2024, 1, 8))
    provider = HistoricalQuoteProvider(fetch_close)

    quote = provider.quote_for("NVDA", day.date, day.clock)

    assert isinstance(provider, QuoteProvider)
    assert calls == [("NVDA", date(2024, 1, 8))]
    assert quote is not None
    assert quote.price == Decimal("100.00")
    assert quote.as_of == day.clock.now()

    with pytest.raises(SimulationError):
        provider.quote_for("NVDA", date(2024, 1, 9), day.clock)
    assert calls == [("NVDA", date(2024, 1, 8))]


@pytest.mark.unit
def test_fr05_historical_quote_provider_handles_missing_and_string_prices():
    """[FR-05] Missing bars are skipped and numeric strings are normalised."""
    def missing(symbol, day):
        return None

    def string_price(symbol, day):
        return "123.45"

    day = _simulation_day()
    assert HistoricalQuoteProvider(missing).quote_for("NVDA", day.date, day.clock) is None
    quote = HistoricalQuoteProvider(string_price).quote_for(
        "NVDA",
        day.date,
        day.clock,
    )
    assert quote is not None
    assert quote.price == Decimal("123.45")
