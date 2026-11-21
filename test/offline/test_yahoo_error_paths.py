"""Every Yahoo statement/fundamentals/insider/news path classifies correctly.

Two layers are covered per path:

- a single failure (transport, 429, 401/403, 400/404, 5xx, malformed body) maps
  to the right typed error and never to ``NoMarketDataError``;
- the raw ``YFRateLimitError`` that ``yf_retry`` re-raises after its backoff is
  exhausted is classified too, not converted into an absence.

No network access: ``yf_retry`` is either a pass-through (``no_retry``) or the
real one with sleeping disabled (``real_retry_no_sleep``); ticker objects are
stubs.
"""
import pytest
import requests
from curl_cffi import requests as curl_client
from yfinance.exceptions import YFRateLimitError

import tradingagents.dataflows.y_finance as y_finance
import tradingagents.dataflows.yfinance_news as yfinance_news
from tradingagents.dataflows.errors import (
    NoMarketDataError,
    VendorAuthenticationError,
    VendorRateLimitError,
    VendorRequestRejectedError,
)

TRANSPORT = [
    pytest.param(requests.Timeout("read timed out"), id="requests-timeout"),
    pytest.param(requests.ConnectionError("refused"), id="requests-connection"),
    pytest.param(curl_client.exceptions.Timeout("read timed out"), id="curl-timeout"),
    pytest.param(curl_client.exceptions.ConnectionError("refused"), id="curl-connection"),
    pytest.param(TimeoutError("socket timed out"), id="builtin-timeout"),
    pytest.param(YFRateLimitError(), id="yf-rate-limit"),
]

STATUSES = [
    pytest.param(requests, 429, VendorRateLimitError, id="requests-429"),
    pytest.param(requests, 401, VendorAuthenticationError, id="requests-401"),
    pytest.param(requests, 403, VendorAuthenticationError, id="requests-403"),
    pytest.param(requests, 404, VendorRequestRejectedError, id="requests-404"),
    pytest.param(curl_client, 429, VendorRateLimitError, id="curl-429"),
    pytest.param(curl_client, 403, VendorAuthenticationError, id="curl-403"),
    pytest.param(curl_client, 404, VendorRequestRejectedError, id="curl-404"),
    pytest.param(curl_client, 503, VendorRateLimitError, id="curl-503"),
]

YAHOO_FUNCTIONS = [
    pytest.param("get_fundamentals", ("AAPL",), id="fundamentals"),
    pytest.param("get_balance_sheet", ("AAPL", "annual", "2026-09-01"), id="balance-sheet"),
    pytest.param("get_cashflow", ("AAPL", "annual", "2026-09-01"), id="cashflow"),
    pytest.param("get_income_statement", ("AAPL", "annual", "2026-09-01"), id="income"),
    pytest.param("get_insider_transactions", ("AAPL", "2026-09-01"), id="insider"),
]


@pytest.mark.unit
class TestSingleFailureIsClassified:
    @pytest.mark.parametrize("fn_name, args", YAHOO_FUNCTIONS)
    @pytest.mark.parametrize("exc", TRANSPORT)
    def test_transport_is_unavailable_on_every_path(
        self, monkeypatch, no_retry, yahoo, fn_name, args, exc
    ):
        monkeypatch.setattr(y_finance.yf, "Ticker", yahoo.ticker_raising(exc))
        with pytest.raises(VendorRateLimitError):
            getattr(y_finance, fn_name)(*args)

    @pytest.mark.parametrize("fn_name, args", YAHOO_FUNCTIONS)
    @pytest.mark.parametrize("client, status, expected", STATUSES)
    def test_status_keeps_its_meaning_on_every_path(
        self, monkeypatch, no_retry, yahoo, fn_name, args, client, status, expected
    ):
        err = yahoo.status_error(client, status)
        monkeypatch.setattr(y_finance.yf, "Ticker", yahoo.ticker_raising(err))
        with pytest.raises(expected):
            getattr(y_finance, fn_name)(*args)

    @pytest.mark.parametrize("exc", TRANSPORT)
    def test_ticker_news_transport_is_unavailable(self, monkeypatch, no_retry, yahoo, exc):
        monkeypatch.setattr(yfinance_news.yf, "Ticker", yahoo.ticker_raising(exc))
        with pytest.raises(VendorRateLimitError):
            yfinance_news.get_news_yfinance("AAPL", "2026-01-01", "2026-01-10")

    @pytest.mark.parametrize("exc", TRANSPORT)
    def test_global_news_transport_is_unavailable(self, monkeypatch, no_retry, yahoo, exc):
        monkeypatch.setattr(yfinance_news.yf, "Search", yahoo.search_raising(exc))
        with pytest.raises(VendorRateLimitError):
            yfinance_news.get_global_news_yfinance("2026-01-10", 7, 5)

    @pytest.mark.parametrize("client, status, expected", STATUSES)
    def test_news_status_keeps_its_meaning(
        self, monkeypatch, no_retry, yahoo, client, status, expected
    ):
        monkeypatch.setattr(
            yfinance_news.yf, "Ticker", yahoo.ticker_raising(yahoo.status_error(client, status))
        )
        with pytest.raises(expected):
            yfinance_news.get_news_yfinance("AAPL", "2026-01-01", "2026-01-10")

    def test_a_403_never_becomes_an_absence_or_a_throttle(self, monkeypatch, no_retry, yahoo):
        monkeypatch.setattr(
            y_finance.yf, "Ticker", yahoo.ticker_raising(yahoo.status_error(requests, 403))
        )
        with pytest.raises(VendorAuthenticationError) as ctx:
            y_finance.get_balance_sheet("AAPL", "annual", "2026-09-01")
        assert not isinstance(ctx.value, (VendorRateLimitError, NoMarketDataError))


@pytest.mark.unit
class TestRateLimitExhaustion:
    """``yf_retry`` re-raises the raw YFRateLimitError after its backoff."""

    @pytest.mark.parametrize("fn_name, args", YAHOO_FUNCTIONS)
    def test_exhaustion_propagates_as_a_throttle(
        self, monkeypatch, real_retry_no_sleep, yahoo, fn_name, args
    ):
        monkeypatch.setattr(y_finance.yf, "Ticker", yahoo.ticker_raising(YFRateLimitError()))
        with pytest.raises(VendorRateLimitError) as ctx:
            getattr(y_finance, fn_name)(*args)
        assert "rate limit" in str(ctx.value).lower()
        assert not isinstance(ctx.value, NoMarketDataError)

    def test_yf_retry_really_retries_then_reraises(self, monkeypatch):
        # Proves the fixture exercises the exhausted-after-retries path.
        import tradingagents.dataflows.stockstats_utils as su

        monkeypatch.setattr(su.time, "sleep", lambda s: None)
        calls = []

        def always_limited():
            calls.append(1)
            raise YFRateLimitError()

        with pytest.raises(YFRateLimitError):
            su.yf_retry(always_limited, max_retries=2)
        assert len(calls) == 3  # initial + 2 retries

    def test_insider_exhaustion_is_not_swallowed(
        self, monkeypatch, real_retry_no_sleep, yahoo
    ):
        # Previously a bare ``except Exception`` here re-labelled the typed
        # throttle it had just raised.
        monkeypatch.setattr(y_finance.yf, "Ticker", yahoo.ticker_raising(YFRateLimitError()))
        with pytest.raises(VendorRateLimitError):
            y_finance.get_insider_transactions("AAPL", "2026-09-01")
