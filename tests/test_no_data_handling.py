"""Tests that empty vendor results never become fabricated data.

Covers two systematic fixes:
  - load_ohlcv must not cache an empty download (cache poisoning), and must
    raise NoMarketDataError instead of returning an empty frame.
  - route_to_vendor must convert NoMarketDataError into a single explicit
    "NO_DATA_AVAILABLE" sentinel after all vendors are exhausted.
"""

import os
import unittest
from unittest import mock

import pandas as pd
import pytest

from tradingagents.dataflows import interface, stockstats_utils
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.errors import VendorNotConfiguredError
from tradingagents.dataflows.symbol_utils import NoMarketDataError


@pytest.mark.unit
class TestLoadOhlcvNoPoison(unittest.TestCase):
    def setUp(self):
        self._tmp = os.path.join(os.path.dirname(__file__), "_tmp_cache")
        os.makedirs(self._tmp, exist_ok=True)
        set_config({"data_cache_dir": self._tmp})

    def tearDown(self):
        for f in os.listdir(self._tmp):
            os.remove(os.path.join(self._tmp, f))
        os.rmdir(self._tmp)

    def test_empty_download_raises_and_does_not_cache(self):
        empty = pd.DataFrame()
        with mock.patch.object(stockstats_utils.yf, "download", return_value=empty), \
                self.assertRaises(NoMarketDataError):
            stockstats_utils.load_ohlcv("FAKE", "2026-01-01")
        # Nothing should have been written to the cache.
        self.assertEqual(os.listdir(self._tmp), [])

        # A second call must re-attempt the fetch (no poisoned cache served).
        with mock.patch.object(stockstats_utils.yf, "download", return_value=empty) as dl2:
            with self.assertRaises(NoMarketDataError):
                stockstats_utils.load_ohlcv("FAKE", "2026-01-01")
            self.assertTrue(dl2.called)


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
