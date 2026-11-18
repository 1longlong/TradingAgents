"""The OHLCV cache: one file per symbol, fresh only on the day it was written.

A current-day request also refetches past a TTL, so a run started before the
day's bar was final is not served that snapshot all day (#1150). Keying the file
by symbol rather than by day keeps the cache from growing a file per symbol per
day (#1330).
"""
from __future__ import annotations

import os
import time

import pandas as pd
import pytest

import tradingagents.dataflows.stockstats_utils as su

NOW = pd.Timestamp("2026-07-18 12:00")
STALE = su.OHLCV_CACHE_TTL_SECONDS + 60


def _local_epoch(ts: pd.Timestamp) -> float:
    """Convert a wall-clock ``Timestamp`` to the POSIX epoch the cache expects.

    Production reads the cache mtime with ``pd.Timestamp.fromtimestamp`` (local
    time). To round-trip the same local wall time, the fixture epoch must
    interpret ``ts`` in the local zone too. ``pd.Timestamp.timestamp()`` instead
    treats a naive value as UTC, which shifts by the UTC offset of the host zone
    (e.g. 8h under Asia/Hong_Kong, 4h under America/New_York DST) and made the
    fixture look like a previous/future day. ``to_pydatetime().timestamp()``
    applies the local zone, so the round-trip is the same wall clock everywhere.
    """
    return ts.to_pydatetime().timestamp()


def _write(tmp_path, name="AAPL-YFin-data.csv", age_seconds=0.0, last_date="2026-07-17", now=None):
    f = tmp_path / name
    pd.DataFrame({"Date": [last_date], "Close": [100.0]}).to_csv(f, index=False)
    written = _local_epoch(now if now is not None else NOW) - age_seconds
    os.utime(f, (written, written))
    return f


def _load(tmp_path, monkeypatch, curr_date, download):
    monkeypatch.setattr(su, "get_config", lambda: {"data_cache_dir": str(tmp_path)})
    monkeypatch.setattr(su.pd.Timestamp, "today", staticmethod(lambda: NOW))
    monkeypatch.setattr(su.yf, "download", download)
    return su.load_ohlcv("AAPL", curr_date)


def _fail_download(*a, **k):
    raise AssertionError("fresh cache must not refetch")


@pytest.mark.unit
def test_current_day_cache_past_ttl_is_not_fresh(tmp_path):
    # Today's bar missing or still in progress: row inspection can't tell, so the TTL governs.
    assert su._cache_is_fresh(_write(tmp_path, age_seconds=STALE), NOW.normalize(), NOW) is False
    f = _write(tmp_path, age_seconds=STALE, last_date="2026-07-18")
    assert su._cache_is_fresh(f, NOW.normalize(), NOW) is False


@pytest.mark.unit
def test_recent_cache_is_fresh(tmp_path):
    # Written moments ago: don't hammer the vendor (weekend/holiday guard).
    assert su._cache_is_fresh(_write(tmp_path), NOW.normalize(), NOW) is True


@pytest.mark.unit
def test_historical_request_uses_todays_cache_past_the_ttl(tmp_path):
    f = _write(tmp_path, age_seconds=STALE, last_date="2026-04-30")
    assert su._cache_is_fresh(f, pd.Timestamp("2026-05-01"), NOW) is True


@pytest.mark.unit
def test_a_download_from_an_earlier_day_is_not_fresh(tmp_path):
    f = _write(tmp_path, age_seconds=13 * 3600)  # yesterday 23:00
    assert su._cache_is_fresh(f, pd.Timestamp("2026-05-01"), NOW) is False


@pytest.mark.unit
def test_load_ohlcv_refetches_stale_same_day_cache(tmp_path, monkeypatch):
    """End-to-end: the freshness check is wired into load_ohlcv's cache branch."""
    _write(tmp_path, age_seconds=STALE)
    calls = []

    def _fake_download(*a, **k):
        calls.append(1)
        return pd.DataFrame(
            {"Date": pd.to_datetime(["2026-07-17", "2026-07-18"]), "Close": [100.0, 222.0]}
        ).set_index("Date")

    out = _load(tmp_path, monkeypatch, "2026-07-18", _fake_download)
    assert calls, "stale same-day cache must trigger a refetch"
    assert 222.0 in out["Close"].values, "refreshed close must reach the caller"


@pytest.mark.unit
def test_load_ohlcv_reuses_fresh_same_day_cache(tmp_path, monkeypatch):
    _write(tmp_path, last_date="2026-07-18")
    _load(tmp_path, monkeypatch, "2026-07-18", _fail_download)


@pytest.mark.unit
def test_one_cache_file_per_symbol_across_days(tmp_path, monkeypatch):
    """A later day's download replaces the symbol's file instead of adding one (#1330)."""
    monkeypatch.setattr(su, "get_config", lambda: {"data_cache_dir": str(tmp_path)})
    frame = pd.DataFrame({"Date": pd.to_datetime(["2026-07-16", "2026-07-17"]), "Close": [1.0, 2.0]})
    downloads = []
    monkeypatch.setattr(su.yf, "download", lambda *a, **k: downloads.append(1) or frame.set_index("Date"))

    for day in ("2026-07-18 10:00", "2026-07-19 10:00", "2026-07-20 10:00"):
        now = pd.Timestamp(day)
        monkeypatch.setattr(su.pd.Timestamp, "today", staticmethod(lambda now=now: now))
        su.load_ohlcv("AAPL", "2026-07-17")
        written = list(tmp_path.glob("AAPL-*.csv"))
        epoch = _local_epoch(now)
        os.utime(written[0], (epoch, epoch))

    assert len(downloads) == 3, "each new day refetches"
    assert [p.name for p in tmp_path.iterdir()] == ["AAPL-YFin-data.csv"]


_TZ_CASES = [
    # (TZ name, a summer (DST-observing where applicable) wall time, a winter one)
    ("UTC", "2026-07-18 12:00", "2026-01-15 12:00"),
    ("Asia/Hong_Kong", "2026-07-18 12:00", "2026-01-15 12:00"),
    # America/New_York observes DST: summer (EDT, -04:00) and winter (EST, -05:00)
    # exercise the UTC-offset change that broke the old ``NOW.timestamp()`` fixture.
    ("America/New_York", "2026-07-18 12:00", "2026-01-15 12:00"),
]


@pytest.fixture()
def process_tz(monkeypatch):
    """Set the process time zone and restore ``TZ``/``tzset`` after the test.

    ``_cache_is_fresh`` reads mtimes with ``pd.Timestamp.fromtimestamp`` (local
    time), so the fixture epoch conversion and the production read must agree on
    the process zone. Each case sets its own zone and restores the original
    (including an unset ``TZ``) so test order cannot leak a zone into other tests.
    """

    original = os.environ.get("TZ")

    def _set(tz_name):
        monkeypatch.setenv("TZ", tz_name)
        time.tzset()

    yield _set

    if original is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = original
    time.tzset()


@pytest.mark.unit
@pytest.mark.parametrize("tz_name, summer_wall, winter_wall", _TZ_CASES)
@pytest.mark.parametrize("is_summer", [True, False])
def test_cache_freshness_round_trips_local_wall_time(
    tmp_path, process_tz, tz_name, summer_wall, winter_wall, is_summer
):
    """Freshness must not depend on the host zone's UTC offset (INV-9, NFR-OFF-001).

    Regression for the fixture bug where ``NOW.timestamp()`` (naive -> UTC)
    disagreed with production's ``pd.Timestamp.fromtimestamp`` (local), so a
    fresh/expired cache was misread under Asia/Hong_Kong and America/New_York.
    The wall-clock semantics of ``_cache_is_fresh`` are unchanged: a same-day
    file within the TTL is fresh, a same-day file past the TTL is not, and a file
    written on an earlier day is never fresh.
    """
    process_tz(tz_name)
    now = pd.Timestamp(summer_wall if is_summer else winter_wall)
    # A cache written now round-trips to the same wall time regardless of zone.
    assert pd.Timestamp.fromtimestamp(_local_epoch(now)) == now
    fresh = _write(tmp_path, "fresh.csv", age_seconds=0.0, last_date="2026-07-17", now=now)
    assert su._cache_is_fresh(fresh, now.normalize(), now) is True
    # Expired same-day cache is rejected (TTL governs).
    expired = _write(tmp_path, "expired.csv", age_seconds=STALE, last_date="2026-07-17", now=now)
    assert su._cache_is_fresh(expired, now.normalize(), now) is False
    # A download from an earlier day is never fresh, even with a fresh mtime.
    earlier = _write(tmp_path, "earlier.csv", age_seconds=24 * 3600, last_date="2026-07-17", now=now)
    assert su._cache_is_fresh(earlier, now.normalize(), now) is False
    # Historical same-day-cache behavior is preserved: a request dated before
    # today (but still on a day the cached file covers) may reuse today's cache
    # past the TTL (the row-inspection path is unchanged). The requested date is
    # derived from `now` so it stays strictly before the cache's write day.
    requested = (now - pd.Timedelta(days=13)).normalize()
    historical = _write(
        tmp_path, "historical.csv", age_seconds=STALE, last_date="2026-07-01", now=now
    )
    assert su._cache_is_fresh(historical, requested, now) is True
