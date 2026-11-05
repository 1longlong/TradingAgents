"""Atomic state-store tests."""

from __future__ import annotations

import itertools
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from trading.audit import AuditLog
from trading.models import (
    EventType,
    FeeModel,
    OrderIntent,
    PersistenceError,
    Side,
    quantize_money,
)
from trading.persistence import BacktestCursor, StateStore
from trading.portfolio import Portfolio

FIXED_NOW = datetime(2024, 1, 5, 21, 0, tzinfo=timezone.utc)


class _FixedClock:
    def now(self) -> datetime:
        return FIXED_NOW

    def is_simulated(self) -> bool:
        return False

    def simulation_date(self):
        return None


def _seq(prefix: str):
    counter = itertools.count(1)
    return lambda: f"{prefix}-{next(counter)}"


def _store(tmp_path: Path, *, initial_cash="10000", fee_bps="5", min_fee="0"):
    clock = _FixedClock()
    fee_model = FeeModel(
        fee_bps=Decimal(fee_bps),
        min_fee=Decimal(min_fee),
    )
    audit = AuditLog(
        tmp_path / "audit.jsonl",
        clock=clock.now,
        id_factory=_seq("evt"),
    )
    store = StateStore(
        tmp_path / "state.json",
        fee_model=fee_model,
        clock=clock,
        audit=audit,
        initial_cash=Decimal(initial_cash),
    )
    return store, fee_model, clock, audit


def _portfolio(clock, fee_model, cash="10000") -> Portfolio:
    return Portfolio(Decimal(cash), fee_model=fee_model, clock=clock.now)


def _order(
    fee_model: FeeModel,
    *,
    quantity="10",
    price="100",
    side=Side.BUY,
) -> OrderIntent:
    qty = Decimal(quantity)
    px = Decimal(price)
    notional = quantize_money(qty * px)
    return OrderIntent(
        decision_id="dec-1",
        symbol="NVDA",
        side=side,
        quantity=qty,
        price=px,
        notional=notional,
        fee=fee_model.fee_for(notional),
    )


def _cursor(last=date(2024, 1, 5)) -> BacktestCursor:
    return BacktestCursor(
        run_id="run-1",
        symbol="NVDA",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 10),
        last_completed_date=last,
    )


@pytest.mark.unit
def test_fr06_save_and_load_round_trip_all_portfolio_fields(tmp_path):
    """[FR-06] Cash, positions, PnL, marks, replay ids, and cursor survive reload."""
    store, fee_model, clock, _ = _store(tmp_path)
    portfolio = _portfolio(clock, fee_model)
    portfolio.apply_fill(_order(fee_model), order_id="ord-1")
    portfolio.mark({"NVDA": Decimal("105")})
    cursor = _cursor()

    store.save(portfolio, cursor=cursor)
    loaded, loaded_cursor = store.load()

    assert loaded is not portfolio
    assert loaded.cash == portfolio.cash
    assert loaded.position("NVDA").quantity == Decimal("10.000000")
    assert loaded.position("NVDA").average_cost == Decimal("100.050000")
    assert loaded.snapshot().realized_pnl == portfolio.snapshot().realized_pnl
    assert loaded.snapshot().total_fees == portfolio.snapshot().total_fees
    assert loaded.last_prices["NVDA"] == Decimal("105")
    assert loaded.applied_order_ids == frozenset({"ord-1"})
    assert loaded.bankrupt is False
    assert loaded.version == portfolio.version
    assert loaded_cursor == cursor

    payload = json.loads(store.path.read_text(encoding="utf-8"))
    for field in (
        "cash",
        "positions",
        "realized_pnl",
        "total_fees",
        "last_prices",
        "applied_order_ids",
        "bankrupt",
    ):
        assert field in payload
    assert payload["backtest"]["run_id"] == "run-1"
    assert list(tmp_path.glob(".state.json.*.tmp")) == []


@pytest.mark.unit
def test_fr06_load_missing_file_returns_fresh_portfolio(tmp_path):
    """[FR-06] A missing state file starts at the requested initial cash."""
    store, _, _, _ = _store(tmp_path)
    portfolio, cursor = store.load(initial_cash=Decimal("500"))
    assert portfolio.cash == Decimal("500.00")
    assert portfolio.position("NVDA") is None
    assert portfolio.applied_order_ids == frozenset()
    assert cursor is None


@pytest.mark.unit
def test_fr06_load_can_restore_into_existing_portfolio(tmp_path):
    """[FR-06] A live engine keeps operating on the same restored instance."""
    store, fee_model, clock, _ = _store(tmp_path)
    source = _portfolio(clock, fee_model)
    source.apply_fill(_order(fee_model), order_id="ord-1")
    store.save(source, cursor=_cursor())

    target = _portfolio(clock, fee_model, cash="123")
    loaded, cursor = store.load(target=target)

    assert loaded is target
    assert target.cash == source.cash
    assert target.position("NVDA").quantity == Decimal("10.000000")
    assert target.applied_order_ids == frozenset({"ord-1"})
    assert cursor == _cursor()


@pytest.mark.unit
def test_fr06_corrupt_state_fails_closed_without_mutating_target(tmp_path):
    """[FR-06] Corruption raises and never silently resets the book."""
    store, fee_model, clock, _ = _store(tmp_path)
    store.path.write_text("{not-json", encoding="utf-8")
    target = _portfolio(clock, fee_model, cash="123")

    with pytest.raises(PersistenceError):
        store.load(target=target)
    assert target.cash == Decimal("123.00")

    store.path.write_text(
        json.dumps({"schema_version": 99}),
        encoding="utf-8",
    )
    with pytest.raises(PersistenceError):
        store.load()


@pytest.mark.unit
def test_fr06_bankruptcy_and_replay_state_round_trip(tmp_path):
    """[FR-06] BANKRUPT and applied order ids persist across restart."""
    store, fee_model, clock, _ = _store(tmp_path)
    portfolio = _portfolio(clock, fee_model)
    portfolio.apply_fill(_order(fee_model), order_id="ord-1")
    portfolio.mark_bankrupt(reason="test bankrupt")
    assert portfolio.bankrupt is True

    store.save(portfolio, cursor=_cursor())
    loaded, _ = store.load()

    assert loaded.bankrupt is True
    assert loaded.bankruptcy_reason == "test bankrupt"
    assert loaded.applied_order_ids == frozenset({"ord-1"})


@pytest.mark.unit
def test_fr06_reset_clears_state_and_appends_audit(tmp_path):
    """[FR-06] Reset restores initial cash without truncating audit history."""
    store, fee_model, clock, audit = _store(tmp_path)
    portfolio = _portfolio(clock, fee_model)
    portfolio.apply_fill(_order(fee_model), order_id="ord-1")
    portfolio.mark({"NVDA": Decimal("0")})
    store.save(portfolio, cursor=_cursor())
    before = audit.read_all()

    reset_portfolio = store.reset(
        initial_cash=Decimal("5000"),
        reason="supervisor reset",
    )

    assert reset_portfolio.cash == Decimal("5000.00")
    assert reset_portfolio.position("NVDA") is None
    assert reset_portfolio.applied_order_ids == frozenset()
    assert reset_portfolio.bankrupt is False

    loaded, cursor = store.load()
    assert loaded.cash == Decimal("5000.00")
    assert loaded.position("NVDA") is None
    assert cursor is None

    after = audit.read_all()
    assert len(after) == len(before) + 1
    assert after[: len(before)] == before
    assert after[-1].event_type is EventType.STATE_RESET
    assert after[-1].payload["reason"] == "supervisor reset"
    assert after[-1].payload["initial_cash"] == "5000.00"


@pytest.mark.unit
def test_fr06_reset_can_target_the_live_portfolio(tmp_path):
    """[FR-06] A running engine can be reset in place."""
    store, fee_model, clock, _ = _store(tmp_path)
    portfolio = _portfolio(clock, fee_model)
    portfolio.apply_fill(_order(fee_model), order_id="ord-1")
    store.save(portfolio, cursor=_cursor())

    returned = store.reset(
        initial_cash=Decimal("2500"),
        target=portfolio,
    )

    assert returned is portfolio
    assert portfolio.cash == Decimal("2500.00")
    assert portfolio.position("NVDA") is None
    assert portfolio.applied_order_ids == frozenset()
    _, cursor = store.load()
    assert cursor is None


@pytest.mark.unit
def test_fr06_atomic_overwrite_keeps_valid_json(tmp_path):
    """[FR-06] Re-saving replaces the document atomically."""
    store, fee_model, clock, _ = _store(tmp_path)
    first = _portfolio(clock, fee_model)
    second = _portfolio(clock, fee_model, cash="2000")
    second.apply_fill(
        _order(fee_model, quantity="1", price="50"),
        order_id="ord-2",
    )

    store.save(first, cursor=_cursor(date(2024, 1, 2)))
    store.save(second, cursor=_cursor(date(2024, 1, 3)))
    loaded, cursor = store.load()

    assert loaded.cash == Decimal("1949.97")
    assert cursor.last_completed_date == date(2024, 1, 3)
    assert json.loads(store.path.read_text(encoding="utf-8"))
    assert list(tmp_path.glob(".state.json.*.tmp")) == []
