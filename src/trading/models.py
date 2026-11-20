"""Shared data models for the simulated trading subsystem."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation
from enum import Enum
from typing import Any

MONEY_QUANTUM = Decimal("0.01")
QUANTITY_QUANTUM = Decimal("0.000001")


class TradingError(Exception):
    """Base class for subsystem errors."""


class DecisionValidationError(TradingError, ValueError):
    """A decision or market value has an invalid shape."""


class ConfigValidationError(TradingError, ValueError):
    """A safety or runtime configuration value is invalid."""


class PortfolioError(TradingError, ValueError):
    """Base class for portfolio ledger errors."""


class InsufficientCashError(PortfolioError):
    """A BUY would spend more cash than is available."""


class InsufficientPositionError(PortfolioError):
    """A SELL would dispose of more units than are held."""


class DuplicateFillError(PortfolioError):
    """An order id has already been applied to the portfolio."""


class PersistenceError(TradingError, RuntimeError):
    """Portfolio or backtest state could not be loaded or saved."""


class AuditIntegrityError(TradingError, RuntimeError):
    """The audit log hash chain or contents are not intact."""


class ExecutionNotAuthorizedError(TradingError, PermissionError):
    """Execution was attempted without a valid engine authorization."""


class IllegalExecutionStateError(TradingError, RuntimeError):
    """An evaluation is not in a state that may be executed."""


class StaleEvaluationError(TradingError, RuntimeError):
    """The portfolio changed between evaluation and execution."""


class ApprovalRequiredError(TradingError, PermissionError):
    """An approval-gated evaluation was executed without approval."""


class ApprovalDeniedError(TradingError, PermissionError):
    """A human denied the approval request."""


class ApprovalExpiredError(TradingError, PermissionError):
    """An approval request or decision has expired."""


class ApprovalMismatchError(TradingError, ValueError):
    """An approval does not belong to the evaluation being applied."""


class ExecutionAuditError(TradingError, RuntimeError):
    """Execution auditing failed."""


class BacktestStateError(TradingError, RuntimeError):
    """Backtest progress cannot be resumed against the loaded state."""


class SimulationError(TradingError, RuntimeError):
    """The simulation could not advance deterministically."""


class UnsupportedOrderTypeError(TradingError, NotImplementedError):
    """The requested order type is not implemented in the simulator."""


class DecisionAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    REVIEW = "REVIEW"


class DecisionStatus(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    NO_ACTION = "NO_ACTION"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class EventType(str, Enum):
    DECISION_RECEIVED = "DECISION_RECEIVED"
    RULE_EVALUATED = "RULE_EVALUATED"
    APPROVAL_POLICY_EVALUATED = "APPROVAL_POLICY_EVALUATED"
    DECISION_EVALUATED = "DECISION_EVALUATED"
    HUMAN_APPROVAL_REQUESTED = "HUMAN_APPROVAL_REQUESTED"
    HUMAN_APPROVAL = "HUMAN_APPROVAL"
    DECISION_APPROVED = "DECISION_APPROVED"
    DECISION_REJECTED = "DECISION_REJECTED"
    EXECUTION_STARTED = "EXECUTION_STARTED"
    ORDER_EXECUTED = "ORDER_EXECUTED"
    INVARIANT_VIOLATION = "INVARIANT_VIOLATION"
    BANKRUPT = "BANKRUPT"
    STATE_LOADED = "STATE_LOADED"
    STATE_SAVED = "STATE_SAVED"
    STATE_RESET = "STATE_RESET"
    BACKTEST_STARTED = "BACKTEST_STARTED"
    BACKTEST_DAY_STARTED = "BACKTEST_DAY_STARTED"
    BACKTEST_DAY_COMPLETED = "BACKTEST_DAY_COMPLETED"
    BACKTEST_COMPLETED = "BACKTEST_COMPLETED"


def to_decimal(
    value: Any,
    *,
    field: str = "value",
    error_type: type[Exception] = DecisionValidationError,
) -> Decimal:
    """Return a finite Decimal without accepting binary floating-point input."""
    if isinstance(value, bool):
        raise error_type(f"{field} must be a decimal-compatible value, got bool")
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise error_type(f"{field} must not be blank")
        try:
            number = Decimal(text)
        except InvalidOperation as exc:
            raise error_type(f"{field} is not a valid decimal: {value!r}") from exc
    else:
        raise error_type(
            f"{field} must be Decimal, int, or str; floats are not accepted: {value!r}"
        )
    if not number.is_finite():
        raise error_type(f"{field} must be finite, got {value!r}")
    return number


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def quantize_quantity(value: Decimal) -> Decimal:
    return value.quantize(QUANTITY_QUANTUM, rounding=ROUND_DOWN)


@dataclass(frozen=True)
class FeeModel:
    fee_bps: Decimal = Decimal("5")
    min_fee: Decimal = Decimal("0.00")

    def __post_init__(self) -> None:
        fee_bps = to_decimal(self.fee_bps, field="fee_bps", error_type=ConfigValidationError)
        min_fee = to_decimal(self.min_fee, field="min_fee", error_type=ConfigValidationError)
        if fee_bps < 0:
            raise ConfigValidationError("fee_bps must be non-negative")
        if min_fee < 0:
            raise ConfigValidationError("min_fee must be non-negative")
        object.__setattr__(self, "fee_bps", fee_bps)
        object.__setattr__(self, "min_fee", min_fee)

    def fee_for(self, notional: Decimal) -> Decimal:
        value = to_decimal(notional, field="notional")
        if value < 0:
            raise DecisionValidationError("notional must be non-negative")
        proportional = value * self.fee_bps / Decimal("10000")
        return quantize_money(max(proportional, self.min_fee))


@dataclass(frozen=True)
class SafetyConfig:
    allowed_symbols: frozenset[str] | None = None
    hard_max_order_notional: Decimal = Decimal("10000.00")
    soft_max_order_notional: Decimal = Decimal("2500.00")
    max_position_fraction: Decimal = Decimal("0.20")
    max_quote_age_seconds: int = 300
    allow_short: bool = False
    fee_bps: Decimal = Decimal("5")
    min_fee: Decimal = Decimal("0.00")
    approval_ttl_seconds: int = 900
    bankrupt_rejection_reason: str = "BANKRUPT"

    def __post_init__(self) -> None:
        hard_max = to_decimal(
            self.hard_max_order_notional,
            field="hard_max_order_notional",
            error_type=ConfigValidationError,
        )
        soft_max = to_decimal(
            self.soft_max_order_notional,
            field="soft_max_order_notional",
            error_type=ConfigValidationError,
        )
        fraction = to_decimal(
            self.max_position_fraction,
            field="max_position_fraction",
            error_type=ConfigValidationError,
        )
        fee_bps = to_decimal(
            self.fee_bps, field="fee_bps", error_type=ConfigValidationError
        )
        min_fee = to_decimal(
            self.min_fee, field="min_fee", error_type=ConfigValidationError
        )
        if hard_max < 0:
            raise ConfigValidationError("hard_max_order_notional must be non-negative")
        if soft_max < 0:
            raise ConfigValidationError("soft_max_order_notional must be non-negative")
        if soft_max > hard_max:
            raise ConfigValidationError(
                "soft_max_order_notional must not exceed hard_max_order_notional"
            )
        if not Decimal("0") < fraction <= Decimal("1"):
            raise ConfigValidationError("max_position_fraction must be in (0, 1]")
        if self.max_quote_age_seconds <= 0:
            raise ConfigValidationError("max_quote_age_seconds must be positive")
        if self.approval_ttl_seconds <= 0:
            raise ConfigValidationError("approval_ttl_seconds must be positive")
        if fee_bps < 0:
            raise ConfigValidationError("fee_bps must be non-negative")
        if min_fee < 0:
            raise ConfigValidationError("min_fee must be non-negative")
        if not self.bankrupt_rejection_reason.strip():
            raise ConfigValidationError("bankrupt_rejection_reason must not be blank")

        allowed = self.allowed_symbols
        if allowed is not None:
            normalized = frozenset(
                symbol.strip().upper() for symbol in allowed if symbol.strip()
            )
            object.__setattr__(self, "allowed_symbols", normalized)

        object.__setattr__(self, "hard_max_order_notional", hard_max)
        object.__setattr__(self, "soft_max_order_notional", soft_max)
        object.__setattr__(self, "max_position_fraction", fraction)
        object.__setattr__(self, "fee_bps", fee_bps)
        object.__setattr__(self, "min_fee", min_fee)

    def fee_model(self) -> FeeModel:
        return FeeModel(fee_bps=self.fee_bps, min_fee=self.min_fee)


@dataclass(frozen=True)
class TradeDecision:
    run_id: str
    decision_id: str
    symbol: str
    action: DecisionAction
    quantity: Decimal | None = None
    order_type: OrderType = OrderType.MARKET
    limit_price: Decimal | None = None
    rationale: str = ""
    source: str = "llm"

    def __post_init__(self) -> None:
        if not isinstance(self.action, DecisionAction):
            try:
                object.__setattr__(self, "action", DecisionAction(self.action))
            except ValueError as exc:
                raise DecisionValidationError(f"unknown action: {self.action!r}") from exc
        if not isinstance(self.order_type, OrderType):
            try:
                object.__setattr__(self, "order_type", OrderType(self.order_type))
            except ValueError as exc:
                raise DecisionValidationError(
                    f"unknown order type: {self.order_type!r}"
                ) from exc
        if self.quantity is not None:
            object.__setattr__(
                self,
                "quantity",
                to_decimal(self.quantity, field="quantity"),
            )
        if self.limit_price is not None:
            object.__setattr__(
                self,
                "limit_price",
                to_decimal(self.limit_price, field="limit_price"),
            )


@dataclass(frozen=True)
class MarketQuote:
    symbol: str
    price: Decimal
    as_of: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "price", to_decimal(self.price, field="price"))
        if not isinstance(self.as_of, datetime):
            raise DecisionValidationError("as_of must be a datetime")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise DecisionValidationError("as_of must be timezone-aware")


@dataclass(frozen=True)
class OrderIntent:
    decision_id: str
    symbol: str
    side: Side
    quantity: Decimal
    price: Decimal
    notional: Decimal
    fee: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.side, Side):
            try:
                object.__setattr__(self, "side", Side(self.side))
            except ValueError as exc:
                raise DecisionValidationError(f"unknown side: {self.side!r}") from exc
        for field in ("quantity", "price", "notional", "fee"):
            object.__setattr__(
                self,
                field,
                to_decimal(getattr(self, field), field=field),
            )


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    passed: bool
    reason: str = ""


@dataclass(frozen=True)
class ApprovalCheck:
    policy_id: str
    triggered: bool
    reason: str = ""


@dataclass(frozen=True)
class EvaluationResult:
    evaluation_id: str
    decision: TradeDecision
    order_intent: OrderIntent | None
    status: DecisionStatus
    rule_results: tuple[RuleResult, ...]
    approval_checks: tuple[ApprovalCheck, ...]
    reasons: tuple[str, ...]
    portfolio_version: int
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_results", tuple(self.rule_results))
        object.__setattr__(self, "approval_checks", tuple(self.approval_checks))
        object.__setattr__(self, "reasons", tuple(self.reasons))


@dataclass(frozen=True)
class ApprovalRequest:
    request_id: str
    decision_id: str
    evaluation_id: str
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class HumanApproval:
    request_id: str
    decision_id: str
    approved: bool
    approver: str
    reason: str
    decided_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: Decimal
    average_cost: Decimal | None = None
    realized_pnl: Decimal = Decimal("0.00")
    market_price: Decimal | None = None
    market_value: Decimal | None = None
    unrealized_pnl: Decimal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "quantity", to_decimal(self.quantity, field="quantity"))
        for field in ("average_cost", "realized_pnl", "market_price"):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, to_decimal(value, field=field))
        for field in ("market_value", "unrealized_pnl"):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, quantize_money(to_decimal(value, field=field)))


@dataclass(frozen=True)
class PortfolioSnapshot:
    cash: Decimal
    positions: tuple[Position, ...]
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_fees: Decimal
    total_equity: Decimal
    bankrupt: bool
    version: int
    as_of: datetime
    valuation_incomplete: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "positions", tuple(self.positions))
        for field in (
            "cash",
            "realized_pnl",
            "unrealized_pnl",
            "total_fees",
            "total_equity",
        ):
            object.__setattr__(
                self,
                field,
                quantize_money(to_decimal(getattr(self, field), field=field)),
            )
        if not isinstance(self.as_of, datetime):
            raise DecisionValidationError("as_of must be a datetime")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise DecisionValidationError("as_of must be timezone-aware")


@dataclass(frozen=True)
class ExecutionResult:
    execution_id: str
    order_id: str
    decision_id: str
    order: OrderIntent
    snapshot: PortfolioSnapshot
    executed_at: datetime


@dataclass(frozen=True)
class ExecutionAuthorization:
    evaluation_id: str
    decision: TradeDecision
    order_intent: OrderIntent
    portfolio_version: int


@dataclass(frozen=True)
class RuleContext:
    decision: TradeDecision
    quote: MarketQuote
    config: SafetyConfig
    portfolio: PortfolioSnapshot
    order_intent: OrderIntent | None
    now: datetime
    is_simulated: bool
    order_id: str | None = None
    applied_order_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "applied_order_ids", frozenset(self.applied_order_ids))


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    run_id: str
    timestamp: datetime
    event_type: EventType
    payload: Mapping[str, Any]
    prev_hash: str = ""
    entry_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.event_type, EventType):
            try:
                object.__setattr__(self, "event_type", EventType(self.event_type))
            except ValueError as exc:
                raise DecisionValidationError(
                    f"unknown event type: {self.event_type!r}"
                ) from exc
        if not isinstance(self.timestamp, datetime):
            raise DecisionValidationError("timestamp must be a datetime")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise DecisionValidationError("timestamp must be timezone-aware")
