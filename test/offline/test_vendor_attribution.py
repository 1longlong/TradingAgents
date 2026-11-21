"""A failure is attributed to the vendor that produced it, never to Yahoo by default.

``as_vendor_error`` classifies *network conditions* (timeout, 429, 401, 5xx), which
are vendor-neutral. Only the display name in the message is vendor-specific. Before
this batch the name was hardcoded to "Yahoo Finance" even though the router calls
the same classifier for alpha_vantage, sec_edgar and fred, so a FRED timeout was
logged and reported as "Yahoo Finance is unreachable".

Rules pinned here:

    as_vendor_error(exc, vendor)        -> message names ``vendor``, never Yahoo
    as_vendor_error(exc)                -> Yahoo only because yfinance is the
                                           project's default HTTP vendor
    YFRateLimitError                    -> still Yahoo (only yfinance raises it)
    router generic branch               -> classifies with the real vendor name,
                                           in both the log and the returned text

All vendors are stubbed through ``interface.VENDOR_METHODS``; the transport
exceptions are real ``requests`` classes. Nothing touches the network.
"""
import copy
import logging
from unittest import mock

import pytest
import requests

import tradingagents.dataflows.config as config_module
import tradingagents.default_config as default_config
from tradingagents.dataflows import interface
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.errors import (
    VendorAuthenticationError,
    VendorRateLimitError,
    VendorRequestRejectedError,
)
from tradingagents.dataflows.stockstats_utils import as_vendor_error

NON_YAHOO = "alpha_vantage"
ARGS = ("AAPL", "2026-01-01", "2026-01-10")


def _status_error(status):
    """A scrubbed-style HTTP error: the status survives in the message prefix."""
    return requests.HTTPError(f"{status} Client Error: refused for url: https://x/?k=***")


CASES = [
    pytest.param(requests.Timeout("read timed out"), VendorRateLimitError, "unreachable",
                 id="timeout"),
    pytest.param(requests.ConnectionError("refused"), VendorRateLimitError, "unreachable",
                 id="connection-reset"),
    pytest.param(_status_error(429), VendorRateLimitError, "rate limit", id="429"),
    pytest.param(_status_error(401), VendorAuthenticationError, "credentials", id="401"),
    pytest.param(_status_error(403), VendorAuthenticationError, "credentials", id="403"),
    pytest.param(_status_error(400), VendorRequestRejectedError, "refused", id="400"),
    pytest.param(_status_error(404), VendorRequestRejectedError, "refused", id="404"),
    pytest.param(_status_error(500), VendorRateLimitError, "service error", id="500"),
    pytest.param(_status_error(503), VendorRateLimitError, "service error", id="503"),
]


@pytest.mark.unit
@pytest.mark.parametrize("exc,expected,phrase", CASES)
class TestClassifierNamesTheCallingVendor:
    def test_the_message_names_the_vendor_not_yahoo(self, exc, expected, phrase):
        err = as_vendor_error(exc, NON_YAHOO)
        assert isinstance(err, expected)
        message = str(err)
        assert NON_YAHOO in message
        assert phrase in message
        assert "Yahoo" not in message

    def test_the_vendor_label_is_attached_for_the_router(self, exc, expected, phrase):
        assert as_vendor_error(exc, NON_YAHOO).vendor == NON_YAHOO

    def test_without_a_label_the_default_is_retained(self, exc, expected, phrase):
        # Backward compatibility: direct Yahoo call sites may omit the label.
        message = str(as_vendor_error(exc))
        assert "Yahoo Finance" in message


@pytest.mark.unit
def test_the_yfinance_throttle_class_stays_yahoo_specific():
    """Only yfinance raises ``YFRateLimitError``, so it names itself."""
    from yfinance.exceptions import YFRateLimitError

    message = str(as_vendor_error(YFRateLimitError(), NON_YAHOO))
    assert "Yahoo Finance" in message


@pytest.mark.unit
def test_an_already_typed_error_keeps_its_own_wording_when_labelled():
    original = VendorRateLimitError(f"{NON_YAHOO} is unreachable; it was not retrieved")
    labelled = as_vendor_error(original, NON_YAHOO)
    assert labelled is original  # identity via with_vendor; wording untouched
    assert "Yahoo" not in str(labelled)


@pytest.fixture
def router_clean_config():
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)
    yield
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)


def _raises(exc):
    def impl(*a, **k):
        raise exc
    return impl


def _route(chain, vendors, category="core_stock_apis", method="get_stock_data"):
    set_config({"data_vendors": {category: ",".join(chain)}})
    with mock.patch.dict(interface.VENDOR_METHODS, {method: vendors}, clear=False):
        return interface.route_to_vendor(method, *ARGS)


@pytest.mark.unit
class TestRouterAttribution:
    """The router supplies the real vendor name to the vendor-neutral classifier."""

    @pytest.mark.parametrize("exc,expected,phrase", [
        (requests.Timeout("read timed out"), VendorRateLimitError, "unreachable"),
        (_status_error(429), VendorRateLimitError, "rate limit"),
        (_status_error(401), VendorAuthenticationError, "rejected the configured credentials"),
        (_status_error(500), VendorRateLimitError, "service error"),
    ], ids=["timeout", "429", "401", "500"])
    def test_optional_vendor_failures_never_name_yahoo(
        self, router_clean_config, exc, expected, phrase
    ):
        # Optional enrichment returns a sentinel instead of raising; both the
        # log and the returned text must attribute the failure to the real vendor.
        with self._logs() as logs:
            out = _route(
                ["fred"], {"fred": _raises(exc)},
                category="macro_data", method="get_macro_indicators",
            )
        assert out.startswith("DATA_UNAVAILABLE"), out
        assert "Yahoo" not in out
        assert phrase in out  # the real failure category survives
        joined = "\n".join(logs)
        assert "Yahoo" not in joined
        assert "fred" in joined

    @pytest.mark.parametrize("exc", [requests.Timeout("t"), _status_error(429)],
                             ids=["timeout", "429"])
    def test_the_throttle_verdict_names_the_real_vendor(self, router_clean_config, exc):
        # A timeout/429 is classified in the generic branch; the sentinel then
        # describes it, and that description must use the caller's vendor.
        out = _route(["alpha_vantage", "sec_edgar"],
                     {"alpha_vantage": _raises(exc), "sec_edgar": _raises(exc)})
        assert "Yahoo" not in out
        assert "alpha_vantage" in out and "sec_edgar" in out

    def test_a_rejected_key_is_raised_without_a_yahoo_label(self, router_clean_config):
        with pytest.raises(VendorAuthenticationError) as caught:
            _route([NON_YAHOO], {NON_YAHOO: _raises(_status_error(401))})
        message = str(caught.value)
        assert NON_YAHOO in message
        assert "Yahoo" not in message
        assert caught.value.vendor == NON_YAHOO

    @staticmethod
    def _logs():
        return _CaptureLogs()


class _CaptureLogs:
    """Context manager collecting router warning records (no pytest capture needed)."""

    def __enter__(self):
        self.records = []
        self._handler = logging.Handler()
        self._handler.emit = self.records.append
        self._logger = logging.getLogger("tradingagents.dataflows.interface")
        self._level = self._logger.level
        self._logger.addHandler(self._handler)
        self._logger.setLevel(logging.WARNING)
        return self

    def __exit__(self, *exc_info):
        self._logger.removeHandler(self._handler)
        self._logger.setLevel(self._level)
        return False

    def __iter__(self):
        return iter(record.getMessage() for record in self.records)
