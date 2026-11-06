"""Walk-forward calendar and deterministic decision/quote providers."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from safety.engine import SafetyEngine
from trading.clock import SimulationClock
from trading.models import (
    BacktestStateError,
    DecisionAction,
    DecisionStatus,
    EvaluationResult,
    HumanApproval,
    MarketQuote,
    OrderType,
    SimulationError,
    TradeDecision,
    to_decimal,
)
from trading.persistence import BacktestCursor, StateStore
from trading.pipeline import TradingPipeline, decision_from_final_state
from trading.portfolio import Portfolio
from tradingagents.portfolio import PortfolioContext


@runtime_checkable
class TradingCalendar(Protocol):
    def trading_days(self, start_date: date, end_date: date) -> Iterator[date]: ...


@runtime_checkable
class DecisionProvider(Protocol):
    def decision_for(self, day: SimulationDay) -> TradeDecision: ...


@runtime_checkable
class QuoteProvider(Protocol):
    def quote_for(
        self,
        symbol: str,
        day: date,
        clock: SimulationClock,
    ) -> MarketQuote | None: ...


class GraphLike(Protocol):
    def propagate(
        self,
        company_name: str,
        trade_date: str,
        *,
        asset_type: str = "stock",
        portfolio: PortfolioContext | None = None,
    ) -> tuple[Mapping[str, Any], str]: ...


@dataclass(frozen=True)
class SimulationDay:
    run_id: str
    symbol: str
    date: date
    clock: SimulationClock
    portfolio: Portfolio
    portfolio_context: PortfolioContext


class WeekdayCalendar:
    """Monday-Friday calendar with optional explicit holidays."""

    def __init__(self, holidays: frozenset[date] = frozenset()) -> None:
        self._holidays = frozenset(
            item.date() if isinstance(item, datetime) else item
            for item in holidays
        )

    def trading_days(self, start_date: date, end_date: date) -> Iterator[date]:
        start = self._coerce(start_date, "start_date")
        end = self._coerce(end_date, "end_date")
        if end < start:
            raise ValueError("end_date must not be before start_date")
        cursor = start
        while cursor <= end:
            if cursor.weekday() < 5 and cursor not in self._holidays:
                yield cursor
            cursor += timedelta(days=1)

    @staticmethod
    def _coerce(value: date, field: str) -> date:
        if isinstance(value, datetime):
            return value.date()
        if not isinstance(value, date):
            raise ValueError(f"{field} must be a date")
        return value


def _coerce_action(value: Any) -> DecisionAction:
    if isinstance(value, DecisionAction):
        return value
    try:
        return DecisionAction(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unknown decision action: {value!r}") from exc


def _coerce_day_key(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if not isinstance(value, date):
        raise ValueError(f"decision schedule keys must be dates, got {value!r}")
    return value


def _decision_id(run_id: str, symbol: str, day: date) -> str:
    return f"{run_id}:{symbol}:{day.isoformat()}"


class MockDecisionProvider:
    """Deterministic decisions from a date schedule or one fixed action."""

    def __init__(
        self,
        decisions: Mapping[date, DecisionAction] | DecisionAction,
        *,
        default_action: DecisionAction = DecisionAction.HOLD,
        quantity: Decimal | None = None,
    ) -> None:
        self._default_action = _coerce_action(default_action)
        self._quantity = (
            to_decimal(quantity, field="quantity") if quantity is not None else None
        )
        if isinstance(decisions, Mapping):
            self._schedule = {
                _coerce_day_key(key): _coerce_action(value)
                for key, value in decisions.items()
            }
        else:
            self._schedule = None
            self._fixed_action = _coerce_action(decisions)

    def decision_for(self, day: SimulationDay) -> TradeDecision:
        if self._schedule is not None:
            action = self._schedule.get(day.date, self._default_action)
        else:
            action = self._fixed_action
        return TradeDecision(
            run_id=day.run_id,
            decision_id=_decision_id(day.run_id, day.symbol, day.date),
            symbol=day.symbol,
            action=action,
            quantity=self._quantity,
            order_type=OrderType.MARKET,
            limit_price=None,
            rationale=f"mock decision: {action.value}",
            source="mock",
        )


class RealDecisionProvider:
    """Adapt TradingAgents graph output to a decision using a lazy factory."""

    def __init__(
        self,
        graph_factory: Callable[[], GraphLike],
        *,
        asset_type: str = "stock",
    ) -> None:
        self._graph_factory = graph_factory
        self._graph: GraphLike | None = None
        self._asset_type = asset_type

    def decision_for(self, day: SimulationDay) -> TradeDecision:
        graph = self._graph
        if graph is None:
            graph = self._graph_factory()
            self._graph = graph
        final_state, _signal = graph.propagate(
            day.symbol,
            day.date.isoformat(),
            asset_type=self._asset_type,
            portfolio=day.portfolio_context,
        )
        return decision_from_final_state(
            final_state,
            run_id=day.run_id,
            symbol=day.symbol,
        )


def _require_simulated_date(
    clock: SimulationClock,
    day: date,
    provider: str,
) -> None:
    if clock.simulation_date() != day:
        raise SimulationError(
            f"{provider} requires the SimulationClock to be set to {day.isoformat()}"
        )


class MockQuoteProvider:
    """Fixed daily closes; timestamps come from the simulation clock."""

    def __init__(self, prices: Mapping[date, Decimal] | Decimal) -> None:
        if isinstance(prices, Mapping):
            self._prices = {
                _coerce_day_key(key): to_decimal(value, field="price")
                for key, value in prices.items()
            }
            self._fixed_price = None
        else:
            self._prices = None
            self._fixed_price = to_decimal(prices, field="price")

    def quote_for(
        self,
        symbol: str,
        day: date,
        clock: SimulationClock,
    ) -> MarketQuote | None:
        _require_simulated_date(clock, day, "MockQuoteProvider")
        if self._prices is not None:
            price = self._prices.get(_coerce_day_key(day))
        else:
            price = self._fixed_price
        if price is None:
            return None
        return MarketQuote(symbol=symbol, price=price, as_of=clock.now())


class HistoricalQuoteProvider:
    """Read one historical close via an injected, read-only date function."""

    def __init__(
        self,
        fetch_close: Callable[[str, date], Decimal | str | int | None],
    ) -> None:
        self._fetch_close = fetch_close

    def quote_for(
        self,
        symbol: str,
        day: date,
        clock: SimulationClock,
    ) -> MarketQuote | None:
        _require_simulated_date(clock, day, "HistoricalQuoteProvider")
        value = self._fetch_close(symbol, day)
        if value is None:
            return None
        price = to_decimal(value, field="close")
        return MarketQuote(symbol=symbol, price=price, as_of=clock.now())



@dataclass(frozen=True)
class BacktestResult:
    run_id: str
    symbol: str
    start_date: date
    end_date: date
    days_processed: int
    days_skipped: int
    executions: int
    rejections: int
    pending_approvals: int
    no_actions: int
    final_equity: Decimal
    bankrupt: bool


_RATING_TEXT = {
    DecisionAction.BUY: "Buy",
    DecisionAction.SELL: "Sell",
    DecisionAction.HOLD: "Hold",
    DecisionAction.REVIEW: None,
}


def _coerce_backtest_date(value: date, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if not isinstance(value, date):
        raise ValueError(f"{field} must be a date")
    return value


def _pipeline_state(decision: TradeDecision, symbol: str, day: date) -> dict:
    rating = _RATING_TEXT.get(decision.action)
    text = (
        f"**Rating**: {rating}"
        if rating is not None
        else "No directional rating."
    )
    return {
        "final_trade_decision": text,
        "company_of_interest": symbol,
        "trade_date": day.isoformat(),
    }


class BacktestRunner:
    """Walk one simulated day at a time, persisting progress after each day."""

    def __init__(
        self,
        *,
        pipeline: TradingPipeline,
        engine: SafetyEngine,
        state_store: StateStore,
        decision_provider: DecisionProvider,
        quote_provider: QuoteProvider,
        calendar: TradingCalendar,
        clock: SimulationClock,
        portfolio: Portfolio,
        symbol: str,
        start_date: date,
        end_date: date,
        run_id: str,
        initial_cash: Decimal,
        approval_handler: Callable[[EvaluationResult], HumanApproval] | None = None,
    ) -> None:
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol must be non-empty")
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id must be non-empty")
        start = _coerce_backtest_date(start_date, "start_date")
        end = _coerce_backtest_date(end_date, "end_date")
        if end < start:
            raise ValueError("end_date must not be before start_date")
        cash = to_decimal(initial_cash, field="initial_cash")
        if cash < 0:
            raise ValueError("initial_cash must be non-negative")
        self._pipeline = pipeline
        self._engine = engine
        self._state_store = state_store
        self._decision_provider = decision_provider
        self._quote_provider = quote_provider
        self._calendar = calendar
        self._clock = clock
        self._portfolio = portfolio
        self._symbol = symbol.strip().upper()
        self._start_date = start
        self._end_date = end
        self._run_id = run_id
        self._initial_cash = cash
        self._approval_handler = approval_handler

    def run(self) -> BacktestResult:
        portfolio, cursor = self._state_store.load(
            initial_cash=self._initial_cash,
            target=self._portfolio,
        )
        start = self._start_date
        if cursor is not None:
            self._validate_cursor(cursor)
            if cursor.last_completed_date is not None:
                start = cursor.last_completed_date + timedelta(days=1)

        days_processed = 0
        days_skipped = 0
        executions = 0
        rejections = 0
        pending_approvals = 0
        no_actions = 0

        for day in self._calendar.trading_days(start, self._end_date):
            days_processed += 1
            self._clock.set_date(day)
            quote = self._quote_provider.quote_for(
                self._symbol,
                day,
                self._clock,
            )
            if quote is None:
                days_skipped += 1
                self._save_cursor(day)
                continue

            self._portfolio.mark({self._symbol: quote.price})
            simulation_day = SimulationDay(
                run_id=self._run_id,
                symbol=self._symbol,
                date=day,
                clock=self._clock,
                portfolio=self._portfolio,
                portfolio_context=self._portfolio.to_context(),
            )
            decision = self._decision_provider.decision_for(simulation_day)
            result = self._pipeline.process(
                _pipeline_state(decision, self._symbol, day),
                quote,
                run_id=self._run_id,
                symbol=self._symbol,
            )

            if result.evaluation.status is DecisionStatus.APPROVED:
                if result.execution is not None:
                    executions += 1
            elif result.evaluation.status is DecisionStatus.PENDING_APPROVAL:
                if self._approval_handler is None:
                    pending_approvals += 1
                else:
                    approval = self._approval_handler(result.evaluation)
                    updated = self._engine.apply_approval(
                        result.evaluation,
                        approval,
                    )
                    if updated.status is DecisionStatus.APPROVED:
                        self._engine.execute(updated)
                        executions += 1
                    else:
                        rejections += 1
            elif result.evaluation.status is DecisionStatus.REJECTED:
                rejections += 1
            elif result.evaluation.status is DecisionStatus.NO_ACTION:
                no_actions += 1

            self._save_cursor(day)

        snapshot = portfolio.snapshot()
        return BacktestResult(
            run_id=self._run_id,
            symbol=self._symbol,
            start_date=self._start_date,
            end_date=self._end_date,
            days_processed=days_processed,
            days_skipped=days_skipped,
            executions=executions,
            rejections=rejections,
            pending_approvals=pending_approvals,
            no_actions=no_actions,
            final_equity=snapshot.total_equity,
            bankrupt=portfolio.bankrupt,
        )

    def _validate_cursor(self, cursor: BacktestCursor) -> None:
        matches = (
            cursor.run_id == self._run_id
            and cursor.symbol == self._symbol
            and cursor.start_date == self._start_date
            and cursor.end_date == self._end_date
        )
        if not matches:
            raise BacktestStateError(
                "persisted backtest cursor does not match this run"
            )

    def _save_cursor(self, day: date) -> None:
        self._state_store.save(
            self._portfolio,
            cursor=BacktestCursor(
                run_id=self._run_id,
                symbol=self._symbol,
                start_date=self._start_date,
                end_date=self._end_date,
                last_completed_date=day,
            ),
        )
