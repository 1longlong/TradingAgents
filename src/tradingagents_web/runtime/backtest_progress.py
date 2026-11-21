"""REQ-WEB-011/021, INV-WEB-003/014, ADR-007-run-controls.md: observed date progress.

The owning BacktestRecord lock guards every update and snapshot. This state never
executes business work or infers success from elapsed time or saved log presence.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat()


class BacktestProgress:
    def __init__(self, tickers: list[str], dates: list[str]):
        self.tickers, self.dates = list(tickers), list(dates)
        self.ticker_indexes = {value: index for index, value in enumerate(tickers)}
        self.date_indexes = {value: index for index, value in enumerate(dates)}
        self.cells: dict[tuple[str, str], dict] = {}
        self.settlements: dict[str, str] = {}
        self.phase = "preparing"
        self.current: tuple[str, str] | None = None
        self.current_ticker: str | None = None
        self.last_index = 0
        self.started = time.monotonic()
        self.finished: float | None = None
        self.updated_at = _now()
        self.counts = {"completed": 0, "failed": 0, "skipped": 0}

    def update(self, event: dict):
        if self.finished is not None:
            return
        kind, ticker, date = event.get("event"), event.get("ticker"), event.get("date")
        if kind == "initializing" and not self.cells:
            self.phase = "preparing"
        elif kind == "summarizing":
            if len(self.settlements) != len(self.tickers) or any(
                value == "running" for value in self.settlements.values()
            ):
                return
            self.phase, self.current, self.current_ticker = "summarizing", None, None
        elif isinstance(kind, str) and kind.startswith("cell."):
            if ticker not in self.ticker_indexes or date not in self.date_indexes:
                return
            key = ticker, date
            row = self.cells.get(key)
            if row and row["status"] in self.counts:
                return
            if kind == "cell.started":
                if row or self.current is not None:
                    return
                row = {
                    "status": "running",
                    "started_at": _now(),
                    "finished_at": None,
                    "started": time.monotonic(),
                    "elapsed_seconds": None,
                }
                self.cells[key] = row
                self.current, self.current_ticker, self.phase = key, ticker, "analyzing"
            elif kind == "cell.skipped" and row is None and self.current is None:
                self.cells[key] = {
                    "status": "skipped",
                    "started_at": None,
                    "finished_at": _now(),
                    "elapsed_seconds": None,
                }
                self.counts["skipped"] += 1
            elif kind in {"cell.completed", "cell.failed"} and row and self.current == key:
                status = kind.split(".")[1]
                row.update(
                    status=status,
                    finished_at=_now(),
                    elapsed_seconds=round(time.monotonic() - row["started"], 1),
                )
                self.counts[status] += 1
                self.current = None
            else:
                return
            self.last_index = (
                self.ticker_indexes[ticker] * len(self.dates) + self.date_indexes[date]
            )
        elif isinstance(kind, str) and kind.startswith("settlement."):
            if ticker not in self.ticker_indexes or sum(self.counts.values()) != len(
                self.tickers
            ) * len(self.dates):
                return
            prior = self.settlements.get(ticker)
            if kind == "settlement.started" and prior is None:
                self.settlements[ticker] = "running"
            elif kind in {"settlement.completed", "settlement.failed"} and prior == "running":
                self.settlements[ticker] = kind.split(".")[1]
            else:
                return
            self.phase, self.current, self.current_ticker = "settling", None, ticker
        else:
            return
        self.updated_at = _now()

    def finish(self, status: str):
        if self.current:
            row = self.cells[self.current]
            row.update(
                status="interrupted",
                finished_at=_now(),
                elapsed_seconds=round(time.monotonic() - row["started"], 1),
            )
        self.phase, self.current, self.current_ticker = status, None, None
        self.finished, self.updated_at = time.monotonic(), _now()

    def snapshot(self, offset: int | None = None, limit: int = 25):
        total = len(self.tickers) * len(self.dates)
        limit = max(1, min(limit, 100))
        offset = self.last_index if offset is None else max(0, offset)
        offset = min(offset // limit, max(0, (total - 1) // limit)) * limit
        now = time.monotonic()
        rows = []
        for index in range(offset, min(total, offset + limit)):
            ticker, date = (
                self.tickers[index // len(self.dates)],
                self.dates[index % len(self.dates)],
            )
            stored = self.cells.get((ticker, date), {})
            elapsed = stored.get("elapsed_seconds")
            if stored.get("status") == "running":
                elapsed = round(now - stored["started"], 1)
            rows.append(
                {
                    "ticker": ticker,
                    "date": date,
                    "status": stored.get("status", "pending"),
                    "started_at": stored.get("started_at"),
                    "finished_at": stored.get("finished_at"),
                    "elapsed_seconds": elapsed,
                }
            )
        return {
            "phase": self.phase,
            "current_ticker": self.current_ticker,
            "current_date": self.current[1] if self.current else None,
            "processed": sum(self.counts.values()),
            "total": total,
            **self.counts,
            "settlements_completed": sum(
                value == "completed" for value in self.settlements.values()
            ),
            "settlements_failed": sum(value == "failed" for value in self.settlements.values()),
            "settlements_total": len(self.tickers),
            "observed": bool(self.cells),
            "elapsed_seconds": round(
                (self.finished if self.finished is not None else now) - self.started, 1
            ),
            "updated_at": self.updated_at,
            "cells": rows,
            "offset": offset,
            "limit": limit,
        }
