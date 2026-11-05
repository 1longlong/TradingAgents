"""Graph-output adapter, deterministic sizing, and pipeline orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal

from safety.engine import SafetyEngine
from trading.approval import HumanApprovalGate
from trading.models import (
    ApprovalRequest,
    ConfigValidationError,
    DecisionAction,
    DecisionStatus,
    DecisionValidationError,
    EvaluationResult,
    ExecutionResult,
    MarketQuote,
    OrderType,
    SafetyConfig,
    TradeDecision,
    quantize_money,
    quantize_quantity,
    to_decimal,
)
from trading.portfolio import Portfolio
from tradingagents.agents.utils.rating import extract_rating

_RATING_TO_ACTION = {
    "Buy": DecisionAction.BUY,
    "Overweight": DecisionAction.BUY,
    "Sell": DecisionAction.SELL,
    "Underweight": DecisionAction.SELL,
    "Hold": DecisionAction.HOLD,
}


@dataclass(frozen=True)
class PipelineResult:
    decision: TradeDecision
    evaluation: EvaluationResult
    execution: ExecutionResult | None = None
    approval_request: ApprovalRequest | None = None


def _decision_id(run_id: str, symbol: str, final_state: Mapping) -> str:
    suffix = f":{symbol}"
    trade_date = final_state.get("trade_date")
    if isinstance(trade_date, str) and trade_date.strip():
        suffix = f"{suffix}:{trade_date.strip()}"
    return f"{run_id}{suffix}"


def decision_from_final_state(
    final_state: Mapping,
    run_id: str,
    symbol: str,
) -> TradeDecision:
    """Map a graph result to an advisory direction-only TradeDecision."""
    if not isinstance(final_state, Mapping):
        raise DecisionValidationError("final_state must be a mapping")
    text = final_state.get("final_trade_decision")
    if not isinstance(text, str):
        text = ""
    rating = extract_rating(text)
    action = (
        _RATING_TO_ACTION.get(rating, DecisionAction.REVIEW)
        if rating is not None
        else DecisionAction.REVIEW
    )
    return TradeDecision(
        run_id=run_id,
        decision_id=_decision_id(run_id, symbol, final_state),
        symbol=symbol,
        action=action,
        quantity=None,
        order_type=OrderType.MARKET,
        limit_price=None,
        rationale=f"advisory rating: {rating or 'REVIEW'}",
        source="graph",
    )


@dataclass(frozen=True)
class SizingPolicy:
    target_fraction: Decimal = Decimal("0.05")

    def __post_init__(self) -> None:
        fraction = to_decimal(
            self.target_fraction,
            field="target_fraction",
            error_type=ConfigValidationError,
        )
        if not Decimal("0") < fraction <= Decimal("1"):
            raise ConfigValidationError("target_fraction must be in (0, 1]")
        object.__setattr__(self, "target_fraction", fraction)

    def size(
        self,
        decision: TradeDecision,
        quote: MarketQuote,
        *,
        total_equity: Decimal,
        hard_max_order_notional: Decimal,
    ) -> TradeDecision:
        if decision.action not in (DecisionAction.BUY, DecisionAction.SELL):
            return decision

        equity = to_decimal(total_equity, field="total_equity")
        hard_max = to_decimal(
            hard_max_order_notional,
            field="hard_max_order_notional",
        )
        price = to_decimal(quote.price, field="price")
        if equity <= 0 or hard_max <= 0 or price <= 0:
            return replace(decision, quantity=Decimal("0"))

        target_notional = min(equity * self.target_fraction, hard_max)
        quantity = quantize_quantity(target_notional / price)
        if quantity < 0:
            quantity = Decimal("0")
        if quantity > 0 and quantize_money(quantity * price) > hard_max:
            quantity = quantize_quantity(hard_max / price)
        return replace(decision, quantity=quantity)


class TradingPipeline:
    def __init__(
        self,
        engine: SafetyEngine,
        gate: HumanApprovalGate,
        portfolio: Portfolio,
        config: SafetyConfig,
        *,
        sizing: SizingPolicy | None = None,
    ) -> None:
        self._engine = engine
        self._gate = gate
        self._portfolio = portfolio
        self._config = config
        self._sizing = sizing or SizingPolicy()

    def process(
        self,
        final_state: Mapping,
        quote: MarketQuote,
        *,
        run_id: str,
        symbol: str | None = None,
    ) -> PipelineResult:
        if symbol is None:
            symbol = (
                final_state.get("company_of_interest", "")
                if isinstance(final_state, Mapping)
                else ""
            )
        if not isinstance(symbol, str):
            symbol = str(symbol)

        decision = decision_from_final_state(final_state, run_id, symbol)
        if decision.action in (DecisionAction.BUY, DecisionAction.SELL):
            snapshot = self._portfolio.snapshot()
            decision = self._sizing.size(
                decision,
                quote,
                total_equity=snapshot.total_equity,
                hard_max_order_notional=self._config.hard_max_order_notional,
            )

        evaluation = self._engine.evaluate(decision, quote)
        if evaluation.status is DecisionStatus.PENDING_APPROVAL:
            request = self._gate.request(evaluation)
            return PipelineResult(
                decision=decision,
                evaluation=evaluation,
                approval_request=request,
            )
        if evaluation.status is DecisionStatus.APPROVED:
            execution = self._engine.execute(evaluation)
            return PipelineResult(
                decision=decision,
                evaluation=evaluation,
                execution=execution,
            )
        return PipelineResult(decision=decision, evaluation=evaluation)
