"""Tests that empty vendor results never become fabricated data.

Covers two systematic fixes:
  - load_ohlcv must not cache an empty download (cache poisoning), and must
    raise NoMarketDataError instead of returning an empty frame.
  - route_to_vendor must convert NoMarketDataError into a single explicit
    "NO_DATA_AVAILABLE" sentinel after all vendors are exhausted.
"""

import unittest
from unittest import mock

import pandas as pd
import pytest

from tradingagents.dataflows import interface, stockstats_utils
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.errors import VendorNotConfiguredError, VendorRateLimitError
from tradingagents.dataflows.symbol_utils import NoMarketDataError


@pytest.mark.unit
class TestLoadOhlcvNoPoison:
    """Historical regression node retained: an empty download must never be
    cached and must be retried on the next call.

    The class/method identifier ``TestLoadOhlcvNoPoison::test_empty_download_raises_and_does_not_cache``
    is preserved (it was the original regression node), now implemented as a
    regular pytest method with a per-test ``tmp_path`` cache dir (no shared
    ``tests/_tmp_cache``) and a mocked ``stockstats_utils.vendor_reachable`` so
    no real network probe is made. Both the genuine no-data case
    (reachable=True -> ``NoMarketDataError``) and the outage case
    (reachable=False -> ``VendorRateLimitError``) are exercised, so the
    outage-vs-no-data distinction in production is preserved (NFR-OFF-001).
    """

    @pytest.mark.parametrize(
        "reachable, expected",
        [(True, NoMarketDataError), (False, VendorRateLimitError)],
    )
    def test_empty_download_raises_and_does_not_cache(
        self, tmp_path, empty_frame, reachable, expected
    ):
        set_config({"data_cache_dir": str(tmp_path)})

        # First call: empty download, reachability mocked -> the correct error.
        with mock.patch.object(stockstats_utils.yf, "download", return_value=empty_frame), \
                mock.patch.object(stockstats_utils, "vendor_reachable", return_value=reachable), \
                pytest.raises(expected):
            stockstats_utils.load_ohlcv("FAKE", "2026-01-01")
        # Nothing should have been written to the cache.
        assert list(tmp_path.iterdir()) == [], "an empty download must never be cached"

        # A second call must re-attempt the fetch (no poisoned cache served).
        with mock.patch.object(stockstats_utils.yf, "download", return_value=empty_frame) as dl2, \
                mock.patch.object(stockstats_utils, "vendor_reachable", return_value=reachable), \
                pytest.raises(expected):
            stockstats_utils.load_ohlcv("FAKE", "2026-01-01")
        assert dl2.called
        assert list(tmp_path.iterdir()) == [], "an empty download must never be cached"


@pytest.mark.unit
class TestRouteToVendorSentinel(unittest.TestCase):
    def setUp(self):
        # The configured chain, not the installed vendor list, decides who is
        # asked: pin the default so a previous test's set_config cannot shrink
        # the chain under these assertions.
        set_config({"data_vendors": {"core_stock_apis": "yfinance,alpha_vantage"}})

    def tearDown(self):
        set_config({"data_vendors": {"core_stock_apis": "yfinance,alpha_vantage"}})

    def test_no_data_from_all_vendors_returns_sentinel(self):
        def raises_no_data(symbol, *a, **k):
            raise NoMarketDataError(symbol, "GC=F", "no rows")

        patched = {"yfinance": raises_no_data, "alpha_vantage": raises_no_data}
        with mock.patch.dict(
            interface.VENDOR_METHODS, {"get_stock_data": patched}, clear=False
        ):
            result = interface.route_to_vendor(
                "get_stock_data", "XAUUSD+", "2026-01-01", "2026-01-10"
            )
        self.assertIn("NO_DATA_AVAILABLE", result)
        self.assertIn("XAUUSD+", result)
        self.assertIn("GC=F", result)
        self.assertIn("Do not estimate", result)
        # Every source confirmed the absence, and the verdict says which.
        self.assertIn("yfinance", result)
        self.assertIn("alpha_vantage", result)
        self.assertNotIn("DATA_UNAVAILABLE", result)

    def test_all_vendors_no_data_ignores_the_unselected_ones(self):
        # Only the configured chain's confirmation counts: an unselected vendor
        # is never called and never part of the claim (#988).
        set_config({"data_vendors": {"core_stock_apis": "yfinance"}})

        def raises_no_data(symbol, *a, **k):
            raise NoMarketDataError(symbol, symbol, "no rows")

        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {
                "get_stock_data": {
                    "yfinance": raises_no_data,
                    "alpha_vantage": mock.Mock(
                        side_effect=AssertionError("unconfigured vendor was called")
                    ),
                },
            },
            clear=False,
        ):
            result = interface.route_to_vendor(
                "get_stock_data", "FAKE", "2026-01-01", "2026-01-10"
            )
        self.assertIn("NO_DATA_AVAILABLE", result)
        self.assertIn("yfinance", result)
        self.assertNotIn("alpha_vantage", result)

    def test_unconfigured_fallback_does_not_mask_no_data(self):
        # OLD EXPECTATION (changed in the vendor-classification batch): this
        # returned NO_DATA_AVAILABLE, i.e. "the symbol is invalid/delisted",
        # whenever yfinance reported no rows -- even though alpha_vantage could
        # not be asked at all (no key). That asserted an absence nobody
        # confirmed: one vendor's empty result plus one unavailable vendor is
        # not evidence about the symbol (#989 reasoning applied to absence).
        # The old test passed a plain ValueError, which is not how a missing key
        # presents itself; VendorNotConfiguredError is.
        def raises_no_data(symbol, *a, **k):
            raise NoMarketDataError(symbol, symbol, "no rows")

        def raises_unconfigured(symbol, *a, **k):
            raise VendorNotConfiguredError("ALPHA_VANTAGE_API_KEY environment variable is not set.")

        patched = {"yfinance": raises_no_data, "alpha_vantage": raises_unconfigured}
        with mock.patch.dict(
            interface.VENDOR_METHODS, {"get_stock_data": patched}, clear=False
        ), self.assertLogs("tradingagents.dataflows.interface", level="WARNING") as logs, \
                self.assertRaises(VendorNotConfiguredError) as caught:
            # Core data raises the typed error (a missing key is actionable and
            # an absence must not downgrade it); either way the result is never
            # a confirmed absence, i.e. never "the symbol is invalid/delisted".
            interface.route_to_vendor(
                "get_stock_data", "FAKE", "2026-01-01", "2026-01-10"
            )

        self.assertEqual(caught.exception.vendor, "alpha_vantage")
        self.assertEqual(caught.exception.absent_vendors, ("yfinance",))
        # The absence is still recorded, so a caller can tell "no rows" from
        # "never asked"; nothing anywhere claims the symbol is invalid.
        joined = "\n".join(logs.output)
        self.assertNotIn("NO_DATA_AVAILABLE", joined)
        self.assertNotIn("delisted", joined)
        self.assertNotIn("may be invalid", joined)
        # Both halves of the picture are logged: what was searched, and why the
        # other source could not be asked.
        self.assertIn("yfinance", joined)
        self.assertIn("alpha_vantage", joined)
        self.assertIn("not configured", joined)
        self.assertIn("also returned no usable data", joined)


if __name__ == "__main__":
    unittest.main()


def test_empty_download_makes_no_real_network_probe(cache_dir, empty_frame):
    """The reachability probe is mocked, so no real socket attempt is made.

    Guards NFR-OFF-001: an unmocked ``vendor_reachable`` would probe Yahoo
    (and, under strict socket denial, raise ``VendorRateLimitError`` instead of
    the intended ``NoMarketDataError``). Asserting the mock is called proves the
    no-data path uses the injected reachability answer rather than the network.
    """
    probe = mock.patch.object(stockstats_utils, "vendor_reachable", return_value=True)
    with mock.patch.object(stockstats_utils.yf, "download", return_value=empty_frame), probe as reach:
        with pytest.raises(NoMarketDataError):
            stockstats_utils.load_ohlcv("FAKE", "2026-01-01")
        assert reach.called, "empty-download path must consult the mocked reachability"


@pytest.fixture()
def empty_frame():
    return pd.DataFrame()

@pytest.fixture()
def cache_dir(tmp_path):
    set_config({"data_cache_dir": str(tmp_path)})
    return tmp_path
