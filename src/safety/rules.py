"""Deterministic safety rules and soft approval policies."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from trading.models import (
    ApprovalCheck,
    DecisionAction,
    OrderType,
    RuleContext,
    RuleResult,
    Side,
    quantize_money,
    quantize_quantity,
    to_decimal,
)

EXECUTABLE_ACTIONS = frozenset({DecisionAction.BUY, DecisionAction.SELL})


def _normalise_symbol(symbol: str) -> str:
    return symbol.strip().upper()


def _position_quantity(ctx: RuleContext, symbol: str) -> Decimal:
    target = _normalise_symbol(symbol)
    for position in ctx.portfolio.positions:
        if position.symbol.strip().upper() == target:
            return position.quantity
    return Decimal("0")


def _check_decision_identity(ctx: RuleContext) -> str | None:
    missing = [
        name
        for name in ("run_id", "decision_id", "symbol")
        if not isinstance(getattr(ctx.decision, name), str)
        or not getattr(ctx.decision, name).strip()
    ]
    if missing:
        return "decision identity is incomplete: " + ", ".join(missing)
    return None


def _check_quantity(ctx: RuleContext) -> str | None:
    if ctx.decision.action not in EXECUTABLE_ACTIONS:
        return None
    if ctx.decision.quantity is None:
        return "quantity is required for an executable decision"
    try:
        quantity = to_decimal(ctx.decision.quantity, field="quantity")
    except Exception:
        return "quantity must be a valid decimal"
    if quantity <= 0:
        return "quantity must be positive"
    if quantize_quantity(quantity) != quantity:
        return "quantity has more than 6 decimal places"
    return None


def _check_quote(ctx: RuleContext) -> str | None:
    quote = ctx.quote
    if quote is None:
        return "quote is required"
    if _normalise_symbol(quote.symbol) != _normalise_symbol(ctx.decision.symbol):
        return "quote symbol does not match the decision"
    if quote.price <= 0:
        return "quote price must be positive"
    if quote.as_of > ctx.now:
        return "quote timestamp is in the future"
    if ctx.is_simulated:
        local_quote_time = quote.as_of
        if ctx.now.tzinfo is not None:
            local_quote_time = quote.as_of.astimezone(ctx.now.tzinfo)
        if local_quote_time.date() != ctx.now.date():
            return "quote date does not match the simulated date"
        return None
    age_seconds = (ctx.now - quote.as_of).total_seconds()
    if age_seconds > ctx.config.max_quote_age_seconds:
        return "quote is older than the allowed age"
    return None


def _check_symbol_allowlist(ctx: RuleContext) -> str | None:
    allowed = ctx.config.allowed_symbols
    if allowed is None:
        return None
    if _normalise_symbol(ctx.decision.symbol) not in allowed:
        return "symbol is not in the allowlist"
    return None


def _check_cash(ctx: RuleContext) -> str | None:
    if ctx.decision.action is not DecisionAction.BUY:
        return None
    intent = ctx.order_intent
    if intent is None:
        return "order intent is required for a BUY"
    required = quantize_money(intent.notional + intent.fee)
    if ctx.portfolio.cash < required:
        return "insufficient cash for BUY"
    return None


def _check_position(ctx: RuleContext) -> str | None:
    if ctx.decision.action is not DecisionAction.SELL:
        return None
    if ctx.config.allow_short:
        return None
    intent = ctx.order_intent
    if intent is None:
        return "order intent is required for a SELL"
    if intent.quantity > _position_quantity(ctx, ctx.decision.symbol):
        return "insufficient position for SELL"
    return None


def _check_hard_notional(ctx: RuleContext) -> str | None:
    if ctx.decision.action not in EXECUTABLE_ACTIONS:
        return None
    intent = ctx.order_intent
    if intent is None:
        return "order intent is required"
    if intent.notional > ctx.config.hard_max_order_notional:
        return "order notional exceeds the hard cap"
    return None


def _check_replay(ctx: RuleContext) -> str | None:
    applied = ctx.applied_order_ids
    decision_id = ctx.decision.decision_id
    order_id = ctx.order_id.strip() if isinstance(ctx.order_id, str) else ""
    if (order_id and order_id in applied) or (decision_id and decision_id in applied):
        return "decision or order was already applied"
    return None


def _check_bankrupt(ctx: RuleContext) -> str | None:
    if ctx.decision.action in EXECUTABLE_ACTIONS and ctx.portfolio.bankrupt:
        return ctx.config.bankrupt_rejection_reason
    return None


def _check_order_intent(ctx: RuleContext) -> str | None:
    if ctx.decision.action not in EXECUTABLE_ACTIONS:
        return "action is not executable"
    intent = ctx.order_intent
    if intent is None:
        return "order intent is required"
    if ctx.decision.order_type is not OrderType.MARKET:
        return "only market orders are supported"
    if not isinstance(ctx.order_id, str) or not ctx.order_id.strip():
        return "order id is required"
    order_id = ctx.order_id.strip()
    applied = ctx.applied_order_ids
    if (
        (order_id and order_id in applied)
        or (ctx.decision.decision_id and ctx.decision.decision_id in applied)
    ):
        return "persisted state indicates the decision or order was already applied"
    if intent.decision_id != ctx.decision.decision_id:
        return "order intent decision id does not match the decision"
    if _normalise_symbol(intent.symbol) != _normalise_symbol(ctx.decision.symbol):
        return "order intent symbol does not match the decision"
    expected_side = (
        Side.BUY if ctx.decision.action is DecisionAction.BUY else Side.SELL
    )
    if intent.side is not expected_side:
        return "order intent side does not match the decision"
    if ctx.decision.quantity is None:
        return "decision quantity is required"
    quantity = to_decimal(ctx.decision.quantity, field="quantity")
    if intent.quantity != quantity:
        return "order intent quantity does not match the decision"
    if intent.price != ctx.quote.price:
        return "order intent price does not match the quote"
    expected_notional = quantize_money(quantity * intent.price)
    if intent.notional != expected_notional:
        return "order intent notional is inconsistent"
    expected_fee = ctx.config.fee_model().fee_for(expected_notional)
    if intent.fee != expected_fee:
        return "order intent fee does not match the configured fee model"
    return None


def _check_soft_notional(ctx: RuleContext) -> str | None:
    if ctx.decision.action not in EXECUTABLE_ACTIONS or ctx.order_intent is None:
        return None
    if ctx.order_intent.notional > ctx.config.soft_max_order_notional:
        return "order notional exceeds the soft approval threshold"
    return None


def _check_concentration(ctx: RuleContext) -> str | None:
    if ctx.decision.action is not DecisionAction.BUY or ctx.order_intent is None:
        return None
    equity = ctx.portfolio.total_equity
    if equity <= 0:
        return None
    held = _position_quantity(ctx, ctx.decision.symbol)
    post_value = quantize_money((held + ctx.order_intent.quantity) * ctx.order_intent.price)
    if post_value > equity * ctx.config.max_position_fraction:
        return "post-trade position exceeds the concentration limit"
    return None


@dataclass(frozen=True)
class SafetyRule:
    rule_id: str
    check: Callable[[RuleContext], str | None]

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        try:
            reason = self.check(ctx)
        except Exception as exc:
            return RuleResult(
                rule_id=self.rule_id,
                passed=False,
                reason=f"rule evaluation failed: {type(exc).__name__}",
            )
        return RuleResult(
            rule_id=self.rule_id,
            passed=reason is None,
            reason=reason or "",
        )


@dataclass(frozen=True)
class ApprovalPolicy:
    policy_id: str
    check: Callable[[RuleContext], str | None]

    def evaluate(self, ctx: RuleContext) -> ApprovalCheck:
        try:
            reason = self.check(ctx)
        except Exception as exc:
            return ApprovalCheck(
                policy_id=self.policy_id,
                triggered=True,
                reason=f"policy evaluation failed: {type(exc).__name__}",
            )
        return ApprovalCheck(
            policy_id=self.policy_id,
            triggered=reason is not None,
            reason=reason or "",
        )


DEFAULT_SAFETY_RULES: tuple[SafetyRule, ...] = (
    SafetyRule("SR-01", _check_decision_identity),
    SafetyRule("SR-02", _check_quantity),
    SafetyRule("SR-03", _check_quote),
    SafetyRule("SR-04", _check_symbol_allowlist),
    SafetyRule("SR-05", _check_cash),
    SafetyRule("SR-06", _check_position),
    SafetyRule("SR-07", _check_hard_notional),
    SafetyRule("SR-08", _check_replay),
    SafetyRule("SR-09", _check_bankrupt),
    SafetyRule("SR-10", _check_order_intent),
)

DEFAULT_APPROVAL_POLICIES: tuple[ApprovalPolicy, ...] = (
    ApprovalPolicy("AP-01", _check_soft_notional),
    ApprovalPolicy("AP-02", _check_concentration),
)
