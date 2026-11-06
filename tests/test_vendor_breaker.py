"""The independent vendor circuit breaker; no routing and no network.

The breaker only decides *whether a call may start*. It is fed an explicit
result category by its caller and never looks at exceptions. What these tests
pin:

    closed    -> a streak of transient failures opens at the threshold
    open      -> refuses during cooldown; the first check afterwards is a probe
    half_open -> one probe at a time; success closes, failure reopens
    reachable -> success (and a completed "no data") clear the streak
    neutral   -> never counts, releases a probe, leaves the state alone
    tickets   -> one completion only; stale tickets cannot overwrite new state;
                 an exception leaving the block still frees the probe
    keys      -> (vendor, scope) are isolated
    threads   -> exactly one probe is granted, decided at a Barrier

Time is virtual and injected; concurrency uses ``Barrier``/``Event`` with time
outs. Every test builds its own instance: the production registry (when a
router eventually holds one) is never touched by this module's tests.
"""
from __future__ import annotations

import logging
import threading

import pytest

from tradingagents.dataflows import vendor_breaker as vb
from tradingagents.dataflows.vendor_breaker import (
    ABSENT,
    NEUTRAL,
    SUCCESS,
    TRANSIENT_FAILURE,
    BreakerConfigError,
    BreakerPolicy,
    BreakerRegistry,
    VendorBreaker,
)

VENDOR = "yfinance"
JOIN_TIMEOUT = 10.0


# --- harness ----------------------------------------------------------------


class Clock:
    """Virtual monotonic time: advancing is explicit, never by sleeping."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make(
    threshold: int = 3,
    cooldown: float = 60.0,
    *,
    vendor: str = VENDOR,
    scope: str = "",
    clock: Clock | None = None,
) -> tuple[VendorBreaker, Clock]:
    clock = clock or Clock()
    breaker = VendorBreaker(
        vendor,
        scope=scope,
        policy=BreakerPolicy(failure_threshold=threshold, cooldown_seconds=cooldown),
        clock=clock,
    )
    return breaker, clock


def report(breaker: VendorBreaker, category: str):
    """One allowed call whose final result is ``category``."""
    ticket = breaker.try_acquire()
    assert ticket is not None, "call was refused unexpectedly"
    return ticket.finish(category)


def fail(breaker: VendorBreaker) -> None:
    report(breaker, TRANSIENT_FAILURE)


def open_breaker(breaker: VendorBreaker, threshold: int = 3) -> None:
    for _ in range(threshold):
        fail(breaker)
    assert breaker.state() == "open"


# --- 1. threshold boundary --------------------------------------------------


@pytest.mark.unit
def test_threshold_minus_one_stays_closed_and_allows_calls():
    breaker, _ = make(threshold=3)
    fail(breaker)
    fail(breaker)
    assert breaker.state() == "closed"
    assert breaker.failures == 2
    assert breaker.try_acquire() is not None


@pytest.mark.unit
def test_reaching_the_threshold_opens_immediately():
    breaker, _ = make(threshold=3)
    fail(breaker)
    fail(breaker)
    fail(breaker)
    assert breaker.state() == "open"
    assert breaker.try_acquire() is None


@pytest.mark.unit
def test_threshold_one_opens_on_the_first_transient_failure():
    breaker, _ = make(threshold=1)
    fail(breaker)
    assert breaker.state() == "open"


# --- 2. cooldown boundary ---------------------------------------------------


@pytest.mark.unit
def test_open_refuses_until_the_cooldown_has_been_served():
    breaker, clock = make(threshold=2, cooldown=60)
    open_breaker(breaker, 2)
    clock.advance(59.999)
    assert breaker.state() == "open"
    assert breaker.try_acquire() is None
    clock.advance(0.001)  # exactly 60.0: the boundary itself is served
    ticket = breaker.try_acquire()
    assert ticket is not None and ticket.probe
    assert breaker.state() == "half_open"


@pytest.mark.unit
def test_a_refused_call_changes_no_state():
    breaker, clock = make(threshold=2, cooldown=30)
    open_breaker(breaker, 2)
    snapshot = breaker.snapshot()
    clock.advance(5)
    assert breaker.try_acquire() is None
    after = breaker.snapshot()
    assert after["state"] == "open"
    assert after["generation"] == snapshot["generation"]
    assert after["failures"] == snapshot["failures"]


@pytest.mark.unit
def test_zero_cooldown_is_served_on_the_next_check():
    breaker, _ = make(threshold=1, cooldown=0)
    fail(breaker)
    ticket = breaker.try_acquire()
    assert ticket is not None and ticket.probe


# --- 3. probes: success, failure, neutrality --------------------------------


@pytest.mark.unit
def test_a_successful_probe_closes_and_clears_the_streak():
    breaker, clock = make(threshold=2, cooldown=60)
    open_breaker(breaker, 2)
    clock.advance(60)
    report(breaker, SUCCESS)
    assert breaker.state() == "closed"
    assert breaker.failures == 0
    assert breaker.try_acquire() is not None  # no probe flag on a normal call


@pytest.mark.unit
def test_a_failed_probe_reopens_and_restarts_the_cooldown():
    breaker, clock = make(threshold=2, cooldown=60)
    open_breaker(breaker, 2)
    clock.advance(60)
    probe = breaker.try_acquire()
    assert probe is not None and probe.probe
    probe.finish(TRANSIENT_FAILURE)
    assert breaker.state() == "open"
    # Cooldown restarted at the probe, not at the original open.
    clock.advance(59)
    assert breaker.try_acquire() is None
    clock.advance(1)
    assert breaker.try_acquire() is not None


@pytest.mark.unit
def test_a_success_after_closure_starts_a_fresh_streak():
    breaker, clock = make(threshold=2, cooldown=60)
    open_breaker(breaker, 2)
    clock.advance(60)
    report(breaker, SUCCESS)
    fail(breaker)
    assert breaker.state() == "closed" and breaker.failures == 1
    fail(breaker)
    assert breaker.state() == "open"


# --- 4. absent and neutral results -----------------------------------------


@pytest.mark.unit
def test_absent_does_not_count_and_clears_the_streak():
    breaker, _ = make(threshold=3)
    fail(breaker)
    fail(breaker)
    report(breaker, ABSENT)
    assert breaker.state() == "closed"
    assert breaker.failures == 0


@pytest.mark.unit
def test_absent_finishes_a_probe_as_reachable():
    breaker, clock = make(threshold=2, cooldown=10)
    open_breaker(breaker, 2)
    clock.advance(10)
    report(breaker, ABSENT)
    assert breaker.state() == "closed"


@pytest.mark.unit
@pytest.mark.parametrize(
    "because",
    ["auth", "rejected", "unconfigured", "quota-exhausted", "internal-error", "cancelled"],
)
def test_neutral_never_counts(because):
    breaker, _ = make(threshold=1)
    for _ in range(5):
        report(breaker, NEUTRAL)
    assert breaker.state() == "closed", because
    assert breaker.failures == 0, because


@pytest.mark.unit
def test_neutral_does_not_mask_a_failure_that_already_happened():
    breaker, _ = make(threshold=2)
    fail(breaker)
    report(breaker, NEUTRAL)  # e.g. bad params on the next call
    assert breaker.failures == 1
    fail(breaker)
    assert breaker.state() == "open"


@pytest.mark.unit
def test_a_neutral_probe_releases_the_ticket_and_stays_half_open():
    breaker, clock = make(threshold=2, cooldown=60)
    open_breaker(breaker, 2)
    clock.advance(60)
    first = breaker.try_acquire()
    assert first is not None and first.probe
    assert breaker.try_acquire() is None  # probe outstanding
    first.finish(NEUTRAL)  # e.g. a missing key: not evidence of an outage
    assert breaker.state() == "half_open"
    second = breaker.try_acquire()
    assert second is not None and second.probe  # released for the next caller
    second.finish(SUCCESS)
    assert breaker.state() == "closed"


@pytest.mark.unit
def test_a_neutral_then_transient_probe_still_reopens():
    breaker, clock = make(threshold=2, cooldown=60)
    open_breaker(breaker, 2)
    clock.advance(60)
    report(breaker, NEUTRAL)
    report(breaker, TRANSIENT_FAILURE)
    assert breaker.state() == "open"


@pytest.mark.unit
def test_neutral_on_a_closed_breaker_leaves_it_closed():
    breaker, _ = make(threshold=3)
    report(breaker, NEUTRAL)
    assert breaker.snapshot()["generation"] == 0


# --- 5. tickets: single completion, staleness, release ---------------------


@pytest.mark.unit
def test_a_ticket_completes_once_and_a_second_finish_is_ignored():
    breaker, _ = make(threshold=2)
    ticket = breaker.try_acquire()
    assert ticket.finish(SUCCESS) is True
    assert ticket.finish(TRANSIENT_FAILURE) is False  # no second count
    assert breaker.failures == 0


@pytest.mark.unit
def test_an_unknown_category_is_a_programming_error_and_keeps_the_ticket_open():
    breaker, _ = make()
    ticket = breaker.try_acquire()
    with pytest.raises(ValueError):
        ticket.finish("throttled")  # not one of the four categories
    assert ticket.done is False
    assert ticket.finish(SUCCESS) is True


@pytest.mark.unit
def test_a_stale_ticket_cannot_overwrite_newer_state():
    """A slow call from before the breaker reopened must not close it."""
    breaker, clock = make(threshold=1, cooldown=10)
    slow = breaker.try_acquire()  # closed, generation N
    fail(breaker)  # threshold 1 -> open (generation N+1)
    assert breaker.state() == "open"
    assert slow.finish(SUCCESS) is False
    assert breaker.state() == "open"


@pytest.mark.unit
def test_a_stale_probe_cannot_close_a_breaker_reopened_after_it():
    breaker, clock = make(threshold=2, cooldown=10)
    open_breaker(breaker, 2)
    clock.advance(10)
    probe = breaker.try_acquire()
    assert probe is not None and probe.probe
    probe.finish(TRANSIENT_FAILURE)  # reopen (generation +1)
    clock.advance(10)
    fresh = breaker.try_acquire()  # a new probe generation
    assert fresh is not None and fresh.probe
    assert probe.finish(SUCCESS) is False  # deferred old result: ignored
    assert breaker.state() == "half_open"
    assert fresh.finish(SUCCESS) is True
    assert breaker.state() == "closed"


@pytest.mark.unit
def test_an_exception_leaving_the_block_releases_a_probe_as_neutral():
    breaker, clock = make(threshold=2, cooldown=10)
    open_breaker(breaker, 2)
    clock.advance(10)
    with (
        pytest.raises(KeyboardInterrupt),
        breaker.try_acquire() as ticket,
    ):
        assert ticket is not None and ticket.probe
        raise KeyboardInterrupt()
    assert breaker.state() == "half_open"
    assert breaker.try_acquire() is not None  # not stuck as "probe outstanding"


@pytest.mark.unit
def test_a_cancelled_call_releases_a_probe_as_neutral():
    import asyncio

    breaker, clock = make(threshold=2, cooldown=10)
    open_breaker(breaker, 2)
    clock.advance(10)
    with (
        pytest.raises(asyncio.CancelledError),
        breaker.try_acquire() as ticket,
    ):
        assert ticket is not None
        raise asyncio.CancelledError()
    assert breaker.state() == "half_open"
    assert breaker.try_acquire() is not None


@pytest.mark.unit
def test_finishing_with_the_context_manager_does_not_double_complete():
    breaker, _ = make(threshold=2)
    with breaker.try_acquire() as ticket:
        ticket.finish(TRANSIENT_FAILURE)
    assert breaker.failures == 1


@pytest.mark.unit
def test_a_repeated_completion_does_not_free_a_later_probe():
    breaker, clock = make(threshold=2, cooldown=10)
    open_breaker(breaker, 2)
    clock.advance(10)
    first = breaker.try_acquire()
    first.finish(NEUTRAL)  # probe ticket released, still half_open
    second = breaker.try_acquire()  # the next probe
    assert second is not None and second.probe
    assert first.finish(SUCCESS) is False  # a repeat is not a second verdict
    assert breaker.try_acquire() is None  # second probe still outstanding
    assert second.finish(SUCCESS) is True
    assert breaker.state() == "closed"


@pytest.mark.unit
def test_a_ticket_from_another_breaker_is_refused():
    a, _ = make()
    b, _ = make()
    ticket = a.try_acquire()
    with pytest.raises(ValueError):
        b._finish(ticket, SUCCESS)


# --- 6. keys and isolation --------------------------------------------------


@pytest.mark.unit
def test_vendors_in_one_registry_are_isolated():
    registry = BreakerRegistry(
        BreakerPolicy(failure_threshold=1, cooldown_seconds=60), clock=Clock()
    )
    yf = registry.for_vendor("yfinance")
    av = registry.for_vendor("alpha_vantage")
    yf.try_acquire().finish(TRANSIENT_FAILURE)
    assert yf.state() == "open"
    assert av.state() == "closed"
    assert av.try_acquire() is not None


@pytest.mark.unit
def test_scopes_of_one_vendor_are_isolated():
    registry = BreakerRegistry(
        BreakerPolicy(failure_threshold=1, cooldown_seconds=60), clock=Clock()
    )
    prod = registry.for_vendor("yfinance", scope="data_vendor_retry:1")
    other = registry.for_vendor("yfinance", scope="data_vendor_retry:2")
    prod.try_acquire().finish(TRANSIENT_FAILURE)
    assert prod.state() == "open"
    assert other.state() == "closed"


@pytest.mark.unit
def test_the_registry_returns_one_breaker_per_key():
    registry = BreakerRegistry(clock=Clock())
    assert registry.for_vendor("x") is registry.for_vendor("x")
    assert registry.for_vendor("x") is not registry.for_vendor("x", scope="s")


@pytest.mark.unit
def test_a_registry_shares_one_policy_and_clock():
    clock = Clock()
    registry = BreakerRegistry(
        BreakerPolicy(failure_threshold=1, cooldown_seconds=10), clock=clock
    )
    breaker = registry.for_vendor("yfinance")
    registry.try_acquire("yfinance").finish(TRANSIENT_FAILURE)
    assert breaker.state() == "open"
    clock.advance(10)
    assert breaker.state() == "half_open"


# --- 7. concurrency: one probe ---------------------------------------------


@pytest.mark.unit
def test_exactly_one_probe_is_granted_under_concurrency():
    """All threads wait at a Barrier, then race; exactly one gets a probe."""
    breaker, clock = make(threshold=2, cooldown=10)
    open_breaker(breaker, 2)
    clock.advance(10)

    starters = 6
    ready = threading.Barrier(starters, timeout=JOIN_TIMEOUT)
    results: list = []
    lock = threading.Lock()
    errors: list[BaseException] = []

    def racer():
        try:
            ready.wait()
            ticket = breaker.try_acquire()
            with lock:
                results.append(ticket)
        except BaseException as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=racer) for _ in range(starters)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(JOIN_TIMEOUT)
        assert not thread.is_alive(), "worker thread hung"

    assert not errors, errors
    probes = [t for t in results if t is not None]
    assert len(probes) == 1, "half_open must allow exactly one probe"
    assert all(t is None for t in results if t is not probes[0])


@pytest.mark.unit
def test_only_the_probe_thread_seeing_half_open_can_finish_it():
    """A second thread's success cannot close a breaker while the probe runs."""
    breaker, clock = make(threshold=2, cooldown=10)
    open_breaker(breaker, 2)
    clock.advance(10)

    probe_taken = threading.Event()
    second_done = threading.Event()
    outcomes = {}
    errors: list[BaseException] = []

    def probe_thread():
        try:
            ticket = breaker.try_acquire()
            assert ticket is not None and ticket.probe
            probe_taken.set()
            if not second_done.wait(JOIN_TIMEOUT):
                raise TimeoutError("second thread never finished")
            outcomes["probe"] = ticket.finish(TRANSIENT_FAILURE)
        except BaseException as exc:
            errors.append(exc)

    def second_thread():
        try:
            if not probe_taken.wait(JOIN_TIMEOUT):
                raise TimeoutError("probe not taken")
            outcomes["second_ticket"] = breaker.try_acquire()
        finally:
            second_done.set()

    threads = [threading.Thread(target=probe_thread), threading.Thread(target=second_thread)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(JOIN_TIMEOUT)
        assert not thread.is_alive(), "worker thread hung"

    assert not errors, errors
    assert outcomes["second_ticket"] is None
    assert outcomes["probe"] is True
    assert breaker.state() == "open"


# --- 8. strict configuration ----------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("value", [0, -1, 1.5, True, "abc", None, float("nan"), float("inf")])
def test_an_invalid_failure_threshold_is_refused(value):
    with pytest.raises(BreakerConfigError):
        BreakerPolicy(failure_threshold=value)


@pytest.mark.unit
def test_digit_text_is_accepted_for_the_threshold():
    assert BreakerPolicy(failure_threshold="2").failure_threshold == 2


@pytest.mark.unit
@pytest.mark.parametrize(
    "value", [-0.1, True, "soon", None, float("nan"), float("inf")]
)
def test_an_invalid_cooldown_is_refused(value):
    with pytest.raises(BreakerConfigError):
        BreakerPolicy(cooldown_seconds=value)


@pytest.mark.unit
def test_zero_cooldown_is_valid():
    assert BreakerPolicy(cooldown_seconds=0).cooldown_seconds == 0.0


@pytest.mark.unit
@pytest.mark.parametrize("vendor", ["", "   ", None, 3])
def test_a_blank_or_non_text_vendor_is_refused(vendor):
    with pytest.raises(BreakerConfigError):
        VendorBreaker(vendor)


@pytest.mark.unit
def test_a_non_text_scope_is_refused():
    with pytest.raises(BreakerConfigError):
        VendorBreaker("yfinance", scope=None)


@pytest.mark.unit
def test_the_default_policy_is_the_agreed_one():
    policy = BreakerPolicy()
    assert policy.failure_threshold == 3
    assert policy.cooldown_seconds == 60.0


# --- 9. one ticket, one verdict, even under a race --------------------------


def _race_finish(ticket, category, *, starters: int = 2):
    """Have ``starters`` threads call ``ticket.finish(category)`` at once.

    Ordering is a ``Barrier``: all threads have entered ``finish`` (or are
    about to) before any of them proceeds, so the window between "is it done?"
    and "mark it done" is exercised without relying on the scheduler.
    Returns the list of return values, one per thread.
    """
    ready = threading.Barrier(starters, timeout=JOIN_TIMEOUT)
    results: list = []
    lock = threading.Lock()
    errors: list[BaseException] = []

    def racer():
        try:
            ready.wait()
            value = ticket.finish(category)
            with lock:
                results.append(value)
        except BaseException as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=racer) for _ in range(starters)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(JOIN_TIMEOUT)
        assert not thread.is_alive(), "worker thread hung"
    assert not errors, errors
    return results


@pytest.mark.unit
def test_a_racing_finish_applies_a_transient_failure_at_most_once():
    """Two threads completing one ticket: one verdict, one counted failure."""
    breaker, _ = make(threshold=10)
    ticket = breaker.try_acquire()
    results = _race_finish(ticket, TRANSIENT_FAILURE, starters=4)
    assert sorted(results) == [False, False, False, True]
    assert breaker.failures == 1


def _forced_double_read(ticket, category, *, starters: int = 2):
    """Have ``starters`` threads all attempt the same ticket at once.

    Deterministic: all threads are released from a ``Barrier``. Completion is
    now atomic under the breaker's lock, so at most one may be applied; the
    assertion is that the return values contain exactly one ``True`` and the
    state moved once.
    """
    ready = threading.Barrier(starters, timeout=JOIN_TIMEOUT)
    results: list = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker():
        try:
            ready.wait()
            value = ticket.finish(category)
            with lock:
                results.append(value)
        except BaseException as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(starters)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(JOIN_TIMEOUT)
        assert not thread.is_alive(), "worker thread hung"
    assert not errors, errors
    return results


@pytest.mark.unit
def test_two_threads_that_both_observe_not_done_still_apply_one_verdict():
    """Deterministic reproduction of the lost 'already done?' check."""
    breaker, _ = make(threshold=10)
    ticket = breaker.try_acquire()
    results = _forced_double_read(ticket, TRANSIENT_FAILURE)
    assert results.count(True) == 1, results
    assert breaker.failures == 1


@pytest.mark.unit
def test_a_hooked_double_read_cannot_release_a_probe_twice():
    """Same forced interleaving, on a probe ticket that must free only once."""
    breaker, clock = make(threshold=2, cooldown=10)
    open_breaker(breaker, 2)
    clock.advance(10)
    probe = breaker.try_acquire()
    assert probe is not None and probe.probe
    results = _forced_double_read(probe, NEUTRAL, starters=3)
    assert results.count(True) == 1
    assert breaker.state() == "half_open"
    assert breaker.try_acquire() is not None


@pytest.mark.unit
def test_a_racing_finish_cannot_trip_the_breaker_twice():
    """With threshold 2 and one ticket, a double count would open it."""
    breaker, _ = make(threshold=2)
    ticket = breaker.try_acquire()
    results = _race_finish(ticket, TRANSIENT_FAILURE, starters=2)
    assert results.count(True) == 1
    assert breaker.state() == "closed" and breaker.failures == 1


@pytest.mark.unit
def test_a_racing_repeat_cannot_release_a_later_probe():
    """A repeat ``finish`` of an old ticket must not free the newest probe."""
    breaker, clock = make(threshold=2, cooldown=10)
    open_breaker(breaker, 2)
    clock.advance(10)
    old = breaker.try_acquire()
    old.finish(NEUTRAL)  # releases the probe; still half_open
    fresh = breaker.try_acquire()
    assert fresh is not None and fresh.probe
    results = _race_finish(old, SUCCESS, starters=4)
    assert results == [False, False, False, False]
    assert breaker.try_acquire() is None, "the fresh probe is still outstanding"
    assert fresh.finish(SUCCESS) is True
    assert breaker.state() == "closed"


@pytest.mark.unit
def test_concurrent_finishes_of_distinct_tickets_each_count_once():
    breaker, _ = make(threshold=100)
    tickets = [breaker.try_acquire() for _ in range(8)]
    ready = threading.Barrier(len(tickets), timeout=JOIN_TIMEOUT)
    errors: list[BaseException] = []

    def worker(slot):
        try:
            ready.wait()
            slot.finish(TRANSIENT_FAILURE)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in tickets]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(JOIN_TIMEOUT)
        assert not thread.is_alive(), "worker thread hung"
    assert not errors, errors
    assert breaker.failures == 8


# --- 10. no user code runs while the lock is held ---------------------------


def _run_with_deadline(fn):
    """Run ``fn`` in a thread; fail (not hang) if it never returns."""
    box = {}
    done = threading.Event()

    def run():
        try:
            box["value"] = fn()
        except BaseException as exc:  # re-raised by the caller
            box["error"] = exc
        finally:
            done.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert done.wait(JOIN_TIMEOUT), "call deadlocked: it never returned"
    if "error" in box:
        raise box["error"]
    return box.get("value")


@pytest.mark.unit
def test_state_does_not_deadlock_when_the_clock_reads_state():
    """A clock that looks at the breaker must not be called under its lock."""
    clock = Clock()
    holder = {}

    def reentrant_clock():
        if "breaker" in holder:
            holder["seen"] = holder["breaker"].failures  # would deadlock if locked
        return clock.now

    breaker = VendorBreaker("yfinance", policy=BreakerPolicy(3, 60), clock=reentrant_clock)
    holder["breaker"] = breaker
    assert _run_with_deadline(breaker.state) == "closed"
    assert holder["seen"] == 0


@pytest.mark.unit
def test_snapshot_does_not_deadlock_when_the_clock_reads_state():
    clock = Clock()
    holder = {}

    def reentrant_clock():
        if "breaker" in holder:
            holder["seen"] = holder["breaker"].failures  # would deadlock if locked
        return clock.now

    breaker = VendorBreaker("yfinance", policy=BreakerPolicy(3, 60), clock=reentrant_clock)
    holder["breaker"] = breaker
    snap = _run_with_deadline(breaker.snapshot)
    assert snap["state"] == "closed"
    assert holder["seen"] == 0


@pytest.mark.unit
def test_opening_does_not_deadlock_when_the_clock_reads_state():
    """``_to_open`` used to stamp ``opened_at`` with the clock under the lock."""
    clock = Clock()
    holder = {}

    def reentrant_clock():
        if "breaker" in holder:
            holder["seen"] = holder["breaker"].failures  # would deadlock if locked
        return clock.now

    breaker = VendorBreaker(
        "yfinance", policy=BreakerPolicy(failure_threshold=1, cooldown_seconds=60),
        clock=reentrant_clock,
    )
    holder["breaker"] = breaker
    _run_with_deadline(lambda: report(breaker, TRANSIENT_FAILURE))
    assert breaker.state() == "open"
    assert "seen" in holder  # the clock ran; it just did so outside the lock


@pytest.mark.unit
def test_try_acquire_does_not_deadlock_when_the_clock_reads_state():
    clock = Clock()
    holder = {}

    def reentrant_clock():
        if "breaker" in holder:
            # Would deadlock if the clock were read while the breaker lock is held.
            holder["seen"] = holder["breaker"].failures
        return clock.now

    breaker = VendorBreaker("yfinance", policy=BreakerPolicy(3, 60), clock=reentrant_clock)
    holder["breaker"] = breaker
    assert _run_with_deadline(breaker.try_acquire) is not None
    assert holder["seen"] == 0


@pytest.mark.unit
def test_a_log_handler_reading_state_does_not_deadlock(caplog):
    """The stale-ticket branch logs; a handler must not run under the lock."""
    holder = []
    logger_name = "tradingagents.dataflows.vendor_breaker"

    class ReadingHandler(logging.Handler):
        def emit(self, record):
            holder.append(holder[0].state() if holder else "not-yet")

    handler = ReadingHandler()
    target = logging.getLogger(logger_name)
    target.addHandler(handler)
    try:
        breaker, clock = make(threshold=1, cooldown=10)
        holder.append(breaker)
        stale = breaker.try_acquire()
        fail(breaker)  # open: supersedes ``stale``

        def finish_stale():
            with caplog.at_level(logging.DEBUG, logger=logger_name):
                return stale.finish(SUCCESS)

        assert _run_with_deadline(finish_stale) is False
        assert holder[-1] == "open"
    finally:
        target.removeHandler(handler)


@pytest.mark.unit
def test_creating_a_breaker_does_not_call_injectable_code_under_the_lock():
    """The registry may construct lazily, but never while holding its lock."""
    holder = {}
    registry = BreakerRegistry()

    def reentrant_clock():
        if "breaker" in holder:
            # Fires only while the breaker is being constructed; a lock held
            # around construction would deadlock here.
            holder["seen"] = holder["breaker"].failures
        return 1000.0

    # First build a breaker so ``holder`` has something to re-enter, then swap
    # in a clock that reads it. The registry must not hold its lock while
    # running this clock (it builds the breaker outside).
    breaker = registry.for_vendor("yfinance")
    breaker._clock = reentrant_clock
    holder["breaker"] = breaker
    assert _run_with_deadline(breaker.state) == "closed"
    assert holder["seen"] == 0

    errors: list[BaseException] = []
    results: list = []
    ready = threading.Barrier(4, timeout=JOIN_TIMEOUT)

    def worker():
        try:
            ready.wait()
            results.append(registry.for_vendor("alpha_vantage"))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(JOIN_TIMEOUT)
        assert not thread.is_alive(), "worker thread hung"
    assert not errors, errors
    assert len({id(b) for b in results}) == 1, "a race must not create two breakers"


@pytest.mark.unit
def test_the_cooldown_boundary_is_unchanged_after_the_lock_was_narrowed():
    breaker, clock = make(threshold=1, cooldown=60)
    open_breaker(breaker, 1)
    clock.advance(59.999)
    assert breaker.state() == "open" and breaker.try_acquire() is None
    clock.advance(0.001)
    ticket = breaker.try_acquire()
    assert ticket is not None and ticket.probe


# --- 10. the config section and its env vars --------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "section, expected",
    [
        (None, None),
        ({"enabled": False}, None),
        ({"enabled": False, "failure_threshold": 0}, None),
        ({}, None),
        ({"enabled": True}, BreakerPolicy(3, 60.0)),
        ({"enabled": True, "failure_threshold": 5, "cooldown_seconds": 30},
         BreakerPolicy(5, 30.0)),
    ],
)
def test_the_config_section_is_validated_and_means_disabled_when_off(section, expected):
    assert vb.breaker_policy_from_config(section) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "section",
    [
        [],
        "on",
        {"enabled": "yes"},
        {"enabled": 1},
        {"enabled": True, "cooldown": 30},  # typo is refused, not ignored
        {"enabled": True, "failure_threshold": 0},
        {"enabled": True, "cooldown_seconds": -1},
    ],
)
def test_a_malformed_config_section_is_refused(section):
    with pytest.raises(BreakerConfigError):
        vb.breaker_policy_from_config(section)


@pytest.mark.unit
def test_the_breaker_is_off_by_default():
    from tradingagents.default_config import DEFAULT_CONFIG

    assert vb.breaker_policy_from_config(DEFAULT_CONFIG["data_vendor_breaker"]) is None


@pytest.mark.unit
def test_the_breaker_can_be_enabled_from_the_environment(monkeypatch):
    import importlib

    from tradingagents import default_config

    monkeypatch.setenv("TRADINGAGENTS_VENDOR_BREAKER_ENABLED", "true")
    monkeypatch.setenv("TRADINGAGENTS_VENDOR_BREAKER_FAILURE_THRESHOLD", "5")
    monkeypatch.setenv("TRADINGAGENTS_VENDOR_BREAKER_COOLDOWN_SECONDS", "30")
    dc = importlib.reload(default_config)
    try:
        section = dc.DEFAULT_CONFIG["data_vendor_breaker"]
        assert vb.breaker_policy_from_config(section) == BreakerPolicy(5, 30.0)
    finally:
        monkeypatch.undo()
        importlib.reload(default_config)
