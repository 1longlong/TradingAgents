"""Stage 6 — PIT notices must not assert a date they never measured.

``coverage_gap`` used to fall back to ``datetime.now()`` when a feed returned no
dated items, so the notice claimed ``coverage starts <today>`` — the run's
wall-clock date. Analysts treated it as vendor fact and carried it into their
reports (and in one Control v3 run drew a backwards "look-ahead" conclusion
from it). The same ticker/date/window therefore produced different text on
different days.

These tests pin the guarantees: P1 no unobserved date, P2 day-independent,
P3/P4 the load-bearing clauses survive, and the withhold decision is untouched.
"""

import re
from datetime import datetime, timedelta, timezone

import pytest

from tradingagents.dataflows.date_window import coverage_gap, in_window

START, END = "2026-09-16", "2026-09-23"
SOURCES = [
    ("Yahoo Finance news", "news for NVDA"),
    ("Yahoo Finance global news", "market news"),
    ("StockTwits", "messages about $NVDA"),
    ("Reddit search", "discussion of NVDA"),
]


def _notices(**kw):
    """One notice per source, from the same ``dates`` argument."""
    return [coverage_gap(kw.get("dates", ()), START, END, s, subj) for s, subj in SOURCES]


@pytest.mark.unit
@pytest.mark.parametrize("dates", [(), (None,), (None, None)])
def test_no_observed_dates_asserts_no_date(dates):
    """P1: with nothing observed, the notice contains no fabricated date."""
    for notice in _notices(dates=dates):
        assert notice is not None
        # Only the requested window may appear; no "coverage starts <date>".
        assert "coverage starts" not in notice
        for found in re.findall(r"\d{4}-\d{2}-\d{2}", notice):
            assert found in (START, END), f"unobserved date leaked: {found}"


@pytest.mark.unit
def test_notice_is_identical_on_different_days():
    """P2: the text cannot depend on the wall clock."""
    # Same inputs twice, a real day apart is not simulable here, so assert the
    # property that causes it: no clock-derived value appears at all.
    today = datetime.now(timezone.utc).date()
    for offset in (0, 1, -400):
        probe = today + timedelta(days=offset)
        for notice in _notices():
            assert str(probe) not in notice


@pytest.mark.unit
def test_observed_coverage_start_is_kept():
    """A date that really was observed is still reported (it is not a guess)."""
    for notice in _notices(dates=[datetime(2026, 10, 28, tzinfo=timezone.utc)]):
        assert "coverage starts 2026-10-28" in notice


@pytest.mark.unit
@pytest.mark.parametrize("source,subject", SOURCES)
def test_loading_clauses_survive(source, subject):
    """P3/P4: still says "not an absence", still names its subject."""
    for dates in ((), (None,), [datetime(2026, 10, 28, tzinfo=timezone.utc)]):
        notice = coverage_gap(dates, START, END, source, subject)
        assert "not an absence of" in notice
        assert subject in notice
        assert notice.startswith(f"<{source} unavailable for {START}..{END}")


@pytest.mark.unit
def test_notice_fits_the_size_budget():
    """P6: <= 120 bytes over the old text, or a documented reason."""
    old_len = len(
        f"<StockTwits unavailable for {START}..{END}: it only serves recent items "
        f"(coverage starts 2026-11-04), so this is not an absence of messages about $NVDA>"
    )
    new_len = len(coverage_gap((), START, END, "StockTwits", "messages about $NVDA"))
    assert new_len <= old_len, f"{new_len} > {old_len}"


@pytest.mark.unit
def test_window_reaching_past_today_is_unaffected():
    today = datetime.now(timezone.utc).date()
    out = coverage_gap((), str(today), str(today + timedelta(days=3)), "Feed", "items")
    assert out is not None and "past today" in out


@pytest.mark.unit
def test_withhold_decision_is_unchanged():
    """P5: the fix touches the notice only, never the filter."""
    start = datetime(2026, 9, 16, tzinfo=timezone.utc)
    end = datetime(2026, 9, 23, tzinfo=timezone.utc)
    assert in_window(datetime(2026, 9, 20, tzinfo=timezone.utc), start, end)
    # Post-run-date items are still rejected; the guard is untouched.
    assert not in_window(datetime(2026, 11, 4, tzinfo=timezone.utc), start, end)
    # An undated item is still rejected for a past window.
    assert not in_window(None, start, end)
