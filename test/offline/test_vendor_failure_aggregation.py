"""Mixed-vendor failure attribution: an absence must be confirmed before claimed.

An empty result from one vendor is evidence about the symbol. A timeout, a
throttle, a rejected key or a missing key from another is evidence about the
*vendor*, and says nothing about the instrument. Before this batch the router
let any single ``NoMarketDataError`` win the chain verdict, so ``yfinance``
returning no rows plus ``alpha_vantage`` timing out reported
"NO_DATA_AVAILABLE ... may be invalid, delisted", and a 401 from the fallback
read as a delisted ticker.

The contract these tests pin, in chain-verdict order:

    all configured vendors confirmed an absence  -> NO_DATA_AVAILABLE
    absence mixed with outage/throttle/auth/config -> DATA_UNAVAILABLE, naming both
    every vendor throttled/unreachable            -> DATA_UNAVAILABLE (vendor's fault)
    a key was supplied and rejected (core)         -> VendorAuthenticationError raised
    a key was supplied and rejected (optional)     -> DATA_UNAVAILABLE (fix the key)
    a later configured vendor succeeded            -> its result, always
    unknown internal error (core category)         -> raised, never a sentinel
    unknown internal error (optional category)     -> DATA_UNAVAILABLE (existing contract)

Nothing here touches the network: vendors are replaced through
``interface.VENDOR_METHODS`` and transport failures are real exception types
from ``requests``.
"""
import copy
import logging
import unittest
from unittest import mock

import pytest
import requests

import tradingagents.dataflows.config as config_module
import tradingagents.default_config as default_config
from tradingagents.dataflows import interface
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.errors import (
    NoMarketDataError,
    VendorAuthenticationError,
    VendorNotConfiguredError,
    VendorRateLimitError,
)

METHOD = "get_stock_data"
ARGS = ("AAPL", "2026-01-01", "2026-01-10")
MACRO_METHOD = "get_macro_indicators"
MACRO_ARGS = ("cpi", "2026-06-01", 365)
MACRO_CATEGORY = "macro_data"


def _no_data(symbol=ARGS[0], *a, **k):
    raise NoMarketDataError(symbol, symbol, "no rows in range")


def _rate_limited(*a, **k):
    raise VendorRateLimitError("HTTP 429")


def _timeout(*a, **k):
    raise requests.Timeout("read timed out after 30s")


def _connection_refused(*a, **k):
    raise requests.ConnectionError("Failed to establish a new connection")


def _auth_rejected(*a, **k):
    raise VendorAuthenticationError("HTTP 401: invalid API key")


def _unconfigured(*a, **k):
    raise VendorNotConfiguredError("ALPHA_VANTAGE_API_KEY environment variable is not set.")


def _returns(value):
    def impl(*a, **k):
        return value
    return impl


def _boom(*a, **k):
    raise KeyError("totalRevenue")  # an internal bug, not a vendor condition


class _RouterCase(unittest.TestCase):
    """Run one call with a stubbed vendor chain and a clean global config."""

    def setUp(self):
        config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)

    def tearDown(self):
        config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)

    def route(self, chain, vendors, method=METHOD, args=ARGS, category="core_stock_apis"):
        set_config({"data_vendors": {category: ",".join(chain)}})
        with mock.patch.dict(interface.VENDOR_METHODS, {method: vendors}, clear=False):
            return interface.route_to_vendor(method, *args)


@pytest.mark.unit
class AllSourcesAbsentTests(_RouterCase):
    def test_1a_all_sources_explicitly_report_no_data(self):
        out = self.route(["yfinance", "alpha_vantage"],
                         {"yfinance": _no_data, "alpha_vantage": _no_data})
        assert out.startswith("NO_DATA_AVAILABLE")
        # It is safe to name the symbol as the reason, and to say which sources agree.
        assert "may be invalid" in out and "yfinance" in out and "alpha_vantage" in out

    def test_1b_single_source_absence_is_still_confirmed(self):
        out = self.route(["yfinance"], {"yfinance": _no_data})
        assert out.startswith("NO_DATA_AVAILABLE")

    def test_1c_canonical_symbol_and_detail_still_surface(self):
        def _gc(*a, **k):
            raise NoMarketDataError("XAUUSD+", "GC=F", "no rows in range")
        out = self.route(["yfinance", "alpha_vantage"], {"yfinance": _gc, "alpha_vantage": _gc})
        assert "XAUUSD+" in out and "GC=F" in out and "no rows in range" in out

    def test_1d_a_later_vendor_success_ends_the_search(self):
        vendor_after = mock.Mock(side_effect=_returns("AV_DATA"))
        out = self.route(
            ["yfinance", "alpha_vantage", "sec_edgar"],
            {"yfinance": _no_data, "alpha_vantage": _returns("AV_DATA"), "sec_edgar": vendor_after},
        )
        assert out == "AV_DATA"
        vendor_after.assert_not_called()


@pytest.mark.unit
class AbsenceMixedWithFailureTests(_RouterCase):
    def assert_mixed(self, out, *, absent="yfinance", failing="alpha_vantage", cause):
        assert out.startswith("DATA_UNAVAILABLE"), out
        assert "NO_DATA_AVAILABLE" not in out
        # Must not assert an absence it did not confirm ...
        assert "may be invalid" not in out
        assert "delisted" not in out
        # ... and must state both halves.
        assert absent in out and failing in out
        assert cause in out
        assert "not a confirmed absence" in out

    def test_2_one_source_absent_another_times_out(self):
        out = self.route(["yfinance", "alpha_vantage"],
                         {"yfinance": _no_data, "alpha_vantage": _timeout})
        self.assert_mixed(out, cause="read timed out")

    def test_2b_a_connection_error_is_not_an_absence_either(self):
        out = self.route(["yfinance", "alpha_vantage"],
                         {"yfinance": _no_data, "alpha_vantage": _connection_refused})
        self.assert_mixed(out, cause="Failed to establish a new connection")

    def test_3_one_source_absent_another_rate_limited(self):
        out = self.route(["yfinance", "alpha_vantage"],
                         {"yfinance": _no_data, "alpha_vantage": _rate_limited})
        self.assert_mixed(out, cause="HTTP 429")

    def test_4a_one_source_absent_another_auth_failed_optional(self):
        # Core data must RAISE this pair (no absence may downgrade a rejected
        # key); optional data owns a sentinel contract, so it degrades here.
        out = self.route(
            ["fred", "fred_backup"],
            {"fred": _no_data, "fred_backup": _auth_rejected},
            method="get_macro_indicators", args=("cpi", "2026-06-01", 365),
            category="macro_data",
        )
        self.assert_mixed(out, absent="fred", failing="fred_backup",
                          cause="VendorAuthenticationError")

    def test_4b_one_source_absent_another_not_configured_optional(self):
        out = self.route(
            ["fred", "fred_backup"],
            {"fred": _no_data, "fred_backup": _unconfigured},
            method="get_macro_indicators", args=("cpi", "2026-06-01", 365),
            category="macro_data",
        )
        self.assert_mixed(out, absent="fred", failing="fred_backup",
                          cause="VendorNotConfiguredError")

    def test_4e_core_absent_plus_rejected_key_raises_not_degrades(self):
        with pytest.raises(VendorAuthenticationError) as caught:
            self.route(["yfinance", "alpha_vantage"],
                       {"yfinance": _no_data, "alpha_vantage": _auth_rejected})
        assert caught.value.absent_vendors == ("yfinance",)

    def test_4c_authentication_outranks_throttle_when_both_present(self):
        # A rejected key is the actionable cause. It must be named even when a
        # throttled vendor is in the chain (and an absence from a third).
        out = self.route(
            ["alpha_vantage", "sec_edgar"],
            {"alpha_vantage": _rate_limited, "sec_edgar": _auth_rejected},
            method="get_macro_indicators", args=("cpi", "2026-06-01", 365),
            category="macro_data",
        )
        assert out.startswith("DATA_UNAVAILABLE")
        assert "rejected the configured credentials" in out
        assert "sec_edgar" in out
        assert "alpha_vantage" in out

    def test_4c_absence_auth_throttle_optional_names_every_part(self):
        out = self.route(
            ["fred", "fred_backup", "fred_3"],
            {"fred": _no_data, "fred_backup": _rate_limited, "fred_3": _auth_rejected},
            method="get_macro_indicators", args=("cpi", "2026-06-01", 365),
            category="macro_data",
        )
        assert out.startswith("DATA_UNAVAILABLE")
        # An absence plus mixed failure categories is "not a confirmed absence",
        # and every side (absent vendor, both failure vendors) is named with its
        # own category tag and real cause.
        assert "not a confirmed absence" in out
        assert "no usable data" in out and "fred " in out
        assert "fred_backup: VendorRateLimitError (HTTP 429 [unavailable])" in out
        assert "fred_3: VendorAuthenticationError (HTTP 401: invalid API key [auth])" in out
        assert "NO_DATA_AVAILABLE" not in out

    def test_4c2_core_authentication_outranks_throttle_with_an_absence(self):
        with pytest.raises(VendorAuthenticationError) as caught:
            self.route(
                ["yfinance", "alpha_vantage", "sec_edgar"],
                {"yfinance": _no_data, "alpha_vantage": _rate_limited,
                 "sec_edgar": _auth_rejected},
            )
        assert caught.value.vendor == "sec_edgar"
        assert caught.value.absent_vendors == ("yfinance",)

    def test_4d_an_optional_category_gets_the_same_attribution(self):
        out = self.route(
            ["fred", "fred_backup"],
            {"fred": _no_data, "fred_backup": _timeout},
            method="get_macro_indicators",
            args=("cpi", "2026-06-01", 365),
            category="macro_data",
        )
        self.assert_mixed(out, absent="fred", failing="fred_backup",
                          cause="read timed out after 30s")


@pytest.mark.unit
class LaterSourceSuccessTests(_RouterCase):
    def test_5_a_failing_primary_does_not_stop_a_healthy_secondary(self):
        for failure in (_timeout, _rate_limited, _auth_rejected, _unconfigured):
            with self.subTest(failure=failure.__name__):
                out = self.route(["alpha_vantage", "yfinance"],
                                 {"alpha_vantage": failure, "yfinance": _returns("YF_DATA")})
                assert out == "YF_DATA"

    def test_5b_an_unknown_error_in_the_primary_does_not_stop_the_secondary(self):
        out = self.route(["alpha_vantage", "yfinance"],
                         {"alpha_vantage": _boom, "yfinance": _returns("YF_DATA")})
        assert out == "YF_DATA"

    def test_5c_the_unselected_vendor_is_never_called(self):
        never = mock.Mock(side_effect=AssertionError("unconfigured vendor was called"))
        out = self.route(["yfinance"], {"yfinance": _returns("YF_DATA"), "alpha_vantage": never})
        assert out == "YF_DATA"
        never.assert_not_called()


@pytest.mark.unit
class UnknownInternalErrorTests(_RouterCase):
    def test_6a_a_core_category_raises_instead_of_claiming_no_data(self):
        with pytest.raises(KeyError, match="totalRevenue"):
            self.route(["yfinance", "alpha_vantage"],
                       {"yfinance": _boom, "alpha_vantage": _boom})

    def test_6b_a_bug_next_to_an_absence_is_not_reported_as_an_absence(self):
        # Core raises the bug rather than degrading to any sentinel: an
        # absence from another vendor must not turn a bug into "unavailable".
        with pytest.raises(KeyError, match="totalRevenue"):
            self.route(["yfinance", "alpha_vantage"],
                       {"yfinance": _no_data, "alpha_vantage": _boom})

    def test_6c_the_optional_category_contract_is_unchanged(self):
        # Optional enrichment keeps degrading to a sentinel on an unknown error.
        out = self.route(
            ["fred"], {"fred": _boom},
            method="get_macro_indicators", args=("cpi", "2026-06-01", 365),
            category="macro_data",
        )
        assert out.startswith("DATA_UNAVAILABLE")
        assert "optional" in out and "macro_data" in out

    def test_6d_a_sole_supplied_but_rejected_key_is_actionable(self):
        # Core data: a rejected key is raised as the typed error, not returned
        # as text a caller could mistake for a normal tool result.
        with self.assertRaises(VendorAuthenticationError) as ctx:
            self.route(["alpha_vantage"], {"alpha_vantage": _auth_rejected})
        # Attributed to the vendor that rejected it, and typed so a caller
        # cannot confuse it with an outage or an absence.
        assert ctx.exception.vendor == "alpha_vantage"
        message = str(ctx.exception)
        assert "unreachable" not in message
        assert "NO_DATA_AVAILABLE" not in message

    def test_6d2_the_optional_category_keeps_the_sentinel_for_a_rejected_key(self):
        # Optional enrichment owns its own contract: it degrades rather than
        # raising, and names the credential problem so it is not read as an
        # absence or an outage.
        out = self.route(
            ["alpha_vantage"], {"alpha_vantage": _auth_rejected},
            method="get_macro_indicators", args=("cpi", "2026-06-01", 365),
            category="macro_data",
        )
        assert out.startswith("DATA_UNAVAILABLE")
        assert "rejected the configured credentials" in out
        assert "valid API key" in out
        assert "NO_DATA_AVAILABLE" not in out
        assert "unreachable" not in out

    def test_6e_a_throttled_chain_still_says_it_is_the_vendor(self):
        out = self.route(["yfinance", "alpha_vantage"],
                         {"yfinance": _rate_limited, "alpha_vantage": _timeout})
        assert out.startswith("DATA_UNAVAILABLE")
        assert "says nothing about the instrument" in out
        assert "NO_DATA_AVAILABLE" not in out


@pytest.mark.unit
class CompatibilityTests(_RouterCase):
    def test_8a_a_normal_return_is_passed_through_unchanged(self):
        data = "# Stock data\n"
        assert self.route(["yfinance"], {"yfinance": _returns(data)}) == data

    def test_8b_a_sole_unconfigured_vendor_still_surfaces_its_own_error(self):
        # Unchanged contract: with nothing else configured there is no vendor
        # to blame, so the typed configuration error is raised, not flattened.
        with pytest.raises(VendorNotConfiguredError):
            self.route(["alpha_vantage"], {"alpha_vantage": _unconfigured})

    def test_8c_an_unknown_configured_vendor_still_raises_value_error(self):
        set_config({"data_vendors": {"core_stock_apis": "bogus_vendor"}})
        with pytest.raises(ValueError, match="bogus_vendor"):
            interface.route_to_vendor(METHOD, *ARGS)

    def test_8d_vendor_is_attached_at_the_routing_boundary(self):
        seen = {}

        def _absent(*a, **k):
            err = NoMarketDataError(*a)
            seen["vendor_before_router"] = err.vendor
            raise err

        self.route(["yfinance", "alpha_vantage"], {"yfinance": _absent, "alpha_vantage": _no_data})
        assert seen["vendor_before_router"] is None  # vendors need not know themselves

    def test_8e_the_mixed_verdict_is_logged_with_its_cause(self):
        with self.assertLogs("tradingagents.dataflows.interface", level=logging.WARNING) as logs:
            self.route(["yfinance", "alpha_vantage"],
                       {"yfinance": _no_data, "alpha_vantage": _timeout})
        joined = "\n".join(logs.output)
        assert "Mixed vendor outcome" in joined
        assert "read timed out" in joined  # the raw detail stays in the log


@pytest.mark.unit
def test_vendor_errors_keep_raising_their_type():
    """A vendor that already classified its failure is not re-wrapped."""
    for exc in (VendorRateLimitError("x"), VendorAuthenticationError("x"),
                VendorNotConfiguredError("x"), NoMarketDataError("AAPL")):
        assert isinstance(exc.with_vendor("v"), type(exc))
