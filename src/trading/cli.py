"""Standalone state inspection and reset CLI for the trading subsystem."""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from trading.clock import SystemClock
from trading.models import PersistenceError, SafetyConfig
from trading.runtime import (
    DEFAULT_INITIAL_CASH,
    RuntimeConfig,
    TradingRuntime,
    build_runtime,
)

DEFAULT_STATE_PATH = Path("trading_state.json")
DEFAULT_AUDIT_PATH = Path("trading_audit.jsonl")


def _initial_cash(value: str) -> Decimal:
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"invalid cash amount: {value!r}") from exc
    if not amount.is_finite() or amount < 0:
        raise argparse.ArgumentTypeError("initial cash must be non-negative")
    return amount


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trading-state",
        description="Inspect or reset the simulated trading portfolio state.",
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=DEFAULT_STATE_PATH,
        help="path to the portfolio state JSON file",
    )
    parser.add_argument(
        "--audit",
        type=Path,
        default=DEFAULT_AUDIT_PATH,
        help="path to the append-only audit JSONL file",
    )
    parser.add_argument(
        "--initial-cash",
        type=_initial_cash,
        default=DEFAULT_INITIAL_CASH,
        help="initial cash used when creating or resetting state",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="clear portfolio and backtest cursor, preserving the audit log",
    )
    return parser


def _print_summary(runtime: TradingRuntime) -> None:
    snapshot = runtime.portfolio.snapshot()
    print(f"Cash: {snapshot.cash:.2f}")
    print(f"Equity: {snapshot.total_equity:.2f}")
    print(f"Bankrupt: {'yes' if snapshot.bankrupt else 'no'}")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    config = RuntimeConfig(
        state_path=args.state,
        audit_path=args.audit,
        initial_cash=args.initial_cash,
        safety=SafetyConfig(),
    )
    try:
        runtime = build_runtime(config, SystemClock(), reset=args.reset)
    except PersistenceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.reset:
        print("State reset.")
    _print_summary(runtime)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
