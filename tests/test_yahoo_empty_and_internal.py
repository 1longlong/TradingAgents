"""An empty result is only an absence when nothing says the vendor failed.

``raise_for_empty`` consults ``vendor_reachable`` only to *avoid* a false
absence. A host that answers a HEAD request proves nothing about the specific
request, so reachability can never establish an absence; only an empty result
from a live vendor does. The news coverage placeholder follows the same rule:
a window the feed never observed is "could not answer", not "no news".
"""
from datetime import datetime, timezone

import pandas as pd
import pytest
import requests

import tradingagents.dataflows.stockstats_utils as su
import tradingagents.dataflows.y_finance as y_finance
import tradingagents.dataflows.yfinance_news as yfinance_news
from tradingagents.dataflows import date_window
from tradingagents.dataflows.errors import (
    NoMarketDataError,
    VendorAuthenticationError,
    VendorRateLimitError,
)


def _frozen_datetime(fixed):
    """A ``datetime`` subclass whose ``now`` is ``fixed``.

    ``coverage_gap`` reads the wall clock as ``datetime.now(timezone.utc)``
    after importing the class into its own module, so patching the class there
    is the seam. Subclassing (rather than replacing with a lambda) keeps
    ``strptime`` and the rest of the class intact for the same module.
    """
    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed if tz is not None else fixed.replace(tzinfo=None)

    return _FrozenDatetime


@pytest.mark.unit
class TestEmptyResult:
    def test_empty_with_a_dead_host_is_an_outage(self, monkeypatch, no_retry, yahoo):
        stub = lambda s: yahoo.ticker_returning(pd.DataFrame())  # noqa: E731
        monkeypatch.setattr(y_finance.yf, "Ticker", stub)
        # The lookup happens inside stockstats_utils.raise_for_empty.
        monkeypatch.setattr(su, "vendor_reachable", lambda url: False)
        with pytest.raises(VendorRateLimitError, match="unreachable"):
            y_finance.get_balance_sheet("AAPL", "annual", "2026-09-01")

    def test_empty_with_a_live_host_is_a_real_absence(self, monkeypatch, no_retry, yahoo):
        stub = lambda s: yahoo.ticker_returning(pd.DataFrame())  # noqa: E731
        monkeypatch.setattr(y_finance.yf, "Ticker", stub)
        monkeypatch.setattr(su, "vendor_reachable", lambda url: True)
        with pytest.raises(NoMarketDataError) as ctx:
            y_finance.get_balance_sheet("AAPL", "annual", "2026-09-01")
        assert not isinstance(ctx.value, VendorRateLimitError)
        assert "no balance sheet data" in str(ctx.value)

    def test_a_live_host_never_upgrades_an_error_to_an_absence(self, monkeypatch, no_retry, yahoo):
        # The boundary this batch enforces: reachable + failure stays a failure.
        monkeypatch.setattr(
            y_finance.yf, "Ticker", yahoo.ticker_raising(requests.Timeout("slow"))
        )
        monkeypatch.setattr(su, "vendor_reachable", lambda url: True)
        with pytest.raises(VendorRateLimitError):
            y_finance.get_balance_sheet("AAPL", "annual", "2026-09-01")

    def test_the_insider_empty_check_uses_its_own_module_name(self, monkeypatch, no_retry, yahoo):
        # get_insider_transactions calls ``vendor_reachable`` in y_finance, so a
        # patch on stockstats_utils would not take effect (and the test would
        # reach the real network). Patch where the call happens.
        stub = lambda s: yahoo.ticker_returning(pd.DataFrame())  # noqa: E731
        monkeypatch.setattr(y_finance.yf, "Ticker", stub)
        monkeypatch.setattr(su, "vendor_reachable", lambda url: True)  # must be ignored
        monkeypatch.setattr(y_finance, "vendor_reachable", lambda url: False)
        with pytest.raises(VendorRateLimitError, match="unreachable"):
            y_finance.get_insider_transactions("AAPL", "2026-09-01")


@pytest.mark.unit
class TestNewsCoverage:
    def test_an_unobserved_window_is_not_a_confirmed_absence(self, monkeypatch, no_retry, yahoo):
        class RecentOnlyTicker:
            def __init__(self, symbol):
                pass

            def get_news(self, count):
                return [{"content": {
                    "title": "t", "pubDate": "2026-01-08T00:00:00Z",
                    "canonicalUrl": {"url": "u"}, "provider": {"displayName": "p"},
                }}]

        monkeypatch.setattr(yfinance_news.yf, "Ticker", RecentOnlyTicker)
        out = yfinance_news.get_news_yfinance("AAPL", "2025-01-01", "2025-01-10")
        assert "unavailable" in out and "not an absence" in out
        assert "No news found" not in out

    def test_an_observed_empty_window_says_no_news(self, monkeypatch, no_retry, yahoo):
        # Pin the UTC clock ``coverage_gap`` actually reads, and query the same
        # date: "ends by today" is decided against that clock, not the host's.
        # (``get_current_date()`` is host-local, so a run near midnight could
        # ask about a day UTC still calls tomorrow.)
        now = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
        monkeypatch.setattr(date_window, "datetime", _frozen_datetime(now))
        monkeypatch.setattr(
            yfinance_news.yf, "Ticker", lambda s: yahoo.ticker_returning(pd.DataFrame(), news=[])
        )
        out = yfinance_news.get_news_yfinance("AAPL", "2026-05-08", "2026-05-08")
        assert out.startswith("No news found for AAPL")


@pytest.mark.unit
class TestUnknownErrorsAreNotAbsences:
    @pytest.mark.parametrize(
        "exc", [KeyError("totalRevenue"), TypeError("no len"), ValueError("x")]
    )
    def test_fundamentals_internal_error_keeps_its_type(self, monkeypatch, no_retry, yahoo, exc):
        monkeypatch.setattr(y_finance.yf, "Ticker", yahoo.ticker_raising(exc))
        with pytest.raises(type(exc)):
            y_finance.get_fundamentals("AAPL")

    def test_news_malformed_body_is_an_error_not_no_news(self, monkeypatch, no_retry, yahoo):
        monkeypatch.setattr(
            yfinance_news.yf,
            "Ticker",
            yahoo.ticker_raising(requests.exceptions.JSONDecodeError("Expecting value", "", 0)),
        )
        with pytest.raises(requests.exceptions.JSONDecodeError):
            yfinance_news.get_news_yfinance("AAPL", "2026-01-01", "2026-01-10")

    def test_news_internal_error_is_not_no_news(self, monkeypatch, no_retry, yahoo):
        monkeypatch.setattr(yfinance_news.yf, "Ticker", yahoo.ticker_raising(KeyError("content")))
        with pytest.raises(KeyError):
            yfinance_news.get_news_yfinance("AAPL", "2026-01-01", "2026-01-10")

    def test_a_403_on_news_is_auth_not_news(self, monkeypatch, no_retry, yahoo):
        monkeypatch.setattr(
            yfinance_news.yf, "Ticker", yahoo.ticker_raising(yahoo.status_error(requests, 403))
        )
        with pytest.raises(VendorAuthenticationError):
            yfinance_news.get_news_yfinance("AAPL", "2026-01-01", "2026-01-10")
