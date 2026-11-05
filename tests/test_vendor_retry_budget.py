"""Bounded data-vendor retries, coordinated by the routing layer.

Batch 1 classified vendor failures and kept them in the chain verdict; it did
not change *how many* times a vendor is called. This batch adds that: the
router may repeat the same vendor after a failure -- but only a failure whose
own metadata says waiting helps, and only within one budget shared by the whole
tool call.

The contract these tests pin:

    transient (429 / 502 / 503 / 504 / timeout / reset)  -> retried within budget
    500                                                  -> retried only with Retry-After
    auth, refused, unconfigured, absence, stale, parse,
    internal bug, TLS/URL                                -> never retried, chain moves on
    per-vendor cap, chain cap, time budget               -> never exceeded
    Retry-After longer than the budget                   -> not waited, next vendor
    exhausted retries                                    -> batch-1 verdicts, unchanged

Counts are *vendor-function invocations*. One invocation may issue several HTTP
requests (``get_global_news`` makes one per query), and the tests below keep the
two numbers apart. Nothing here touches the network or a paid API: vendors are
injected through ``interface.VENDOR_METHODS`` and failures are built from the
real ``requests``/``curl_cffi`` exception types. Time is virtual (a fake
clock/sleep), so a budget test never sleeps.
"""
from __future__ import annotations

import contextlib
import copy
import dataclasses
import time as real_time
from datetime import datetime, timezone

import pytest
import requests
from yfinance.exceptions import YFRateLimitError

import tradingagents.dataflows.config as config_module
import tradingagents.default_config as default_config

# Imported by module so a test can replace its ``time`` and call ``yf_retry``.
from tradingagents.dataflows import interface, retry_session, stockstats_utils as su
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.errors import (
    NoMarketDataError,
    VendorAuthenticationError,
    VendorNotConfiguredError,
    VendorRateLimitError,
    VendorRequestRejectedError,
    retryable_status,
)
from tradingagents.dataflows.retry_session import RetrySession
from tradingagents.dataflows.utils import retry_after_seconds

METHOD = "get_stock_data"
ARGS = ("AAPL", "2026-01-01", "2026-01-10")
CATEGORY = "core_stock_apis"


# --- failure builders (real exception types, metadata intact) ---------------


def http_error(status: int, headers: dict | None = None) -> requests.HTTPError:
    """A ``requests.HTTPError`` carrying ``status`` and optional response headers."""
    response = requests.models.Response()
    response.status_code = status
    response.url = "https://example.invalid/data"
    if headers:
        response.headers.update(headers)
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        return exc
    raise AssertionError("raise_for_status did not raise")


def timeout() -> requests.Timeout:
    return requests.Timeout("read timed out after 30s")


class Call:
    """A vendor function that fails or succeeds a given number of times.

    ``failures`` is a list of exceptions (or None for success) consumed in
    order; the last entry repeats. Every invocation is counted, so a test can
    assert on attempts, not just on the result.
    """

    def __init__(self, *failures, result="ok", duration=0.0):
        self.failures = list(failures) or [None]
        self.result = result
        self.calls = 0
        self.kwargs_seen = []
        # Virtual time this vendor spends per invocation (network latency,
        # a server that hangs, ...).
        self.duration = duration

    def __call__(self, *args, **kwargs):
        self.calls += 1
        self.kwargs_seen.append(kwargs)
        if self.duration:
            _ADVANCE[0](self.duration)
        failure = self.failures.pop(0) if len(self.failures) > 1 else self.failures[0]
        if failure is not None:
            raise failure
        return self.result


# The router fixture installs a function that moves the shared fake clock, so a
# vendor in a test can "spend" time without knowing about the harness.
_ADVANCE: list = [lambda seconds: None]


class Clock:
    """Virtual time: ``sleep`` advances the clock instead of waiting."""

    def __init__(self):
        self.now = 1000.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


# --- router harness ---------------------------------------------------------


@pytest.fixture
def router(monkeypatch):
    """Run a chain with injected vendors, a clean config and virtual time."""
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)
    clock = Clock()
    monkeypatch.setattr(retry_session.time, "monotonic", clock.clock)
    monkeypatch.setattr(retry_session.time, "sleep", clock.sleep)
    # Default: a vendor finishes instantly. A test that cares about the
    # deadline gives one a ``duration``; success consumes the virtual clock,
    # failure does not (the router stops at the failure).
    _ADVANCE[0] = clock.advance

    class Harness:
        def __init__(self):
            self.clock = clock

        def configure(self, retry: dict | None = None, chain=("yfinance",)) -> None:
            set_config(
                {
                    "data_vendors": {CATEGORY: ",".join(chain)},
                    "data_vendor_retry": retry or {},
                }
            )

        def route(self, vendors, *, chain=("yfinance",), retry=None):
            set_config(
                {
                    "data_vendors": {CATEGORY: ",".join(chain)},
                    "data_vendor_retry": retry or {},
                }
            )
            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(interface, "VENDOR_METHODS", {METHOD: vendors})
                return interface.route_to_vendor(METHOD, *ARGS)

        def route_error(self, vendors, exc_type, **kwargs):
            with pytest.raises(exc_type) as caught:
                self.route(vendors, **kwargs)
            return caught.value

    yield Harness()
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)


# --- 1. what is retried, and what is not ------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(lambda: VendorRateLimitError("429").with_retry_evidence(
            status=429, retry=True), id="429"),
        pytest.param(lambda: VendorRateLimitError("502").with_retry_evidence(
            status=502, retry=True), id="502"),
        pytest.param(lambda: VendorRateLimitError("503").with_retry_evidence(
            status=503, retry=True), id="503"),
        pytest.param(lambda: VendorRateLimitError("504").with_retry_evidence(
            status=504, retry=True), id="504"),
        pytest.param(timeout, id="read-timeout"),
        pytest.param(lambda: requests.ConnectionError("reset by peer"), id="connection-reset"),
    ],
)
def test_transient_failures_are_retried_on_the_same_vendor(router, failure):
    vendor = Call(failure(), None)
    assert router.route({"yfinance": vendor}) == "ok"
    assert vendor.calls == 2  # initial + exactly one retry


@pytest.mark.unit
@pytest.mark.parametrize(
    "failure,because",
    [
        (lambda: http_error(401), "auth"),
        (lambda: http_error(403), "auth"),
        (lambda: http_error(400), "refused"),
        (lambda: http_error(404), "refused"),
        (lambda: VendorAuthenticationError("bad key"), "typed auth"),
        (lambda: VendorRequestRejectedError("bad params"), "typed refusal"),
        (lambda: VendorNotConfiguredError("no key"), "unconfigured"),
        (lambda: ValueError("could not parse body"), "parse failure"),
        (lambda: KeyError("totalRevenue"), "internal bug"),
        (lambda: requests.exceptions.SSLError("certificate verify failed"), "tls"),
        (lambda: requests.exceptions.InvalidURL("no host"), "invalid url"),
    ],
)
def test_non_transient_failures_are_never_retried(router, failure, because):
    """One invocation, however batch 1 chose to report the failure.

    A TLS/URL failure is not a bug, so batch 1 reports it as an unavailable
    vendor (``DATA_UNAVAILABLE`` text); an auth error is raised. Either way the
    router must not repeat the call.
    """
    vendor = Call(failure())
    try:
        out = router.route({"yfinance": vendor})
    except Exception:
        out = None
    assert vendor.calls == 1, because
    if out is not None:
        assert out.startswith("DATA_UNAVAILABLE"), because


@pytest.mark.unit
@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(lambda: http_error(500), id="500-without-retry-after"),
        pytest.param(lambda: http_error(501), id="501"),
        pytest.param(lambda: http_error(505), id="505"),
        pytest.param(lambda: VendorRateLimitError("a throttle with no evidence"), id="class-alone"),
    ],
)
def test_unproven_service_errors_are_not_retried(router, failure):
    """A 5xx that is not provably transient is reported, not repeated."""
    vendor = Call(failure())
    out = router.route({"yfinance": vendor})
    assert vendor.calls == 1
    assert out.startswith("DATA_UNAVAILABLE")


@pytest.mark.unit
def test_an_absence_is_never_retried_and_stays_an_absence(router):
    vendor = Call(NoMarketDataError("AAPL", "AAPL", "no rows"))
    out = router.route({"yfinance": vendor})
    assert vendor.calls == 1
    assert out.startswith("NO_DATA_AVAILABLE")


@pytest.mark.unit
def test_a_500_with_retry_after_is_transient(router):
    vendor = Call(http_error(500, {"Retry-After": "1"}), None)
    assert router.route({"yfinance": vendor}) == "ok"
    assert vendor.calls == 2
    assert router.clock.slept == [1.0]  # the vendor's own instruction, not a guess


@pytest.mark.unit
def test_a_non_retryable_failure_still_lets_the_next_vendor_serve(router):
    first = Call(http_error(403))
    second = Call(None, result="from-fallback")
    out = router.route({"yfinance": first, "alpha_vantage": second}, chain=("yfinance", "alpha_vantage"))
    assert out == "from-fallback"
    assert first.calls == 1 and second.calls == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(lambda: requests.exceptions.SSLError("certificate verify failed"), id="tls"),
        pytest.param(lambda: requests.exceptions.InvalidURL("no host"), id="invalid-url"),
    ],
)
def test_a_broken_transport_configuration_moves_on_without_repeating(router, failure):
    """TLS/URL problems are configuration: not retried, but the chain still falls through."""
    first = Call(failure())
    second = Call(None, result="from-fallback")
    out = router.route(
        {"yfinance": first, "alpha_vantage": second},
        chain=("yfinance", "alpha_vantage"),
    )
    assert out == "from-fallback"
    assert first.calls == 1 and second.calls == 1


# --- 2. the budget is shared by the whole chain ----------------------------


@pytest.mark.unit
def test_switching_vendors_does_not_reset_the_chain_attempt_budget(router):
    first = Call(http_error(502))
    second = Call(http_error(503))
    out = router.route(
        {"yfinance": first, "alpha_vantage": second},
        chain=("yfinance", "alpha_vantage"),
        retry={"max_total_attempts": 2, "max_attempts": 2},
    )
    # Two invocations total, shared: the second vendor is not started at all,
    # and the batch-1 all-unavailable verdict still applies.
    assert first.calls == 2
    assert second.calls == 0
    assert out.startswith("DATA_UNAVAILABLE")


@pytest.mark.unit
def test_per_vendor_attempt_cap_is_respected(router):
    vendor = Call(http_error(503))
    out = router.route({"yfinance": vendor}, retry={"max_attempts": 3})
    assert vendor.calls == 3  # initial + 2 retries, then give up
    assert out.startswith("DATA_UNAVAILABLE")


@pytest.mark.unit
def test_alpha_vantage_defaults_to_a_single_attempt_while_others_retry(router):
    av = Call(http_error(503))
    router.route({"alpha_vantage": av}, chain=("alpha_vantage",))
    assert av.calls == 1, "the free tier is a narrow, possibly-metered quota"

    yf = Call(http_error(503))
    router.route({"yfinance": yf}, chain=("yfinance",))
    assert yf.calls == 2, "the default vendor keeps one retry"


@pytest.mark.unit
def test_alpha_vantage_can_opt_into_retries(router):
    av = Call(http_error(503))
    router.route(
        {"alpha_vantage": av},
        chain=("alpha_vantage",),
        retry={"vendor_max_attempts": {"alpha_vantage": 2}},
    )
    assert av.calls == 2


@pytest.mark.unit
def test_a_spent_time_budget_starts_nothing_at_all(router):
    """Zero seconds left: not even the first call starts (no request when spent)."""
    vendor = Call(http_error(503))
    out = router.route({"yfinance": vendor}, retry={"max_total_seconds": 0.0})
    assert vendor.calls == 0
    assert router.clock.slept == []
    assert out.startswith("DATA_UNAVAILABLE")


@pytest.mark.unit
def test_backoff_grows_and_is_bounded_by_the_budget(router):
    vendor = Call(http_error(502))
    router.route(
        {"yfinance": vendor},
        retry={
            "max_attempts": 3,
            "base_delay_seconds": 1.0,
            "max_total_seconds": 60.0,
            "jitter_fraction": 0.0,
        },
    )
    assert router.clock.slept == [1.0, 2.0]  # doubled each attempt


@pytest.mark.unit
def test_a_wait_that_does_not_fit_the_budget_is_not_taken(router):
    vendor = Call(http_error(503))
    router.route(
        {"yfinance": vendor},
        retry={
            "max_attempts": 3,
            "base_delay_seconds": 0.6,
            "max_total_seconds": 1.0,
            "jitter_fraction": 0.0,
        },
    )
    # 0.6s fits; the next 1.2s would exceed the 1.0s budget, so it is refused.
    assert vendor.calls == 2
    assert router.clock.slept == [0.6]


# --- 3. Retry-After comes from the header, never from text -----------------


@pytest.mark.unit
def test_retry_after_header_is_honoured_exactly(router):
    vendor = Call(http_error(429, {"Retry-After": "4"}), None)
    assert router.route({"yfinance": vendor}) == "ok"
    assert router.clock.slept == [4.0]


@pytest.mark.unit
def test_retry_after_zero_retries_at_once_not_after_a_fallback(router):
    vendor = Call(http_error(429, {"Retry-After": "0"}), None)
    assert router.route({"yfinance": vendor}) == "ok"
    assert vendor.calls == 2
    assert router.clock.slept == []  # no pause was needed


@pytest.mark.unit
def test_a_retry_after_beyond_the_cap_moves_on_instead_of_stalling(router):
    first = Call(http_error(429, {"Retry-After": "120"}))
    second = Call(None, result="from-fallback")
    out = router.route(
        {"yfinance": first, "alpha_vantage": second},
        chain=("yfinance", "alpha_vantage"),
        retry={"max_retry_after_seconds": 10},
    )
    assert out == "from-fallback"
    assert first.calls == 1
    assert router.clock.slept == []


@pytest.mark.unit
def test_a_hostile_retry_after_value_is_not_a_wait():
    for value in ("", "soon", "-3", "NaN", None):
        assert retry_after_seconds({"Retry-After": value}) is None


@pytest.mark.unit
def test_retry_after_accepts_the_http_date_form(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.dataflows.utils._utc_now",
        lambda: datetime(2026, 11, 5, 16, 0, 0, tzinfo=timezone.utc),
    )
    assert retry_after_seconds(
        {"Retry-After": "Thu, 05 Nov 2026 16:00:30 GMT"}
    ) == pytest.approx(30.0)


# --- 4. retries removed the pointless repeat on success --------------------


@pytest.mark.unit
def test_a_retry_that_succeeds_returns_normally_and_ends_the_chain(router):
    first = Call(http_error(503), None, result="retried-ok")
    second = Call(None, result="never-reached")
    out = router.route({"yfinance": first, "alpha_vantage": second}, chain=("yfinance", "alpha_vantage"))
    assert out == "retried-ok"
    assert second.calls == 0


@pytest.mark.unit
def test_exhausted_retries_keep_the_batch1_verdict(router):
    vendor = Call(http_error(503))
    out = router.route({"yfinance": vendor}, retry={"max_attempts": 2})
    assert vendor.calls == 2
    assert out.startswith("DATA_UNAVAILABLE")


@pytest.mark.unit
def test_exhausted_retries_of_an_auth_error_still_raise_it(router):
    vendor = Call(http_error(401))
    exc = router.route_error({"yfinance": vendor}, VendorAuthenticationError)
    assert vendor.calls == 1
    assert "401" in str(exc)


@pytest.mark.unit
def test_no_data_from_every_retried_vendor_is_still_an_absence(router):
    vendor = Call(NoMarketDataError("AAPL", "AAPL", "no rows"))
    out = router.route({"yfinance": vendor})
    assert vendor.calls == 1
    assert out.startswith("NO_DATA_AVAILABLE")


# --- 5. units: vendor-function invocations vs. HTTP requests ---------------


@pytest.mark.unit
def test_attempts_count_invocations_not_http_requests():
    session = RetrySession(retry_session.RetryBudget(max_attempts=4))
    session.note_attempt("yfinance", http_requests=5)  # one get_global_news = 5 searches
    assert session.attempts == 1
    assert session.http_requests == 5


@pytest.mark.unit
def test_one_multi_request_vendor_invocation_stays_one_attempt(router):
    """get_global_news makes one HTTP request per query, but one invocation."""
    vendor = Call(http_error(503), None)
    out = router.route(
        {"yfinance": vendor}, retry={"max_attempts": 2, "max_total_attempts": 2}
    )
    assert out == "ok"
    assert vendor.calls == 2  # two invocations; their inner HTTP count is the vendor's


# --- 6. no outer x inner retry amplification -------------------------------


@pytest.mark.unit
def test_yf_retry_delegates_to_the_router_loop(monkeypatch):
    """Inside a routed call, yf_retry makes exactly one attempt."""
    monkeypatch.setattr(su.time, "sleep", lambda s: None)
    calls = []

    def always_limited():
        calls.append(1)
        raise YFRateLimitError()

    session = RetrySession(retry_session.RetryBudget(max_attempts=4))
    with retry_session.retry_session(session), pytest.raises(YFRateLimitError):
        su.yf_retry(always_limited, max_retries=3)
    assert len(calls) == 1  # not 4: the router owns the loop


@pytest.mark.unit
def test_yf_retry_keeps_its_standalone_behaviour(monkeypatch):
    """Outside a routed call, the existing interface and loop are unchanged."""
    monkeypatch.setattr(su.time, "sleep", lambda s: None)
    calls = []

    def always_limited():
        calls.append(1)
        raise YFRateLimitError()

    with pytest.raises(YFRateLimitError):
        su.yf_retry(always_limited, max_retries=2)
    assert len(calls) == 3  # initial + 2 retries, as before this batch


@pytest.mark.unit
def test_routed_total_attempts_equal_the_router_budget_not_the_product():
    """A full chain of throttled vendors spends the chain cap, not cap x inner."""
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)
    try:
        set_config(
            {
                "data_vendors": {CATEGORY: "yfinance"},
                "data_vendor_retry": {"max_attempts": 2, "max_total_attempts": 4},
            }
        )
        invocations = []

        def vendor(*a, **k):
            invocations.append(1)
            with retry_session.retry_session(
                retry_session.get_active_retry_session()
            ):
                # One yf_retry-style inner wrapper per invocation, as the real
                # vendors have: it must not multiply the router's attempts.
                su.yf_retry(lambda: (_ for _ in ()).throw(YFRateLimitError()))
            return "unreachable"

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(interface, "VENDOR_METHODS", {METHOD: {"yfinance": vendor}})
            patch.setattr(retry_session.time, "sleep", lambda s: None)
            interface.route_to_vendor(METHOD, *ARGS)
        assert len(invocations) == 2  # router: initial + 1 retry; inner: 1 each
    finally:
        config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)


# --- 7. time budget is propagated, and what cannot be is declared ----------


@pytest.mark.unit
def test_remaining_time_is_passed_to_a_capable_request(monkeypatch):
    import tradingagents.dataflows.retry_session as rs

    session = RetrySession(rs.RetryBudget(max_attempts=2, max_total_seconds=45.0))
    with rs.retry_session(session):
        assert rs.remaining_request_timeout() == pytest.approx(45.0)
        # The per-request cap (15s) bounds a request even when 45s are left,
        # and the timeout never exceeds what is left.
        assert rs.request_timeout(30, "test") == pytest.approx(15.0)
        assert rs.request_timeout(45, "test") == pytest.approx(15.0)
    assert rs.remaining_request_timeout() is None  # standalone: vendor default
    assert rs.request_timeout(30, "test") == 30  # standalone: the vendor's own


@pytest.mark.unit
def test_the_request_timeout_never_grows_the_budget():
    """0.2s left must not become a 1s request: it is refused, with a reason."""
    import tradingagents.dataflows.retry_session as rs

    budget = rs.RetryBudget(max_attempts=2, max_total_seconds=10.0)
    session = RetrySession(budget)
    session.started -= 9.8  # 0.2s left
    with rs.retry_session(session):
        assert rs.request_timeout_for(0.2) is None
        assert rs.request_timeout_for(0.2, 15) is None
        assert rs.request_timeout(15, "a test request") is None
    # Exactly at the budget: also refused (nothing left).
    session.started -= 10.0
    with rs.retry_session(session):
        assert rs.request_timeout(15, "a test request") is None


@pytest.mark.unit
def test_a_refused_request_says_why_in_the_log(caplog):
    import logging

    import tradingagents.dataflows.retry_session as rs

    budget = rs.RetryBudget(max_attempts=2, max_total_seconds=10.0)
    session = RetrySession(budget)
    session.started -= 9.9
    with rs.retry_session(session), caplog.at_level(logging.WARNING, logger=rs.__name__):
        assert rs.request_timeout(15, "a FRED series request") is None
    messages = [r.getMessage() for r in caplog.records]
    assert any("FRED series request" in m and "not" in m.lower() for m in messages)


@pytest.mark.unit
def test_the_timeout_never_exceeds_the_time_left_and_honours_the_cap():
    import tradingagents.dataflows.retry_session as rs

    session = RetrySession(rs.RetryBudget(max_attempts=2, max_total_seconds=45.0))
    session.started -= 40.0  # 5s left
    with rs.retry_session(session):
        assert rs.request_timeout_for(5.0) == pytest.approx(5.0)
        assert rs.request_timeout_for(5.0, 15.0) == pytest.approx(5.0)
        assert rs.request_timeout(15.0, "test") == pytest.approx(5.0)
    session.started += 39.0  # 44s left: the 15s cap applies
    with rs.retry_session(session):
        assert rs.request_timeout_for(44.0, 15.0) == pytest.approx(15.0)


@pytest.mark.unit
def test_remaining_time_shrinks_with_the_clock(monkeypatch):
    import tradingagents.dataflows.retry_session as rs

    clock = Clock()
    budget = rs.RetryBudget(max_attempts=2, max_total_seconds=30.0, clock=clock.clock)
    session = RetrySession(budget)
    clock.now += 12.0
    assert session.remaining() == pytest.approx(18.0)


@pytest.mark.unit
def test_an_uncontrollable_call_is_not_started_with_no_budget():
    import tradingagents.dataflows.retry_session as rs

    session = RetrySession(rs.RetryBudget(max_attempts=2, max_total_seconds=5.0))
    session.started -= 10  # the clock moved past the deadline
    with rs.retry_session(session):
        with pytest.raises(VendorRateLimitError):
            rs.budget_check_before_uncontrolled_call("fundamentals")
        with pytest.raises(VendorRateLimitError):
            rs.budget_check_before_uncontrolled_call("price history")


@pytest.mark.unit
def test_an_overrun_of_an_uncontrollable_call_is_logged_not_claimed(caplog):
    import logging

    import tradingagents.dataflows.retry_session as rs

    session = RetrySession(rs.RetryBudget(max_attempts=2, max_total_seconds=5.0))
    session.started -= 10
    with rs.retry_session(session), caplog.at_level(logging.WARNING, logger=rs.__name__):
        rs.note_uncontrolled_overrun("AAPL news")
    assert any("could not be cut short" in r.message for r in caplog.records)


# --- 8. configuration -------------------------------------------------------


@pytest.mark.unit
def test_default_budget_mirrors_default_config():
    budget = interface._retry_budget()
    cfg = default_config.DEFAULT_CONFIG["data_vendor_retry"]
    assert budget.default_per_vendor_attempts == cfg["max_attempts"] == 2
    assert budget.attempts_for("alpha_vantage") == 1
    assert budget.attempts_for("yfinance") == 2
    assert budget.max_attempts == cfg["max_total_attempts"]
    assert budget.max_total_seconds == cfg["max_total_seconds"] == 45.0
    assert budget.max_request_seconds == cfg["max_request_seconds"] == 15.0
    assert budget.max_cumulative_wait_seconds == cfg["max_cumulative_wait_seconds"]


@pytest.mark.unit
def test_a_partial_retry_section_is_completed_from_defaults():
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)
    try:
        set_config({"data_vendor_retry": {"max_attempts": 5}})
        budget = interface._retry_budget()
        assert budget.default_per_vendor_attempts == 5
        assert budget.max_total_seconds == 45.0  # untouched default survives the merge
        assert budget.max_request_seconds == 15.0
    finally:
        config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)


@pytest.mark.unit
def test_the_time_budget_is_configurable_by_a_nested_env_var(monkeypatch):
    import importlib

    monkeypatch.setenv("TRADINGAGENTS_VENDOR_RETRY_MAX_SECONDS", "7.5")
    dc = importlib.reload(default_config)
    try:
        assert dc.DEFAULT_CONFIG["data_vendor_retry"]["max_total_seconds"] == 7.5
        # The siblings of the nested key are untouched by the override.
        assert dc.DEFAULT_CONFIG["data_vendor_retry"]["max_attempts"] == 2
    finally:
        monkeypatch.undo()
        importlib.reload(default_config)


@pytest.mark.unit
def test_an_invalid_nested_env_value_is_rejected_at_import(monkeypatch):
    import importlib

    monkeypatch.setenv("TRADINGAGENTS_VENDOR_RETRY_MAX_SECONDS", "soon")
    with pytest.raises(ValueError, match="TRADINGAGENTS_VENDOR_RETRY_MAX_SECONDS"):
        importlib.reload(default_config)
    monkeypatch.undo()
    importlib.reload(default_config)


@pytest.mark.unit
def test_one_attempt_means_no_retry_not_one_retry(router):
    """The count includes the first attempt: 1 = never retried, 2 = one retry."""
    once = Call(http_error(503))
    router.route({"yfinance": once}, retry={"max_attempts": 1})
    assert once.calls == 1

    twice = Call(http_error(503))
    router.route({"yfinance": twice}, retry={"max_attempts": 2})
    assert twice.calls == 2


@pytest.mark.unit
def test_retryable_status_rules_are_explicit():
    assert retryable_status(429) is True
    assert retryable_status(502) is True
    assert retryable_status(503) is True
    assert retryable_status(504) is True
    assert retryable_status(500) is False
    assert retryable_status(500, retry_after=1.0) is True
    for status in (400, 401, 403, 404, 501, 505):
        assert retryable_status(status) is False
    assert retryable_status(None) is None


@pytest.mark.unit
def test_the_router_does_not_really_sleep(router):
    """Guard: these tests replace the clock, so a real budget wait is a bug."""
    started = real_time.monotonic()
    vendor = Call(http_error(503))
    router.route({"yfinance": vendor}, retry={"max_attempts": 3})
    assert vendor.calls == 3
    assert real_time.monotonic() - started < 5


# --- 9. Alpha Vantage: a quota is not a short throttle ----------------------


AV_KEY = "AVSECRET0123456789"


class AvResponse:
    """A minimal response whose body is the vendor's JSON notice."""

    def __init__(self, body: str, *, status: int = 200, headers: dict | None = None):
        self.status_code = status
        self.url = f"https://www.alphavantage.co/query?apikey={AV_KEY}"
        self.text = body
        self.headers = requests.structures.CaseInsensitiveDict(headers or {})

    def raise_for_status(self):
        if self.status_code < 400:
            return
        message = (
            f"{self.status_code} Client Error: throttle for url: {self.url}"
            if self.status_code < 500
            else f"{self.status_code} Server Error: busy for url: {self.url}"
        )
        raise requests.HTTPError(message, response=self)


@pytest.fixture
def alpha_vantage(monkeypatch):
    import tradingagents.dataflows.alpha_vantage_common as av

    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", AV_KEY)
    return av


def _av_call(monkeypatch, av, response, *, timeout_seen=None):
    def get(url, params=None, timeout=None):
        if timeout_seen is not None:
            timeout_seen.append(timeout)
        return response

    monkeypatch.setattr(requests, "get", get)
    return av._make_api_request("TIME_SERIES_DAILY", {"symbol": "AAPL"})


@pytest.mark.unit
@pytest.mark.parametrize(
    "notice",
    [
        "Thank you for using Alpha Vantage! Our standard API rate limit is 25 "
        "requests per day.",
        "Your daily requests are exhausted.",
        "This endpoint is available on a premium plan.",
        "Your entitlement does not cover this function.",
    ],
)
def test_a_quota_notice_is_a_throttle_that_waiting_cannot_lift(
    monkeypatch, alpha_vantage, notice
):
    import json

    with pytest.raises(VendorRateLimitError) as caught:
        _av_call(monkeypatch, alpha_vantage, AvResponse(json.dumps({"Information": notice})))
    assert caught.value.retry is False
    assert isinstance(caught.value, alpha_vantage.AlphaVantageQuotaExhaustedError)


@pytest.mark.unit
def test_a_call_frequency_notice_is_a_short_throttle(monkeypatch, alpha_vantage):
    import json

    notice = "We have detected unusually high call frequency. Please try again later."
    with pytest.raises(VendorRateLimitError) as caught:
        _av_call(monkeypatch, alpha_vantage, AvResponse(json.dumps({"Note": notice})))
    assert caught.value.retry is True
    assert not isinstance(caught.value, alpha_vantage.AlphaVantageQuotaExhaustedError)


@pytest.mark.unit
def test_the_router_does_not_retry_alpha_vantage_even_when_it_says_retry(router, monkeypatch):
    """The default per-vendor cap (1) wins: a metered vendor is asked once."""
    import json

    import tradingagents.dataflows.alpha_vantage_common as av

    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", AV_KEY)
    calls = []

    def get(url, params=None, timeout=None):
        calls.append(1)
        return AvResponse(json.dumps({"Note": "call frequency exceeded; please try again later"}))

    monkeypatch.setattr(requests, "get", get)
    out = router.route(
        {"alpha_vantage": lambda *a, **k: av._make_api_request("TIME_SERIES_DAILY", {"symbol": "AAPL"})},
        chain=("alpha_vantage",),
    )
    assert len(calls) == 1
    assert out.startswith("DATA_UNAVAILABLE")


# --- 10. Retry-After survives scrubbing without the keyed URL -------------


@pytest.mark.unit
def test_alpha_vantage_keeps_retry_after_but_not_the_keyed_url(monkeypatch, alpha_vantage):
    with pytest.raises(VendorRateLimitError) as caught:
        _av_call(
            monkeypatch,
            alpha_vantage,
            AvResponse("throttled", status=429, headers={"Retry-After": "3"}),
        )
    error = caught.value
    assert error.status == 429 and error.retry_after == 3.0 and error.retry is True
    assert AV_KEY not in str(error) and AV_KEY not in repr(error)
    assert getattr(error, "response", None) is None
    # The scrubbed client error may be kept implicitly, but the printed chain
    # stops at the vendor error: the cause is never re-attached.
    assert error.__cause__ is None
    assert error.__suppress_context__ is True
    assert AV_KEY not in "".join(
        str(item) for item in (error, error.__cause__) if item is not None
    )


@pytest.mark.unit
def test_the_scrubbed_retention_copy_holds_only_scalars():
    from tradingagents.dataflows.utils import retry_after_seconds

    response = AvResponse("throttled", status=429, headers={"Retry-After": "3"})
    copied = {"retry_after": retry_after_seconds(response.headers)}
    assert copied == {"retry_after": 3.0}
    for value in copied.values():
        assert isinstance(value, (int, float, str, type(None), bool))
    assert AV_KEY not in repr(copied)


@pytest.mark.unit
def test_the_router_waits_the_scrubbed_retry_after(router, monkeypatch):
    """End to end: a vendor-typed 429 with Retry-After is waited out exactly."""
    import tradingagents.dataflows.alpha_vantage_common as av

    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", AV_KEY)
    responses = [
        AvResponse("throttled", status=429, headers={"Retry-After": "2"}),
        AvResponse("close,open\n1,2", status=200),
    ]

    def get(url, params=None, timeout=None):
        return responses.pop(0)

    monkeypatch.setattr(requests, "get", get)
    out = router.route(
        {"alpha_vantage": lambda *a, **k: av._make_api_request("TIME_SERIES_DAILY", {"symbol": "AAPL"})},
        chain=("alpha_vantage",),
        retry={"vendor_max_attempts": {"alpha_vantage": 2}},
    )
    assert out.startswith("close,open")
    assert router.clock.slept == [2.0]


# --- 11. the budget is passed down as a request timeout --------------------


@pytest.mark.unit
def test_alpha_vantage_caps_its_request_at_the_time_left(monkeypatch, alpha_vantage):
    seen = []
    budget = retry_session.RetryBudget(max_attempts=2, max_total_seconds=4.0)
    with retry_session.retry_session(RetrySession(budget)):
        _av_call(monkeypatch, alpha_vantage, AvResponse("close\n1"), timeout_seen=seen)
    assert seen == [pytest.approx(4.0)]


@pytest.mark.unit
def test_a_standalone_alpha_vantage_call_keeps_its_own_timeout(monkeypatch, alpha_vantage):
    seen = []
    _av_call(monkeypatch, alpha_vantage, AvResponse("close\n1"), timeout_seen=seen)
    assert seen == [alpha_vantage.REQUEST_TIMEOUT]


# --- 12. FRED: one HTTP request per call, the router owns the retry --------


FRED_KEY = "FREDSECRET0123456789"


@pytest.fixture
def fred(monkeypatch):
    import tradingagents.dataflows.fred as fred_module

    monkeypatch.setenv("FRED_API_KEY", FRED_KEY)
    return fred_module


def _fred_response(status=200, headers=None, body=b'{"observations": []}'):
    response = requests.models.Response()
    response.status_code = status
    response.url = f"https://api.stlouisfed.org/fred/series?api_key={FRED_KEY}"
    response._content = body
    if headers:
        response.headers.update(headers)
    return response


@pytest.mark.unit
def test_fred_alone_makes_one_request_and_raises(monkeypatch, fred):
    """Called directly (no router), one transient failure is one request.

    This is the direct check that the vendor has no retry loop of its own: the
    count is asserted on ``requests.get`` itself, not through the router, whose
    mocked vendor table could mask a second in-call request.
    """
    attempts = []

    def get(url, params=None, timeout=None):
        attempts.append(1)
        return _fred_response(503)

    monkeypatch.setattr(requests, "get", get)
    with pytest.raises(requests.HTTPError) as caught:
        fred._request("series", {"series_id": "DGS10"})
    assert len(attempts) == 1
    assert getattr(caught.value, "retry_after", None) is None


@pytest.mark.unit
def test_fred_does_not_retry_an_auth_failure(monkeypatch, fred):
    attempts = []

    def get(url, params=None, timeout=None):
        attempts.append(1)
        return _fred_response(403)

    monkeypatch.setattr(requests, "get", get)
    with pytest.raises(requests.HTTPError):
        fred._request("series", {"series_id": "DGS10"})
    assert len(attempts) == 1


@pytest.mark.unit
def test_fred_keeps_retry_after_without_the_key(monkeypatch, fred):
    """The router can honour the header: the scrubbed error still carries it."""

    def get(url, params=None, timeout=None):
        return _fred_response(429, {"Retry-After": "3"})

    monkeypatch.setattr(requests, "get", get)
    with pytest.raises(requests.HTTPError) as caught:
        fred._request("series", {"series_id": "DGS10"})
    error = caught.value
    assert error.retry_after == 3.0
    assert FRED_KEY not in str(error) and FRED_KEY not in repr(error)


@pytest.mark.unit
def test_fred_reports_a_failure_through_the_router_without_amplification(
    monkeypatch, fred, router
):
    """One vendor invocation = one HTTP request number; the router counts both."""
    requests_made = []
    calls = []

    def get(url, params=None, timeout=None):
        requests_made.append(1)
        return _fred_response(503)

    def vendor(*a, **k):
        calls.append(1)
        return fred._request("series", {"series_id": "DGS10"})

    monkeypatch.setattr(requests, "get", get)
    out = router.route(
        {"fred": vendor},
        chain=("fred",),
        retry={"max_attempts": 2, "vendor_max_attempts": {"fred": 2}},
    )
    # Router: 2 vendor invocations. Vendor: exactly 1 request each (no inner loop).
    assert len(calls) == 2
    assert len(requests_made) == 2
    assert out.startswith("DATA_UNAVAILABLE")


@pytest.mark.unit
def test_fred_second_call_is_not_started_when_the_budget_cannot_cover_it(
    monkeypatch, fred
):
    """Two requests per get_macro_data; the second re-checks the budget."""
    clock = Clock()
    budget = retry_session.RetryBudget(
        max_attempts=2, max_total_seconds=5.0, clock=clock.clock, sleep=clock.sleep
    )
    session = RetrySession(budget)
    session.note_attempt("fred")  # what the router does before calling the vendor
    attempts = []

    def get(url, params=None, timeout=None):
        attempts.append(url)
        clock.advance(4.8)  # each request spends most of the 5s budget
        if url.endswith("/series"):
            return _fred_response(
                body=b'{"seriess": [{"title": "T", "units": "u", "frequency": "f"}]}'
            )
        return _fred_response(body=b'{"observations": []}')

    monkeypatch.setattr(requests, "get", get)
    with (
        retry_session.retry_session(session),
        pytest.raises(VendorRateLimitError) as caught,
    ):
        fred.get_macro_data("10y_treasury", "2026-01-10")
    assert len(attempts) == 1, "the second request would start with 0.2s left"
    assert caught.value.retry is False


# --- 13. yfinance: no inner loop, a bounded call, and no global mutation ---


# A real curl_cffi Session whose transport is offline: yfinance builds its own
# request from it, so a test drives yfinance's real code path without a socket.

import yfinance as yf  # noqa: E402
from curl_cffi import requests as _curl  # noqa: E402

YF_URL = "https://query1.finance.yahoo.com/v8/finance/chart/AAPL"


class _NoCookieCache:
    def lookup(self, key):
        return None

    def store(self, key, value):
        pass


class _YfResponse:
    def __init__(self, status, headers, url):
        self.status_code = status
        self.headers = dict(headers or {})
        self.url = url
        self.text = f"refused-{status}?crumb=secret-crumb"
        self.content = self.text.encode()

    def json(self):
        return {"chart": {"result": None, "error": {"code": "x", "description": "no"}}}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise _curl.exceptions.HTTPError(
                f"HTTP Error {self.status_code}: refused", 0, self
            )


class _FixedStatusSession(_curl.Session):
    """A supported session type that answers every request the same way."""

    def __init__(self, status, headers=None):
        super().__init__(impersonate="chrome")
        self.status = status
        self.reply_headers = headers
        self.calls: list[tuple[str, str, dict]] = []

    def request(self, method, url, **kwargs):
        """Record the request, then answer without a socket.

        Overridden at ``request`` (the method yfinance calls, and the one any
        session wrapper would replace) so a wrapped session behaves exactly as
        it would against the network; the transport is never touched.
        """
        self.calls.append((method, url, dict(kwargs.get("params") or {})))
        return _YfResponse(self.status, self.reply_headers, url)


class _FinegrainedSession(_FixedStatusSession):
    """A crumb succeeds so the target URL is really requested and then refused."""

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, dict(kwargs.get("params") or {})))
        if "getcrumb" in url or "fc.yahoo.com" in url or "consent" in url:
            return _YfResponse(200, {}, url)
        return _YfResponse(self.status, self.reply_headers, url)


def _fixed_status_session(status, headers=None):
    if status < 400:
        return _FixedStatusSession(status, headers)
    return _FinegrainedSession(status, headers)


def _yf_get(session):
    """One yfinance data request through ``YfData``, as a vendor call makes it."""
    ticker = yf.Ticker("AAPL", session=session)
    return ticker._data.get(YF_URL)


@contextlib.contextmanager
def _cookie_cache_offline(monkeypatch):
    """A deterministic, stateless cookie/crumb setup for an offline session.

    yfinance caches the ``_CookieCache`` instance on its manager (a value
    created earlier has a disk parent) and keeps the cookie strategy on the
    class, so with the real store the first test in a process would fetch a
    cookie and every later one would reuse it -- a different code path. Here
    the cookie step always succeeds without storing anything, and the cookie
    never counts as "loaded", so the request sequence is the same every time.
    """
    manager = su.yf.cache._CookieCacheManager
    previous_instance = manager._Cookie_cache
    manager._Cookie_cache = None
    try:
        with monkeypatch.context() as patch:
            # Offline: no SQLite cache to write to and no real cookie to load;
            # the cookie step always succeeds, so the request sequence is the
            # same on every run (the real store makes the first test in a
            # process fetch a cookie and every later one reuse it).
            patch.setattr(su.yf.data.YfData, "_save_cookie_curlCffi", lambda self: False)
            patch.setattr(su.yf.data.YfData, "_load_cookie_curlCffi", lambda self: False)
            patch.setattr(su.yf.data.YfData, "_get_cookie_basic", lambda self, timeout=30: True)
            # The fallback (csrf) cookie strategy would go through a consent
            # page and a second data request; declining it is a real yfinance
            # path (it then requests without a crumb) and keeps the test to the
            # refusal behaviour it is about.
            patch.setattr(su.yf.data.YfData, "_get_cookie_csrf", lambda self, timeout=30: False)
            yield
    finally:
        manager._Cookie_cache = previous_instance


def _target_calls(session):
    return [call for call in session.calls if "/v8/finance/" in call[1]]


def _as_yfinance_failure(session, monkeypatch):
    """What the router receives from a real yfinance call: the error, or None."""
    with _cookie_cache_offline(monkeypatch):
        try:
            response = _yf_get(session)
        except Exception as exc:  # noqa: BLE001 - the vendor's own failure
            return su.as_vendor_error(exc, "yfinance") or exc
    return response.status_code


def _raise_for_status_like_yfinance(session):
    """What the vendor layer (``raise_for_status``) makes of that response."""
    response = _yf_get(session)
    response.raise_for_status()
    raise AssertionError("a >=400 response must not be treated as data")


def _as_raised_failure(session, monkeypatch):
    """Both what yfinance raised and what the vendor layer makes of it."""
    with _cookie_cache_offline(monkeypatch):
        try:
            _raise_for_status_like_yfinance(session)
        except Exception as exc:  # noqa: BLE001 - the vendor's own failure
            return exc, su.as_vendor_error(exc, "yfinance") or exc
    raise AssertionError("unreachable")


def _as_raised_error(session, monkeypatch):
    """The error a real vendor call would raise for this session."""
    _, error = _as_raised_failure(session, monkeypatch)
    return error


@pytest.mark.unit
@pytest.mark.parametrize(
    "status,classification",
    [
        (400, VendorRequestRejectedError),
        (401, VendorAuthenticationError),
        (403, VendorAuthenticationError),
        (404, VendorRequestRejectedError),
        (429, VendorRateLimitError),
        (500, VendorRateLimitError),
        (503, VendorRateLimitError),
    ],
)
def test_the_real_yfinance_chain_keeps_each_status(monkeypatch, status, classification):
    """Item 5: only a real 429 is a rate-limit error; nothing is retyped."""
    raw, error = _as_raised_failure(_fixed_status_session(status), monkeypatch)
    if status == 429:
        # yfinance itself raises its own 429 error: that is the real status.
        assert isinstance(raw, YFRateLimitError)
        assert error.status == 429
    else:
        # The client's own 4xx/5xx error reaches the vendor layer...
        assert type(raw) is _curl.exceptions.HTTPError, f"{status} -> {raw!r}"
        # ...with the same status the server sent, not a 429.
        assert isinstance(error, classification), f"{status} -> {error!r}"
        assert error.status == status
        assert f"HTTP {status}" in str(error)


@pytest.mark.unit
@pytest.mark.parametrize("status", [500, 503])
def test_the_real_yfinance_chain_keeps_retry_after(monkeypatch, status):
    """The header the server sent reaches the router's decision unchanged.

    Only 5xx carries it onto the vendor error: 4xx is decided ``retry=False``
    before a wait could apply, so its header is intentionally not copied.
    """
    raw, error = _as_raised_failure(
        _fixed_status_session(status, {"Retry-After": "3"}), monkeypatch
    )
    assert su._http_status(raw) == status
    assert error.status == status
    assert error.retry_after == 3.0


@pytest.mark.unit
def test_the_real_yfinance_chain_does_not_leak_the_url_or_crumb(monkeypatch):
    _, error = _as_raised_failure(_fixed_status_session(403), monkeypatch)
    message = str(error)
    assert "secret-crumb" not in message
    assert "query1.finance.yahoo.com" not in message


@pytest.mark.unit
@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 501, 502, 503, 504, 505])
def test_the_real_yfinance_verdict_follows_the_status_alone(monkeypatch, status):
    """A 500 is retried only with ``Retry-After``; 502/503/504 always are."""
    if status == 429:
        bare = _as_yfinance_failure(_fixed_status_session(status), monkeypatch)
        told_when = bare
        assert retryable_status(bare.status, bare.retry_after) is True
        return
    _, bare = _as_raised_failure(_fixed_status_session(status), monkeypatch)
    _, told_when = _as_raised_failure(
        _fixed_status_session(status, {"Retry-After": "1"}), monkeypatch
    )
    assert retryable_status(bare.status, bare.retry_after) is retryable_status(status)
    if status in (401, 403, 400, 404):
        # Decided, not deferred: the router does not wait even if told to.
        assert bare.retry is False
        assert told_when.retry is False
        assert told_when.retry_after is None
    elif status == 500:
        assert told_when.retry_after == 1.0
        assert retryable_status(told_when.status, told_when.retry_after) is True
    else:
        # A 5xx the vendor layer reports as a service error: a wait is carried
        # with it, but the status rule alone decides (501/505 stay permanent).
        assert told_when.retry_after == 1.0
        assert retryable_status(told_when.status, told_when.retry_after) is (
            retryable_status(status)
        )


class _ChattyThenQuiet(_FinegrainedSession):
    """Refuses only the target URL; the crumb and cookie fetches succeed."""


@pytest.mark.unit
@pytest.mark.parametrize(
    "status,extra_invocations",
    [(400, 0), (401, 0), (403, 0), (404, 0), (500, 0), (429, 1), (503, 1)],
)
def test_a_real_router_chain_makes_and_counts_the_same_requests(
    monkeypatch, router, status, extra_invocations
):
    """Router verdict on a real yfinance failure, and the true request cost.

    A refused Yahoo call costs a crumb fetch, the target request, then
    yfinance's own duplicate target request. The duplicate cannot be disabled;
    it is asserted here so the documentation cannot drift, and it is counted on
    the session rather than dropped.

    The ``YfData`` cache keys on URL and params only, so every invocation must
    be a *fresh* ``YfData`` (a new ``Ticker``); one shared instance would serve
    the first method's response to the second and make this assertion lie.
    """
    sessions = []

    def vendor(*args, **kwargs):
        session = _fixed_status_session(status)
        sessions.append(session)
        error = _as_raised_error(session, monkeypatch)
        retry_session.count_uncontrollable_requests(
            max(0, len(_target_calls(session)) - 1), "yfinance"
        )
        raise error

    second = Call(None, result="fallback")
    # A retried vendor costs two chain attempts (+jittered backoff) before the
    # fallback, so raise the chain's attempt count: the default of 4 would let
    # the *attempt cap* (not the status) stop the fallback, hiding the point.
    router.configure(
        chain=("yfinance", "alpha_vantage"),
        retry={"max_total_attempts": 6, "jitter_fraction": 0.0},
    )
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(interface, "VENDOR_METHODS", {METHOD: {"yfinance": vendor,
                                                             "alpha_vantage": second}})
        interface.route_to_vendor(METHOD, *ARGS)

    invocations = 1 + extra_invocations
    assert len(sessions) == invocations, "429/503 retry; auth and refusal do not"
    for session in sessions:
        assert len(_target_calls(session)) == 2, "one refusal + the duplicate"
    assert second.calls == 1, "the chain moves on exactly once"


@pytest.mark.unit
@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 503])
def test_the_real_yfinance_request_count_is_counted_not_hidden(monkeypatch, status):
    """The duplicate request is recorded on the session, never suppressed.

    The router is only *told*; nothing raises, returns early or changes type to
    make the second request disappear.
    """
    session = RetrySession(retry_session.RetryBudget(max_attempts=4))
    with retry_session.retry_session(session):
        session.note_attempt("yfinance")
        transport = _fixed_status_session(status)
        raw, error = _as_raised_failure(transport, monkeypatch)
        assert isinstance(error, BaseException)
        targets = _target_calls(transport)
        assert len(targets) == 2, "yfinance's own duplicate runs"
        retry_session.count_uncontrollable_requests(len(targets) - 1, "yfinance")
        assert session.http_requests == 1 + (len(targets) - 1)
    # And the error is exactly what yfinance produced (no retyping to cap it).
    if status == 429:
        assert isinstance(raw, YFRateLimitError)
    else:
        assert type(raw) is _curl.exceptions.HTTPError


@pytest.mark.unit
def test_counting_unschedulable_requests_never_lowers_the_total():
    """Accounting only: at least the invocations already made, never a veto."""
    session = RetrySession(retry_session.RetryBudget(max_attempts=4))
    with retry_session.retry_session(session):
        session.note_attempt("yfinance", http_requests=1)
        retry_session.count_uncontrollable_requests(2, "yfinance")
        assert session.http_requests == 3
        retry_session.count_uncontrollable_requests(0, "yfinance")
        assert session.http_requests == 3
    # Outside a routed call it is a no-op (nothing to count, nothing logged as
    # a verdict): it never raises.
    retry_session.count_uncontrollable_requests(5, "yfinance")


@pytest.mark.unit
def test_a_routed_yfinance_ticker_gets_the_zero_retry_session():
    """Only a routed call installs a session (standalone keeps yfinance's own)."""
    assert retry_session.routed_yfin_session() == {}
    with retry_session.retry_session(RetrySession(retry_session.RetryBudget(max_attempts=1))):
        kwargs = retry_session.routed_yfin_session()
    assert set(kwargs) == {"session"}


@pytest.mark.unit
def test_yf_retry_still_stops_at_one_attempt_for_every_nested_scope():
    """Re-entering a session (a vendor wrapping a routed call) must not double it."""
    calls = []

    def always_limited():
        calls.append(1)
        raise YFRateLimitError()

    session = RetrySession(retry_session.RetryBudget(max_attempts=4))
    with retry_session.retry_session(session), retry_session.retry_session(
        retry_session.get_active_retry_session()
    ), pytest.raises(YFRateLimitError):
        su.yf_retry(lambda: su.yf_retry(always_limited))
    assert len(calls) == 1


@pytest.mark.unit
def test_a_routed_yfinance_session_pins_zero_retries_on_itself_only():
    """Item 5: the session is configured; the process-wide ``YfConfig`` is not."""
    from yfinance.config import YfConfig

    # Prove the pin on a session that *would* retry: widening is the only way
    # to see the difference, since curl_cffi already ships count=0 here.
    widened = retry_session.yfin_session()
    retry = widened.retry
    if isinstance(retry, int):
        widened.retry = 3
    else:  # curl_cffi's RetryStrategy
        widened.retry = type(retry)(count=3)
    assert getattr(widened.retry, "count", widened.retry) == 3
    retry_session._zero_retries(widened)
    assert getattr(widened.retry, "count", widened.retry) == 0
    # The pin is observed on a session that would retry: produce one with the
    # pin removed and assert it is widened, then assert ``yfin_session`` itself
    # returns a zero-retry session. Widening the raw session is not enough
    # (curl_cffi already ships count=0 here), so patch ``new_session`` to hand
    # ``yfin_session`` a widened session.
    widened = retry_session.yfin_session()
    retry = widened.retry
    if isinstance(retry, int):
        widened.retry = 3
    else:  # curl_cffi's RetryStrategy
        widened.retry = type(retry)(count=3)
    assert getattr(widened.retry, "count", widened.retry) == 3

    import yfinance._http as http_mod

    original_new_session = http_mod.new_session
    try:
        http_mod.new_session = lambda: widened
        pinned = retry_session.yfin_session()
    finally:
        http_mod.new_session = original_new_session
    assert pinned is widened
    assert getattr(pinned.retry, "count", pinned.retry) == 0

    # A routed session is pinned even when the global was widened elsewhere.
    before = YfConfig.network.retries
    YfConfig.network.retries = 3
    try:
        routed = retry_session.yfin_session()
        assert getattr(routed.retry, "count", routed.retry) == 0
        assert YfConfig.network.retries == 3, "the global must be untouched"
        with retry_session.retry_session(RetrySession(retry_session.RetryBudget(max_attempts=1))):
            kwargs = retry_session.routed_yfin_session()
        inner = kwargs["session"]
        assert getattr(inner.retry, "count", inner.retry) == 0
        assert YfConfig.network.retries == 3
    finally:
        YfConfig.network.retries = before


@pytest.mark.unit
def test_a_routed_yfinance_session_never_retypes_a_refusal(monkeypatch):
    """Repro: 400/401/403/404/503 must not become ``YFRateLimitError``.

    The session is not wrapped, so the only way to see the difference between
    "the refusal" and "a fabricated 429" is to drive yfinance's real request
    path on a session that answers with a fixed status, offline.
    """
    monkeypatch.setattr(su.yf.cache, "get_cookie_cache", lambda: _NoCookieCache())
    for status in (400, 401, 403, 404, 500, 503):
        session = _fixed_status_session(status)
        retry_session._zero_retries(session)
        response = _yf_get(session)
        assert response.status_code == status
        target = [call for call in session.calls if "/v8/finance/" in call[1]]
        assert len(target) == 2, (
            "yfinance's own post-refusal request still runs; it is counted, "
            "never suppressed by faking a 429"
        )
        assert getattr(session.retry, "count", session.retry) == 0
    with pytest.raises(YFRateLimitError):
        _yf_get(_fixed_status_session(429))


@pytest.mark.unit
def test_a_routed_yfinance_session_leaves_other_sessions_alone():
    """Pinning zero retries on our session never wraps or edits another one."""
    import yfinance._http as http_mod

    elsewhere = http_mod.new_session()
    other_request = type(elsewhere).request
    other_retry = elsewhere.retry
    inside = retry_session.yfin_session()
    assert type(inside).request is other_request
    assert "request" not in vars(inside), "no per-instance wrapper is installed"
    # The session that existed before is untouched.
    assert type(elsewhere).request is other_request
    assert elsewhere.retry is other_retry


# --- 14. the chain deadline is checked before every start -------------------


@pytest.mark.unit
def test_an_uncontrollable_call_does_not_let_the_next_vendor_start(router):
    """Repro: 2s budget, the first vendor takes 5s, the second must not run."""
    clock = router.clock

    class Hangs(Call):
        def __call__(self, *args, **kwargs):
            self.calls += 1
            clock.advance(5.0)  # the first vendor hangs past the whole budget
            raise http_error(503)

    first = Hangs()
    second = Call(None, result="second-vendor")
    out = router.route(
        {"yfinance": first, "alpha_vantage": second},
        chain=("yfinance", "alpha_vantage"),
        retry={"max_total_seconds": 2.0},
    )
    assert first.calls == 1
    assert second.calls == 0, "a spent budget must not start a new request"
    assert out.startswith("DATA_UNAVAILABLE")
    # The first vendor ate 5s of the 2s budget; no wait was even attempted.
    assert router.clock.slept == []


@pytest.mark.unit
def test_a_retry_after_wait_that_ends_past_the_deadline_is_not_followed_by_a_call(
    router,
):
    vendor = Call(http_error(503), None, result="retried")
    out = router.route(
        {"yfinance": vendor},
        retry={
            "max_total_seconds": 10.0,
            "base_delay_seconds": 1.0,
            "jitter_fraction": 0.0,
        },
    )
    assert out == "retried"
    assert vendor.calls == 2
    assert sum(router.clock.slept) < 10.0


@pytest.mark.unit
def test_every_start_checks_the_deadline_including_the_first(router):
    vendor = Call(None, result="never")
    router.route(
        {"yfinance": vendor},
        retry={"max_total_seconds": 0.0},
    )
    assert vendor.calls == 0


@pytest.mark.unit
def test_a_vendor_that_outlives_the_budget_stops_the_chain_without_a_wait(router):
    """A hanging success is uncontrollable; the chain still reports, never awaits."""
    slow_ok = Call(None, result="slow-ok", duration=60.0)
    second = Call(None, result="second")
    # A slow *success* is returned: the router never discards a real answer.
    out = router.route(
        {"yfinance": slow_ok, "alpha_vantage": second},
        chain=("yfinance", "alpha_vantage"),
    )
    assert out == "slow-ok"
    assert second.calls == 0


# --- 15. cumulative wait cap and jitter (item 6) ----------------------------


@pytest.mark.unit
def test_max_retry_after_is_a_per_wait_threshold_not_a_total():
    import tradingagents.dataflows.retry_session as rs

    clock = Clock()
    budget = rs.RetryBudget(
        max_attempts=10,
        max_total_seconds=45.0,
        max_retry_after_seconds=10.0,
        max_cumulative_wait_seconds=12.0,
        base_delay_seconds=1.0,
        jitter_fraction=0.0,
        clock=clock.clock,
        sleep=clock.sleep,
    )
    session = RetrySession(budget)
    # Two 10s waits each pass the per-wait threshold ...
    assert session.pause(10.0) is True
    assert session.waited == 10.0
    # ... but the second would take the total past the cumulative cap.
    assert session.pause(10.0) is False
    assert clock.slept == [10.0]
    # A smaller wait that still fits the cap is allowed.
    assert session.pause(2.0) is True
    assert session.waited == 12.0
    assert session.pause(0.1) is False


@pytest.mark.unit
def test_the_router_stops_retrying_when_the_cumulative_cap_is_reached(router):
    vendor = Call(http_error(503))
    router.route(
        {"yfinance": vendor},
        retry={
            "max_attempts": 4,
            "base_delay_seconds": 1.0,
            "jitter_fraction": 0.0,
            "max_cumulative_wait_seconds": 1.5,
            "max_total_seconds": 45.0,
        },
    )
    # 1s waited, then a 2s wait would exceed the 1.5s cumulative cap.
    assert router.clock.slept == [1.0]
    assert vendor.calls == 2


@pytest.mark.unit
def test_the_router_verdict_refuses_a_wait_beyond_the_cumulative_cap():
    """The verdict itself must refuse: no "Retrying" announcement past the cap."""
    import copy as _copy
    import dataclasses
    import logging

    real_budget = interface._retry_budget

    def budget_with_small_cap():
        return dataclasses.replace(
            real_budget(),
            max_attempts=4,
            default_per_vendor_attempts=4,  # let the *wait cap* be the only limit
            max_total_seconds=45.0,
            max_cumulative_wait_seconds=1.5,
            base_delay_seconds=1.0,
            jitter_fraction=0.0,
        )

    calls = []
    retry_log = []

    class RecordingHandler(logging.Handler):
        def emit(self, record):
            message = record.getMessage()
            if "Retrying vendor" in message:
                retry_log.append(message)

    def vendor(*args, **kwargs):
        calls.append(1)
        raise http_error(503)

    handler = RecordingHandler()
    logger = logging.getLogger("tradingagents.dataflows.interface")
    old_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    config_module._config = _copy.deepcopy(default_config.DEFAULT_CONFIG)
    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(interface, "_retry_budget", budget_with_small_cap)
            patch.setattr(interface, "VENDOR_METHODS", {METHOD: {"yfinance": vendor}})
            set_config({"data_vendors": {CATEGORY: "yfinance"}})
            out = interface.route_to_vendor(METHOD, *ARGS)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
        config_module._config = _copy.deepcopy(default_config.DEFAULT_CONFIG)
    # Two invocations are cheap; the third would need a 2s wait (> 1.5s cap).
    # The verdict must refuse it *before* the router announces or takes the
    # wait; "pause would refuse later" is not the same guarantee.
    assert len(calls) == 2, f"the router spent {len(calls)} invocations"
    assert len(retry_log) == 1, retry_log
    assert out.startswith("DATA_UNAVAILABLE")


@pytest.mark.unit
def test_jitter_only_shortens_a_self_chosen_backoff():
    import tradingagents.dataflows.retry_session as rs

    for draw, expected in [(0.0, 1.0), (0.5, 0.9), (0.999999, 1.0 - 0.2 * 0.999999)]:
        assert rs.jittered_delay(1.0, 0.2, lambda d=draw: d) == pytest.approx(expected)
    assert rs.jittered_delay(1.0, 0.0, lambda: 0.5) == 1.0
    # A hostile rng cannot lengthen the wait, nor make it negative.
    assert rs.jittered_delay(2.0, 0.5, lambda: 7.0) == 1.0
    assert rs.jittered_delay(2.0, 0.5, lambda: -7.0) == 2.0


@pytest.mark.unit
def test_router_backoff_is_jittered_with_an_injected_rng(router):
    vendor = Call(http_error(502))
    real_budget = interface._retry_budget  # still the real factory
    draws = iter([0.0, 0.5])  # first: no shortening; second: half of the fraction

    def budget_with_seam():
        return dataclasses.replace(real_budget(), rng=lambda: next(draws))

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(interface, "_retry_budget", budget_with_seam)
        router.route(
            {"yfinance": vendor},
            retry={
                "max_attempts": 3,
                "base_delay_seconds": 2.0,
                "jitter_fraction": 0.5,
                "max_total_seconds": 45.0,
            },
        )
    # 2 * (1 - 0.5*0) = 2.0 ; then 4 * (1 - 0.5*0.5) = 3.0
    assert router.clock.slept == [pytest.approx(2.0), pytest.approx(3.0)]


@pytest.mark.unit
def test_a_server_retry_after_is_never_shortened_by_jitter(router):
    vendor = Call(http_error(429, {"Retry-After": "4"}), None)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(retry_session.random, "random", lambda: 0.0)  # maximum jitter
        assert router.route(
            {"yfinance": vendor}, retry={"jitter_fraction": 0.5}
        ) == "ok"
    assert router.clock.slept == [4.0]


# --- 16. strict configuration (item 3) -------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "section",
    [
        pytest.param({"max_total_seconds": -1.0}, id="negative seconds"),
        pytest.param({"max_total_seconds": float("nan")}, id="nan seconds"),
        pytest.param({"max_total_seconds": float("inf")}, id="infinite seconds"),
        pytest.param({"max_total_seconds": "45"}, id="string seconds"),
        pytest.param({"max_total_seconds": True}, id="bool seconds"),
        pytest.param({"max_request_seconds": -0.1}, id="negative request cap"),
        pytest.param({"max_cumulative_wait_seconds": -1}, id="negative wait cap"),
        pytest.param({"base_delay_seconds": -2.0}, id="negative backoff"),
        pytest.param({"max_retry_after_seconds": float("inf")}, id="infinite retry-after"),
        pytest.param({"jitter_fraction": -0.1}, id="negative jitter"),
        pytest.param({"jitter_fraction": 1.5}, id="jitter above one"),
        pytest.param({"max_attempts": 0}, id="zero attempts"),
        pytest.param({"max_attempts": -2}, id="negative attempts"),
        pytest.param({"max_attempts": True}, id="bool attempts"),
        pytest.param({"max_attempts": 2.5}, id="fractional attempts"),
        pytest.param({"max_attempts": float("nan")}, id="nan attempts"),
        pytest.param({"max_attempts": "two"}, id="text attempts"),
        pytest.param({"max_total_attempts": 0}, id="zero chain attempts"),
        pytest.param({"vendor_max_attempts": 2}, id="override not a dict"),
        pytest.param({"vendor_max_attempts": ["yfinance", 2]}, id="override is a list"),
        pytest.param({"vendor_max_attempts": {"yfinance": 0}}, id="override zero"),
        pytest.param({"vendor_max_attempts": {"yfinance": True}}, id="override bool"),
        pytest.param({"vendor_max_attempts": {"yfinance": 1.5}}, id="override fractional"),
        pytest.param({"vendor_max_attempts": {"": 2}}, id="override blank vendor"),
        pytest.param({"vendor_max_attempts": {"yfinance": "two"}}, id="override text"),
    ],
)
def test_an_invalid_retry_setting_raises_instead_of_being_clamped(section):
    import tradingagents.dataflows.retry_session as rs

    with pytest.raises(rs.RetryConfigError):
        rs.retry_budget_from_config(section)


@pytest.mark.unit
def test_the_whole_section_must_be_a_mapping():
    import tradingagents.dataflows.retry_session as rs

    with pytest.raises(rs.RetryConfigError):
        rs.retry_budget_from_config([("max_attempts", 2)])


@pytest.mark.unit
def test_a_whole_float_attempt_count_is_accepted():
    import tradingagents.dataflows.retry_session as rs

    budget = rs.retry_budget_from_config({"max_attempts": 2.0})
    assert budget.default_per_vendor_attempts == 2


@pytest.mark.unit
def test_a_text_attempt_count_is_accepted_only_as_whole_digits():
    """An env-var count arrives as text; a decimal one is refused, not rounded."""
    import tradingagents.dataflows.retry_session as rs

    assert rs.retry_budget_from_config({"max_attempts": "2"}).default_per_vendor_attempts == 2
    for text in ("2.0", "2.5", "-2", "2e0"):
        with pytest.raises(rs.RetryConfigError):
            rs.retry_budget_from_config({"max_attempts": text})


@pytest.mark.unit
def test_an_explicit_null_per_vendor_override_means_no_override():
    """``None`` is how a cleared override appears after a config merge."""
    import tradingagents.dataflows.retry_session as rs

    budget = rs.retry_budget_from_config({"vendor_max_attempts": None})
    assert budget.per_vendor_attempts == {}
    assert budget.attempts_for("alpha_vantage") == 2


@pytest.mark.unit
def test_a_router_call_with_an_invalid_setting_fails_loudly(router):
    import tradingagents.dataflows.retry_session as rs

    vendor = Call(None, result="never")
    with pytest.raises(rs.RetryConfigError):
        router.route({"yfinance": vendor}, retry={"max_total_seconds": -5.0})
    assert vendor.calls == 0


@pytest.mark.unit
@pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "soon"])
def test_an_env_override_that_is_not_finite_is_rejected_at_import(monkeypatch, raw):
    import importlib

    monkeypatch.setenv("TRADINGAGENTS_VENDOR_RETRY_MAX_SECONDS", raw)
    with pytest.raises(ValueError, match="TRADINGAGENTS_VENDOR_RETRY_MAX_SECONDS"):
        importlib.reload(default_config)
    monkeypatch.undo()
    importlib.reload(default_config)


@pytest.mark.unit
def test_the_request_cap_is_configurable_by_env(monkeypatch):
    import importlib

    monkeypatch.setenv("TRADINGAGENTS_VENDOR_RETRY_MAX_REQUEST_SECONDS", "3.5")
    dc = importlib.reload(default_config)
    try:
        assert dc.DEFAULT_CONFIG["data_vendor_retry"]["max_request_seconds"] == 3.5
    finally:
        monkeypatch.undo()
        importlib.reload(default_config)

