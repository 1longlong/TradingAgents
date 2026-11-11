"""Stage 4 — news vendor failures must be classified, not lumped together.

A single ``NoMarketDataError`` for every failure told the analyst "the symbol
may be invalid, delisted, not covered, or stale" even when Yahoo was simply
down. The router already reacts by exception *type*; these tests pin the
mapping so a transient failure can never again be reported as a fact about the
instrument, and so a 401/403 can never abort the run.
"""

import unittest
from unittest.mock import patch

import requests

from tradingagents.dataflows import yfinance_news as yn
from tradingagents.dataflows import interface as iface
from tradingagents.dataflows.errors import (
    NoMarketDataError,
    VendorRateLimitError,
    VendorUnavailableError,
)

START, END = "2026-09-16", "2026-09-23"


def _http_error(status: int, text: str) -> requests.HTTPError:
    """Reproduce how yfinance surfaces a bad status: raise_for_status()."""
    response = requests.Response()
    response.status_code = status
    response.url = "https://example.invalid/x"
    response.reason = text
    with unittest.TestCase().assertRaises(requests.HTTPError) as ctx:
        response.raise_for_status()
    return ctx.exception


def _yfinance_only():
    """Context manager pinning ``get_news`` to yfinance alone.

    These tests pin *yfinance's* behaviour. Since campaign 20261107_140536 the
    default chain tries date-range vendors first, so an unpinned call returns
    GDELT's answer instead of exercising the code under test. Chain order
    itself is covered by ``test_historical_news.TestRouting``.
    """
    import copy

    import tradingagents.dataflows.config as config_module
    import tradingagents.default_config as default_config

    pinned = copy.deepcopy(default_config.DEFAULT_CONFIG)
    pinned.setdefault("tool_vendors", {})["get_news"] = "yfinance"
    return patch.object(config_module, "_config", pinned)


def _route_with_failure(exc: Exception) -> str:
    with patch.object(yn.yf, "Ticker") as ticker, _yfinance_only():
        ticker.side_effect = exc
        return iface.route_to_vendor("get_news", "NVDA", START, END)


class ClassifyNewsFailureTest(unittest.TestCase):
    def test_transient_failures_are_rate_limit_errors(self):
        cases = {
            "timeout": requests.exceptions.ReadTimeout("read timed out"),
            "connection": requests.exceptions.ConnectionError("curl: (28) timed out"),
            "yf_rate_limit": yn.YFRateLimitError(),
            "http_500": _http_error(500, "Internal Server Error"),
            "http_503": _http_error(503, "Service Unavailable"),
            "http_408": _http_error(408, "Request Timeout"),
            "http_429": _http_error(429, "Too Many Requests"),
            "http_401": _http_error(401, "Unauthorized"),
            "http_403": _http_error(403, "Forbidden"),
        }
        for name, exc in cases.items():
            with self.subTest(case=name):
                self.assertIsInstance(
                    yn._classify_news_failure(exc, "NVDA", "NVDA", "news unavailable"),
                    VendorRateLimitError,
                )

    def test_absence_remains_no_market_data(self):
        cases = {
            "http_404": _http_error(404, "Not Found"),
            "http_400": _http_error(400, "Bad Request"),
            "unknown": ValueError("something odd"),
        }
        for name, exc in cases.items():
            with self.subTest(case=name):
                self.assertIsInstance(
                    yn._classify_news_failure(exc, "NVDA", "NVDA", "news unavailable"),
                    NoMarketDataError,
                )

    def test_yfinance_data_exception_is_the_retired_endpoint(self):
        # yfinance raises this their own literal outage marker (seen live on
        # 2026-11-04); before Stage 4 it was reported as "symbol may be invalid".
        # Campaign 20261107_140536 then measured the cause with a raw HTTP call:
        # ``xhr/ncp`` answers HTTP 404 with a plain-text body, yfinance's JSON
        # parse fails and it raises this marker. The endpoint is RETIRED, so the
        # marker is permanent, not transient -- see
        # ``test_yfinance_data_exception_is_the_retired_endpoint``.
        self.assertIsInstance(
            yn._classify_news_failure(
                yn.YFDataException("*** YAHOO! FINANCE IS CURRENTLY DOWN! ***"),
                "NVDA", "NVDA", "news unavailable",
            ),
            VendorUnavailableError,
        )

    def test_yfinance_data_exception_is_a_retired_endpoint_not_a_throttle(self):
        # The retired endpoint must not read as "try again later": a retry can
        # never succeed, and telling the analyst to retry hides a permanent
        # vendor failure behind an apparently temporary one.
        result = yn._classify_news_failure(
            yn.YFDataException("*** YAHOO! FINANCE IS CURRENTLY DOWN! ***"),
            "NVDA", "NVDA", "news unavailable",
        )
        self.assertNotIsInstance(result, VendorRateLimitError)
        self.assertIn("retired", str(result))

    def test_yfinance_missing_data_subclasses_stay_absence(self):
        # These derive from YFException, not YFDataException: real absence.
        for exc in (yn.yf.exceptions.YFPricesMissingError("X", "no prices"),
                    yn.yf.exceptions.YFTickerMissingError("X", "no such ticker")):
            with self.subTest(exc=type(exc).__name__):
                self.assertIsInstance(
                    yn._classify_news_failure(exc, "NVDA", "NVDA", "news unavailable"),
                    NoMarketDataError,
                )

    def test_curl_cffi_transport_errors_are_transient(self):
        # yfinance 1.x uses curl_cffi, whose exceptions are NOT subclasses of
        # requests'. Seen live on 2026-11-05: a curl (28) timeout otherwise
        # fell through to "the symbol may be invalid".
        import curl_cffi.requests.exceptions as ce

        for exc in (ce.Timeout("curl: (28) Connection timed out"),
                    ce.ReadTimeout("curl: (28) Connection timed out"),
                    ce.ConnectionError("curl: (7) Failed to connect")):
            with self.subTest(exc=type(exc).__name__):
                self.assertIsInstance(
                    yn._classify_news_failure(exc, "NVDA", "NVDA", "news unavailable"),
                    VendorRateLimitError,
                )

    def test_transient_http_error_without_response_is_not_misclassified(self):
        # A bare HTTPError has no status to read; it must degrade to the old
        # behaviour rather than raise.
        self.assertIsInstance(
            yn._classify_news_failure(
                requests.exceptions.HTTPError("boom"), "NVDA", "NVDA", "news unavailable"
            ),
            NoMarketDataError,
        )


class RouteToVendorNewsTest(unittest.TestCase):
    """End-to-end through the unchanged router: type -> message."""

    def test_outage_does_not_blame_the_instrument(self):
        for exc in (
            requests.exceptions.ReadTimeout("read timed out"),
            requests.exceptions.ConnectionError("curl: (28) timed out"),
            _http_error(500, "Internal Server Error"),
            _http_error(429, "Too Many Requests"),
        ):
            with self.subTest(exc=type(exc).__name__):
                msg = _route_with_failure(exc)
                self.assertTrue(msg.startswith("DATA_UNAVAILABLE"), msg)
                self.assertIn("says nothing about the instrument", msg)
                self.assertNotIn("may be invalid", msg)
                self.assertNotIn("delisted", msg)

    def test_auth_failure_does_not_abort_the_run(self):
        # Vendors must raise VendorRateLimitError here: VendorNotConfiguredError
        # would be re-raised by route_to_vendor (news is a core category with a
        # single vendor) and would end the run.
        for status in (401, 403):
            with self.subTest(status=status):
                msg = _route_with_failure(_http_error(status, "Forbidden"))
                self.assertTrue(msg.startswith("DATA_UNAVAILABLE"), msg)
                self.assertNotIn("may be invalid", msg)

    def test_missing_symbol_still_reports_absence(self):
        msg = _route_with_failure(_http_error(404, "Not Found"))
        self.assertTrue(msg.startswith("NO_DATA_AVAILABLE"), msg)

    def test_empty_feed_is_still_a_real_absence(self):
        class _Ticker:
            def __init__(self, symbol):
                pass

            def get_news(self, count=0):
                return []

        with patch.object(yn.yf, "Ticker", _Ticker), \
             patch.object(yn, "coverage_gap", return_value=None), \
             _yfinance_only():
            msg = iface.route_to_vendor("get_news", "NVDA", START, END)
        self.assertTrue(msg.startswith("No news found"), msg)


if __name__ == "__main__":
    unittest.main()
