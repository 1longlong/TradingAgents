"""News must not leak future-dated (or undated, in a backtest) articles.

The window primitive is provider-agnostic and pinned here directly. The
provider-specific look-ahead contracts live with each provider's suite:
"a vendor that cannot reach the window must never claim no news" and
"a covered-but-empty window is a real absence" are pinned in
``test_gdelt_news.py`` and ``test_finnhub_news.py``, and the merged-status
consequences in ``test_news_dual_source.py`` and ``test_news_status_taxonomy.py``.

Regressions for #992 (flat articles bypassed the date filter), #1007 (global
news injected future articles), #993 (empty-after-filter returned a blank body),
and #1126 (inclusive upper bound leaked the midnight-after article; host-local
timestamp parsing made filtering machine-dependent).

Traceability: NFR-PIT-001 (point-in-time integrity); supports INV-3 (no
look-ahead).
"""

from datetime import datetime, timezone

import pytest

from tradingagents.dataflows.date_window import in_window


@pytest.mark.unit
def test_window_excludes_future_and_undated_in_backtest():
    start = datetime(2025, 5, 1)
    end = datetime(2025, 5, 9)  # historical window (well in the past)
    inside = datetime(2025, 5, 5)
    future = datetime(2025, 6, 1)
    assert in_window(inside, start, end) is True
    assert in_window(future, start, end) is False     # look-ahead blocked
    assert in_window(None, start, end) is False        # undated -> excluded in backtest


@pytest.mark.unit
def test_window_keeps_undated_in_live_window():
    # Live window (reaches today): undated articles can't be "future", so keep them.
    now = datetime.now(timezone.utc)
    assert in_window(None, now, now) is True


@pytest.mark.unit
def test_upper_bound_is_exclusive():
    # #1126: an article stamped exactly midnight AFTER end_date leaked in under
    # the old inclusive bound; the whole of end_date itself must still be kept.
    start = datetime(2025, 5, 1)
    end = datetime(2025, 5, 9)
    midnight_after = datetime(2025, 5, 10, 0, 0, 0, tzinfo=timezone.utc)
    last_moment = datetime(2025, 5, 9, 23, 59, 59, tzinfo=timezone.utc)
    assert in_window(midnight_after, start, end) is False
    assert in_window(last_moment, start, end) is True


@pytest.mark.unit
def test_offset_aware_timestamp_is_converted_not_truncated():
    # #1126: 2025-05-10T01:00+05:00 is really 2025-05-09T20:00Z -> inside the
    # window. Stripping tzinfo (old behavior) misread it as 05-10 and dropped it.
    start = datetime(2025, 5, 1)
    end = datetime(2025, 5, 9)
    aware = datetime.fromisoformat("2025-05-10T01:00:00+05:00")
    assert in_window(aware, start, end) is True


@pytest.mark.unit
@pytest.mark.parametrize("dates, expect_gap", [
    ([], True),                                             # no dated items at all
    ([datetime(2026, 5, 20, tzinfo=timezone.utc)], True),    # all after the window
    ([datetime(2026, 5, 4, tzinfo=timezone.utc)], True),     # starts mid-window: partial
    ([datetime(2026, 5, 1, 18, tzinfo=timezone.utc)], False),  # reaches the first day
    ([datetime(2026, 5, 20, tzinfo=timezone.utc),
      datetime(2026, 4, 1, tzinfo=timezone.utc)], False),    # coverage reaches back
])
def test_coverage_gap_boundaries(dates, expect_gap):
    from tradingagents.dataflows.date_window import coverage_gap

    out = coverage_gap(dates, "2026-05-01", "2026-05-08", "Feed", "items")
    assert (out is not None) is expect_gap
    if expect_gap:
        assert "unavailable for 2026-05-01..2026-05-08" in out and "not an absence" in out


@pytest.mark.unit
def test_coverage_gap_future_window_is_unavailable():
    from datetime import timedelta

    from tradingagents.dataflows.date_window import coverage_gap
    today = datetime.now(timezone.utc).date()
    out = coverage_gap([], str(today), str(today + timedelta(days=3)), "Feed", "items")
    assert out is not None and "past today" in out
