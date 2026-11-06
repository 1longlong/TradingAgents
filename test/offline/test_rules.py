"""Deterministic hard safety rule and approval policy tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from safety.rules import (
    DEFAULT_APPROVAL_POLICIES,
    DEFAULT_SAFETY_RULES,
    ApprovalPolicy,
    SafetyRule,
)
from trading.models import (
    DecisionAction,
    MarketQuote,
    OrderIntent,
    OrderType,
    PortfolioSnapshot,
    Position,
    RuleContext,
    SafetyConfig,
    Side,
    TradeDecision,
    quantize_money,
)

NOW = datetime(2024, 1, 5, 21, 0, tzinfo=timezone.utc)


def _position(
    symbol="NVDA",
    *,
    quantity="5",
    average_cost="100",
    price="100",
) -> Position:
    qty = Decimal(quantity)
    px = Decimal(price)
    avg = Decimal(average_cost)
    return Position(
        symbol=symbol,
        quantity=qty,
        average_cost=avg,
        market_price=px,
        market_value=quantize_money(qty * px),
        unrealized_pnl=quantize_money((px - avg) * qty),
    )


def _snapshot(cash="10000", positions=(), *, bankrupt=False) -> PortfolioSnapshot:
    cash_value = Decimal(cash)
    market_value = sum(
        (position.market_value or Decimal("0.00") for position in positions),
        Decimal("0.00"),
    )
    return PortfolioSnapshot(
        cash=cash_value,
        positions=tuple(positions),
        realized_pnl=Decimal("0.00"),
        unrealized_pnl=Decimal("0.00"),
        total_fees=Decimal("0.00"),
        total_equity=quantize_money(cash_value + market_value),
        bankrupt=bankrupt,
        version=0,
        as_of=NOW,
    )


def _context(
    *,
    action=DecisionAction.BUY,
    quantity="10",
    price="100",
    symbol="NVDA",
    cash="10000",
    positions=(),
    bankrupt=False,
    config=None,
    now=NOW,
    quote_as_of=None,
    quote_symbol=None,
    is_simulated=False,
    order_id="ord-dec-1",
    applied_order_ids=frozenset(),
    order_type=OrderType.MARKET,
    with_intent=True,
    run_id="run-1",
    decision_id="dec-1",
) -> RuleContext:
    config = config or SafetyConfig()
    action = DecisionAction(action) if isinstance(action, str) else action
    qty = Decimal(quantity) if quantity is not None else None
    px = Decimal(price)
    decision = TradeDecision(
        run_id=run_id,
        decision_id=decision_id,
        symbol=symbol,
        action=action,
        quantity=qty,
        order_type=order_type,
    )
    quote = MarketQuote(
        symbol=quote_symbol if quote_symbol is not None else symbol,
        price=px,
        as_of=quote_as_of if quote_as_of is not None else now,
    )
    snapshot = _snapshot(cash, positions, bankrupt=bankrupt)

    intent = None
    if with_intent and action in (DecisionAction.BUY, DecisionAction.SELL) and qty is not None:
        side = Side.BUY if action is DecisionAction.BUY else Side.SELL
        notional = quantize_money(qty * px)
        intent = OrderIntent(
            decision_id=decision_id,
            symbol=symbol,
            side=side,
            quantity=qty,
            price=px,
            notional=notional,
            fee=config.fee_model().fee_for(notional),
        )

    return RuleContext(
        decision=decision,
        quote=quote,
        config=config,
        portfolio=snapshot,
        order_intent=intent,
        now=now,
        is_simulated=is_simulated,
        order_id=order_id,
        applied_order_ids=applied_order_ids,
    )


def _rule(rule_id: str) -> SafetyRule:
    return next(rule for rule in DEFAULT_SAFETY_RULES if rule.rule_id == rule_id)


def _policy(policy_id: str) -> ApprovalPolicy:
    return next(policy for policy in DEFAULT_APPROVAL_POLICIES if policy.policy_id == policy_id)


def _with_intent(ctx: RuleContext, **changes) -> RuleContext:
    assert ctx.order_intent is not None
    return replace(ctx, order_intent=replace(ctx.order_intent, **changes))


def _violating_context(rule_id: str) -> RuleContext:
    if rule_id == "SR-01":
        return _context(run_id=" ")
    if rule_id == "SR-02":
        return _context(quantity="0", with_intent=False)
    if rule_id == "SR-03":
        return _context(quote_as_of=NOW - timedelta(seconds=301))
    if rule_id == "SR-04":
        return _context(config=SafetyConfig(allowed_symbols=frozenset({"AAPL"})))
    if rule_id == "SR-05":
        return _context(cash="10")
    if rule_id == "SR-06":
        return _context(
            action=DecisionAction.SELL,
            positions=(_position(quantity="5"),),
        )
    if rule_id == "SR-07":
        return _context(
            config=SafetyConfig(
                hard_max_order_notional=Decimal("500"),
                soft_max_order_notional=Decimal("400"),
            )
        )
    if rule_id == "SR-08":
        return _context(applied_order_ids=frozenset({"ord-dec-1"}))
    if rule_id == "SR-09":
        return _context(bankrupt=True)
    if rule_id == "SR-10":
        return _context(order_type=OrderType.LIMIT)
    raise AssertionError(rule_id)


@pytest.mark.unit
def test_rules_register_contains_sr01_through_sr10_and_both_policies():
    """[NFR-01] The rule catalogue is complete and explicitly ordered."""
    assert [rule.rule_id for rule in DEFAULT_SAFETY_RULES] == [
        f"SR-{number:02d}" for number in range(1, 11)
    ]
    assert [policy.policy_id for policy in DEFAULT_APPROVAL_POLICIES] == [
        "AP-01",
        "AP-02",
    ]


@pytest.mark.unit
@pytest.mark.parametrize("rule", DEFAULT_SAFETY_RULES, ids=lambda rule: rule.rule_id)
def test_nfr01_valid_baseline_passes_every_hard_rule(rule):
    """[NFR-01] A valid decision does not trigger a hard safety rule."""
    result = rule.evaluate(_context())
    assert result.passed is True
    assert result.reason == ""


@pytest.mark.unit
@pytest.mark.parametrize("rule_id", [rule.rule_id for rule in DEFAULT_SAFETY_RULES])
def test_nfr01_each_hard_rule_rejects_its_violation(rule_id):
    """[NFR-01] Every hard rule rejects the violation it owns."""
    result = _rule(rule_id).evaluate(_violating_context(rule_id))
    assert result.passed is False
    assert result.reason


@pytest.mark.unit
@pytest.mark.parametrize("policy", DEFAULT_APPROVAL_POLICIES, ids=lambda policy: policy.policy_id)
def test_ap_baseline_does_not_trigger_approval(policy):
    """[FR-01] A normal small order needs no human approval."""
    result = policy.evaluate(_context())
    assert result.triggered is False
    assert result.reason == ""


@pytest.mark.unit
@pytest.mark.parametrize("field", ["run_id", "decision_id", "symbol"])
def test_sr01_rejects_incomplete_identity(field):
    """[FR-01] SR-01 requires explicit decision identity."""
    ctx = _context(**{field: " "})
    result = _rule("SR-01").evaluate(ctx)
    assert result.passed is False
    assert field in result.reason


@pytest.mark.unit
@pytest.mark.parametrize("quantity", [None, "0", "-1", "1.0000001"])
def test_sr02_rejects_missing_or_invalid_quantity(quantity):
    """[FR-01] SR-02 requires a positive, six-decimal quantity."""
    ctx = _context(quantity=quantity, with_intent=False)
    result = _rule("SR-02").evaluate(ctx)
    assert result.passed is False


@pytest.mark.unit
def test_sr02_accepts_precise_positive_quantity():
    """[FR-01] SR-02 accepts the supported quantity scale."""
    assert _rule("SR-02").evaluate(_context(quantity="1.123456")).passed is True


@pytest.mark.unit
def test_sr03_live_freshness_uses_elapsed_seconds():
    """[FR-01] SR-03 enforces the configured age in live mode."""
    fresh = _context(quote_as_of=NOW - timedelta(seconds=100))
    stale = _context(quote_as_of=NOW - timedelta(seconds=301))
    assert _rule("SR-03").evaluate(fresh).passed is True
    assert _rule("SR-03").evaluate(stale).passed is False


@pytest.mark.unit
def test_sr03_simulation_uses_simulated_date_not_wall_clock():
    """[FR-05] SR-03 compares the quote date to the SimulationClock date."""
    same_day = _context(
        is_simulated=True,
        quote_as_of=datetime(2024, 1, 5, 0, 0, tzinfo=timezone.utc),
    )
    previous_day = _context(
        is_simulated=True,
        quote_as_of=datetime(2024, 1, 4, 21, 0, tzinfo=timezone.utc),
    )
    future = _context(
        is_simulated=True,
        quote_as_of=datetime(2024, 1, 6, 0, 0, tzinfo=timezone.utc),
    )
    assert _rule("SR-03").evaluate(same_day).passed is True
    assert _rule("SR-03").evaluate(previous_day).passed is False
    assert _rule("SR-03").evaluate(future).passed is False


@pytest.mark.unit
@pytest.mark.parametrize(
    "ctx",
    [
        _context(quote_symbol="AAPL"),
        _context(price="0"),
    ],
)
def test_sr03_rejects_bad_symbol_or_price(ctx):
    """[FR-01] SR-03 requires the matching symbol and a positive price."""
    assert _rule("SR-03").evaluate(ctx).passed is False


@pytest.mark.unit
def test_sr04_allowlist_is_case_insensitive_and_optional():
    """[FR-01] SR-04 enforces the configured symbol allowlist."""
    allowed = _context(
        symbol="nvda",
        config=SafetyConfig(allowed_symbols=frozenset({"NVDA"})),
    )
    blocked = _context(
        symbol="NVDA",
        config=SafetyConfig(allowed_symbols=frozenset({"AAPL"})),
    )
    assert _rule("SR-04").evaluate(allowed).passed is True
    assert _rule("SR-04").evaluate(blocked).passed is False
    assert _rule("SR-04").evaluate(_context()).passed is True


@pytest.mark.unit
def test_sr05_cash_boundary_includes_fee():
    """[FR-02] SR-05 requires cash for trade value plus fee."""
    exact = _context(cash="1000.50")
    short = _context(cash="1000.49")
    assert _rule("SR-05").evaluate(exact).passed is True
    assert _rule("SR-05").evaluate(short).passed is False


@pytest.mark.unit
def test_sr06_position_boundary_and_short_setting():
    """[FR-02] SR-06 prevents selling more than is held unless shorting is allowed."""
    exact = _context(
        action=DecisionAction.SELL,
        positions=(_position(quantity="10"),),
    )
    short = _context(
        action=DecisionAction.SELL,
        positions=(_position(quantity="9.999999"),),
    )
    allowed = _context(
        action=DecisionAction.SELL,
        positions=(_position(quantity="1"),),
        config=SafetyConfig(allow_short=True),
    )
    assert _rule("SR-06").evaluate(exact).passed is True
    assert _rule("SR-06").evaluate(short).passed is False
    assert _rule("SR-06").evaluate(allowed).passed is True


@pytest.mark.unit
def test_sr07_hard_notional_cap_boundary():
    """[FR-01] SR-07 permits the cap but rejects anything above it."""
    config = SafetyConfig(
        hard_max_order_notional=Decimal("500"),
        soft_max_order_notional=Decimal("400"),
    )
    at_cap = _context(config=config, quantity="5")
    over_cap = _context(config=config, quantity="6")
    assert _rule("SR-07").evaluate(at_cap).passed is True
    assert _rule("SR-07").evaluate(over_cap).passed is False


@pytest.mark.unit
@pytest.mark.parametrize(
    "applied",
    [
        frozenset({"ord-dec-1"}),
        frozenset({"dec-1"}),
    ],
)
def test_sr08_rejects_replayed_order_or_decision(applied):
    """[FR-05] SR-08 blocks replay after a resumed run."""
    ctx = _context(applied_order_ids=applied)
    assert _rule("SR-08").evaluate(ctx).passed is False
    assert _rule("SR-08").evaluate(_context()).passed is True


@pytest.mark.unit
def test_sr09_bankrupt_rejects_with_exact_reason():
    """[FR-06] SR-09 returns exactly BANKRUPT for every executable action."""
    for action in (DecisionAction.BUY, DecisionAction.SELL):
        ctx = _context(
            action=action,
            positions=(_position(quantity="10"),),
            bankrupt=True,
        )
        result = _rule("SR-09").evaluate(ctx)
        assert result.passed is False
        assert result.reason == "BANKRUPT"

    hold = _context(action=DecisionAction.HOLD, bankrupt=True)
    assert _rule("SR-09").evaluate(hold).passed is True


@pytest.mark.unit
@pytest.mark.parametrize(
    "changes",
    [
        {"decision_id": "other"},
        {"symbol": "AAPL"},
        {"side": Side.SELL},
        {"quantity": Decimal("5")},
        {"price": Decimal("101")},
        {"notional": Decimal("999.00")},
        {"fee": Decimal("0.00")},
    ],
)
def test_sr10_rejects_inconsistent_order_intent(changes):
    """[FR-01] SR-10 verifies the order intent against the decision and quote."""
    ctx = _with_intent(_context(), **changes)
    assert _rule("SR-10").evaluate(ctx).passed is False


@pytest.mark.unit
def test_sr10_rejects_replay_from_persisted_state():
    """[FR-05] SR-10 fails closed when persisted state marks the order as applied."""
    ctx = _context(applied_order_ids=frozenset({"ord-dec-1"}))
    assert _rule("SR-10").evaluate(ctx).passed is False


@pytest.mark.unit
def test_sr10_requires_intent_order_id_and_market_order():
    """[FR-01] SR-10 fails closed when the order envelope is incomplete."""
    missing_intent = replace(_context(), order_intent=None)
    missing_id = replace(_context(), order_id=" ")
    limit_order = _context(order_type=OrderType.LIMIT)

    assert _rule("SR-10").evaluate(missing_intent).passed is False
    assert _rule("SR-10").evaluate(missing_id).passed is False
    assert _rule("SR-10").evaluate(limit_order).passed is False


@pytest.mark.unit
def test_ap01_soft_notional_boundary():
    """[FR-01] AP-01 triggers only above the soft notional threshold."""
    at_soft = _context(quantity="25")
    above_soft = _context(quantity="30")
    assert _policy("AP-01").evaluate(at_soft).triggered is False
    assert _policy("AP-01").evaluate(above_soft).triggered is True


@pytest.mark.unit
def test_ap02_concentration_uses_post_trade_position_value():
    """[FR-01] AP-02 escalates a BUY that breaches concentration."""
    small = _context(quantity="10")
    large = _context(quantity="30")
    existing = _context(
        quantity="10",
        positions=(_position(quantity="15"),),
    )
    sell = _context(
        action=DecisionAction.SELL,
        quantity="10",
        positions=(_position(quantity="20"),),
    )
    assert _policy("AP-02").evaluate(small).triggered is False
    assert _policy("AP-02").evaluate(large).triggered is True
    assert _policy("AP-02").evaluate(existing).triggered is True
    assert _policy("AP-02").evaluate(sell).triggered is False


@pytest.mark.unit
def test_rule_and_policy_wrappers_fail_closed_on_errors():
    """[NFR-01] Unexpected rule evaluation errors reject; policy errors escalate."""
    broken_rule = SafetyRule("SR-TEST", lambda ctx: 1 / 0)
    broken_policy = ApprovalPolicy("AP-TEST", lambda ctx: 1 / 0)

    rule_result = broken_rule.evaluate(_context())
    policy_result = broken_policy.evaluate(_context())

    assert rule_result.passed is False
    assert "rule evaluation failed" in rule_result.reason
    assert policy_result.triggered is True
    assert "policy evaluation failed" in policy_result.reason


@pytest.mark.unit
def test_rule_evaluation_is_deterministic():
    """[NFR-01] Re-evaluating the same context yields the same result."""
    ctx = _context()
    first = [rule.evaluate(ctx) for rule in DEFAULT_SAFETY_RULES]
    second = [rule.evaluate(ctx) for rule in DEFAULT_SAFETY_RULES]
    assert first == second
