"""Multi-failure chains: no failure category is lost to which vendor came last.

A chain can fail for more than one reason at once (a timeout on one vendor and a
rejected key on another). Before this batch the verdict came from the last slot
of one kind, so "timeout then 401" and "401 then timeout" gave different answers
and one of the two facts disappeared.

Rules pinned here (see ``interface._RANK`` / ``_robust_verdict``):

  * every failure is recorded in chain order and named in the verdict;
  * when several categories coexist, the remaining ones are always listed,
    in a fixed precedence (auth > refused > outage > unconfigured > bug), so
    reversing the vendor order cannot hide a category;
  * a verdict is the same *set* of sentences for either order (the vendors
    inside the list are in chain order, which is the only intended difference);
  * a core category still raises the typed error per its contract, and the
    raised type is the most actionable one present (auth before unconfigured);
  * optional data degrades but states the real category and vendor;
  * a later vendor's success still returns normally;
  * the router log names every vendor failure with its real detail.

Vendors are stubbed through ``interface.VENDOR_METHODS``; transport errors are
real ``requests`` exceptions. Nothing touches the network.
"""
import copy
import logging
import re
from unittest import mock

import pytest
import requests

import tradingagents.dataflows.config as config_module
import tradingagents.default_config as default_config
from tradingagents.dataflows import interface
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.errors import (
    VendorAuthenticationError,
    VendorNotConfiguredError,
    VendorRateLimitError,
    VendorRequestRejectedError,
)

CORE = ("yfinance", "alpha_vantage")
ARGS = ("AAPL", "2026-01-01", "2026-01-10")


# --- vendor stubs -----------------------------------------------------------


def _timeout(*a, **k):
    raise requests.Timeout("read timed out")


def _throttle(*a, **k):
    raise VendorRateLimitError("throttled by the vendor")


def _auth(*a, **k):
    raise VendorAuthenticationError("HTTP 401: invalid API key")


def _rejected(*a, **k):
    raise VendorRequestRejectedError("HTTP 404: not found")


def _unconfigured(*a, **k):
    raise VendorNotConfiguredError("FYI_API_KEY is not set")


def _bug(*a, **k):
    raise KeyError("totalRevenue")


def _ok(*a, **k):
    return "OK"


# The four required pairs, as (first failure, second failure).
PAIRS = {
    "timeout+auth": (_timeout, _auth),
    "throttle+rejected": (_throttle, _rejected),
    "transient+internal": (_throttle, _bug),
    "auth+unconfigured": (_auth, _unconfigured),
}


@pytest.fixture
def clean_config():
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)
    yield
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)


class _CaptureLogs:
    def __enter__(self):
        self.records = []
        handler = logging.Handler()
        handler.emit = self.records.append
        self._logger = logging.getLogger("tradingagents.dataflows.interface")
        self._level = self._logger.level
        self._logger.addHandler(handler)
        self._logger.setLevel(logging.WARNING)
        return self

    def __exit__(self, *exc_info):
        self._logger.setLevel(self._level)
        self._logger.removeHandler(self._logger.handlers[-1])
        return False

    @property
    def text(self):
        return "\n".join(r.getMessage() for r in self.records)


def _route(chain, vendors, category="core_stock_apis", method="get_stock_data"):
    # set_config merges nested dicts one level, so reset first: a key left by a
    # previous call would otherwise keep an extra vendor in this chain.
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)
    set_config({"data_vendors": {category: ",".join(chain)}})
    with mock.patch.dict(interface.VENDOR_METHODS, {method: vendors}, clear=False):
        return interface.route_to_vendor(method, *ARGS)


def _run(order, category="core_stock_apis", method="get_stock_data"):
    """Route a two-vendor chain and return (result or raised error, log text)."""
    with _CaptureLogs() as logs:
        try:
            result = _route(
                CORE, dict(zip(CORE, order, strict=True)), category=category, method=method
            )
        except BaseException as exc:  # noqa: BLE001 - the raised type is the subject
            return exc, logs.text
    return result, logs.text


# --- core category ----------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("name", list(PAIRS))
class TestCoreCombinations:
    def test_both_orders_raise_the_same_most_actionable_type(self, clean_config, name):
        first, second = PAIRS[name]
        for order in ((first, second), (second, first)):
            outcome, logs = _run(order)
            assert isinstance(outcome, Exception), f"{name} {order} must not return text"
            assert not isinstance(outcome, requests.RequestException), (
                f"{name}: an unclassified transport error leaked past the router"
            )
            assert not isinstance(outcome, str)
            expected = {
                "timeout+auth": VendorAuthenticationError,
                "throttle+rejected": VendorRequestRejectedError,
                "transient+internal": KeyError,
                "auth+unconfigured": VendorAuthenticationError,
            }[name]
            assert isinstance(outcome, expected), (name, order)
            assert "NO_DATA_AVAILABLE" not in logs

    def test_auth_and_unconfigured_never_become_temporarily_unavailable(self, clean_config, name):
        first, second = PAIRS[name]
        for order in ((first, second), (second, first)):
            outcome, _ = _run(order)
            assert not isinstance(outcome, str)
            message = str(outcome)
            assert "NO_DATA_AVAILABLE" not in message
            # Whatever is raised, it is a typed vendor condition or a real bug.
            assert isinstance(
                outcome,
                (VendorAuthenticationError, VendorNotConfiguredError,
                 VendorRequestRejectedError, KeyError),
            )

    def test_swapping_the_order_cannot_hide_the_other_failure(self, clean_config, name):
        first, second = PAIRS[name]
        types_forward = _failure_types(_run((first, second))[0])
        types_reversed = _failure_types(_run((second, first))[0])
        assert types_forward == types_reversed, name


def _failure_types(outcome):
    """The raised type plus every type kept in its structured context."""
    types = {type(outcome).__name__}
    types.update(type(exc).__name__ for _, exc in getattr(outcome, "chain_failures", ()))
    return types


@pytest.mark.unit
def test_an_internal_error_is_never_hidden_by_a_throttle(clean_config):
    """A bug next to a timeout is still a bug: core raises it, not "unavailable"."""
    for order in ((_throttle, _bug), (_bug, _throttle)):
        outcome, _ = _run(order)
        assert isinstance(outcome, KeyError)
        assert "totalRevenue" in str(outcome)  # diagnostics survive


@pytest.mark.unit
def test_a_rejected_key_is_never_flattened_into_an_outage(clean_config):
    outcome, logs = _run((_timeout, _auth))
    assert isinstance(outcome, VendorAuthenticationError)
    assert "unreachable" not in str(outcome)
    # The other vendor's timeout is kept on the raised error, not just in the log.
    context = {v: type(e).__name__ for v, e in outcome.chain_failures}
    assert context == {"yfinance": "VendorRateLimitError"}
    assert "read timed out" in str(outcome.chain_failures[0][1])
    assert "yfinance" in logs and "read timed out" in logs


@pytest.mark.unit
def test_a_missing_key_does_not_outrank_a_rejected_key(clean_config):
    for order in ((_auth, _unconfigured), (_unconfigured, _auth)):
        outcome, _ = _run(order)
        assert isinstance(outcome, VendorAuthenticationError)
        assert {v: type(e) for v, e in outcome.chain_failures}


@pytest.mark.unit
def test_a_refused_request_outranks_a_throttle(clean_config):
    for order in ((_throttle, _rejected), (_rejected, _throttle)):
        outcome, _ = _run(order)
        assert isinstance(outcome, VendorRequestRejectedError)
        others = {v: type(e).__name__ for v, e in outcome.chain_failures}
        assert others == {"yfinance": "VendorRateLimitError"} or others == {
            "alpha_vantage": "VendorRateLimitError"
        }


# --- optional category ------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("name", list(PAIRS))
class TestOptionalCombinations:
    def test_the_verdict_keeps_every_category_in_both_orders(self, clean_config, name):
        first, second = PAIRS[name]
        verdicts = {}
        for label, order in (("forward", (first, second)), ("reversed", (second, first))):
            out, _ = _run(order, category="macro_data", method="get_macro_indicators")
            assert isinstance(out, str), f"{name}/{label} must degrade, not raise"
            assert out.startswith("DATA_UNAVAILABLE")
            assert "NO_DATA_AVAILABLE" not in out
            assert "All configured vendors failed" in out
            # Both vendors, both types and the real causes are named.
            assert "yfinance" in out and "alpha_vantage" in out
            for failure in (first, second):
                assert _cause_of(failure) in out, (name, failure.__name__)
            verdicts[label] = out

        # Reversing the chain may reorder the names inside the parenthesised
        # list, but must not change which categories are surfaced.
        forward, reversed_ = verdicts["forward"], verdicts["reversed"]
        assert _listed_types(forward) == _listed_types(reversed_), name

    def test_the_primary_category_is_stated_not_just_the_last_failure(self, clean_config, name):
        first, second = PAIRS[name]
        out, _ = _run((first, second), category="macro_data", method="get_macro_indicators")
        expected = {
            # The primary sentence is the verdict's own wording; the "also"
            # sentence names each remaining category (when there is one).
            "timeout+auth": ["rejected the configured credentials"],
            "throttle+rejected": ["refused the"],
            "transient+internal": ["(KeyError)"],
            "auth+unconfigured": ["rejected the configured credentials", "not configured"],
        }[name]
        for phrase in expected:
            assert phrase in out, (name, phrase, out)
        if name == "transient+internal":
            # The non-primary failure must keep its category and cause too.
            assert "throttled or unreachable" in out
            assert "KeyError ('totalRevenue' [unknown])" in out
            assert "temporarily unavailable" not in out


def _listed_types(verdict):
    """The set of exception types the 'All configured vendors failed' list names."""
    marker = "All configured vendors failed ("
    start = verdict.index(marker) + len(marker)
    prefix = verdict[start:]
    # Entries are "vendor: Type (cause [kind])" joined by "; ". A cause may itself
    # contain parentheses and "; ", so each entry is recognised by its start.
    return set(re.findall(r"(?:^|; )[a-z_]+: ([A-Za-z]+(?:Error)?) \(", prefix))


def _cause_of(stub):
    """The message the stub raises, without touching the network."""
    try:
        stub()
    except BaseException as exc:  # noqa: BLE001 - probing our own stub
        return str(exc)
    return ""


@pytest.mark.unit
def test_optional_auth_keeps_its_category_alongside_an_outage(clean_config):
    out, _ = _run((_timeout, _auth), category="macro_data", method="get_macro_indicators")
    # The primary verdict is the rejected key, not the outage it shared the chain with.
    assert "rejected the configured credentials" in out
    assert "Provide a valid API key" in out
    assert "the request was refused" not in out
    # ... and the outage is still named, with its vendor and real cause.
    assert "throttled or unreachable" in out
    assert "VendorRateLimitError" in out and "read timed out" in out


# --- success and single failures -------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("failure", [_timeout, _throttle, _auth, _unconfigured, _bug],
                         ids=lambda f: f.__name__)
class TestLaterVendorStillSucceeds:
    def test_a_failing_primary_does_not_change_the_secondary_result(self, clean_config, failure):
        for order in ((failure, _ok), (_ok, failure)):
            with _CaptureLogs():
                out = _route(CORE, dict(zip(CORE, order, strict=True)))
            assert out == "OK"

    def test_the_success_is_not_decorated_with_failure_text(self, clean_config, failure):
        out, _ = _run((failure, _ok))
        assert out == "OK"
        assert "DATA_UNAVAILABLE" not in out


@pytest.mark.unit
def test_a_single_failure_category_gets_no_mixed_sentence(clean_config):
    # Two outages are one category: no "also" sentence, but both vendors listed.
    out, _ = _run((_throttle, _timeout), category="macro_data", method="get_macro_indicators")
    assert "Mixed failure categories" not in out
    assert "All configured vendors failed (yfinance" in out
    assert "alpha_vantage" in out


@pytest.mark.unit
def test_a_one_vendor_chain_names_the_vendor_cause_once(clean_config):
    # A single failure still gets its own vendor/cause named exactly once, so
    # the reason is never lost behind a category remedy; no "also" sentence.
    set_config({"data_vendors": {"macro_data": "fred"}})
    with mock.patch.dict(
        interface.VENDOR_METHODS, {"get_macro_indicators": {"fred": _throttle}}, clear=False
    ):
        out = interface.route_to_vendor("get_macro_indicators", *ARGS)
    assert out.startswith("DATA_UNAVAILABLE")
    assert "Mixed failure categories" not in out
    assert out.count("All configured vendors failed (fred: ") == 1
    assert (
        "All configured vendors failed "
        "(fred: VendorRateLimitError (throttled by the vendor [unavailable]))"
    ) in out
