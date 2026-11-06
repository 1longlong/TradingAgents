"""Bankruptcy-state tests for the simulated portfolio."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from trading.models import (
    FeeModel,
    OrderIntent,
    PortfolioError,
    Side,
    quantize_money,
)
from trading.portfolio import Portfolio

FIXED_NOW = datetime(2024, 1, 5, 21, 0, tzinfo=timezone.utc)


def _portfolio(cash="1000", *, fee_bps="0", min_fee="0") -> tuple[Portfolio, FeeModel]:
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
def test_fr06_zero_equity_enters_bankrupt_and_is_sticky():
    """[FR-06] Equity at zero sets BANKRUPT and later marks cannot clear it."""
    portfolio, fee_model = _portfolio()
    portfolio.apply_fill(_order(fee_model), order_id="ord-1")
    assert portfolio.bankrupt is False
    assert portfolio.snapshot().total_equity == Decimal("1000.00")

    newly_bankrupt = portfolio.mark({"NVDA": Decimal("0")})
    snapshot = portfolio.snapshot()

    assert newly_bankrupt is True
    assert portfolio.bankrupt is True
    assert portfolio.bankruptcy_reason == "equity <= 0"
    assert snapshot.bankrupt is True
    assert snapshot.total_equity == Decimal("0.00")
    assert snapshot.positions[0].market_value == Decimal("0.00")
    assert snapshot.positions[0].unrealized_pnl == Decimal("-1000.00")

    version = portfolio.version
    assert portfolio.mark({"NVDA": Decimal("100")}) is False
    recovered = portfolio.snapshot()
    assert portfolio.bankrupt is True
    assert recovered.total_equity == Decimal("1000.00")
    assert portfolio.version == version + 1


@pytest.mark.unit
def test_fr06_negative_equity_after_fees_enters_bankrupt():
    """[FR-06] A fee can push total equity below zero, which is fatal."""
    from tradingagents.portfolio import PortfolioContext, Position as ContextPosition

    fee_model = FeeModel(fee_bps=Decimal("0"), min_fee=Decimal("1.00"))
    portfolio = Portfolio.from_context(
        PortfolioContext(
            cash=0.0,
            positions=[ContextPosition(ticker="NVDA", quantity=10.0, average_price=100.0)],
        ),
        fee_model=fee_model,
        clock=lambda: FIXED_NOW,
    )

    portfolio.apply_fill(
        _order(fee_model, side=Side.SELL, quantity="10", price="0.01"),
        order_id="ord-sell",
    )
    snapshot = portfolio.snapshot()

    assert portfolio.cash == Decimal("-0.90")
    assert snapshot.total_equity == Decimal("-0.90")
    assert portfolio.bankrupt is True
    assert portfolio.bankruptcy_reason == "equity <= 0"


@pytest.mark.unit
def test_fr06_bankrupt_rejects_every_new_fill_without_mutation():
    """[FR-06] No execution is possible after bankruptcy."""
    portfolio, fee_model = _portfolio()
    portfolio.apply_fill(_order(fee_model), order_id="ord-1")
    portfolio.mark({"NVDA": Decimal("0")})
    before = portfolio.snapshot()

    with pytest.raises(PortfolioError, match="BANKRUPT"):
        portfolio.apply_fill(
            _order(fee_model, quantity="1", price="50"),
            order_id="ord-2",
        )

    assert portfolio.snapshot() == before
    assert not portfolio.has_applied("ord-2")


@pytest.mark.unit
def test_fr06_manual_bankruptcy_mark_is_idempotent():
    """[FR-06] An explicit bankruptcy transition is recorded once."""
    portfolio, _ = _portfolio()
    portfolio.mark_bankrupt(reason="manual supervisor halt")

    assert portfolio.bankrupt is True
    assert portfolio.bankruptcy_reason == "manual supervisor halt"
    version = portfolio.version

    portfolio.mark_bankrupt(reason="ignored second call")
    assert portfolio.bankruptcy_reason == "manual supervisor halt"
    assert portfolio.version == version

    with pytest.raises(PortfolioError):
        portfolio.mark_bankrupt(reason=" ")


@pytest.mark.unit
def test_fr06_cashless_empty_portfolio_starts_bankrupt():
    """[FR-06] A zero-equity loaded book is treated as BANKRUPT at startup."""
    from tradingagents.portfolio import PortfolioContext

    portfolio = Portfolio.from_context(
        PortfolioContext(cash=0.0),
        fee_model=FeeModel(),
        clock=lambda: FIXED_NOW,
    )

    snapshot = portfolio.snapshot()
    assert snapshot.total_equity == Decimal("0.00")
    assert portfolio.bankrupt is True
    assert portfolio.bankruptcy_reason == "equity <= 0"
