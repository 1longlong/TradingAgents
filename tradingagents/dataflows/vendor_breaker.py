"""A per-vendor circuit breaker: stop asking a vendor that is provably down.

One vendor call can already be bounded (``retry_session``) and classified
(``errors``). This module answers the remaining question -- *should this call be
started at all* -- by remembering, across tool calls, whether the vendor has
just failed transiently. It is deliberately small and deliberately dumb:

    - It receives an explicit **result category**, never an exception. The
      routing layer owns the translation from the exception taxonomy to
      ``success`` / ``transient_failure`` / ``absent`` / ``neutral``; this
      module must never inspect a class name or a message.
    - One supplier *logical call* is recorded once. Retries inside that call are
      the router's business; a call that ends up succeeding is ``success`` even
      if its first attempt failed.
    - State is in-process memory, kept across calls, never shared between
      processes. The clock is injectable (monotonic, no wall-clock jumps).

States::

    closed     allow. Each transient failure adds one; at the threshold -> open.
    open       refuse until ``cooldown_seconds`` have passed, then -> half_open.
    half_open  allow exactly one probe. ``success`` -> closed (count reset);
               ``transient_failure`` -> open (cooldown restarts).

Results (what the caller reports):

    success            reached a result: closes / resets the streak.
    transient_failure  the vendor was momentarily unavailable: counts.
    absent             the request completed and said "no data": a reachable
                       result. Never counts; may finish a probe as success.
    neutral            auth, request refused, unconfigured, quota/budget
                       exhaustion, internal error, cancellation. Never counts.
                       Releases a probe ticket but cannot *change* the state (it
                       is not evidence of health or of an outage).

Every ticket can be completed at most once. A ticket is only honoured while it
is still *current*: a ticket handed out for one half-open generation cannot
close a breaker that has since moved to open or closed, so a slow caller cannot
overwrite newer state. Tickets are opaque, single-use and must be released --
``try_acquire().finish()`` is the only supported path, and a router that has
acquired a ticket but cannot call the vendor must still ``finish(NEUTRAL)``
(a ``finally`` block or context manager).

Locking: the lock guards state reads/writes only. No network, no waiting, no
user callback ever runs while it is held.

Single-process only. ``scope`` is a caller-supplied identifier that groups
state for one deployment/configuration; it must carry no credentials (this
module stores it as a plain dict key and logs it).
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# --- result categories ------------------------------------------------------

SUCCESS = "success"
TRANSIENT_FAILURE = "transient_failure"
ABSENT = "absent"
NEUTRAL = "neutral"

#: Categories a caller may report. Deliberately a closed set: a typo must fail
#: loudly rather than silently become "no evidence".
RESULT_CATEGORIES = frozenset({SUCCESS, TRANSIENT_FAILURE, ABSENT, NEUTRAL})

#: Categories that count toward the failure threshold.
FAILURE_CATEGORIES = frozenset({TRANSIENT_FAILURE})

#: Categories that mean "the vendor answered": they reset the streak and can
#: finish a probe as a success.
REACHABLE_CATEGORIES = frozenset({SUCCESS, ABSENT})


class BreakerConfigError(ValueError):
    """A breaker setting is invalid; raised at construction, never defaulted."""




def _is_number(value) -> bool:
    """A real, finite number (bools are ints in Python and are excluded)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def _require_threshold(value) -> int:
    """A whole number of failures, at least 1."""
    original = value
    if isinstance(value, str):
        text = value.strip()
        if not text.isdigit():
            raise BreakerConfigError(
                f"failure_threshold must be a whole number, got {original!r}"
            )
        value = int(text)
    elif _is_number(value) and float(value).is_integer():
        value = int(value)
    else:
        raise BreakerConfigError(
            f"failure_threshold must be a whole number, got {original!r}"
        )
    if value < 1:
        raise BreakerConfigError(
            f"failure_threshold must be at least 1, got {original!r}"
        )
    return value


def _require_cooldown(value) -> float:
    """A finite, non-negative number of seconds (0 opens and recovers at once)."""
    if not _is_number(value):
        raise BreakerConfigError(
            f"cooldown_seconds must be a finite number, got {value!r}"
        )
    if value < 0:
        raise BreakerConfigError(
            f"cooldown_seconds must not be negative, got {value!r}"
        )
    return float(value)


@dataclass(frozen=True)
class BreakerPolicy:
    """The validated settings of one breaker (or of a registry of them).

    Zero is meaningful: ``cooldown_seconds=0`` means an opened breaker is
    eligible for a probe on the very next check.
    """

    failure_threshold: int = 3
    cooldown_seconds: float = 60.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "failure_threshold", _require_threshold(self.failure_threshold))
        object.__setattr__(self, "cooldown_seconds", _require_cooldown(self.cooldown_seconds))

    def signature(self) -> str:
        """A stable, credential-free description used in the state key.

        Two policies that differ in either setting must not share state, so the
        key includes this string rather than an object identity.
        """
        return f"t={self.failure_threshold};c={self.cooldown_seconds:g}"


# --- one vendor's state -----------------------------------------------------

#: Skip reasons a caller may report when it could not, or would not, start a
#: call. Kept as plain strings so the router can pass them through unchanged.
SKIP_CIRCUIT_OPEN = "circuit_open"
SKIP_PROBE_IN_PROGRESS = "probe_in_progress"


@dataclass(frozen=True)
class BreakerEvent:
    """A structured, credential-free record of one breaker decision.

    Deliberately flat and JSON-friendly so a consumer (a log formatter, or a
    teammate's evidence model) can adapt it without importing this module's
    classes. It never carries a symbol, a URL, a header or a key: only the
    vendor name, whether a call was actually made, the skip reason and the
    state transition, plus the endpoint/policy fingerprint already in the key.

    This event is *not* a data-quality verdict and this module does not decide
    one; it says only whether a vendor call was allowed and how it ended.
    """

    vendor: str
    scope: str
    state: str              # state after this decision: closed|open|half_open
    previous_state: str     # state before it
    action: str             # "call" | "skip" | "finish"
    called: bool            # whether a vendor call was actually made
    result: str | None      # success|transient_failure|absent|neutral, if any
    skip_reason: str | None  # circuit_open|probe_in_progress, if skipped
    probe: bool             # whether this call is the half-open probe


class _Slot:
    """The mutable state of one ``(vendor, scope)`` key. Guarded by the lock."""

    __slots__ = ("state", "failures", "opened_at", "generation", "probe_open", "reason")

    def __init__(self, state: str) -> None:
        self.state = state
        self.failures = 0
        self.opened_at: float | None = None
        # Bumped on every transition that invalidates outstanding tickets, so a
        # stale ticket can be told apart from a current one.
        self.generation = 0
        self.probe_open = False
        # Diagnostic only: why the breaker last opened (never read for decisions).
        self.reason: str | None = None


class Ticket:
    """Permission to make one vendor call, obtained from ``try_acquire``.

    Release it exactly once with ``finish(category)``. ``finish`` returns
    whether the result was applied (``False`` for an already-finished or
    superseded ticket) -- a stale result is ignored, never written.

    A ticket is also a context manager: leaving the ``with`` block without
    calling ``finish`` releases it as ``neutral``, so an exception, a
    cancellation or an early return cannot leak probe eligibility.
    """

    __slots__ = ("_breaker", "vendor", "scope", "generation", "probe", "_done")

    def __init__(
        self,
        breaker: VendorBreaker,
        vendor: str,
        scope: str,
        generation: int,
        probe: bool,
    ) -> None:
        self._breaker = breaker
        self.vendor = vendor
        self.scope = scope
        self.generation = generation
        self.probe = probe
        self._done = False

    @property
    def done(self) -> bool:
        """Whether this ticket has already been completed."""
        return self._breaker._ticket_done(self)

    def finish(self, category: str) -> bool:
        """Report the call's final category; return whether it was applied.

        Completion is atomic: the "already done?" read, the generation check,
        the state update and the "done" mark all happen under the breaker's one
        lock, so two threads finishing the same ticket can apply it at most
        once. There is no second lock on the ticket, hence no lock-order
        inversion. ``False`` means the ticket was already completed, was
        superseded by a newer transition, or no longer owns its probe.

        Raises ``ValueError`` for an unknown category (a programming error, not
        a vendor condition) or for a ticket belonging to another breaker.
        """
        if category not in RESULT_CATEGORIES:
            raise ValueError(
                f"unknown breaker result category {category!r}; "
                f"expected one of {sorted(RESULT_CATEGORIES)}"
            )
        return self._breaker._finish(self, category)

    def __enter__(self) -> Ticket:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if not self.done:
            # Not a verdict: an exception on the way out says nothing about the
            # vendor, and must not become a transient failure by accident.
            self.finish(NEUTRAL)
        return False


# --- the breaker ------------------------------------------------------------


class VendorBreaker:
    """The breaker for one vendor and one scope, with an injectable clock.

    ``try_acquire`` is the only question the router asks; ``finish`` on the
    returned ticket is the only report it makes. Both are safe to call from any
    thread.
    """

    def __init__(
        self,
        vendor: str,
        *,
        scope: str = "",
        policy: BreakerPolicy | None = None,
        clock: Callable[[], float] | None = None,
        on_event: Callable[[BreakerEvent], None] | None = None,
    ) -> None:
        if not isinstance(vendor, str) or not vendor.strip():
            raise BreakerConfigError(f"vendor must be a non-empty name, got {vendor!r}")
        if not isinstance(scope, str):
            raise BreakerConfigError(
                f"scope must be a string, got {type(scope).__name__}"
            )
        self.vendor = vendor
        self.scope = scope
        self.policy = policy if policy is not None else BreakerPolicy()
        # ``clock`` is looked up at call time on the instance, so a test may
        # swap it; it must be monotonic (the caller owns that contract).
        self._clock = clock or time.monotonic
        self._on_event = on_event
        self._lock = threading.Lock()
        self._slot = _Slot("closed")

    def _emit(self, event: BreakerEvent) -> None:
        """Hand one event to the sink (called outside every lock)."""
        sink = self._on_event
        if sink is not None:
            sink(event)

    # -- observation ---------------------------------------------------------

    def _ticket_done(self, ticket: Ticket) -> bool:
        """Whether ``ticket`` has been completed (read under the breaker's lock)."""
        with self._lock:
            return ticket._done

    def state(self) -> str:
        """The current state, as of now (open + cooldown served reads half_open)."""
        now = self._clock()  # user-injectable: never called under the lock
        with self._lock:
            return self._effective_state(self._slot, now)

    @property
    def failures(self) -> int:
        """The consecutive transient failures currently counted."""
        with self._lock:
            return self._slot.failures

    def snapshot(self) -> dict:
        """A read-only view for logs and tests; never a decision input."""
        now = self._clock()  # user-injectable: never called under the lock
        with self._lock:
            slot = self._slot
            return {
                "vendor": self.vendor,
                "scope": self.scope,
                "state": self._effective_state(slot, now),
                "failures": slot.failures,
                "generation": slot.generation,
                "probe_open": slot.probe_open,
                "reason": slot.reason,
            }

    # -- the decision --------------------------------------------------------

    def try_acquire(self, *, reason_out: list | None = None) -> Ticket | None:
        """A ticket to call the vendor, or None when the call must not start.

        A served cooldown moves ``open`` to ``half_open`` and hands out its one
        probe ticket; while that probe is outstanding every other caller gets
        None. A refused call starts no work and changes no state.

        ``reason_out``, when given, receives the skip reason as its only item
        (``SKIP_CIRCUIT_OPEN`` or ``SKIP_PROBE_IN_PROGRESS``) before this
        returns; it is the caller's way to log *why* nothing started without
        this method having to know about logging.
        """
        now = self._clock()  # user-injectable: never called under the lock
        with self._lock:
            slot = self._slot
            before = self._effective_state(slot, now)
            # A served cooldown is a transition in its own right: the caller
            # that observes it first owns the probe.
            if slot.state == "open" and now >= self._ready_at(slot):
                self._to_half_open(slot)
            if slot.state == "closed":
                ticket = Ticket(self, self.vendor, self.scope, slot.generation, False)
                reason = None
            elif slot.state == "half_open" and not slot.probe_open:
                slot.probe_open = True
                ticket = Ticket(self, self.vendor, self.scope, slot.generation, True)
                reason = None
            else:
                ticket = None
                reason = (
                    SKIP_PROBE_IN_PROGRESS if slot.state == "half_open" else SKIP_CIRCUIT_OPEN
                )
            after = self._effective_state(slot, now)
        if reason_out is not None:
            reason_out.clear()
            if reason is not None:
                reason_out.append(reason)
        self._emit(
            BreakerEvent(
                vendor=self.vendor,
                scope=self.scope,
                state=after,
                previous_state=before,
                action="skip" if ticket is None else "call",
                called=False,
                result=None,
                skip_reason=reason,
                probe=bool(ticket is not None and ticket.probe),
            )
        )
        return ticket

    # -- transitions (lock already held) ------------------------------------

    def _finish(self, ticket: Ticket, category: str) -> bool:
        """Apply one final category for a ticket, atomically and at most once.

        The whole decision -- "is it already done?", "is it still current?",
        "does it own the probe?", the state update and marking it done -- runs
        under the one breaker lock, so two threads finishing the same ticket
        cannot both be applied. The clock is read before the lock and logging
        is emitted after it, so neither user-injectable code nor I/O runs while
        waiting for state.
        """
        if ticket._breaker is not self:
            raise ValueError("ticket belongs to a different breaker")
        # Read the clock outside the lock. It is only needed when this result
        # actually opens the breaker; reading it always keeps the rule simple.
        now = self._clock()
        stale = None
        with self._lock:
            if ticket._done:
                # A second completion is a no-op: it cannot count a failure
                # again or free a probe owned by another ticket.
                return False
            slot = self._slot
            if ticket.generation != slot.generation:
                # A newer transition superseded this call; its result must not
                # revive old state. Collect what to log; log it outside.
                stale = (ticket.generation, slot.generation)
            elif ticket.probe and (not slot.probe_open or slot.state != "half_open"):
                stale = (ticket.generation, slot.generation)
            if stale is None:
                before = slot.state
                if ticket.probe:
                    slot.probe_open = False
                ticket._done = True
                applied = self._apply(slot, ticket.probe, category, now)
                after = slot.state
            else:
                applied = False
                before = after = slot.state
                ticket._done = True
        if stale is not None:
            logger.debug(
                "Ignoring stale %s for %s/%r (ticket gen %d, state gen %d)",
                category, self.vendor, self.scope, stale[0], stale[1],
            )
            return False
        self._emit(
            BreakerEvent(
                vendor=self.vendor,
                scope=self.scope,
                state=after,
                previous_state=before,
                action="finish",
                called=True,
                result=category,
                skip_reason=None,
                probe=ticket.probe,
            )
        )
        return applied

    def _apply(self, slot: _Slot, probe: bool, category: str, now: float) -> bool:
        if category in REACHABLE_CATEGORIES:
            self._to_closed(slot)
            return True
        if category == NEUTRAL:
            # Neutral releases a probe ticket (done by the caller) but is not
            # evidence either way: a half_open slot stays half_open and its
            # ticket is free again; a closed slot keeps its streak exactly as
            # it was (so a neutral result can never *mark* a transient failure
            # or mask one that already happened).
            return True
        # TRANSIENT_FAILURE
        if slot.state == "half_open":
            # The probe failed: reopen and restart the cooldown.
            self._to_open(slot, category, now)
            return True
        slot.failures += 1
        if slot.failures >= self.policy.failure_threshold:
            self._to_open(slot, category, now)
        return True

    def _to_closed(self, slot: _Slot) -> None:
        if slot.state != "closed" or slot.failures or slot.probe_open:
            slot.generation += 1
        slot.state = "closed"
        slot.failures = 0
        slot.opened_at = None
        slot.probe_open = False
        slot.reason = None

    def _to_open(self, slot: _Slot, reason: str, now: float) -> None:
        # ``now`` is passed in: the clock is read by the caller, never here.
        slot.generation += 1
        slot.state = "open"
        slot.failures = 0
        slot.opened_at = now
        slot.probe_open = False
        slot.reason = reason

    def _to_half_open(self, slot: _Slot) -> None:
        slot.generation += 1
        slot.state = "half_open"
        slot.failures = 0
        slot.opened_at = None
        slot.probe_open = False
        slot.reason = None

    def _ready_at(self, slot: _Slot) -> float:
        opened = slot.opened_at if slot.opened_at is not None else 0.0
        return opened + self.policy.cooldown_seconds

    def _effective_state(self, slot: _Slot, now: float) -> str:
        if slot.state == "open" and now >= self._ready_at(slot):
            return "half_open"
        return slot.state


# --- a registry of breakers -------------------------------------------------


class BreakerRegistry:
    """Breakers keyed by ``(vendor, scope)``, sharing one policy and clock.

    This is what a router would hold across tool calls; the breaker objects
    themselves are what a single call observes. The registry never evicts: one
    entry per configured vendor/scope is the intended bound.
    """

    def __init__(
        self,
        policy: BreakerPolicy | None = None,
        *,
        clock: Callable[[], float] | None = None,
        on_event: Callable[[BreakerEvent], None] | None = None,
    ) -> None:
        self.policy = policy if policy is not None else BreakerPolicy()
        self._clock = clock or time.monotonic
        # Optional sink for structured events (a logger, a collector). Called
        # outside the lock; None means "log the event through this module".
        self._on_event = on_event
        self._lock = threading.Lock()
        self._breakers: dict[tuple[str, str], VendorBreaker] = {}


    def for_vendor(self, vendor: str, *, scope: str = "") -> VendorBreaker:
        """The breaker for ``vendor`` in ``scope``, created on first use.

        Construction is done *outside* the registry lock: creating a breaker
        runs no user code today, but keeping it outside means a future clock or
        policy argument can never run under this lock. Two callers racing to
        create the same key both build one; the first to store wins and the
        other returns the stored object, so a key still has exactly one breaker.
        """
        if not isinstance(vendor, str) or not vendor.strip():
            raise BreakerConfigError(f"vendor must be a non-empty name, got {vendor!r}")
        if not isinstance(scope, str):
            raise BreakerConfigError(
                f"scope must be a string, got {type(scope).__name__}"
            )
        key = (vendor, scope)
        with self._lock:
            breaker = self._breakers.get(key)
        if breaker is not None:
            return breaker
        candidate = VendorBreaker(
            vendor, scope=scope, policy=self.policy, clock=self._clock,
            on_event=self._on_event,
        )
        with self._lock:
            # First store wins: a concurrent creator's object is discarded, not
            # merged, so no caller ever sees two breakers for one key.
            return self._breakers.setdefault(key, candidate)

    def try_acquire(self, vendor: str, *, scope: str = "", reason_out: list | None = None):
        """``for_vendor(vendor, scope=scope).try_acquire(reason_out=reason_out)``."""
        return self.for_vendor(vendor, scope=scope).try_acquire(reason_out=reason_out)

    def reset(self) -> None:
        """Forget every breaker (new registry state, same object).

        Used when the provider configuration changes (a new policy or endpoint
        must not mix with old state) and by tests that need a clean registry of
        their own. Never called by ``try_acquire``.
        """
        with self._lock:
            self._breakers.clear()


# --- configuration ----------------------------------------------------------


def breaker_policy_from_config(section) -> BreakerPolicy | None:
    """Validate the ``data_vendor_breaker`` section; None means disabled.

    The defaults are the agreed ones: ``enabled`` off, three consecutive
    transient failures, a 60 s cooldown. A wrong value raises
    ``BreakerConfigError`` rather than being clamped. While ``enabled`` is not
    true the other values are not even inspected, because nothing will use
    them -- but a malformed ``enabled`` is still refused.

    Unknown keys are refused too: a misspelling (``cooldown``) silently doing
    nothing is worse than failing at startup.
    """
    if section is None:
        return None
    if not isinstance(section, dict):
        raise BreakerConfigError(
            f"data_vendor_breaker must be a mapping, got {type(section).__name__}"
        )
    enabled = section.get("enabled", False)
    if not isinstance(enabled, bool):
        raise BreakerConfigError(
            f"data_vendor_breaker.enabled must be a boolean, got {enabled!r}"
        )
    allowed = {"enabled", "failure_threshold", "cooldown_seconds"}
    unknown = sorted(set(section) - allowed)
    if unknown:
        raise BreakerConfigError(
            f"data_vendor_breaker has unknown key(s) {unknown}; "
            f"allowed: {sorted(allowed)}"
        )
    if not enabled:
        return None
    return BreakerPolicy(
        failure_threshold=section.get("failure_threshold", 3),
        cooldown_seconds=section.get("cooldown_seconds", 60.0),
    )


def breaker_scope(endpoint: str, policy: BreakerPolicy) -> str:
    """The credential-free scope for a state key: endpoint plus policy.

    The key as a whole is ``(vendor, scope)``, so the same vendor on two
    endpoints, or under two policies, keeps separate state. ``endpoint`` is the
    vendor's own base URL (a constant in its module), never a request URL: a
    request URL can carry a key, symbol or date and would make state depend on
    the instrument or the query.
    """
    if not isinstance(endpoint, str) or not endpoint.strip():
        # An unknown endpoint still needs *a* scope; the vendor name alone is
        # the safe fallback and never widens sharing across endpoints.
        endpoint = "unknown"
    return f"endpoint={endpoint};{policy.signature()}"

