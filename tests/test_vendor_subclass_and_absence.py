"""Subclass semantics and absence propagation through the router.

Two defects fixed in this round, pinned here:

1. The verdict categorised exceptions by ``type(exc).__name__``, so a vendor's
   thin subclass -- the real ``AlphaVantageAuthenticationError``,
   ``AlphaVantageRateLimitError``, ``AlphaVantageNotConfiguredError``,
   ``FredNotConfiguredError`` -- was filed as "unknown". Classification is now
   by inheritance, so a subclass always inherits its base's verdict semantics.

2. An absence returned early from ``route_to_vendor`` and bypassed the core
   contract, so "vendor A reports no data + vendor B rejects the key" came back
   as plain DATA_UNAVAILABLE text. The router now decides what must be raised
   *before* building an absence/degraded sentence:
     - core + auth / refused / internal error  -> raised (typed, or the bug)
     - core + unconfigured                     -> raised (missing setup)
     - core + outage/throttle + absence        -> explicit "not confirmed" text
     - optional + anything + absence           -> sentinel naming both sides
   The absence sources are kept (``VendorError.absent_vendors``) so raising one
   error never hides that the symbol was also searched elsewhere.

All vendors are stubbed through ``interface.VENDOR_METHODS``; the transport
error is a real ``requests`` exception. Nothing touches the network.
"""
import copy
import logging
from unittest import mock

import pytest
import requests

import tradingagents.dataflows.config as config_module
import tradingagents.default_config as default_config
from tradingagents.dataflows import interface
from tradingagents.dataflows.alpha_vantage_common import (
    AlphaVantageAuthenticationError,
    AlphaVantageNotConfiguredError,
    AlphaVantageRateLimitError,
)
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.errors import (
    NoMarketDataError,
    VendorAuthenticationError,
    VendorNotConfiguredError,
    VendorRateLimitError,
    VendorRequestRejectedError,
)
from tradingagents.dataflows.fred import FredNotConfiguredError

A, B = "yfinance", "alpha_vantage"
ARGS = ("AAPL", "2026-01-01", "2026-01-10")


@pytest.fixture
def clean_config():
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)
    yield
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)


def _raises(exc):
    def impl(*a, **k):
        raise exc
    return impl


def _no_data():
    return NoMarketDataError("AAPL", "AAPL", "no rows in range")


def _route(chain, vendors, category="core_stock_apis", method="get_stock_data"):
    # Reset first: set_config merges nested dicts one level, so a key left by a
    # previous call would otherwise keep an extra vendor in this chain.
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)
    set_config({"data_vendors": {category: ",".join(chain)}})
    with mock.patch.dict(interface.VENDOR_METHODS, {method: vendors}, clear=False):
        return interface.route_to_vendor(method, *ARGS)


# ---------------------------------------------------------------------------
# 1. Subclass classification
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubclassesInheritTheirBaseSemantics:
    @pytest.mark.parametrize("exc,kind", [
        (AlphaVantageAuthenticationError("401"), "auth"),
        (AlphaVantageRateLimitError("429"), "unavailable"),
        (AlphaVantageNotConfiguredError("no key"), "not_configured"),
        (FredNotConfiguredError("no key"), "not_configured"),
    ], ids=lambda v: type(v).__name__ if isinstance(v, BaseException) else str(v))
    def test_real_vendor_subclasses_are_not_unknown(self, exc, kind):
        assert interface._kind(exc) == kind

    def test_the_base_types_are_unchanged(self):
        assert interface._kind(VendorAuthenticationError("x")) == "auth"
        assert interface._kind(VendorRateLimitError("x")) == "unavailable"
        assert interface._kind(VendorNotConfiguredError("x")) == "not_configured"
        assert interface._kind(VendorRequestRejectedError("x")) == "rejected"

    def test_a_plain_bug_is_still_unknown(self):
        assert interface._kind(KeyError("totalRevenue")) == "unknown"

    def test_the_most_specific_base_wins_for_a_diamond_subclass(self):
        class Both(VendorAuthenticationError, VendorRateLimitError):
            pass

        # auth is ranked above unavailable; the order of the MRO decides.
        assert interface._kind(Both("x")) == "auth"


@pytest.mark.unit
class TestSubclassFailuresThroughTheRouter:
    """The router's verdicts must reflect the subclass semantics, not "unknown"."""

    def test_an_alpha_vantage_auth_subclass_raises_as_auth(self, clean_config):
        for order in ((_raises(AlphaVantageAuthenticationError("401")), _raises(_no_data())),
                      (_raises(_no_data()), _raises(AlphaVantageAuthenticationError("401")))):
            with pytest.raises(VendorAuthenticationError):
                _route([A, B], dict(zip([A, B], order, strict=True)))

    def test_an_alpha_vantage_rate_limit_subclass_is_a_degradable_outage(self, clean_config):
        out = _route(
            ["fred", "alpha_vantage"],
            {
                "fred": _raises(_no_data()),
                "alpha_vantage": _raises(AlphaVantageRateLimitError("429")),
            },
            category="macro_data", method="get_macro_indicators",
        )
        assert out.startswith("DATA_UNAVAILABLE")
        assert "not a confirmed absence" in out
        # Classified as an outage, not misfiled as an unexpected error.
        assert "AlphaVantageRateLimitError (429 [unavailable])" in out
        assert "[unknown]" not in out

    def test_an_alpha_vantage_config_subclass_raises_as_unconfigured(self, clean_config):
        with pytest.raises(VendorNotConfiguredError):
            _route([B], {
                B: _raises(AlphaVantageNotConfiguredError("ALPHA_VANTAGE_API_KEY is not set."))
            })

    def test_a_fred_config_subclass_is_reported_through_the_optional_sentinel(self, clean_config):
        out = _route(
            ["fred"], {"fred": _raises(FredNotConfiguredError("FRED_API_KEY is not set."))},
            category="macro_data", method="get_macro_indicators",
        )
        # A sole vendor's config error is raised (unchanged contract) even in
        # the optional category, so the setup problem is not hidden.
        assert out.startswith("DATA_UNAVAILABLE")

    def test_a_subclass_keeps_its_type_when_it_is_the_sole_failure(self, clean_config):
        err = AlphaVantageAuthenticationError("401")
        with pytest.raises(AlphaVantageAuthenticationError):
            _route([B], {B: _raises(err)})


# ---------------------------------------------------------------------------
# 2. An absence never downgrades a required core error
# ---------------------------------------------------------------------------

RAISING = {
    "auth": lambda: AlphaVantageAuthenticationError("HTTP 401: invalid API key"),
    "unconfigured": lambda: AlphaVantageNotConfiguredError("ALPHA_VANTAGE_API_KEY is not set."),
    "rejected": lambda: VendorRequestRejectedError("HTTP 404: not found"),
    "internal": lambda: KeyError("totalRevenue"),
}

EXPECTED_TYPE = {
    "auth": VendorAuthenticationError,
    "unconfigured": VendorNotConfiguredError,
    "rejected": VendorRequestRejectedError,
    "internal": KeyError,
}


@pytest.mark.unit
@pytest.mark.parametrize("name", list(RAISING))
class TestCoreAbsencePlusRequiredErrorRaises:
    def test_both_orders_raise_instead_of_degrading(self, clean_config, name):
        failing = _raises(RAISING[name]())
        absent = _raises(_no_data())
        for order in ((absent, failing), (failing, absent)):
            with pytest.raises(EXPECTED_TYPE[name]):
                _route([A, B], dict(zip([A, B], order, strict=True)))

    def test_the_absence_sources_are_not_lost(self, clean_config, name):
        failing = _raises(RAISING[name]())
        absent = _raises(_no_data())
        for order in ((absent, failing), (failing, absent)):
            with pytest.raises(EXPECTED_TYPE[name]) as caught:
                _route([A, B], dict(zip([A, B], order, strict=True)))
            if name != "internal":
                # The typed error records which vendor(s) had already said "no data".
                assert caught.value.absent_vendors == (A if order[0] is absent else B,)

    def test_the_returned_text_never_claims_a_confirmed_absence(self, clean_config, name):
        # Whatever happens, NO_DATA_AVAILABLE must not appear for this pair.
        failing = _raises(RAISING[name]())
        absent = _raises(_no_data())
        try:
            out = _route([A, B], dict(zip([A, B], [absent, failing], strict=True)))
        except BaseException as exc:  # noqa: BLE001 - either outcome is acceptable
            assert "NO_DATA_AVAILABLE" not in str(exc)
        else:
            assert "NO_DATA_AVAILABLE" not in out


@pytest.mark.unit
class TestCoreAbsencePlusTransientStillDegrades:
    @pytest.mark.parametrize("transient,cause", [
        (requests.Timeout("read timed out"), "read timed out"),
        (VendorRateLimitError("HTTP 429"), "HTTP 429"),
        (requests.ConnectionError("refused"), "refused"),
    ], ids=["timeout", "429", "connection"])
    def test_an_unconfirmed_absence_is_explicit(self, clean_config, transient, cause):
        failing = _raises(transient)
        absent = _raises(_no_data())
        for order in ((absent, failing), (failing, absent)):
            out = _route([A, B], dict(zip([A, B], order, strict=True)))
            assert out.startswith("DATA_UNAVAILABLE")
            assert "NO_DATA_AVAILABLE" not in out
            assert "not a confirmed absence" in out
            # Names the absent vendor, the failing vendor, its category and cause.
            absent_vendor, failing_vendor = (
                (A, B) if order[0] is absent else (B, A)
            )
            assert absent_vendor in out and failing_vendor in out
            assert f"{failing_vendor}: " in out and cause in out
            assert "[unavailable]" in out
            assert "may be invalid" not in out

    def test_the_absence_and_failure_vendors_are_never_conflated(self, clean_config):
        out = _route(
            [A, B],
            {A: _raises(_no_data()), B: _raises(requests.Timeout("read timed out"))},
        )
        # The absence belongs to yfinance and the outage to alpha_vantage; the
        # sentence must not say alpha_vantage "returned no usable data".
        assert "Vendor(s) yfinance returned no usable data" in out
        assert "alpha_vantage returned no usable data" not in out


@pytest.mark.unit
class TestMixedAbsenceVerdictsAreOrderStable:
    @pytest.mark.parametrize("failure", [
        lambda *a, **k: (_ for _ in ()).throw(requests.Timeout("read timed out")),
        lambda *a, **k: (_ for _ in ()).throw(VendorRateLimitError("HTTP 429")),
    ], ids=["timeout", "throttle"])
    def test_reversing_the_chain_keeps_both_facts(self, clean_config, failure):
        absent = _raises(_no_data())
        outputs = []
        for first, second in ((absent, failure), (failure, absent)):
            out = _route(
                ["fred", "fred_backup"],
                {"fred": first, "fred_backup": second},
                category="macro_data", method="get_macro_indicators",
            )
            assert "not a confirmed absence" in out
            assert "[unavailable]" in out
            outputs.append(out)
        assert outputs[0] != outputs[1]  # the vendor names are in chain order
        for out in outputs:
            assert "fred" in out and "fred_backup" in out


@pytest.mark.unit
class TestOptionalAbsencePlusFailureDegrades:
    @pytest.mark.parametrize("name", list(RAISING))
    def test_the_sentinel_names_the_absence_and_the_failure(self, clean_config, name):
        failing = _raises(RAISING[name]())
        absent = _raises(_no_data())
        for order in ((absent, failing), (failing, absent)):
            out = _route(
                ["fred", "fred_backup"],
                dict(zip(["fred", "fred_backup"], order, strict=True)),
                category="macro_data", method="get_macro_indicators",
            )
            assert out.startswith("DATA_UNAVAILABLE"), out
            assert "NO_DATA_AVAILABLE" not in out
            assert "not a confirmed absence" in out
            assert "fred" in out and "fred_backup" in out
            # The failing side keeps its type and its real cause; the cause is
            # listed under "Failures in the chain", which does not claim that
            # *all* vendors failed (one reported an absence).
            cause = RAISING[name]()
            assert type(cause).__name__ in out
            assert str(cause) in out


@pytest.mark.unit
class TestAbsenceDoesNotStopASuccess:
    @pytest.mark.parametrize("name", list(RAISING))
    def test_a_later_vendor_success_returns_normally(self, clean_config, name):
        failing = _raises(RAISING[name]())
        absent = _raises(_no_data())

        def ok(*a, **k):
            return "DATA"

        for order in ((absent, failing, ok), (failing, absent, ok)):
            out = _route(
                [A, B, "sec_edgar"], dict(zip([A, B, "sec_edgar"], order, strict=True))
            )
            assert out == "DATA"

    def test_absence_then_success_is_not_text(self, clean_config):
        out = _route([A, B], {A: _raises(_no_data()), B: lambda *a, **k: "DATA"})
        assert out == "DATA"


@pytest.mark.unit
def test_the_mixed_log_names_the_real_failure(clean_config):
    records = []
    handler = logging.Handler()
    handler.emit = records.append
    logger = logging.getLogger("tradingagents.dataflows.interface")
    logger.addHandler(handler)
    level = logger.level
    logger.setLevel(logging.WARNING)
    try:
        _route([A, B], {A: _raises(_no_data()), B: _raises(requests.Timeout("read timed out"))})
    finally:
        logger.removeHandler(handler)
        logger.setLevel(level)
    joined = "\n".join(r.getMessage() for r in records)
    assert "no data from yfinance" in joined
    assert "alpha_vantage" in joined
    # The cause survives classification (a Timeout is normalised to an outage,
    # so the class name is not asserted; the message is).
    assert "read timed out" in joined
