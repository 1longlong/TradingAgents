"""Simulated portfolio ledger: cash, positions, cost basis, and PnL."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType

from trading.clock import SystemClock
from trading.models import (
    DuplicateFillError,
    FeeModel,
    InsufficientCashError,
    InsufficientPositionError,
    OrderIntent,
    PortfolioError,
    PortfolioSnapshot,
    Position,
    Side,
    quantize_money,
    quantize_quantity,
    to_decimal,
)

AVERAGE_COST_QUANTUM = Decimal("0.000001")


def _utc_now() -> datetime:
    return SystemClock().now()


def _normalise_symbol(symbol: str) -> str:
    if not isinstance(symbol, str) or not symbol.strip():
        raise PortfolioError("symbol must be a non-empty string")
    return symbol.strip().upper()


def _quantize_average(value: Decimal) -> Decimal:
    return value.quantize(AVERAGE_COST_QUANTUM, rounding=ROUND_HALF_UP)


def _from_external(value, *, field: str) -> Decimal:
    """Convert the read-only PortfolioContext's float fields at the boundary."""
    if isinstance(value, float):
        value = str(value)
    return to_decimal(value, field=field)


@dataclass
class _Holding:
    symbol: str
    quantity: Decimal
    average_cost: Decimal | None
    realized_pnl: Decimal


class Portfolio:
    """A long-only simulated book with deterministic Decimal accounting."""

    def __init__(
        self,
        initial_cash: Decimal,
        *,
        fee_model: FeeModel,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        cash = quantize_money(to_decimal(initial_cash, field="initial_cash"))
        if cash < 0:
            raise PortfolioError("initial_cash must be non-negative")
        if not isinstance(fee_model, FeeModel):
            raise PortfolioError("fee_model must be a FeeModel")
        self._cash = cash
        self._fee_model = fee_model
        self._clock = clock
        self._holdings: dict[str, _Holding] = {}
        self._last_prices: dict[str, Decimal] = {}
        self._applied_order_ids: set[str] = set()
        self._total_fees = Decimal("0.00")
        self._version = 0
        self._bankrupt = False
        self._bankruptcy_reason: str | None = None

    @classmethod
    def from_context(
        cls,
        context,
        *,
        fee_model: FeeModel,
        clock: Callable[[], datetime] = _utc_now,
    ) -> Portfolio:
        if context.cash is None:
            raise PortfolioError("portfolio context must include cash")
        portfolio = cls(
            _from_external(context.cash, field="cash"),
            fee_model=fee_model,
            clock=clock,
        )
        seen: set[str] = set()
        for item in context.positions:
            symbol = _normalise_symbol(item.ticker)
            if symbol in seen:
                raise PortfolioError(f"duplicate position for {symbol}")
            seen.add(symbol)
            quantity = _from_external(item.quantity, field="quantity")
            if quantity < 0:
                raise PortfolioError("short positions are not supported")
            if quantity == 0:
                continue
            average_cost = None
            if item.average_price is not None:
                average_cost = _from_external(
                    item.average_price, field="average_price"
                )
                if average_cost <= 0:
                    raise PortfolioError("average_price must be positive")
                average_cost = _quantize_average(average_cost)
            portfolio._holdings[symbol] = _Holding(
                symbol=symbol,
                quantity=quantize_quantity(quantity),
                average_cost=average_cost,
                realized_pnl=Decimal("0.00"),
            )
        portfolio._refresh_bankruptcy()
        return portfolio

    @property
    def cash(self) -> Decimal:
        return self._cash

    @property
    def version(self) -> int:
        return self._version

    @property
    def bankrupt(self) -> bool:
        return self._bankrupt

    @property
    def bankruptcy_reason(self) -> str | None:
        return self._bankruptcy_reason

    @property
    def applied_order_ids(self) -> frozenset[str]:
        return frozenset(self._applied_order_ids)

    @property
    def last_prices(self) -> Mapping[str, Decimal]:
        return MappingProxyType(dict(self._last_prices))

    def position(self, symbol: str) -> Position | None:
        if not isinstance(symbol, str) or not symbol.strip():
            return None
        holding = self._holdings.get(symbol.strip().upper())
        if holding is None or holding.quantity == 0:
            return None
        return self._position_snapshot(holding)[0]

    def has_applied(self, order_id: str) -> bool:
        return isinstance(order_id, str) and order_id in self._applied_order_ids

    def snapshot(self) -> PortfolioSnapshot:
        positions: list[Position] = []
        unrealized = Decimal("0.00")
        market_value = Decimal("0.00")
        incomplete = False
        for symbol in sorted(self._holdings):
            holding = self._holdings[symbol]
            if holding.quantity == 0:
                continue
            position, position_incomplete = self._position_snapshot(holding)
            positions.append(position)
            incomplete = incomplete or position_incomplete
            unrealized += position.unrealized_pnl or Decimal("0.00")
            market_value += position.market_value or Decimal("0.00")
        realized = quantize_money(
            sum((holding.realized_pnl for holding in self._holdings.values()), Decimal("0.00"))
        )
        equity = quantize_money(self._cash + market_value)
        return PortfolioSnapshot(
            cash=self._cash,
            positions=tuple(positions),
            realized_pnl=realized,
            unrealized_pnl=quantize_money(unrealized),
            total_fees=self._total_fees,
            total_equity=equity,
            bankrupt=self._bankrupt,
            version=self._version,
            as_of=self._clock(),
            valuation_incomplete=incomplete,
        )

    def mark(self, prices: Mapping[str, Decimal]) -> bool:
        if not isinstance(prices, Mapping):
            raise PortfolioError("prices must be a mapping")
        normalised: dict[str, Decimal] = {}
        for symbol, price in prices.items():
            key = _normalise_symbol(symbol)
            value = to_decimal(price, field=f"price[{key}]")
            if value < 0:
                raise PortfolioError(f"price for {key} must be non-negative")
            normalised[key] = value

        changed = False
        for symbol, price in normalised.items():
            if self._last_prices.get(symbol) != price:
                self._last_prices[symbol] = price
                changed = True

        newly_bankrupt = self._refresh_bankruptcy()
        changed = changed or newly_bankrupt
        if changed:
            self._version += 1
        return newly_bankrupt

    def mark_bankrupt(self, *, reason: str) -> None:
        if not isinstance(reason, str) or not reason.strip():
            raise PortfolioError("bankruptcy reason must be non-empty")
        if self._bankrupt:
            return
        self._bankrupt = True
        self._bankruptcy_reason = reason.strip()
        self._version += 1

    def apply_fill(self, order: OrderIntent, *, order_id: str) -> PortfolioSnapshot:
        if not isinstance(order, OrderIntent):
            raise PortfolioError("order must be an OrderIntent")
        if not isinstance(order_id, str) or not order_id.strip():
            raise PortfolioError("order_id must be a non-empty string")
        order_id = order_id.strip()
        if self._bankrupt:
            raise PortfolioError("portfolio is BANKRUPT")
        if self.has_applied(order_id):
            raise DuplicateFillError(f"order {order_id} was already applied")

        symbol = _normalise_symbol(order.symbol)
        quantity = to_decimal(order.quantity, field="quantity")
        price = to_decimal(order.price, field="price")
        if quantity <= 0:
            raise PortfolioError("quantity must be positive")
        if quantize_quantity(quantity) != quantity:
            raise PortfolioError("quantity has more than 6 decimal places")
        if price <= 0:
            raise PortfolioError("price must be positive")

        notional = quantize_money(quantity * price)
        fee = self._fee_model.fee_for(notional)
        if order.notional != notional:
            raise PortfolioError("order notional does not match quantity and price")
        if order.fee != fee:
            raise PortfolioError("order fee does not match the configured fee model")

        holding = self._holdings.get(symbol)
        if holding is None:
            holding = _Holding(
                symbol=symbol,
                quantity=Decimal("0.000000"),
                average_cost=None,
                realized_pnl=Decimal("0.00"),
            )

        if order.side is Side.BUY:
            total_cost = quantize_money(notional + fee)
            if self._cash < total_cost:
                raise InsufficientCashError(
                    f"buy needs {total_cost}, cash is {self._cash}"
                )
            new_quantity = quantize_quantity(holding.quantity + quantity)
            previous_cost = (
                holding.average_cost * holding.quantity
                if holding.average_cost is not None
                else Decimal("0.00")
            )
            new_average = _quantize_average(
                (previous_cost + total_cost) / new_quantity
            )
            new_cash = quantize_money(self._cash - total_cost)
            new_realized = holding.realized_pnl
        else:
            if holding.quantity < quantity:
                raise InsufficientPositionError(
                    f"sell needs {quantity}, holding is {holding.quantity}"
                )
            new_quantity = quantize_quantity(holding.quantity - quantity)
            new_cash = quantize_money(self._cash + notional - fee)
            if holding.average_cost is None:
                raise PortfolioError("cannot sell a position without an average cost")
            cost_basis = quantize_money(holding.average_cost * quantity)
            realized_delta = quantize_money(notional - cost_basis - fee)
            new_realized = quantize_money(holding.realized_pnl + realized_delta)
            new_average = (
                holding.average_cost if new_quantity > 0 else None
            )

        self._holdings[symbol] = _Holding(
            symbol=symbol,
            quantity=new_quantity,
            average_cost=new_average,
            realized_pnl=new_realized,
        )
        self._cash = new_cash
        self._total_fees = quantize_money(self._total_fees + fee)
        self._last_prices[symbol] = price
        self._applied_order_ids.add(order_id)
        self._refresh_bankruptcy()
        self._version += 1
        return self.snapshot()

    def to_context(self):
        from tradingagents.portfolio import PortfolioContext, Position as ContextPosition

        positions = [
            ContextPosition(
                ticker=holding.symbol,
                quantity=float(holding.quantity),
                average_price=(
                    float(holding.average_cost)
                    if holding.average_cost is not None
                    else None
                ),
            )
            for holding in sorted(self._holdings.values(), key=lambda item: item.symbol)
            if holding.quantity != 0
        ]
        return PortfolioContext(cash=float(self._cash), positions=positions)

    def _price_for(self, holding: _Holding) -> tuple[Decimal | None, bool]:
        price = self._last_prices.get(holding.symbol)
        if price is not None:
            return price, holding.average_cost is None
        if holding.average_cost is not None:
            return holding.average_cost, True
        return None, True

    def _position_snapshot(self, holding: _Holding) -> tuple[Position, bool]:
        price, incomplete = self._price_for(holding)
        if price is None:
            return (
                Position(
                    symbol=holding.symbol,
                    quantity=holding.quantity,
                    average_cost=holding.average_cost,
                    realized_pnl=holding.realized_pnl,
                    market_price=None,
                    market_value=None,
                    unrealized_pnl=None,
                ),
                True,
            )
        market_value = quantize_money(holding.quantity * price)
        if holding.average_cost is None:
            unrealized = None
        else:
            unrealized = quantize_money(
                (price - holding.average_cost) * holding.quantity
            )
        return (
            Position(
                symbol=holding.symbol,
                quantity=holding.quantity,
                average_cost=holding.average_cost,
                realized_pnl=holding.realized_pnl,
                market_price=price,
                market_value=market_value,
                unrealized_pnl=unrealized,
            ),
            incomplete,
        )

    def _equity(self) -> Decimal:
        equity = self._cash
        for holding in self._holdings.values():
            if holding.quantity == 0:
                continue
            price, _ = self._price_for(holding)
            if price is not None:
                equity += quantize_money(holding.quantity * price)
        return quantize_money(equity)

    def _refresh_bankruptcy(self) -> bool:
        if self._bankrupt:
            return False
        if self._equity() <= 0:
            self._bankrupt = True
            self._bankruptcy_reason = "equity <= 0"
            return True
        return False
