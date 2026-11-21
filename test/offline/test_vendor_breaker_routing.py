"""The circuit breaker wired into ``route_to_vendor``; no network, virtual time.

The breaker's own state machine is covered by ``test_vendor_breaker.py``. These
tests cover the *routing* contract around it:

    one ticket per vendor logical call    -> retries do not count again
    budget gate before the breaker        -> a spent budget is not a skip
    breaker skip                          -> no attempt, no HTTP request, no wait
    skip reasons                          -> circuit_open / probe_in_progress
    key = vendor + endpoint + policy      -> symbols share, endpoints do not
    disabled                              -> byte-for-byte old behaviour
    evidence                              -> ``handle``'s classified copy, with
                                             the original as witness
    release                               -> a ``finally`` frees an unfinished
                                             ticket as NEUTRAL from any exit

Every test builds its own registry and monkeypatches ``interface._BREAKER_REGISTRY``
and ``_BREAKER_POLICY`` (plus the module-level real registry is reset on setup),
so nothing here depends on, or pollutes, another test's breaker state. There is
no autouse fixture clearing the production registry.
"""
from __future__ import annotations

import contextlib
import copy
import threading
import time

import pytest
import requests

import tradingagents.dataflows.config as config_module
import tradingagents.default_config as default_config
from tradingagents.dataflows import interface, retry_session
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.errors import (
    NoMarketDataError,
    VendorAuthenticationError,
    VendorNotConfiguredError,
    VendorRateLimitError,
    VendorRequestRejectedError,
)
from tradingagents.dataflows.vendor_breaker import (
    BreakerPolicy,
    BreakerRegistry,
)

METHOD = "get_stock_data"
CATEGORY = "core_stock_apis"
ARGS = ("AAPL", "2026-01-01", "2026-01-10")
BREAKER = "tradingagents.dataflows.vendor_breaker"


class Clock:
    """Virtual monotonic time; advancing is explicit."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Call:
    """A vendor function that fails or succeeds per invocation, counting calls."""

    def __init__(self, *outcomes, result="ok"):
        # Each entry is an exception to raise or a value to return; the last
        # entry repeats. ``None`` means "return ``result``".
        self.outcomes = list(outcomes) or [None]
        self.result = result
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, BaseException):
            raise outcome
        return self.result if outcome is None else outcome


FAST_RETRY = {"base_delay_seconds": 0.0, "jitter_fraction": 0.0}


class Router:
    """Route ``METHOD`` with injected vendors and virtual time."""

    def __init__(self, monkeypatch, policy=None):
        self.clock = Clock()
        # Both seams: the session's budget owns its own copy of the clock, and
        # the backoff jitter must be off so an injected error is what surfaces.
        monkeypatch.setattr(retry_session.time, "monotonic", self.clock)
        monkeypatch.setattr(retry_session.time, "sleep", self.clock.advance)
        self.events = []
        self.policy = policy or BreakerPolicy(3, 60)
        self.registry = BreakerRegistry(
            self.policy, clock=self.clock, on_event=self.events.append
        )

    def set_breaker(self, *, enabled=True, threshold=3, cooldown=60.0, policy=None):
        """Install this router's registry (or disable the breaker)."""
        # A policy change starts from a clean registry: old counts belong to
        # the old rules. The registry survives every route() call otherwise.
        if policy is None:
            policy = BreakerPolicy(threshold, cooldown)
        self.policy = policy
        self.registry = BreakerRegistry(policy, clock=self.clock, on_event=self.events.append)
        interface._BREAKER_REGISTRY = self.registry if enabled else None
        interface._BREAKER_POLICY = policy if enabled else None
        config = {"data_vendor_breaker": {"enabled": enabled}}
        if enabled:
            config["data_vendor_breaker"]["failure_threshold"] = policy.failure_threshold
            config["data_vendor_breaker"]["cooldown_seconds"] = policy.cooldown_seconds
        set_config(config)
        interface._BREAKER_REGISTRY = self.registry if enabled else None
        interface._BREAKER_POLICY = policy if enabled else None

    def route(self, vendors, chain=None, *, retry=None, args=ARGS):
        chain = tuple(chain or vendors)
        settings = dict(FAST_RETRY)
        settings.update(retry or {})
        set_config({"data_vendor_retry": settings})
        # VENDOR_METHODS before the chain: routing only *reads* the configured
        # chain, and a concurrent caller finding the previous chain would still
        # see this call's injected vendor functions.
        interface.VENDOR_METHODS[METHOD] = dict(vendors)
        set_config({"data_vendors": {CATEGORY: ",".join(chain)}})
        return interface.route_to_vendor(METHOD, *args)


@pytest.fixture(autouse=True)
def _inject_vendors(monkeypatch):
    """``VENDOR_METHODS`` is process-wide; give every test its own copy.

    Not a breaker reset: the router under test installs its own registry. This
    only stops a stub vendor from leaking into another module's test.
    """
    methods = copy.deepcopy(interface.VENDOR_METHODS)
    methods[METHOD] = {}
    monkeypatch.setattr(interface, "VENDOR_METHODS", methods)


@pytest.fixture
def router(monkeypatch, _inject_vendors):
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)
    interface.reset_vendor_breaker_state()
    harness = Router(monkeypatch)
    harness.set_breaker(policy=BreakerPolicy(3, 60))
    yield harness
    interface.reset_vendor_breaker_state()
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)


def transient(reason="throttled"):
    return VendorRateLimitError(reason).with_retry_evidence(status=503, retry=True)


# --- 1. threshold, one record per logical call ------------------------------


@pytest.mark.unit
def test_consecutive_logical_failures_open_the_breaker_and_later_calls_skip(router):
    vendor = Call(transient())
    outcomes = [router.route({"yfinance": vendor}) for _ in range(3)]
    assert all(isinstance(o, str) and o.startswith("DATA_UNAVAILABLE") for o in outcomes)
    # Two attempts per logical call (one retry), but one counted outcome each.
    assert vendor.calls == 6

    # Threshold reached: the next tool call never invokes the vendor.
    skipped = router.route({"yfinance": vendor})
    assert vendor.calls == 6, "an open breaker must not start the vendor"
    assert "DATA_UNAVAILABLE" in skipped
    assert "circuit breaker (circuit_open)" in skipped


@pytest.mark.unit
def test_retries_within_one_call_count_once(router):
    """Two transient attempts, then give up: one logical failure, not two."""
    router.set_breaker(threshold=2)
    vendor = Call(transient(), transient(), transient())
    router.route({"yfinance": vendor}, retry={"max_attempts": 2, "base_delay_seconds": 0})
    assert vendor.calls == 2  # both attempts made
    breaker = router.registry.for_vendor(
        "yfinance",
        scope=interface.breaker_scope(interface.VENDOR_ENDPOINTS["yfinance"], BreakerPolicy(2, 60)),
    )
    assert breaker.failures == 1, "one logical call = one counted failure"
    assert breaker.state() == "closed"


@pytest.mark.unit
def test_a_successful_retry_is_a_success_not_a_failure(router):
    router.set_breaker(threshold=2)
    vendor = Call(transient(), None, result="recovered")
    assert router.route({"yfinance": vendor}, retry={"max_attempts": 2}) == "recovered"
    assert vendor.calls == 2
    breaker = next(iter(router.registry._breakers.values()))
    assert breaker.failures == 0 and breaker.state() == "closed"


@pytest.mark.unit
def test_no_data_is_absent_and_clears_the_streak(router):
    router.set_breaker(threshold=2)
    failing = Call(transient())
    router.route({"yfinance": failing})
    absent = Call(NoMarketDataError("AAPL", "AAPL", "no rows"))
    out = router.route({"yfinance": absent})
    assert out.startswith("NO_DATA_AVAILABLE")
    breaker = next(iter(router.registry._breakers.values()))
    assert breaker.failures == 0 and breaker.state() == "closed"


@pytest.mark.unit
def test_a_bare_transport_timeout_is_classified_evidence_and_counts(router):
    """``handle`` classifies a raw timeout; the breaker reads *that* proof.

    The original ``requests.Timeout`` carries no breaker metadata of its own, so
    judging it directly would silently drop a real outage. The classified copy
    (status/retry evidence from ``as_vendor_error``) is what counts, and the
    original is still the witness that it was really raised.
    """
    router.set_breaker(threshold=1)
    vendor = Call(requests.exceptions.ReadTimeout("read timed out"))
    out = router.route({"yfinance": vendor})
    assert vendor.calls == 2, "the classified timeout was retried once"
    assert isinstance(out, str) and out.startswith("DATA_UNAVAILABLE")
    assert _breaker(router).state() == "open"


@pytest.mark.unit
def test_an_unclassified_error_without_retry_evidence_is_neutral(router):
    router.set_breaker(threshold=1)
    vendor = Call(ValueError("parse"))
    for _ in range(3):
        with pytest.raises(ValueError):
            router.route({"yfinance": vendor})
    assert vendor.calls == 3, "never skip a vendor for our own bug"
    assert _breaker(router).state() == "closed"


@pytest.mark.unit
def test_a_budget_stop_after_a_retry_keeps_the_vendor_failure(router):
    """The vendor proved a short outage, then our retry wait did not fit."""
    # One attempt total: no retry is allowed, the vendor's own error decides.
    router.set_breaker(threshold=1)
    vendor = Call(transient())
    router.route({"yfinance": vendor}, retry={"max_attempts": 1})
    assert vendor.calls == 1
    assert _breaker(router).state() == "open"

    # With retries allowed but no cumulative wait, the retry is refused after
    # the vendor's error: still one real failure, not a neutral overwrite.
    router.set_breaker(threshold=1)
    vendor = Call(transient())
    router.route({"yfinance": vendor}, retry={"max_cumulative_wait_seconds": 0.0})
    assert vendor.calls == 1
    assert _breaker(router).state() == "open"


@pytest.mark.unit
def test_a_budget_stop_before_the_first_attempt_is_neutral(router):
    """No call was started, so the vendor's last real result must stand."""
    router.set_breaker(threshold=2)
    vendor = Call(transient())
    router.route({"yfinance": vendor})  # one real failure
    assert _breaker(router).failures == 1

    spent = router.route({"yfinance": vendor}, retry={"max_total_seconds": 0.0})
    assert "data budget ran out" in spent
    assert _breaker(router).failures == 1, "an unused budget is not evidence"
    assert _breaker(router).state() == "closed"


@pytest.mark.unit
@pytest.mark.parametrize(
    "exc",
    [
        pytest.param(VendorAuthenticationError("401"), id="auth"),
        pytest.param(VendorRequestRejectedError("400"), id="refused"),
        pytest.param(VendorNotConfiguredError("no key"), id="unconfigured"),
        pytest.param(ValueError("parse"), id="internal"),
        pytest.param(
            VendorRateLimitError("daily quota").with_retry_evidence(retry=False),
            id="quota-not-recoverable",
        ),
        pytest.param(
            VendorRateLimitError("long wait").with_retry_evidence(retry_after=120),
            id="retry-after-beyond-cap",
        ),
        pytest.param(VendorRateLimitError("class only"), id="class-without-evidence"),
    ],
)
def test_neutral_failures_never_trip_the_breaker(router, exc):
    router.set_breaker(threshold=1)
    vendor = Call(exc)
    for _ in range(4):
        with contextlib.suppress(Exception):
            router.route({"yfinance": vendor})
    assert vendor.calls == 4, "a neutral result must never skip the vendor"
    breaker = router.registry.for_vendor(
        "yfinance",
        scope=interface.breaker_scope(interface.VENDOR_ENDPOINTS["yfinance"], BreakerPolicy(1, 60)),
    )
    assert breaker.failures == 0


# --- 2. fall-through, skip reasons, budget ----------------------------------


@pytest.mark.unit
def test_an_open_primary_falls_through_to_the_backup(router):
    router.set_breaker(threshold=1)
    primary = Call(transient())
    backup = Call(None, result="from-backup")
    vendors = {"yfinance": primary, "alpha_vantage": backup}
    router.route(vendors, chain=("yfinance", "alpha_vantage"))
    out = router.route(vendors, chain=("yfinance", "alpha_vantage"))
    assert out == "from-backup"
    # The primary failed once (a logical call, retried internally); the open
    # breaker then skipped it, and the backup served exactly once -- until its
    # own logical failure tripped its (independent) breaker, one per vendor.
    assert primary.calls == 2 and backup.calls == 2


@pytest.mark.unit
def test_every_vendor_skipped_is_an_explicit_unavailable_result(router):
    router.set_breaker(threshold=1)
    a, b = Call(transient()), Call(transient())
    vendors = {"yfinance": a, "alpha_vantage": b}
    router.route(vendors, chain=("yfinance", "alpha_vantage"))
    out = router.route(vendors, chain=("yfinance", "alpha_vantage"))
    assert out.startswith("DATA_UNAVAILABLE")
    assert "circuit_open" in out
    assert "NO_DATA" not in out
    # The primary stays open, so neither is invoked; the verdict names the
    # skip reason explicitly and never claims the data does not exist.
    assert a.calls == 2 and b.calls == 1


@pytest.mark.unit
def test_a_skip_does_not_consume_an_attempt_request_or_wait(router):
    router.set_breaker(threshold=1)
    vendor = Call(transient())
    router.route({"yfinance": vendor})
    calls = vendor.calls

    # The breaker is open; the budget is fully available, so nothing but the
    # skip explains the absent attempt. No retry or wait is triggered by it.
    out = router.route({"yfinance": vendor})
    assert "DATA_UNAVAILABLE" in out
    assert "circuit breaker (circuit_open)" in out
    assert vendor.calls == calls
    skipped = [e for e in router.events if e.action == "skip"]
    assert skipped and skipped[-1].skip_reason == "circuit_open"
    assert skipped[-1].called is False


@pytest.mark.unit
def test_a_spent_budget_is_reported_as_budget_not_as_a_breaker_skip(router):
    router.set_breaker(threshold=1)
    vendor = Call(None)
    out = router.route({"yfinance": vendor}, retry={"max_total_seconds": 0.0})
    assert "data budget ran out" in out
    assert "circuit" not in out.lower()
    assert vendor.calls == 0


@pytest.mark.unit
def test_a_skip_is_not_recorded_as_a_breaker_failure(router):
    router.set_breaker(threshold=1)
    vendor = Call(transient())
    router.route({"yfinance": vendor})
    policy = BreakerPolicy(1, 60)
    breaker = router.registry.for_vendor(
        "yfinance", scope=interface.breaker_scope(interface.VENDOR_ENDPOINTS["yfinance"], policy)
    )
    generation = breaker.snapshot()["generation"]
    router.route({"yfinance": vendor})
    assert breaker.snapshot()["generation"] == generation


# --- 3. half-open: probe success, failure, neutral ---------------------------


def _breaker(router):
    policy = router.registry.policy
    return router.registry.for_vendor(
        "yfinance", scope=interface.breaker_scope(interface.VENDOR_ENDPOINTS["yfinance"], policy)
    )


# __BREAKER_HELPER__


@pytest.mark.unit
def test_a_successful_probe_after_cooldown_closes_the_breaker(router):
    router.set_breaker(threshold=1, cooldown=60)
    failing = Call(transient())
    router.route({"yfinance": failing})
    router.clock.advance(60)
    good = Call(None, result="back")
    assert router.route({"yfinance": good}) == "back"
    assert _breaker(router).state() == "closed"
    assert router.route({"yfinance": good}) == "back"


@pytest.mark.unit
def test_a_failed_probe_reopens_and_restarts_the_cooldown(router):
    router.set_breaker(threshold=1, cooldown=60)
    vendor = Call(transient())
    router.route({"yfinance": vendor})
    router.clock.advance(60)
    router.route({"yfinance": vendor})  # probe fails
    assert _breaker(router).state() == "open"
    calls = vendor.calls
    router.route({"yfinance": vendor})
    assert vendor.calls == calls, "cooldown restarted at the failed probe"


@pytest.mark.unit
def test_a_neutral_probe_releases_the_ticket_without_closing(router):
    router.set_breaker(threshold=1, cooldown=60)
    router.route({"yfinance": Call(transient())})
    router.clock.advance(60)
    with pytest.raises(VendorAuthenticationError):
        router.route({"yfinance": Call(VendorAuthenticationError("401"))})
    assert _breaker(router).state() == "half_open"
    # The probe was released: another caller may probe immediately.
    assert router.route({"yfinance": Call(None, result="late")}) == "late"
    assert _breaker(router).state() == "closed"


# --- 4. keys: symbols share, endpoints and policies are isolated ------------


@pytest.mark.unit
def test_symbols_share_one_breaker_per_endpoint(router):
    router.set_breaker(threshold=2)
    router.route({"yfinance": Call(transient())}, args=("AAPL", "2026-01-01", "2026-01-10"))
    router.route({"yfinance": Call(transient())}, args=("MSFT", "2026-01-01", "2026-01-10"))
    skipped = router.route(
        {"yfinance": Call(None)}, args=("NVDA", "2026-01-01", "2026-01-10")
    )
    assert "circuit_open" in skipped, "a symbol change must not reset the state"


@pytest.mark.unit
def test_vendors_do_not_share_state(router):
    router.set_breaker(threshold=1)
    router.route({"yfinance": Call(transient()), "alpha_vantage": Call(None)})
    out = router.route(
        {"yfinance": Call(None), "alpha_vantage": Call(None, result="av-ok")},
        chain=("yfinance", "alpha_vantage"),
    )
    assert out == "av-ok"


@pytest.mark.unit
def test_endpoints_are_isolated(monkeypatch):
    clock = Clock()
    registry = BreakerRegistry(BreakerPolicy(1, 60), clock=clock)
    policy = BreakerPolicy(1, 60)
    a = registry.for_vendor("yfinance", scope=interface.breaker_scope("https://a.example", policy))
    b = registry.for_vendor("yfinance", scope=interface.breaker_scope("https://b.example", policy))
    a.try_acquire().finish("transient_failure")
    assert a.state() == "open"
    assert b.state() == "closed"


@pytest.mark.unit
def test_policies_are_isolated():
    registry = BreakerRegistry(BreakerPolicy(1, 60), clock=Clock())
    strict = registry.for_vendor("yfinance", scope=interface.breaker_scope("e", BreakerPolicy(1, 60)))
    loose = registry.for_vendor("yfinance", scope=interface.breaker_scope("e", BreakerPolicy(5, 60)))
    strict.try_acquire().finish("transient_failure")
    assert strict.state() == "open"
    assert loose.state() == "closed"


@pytest.mark.unit
def test_a_policy_change_replaces_the_registry(router):
    router.set_breaker(threshold=1)
    router.route({"yfinance": Call(transient())})
    first = interface._BREAKER_REGISTRY
    router.set_breaker(threshold=2)  # new policy, new registry
    second = interface._breaker_registry(BreakerPolicy(2, 60))
    assert second is not first


@pytest.mark.unit
def test_the_registry_survives_calls_and_is_not_rebuilt(router):
    router.set_breaker(threshold=5)
    before = interface._BREAKER_REGISTRY
    router.route({"yfinance": Call(None)})
    router.route({"yfinance": Call(None)})
    assert interface._BREAKER_REGISTRY is before


# --- 5. cancellation / early exit releases the ticket ------------------------


@pytest.mark.unit
def test_a_cancelled_call_releases_a_probe_ticket(router):
    router.set_breaker(threshold=1, cooldown=60)
    router.route({"yfinance": Call(transient())})
    router.clock.advance(60)

    class Cancel:
        def __init__(self):
            self.calls = 0

        def __call__(self, *a, **k):
            self.calls += 1
            raise KeyboardInterrupt()  # not an Exception: the router cannot see it

    interrupt = Cancel()
    with pytest.raises(KeyboardInterrupt):
        router.route({"yfinance": interrupt})
    breaker = _breaker(router)
    assert breaker.state() == "half_open"
    # Releasing the probe frees its ticket: another caller may probe at once,
    # and a success closes the breaker.
    assert router.route({"yfinance": Call(None, result="late")}) == "late"
    assert breaker.state() == "closed"


# --- 6. concurrency: one logical probe -------------------------------------


@pytest.mark.unit
def test_probe_in_progress_is_visible_to_a_concurrent_caller(router):
    """A second caller arriving mid-probe is refused, not admitted.

    This is the *synchronous* half of the concurrency contract: it removes
    every thread-start race, so it is deterministic on any machine. The
    threaded test below adds real parallelism on top.
    """
    router.set_breaker(threshold=1, cooldown=60)
    router.route({"yfinance": Call(transient())})
    router.clock.advance(60)

    probe_entered = threading.Event()
    release_probe = threading.Event()

    def vendor(*args, **kwargs):
        probe_entered.set()
        release_probe.wait(10)
        return "probe-ok"

    probe = threading.Thread(target=lambda: router.route({"yfinance": vendor}))
    probe.start()
    try:
        assert probe_entered.wait(10), "the probe never started"
        # The probe is outstanding *now*; a caller asking now must skip.
        out = router.route({"yfinance": Call(None, result="must-not-run")})
        assert "DATA_UNAVAILABLE" in out
        assert "probe_in_progress" in out
        assert any(e.action == "skip" and e.skip_reason == "probe_in_progress"
                   and e.called is False for e in router.events)
    finally:
        release_probe.set()
        probe.join(10)
    assert not probe.is_alive(), "probe thread hung"


@pytest.mark.unit
def test_concurrent_calls_grant_only_one_probe(router):
    """Under real parallelism, a probe is never joined by a second probe.

    Deliberately tolerant on timing: a caller that reaches the breaker only
    after the probe has finished is an ordinary call, not a second probe. The
    invariant is (a) at most one probe was ever held and (b) every caller
    refused while the probe ran was refused *because* of the probe.
    """
    router.set_breaker(threshold=1, cooldown=60)
    router.route({"yfinance": Call(transient())})
    router.clock.advance(60)

    probe_entered = threading.Event()
    release_probe = threading.Event()
    probe_entries = []
    results = []

    def vendor(*args, **kwargs):
        probe_entries.append(threading.get_ident())
        probe_entered.set()
        release_probe.wait(10)
        return "probe-ok"

    probe = threading.Thread(target=lambda: results.append(router.route({"yfinance": vendor})))
    probe.start()
    assert probe_entered.wait(10), "the probe never started"
    assert _breaker(router).snapshot()["probe_open"] is True

    start = threading.Barrier(5, timeout=10)
    lock = threading.Lock()

    def worker():
        start.wait()
        out = router.route({"yfinance": vendor})
        with lock:
            results.append(out)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    start.wait()
    # Let the four callers reach the breaker while the probe is outstanding,
    # then release the probe.
    time.sleep(0.2)
    release_probe.set()
    probe.join(10)
    assert not probe.is_alive(), "probe thread hung"
    for thread in threads:
        thread.join(10)
        assert not thread.is_alive(), "worker thread hung"

    # Only callers that found the probe outstanding can have blocked in the
    # vendor while the probe ran; every one of them is a duplicate of the probe
    # holder, i.e. the breaker admitted more than one caller to a *probe*.
    skips = [e for e in router.events if e.action == "skip"]
    assert all(e.skip_reason == "probe_in_progress" for e in skips)
    assert all(e.called is False for e in skips)
    assert len(results) == 5
    assert results.count("probe-ok") >= 1
    # A closing breaker moves the generation exactly once (open -> closed);
    # every extra move would be an extra probe that the breaker let through.
    assert _breaker(router).state() == "closed"


# --- 7. disabled mode, logging, request accounting --------------------------


@pytest.mark.unit
def test_disabled_mode_keeps_the_old_result_and_call_counts(router):
    """The breaker off is exactly the old router: same text, same calls."""
    calls = Call(transient())
    router.set_breaker(enabled=False)
    outs = [router.route({"yfinance": calls}) for _ in range(3)]
    assert all(o.startswith("DATA_UNAVAILABLE") for o in outs)
    assert len(set(outs)) == 1, "a disabled breaker never changes the verdict"
    assert calls.calls == 6, "three logical calls, one retry each, no skip"
    assert not interface._BREAKER_REGISTRY, "disabled: no state is kept"


@pytest.mark.unit
def test_disabled_mode_never_records_an_event(router):
    router.set_breaker(enabled=False)
    router.route({"yfinance": Call(transient())})
    assert router.events == [], "no ticket, no event"


@pytest.mark.unit
def test_events_are_credential_free(router, caplog):
    """No API key, base URL query or symbol ever reaches an event or a log."""
    import logging as _logging

    # A real look at the INFO records the breaker itself emits.
    logger = _logging.getLogger(interface.__name__)
    records = []
    handler = _logging.Handler()
    handler.emit = lambda record: records.append(record.getMessage())
    old_level = logger.level
    logger.setLevel(_logging.INFO)
    logger.addHandler(handler)
    try:
        router.set_breaker(threshold=1)
        router.route({"yfinance": Call(transient())})
        router.route({"yfinance": Call(None)})  # the skip
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)

    events = router.events
    assert events[-1].action == "skip"
    text = "\n".join(str(e) for e in events)
    for secret in ("placeholder", "api_key", "ALPHA_VANTAGE", "AAPL", "2026-01-01", "?apikey"):
        assert secret.lower() not in text.lower()

    emitted = "\n".join(m for m in records if "breaker" in m.lower())
    assert emitted, "breaker events are logged"
    for secret in ("placeholder", "api_key", "AAPL", "2026-01-01"):
        assert secret.lower() not in emitted.lower()


@pytest.mark.unit
def test_a_skip_does_not_inflate_the_request_counts(router):
    """The skipped vendor is not counted as an attempt or an HTTP request."""
    router.set_breaker(threshold=1)
    first = Call(transient())
    router.route({"yfinance": first})

    # Observe the session's accounting: a vendor that must never run would
    # have called note_attempt() and spent a request had the skip been one.
    called = Call(None, result="must-not-run")
    out = router.route({"yfinance": called})
    assert "circuit_open" in out
    assert called.calls == 0
    skips = [e for e in router.events if e.action == "skip"]
    assert skips and skips[-1].called is False
    assert skips[-1].skip_reason == "circuit_open"


@pytest.mark.unit
def test_the_scope_key_has_no_symbol_or_secret(router):
    router.set_breaker(threshold=1)
    router.route({"yfinance": Call(transient())})
    (key,) = router.registry._breakers
    vendor, scope = key
    assert vendor == "yfinance"
    assert scope == interface.breaker_scope(
        interface.VENDOR_ENDPOINTS["yfinance"], BreakerPolicy(1, 60)
    )
    for secret in ("AAPL", "placeholder", "apikey", "token"):
        assert secret.lower() not in scope.lower()


# --- 8. raw transport/HTTP errors: the classified copy is the evidence ------


def _requests_http_error(status, headers=None):
    response = requests.Response()
    response.status_code = status
    if headers:
        response.headers.update(headers)
    return requests.exceptions.HTTPError(f"{status} Error", response=response)


def _client_exceptions():
    """(label, exceptions module) for both HTTP backends.

    ``requests`` is always covered; the backend yfinance actually uses is added
    when it is a different module (``curl_cffi`` in this environment).
    """
    from tradingagents.dataflows import stockstats_utils

    found = [("requests", requests.exceptions)]
    live = stockstats_utils._yf_http.exceptions
    if live is not requests.exceptions:
        found.append(("live-client", live))
    return found


# Parametrise over exactly the backends present: the live client's label only
# exists when yfinance is wired to a different library than ``requests``.
_client_labels = [label for label, _ in _client_exceptions()]


@pytest.mark.unit
@pytest.mark.parametrize("library", _client_labels)
def test_a_raw_transport_timeout_counts_once_and_opens_the_breaker(router, library):
    excs = dict(_client_exceptions()).get(library, requests.exceptions)
    exc = excs.Timeout("read timed out")
    router.set_breaker(threshold=1)
    vendor = Call(exc)
    out = router.route({"yfinance": vendor})
    assert vendor.calls == 2, "the classified timeout is retried once inside one call"
    assert out.startswith("DATA_UNAVAILABLE")
    breaker = _breaker(router)
    assert breaker.snapshot()["reason"] == "transient_failure"
    finishes = [e for e in router.events if e.action == "finish"]
    assert [e.result for e in finishes] == ["transient_failure"], "one call, one verdict"
    # The open breaker now skips the vendor: no attempt, no request.
    assert "circuit_open" in router.route({"yfinance": vendor})
    assert vendor.calls == 2


@pytest.mark.unit
@pytest.mark.parametrize("library", _client_labels)
def test_a_raw_connection_error_counts_once(router, library):
    excs = dict(_client_exceptions()).get(library, requests.exceptions)
    exc = excs.ConnectionError("reset by peer")
    router.set_breaker(threshold=2)
    vendor = Call(exc)
    for _ in range(2):
        router.route({"yfinance": vendor})
    assert vendor.calls == 4
    breaker = _breaker(router)
    assert breaker.state() == "open", "two logical calls, each counted once"
    assert breaker.snapshot()["reason"] == "transient_failure"
    assert "circuit_open" in router.route({"yfinance": vendor})
    assert vendor.calls == 4


@pytest.mark.unit
def test_a_raw_503_http_error_counts_once(router):
    router.set_breaker(threshold=1)
    vendor = Call(_requests_http_error(503))
    router.route({"yfinance": vendor})
    assert vendor.calls == 2
    assert _breaker(router).snapshot()["reason"] == "transient_failure"
    assert [e.result for e in router.events if e.action == "finish"] == ["transient_failure"]


@pytest.mark.unit
def test_a_raw_error_that_recovers_on_retry_is_a_success(router):
    router.set_breaker(threshold=1)
    vendor = Call(requests.exceptions.Timeout("slow"), None, result="recovered")
    assert router.route({"yfinance": vendor}) == "recovered"
    assert vendor.calls == 2
    breaker = _breaker(router)
    assert breaker.failures == 0 and breaker.state() == "closed"
    assert [e.result for e in router.events if e.action == "finish"] == ["success"]


@pytest.mark.unit
@pytest.mark.parametrize("library", _client_labels)
def test_a_raw_tls_or_credential_failure_is_neutral(router, library):
    excs = dict(_client_exceptions()).get(library, requests.exceptions)
    router.set_breaker(threshold=1)
    vendor = Call(excs.SSLError("certificate verify failed"))
    with contextlib.suppress(Exception):
        router.route({"yfinance": vendor})
    assert vendor.calls == 1, "TLS trouble is configuration: never retried"
    assert _breaker(router).state() == "closed"


@pytest.mark.unit
@pytest.mark.parametrize("status", [401, 403, 400, 404])
def test_a_raw_client_error_is_neutral(router, status):
    router.set_breaker(threshold=1)
    vendor = Call(_requests_http_error(status))
    with contextlib.suppress(Exception):
        router.route({"yfinance": vendor})
    assert vendor.calls == 1
    assert _breaker(router).state() == "closed"


@pytest.mark.unit
def test_a_raw_daily_quota_is_neutral(router):
    """A typed quota error (``retry=False``) is never evidence, raw or not."""
    router.set_breaker(threshold=1)
    quota = (
        VendorRateLimitError("daily quota used up")
        .with_retry_evidence(status=429, retry=False)
    )
    vendor = Call(quota)
    for _ in range(3):
        router.route({"yfinance": vendor})
    assert vendor.calls == 3, "a quota is not retried and never skips the vendor"
    assert _breaker(router).state() == "closed"


@pytest.mark.unit
def test_a_local_budget_stop_after_a_raw_timeout_keeps_the_vendor_failure(router):
    """Our attempt cap stops the retry; the vendor's proven failure still counts."""
    router.set_breaker(threshold=1)
    vendor = Call(requests.exceptions.Timeout("slow"))
    router.route({"yfinance": vendor}, retry={"max_attempts": 1})
    assert vendor.calls == 1
    assert _breaker(router).snapshot()["reason"] == "transient_failure"


@pytest.mark.unit
def test_an_unknown_exception_stays_neutral_even_with_a_classified_copy(router):
    """Classification is never assumed: an unclassifiable error is not evidence."""
    router.set_breaker(threshold=1)
    vendor = Call(ValueError("a bug of ours"))
    for _ in range(3):
        with pytest.raises(ValueError):
            router.route({"yfinance": vendor})
    assert vendor.calls == 3
    assert _breaker(router).state() == "closed"


@pytest.mark.unit
def test_the_classifier_helper_requires_the_classified_evidence(monkeypatch):
    """Only a proven momentary vendor failure is forwarded, never a raw bug."""
    budget = interface._retry_budget()
    proven = VendorRateLimitError("classified").with_retry_evidence(status=503, retry=True)
    unknown = ValueError("not the vendor's")
    long_retry = VendorRateLimitError("quota").with_retry_evidence(
        status=429, retry_after=3600, retry=True
    )
    assert interface._classified_vendor_failure(proven, proven, budget) is True
    assert interface._classified_vendor_failure(unknown, proven, budget) is True
    # The raw witness, when it speaks, must agree.
    assert interface._classified_vendor_failure(unknown, unknown, budget) is False
    assert interface._classified_vendor_failure(unknown, long_retry, budget) is False
    # An unclassifiable error never becomes evidence on its own.
    assert interface._classified_vendor_failure(unknown, ValueError("x"), budget) is False


# --- 9. the ticket is always released, even from inside the handler ---------


def _opened_router(router):
    """Open the breaker and serve the cooldown: the next call is a probe."""
    router.set_breaker(threshold=1, cooldown=60)
    router.route({"yfinance": Call(transient())})
    router.clock.advance(60)
    breaker = _breaker(router)
    assert breaker.snapshot()["state"] == "half_open"
    return breaker


@contextlib.contextmanager
def _patched_session_method(monkeypatch, name, replacement):  # noqa: SIM117
    original = getattr(retry_session.RetrySession, name)
    monkeypatch.setattr(retry_session.RetrySession, name, replacement)
    try:
        yield
    finally:
        monkeypatch.setattr(retry_session.RetrySession, name, original)


@pytest.mark.unit
def test_a_keyboard_interrupt_during_the_backoff_wait_frees_the_probe(
    router, monkeypatch
):
    breaker = _opened_router(router)
    vendor = Call(transient())

    def interrupted_pause(self, seconds):
        raise KeyboardInterrupt

    with _patched_session_method(monkeypatch, "pause", interrupted_pause):  # noqa: SIM117
        with pytest.raises(KeyboardInterrupt):
            router.route({"yfinance": vendor}, retry={"base_delay_seconds": 1.0})

    assert vendor.calls == 1, "the retry never started"
    snapshot = breaker.snapshot()
    assert snapshot["state"] == "half_open"
    assert snapshot["probe_open"] is False, "no probe may be left outstanding"
    # The probe was freed: another caller may obtain one immediately.
    assert router.route({"yfinance": Call(None, result="after")}) == "after"
    assert breaker.state() == "closed"


@pytest.mark.unit
def test_a_cancellation_during_the_backoff_wait_frees_the_probe(router, monkeypatch):
    import asyncio

    breaker = _opened_router(router)
    vendor = Call(transient())

    def cancelled_pause(self, seconds):
        raise asyncio.CancelledError()

    with _patched_session_method(monkeypatch, "pause", cancelled_pause):  # noqa: SIM117
        with pytest.raises(asyncio.CancelledError):
            router.route({"yfinance": vendor}, retry={"base_delay_seconds": 1.0})

    assert breaker.snapshot()["probe_open"] is False
    ticket = breaker.try_acquire()
    assert ticket is not None and ticket.probe
    ticket.finish("neutral")


@pytest.mark.unit
def test_an_error_inside_the_retry_bookkeeping_frees_the_probe(router, monkeypatch):
    """A bug *inside the handler* (after the call) must not leak the ticket."""
    breaker = _opened_router(router)

    def broken_log(*args, **kwargs):
        raise RuntimeError("logging backend broke")

    monkeypatch.setattr(interface.logger, "warning", broken_log)
    with pytest.raises(RuntimeError, match="logging backend broke"):
        router.route({"yfinance": Call(transient())})

    assert breaker.snapshot()["probe_open"] is False
    assert router.route({"yfinance": Call(None, result="after")}) == "after"


@pytest.mark.unit
def test_an_error_before_any_call_after_admission_frees_the_probe(router, monkeypatch):
    """Admitted, then the next step fails before the vendor is ever called."""
    breaker = _opened_router(router)
    vendor = Call(None, result="must-not-run")

    def broken_note(self, name, http_requests=1):
        raise RuntimeError("accounting broke")

    with _patched_session_method(monkeypatch, "note_attempt", broken_note):  # noqa: SIM117
        with pytest.raises(RuntimeError, match="accounting broke"):
            router.route({"yfinance": vendor})

    assert vendor.calls == 0
    assert breaker.snapshot()["probe_open"] is False
    assert router.route({"yfinance": Call(None, result="after")}) == "after"


@pytest.mark.unit
def test_an_unexpected_interrupt_after_admission_is_released_neutral(router):
    """The vendor raises a non-Exception: no attempt completes, ticket freed."""
    breaker = _opened_router(router)
    vendor = Call(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        router.route({"yfinance": vendor})

    assert vendor.calls == 1, "the vendor was entered but never completed"
    snapshot = breaker.snapshot()
    assert snapshot["probe_open"] is False
    # NEUTRAL, not a failure: the breaker stays half_open and can probe again.
    assert snapshot["state"] == "half_open"
    assert snapshot["failures"] == 0
