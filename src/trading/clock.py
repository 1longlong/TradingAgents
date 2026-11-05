"""Clocks used by the simulator and by live callers."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Protocol
from zoneinfo import ZoneInfo

DEFAULT_MARKET_TZ = ZoneInfo("America/New_York")


class Clock(Protocol):
    def now(self) -> datetime:
        """Return the current instant as a timezone-aware datetime."""

    def is_simulated(self) -> bool:
        """Return True when time is controlled by the walk-forward simulator."""

    def simulation_date(self) -> date | None:
        """Return the active simulated date, or None for a live clock."""


class SystemClock:
    """Wall-clock implementation for live operation."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def is_simulated(self) -> bool:
        return False

    def simulation_date(self) -> None:
        return None


class SimulationClock:
    """Deterministic clock pinned to a market close on a simulated date."""

    def __init__(
        self,
        day: date,
        close_time: time = time(16, 0),
        tz: ZoneInfo = DEFAULT_MARKET_TZ,
    ) -> None:
        self._tz = tz
        self._close_time = close_time.replace(tzinfo=None)
        self._day = self._coerce_day(day)
        self._now = self._at_close(self._day)

    @staticmethod
    def _coerce_day(day: date) -> date:
        if isinstance(day, datetime):
            return day.date()
        if not isinstance(day, date):
            raise TypeError(f"day must be a date, got {type(day).__name__}")
        return day

    def _at_close(self, day: date) -> datetime:
        return datetime.combine(day, self._close_time, tzinfo=self._tz)

    def now(self) -> datetime:
        return self._now

    def is_simulated(self) -> bool:
        return True

    def simulation_date(self) -> date:
        return self._day

    def set_date(self, day: date) -> None:
        self._day = self._coerce_day(day)
        self._now = self._at_close(self._day)

    def advance_trading_day(self) -> None:
        next_day = self._day + timedelta(days=1)
        while next_day.weekday() >= 5:
            next_day += timedelta(days=1)
        self.set_date(next_day)
