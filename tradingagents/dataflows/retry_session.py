"""One time and attempt budget shared by every vendor call of one tool call.

Batch 1 taught the router *when* a vendor failure is worth repeating. This
module supplies the *whether a repeat still fits*: one ``RetrySession`` per
``route_to_vendor`` call, holding the chain attempt cap, a per-vendor cap, a
wall-clock budget and a cumulative wait cap. A vendor that accepts a timeout
spends the budget left (capped), so a request can never be given more time than
the chain still has.

The contract:

    ``max_total_seconds``          wall clock for the whole chain. Checked
                                   before every start -- first call, retry and
                                   fall-through -- so when it is spent no new
                                   request begins.
    ``max_request_seconds``        cap on one HTTP request. A request's timeout
                                   is the time left, capped by this.
    ``max_cumulative_wait_seconds`` total of every backoff/Retry-After wait.
    ``max_retry_after_seconds``    per-wait threshold: a longer ask is refused
                                   and the chain moves on (not a total).
    ``base_delay_seconds`` +       backoff for a retry whose vendor said
    ``jitter_fraction``            nothing; jitter only ever shortens it.

The budget is a bound, not a promise. A client that accepts no timeout (some
``yfinance`` attributes) can only be started within the budget, never cut short;
such calls go through ``budget_check_before_uncontrolled_call`` and
``note_uncontrolled_overrun`` so the limitation is logged, not hidden.
"""

from __future__ import annotations

import contextlib
import logging
import math
import os
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .errors import VendorRateLimitError

logger = logging.getLogger(__name__)

# The active session for the current tool call; nested vendor scopes inherit it.
_ACTIVE: list[RetrySession] = []

# A request shorter than this is not worth starting: the client could only be
# cut off before it answers, which spends the budget and returns nothing.
_MIN_REQUEST_SECONDS = 0.5


def get_active_retry_session() -> RetrySession | None:
    """The session of the routed call in progress, or None when standalone.

    Vendors use this to tell a routed call (the router owns the retry loop)
    from a direct one (the vendor keeps its own behaviour).
    """
    return _ACTIVE[-1] if _ACTIVE else None


@contextlib.contextmanager
def retry_session(session: RetrySession):
    """Make ``session`` active for the block, restoring whatever was active.

    Re-entrant on purpose: a vendor that itself calls a routed helper must
    inherit the same budget instead of opening a second one.
    """
    _ACTIVE.append(session)
    try:
        yield session
    finally:
        _ACTIVE.pop()


# --- time helpers -----------------------------------------------------------


def remaining_request_timeout() -> float | None:
    """Time left in the active budget, or None outside a routed call.

    The value is the whole time left, not yet capped by
    ``max_request_seconds``; ``request_timeout`` applies that cap.
    """
    session = get_active_retry_session()
    return session.remaining() if session is not None else None


def request_timeout_for(remaining: float, cap: float | None = None) -> float | None:
    """The timeout to use given ``remaining`` seconds left and an optional cap.

    Returns None -- meaning "do not start this request" -- when the budget
    cannot cover even the minimum useful request. The result never exceeds what
    is left, so a retry can never be granted more time than the chain has.
    """
    if remaining <= 0:
        return None
    if cap is not None:
        remaining = min(remaining, cap)
    if remaining < _MIN_REQUEST_SECONDS:
        return None
    return remaining


def _stop_before_request(what: str, remaining: float, exc_type) -> BaseException:
    """Build the typed error for a request the budget cannot cover."""
    error = exc_type(
        f"the data budget cannot cover {what} ({remaining:.1f}s left); it was not started"
    )
    # Explicit metadata: the router must not retry a request that was refused
    # before it began.
    return error.with_retry_evidence(retry=False)


def stop_before_request(what: str, exc_type=None):
    """Fail with a typed, non-retryable error: ``what`` was not started.

    Used by a vendor whose remaining work (a second HTTP request in one call)
    no longer fits the budget, so the chain moves on rather than spending the
    last of the clock on a request that would be cut off.
    """
    session = get_active_retry_session()
    remaining = session.remaining() if session is not None else 0.0
    error = _stop_before_request(
        what, remaining, exc_type if exc_type is not None else VendorRateLimitError
    )
    logger.warning("%s", error)
    raise error


# --- time helpers used by the vendors ---------------------------------------


def request_timeout(cap: float, what: str = "this request") -> float | None:
    """The per-request timeout: budget left (capped), else the vendor default.

    Inside a routed call this is the time left, never more than ``cap`` nor
    than the budget's ``max_request_seconds``. Outside a routed call the
    vendor's own ``cap`` is returned unchanged, so a standalone call behaves
    exactly as before.

    When too little is left for a valid request (or nothing is left) it
    returns ``None`` -- "do not start this request" -- and logs the reason. The
    caller decides how to fail, because only it knows which error type fits
    (``stop_before_request`` raises the typed, non-retryable one).
    """
    session = get_active_retry_session()
    if session is None:
        return cap
    remaining = session.remaining()
    # The per-request cap bounds every request even when more time is left; a
    # vendor's own cap only applies when it is stricter.
    timeout = request_timeout_for(remaining, min(cap, session.budget.max_request_seconds))
    if timeout is None:
        logger.warning(
            "%s was not started: the data budget cannot cover it (%.1fs left)",
            what,
            remaining,
        )
    return timeout


def remaining_or(default: float | None = None) -> float | None:
    """Time left in the active budget, or ``default`` outside a routed call."""
    session = get_active_retry_session()
    return session.remaining() if session is not None else default


def budget_check_before_uncontrolled_call(what: str) -> float | None:
    """Gate a call that accepts no timeout on the budget being non-empty.

    Such a call cannot be cut short, so the only control is not to start it
    once the deadline has passed; this raises a typed, non-retryable error
    instead of pretending the call can be bounded.
    """
    session = get_active_retry_session()
    if session is None:
        return None
    remaining = session.remaining()
    if remaining <= 0:
        error = _stop_before_request(what, remaining, VendorRateLimitError)
        logger.warning("%s", error)
        raise error
    return remaining


def note_uncontrolled_overrun(what: str) -> None:
    """Log when a call that accepts no timeout ran past the budget.

    Deliberately a log and not a retry veto: the result is already in hand.
    """
    session = get_active_retry_session()
    if session is not None and session.remaining() <= 0:
        logger.warning(
            "%s returned after the %.0fs data budget was spent; the client "
            "accepts no timeout, so the call could not be cut short.",
            what,
            session.budget.max_total_seconds,
        )


# --- yfinance ------------------------------------------------------------------


def _zero_retries(session) -> None:
    """Pin a session's own retry count at zero (backend-neutral).

    ``curl_cffi`` keeps the count in ``session.retry`` (an int or its
    ``RetryStrategy``); ``requests`` keeps it in URL adapters
    (``max_retries``). Both are set on the *session object*, so the
    process-wide setting is never touched.
    """
    retry = getattr(session, "retry", None)
    if retry is not None:
        if isinstance(retry, int) or not hasattr(retry, "count"):
            session.retry = 0
        else:
            session.retry = type(retry)(count=0)
    adapters = getattr(session, "adapters", None)
    if adapters:
        for adapter in adapters.values():
            if hasattr(adapter, "max_retries"):
                try:
                    adapter.max_retries = 0
                except Exception:  # pragma: no cover - backend-specific
                    logger.debug("could not pin %r's adapter retries", session)


def yfin_session():
    """A yfinance session whose own retries are pinned at zero for this session.

    yfinance ships ``network.retries == 0``, but its retry loop reads the
    process-global ``YfConfig``; what a call can control is the session it
    hands over, so here that session's own retry count is pinned at zero
    *without touching ``YfConfig``*.

    Deliberately not wrapped: the response and the exception yfinance builds
    from it pass through unchanged (status, ``Retry-After``, message), so the
    router sees exactly the failure the server sent.

    Known limitations -- counted and logged, never hidden by faking a response,
    changing an exception's type, or mutating a global:

    - ``YfData._make_request`` makes one more request after any response
      >= 400 (its cookie-strategy fallback), unconditionally, and that request
      is not a ``session=`` argument. A refused Yahoo call therefore costs one
      duplicate request the budget did not schedule (plus cookie/crumb
      fetches). ``count_uncontrollable_requests`` records it when a caller can
      observe it; the chain deadline still bounds what may *start* next.
    - A retry count widened elsewhere in the process is global state shared
      with this session.
    - yfinance's cookie/crumb fetches go through the singleton ``YfData``,
      whose session is whichever one was passed last, so they are bounded by
      the deadline but not attributable to the call that caused them.
    """
    from yfinance._http import new_session

    session = new_session()
    _zero_retries(session)
    return session


def count_uncontrollable_requests(count: int, what: str) -> None:
    """Record requests an upstream client made that the budget did not schedule.

    Honest accounting only: it raises no error and changes no verdict. It adds
    to the active session's ``http_requests`` (never below the vendor
    invocations already recorded) and logs a warning, so an operator can see
    the extra cost.
    """
    if count <= 0:
        return
    session = get_active_retry_session()
    if session is not None:
        session.note_extra_http_requests(count)
    logger.warning(
        "%s issued %d request(s) the retry budget did not schedule (client "
        "retry/cookie fallback); they are counted, not prevented.",
        what,
        count,
    )


def routed_yfin_session():
    """The session kwargs for a yfinance constructor, only when a call is routed.

    Standalone calls pass nothing and keep yfinance's own defaults (and the
    lightweight ``Ticker(symbol)`` signature), so a vendor used directly is
    unchanged. A routed call gets yfinance's defaults too, except that the
    session's own retry count is pinned at zero for that session.
    """
    if get_active_retry_session() is None:
        return {}
    return {"session": yfin_session()}


# --- the session ------------------------------------------------------------


@dataclass
class RetrySession:
    """The mutable state of one routed call's retry budget.

    ``attempts`` counts vendor-function *invocations* (what the router repeats);
    ``http_requests`` counts the HTTP requests those invocations issued, so the
    two are never conflated -- one invocation may make several requests (e.g.
    a multi-query news search) and must still be one attempt.
    """

    budget: RetryBudget
    started: float = field(init=False)
    attempts: int = 0
    http_requests: int = 0
    vendor_attempts: dict[str, int] = field(default_factory=dict)
    waited: float = 0.0
    stop_reason: str | None = None

    def __post_init__(self) -> None:
        self.started = self.budget.now()

    # -- accounting -----

    def note_attempt(self, vendor: str, http_requests: int = 1) -> None:
        self.attempts += 1
        self.vendor_attempts[vendor] = self.vendor_attempts.get(vendor, 0) + 1
        self.http_requests += http_requests

    def note_extra_http_requests(self, count: int) -> None:
        """Count requests an upstream client made beyond the scheduled ones.

        Accounting only (a client's own retry or cookie fallback cannot be
        disabled from here): it never alters a verdict or a wait. Each vendor
        invocation is already counted as one request, so the extra requests
        can only add to that floor.
        """
        if count > 0:
            self.http_requests = max(self.http_requests + count, self.attempts)

    # -- decisions ---

    def elapsed(self) -> float:
        """Seconds since this call's budget started."""
        return self.budget.now() - self.started

    def remaining(self) -> float:
        """Seconds left of the wall-clock budget (never negative)."""
        return max(0.0, self.budget.max_total_seconds - self.elapsed())

    def exhausted(self) -> bool:
        """Whether the chain attempt cap has been reached."""
        return self.attempts >= self.budget.max_attempts

    def can_try_again(self, vendor: str) -> bool:
        """Whether this vendor still has an attempt and the chain has room."""
        if self.exhausted():
            return False
        return self.vendor_attempts.get(vendor, 0) < self.budget.attempts_for(vendor)

    def wait_allowance(self) -> float:
        """Seconds still available under the cumulative wait cap."""
        return max(0.0, self.budget.max_cumulative_wait_seconds - self.waited)

    def precheck(self, vendor: str) -> tuple[bool, str]:
        """Whether one more call to ``vendor`` may start; the reason if not.

        Checked immediately before every call, so the first call, a retry and a
        fall-through all pass the same gate, and a spent deadline stops the
        chain before anything else is spent.
        """
        if self.remaining() <= 0:
            return False, "the data budget's time is spent"
        if not self.can_try_again(vendor):
            if self.exhausted():
                return False, "the chain's attempt cap is reached"
            return False, f"vendor {vendor!r} has used its attempts"
        return True, ""

    def pause(self, seconds: float) -> bool:
        """Wait ``seconds`` before a retry if both caps allow it.

        Returns False when the wait would take the cumulative wait total past
        its cap (the chain should move on instead). A wait longer than the time
        left is unnecessary -- the next ``precheck`` refuses the start anyway.
        """
        if seconds > self.wait_allowance():
            return False
        if seconds > 0:
            # A zero-length wait (a server's ``Retry-After: 0``) is taken at
            # once: it is still counted as a retry, but nothing is slept.
            self.budget.pause_for(seconds)
            self.waited += seconds
        return True


# --- configuration ----------------------------------------------------------


class RetryConfigError(ValueError):
    """A retry setting is invalid; raised at startup instead of being defaulted."""


def _is_number(value) -> bool:
    """A real, finite number (bools are ints in Python and are excluded)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def _env_number(name: str, default: float) -> float:
    """Read a finite number from the environment, refusing an unusable value."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number, got {raw!r}") from None
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {raw!r}")
    return value


def _require_number(section: dict, key: str, default: float) -> float:
    """A finite, non-negative setting from ``section``, or the default."""
    if key not in section or section[key] is None:
        return default
    value = section[key]
    if not _is_number(value):
        raise RetryConfigError(f"data_vendor_retry.{key} must be a finite number, got {value!r}")
    if value < 0:
        raise RetryConfigError(f"data_vendor_retry.{key} must not be negative, got {value!r}")
    return float(value)


def _require_attempts(value, what: str) -> int:
    """A whole attempt count (at least 1), from a number or digit-only text."""
    original = value
    if isinstance(value, str):
        text = value.strip()
        if not text.isdigit():
            raise RetryConfigError(f"{what} must be a whole number, got {original!r}")
        value = int(text)
    elif _is_number(value) and float(value).is_integer():
        value = int(value)
    else:
        raise RetryConfigError(f"{what} must be a whole number, got {original!r}")
    if value < 1:
        raise RetryConfigError(f"{what} must be at least 1, got {original!r}")
    return value


def _require_int(section: dict, key: str, default: int) -> int:
    if key not in section or section[key] is None:
        return default
    return _require_attempts(section[key], f"data_vendor_retry.{key}")


def retry_budget_from_config(section) -> RetryBudget:
    """Validate ``data_vendor_retry`` into a ``RetryBudget``.

    A wrong value raises ``RetryConfigError`` rather than silently becoming a
    default. Zero is meaningful, not a missing value:

        max_total_seconds = 0           no call may ever start
        max_cumulative_wait_seconds = 0 no wait may ever be taken
        max_retry_after_seconds = 0     any asked-for wait is longer than the
                                        threshold, so the chain moves on
        jitter_fraction = 0             deterministic backoff

    Attempt counts are inclusive of the first call: 1 means "never retry".
    """
    if not isinstance(section, dict):
        raise RetryConfigError(f"data_vendor_retry must be a mapping, got {type(section).__name__}")
    attempts = _require_int(section, "max_attempts", 2)
    overrides = section.get("vendor_max_attempts") or {}
    if not isinstance(overrides, dict):
        raise RetryConfigError(
            f"data_vendor_retry.vendor_max_attempts must be a mapping, got {overrides!r}"
        )
    per_vendor = {}
    for vendor, value in overrides.items():
        if not isinstance(vendor, str) or not vendor.strip():
            raise RetryConfigError(
                f"data_vendor_retry.vendor_max_attempts needs a non-empty vendor name, got {vendor!r}"
            )
        per_vendor[vendor] = _require_attempts(
            value, f"data_vendor_retry.vendor_max_attempts.{vendor}"
        )
    max_total_seconds = _require_number(section, "max_total_seconds", 45.0)
    max_request_seconds = _require_number(section, "max_request_seconds", 15.0)
    max_cumulative_wait_seconds = _require_number(section, "max_cumulative_wait_seconds", 20.0)
    max_retry_after_seconds = _require_number(section, "max_retry_after_seconds", 10.0)
    base_delay_seconds = _require_number(section, "base_delay_seconds", 1.0)
    jitter_fraction = _require_number(section, "jitter_fraction", 0.2)
    if jitter_fraction > 1.0:
        raise RetryConfigError(
            f"data_vendor_retry.jitter_fraction must be at most 1.0, got {jitter_fraction!r}"
        )
    return RetryBudget(
        max_attempts=_require_int(section, "max_total_attempts", 4),
        default_per_vendor_attempts=attempts,
        per_vendor_attempts=per_vendor,
        max_total_seconds=max_total_seconds,
        max_request_seconds=max_request_seconds,
        max_cumulative_wait_seconds=max_cumulative_wait_seconds,
        max_retry_after_seconds=max_retry_after_seconds,
        base_delay_seconds=base_delay_seconds,
        jitter_fraction=jitter_fraction,
    )


def jittered_delay(seconds: float, fraction: float, rng: Callable[[], float] | None = None) -> float:
    """Shave up to ``fraction`` of ``seconds`` at random; never lengthen it.

    Downward-only jitter spreads concurrent retries without ever making a
    caller wait longer than it planned. The draw is clamped, so a hostile or
    injected ``rng`` cannot turn the wait negative or longer.
    """
    if seconds <= 0 or fraction <= 0:
        return max(0.0, seconds)
    draw = (rng or random.random)()
    draw = min(max(float(draw), 0.0), 1.0)
    return max(0.0, seconds * (1.0 - fraction * draw))


@dataclass
class RetryBudget:
    """The validated allowances for one routed call.

    ``clock``/``sleep`` are seams for tests; production uses the real ones.
    """

    max_attempts: int = 4
    default_per_vendor_attempts: int = 2
    per_vendor_attempts: dict[str, int] = field(default_factory=dict)
    max_total_seconds: float = 45.0
    max_request_seconds: float = 15.0
    max_cumulative_wait_seconds: float = 20.0
    max_retry_after_seconds: float = 10.0
    base_delay_seconds: float = 1.0
    jitter_fraction: float = 0.2
    # ``time`` is looked up at call time (not bound at import), so a seam that
    # replaces ``retry_session.time`` -- or one injected on the dataclass --
    # governs every wait and deadline.
    clock: Callable[[], float] | None = None
    sleep: Callable[[float], None] | None = None
    rng: Callable[[], float] | None = None

    def now(self) -> float:
        return (self.clock or time.monotonic)()

    def pause_for(self, seconds: float) -> None:
        (self.sleep or time.sleep)(seconds)

    def attempts_for(self, vendor: str) -> int:
        """The inclusive attempt allowance for one vendor."""
        return self.per_vendor_attempts.get(vendor, self.default_per_vendor_attempts)

    def backoff_seconds(self, failed_attempts: int) -> float:
        """Wait before the next attempt, exponential and jittered downward.

        ``failed_attempts`` is the number of attempts this vendor already made,
        so the first retry is one ``base_delay_seconds``. A server-specified
        Retry-After never passes through here, so it is never shortened.
        """
        step = max(1, failed_attempts)
        delay = self.base_delay_seconds * (2 ** (step - 1))
        return jittered_delay(delay, self.jitter_fraction, self.rng)
