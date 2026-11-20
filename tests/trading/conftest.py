"""Deterministic fixtures for the offline trading subsystem tests."""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from trading.clock import SimulationClock  # noqa: E402

FIXED_UTC_NOW = datetime(2024, 1, 5, 21, 0, tzinfo=timezone.utc)


@pytest.fixture()
def fixed_utc_now() -> datetime:
    return FIXED_UTC_NOW


@pytest.fixture()
def simulation_clock() -> SimulationClock:
    return SimulationClock(date(2024, 1, 5))
