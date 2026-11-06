"""Deterministic simulated order executor."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime

from trading.audit import AuditLog
from trading.clock import SystemClock
from trading.models import (
    DecisionAction,
    DuplicateFillError,
    EventType,
    ExecutionAuditError,
    ExecutionAuthorization,
    ExecutionNotAuthorizedError,
    ExecutionResult,
    IllegalExecutionStateError,
    OrderIntent,
    OrderType,
    PortfolioError,
    PortfolioSnapshot,
    Side,
    StaleEvaluationError,
    TradeDecision,
    UnsupportedOrderTypeError,
    quantize_money,
    quantize_quantity,
    to_decimal,
)
from trading.portfolio import Portfolio

EXECUTABLE_ACTIONS = frozenset({DecisionAction.BUY, DecisionAction.SELL})


def _utc_now() -> datetime:
    return SystemClock().now()


def _uuid_hex() -> str:
    return uuid.uuid4().hex


def _normalise_symbol(symbol: str) -> str:
    return symbol.strip().upper()


def _snapshot_payload(snapshot: PortfolioSnapshot) -> dict:
    return {
        "cash": str(snapshot.cash),
        "positions": [
            {
                "symbol": position.symbol,
                "quantity": str(position.quantity),
                "average_cost": (
                    str(position.average_cost)
                    if position.average_cost is not None
                    else None
                ),
                "realized_pnl": str(position.realized_pnl),
                "market_price": (
                    str(position.market_price)
                    if position.market_price is not None
                    else None
                ),
                "market_value": (
                    str(position.market_value)
                    if position.market_value is not None
                    else None
                ),
                "unrealized_pnl": (
                    str(position.unrealized_pnl)
                    if position.unrealized_pnl is not None
                    else None
                ),
            }
            for position in snapshot.positions
        ],
        "realized_pnl": str(snapshot.realized_pnl),
        "unrealized_pnl": str(snapshot.unrealized_pnl),
        "total_fees": str(snapshot.total_fees),
        "total_equity": str(snapshot.total_equity),
        "bankrupt": snapshot.bankrupt,
        "version": snapshot.version,
        "as_of": snapshot.as_of.isoformat(),
        "valuation_incomplete": snapshot.valuation_incomplete,
    }


class SimulatedExecutor:
    """Apply pre-approved simulated fills and write execution audit events."""

    def __init__(
        self,
        portfolio: Portfolio,
        audit: AuditLog,
        *,
        authorization_token: object,
        clock: Callable[[], datetime] = _utc_now,
        id_factory: Callable[[], str] = _uuid_hex,
    ) -> None:
        if not isinstance(portfolio, Portfolio):
            raise PortfolioError("portfolio must be a Portfolio")
        if authorization_token is None:
            raise ValueError("authorization_token is required")
        self._portfolio = portfolio
        self._audit = audit
        self._authorization_token = authorization_token
        self._clock = clock
        self._id_factory = id_factory
        self._execution_count = 0

    @property
    def execution_count(self) -> int:
        return self._execution_count

    def execute(self, authorization: ExecutionAuthorization) -> ExecutionResult:
        if (
            getattr(authorization, "provenance_token", None)
            is not self._authorization_token
        ):
            raise ExecutionNotAuthorizedError(
                "authorization was not issued by the SafetyEngine"
            )
        self._validate_authorization(authorization)
        portfolio = self._portfolio

        if portfolio.bankrupt:
            raise PortfolioError("portfolio is BANKRUPT")
        if authorization.portfolio_version != portfolio.version:
            raise StaleEvaluationError(
                "portfolio changed after the evaluation was produced"
            )

        decision = authorization.decision
        order = authorization.order_intent
        order_id = self._validate_order_envelope(decision, order)

        if portfolio.has_applied(order_id):
            raise DuplicateFillError(f"order {order_id} was already applied")

        execution_id = self._next_execution_id()
        executed_at = self._current_time()
        pre_snapshot = portfolio.snapshot()
        started_payload = self._execution_payload(
            authorization,
            order,
            order_id,
            pre_snapshot,
            execution_id,
            executed_at,
        )

        try:
            self._audit.append(
                run_id=decision.run_id,
                event_type=EventType.EXECUTION_STARTED,
                payload=started_payload,
            )
        except Exception as exc:
            raise ExecutionAuditError(
                "EXECUTION_STARTED could not be written; portfolio unchanged"
            ) from exc

        snapshot = portfolio.apply_fill(order, order_id=order_id)
        self._execution_count += 1

        executed_payload = self._execution_payload(
            authorization,
            order,
            order_id,
            snapshot,
            execution_id,
            executed_at,
        )
        try:
            self._audit.append(
                run_id=decision.run_id,
                event_type=EventType.ORDER_EXECUTED,
                payload=executed_payload,
            )
        except Exception as exc:
            self._record_invariant_violation(
                authorization,
                order,
                order_id,
                execution_id,
                exc,
            )
            raise ExecutionAuditError(
                "ORDER_EXECUTED could not be written after the portfolio was mutated"
            ) from exc

        return ExecutionResult(
            execution_id=execution_id,
            order_id=order_id,
            decision_id=decision.decision_id,
            order=order,
            snapshot=snapshot,
            executed_at=executed_at,
        )

    @staticmethod
    def _validate_authorization(authorization: ExecutionAuthorization) -> None:
        if not isinstance(authorization, ExecutionAuthorization):
            raise ExecutionNotAuthorizedError(
                "execution requires an ExecutionAuthorization"
            )
        if (
            not isinstance(authorization.evaluation_id, str)
            or not authorization.evaluation_id.strip()
        ):
            raise ExecutionNotAuthorizedError("evaluation_id must be non-empty")
        if not isinstance(authorization.decision, TradeDecision):
            raise ExecutionNotAuthorizedError("authorization is missing a decision")
        if not isinstance(authorization.order_intent, OrderIntent):
            raise ExecutionNotAuthorizedError(
                "authorization is missing an order intent"
            )
        if (
            not isinstance(authorization.portfolio_version, int)
            or isinstance(authorization.portfolio_version, bool)
            or authorization.portfolio_version < 0
        ):
            raise ExecutionNotAuthorizedError("portfolio_version is invalid")

    @staticmethod
    def _validate_order_envelope(
        decision: TradeDecision,
        order: OrderIntent,
    ) -> str:
        if decision.action not in EXECUTABLE_ACTIONS:
            raise IllegalExecutionStateError("decision action is not executable")
        if decision.order_type is not OrderType.MARKET:
            raise UnsupportedOrderTypeError("only market orders are supported")
        if (
            not isinstance(decision.run_id, str)
            or not decision.run_id.strip()
            or not isinstance(decision.decision_id, str)
            or not decision.decision_id.strip()
            or not isinstance(decision.symbol, str)
            or not decision.symbol.strip()
        ):
            raise IllegalExecutionStateError("decision identity is incomplete")
        if decision.quantity is None:
            raise IllegalExecutionStateError("decision quantity is required")
        quantity = to_decimal(decision.quantity, field="quantity")
        if quantity <= 0:
            raise IllegalExecutionStateError("quantity must be positive")
        if quantize_quantity(quantity) != quantity:
            raise IllegalExecutionStateError(
                "quantity has more than 6 decimal places"
            )
        if order.decision_id != decision.decision_id:
            raise IllegalExecutionStateError(
                "order intent decision id does not match the decision"
            )
        if _normalise_symbol(order.symbol) != _normalise_symbol(decision.symbol):
            raise IllegalExecutionStateError(
                "order intent symbol does not match the decision"
            )
        expected_side = (
            Side.BUY if decision.action is DecisionAction.BUY else Side.SELL
        )
        if order.side is not expected_side:
            raise IllegalExecutionStateError(
                "order intent side does not match the decision"
            )
        if order.quantity != quantity:
            raise IllegalExecutionStateError(
                "order intent quantity does not match the decision"
            )
        price = to_decimal(order.price, field="price")
        if price <= 0:
            raise IllegalExecutionStateError("fill price must be positive")
        notional = quantize_money(quantity * price)
        if notional <= 0:
            raise IllegalExecutionStateError(
                "order notional is zero after money rounding"
            )
        if order.notional != notional:
            raise IllegalExecutionStateError(
                "order notional does not match quantity and price"
            )
        fee = to_decimal(order.fee, field="fee")
        if fee < 0:
            raise IllegalExecutionStateError("order fee must be non-negative")
        return f"ord-{decision.decision_id}"

    def _next_execution_id(self) -> str:
        execution_id = str(self._id_factory())
        if not execution_id.strip():
            raise IllegalExecutionStateError("execution id must be non-empty")
        return execution_id

    def _current_time(self) -> datetime:
        executed_at = self._clock()
        if not isinstance(executed_at, datetime):
            raise IllegalExecutionStateError("clock must return a datetime")
        if executed_at.tzinfo is None or executed_at.utcoffset() is None:
            raise IllegalExecutionStateError("clock must return a timezone-aware datetime")
        return executed_at

    @staticmethod
    def _execution_payload(
        authorization: ExecutionAuthorization,
        order: OrderIntent,
        order_id: str,
        snapshot: PortfolioSnapshot,
        execution_id: str,
        executed_at: datetime,
    ) -> dict:
        decision = authorization.decision
        return {
            "run_id": decision.run_id,
            "evaluation_id": authorization.evaluation_id,
            "execution_id": execution_id,
            "decision_id": decision.decision_id,
            "order_id": order_id,
            "symbol": _normalise_symbol(decision.symbol),
            "side": order.side.value,
            "quantity": str(order.quantity),
            "fill_price": str(order.price),
            "fee": str(order.fee),
            "executed_at": executed_at.isoformat(),
            "snapshot": _snapshot_payload(snapshot),
        }

    def _record_invariant_violation(
        self,
        authorization: ExecutionAuthorization,
        order: OrderIntent,
        order_id: str,
        execution_id: str,
        error: Exception,
    ) -> None:
        decision = authorization.decision
        try:
            snapshot = self._portfolio.snapshot()
            payload = self._execution_payload(
                authorization,
                order,
                order_id,
                snapshot,
                execution_id,
                self._current_time(),
            )
            payload["reason"] = "ORDER_EXECUTED audit failed after portfolio mutation"
            payload["error_type"] = type(error).__name__
            self._audit.append(
                run_id=decision.run_id,
                event_type=EventType.INVARIANT_VIOLATION,
                payload=payload,
            )
        except Exception:
            return
