"""Clock tests for the walk-forward simulator."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest

from trading.clock import DEFAULT_MARKET_TZ, SimulationClock, SystemClock


@pytest.mark.unit
def test_fr05_system_clock_reports_live_mode():
    """[FR-05] Live operation uses a timezone-aware wall clock and no simulated date."""
    clock = SystemClock()
    now = clock.now()
    assert now.tzinfo is not None
    assert now.utcoffset() is not None
    assert clock.is_simulated() is False
    assert clock.simulation_date() is None


@pytest.mark.unit
def test_fr05_simulation_clock_uses_market_close_not_wall_clock():
    """[FR-05] The simulated instant comes from the configured date, not today."""
    clock = SimulationClock(date(2000, 1, 3))
    assert clock.is_simulated() is True
    assert clock.simulation_date() == date(2000, 1, 3)
    assert clock.now() == datetime(2000, 1, 3, 16, 0, tzinfo=DEFAULT_MARKET_TZ)
    assert clock.now().date() != datetime.now(timezone.utc).date()


@pytest.mark.unit
def test_fr05_simulation_clock_supports_explicit_close_and_timezone():
    """[FR-05] Tests and demos can pin a deterministic close time."""
    clock = SimulationClock(
        date(2024, 1, 5),
        close_time=time(15, 30),
        tz=ZoneInfo("UTC"),
    )
    assert clock.now() == datetime(2024, 1, 5, 15, 30, tzinfo=timezone.utc)


@pytest.mark.unit
def test_fr05_simulation_clock_set_date_resets_displayed_instant():
    """[FR-05] The runner can move the clock to an exact trading day."""
    clock = SimulationClock(date(2024, 1, 5))
    clock.set_date(date(2024, 1, 8))
    assert clock.simulation_date() == date(2024, 1, 8)
    assert clock.now().date() == date(2024, 1, 8)


@pytest.mark.unit
def test_fr05_advance_trading_day_skips_weekend():
    """[FR-05] Friday advances to Monday, never to a weekend day."""
    clock = SimulationClock(date(2024, 1, 5))
    clock.advance_trading_day()
    assert clock.simulation_date() == date(2024, 1, 8)

    clock.set_date(date(2024, 1, 4))
    clock.advance_trading_day()
    assert clock.simulation_date() == date(2024, 1, 5)


@pytest.mark.unit
def test_fr05_simulation_clock_accepts_datetime_as_date():
    """[FR-05] A datetime input is reduced to its calendar date."""
    clock = SimulationClock(datetime(2024, 1, 5, 12, 0, tzinfo=timezone.utc))
    assert clock.simulation_date() == date(2024, 1, 5)


@pytest.mark.unit
def test_fr05_simulation_clock_rejects_non_date_input():
    """[FR-05] Invalid simulation dates fail before the runner starts."""
    with pytest.raises(TypeError):
        SimulationClock("2024-01-05")  # type: ignore[arg-type]
