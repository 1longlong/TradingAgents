"""The OHLCV cache: one file per symbol, fresh only on the day it was written.

A current-day request also refetches past a TTL, so a run started before the
day's bar was final is not served that snapshot all day (#1150). Keying the file
by symbol rather than by day keeps the cache from growing a file per symbol per
day (#1330).

Three time meanings are kept apart here, as the production code does:

- the file's mtime is an **absolute instant** (a POSIX epoch, zone-free);
- ``now`` is the host's **local wall time** (``pd.Timestamp.today()``, naive);
- ``curr_date`` is a **business date** (naive, not an instant).

So ``NOW`` is a naive *local* wall time, and every fixture converts it to a real
instant through an explicit zone before writing an mtime. ``NOW.value`` is NOT
an epoch: it silently calls a local wall clock UTC. Each case runs in the zone
it names, never in whatever zone the test runner happens to be in.
"""
from __future__ import annotations

import itertools
import os
import time

import pandas as pd
import pytest

import tradingagents.dataflows.stockstats_utils as su

# Naive: the local wall time ``pd.Timestamp.today()`` would return.
NOW = pd.Timestamp("2026-07-18 12:00")
STALE = su.OHLCV_CACHE_TTL_SECONDS + 60

ZONE_UTC = "UTC"
ZONE_SHANGHAI = "Asia/Shanghai"
ZONE_NEW_YORK = "America/New_York"

_NAME_SEQ = itertools.count()


def _tzinfo(zone: str):
    """The tz for ``zone`` (whatever offset that zone has on 2026-07-18)."""
    return pd.Timestamp("2026-07-18 12:00", tz=zone).tzinfo


def _aware(local_naive, zone: str) -> pd.Timestamp:
    """A local wall time read in ``zone`` (never relabelled as UTC)."""
    return pd.Timestamp(local_naive).tz_localize(_tzinfo(zone))


def real_now() -> pd.Timestamp:
    """The fixture's "real now": the host clock read in UTC, rounded to seconds.

    The nominal fixtures are dated 2026-07-18 (~110 days after this host's
    real clock), so a raw 2026 mtime is "in the future" and Windows silently
    clamps it to the real clock. Everything is therefore written on the real
    clock, shifted by the fixture's wall time relative to it; ``_fresh`` and
    ``_load`` apply the same shift to ``now``, so the nominal calendar and TTL
    facts are exactly what is tested.
    """
    return pd.Timestamp(time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), tz="UTC")


def _shift_to_real_clock(local_naive, zone: str) -> pd.Timestamp:
    """The instant of ``local_naive`` (wall time in ``zone``), moved onto the real clock.

    Equivalent for every calendar and age comparison to a real host clock at
    ``local_naive``, but always at-or-before ``time.time()`` so the OS stores
    the mtime it is given.
    """
    base = real_now()
    # ``base`` read as a wall clock in the same zone. Shifting the nominal
    # aware instant by the *difference from that reading* keeps the result a
    # pure wall-clock shift (an instant difference would add the offset twice
    # and move the day), and leaves the zone's offset on the result.
    base_wall = base.tz_convert(zone).tz_localize(None)
    return _aware(local_naive, zone) + (base - _aware(base_wall, zone))


@pytest.fixture(autouse=True)
def _pinned_host_zone(monkeypatch):
    """Keep the host's real timezone out of every case in this module.

    ``_cache_is_fresh`` converts the file's epoch into the *host* zone to get
    its calendar day. The host here reports a miscalibrated zone, so a module
    that says "UTC" would otherwise be judged in it. Tests name their zone
    explicitly (``zone=...`` / ``tz=...``); this fixture makes UTC the default,
    and ``_fresh`` pins the case's own zone.
    """
    monkeypatch.setattr(su, "local_tz", lambda: _tzinfo(ZONE_UTC))


def _write(tmp_path, local_naive, zone=ZONE_UTC, age_seconds=0.0,
           last_date="2026-07-17", name=None):
    """Write a cache file mtime-dated ``age_seconds`` before ``local_naive`` in ``zone``.

    Anchored on the *host's real* clock (``time.time()``) so the requested
    instant is in the past even when the nominal date (2026-07-18) is not: this
    Windows host silently clamps a future mtime to the real clock. ``now`` is
    then built in the engine under test as ``real now_read + (nominal - real)``,
    i.e. the same wall time in the same zone, so every calendar/TTL fact holds.
    """
    if name is None:
        name = f"cache-{next(_NAME_SEQ)}.csv"
    f = tmp_path / name
    pd.DataFrame({"Date": [last_date], "Close": [100.0]}).to_csv(f, index=False)
    # The fixture's wall time is the 2026-07-18 date shifted onto the real
    # clock (see ``now_read``); the age is then subtracted as an absolute
    # number of seconds, exactly as "written N seconds ago" means.
    written = _shift_to_real_clock(local_naive, zone).timestamp() - age_seconds
    os.utime(f, (written, written))
    _fail_if_clamped(f, written, age_seconds)
    return f


def _fail_if_clamped(f, written, age_seconds) -> None:
    """Fail if the filesystem stored a mtime other than the one requested.

    ``os.utime`` succeeds silently on Windows while clamping a *future* mtime
    to the host's real clock. Catching that keeps a mis-written fixture from
    quietly testing the wrong age (or passing for the wrong reason).
    """
    assert abs(os.path.getmtime(f) - written) <= 1, (
        f"filesystem stored mtime {os.path.getmtime(f)} instead of {written} "
        f"(requested age {age_seconds}s); the OS clamped it to the real clock"
    )


def _fresh(f, curr_date, local_naive, zone=ZONE_UTC) -> bool:
    """Check freshness with ``now`` as the local wall time of ``zone``.

    ``now`` is the nominal wall time shifted onto the host's real clock (the
    same construction ``_write`` uses for the mtime), so nominal calendar facts
    (midnight, day boundaries, offsets) still decide the verdict. ``zone`` is
    also installed as the host zone, since that is the zone the naive ``now``
    belongs to.
    """
    previous = su.local_tz
    su.local_tz = lambda: _tzinfo(zone)
    try:
        return su._cache_is_fresh(
            f, pd.Timestamp(curr_date), _shift_to_real_clock(local_naive, zone)
        )
    finally:
        su.local_tz = previous


def _load(tmp_path, monkeypatch, curr_date, download, reachable=True, *, tz=ZONE_UTC, now=NOW):
    monkeypatch.setattr(su, "get_config", lambda: {"data_cache_dir": str(tmp_path)})
    # Naive local wall time, as ``pd.Timestamp.today()`` returns it, on the
    # same shifted clock the cache file was written with.
    shifted = _shift_to_real_clock(now, tz)
    monkeypatch.setattr(su.pd.Timestamp, "today",
                        staticmethod(lambda: shifted.tz_convert(_tzinfo(tz)).tz_localize(None)))
    # The host zone the naive ``now`` belongs to; explicit, so no test depends
    # on (or is broken by) the machine's own timezone setting.
    monkeypatch.setattr(su, "local_tz", lambda: _tzinfo(tz))
    monkeypatch.setattr(su.yf, "download", download)
    # Mocked at the symbol's lookup site (raise_for_empty reads su.vendor_reachable),
    # so no load path can reach the network through it.
    monkeypatch.setattr(su, "vendor_reachable", lambda host: reachable)
    return su.load_ohlcv("AAPL", curr_date)


# ---------------------------------------------------------------------------
# Core rules: same-day, TTL, earlier-day file.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_current_day_cache_past_ttl_is_not_fresh(tmp_path):
    # Today's bar missing or still in progress: row inspection can't tell, so the TTL governs.
    assert _fresh(_write(tmp_path, NOW, age_seconds=STALE), NOW, NOW) is False
    f = _write(tmp_path, NOW, age_seconds=STALE, last_date="2026-07-18")
    assert _fresh(f, NOW, NOW) is False


@pytest.mark.unit
def test_recent_cache_is_fresh(tmp_path):
    # Written moments ago: don't hammer the vendor (weekend/holiday guard).
    assert _fresh(_write(tmp_path, NOW), NOW, NOW) is True


@pytest.mark.unit
def test_historical_request_uses_todays_cache_past_the_ttl(tmp_path):
    f = _write(tmp_path, NOW, age_seconds=STALE, last_date="2026-04-30")
    assert _fresh(f, "2026-05-01", NOW) is True


@pytest.mark.unit
def test_a_same_day_request_past_the_ttl_is_not_fresh(tmp_path):
    # The TTL rule with a same-day request too: 2h30m old, still the 18th.
    f = _write(tmp_path, NOW, age_seconds=2 * 3600 + 1800)
    assert _fresh(f, NOW, NOW) is False


@pytest.mark.unit
def test_a_download_from_an_earlier_day_is_not_fresh(tmp_path):
    # Written the *previous* calendar day (16:00 the day before NOW's noon),
    # so the day rule (not the TTL) must reject it for a historical request.
    f = _write(tmp_path, NOW, age_seconds=20 * 3600)
    assert _fresh(f, "2026-05-01", NOW) is False


@pytest.mark.unit
def test_load_ohlcv_refetches_stale_same_day_cache(tmp_path, monkeypatch):
    """End-to-end: the freshness check is wired into load_ohlcv's cache branch."""
    _write(tmp_path, NOW, age_seconds=STALE, name="AAPL-YFin-data.csv")
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
def test_load_ohlcv_accepts_a_fresh_cache(tmp_path, monkeypatch):
    """End-to-end, the fresh branch must not download (the other side of the wiring)."""
    _write(tmp_path, NOW, name="AAPL-YFin-data.csv", last_date="2026-07-17")

    def _download(*a, **k):
        raise AssertionError("fresh cache must not refetch")

    out = _load(tmp_path, monkeypatch, "2026-07-18", _download)
    assert 100.0 in out["Close"].values


# ---------------------------------------------------------------------------
# Timezones: a naive ``now`` is local wall time; the mtime is an absolute epoch.
# Every case names its zone, so none depends on the host's own timezone.
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("zone", [ZONE_UTC, ZONE_SHANGHAI, ZONE_NEW_YORK])
def test_same_instant_same_local_day_is_fresh_in_any_zone(tmp_path, zone):
    # The reported regression: 2026-07-18 12:00 in the host zone, file mtime
    # that very instant, same local naive ``now`` -> must be fresh. The old
    # code relabelled the local wall time as UTC while reading the file in UTC,
    # offsetting the two by the host's offset (8h for Shanghai).
    f = _write(tmp_path, NOW, zone=zone, age_seconds=0)
    assert _fresh(f, "2026-07-18", NOW, zone) is True


@pytest.mark.unit
@pytest.mark.parametrize("zone", [ZONE_UTC, ZONE_SHANGHAI, ZONE_NEW_YORK])
def test_writing_at_local_midnight_is_fresh_for_that_day(tmp_path, zone):
    # Exactly 00:00 local: written "today".
    local_midnight = pd.Timestamp("2026-07-18 00:00")
    f = _write(tmp_path, local_midnight, zone=zone, age_seconds=0)
    assert _fresh(f, "2026-07-18", local_midnight, zone) is True

@pytest.mark.unit
@pytest.mark.parametrize("zone", [ZONE_UTC, ZONE_SHANGHAI, ZONE_NEW_YORK])
@pytest.mark.parametrize("age", [su.OHLCV_CACHE_TTL_SECONDS - 1, su.OHLCV_CACHE_TTL_SECONDS])
def test_ttl_inside_is_fresh(tmp_path, zone, age):
    # The inside edge of the TTL, as an absolute age in seconds -- no zone
    # arithmetic, so the host's offset cannot move the boundary.
    f = _write(tmp_path, NOW, zone=zone, age_seconds=age)
    assert _fresh(f, "2026-07-18", NOW, zone) is True


@pytest.mark.unit
@pytest.mark.parametrize("zone", [ZONE_UTC, ZONE_SHANGHAI, ZONE_NEW_YORK])
def test_ttl_just_past_is_not_fresh(tmp_path, zone):
    # A current-day request (the TTL only governs that case): at 13:30 a file
    # written at 11:00 is 2h30m old and must refetch.
    stale_now = pd.Timestamp("2026-07-18 13:30")
    age = 2 * 3600 + 1800
    assert age > su.OHLCV_CACHE_TTL_SECONDS
    f = _write(tmp_path, stale_now, zone=zone, age_seconds=age)
    assert _fresh(f, "2026-07-18", stale_now, zone) is False
    # One second inside the limit, same now, is fresh.
    f = _write(tmp_path, stale_now, zone=zone, age_seconds=su.OHLCV_CACHE_TTL_SECONDS - 1)
    assert _fresh(f, "2026-07-18", stale_now, zone) is True


@pytest.mark.unit
@pytest.mark.parametrize("zone", [ZONE_SHANGHAI, ZONE_NEW_YORK])
def test_crossing_local_midnight_is_a_new_day(tmp_path, zone):
    # Written 23:59:30 the previous local day; ``now`` is 00:00:30 next day.
    # Only 60 seconds apart, well inside the TTL, but a different business day:
    # it holds yesterday's download, so it must not serve today's request.
    # (Raised with the timezone fix: the two dates here differ by one, so a
    # botched zone conversion lands on the wrong side of the midnight rule.)
    now = pd.Timestamp("2026-07-18 00:00:30")
    f = _write(tmp_path, now, zone=zone, age_seconds=60, last_date="2026-07-17")
    assert _fresh(f, "2026-07-18", now, zone) is False
    # Written 30s into the same local day is today's file: fresh.
    f = _write(tmp_path, now, zone=zone, age_seconds=30, last_date="2026-07-17")
    assert _fresh(f, "2026-07-18", now, zone) is True


@pytest.mark.unit
def test_an_absolute_instant_is_judged_in_the_host_zone(tmp_path):
    # The same *absolute* instant is two different wall times in Shanghai and
    # New York, so the host zone -- not a fixed one -- must decide which local
    # day the file belongs to. File written at 23:50 NY on the 17th, which is
    # 11:50 on the 18th in Shanghai.
    ny_wall = pd.Timestamp("2026-07-17 23:50")
    sh_wall = ny_wall.tz_localize(ZONE_NEW_YORK).tz_convert(ZONE_SHANGHAI).tz_localize(None)
    f = _write(tmp_path, sh_wall, zone=ZONE_SHANGHAI, age_seconds=0)

    # Same instant, same 10-minute-age check; only the host zone differs.
    ten_min_later_ny = ny_wall + pd.Timedelta(minutes=10)
    ten_min_later_sh = sh_wall + pd.Timedelta(minutes=10)
    assert _fresh(f, "2026-07-18", ten_min_later_sh, ZONE_SHANGHAI) is True
    assert _fresh(f, "2026-07-18", ten_min_later_ny, ZONE_NEW_YORK) is False


@pytest.mark.unit
def test_a_now_that_is_already_aware_keeps_its_own_zone(tmp_path):
    # Production passes naive local time, but an aware ``now`` must not be
    # re-interpreted: its zone is authoritative.
    instant = pd.Timestamp("2026-07-18 12:00", tz=ZONE_SHANGHAI)
    f = _write(tmp_path, instant.tz_localize(None), zone=ZONE_SHANGHAI)
    assert su._cache_is_fresh(f, pd.Timestamp("2026-07-17"), instant) is True
    # The very same instant seen from UTC is 04:00 on the 18th: still the
    # 18th, so the aware ``now`` governs, not the host zone.
    same_in_utc = instant.tz_convert("UTC")
    assert su._cache_is_fresh(f, pd.Timestamp("2026-07-17"), same_in_utc) is True
    # At 12:15 UTC the same file is >15 minutes old *and* still today: the
    # aware zone alone decides, with no host-zone date shift.
    later = pd.Timestamp("2026-07-18 12:15", tz="UTC")
    assert su._cache_is_fresh(f, pd.Timestamp("2026-07-18"), later) is False


@pytest.mark.unit
def test_local_tz_is_an_explicit_timezone():
    # The caller needs a real tz to interpret a naive wall time; on a normal
    # host that is a tzinfo, never the naive ``None`` used as "UTC".
    assert su.local_tz() is not None
