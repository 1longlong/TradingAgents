"""Stage 4 — news vendor failures must be classified, not lumped together.

A single ``NoMarketDataError`` for every failure told the analyst "the symbol
may be invalid, delisted, not covered, or stale" even when the vendor was simply
down. The router already reacts by exception *type*; these tests pin the
mapping so a transient failure can never again be reported as a fact about the
instrument, and so a 401/403 can never abort the run.

The classification itself now lives inside each provider adapter
(``finnhub_news._classify_http`` / ``gdelt_news._classify_http``), which is what
``ClassifyNewsFailureTest`` pins.
"""

import unittest
from unittest.mock import patch

from tradingagents.dataflows import finnhub_news as fn, interface as iface
from tradingagents.dataflows.errors import (
    NoMarketDataError,
    VendorRateLimitError,
)
from tradingagents.dataflows.news_status import NewsStatus

START, END = "2026-09-16", "2026-09-23"


def _classify(status, error_kind=""):
    return fn._classify_http(status, error_kind)


def _yfinance_only():
    """Pin ``get_news`` to one controlled vendor that raises the error under test.

    These tests pin how the *router* classifies a vendor failure end to end.
    They originally pinned yfinance, but Yahoo's news endpoint was retired
    (HTTP 404) and its news path removed in the Finnhub+GDELT migration, so it
    is no longer a registered ``get_news`` vendor. A throwaway vendor name is
    registered with a single callable, so the chain is exactly the behaviour
    under test and no real provider is contacted.
    """
    import copy

    import tradingagents.dataflows.config as config_module
    import tradingagents.default_config as default_config

    pinned = copy.deepcopy(default_config.DEFAULT_CONFIG)
    pinned.setdefault("tool_vendors", {})["get_news"] = "test_vendor"
    return patch.object(config_module, "_config", pinned)


def _with_news_vendor(func, *, keep: bool = False):
    """Register ``func`` as ``test_vendor`` for ``get_news`` for one call."""
    patcher = patch.dict(iface.VENDOR_METHODS["get_news"], {"test_vendor": func},
                         clear=not keep)
    return patcher


def _route_with_failure(exc: Exception) -> str:
    def _boom(*_args, **_kwargs):
        raise exc

    with _with_news_vendor(_boom), _yfinance_only():
        return iface.route_to_vendor("get_news", "NVDA", START, END)


class ClassifyNewsFailureTest(unittest.TestCase):
    """Each adapter classifies its own transport failure.

    The retired yfinance path did this inline in ``_classify_news_failure``.
    With the Finnhub + GDELT chain the classification lives in each adapter
    (``finnhub_news._classify_http`` / ``gdelt_news._classify_http``), so these
    cases pin *that* mapping: a transient failure must never read as a fact
    about the instrument, and a 401/403 must never abort the run.
    """

    def test_transient_failures_are_rate_limit_errors(self):
        # 429 is the one status that means "try later", and it maps to the
        # throttle class so the router can fail over to the next vendor.
        self.assertIs(_classify(429), NewsStatus.RATE_LIMITED)

    def test_timeouts_and_transport_errors_are_not_about_the_instrument(self):
        cases = {
            "timeout": _classify(None, "timeout"),
            "transport": _classify(None, "transport"),
            "http_500": _classify(500),
            "http_503": _classify(503),
            "http_502": _classify(502),
            "http_504": _classify(504),
        }
        all_news_classes = set(NewsStatus)
        for name, status in cases.items():
            with self.subTest(case=name):
                self.assertIsNotNone(status, f"{name} must classify as a failure")
                self.assertIn(status, all_news_classes)
                # Never an authoritative answer: an outage is not an absence.
                self.assertNotEqual(status, NewsStatus.EMPTY_VALID)

    def test_ok_status_classifies_as_success(self):
        self.assertIsNone(_classify(200))

    def test_auth_failures_are_invalid_credential_not_absence(self):
        for status in (401, 403):
            with self.subTest(status=status):
                self.assertIs(_classify(status), NewsStatus.AUTH_INVALID)

    def test_absence_remains_no_market_data(self):
        # A 404/410 is a fact about coverage, not an outage. GDELT maps 404 to
        # "endpoint not serving", never to a successful empty answer.
        for status in (404, 410):
            with self.subTest(status=status):
                classified = _classify(status)
                self.assertIsNotNone(classified)
                self.assertNotEqual(classified, NewsStatus.EMPTY_VALID)

    def test_unknown_status_is_an_http_error(self):
        self.assertIs(_classify(400), NewsStatus.HTTP_ERROR)
        self.assertIs(_classify(418), NewsStatus.HTTP_ERROR)

    def test_a_raw_transport_exception_never_escapes_the_adapter(self):
        # A transport bug raised *inside* the HTTP stack is classified by
        # ``_request`` itself: it must become a typed raise, never a bare
        # exception reaching the analyst as a crash.
        import urllib.error

        def _boom(*_a, **_k):
            raise RuntimeError("hiccup")

        with patch.object(urllib.request, "urlopen", side_effect=_boom):
            status, _body, kind = fn._request("https://finnhub.io/x")
        self.assertIsNone(status)
        self.assertEqual(kind, "transport")


class RouteToVendorNewsTest(unittest.TestCase):
    """End-to-end through the unchanged router: type -> message.

    A vendor adapter is responsible for *classifying* its transport failure: the
    router only understands the ``VendorError`` hierarchy. The retired yfinance
    path did that classification inline (``_classify_news_failure``), which is
    why these cases used to inject raw ``requests`` exceptions. With the
    Finnhub+GDELT chain the classification happens inside each adapter (see
    ``finnhub_news._classify_http``), so the router contract is pinned here with
    the types it actually receives. ``ClassifyNewsFailureTest`` still covers the
    legacy mapping for any caller that keeps using it.
    """

    def test_outage_does_not_blame_the_instrument(self):
        for exc in (
            VendorRateLimitError("read timed out"),
            VendorRateLimitError("curl: (28) timed out"),
            VendorRateLimitError("HTTP 500: Internal Server Error"),
            VendorRateLimitError("HTTP 429: Too Many Requests"),
        ):
            with self.subTest(exc=str(exc)):
                msg = _route_with_failure(exc)
                self.assertTrue(msg.startswith("DATA_UNAVAILABLE"), msg)
                self.assertIn("says nothing about the instrument", msg)
                self.assertNotIn("may be invalid", msg)
                self.assertNotIn("delisted", msg)

    def test_auth_failure_does_not_abort_the_run(self):
        # Vendors must raise VendorRateLimitError (or another VendorError the
        # router can fail over) here: VendorNotConfiguredError would be
        # re-raised by route_to_vendor (news is a core category with a single
        # vendor) and would end the run. Both Finnhub's 401 and 403 map to
        # AUTH_INVALID and are rendered, never raised as a config error.
        for status in (401, 403):
            with self.subTest(status=status):
                msg = _route_with_failure(
                    VendorRateLimitError(f"HTTP {status}: credential rejected")
                )
                self.assertTrue(msg.startswith("DATA_UNAVAILABLE"), msg)
                self.assertNotIn("may be invalid", msg)

    def test_missing_symbol_still_reports_absence(self):
        # A 404 is a fact about the symbol (no coverage), not an outage: it must
        # stay NoMarketDataError semantics through the router.
        def _not_found(*_a, **_k):
            raise NoMarketDataError("NVDA", "NVDA", "HTTP 404: not covered")

        with _with_news_vendor(_not_found), _yfinance_only():
            msg = iface.route_to_vendor("get_news", "NVDA", START, END)
        self.assertTrue(msg.startswith("NO_DATA_AVAILABLE"), msg)

    def test_empty_feed_is_still_a_real_absence(self):
        # A vendor that answers "no articles" must produce an absence, never an
        # outage sentinel and never invented news.
        with _with_news_vendor(
            lambda *a, **k: "No news found for NVDA between a and b"
        ), _yfinance_only():
            msg = iface.route_to_vendor("get_news", "NVDA", START, END)
        self.assertTrue(msg.startswith("No news found"), msg)


if __name__ == "__main__":
    unittest.main()
