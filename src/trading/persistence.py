"""Atomic JSON persistence for portfolio and backtest state."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from trading.audit import AuditLog
from trading.clock import Clock
from trading.models import (
    EventType,
    FeeModel,
    PersistenceError,
    quantize_money,
    quantize_quantity,
    to_decimal,
)
from trading.portfolio import Portfolio, _Holding

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class BacktestCursor:
    run_id: str
    symbol: str
    start_date: date
    end_date: date
    last_completed_date: date | None


def _as_date(value: Any, field: str) -> date:
    if not isinstance(value, str):
        raise PersistenceError(f"{field} must be an ISO date string")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise PersistenceError(f"{field} is not a valid ISO date") from exc


def _as_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise PersistenceError(f"{field} must be boolean")
    return value


def _as_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PersistenceError(f"{field} must be a non-empty string")
    return value


def _decimal(value: Any, field: str) -> Decimal:
    try:
        return to_decimal(value, field=field)
    except Exception as exc:
        raise PersistenceError(f"{field} is not a valid decimal") from exc


def _position_payload(holding: _Holding) -> dict[str, Any]:
    return {
        "symbol": holding.symbol,
        "quantity": str(holding.quantity),
        "average_cost": (
            str(holding.average_cost) if holding.average_cost is not None else None
        ),
        "realized_pnl": str(holding.realized_pnl),
    }


def _cursor_payload(cursor: BacktestCursor | None) -> dict[str, Any] | None:
    if cursor is None:
        return None
    return {
        "run_id": cursor.run_id,
        "symbol": cursor.symbol,
        "start_date": cursor.start_date.isoformat(),
        "end_date": cursor.end_date.isoformat(),
        "last_completed_date": (
            cursor.last_completed_date.isoformat()
            if cursor.last_completed_date is not None
            else None
        ),
    }


class StateStore:
    """Load/save a complete simulated portfolio plus an optional backtest cursor."""

    def __init__(
        self,
        path: str | Path,
        *,
        fee_model: FeeModel,
        clock: Clock,
        audit: AuditLog,
        initial_cash: Decimal | None = None,
    ) -> None:
        self._path = Path(path)
        self._fee_model = fee_model
        self._clock = clock
        self._audit = audit
        self._initial_cash = (
            quantize_money(to_decimal(initial_cash, field="initial_cash"))
            if initial_cash is not None
            else None
        )

    @property
    def path(self) -> Path:
        return self._path

    def load(
        self,
        *,
        initial_cash: Decimal | None = None,
        target: Portfolio | None = None,
    ) -> tuple[Portfolio, BacktestCursor | None]:
        resolved_cash = self._resolve_initial_cash(initial_cash)
        if not self._path.exists():
            portfolio = target or Portfolio(
                resolved_cash,
                fee_model=self._fee_model,
                clock=self._clock.now,
            )
            self._apply_fresh(portfolio, resolved_cash)
            return portfolio, None

        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise PersistenceError(f"state file {self._path} is not readable JSON") from exc
        if not isinstance(data, dict):
            raise PersistenceError("state file must contain a JSON object")
        if data.get("schema_version") != SCHEMA_VERSION:
            raise PersistenceError("state file has an unsupported schema version")

        cash = quantize_money(_decimal(data.get("cash"), "cash"))
        total_fees = quantize_money(_decimal(data.get("total_fees"), "total_fees"))
        if total_fees < 0:
            raise PersistenceError("total_fees must be non-negative")

        positions_data = data.get("positions")
        if not isinstance(positions_data, list):
            raise PersistenceError("positions must be a list")
        holdings: dict[str, _Holding] = {}
        realized_total = Decimal("0.00")
        for index, item in enumerate(positions_data):
            if not isinstance(item, dict):
                raise PersistenceError(f"positions[{index}] must be an object")
            symbol = _as_str(item.get("symbol"), f"positions[{index}].symbol").strip().upper()
            if symbol in holdings:
                raise PersistenceError(f"duplicate position for {symbol}")
            quantity = _decimal(item.get("quantity"), f"positions[{index}].quantity")
            if quantize_quantity(quantity) != quantity:
                raise PersistenceError(f"positions[{index}].quantity has too many decimals")
            average_cost = item.get("average_cost")
            if average_cost is not None:
                average_cost = _decimal(
                    average_cost,
                    f"positions[{index}].average_cost",
                )
                if average_cost <= 0:
                    raise PersistenceError(
                        f"positions[{index}].average_cost must be positive"
                    )
            realized = quantize_money(
                _decimal(item.get("realized_pnl"), f"positions[{index}].realized_pnl")
            )
            holdings[symbol] = _Holding(
                symbol=symbol,
                quantity=quantity,
                average_cost=average_cost,
                realized_pnl=realized,
            )
            realized_total += realized

        saved_realized = quantize_money(
            _decimal(data.get("realized_pnl"), "realized_pnl")
        )
        if quantize_money(realized_total) != saved_realized:
            raise PersistenceError("position realized PnL does not match the saved total")

        last_prices_data = data.get("last_prices")
        if not isinstance(last_prices_data, dict):
            raise PersistenceError("last_prices must be an object")
        last_prices: dict[str, Decimal] = {}
        for symbol, value in last_prices_data.items():
            key = _as_str(symbol, "last_prices symbol").strip().upper()
            price = _decimal(value, f"last_prices[{key}]")
            if price < 0:
                raise PersistenceError(f"last_prices[{key}] must be non-negative")
            last_prices[key] = price

        applied_data = data.get("applied_order_ids")
        if not isinstance(applied_data, list):
            raise PersistenceError("applied_order_ids must be a list")
        applied_ids = set()
        for value in applied_data:
            applied_ids.add(_as_str(value, "applied_order_ids item"))
        if len(applied_ids) != len(applied_data):
            raise PersistenceError("applied_order_ids contains duplicates")

        bankrupt = _as_bool(data.get("bankrupt"), "bankrupt")
        version = data.get("version")
        if not isinstance(version, int) or isinstance(version, bool) or version < 0:
            raise PersistenceError("version must be a non-negative integer")
        bankruptcy_reason = data.get("bankruptcy_reason")
        if bankruptcy_reason is not None:
            bankruptcy_reason = _as_str(bankruptcy_reason, "bankruptcy_reason")

        cursor = self._parse_cursor(data.get("backtest"))

        portfolio = target or Portfolio(
            resolved_cash,
            fee_model=self._fee_model,
            clock=self._clock.now,
        )
        portfolio._cash = cash
        portfolio._holdings = holdings
        portfolio._last_prices = last_prices
        portfolio._applied_order_ids = applied_ids
        portfolio._total_fees = total_fees
        portfolio._version = version
        portfolio._bankrupt = bankrupt
        portfolio._bankruptcy_reason = bankruptcy_reason
        portfolio._refresh_bankruptcy()
        return portfolio, cursor

    def save(
        self,
        portfolio: Portfolio,
        *,
        cursor: BacktestCursor | None = None,
    ) -> None:
        if self._initial_cash is None:
            raise PersistenceError("initial_cash is required before saving state")
        if not isinstance(portfolio, Portfolio):
            raise PersistenceError("portfolio must be a Portfolio")
        if cursor is not None and not isinstance(cursor, BacktestCursor):
            raise PersistenceError("cursor must be a BacktestCursor or None")

        snapshot = portfolio.snapshot()
        payload = {
            "schema_version": SCHEMA_VERSION,
            "initial_cash": str(self._initial_cash),
            "cash": str(portfolio.cash),
            "positions": [
                _position_payload(holding)
                for holding in sorted(
                    portfolio._holdings.values(),
                    key=lambda item: item.symbol,
                )
            ],
            "realized_pnl": str(snapshot.realized_pnl),
            "total_fees": str(portfolio._total_fees),
            "last_prices": {
                symbol: str(price)
                for symbol, price in sorted(portfolio._last_prices.items())
            },
            "applied_order_ids": sorted(portfolio._applied_order_ids),
            "bankrupt": portfolio.bankrupt,
            "bankruptcy_reason": portfolio.bankruptcy_reason,
            "version": portfolio.version,
            "updated_at": self._clock.now().isoformat(),
            "backtest": _cursor_payload(cursor),
        }
        self._write_atomic(payload)

    def reset(
        self,
        *,
        initial_cash: Decimal | None = None,
        reason: str = "manual",
        target: Portfolio | None = None,
    ) -> Portfolio:
        if not isinstance(reason, str) or not reason.strip():
            raise PersistenceError("reset reason must be non-empty")
        resolved_cash = self._resolve_initial_cash(initial_cash)
        self._initial_cash = resolved_cash
        portfolio = target or Portfolio(
            resolved_cash,
            fee_model=self._fee_model,
            clock=self._clock.now,
        )
        self._apply_fresh(portfolio, resolved_cash)
        self.save(portfolio, cursor=None)
        self._audit.append(
            run_id="state-reset",
            event_type=EventType.STATE_RESET,
            payload={
                "reason": reason.strip(),
                "initial_cash": str(resolved_cash),
                "bankrupt": False,
            },
        )
        return portfolio

    def _resolve_initial_cash(self, initial_cash: Decimal | None) -> Decimal:
        if initial_cash is not None:
            value = quantize_money(to_decimal(initial_cash, field="initial_cash"))
            if value < 0:
                raise PersistenceError("initial_cash must be non-negative")
            self._initial_cash = value
            return value
        if self._initial_cash is None:
            raise PersistenceError("initial_cash is required")
        return self._initial_cash

    @staticmethod
    def _apply_fresh(portfolio: Portfolio, initial_cash: Decimal) -> None:
        portfolio._cash = quantize_money(initial_cash)
        portfolio._holdings = {}
        portfolio._last_prices = {}
        portfolio._applied_order_ids = set()
        portfolio._total_fees = Decimal("0.00")
        portfolio._version = 0
        portfolio._bankrupt = False
        portfolio._bankruptcy_reason = None

    @staticmethod
    def _parse_cursor(data: Any) -> BacktestCursor | None:
        if data is None:
            return None
        if not isinstance(data, dict):
            raise PersistenceError("backtest cursor must be an object or null")
        required = {
            "run_id",
            "symbol",
            "start_date",
            "end_date",
            "last_completed_date",
        }
        if set(data) != required:
            raise PersistenceError("backtest cursor has unexpected fields")
        run_id = _as_str(data.get("run_id"), "backtest.run_id")
        symbol = _as_str(data.get("symbol"), "backtest.symbol").strip().upper()
        start_date = _as_date(data.get("start_date"), "backtest.start_date")
        end_date = _as_date(data.get("end_date"), "backtest.end_date")
        if end_date < start_date:
            raise PersistenceError("backtest cursor ends before it starts")
        last = data.get("last_completed_date")
        last_completed = (
            None if last is None else _as_date(last, "backtest.last_completed_date")
        )
        if last_completed is not None and not start_date <= last_completed <= end_date:
            raise PersistenceError("backtest cursor is outside its date range")
        return BacktestCursor(
            run_id=run_id,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            last_completed_date=last_completed,
        )

    def _write_atomic(self, payload: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
        fd, temporary = tempfile.mkstemp(
            dir=self._path.parent,
            prefix=f".{self._path.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
            directory = os.open(self._path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except BaseException:
            with suppress(FileNotFoundError):
                os.unlink(temporary)
            raise
