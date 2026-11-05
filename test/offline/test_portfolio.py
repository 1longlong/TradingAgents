"""Portfolio ledger tests."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from trading.models import (
    DuplicateFillError,
    FeeModel,
    InsufficientCashError,
    InsufficientPositionError,
    OrderIntent,
    PortfolioError,
    Side,
    quantize_money,
)
from trading.portfolio import Portfolio

FIXED_NOW = datetime(2024, 1, 5, 21, 0, tzinfo=timezone.utc)


def _portfolio(cash="10000", fee_bps="5", min_fee="0") -> tuple[Portfolio, FeeModel]:
    fee_model = FeeModel(fee_bps=Decimal(fee_bps), min_fee=Decimal(min_fee))
    return (
        Portfolio(Decimal(cash), fee_model=fee_model, clock=lambda: FIXED_NOW),
        fee_model,
    )


def _order(
    fee_model: FeeModel,
    *,
    symbol="NVDA",
    side=Side.BUY,
    quantity="10",
    price="100",
) -> OrderIntent:
    qty = Decimal(quantity)
    px = Decimal(price)
    notional = quantize_money(qty * px)
    return OrderIntent(
        decision_id="dec-1",
        symbol=symbol,
        side=side,
        quantity=qty,
        price=px,
        notional=notional,
        fee=fee_model.fee_for(notional),
    )


@pytest.mark.unit
def test_fr02_approved_buy_updates_cash_and_position():
    """[FR-02] A BUY increases quantity and deducts value plus fee."""
    portfolio, fee_model = _portfolio()
    snapshot = portfolio.apply_fill(_order(fee_model), order_id="ord-1")

    assert portfolio.cash == Decimal("8999.50")
    assert portfolio.position("nvda") is not None
    assert portfolio.position("NVDA").quantity == Decimal("10.000000")
    assert portfolio.position("NVDA").average_cost == Decimal("100.050000")
    assert snapshot.total_fees == Decimal("0.50")
    assert snapshot.total_equity == Decimal("9999.50")
    assert snapshot.unrealized_pnl == Decimal("-0.50")
    assert snapshot.version == 1
    assert portfolio.has_applied("ord-1")


@pytest.mark.unit
def test_fr02_approved_sell_updates_cash_position_and_realized_pnl():
    """[FR-02] A SELL adds proceeds minus fee and realizes PnL."""
    portfolio, fee_model = _portfolio()
    portfolio.apply_fill(_order(fee_model), order_id="ord-buy")
    snapshot = portfolio.apply_fill(
        _order(fee_model, side=Side.SELL, quantity="4", price="110"),
        order_id="ord-sell",
    )

    assert portfolio.cash == Decimal("9439.28")
    position = portfolio.position("NVDA")
    assert position.quantity == Decimal("6.000000")
    assert position.average_cost == Decimal("100.050000")
    assert position.realized_pnl == Decimal("39.58")
    assert snapshot.realized_pnl == Decimal("39.58")
    assert snapshot.total_fees == Decimal("0.72")
    assert snapshot.unrealized_pnl == Decimal("59.70")
    assert snapshot.total_equity == Decimal("10099.28")


@pytest.mark.unit
def test_fr03_selling_all_clears_average_cost_but_keeps_realized_pnl():
    """[FR-03] A flat position is absent from the book without losing history."""
    portfolio, fee_model = _portfolio()
    portfolio.apply_fill(_order(fee_model), order_id="ord-buy")
    snapshot = portfolio.apply_fill(
        _order(fee_model, side=Side.SELL, quantity="10", price="110"),
        order_id="ord-sell",
    )

    assert portfolio.position("NVDA") is None
    assert snapshot.positions == ()
    assert snapshot.realized_pnl == Decimal("98.95")
    assert portfolio.cash == Decimal("10098.95")

    portfolio.apply_fill(
        _order(fee_model, quantity="2", price="100"),
        order_id="ord-rebuy",
    )
    assert portfolio.position("NVDA").average_cost == Decimal("100.050000")
    assert portfolio.snapshot().realized_pnl == Decimal("98.95")


@pytest.mark.unit
def test_fr03_mark_to_market_updates_unrealized_pnl_and_equity():
    """[FR-03] Marks change valuation but never cash or cost basis."""
    portfolio, fee_model = _portfolio()
    portfolio.apply_fill(_order(fee_model), order_id="ord-1")
    before = portfolio.snapshot()

    newly_bankrupt = portfolio.mark({"NVDA": Decimal("105")})
    after = portfolio.snapshot()

    assert newly_bankrupt is False
    assert after.cash == before.cash
    assert after.positions[0].average_cost == Decimal("100.050000")
    assert after.positions[0].market_price == Decimal("105")
    assert after.positions[0].market_value == Decimal("1050.00")
    assert after.unrealized_pnl == Decimal("49.50")
    assert after.total_equity == Decimal("10049.50")
    assert after.version == before.version + 1


@pytest.mark.unit
def test_fr03_snapshot_falls_back_to_average_cost_and_flags_incomplete_valuation():
    """[FR-03] A restored holding without a mark is valued explicitly, not guessed."""
    from tradingagents.portfolio import PortfolioContext, Position as ContextPosition

    fee_model = FeeModel()
    portfolio = Portfolio.from_context(
        PortfolioContext(
            cash=1000.0,
            positions=[ContextPosition(ticker="NVDA", quantity=10.0, average_price=100.0)],
        ),
        fee_model=fee_model,
    )

    snapshot = portfolio.snapshot()
    assert snapshot.cash == Decimal("1000.00")
    assert snapshot.positions[0].market_price == Decimal("100.000000")
    assert snapshot.positions[0].market_value == Decimal("1000.00")
    assert snapshot.total_equity == Decimal("2000.00")
    assert snapshot.valuation_incomplete is True


@pytest.mark.unit
def test_fr03_from_and_to_context_round_trip_advisory_state():
    """[FR-03] The existing read-only PortfolioContext can seed and display the book."""
    from tradingagents.portfolio import PortfolioContext, Position as ContextPosition

    fee_model = FeeModel()
    portfolio = Portfolio.from_context(
        PortfolioContext(
            cash=2500.0,
            positions=[
                ContextPosition(ticker="NVDA", quantity=3.0, average_price=100.0),
                ContextPosition(ticker="AAPL", quantity=2.0, average_price=50.0),
            ],
        ),
        fee_model=fee_model,
    )

    context = portfolio.to_context()
    assert context.cash == pytest.approx(2500.0)
    assert [(p.ticker, p.quantity, p.average_price) for p in context.positions] == [
        ("AAPL", pytest.approx(2.0), pytest.approx(50.0)),
        ("NVDA", pytest.approx(3.0), pytest.approx(100.0)),
    ]


@pytest.mark.unit
def test_fr02_insufficient_cash_leaves_state_unchanged():
    """[FR-02] A rejected BUY cannot partially debit the portfolio."""
    portfolio, fee_model = _portfolio(cash="100")
    before = portfolio.snapshot()

    with pytest.raises(InsufficientCashError):
        portfolio.apply_fill(
            _order(fee_model, quantity="1", price="200"),
            order_id="ord-1",
        )

    after = portfolio.snapshot()
    assert after.cash == before.cash == Decimal("100.00")
    assert after.positions == ()
    assert after.version == before.version
    assert not portfolio.has_applied("ord-1")


@pytest.mark.unit
def test_fr02_insufficient_position_leaves_state_unchanged():
    """[FR-02] A rejected SELL cannot partially reduce a holding."""
    portfolio, fee_model = _portfolio()
    portfolio.apply_fill(
        _order(fee_model, quantity="1", price="100"),
        order_id="ord-buy",
    )
    before = portfolio.snapshot()

    with pytest.raises(InsufficientPositionError):
        portfolio.apply_fill(
            _order(fee_model, side=Side.SELL, quantity="2", price="100"),
            order_id="ord-sell",
        )

    after = portfolio.snapshot()
    assert after.cash == before.cash
    assert after.positions[0].quantity == Decimal("1.000000")
    assert after.version == before.version
    assert not portfolio.has_applied("ord-sell")


@pytest.mark.unit
def test_fr02_duplicate_fill_is_rejected_without_mutation():
    """[FR-02] An order id is applied at most once."""
    portfolio, fee_model = _portfolio()
    portfolio.apply_fill(_order(fee_model), order_id="ord-1")
    before = portfolio.snapshot()

    with pytest.raises(DuplicateFillError):
        portfolio.apply_fill(_order(fee_model), order_id="ord-1")

    assert portfolio.snapshot() == before


@pytest.mark.unit
@pytest.mark.parametrize(
    "quantity,price,notional,fee",
    [
        ("0", "100", "0", "0"),
        ("1", "0", "0", "0"),
        ("1", "-100", "-100", "0"),
        ("1.0000001", "100", "100.00", "0.05"),
        ("1", "100", "99.00", "0.05"),
        ("1", "100", "100.00", "0.00"),
    ],
)
def test_fr02_invalid_fill_inputs_are_rejected(quantity, price, notional, fee):
    """[FR-02] Malformed quantities, prices, notionals, and fees fail closed."""
    portfolio, _ = _portfolio()
    order = OrderIntent(
        decision_id="dec-1",
        symbol="NVDA",
        side=Side.BUY,
        quantity=Decimal(quantity),
        price=Decimal(price),
        notional=Decimal(notional),
        fee=Decimal(fee),
    )

    with pytest.raises(PortfolioError):
        portfolio.apply_fill(order, order_id="ord-1")
    assert portfolio.snapshot().positions == ()
    assert portfolio.cash == Decimal("10000.00")


@pytest.mark.unit
def test_fr02_order_id_and_symbol_must_be_present():
    """[FR-02] Applied orders have explicit identity."""
    portfolio, fee_model = _portfolio()
    with pytest.raises(PortfolioError):
        portfolio.apply_fill(_order(fee_model), order_id=" ")

    blank_symbol = _order(fee_model)
    blank_symbol = OrderIntent(
        decision_id=blank_symbol.decision_id,
        symbol=" ",
        side=blank_symbol.side,
        quantity=blank_symbol.quantity,
        price=blank_symbol.price,
        notional=blank_symbol.notional,
        fee=blank_symbol.fee,
    )
    with pytest.raises(PortfolioError):
        portfolio.apply_fill(blank_symbol, order_id="ord-1")


@pytest.mark.unit
def test_fr03_marks_reject_negative_prices_and_are_read_only():
    """[FR-03] Marks cannot invent negative value or mutate internal state."""
    portfolio, fee_model = _portfolio()
    portfolio.apply_fill(_order(fee_model), order_id="ord-1")

    with pytest.raises(PortfolioError):
        portfolio.mark({"NVDA": Decimal("-1")})

    prices = portfolio.last_prices
    with pytest.raises(TypeError):
        prices["NVDA"] = Decimal("1")  # type: ignore[index]


@pytest.mark.unit
def test_fr03_from_context_rejects_unsupported_books():
    """[FR-03] Short, duplicate, and cashless contexts fail before trading."""
    from tradingagents.portfolio import PortfolioContext, Position as ContextPosition

    fee_model = FeeModel()
    with pytest.raises(PortfolioError):
        Portfolio.from_context(PortfolioContext(cash=None), fee_model=fee_model)
    with pytest.raises(PortfolioError):
        Portfolio.from_context(
            PortfolioContext(
                cash=1000.0,
                positions=[ContextPosition(ticker="NVDA", quantity=-1.0, average_price=100.0)],
            ),
            fee_model=fee_model,
        )
    with pytest.raises(PortfolioError):
        Portfolio.from_context(
            PortfolioContext(
                cash=1000.0,
                positions=[
                    ContextPosition(ticker="NVDA", quantity=1.0, average_price=100.0),
                    ContextPosition(ticker="NVDA", quantity=2.0, average_price=100.0),
                ],
            ),
            fee_model=fee_model,
        )


@pytest.mark.unit
def test_fr02_cash_is_quantized_and_versions_advance_once_per_fill():
    """[FR-02] Ledger precision and versioning are deterministic."""
    fee_model = FeeModel(fee_bps=Decimal("0"), min_fee=Decimal("0"))
    portfolio = Portfolio(Decimal("1000.001"), fee_model=fee_model)
    assert portfolio.cash == Decimal("1000.00")
    assert portfolio.version == 0

    portfolio.apply_fill(
        _order(fee_model, quantity="1", price="100.00"),
        order_id="ord-1",
    )
    assert portfolio.version == 1
