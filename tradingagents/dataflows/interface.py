import contextlib
import logging
import threading

from .alpha_vantage import (
    get_balance_sheet as get_alpha_vantage_balance_sheet,
    get_cashflow as get_alpha_vantage_cashflow,
    get_fundamentals as get_alpha_vantage_fundamentals,
    get_global_news as get_alpha_vantage_global_news,
    get_income_statement as get_alpha_vantage_income_statement,
    get_indicator as get_alpha_vantage_indicator,
    get_insider_transactions as get_alpha_vantage_insider_transactions,
    get_news as get_alpha_vantage_news,
    get_stock as get_alpha_vantage_stock,
)
from .config import get_config
from .errors import (
    NoMarketDataError,
    VendorAuthenticationError,
    VendorError,
    VendorNotConfiguredError,
    VendorRateLimitError,
    VendorRequestRejectedError,
    retryable_status,
)
from .fred import FRED_API_BASE, get_macro_data as get_fred_macro_data
from .polymarket import GAMMA_BASE, get_prediction_markets as get_polymarket_prediction_markets
from .retry_session import (
    RetryBudget,
    RetrySession,
    retry_budget_from_config,
    retry_session,
)
from .sec_edgar import (
    _FACTS_URL as _SEC_FACTS_URL,
    get_balance_sheet as get_sec_edgar_balance_sheet,
    get_cashflow as get_sec_edgar_cashflow,
    get_income_statement as get_sec_edgar_income_statement,
)
from .stockstats_utils import as_vendor_error
from .vendor_breaker import (
    ABSENT,
    NEUTRAL,
    SUCCESS,
    TRANSIENT_FAILURE,
    BreakerPolicy,
    BreakerRegistry,
    breaker_policy_from_config,
    breaker_scope,
)
from .y_finance import (
    get_balance_sheet as get_yfinance_balance_sheet,
    get_cashflow as get_yfinance_cashflow,
    get_fundamentals as get_yfinance_fundamentals,
    get_income_statement as get_yfinance_income_statement,
    get_insider_transactions as get_yfinance_insider_transactions,
    get_stock_stats_indicators_window,
    get_YFin_data_online,
)
from .yfinance_news import get_global_news_yfinance, get_news_yfinance

logger = logging.getLogger(__name__)

# Tools organized by category
TOOLS_CATEGORIES = {
    "core_stock_apis": {
        "description": "OHLCV stock price data",
        "tools": [
            "get_stock_data"
        ]
    },
    "technical_indicators": {
        "description": "Technical analysis indicators",
        "tools": [
            "get_indicators"
        ]
    },
    "fundamental_data": {
        "description": "Company fundamentals",
        "tools": [
            "get_fundamentals",
            "get_balance_sheet",
            "get_cashflow",
            "get_income_statement"
        ]
    },
    "news_data": {
        "description": "News and insider data",
        "tools": [
            "get_news",
            "get_global_news",
            "get_insider_transactions",
        ]
    },
    "macro_data": {
        "description": "Macroeconomic indicators (rates, inflation, labor, growth)",
        "tools": [
            "get_macro_indicators",
        ]
    },
    "prediction_markets": {
        "description": "Market-implied probabilities for forward-looking events",
        "tools": [
            "get_prediction_markets",
        ]
    }
}

VENDOR_LIST = [
    "yfinance",
    "sec_edgar",
    "fred",
    "polymarket",
    "alpha_vantage",
]

# Optional enrichment categories. These add macro/event context to the news
# analyst but are not core to a decision, so a vendor failure here degrades to a
# sentinel instead of aborting the run (a bad LLM-supplied indicator, a missing
# key, or a network blip should not crash an analysis over flavour data). Core
# categories (prices, fundamentals, news) still raise unknown errors so a broken
# primary is loud; an outage, throttle, rejected key or missing config is
# reported as a sentinel in every category, because none of those is a fact
# about the instrument and retrying cannot fix them.
OPTIONAL_CATEGORIES = {"macro_data", "prediction_markets"}

# Mapping of methods to their vendor-specific implementations
VENDOR_METHODS = {
    # core_stock_apis
    "get_stock_data": {
        "alpha_vantage": get_alpha_vantage_stock,
        "yfinance": get_YFin_data_online,
    },
    # technical_indicators
    "get_indicators": {
        "alpha_vantage": get_alpha_vantage_indicator,
        "yfinance": get_stock_stats_indicators_window,
    },
    # fundamental_data
    "get_fundamentals": {
        "alpha_vantage": get_alpha_vantage_fundamentals,
        "yfinance": get_yfinance_fundamentals,
    },
    "get_balance_sheet": {
        "alpha_vantage": get_alpha_vantage_balance_sheet,
        "sec_edgar": get_sec_edgar_balance_sheet,
        "yfinance": get_yfinance_balance_sheet,
    },
    "get_cashflow": {
        "alpha_vantage": get_alpha_vantage_cashflow,
        "sec_edgar": get_sec_edgar_cashflow,
        "yfinance": get_yfinance_cashflow,
    },
    "get_income_statement": {
        "alpha_vantage": get_alpha_vantage_income_statement,
        "sec_edgar": get_sec_edgar_income_statement,
        "yfinance": get_yfinance_income_statement,
    },
    # news_data
    "get_news": {
        "alpha_vantage": get_alpha_vantage_news,
        "yfinance": get_news_yfinance,
    },
    "get_global_news": {
        "yfinance": get_global_news_yfinance,
        "alpha_vantage": get_alpha_vantage_global_news,
    },
    "get_insider_transactions": {
        "alpha_vantage": get_alpha_vantage_insider_transactions,
        "yfinance": get_yfinance_insider_transactions,
    },
    # macro_data
    "get_macro_indicators": {
        "fred": get_fred_macro_data,
    },
    # prediction_markets
    "get_prediction_markets": {
        "polymarket": get_polymarket_prediction_markets,
    },
}

# The base URL each vendor serves from, used only to keep circuit-breaker state
# apart: two vendors (or the same vendor on a moved endpoint) must not share a
# verdict about availability. A constant, never a request URL -- request URLs
# carry the symbol, dates and sometimes a key, and state keyed by those would
# stop protecting anything. Omitted vendors fall back to "(no endpoint)".
VENDOR_ENDPOINTS = {
    "yfinance": "https://query2.finance.yahoo.com",
    "alpha_vantage": "https://www.alphavantage.co/query",
    "sec_edgar": _SEC_FACTS_URL,
    "fred": FRED_API_BASE,
    "polymarket": GAMMA_BASE,
}


def get_category_for_method(method: str) -> str:
    """Get the category that contains the specified method."""
    for category, info in TOOLS_CATEGORIES.items():
        if method in info["tools"]:
            return category
    raise ValueError(f"Method '{method}' not found in any category")

def get_vendor(category: str, method: str = None) -> str:
    """Get the configured vendor for a data category or specific tool method.
    Tool-level configuration takes precedence over category-level.
    """
    config = get_config()

    # Check tool-level configuration first (if method provided)
    if method:
        tool_vendors = config.get("tool_vendors", {})
        if method in tool_vendors:
            return tool_vendors[method]

    # Fall back to category-level configuration
    return config.get("data_vendors", {}).get(category, "default")

def _cause(exc: BaseException) -> str:
    """The exception's own wording, or just its type when it has none."""
    return str(exc) if str(exc) else type(exc).__name__


# How a failure moves the chain verdict. The classes are tried in this order,
# which is also the precedence when a chain holds more than one of them: an
# injected key is fixable by the user, a refused request is not retried, an
# outage may resolve itself, a missing key is install-time, and a bug is
# neither of the above. This order is what makes the verdict deterministic when
# the vendor ORDER is reversed.
_RANK = (
    ("auth", "the supplied API key was rejected"),
    ("rejected", "the request was refused"),
    ("unavailable", "throttled or unreachable"),
    ("not_configured", "not configured"),
    ("unknown", "an unexpected error"),
)


_KIND_OF = (
    # Most specific first. ``isinstance`` is used (not ``type(x).__name__``) so a
    # vendor's thin subclass (e.g. ``AlphaVantageAuthenticationError``, which
    # derives from ``VendorAuthenticationError``) inherits the base semantics
    # instead of falling through to "unknown".
    (VendorAuthenticationError, "auth"),
    (VendorRequestRejectedError, "rejected"),
    (VendorRateLimitError, "unavailable"),
    (VendorNotConfiguredError, "not_configured"),
)


def _kind(exc: BaseException) -> str:
    """Which verdict slot an exception occupies, by its class hierarchy."""
    for cls, kind in _KIND_OF:
        if isinstance(exc, cls):
            return kind
    # NoMarketDataError is an absence, not a failure, and never reaches here.
    # Anything else is a real surprise (a bug or an unclassified error).
    return "unknown"


def _failure_detail(vendor: str, exc: BaseException) -> str:
    """One vendor's real cause, with its type and category (no remedy wording)."""
    return f"{vendor}: {type(exc).__name__} ({_cause(exc)} [{_kind(exc)}])"


def _combination(
    failures: list[tuple[str, BaseException]], no_data_vendors: list[str] | None = None
) -> str:
    """Name every failure in chain order: vendor, category and real cause.

    Deterministic: each failure appears once, in the order the chain tried the
    vendors. The primary verdict above names the most actionable category;
    this sentence keeps the whole picture (every vendor, every category and the
    actual cause) so reversing the chain cannot hide one of them. A single
    failure is still named: the primary verdict above it states the category's
    remedy, not the vendor's own cause.
    """
    parts = "; ".join(_failure_detail(vendor, exc) for vendor, exc in failures)
    if not parts:
        return ""
    lead = "Failures in the chain" if no_data_vendors else "All configured vendors failed"
    return f"{lead} ({parts})."


def _retry_budget() -> RetryBudget:
    """The retry allowance for one tool call, from ``data_vendor_retry``.

    Defaults mirror ``DEFAULT_CONFIG``; a partially configured section is
    completed from them, so a user who set only one key still gets sane bounds.
    Every value is validated: a wrong one raises ``RetryConfigError`` rather than
    being clamped. Zero semantics are defined with the validator (see
    ``retry_session.retry_budget_from_config``): a zero time budget means no
    call -- first, retry or fall-through -- is ever started.
    """
    cfg = get_config().get("data_vendor_retry", {})
    return retry_budget_from_config(cfg)


# --- Data-vendor circuit breaker -------------------------------------------
#
# The breaker decides whether a vendor logical call may start, across tool
# calls. It lives at module level so its state survives them; it is re-created
# only when the *breaker policy* changes, never per call. The key is
# ``(vendor, breaker_scope(endpoint, policy))``: the same vendor on two
# endpoints or under two policies keeps separate state, while every symbol,
# date and method served by one endpoint shares the same protection.
#
# Disabled (the default) means: no registry, no ticket, no state -- exactly
# the behaviour before this feature existed.
_BREAKER_LOCK = threading.Lock()
_BREAKER_REGISTRY: BreakerRegistry | None = None
_BREAKER_POLICY: BreakerPolicy | None = None


_TICKETLESS = contextlib.nullcontext()


def _breaker_policy() -> BreakerPolicy | None:
    """The configured policy, or None when the breaker is disabled/absent."""
    return breaker_policy_from_config(get_config().get("data_vendor_breaker"))


def _breaker_registry(policy: BreakerPolicy | None) -> BreakerRegistry | None:
    """The process-wide registry for ``policy``, or None when disabled.

    Kept across ``route_to_vendor`` calls. A policy change (threshold or
    cooldown) builds a new registry, because old counts were earned under other
    rules; nothing else -- not a symbol, not a retry-budget change, not an
    unrelated setting -- resets it.
    """
    global _BREAKER_REGISTRY, _BREAKER_POLICY
    if policy is None:
        return None
    with _BREAKER_LOCK:
        if _BREAKER_REGISTRY is None or policy != _BREAKER_POLICY:
            _BREAKER_REGISTRY = BreakerRegistry(policy, on_event=_log_breaker_event)
            _BREAKER_POLICY = policy
        return _BREAKER_REGISTRY


def reset_vendor_breaker_state() -> None:
    """Forget all breaker state (policy change hook, and tests).

    Not called on every request: the registry must survive tool calls.
    """
    global _BREAKER_REGISTRY, _BREAKER_POLICY
    with _BREAKER_LOCK:
        _BREAKER_REGISTRY = None
        _BREAKER_POLICY = None


class _VendorCall:
    """The per-vendor half of the ticket bookkeeping.

    A fresh instance per iteration of the vendor loop, so the closure that
    completes the ticket always reads and writes the state of *its own* vendor.
    ``ticket`` is the admitted ticket (None until the breaker says yes), and
    ``recorded`` makes completion one-shot: a verdict, whether a success or a
    proven failure, is never overwritten and never counted twice.
    """

    __slots__ = ("ticket", "recorded")

    def __init__(self) -> None:
        self.ticket = None
        self.recorded = False


def _log_breaker_event(event) -> None:
    """Record one breaker event. Flat, credential-free, and outside the lock."""
    if event.action == "finish":
        logger.info(
            "Vendor breaker %s/%s: %s -> %s (result=%s, probe=%s).",
            event.vendor, event.scope, event.previous_state, event.state,
            event.result, event.probe,
        )
    else:
        logger.info(
            "Vendor breaker %s/%s: %s -> %s (action=%s, skip=%s, called=%s).",
            event.vendor, event.scope, event.previous_state, event.state,
            event.action, event.skip_reason, event.called,
        )


def _is_short_vendor_failure(exc: BaseException, budget: RetryBudget) -> bool:
    """Did the vendor itself say "come back shortly" for this failure?

    True for a typed throttle/service failure carrying ``retry`` evidence whose
    ``Retry-After`` (if any) fits the per-wait cap. This is the vendor-side
    half of ``retry_verdict``, deliberately *without* its local checks (deadline
    left, attempt allowance, cumulative wait): those say whether *we* may retry,
    not whether the vendor is unhealthy. A daily/monthly quota is ``retry=False``
    and therefore never matches; neither does a sign of credential or config
    trouble, whatever evidence was attached.
    """
    if not isinstance(exc, VendorRateLimitError):
        return False
    metadata = _retry_metadata(exc)
    if metadata is None:
        return False
    recoverable, retry_after = metadata
    if not recoverable:
        return False
    return retry_after is None or retry_after <= budget.max_retry_after_seconds


def _classified_vendor_failure(
    exc: BaseException, classified: BaseException, budget: RetryBudget
) -> bool:
    """Is this failure a *proven* momentary vendor failure?

    ``classified`` is what ``handle`` returned for the original ``exc``: a
    vendor's own typed error, or the copy ``as_vendor_error`` built when the
    vendor raised an unclassified transport/HTTP error. The classification is
    what carries the status and ``retry``/``Retry-After`` evidence, so it -- not
    the raw ``requests.Timeout`` or ``HTTPError`` -- is what proves the outage.

    The comparison is deliberately strict: only the categories that are a real
    throttle/service failure count. Auth, refused requests, missing config and
    absences are never transient, whatever a copy's class alone might suggest.

    Unknown exceptions are never transient by default: a *copy* is accepted
    only when the original was itself classifiable -- that is, the classifier
    turned the raw exception into a vendor error rather than passing it through
    unchanged. When the original carries its own evidence, that evidence must
    agree; when it carries none (a bare ``requests.Timeout``), the classifier's
    verdict for that original is the proof.
    """
    if not _is_short_vendor_failure(classified, budget):
        return False
    if classified is exc:
        return True
    # If the raw original already states its own recoverability, it must agree.
    own = _retry_metadata(exc)
    return own is None or own[0]


def _breaker_result(
    exc: BaseException, provable: bool = False, classified: BaseException | None = None
) -> str:
    """Map one final vendor failure to a breaker category, from its metadata only.

    ``provable`` is true only when this vendor function itself proved the
    condition was momentary: its error carried ``retry``/a short ``Retry-After``
    (short 429/502/503/504, timeout, reset) and the call still ended on that
    error. A local limit (attempt allowance, wall-clock deadline, wait cap) is
    never ``provable``: stopping because *our* budget ran out says nothing
    about the vendor, and must not replace its last real result.

    ``classified`` is ``handle``'s result for ``exc`` (see
    ``_classified_vendor_failure``); it lets a *completed absence* be recognised
    even when it arrived as a raw exception and was wrapped for reporting.

    Everything else -- daily/monthly quota, entitlement, auth, refused request,
    missing config, TLS/URL, unparseable body, internal error, cancellation --
    is NEUTRAL. The class alone is never enough: a bare
    ``VendorRateLimitError`` (no status, no ``retry``) or a
    ``_kind() == "unavailable"`` label says only "this failed", not "asking
    again soon would help".
    """
    if isinstance(exc, NoMarketDataError) or isinstance(classified, NoMarketDataError):
        return ABSENT
    if provable:
        return TRANSIENT_FAILURE
    return NEUTRAL


def _retry_metadata(exc: BaseException) -> tuple[bool, float | None] | None:
    """Read a failure's own recoverability metadata: (recoverable, Retry-After).

    None means the exception carries none and is therefore not retried. An
    explicit ``exc.retry`` (set by a vendor or by ``as_vendor_error``) wins over
    the generic status/transport rules; a ``VendorRateLimitError`` raised from
    scratch carries neither, so it is *not* assumed transient just because of
    its class -- the first batch's own wording (a throttle is one class) does
    not by itself say that waiting helps.
    """
    explicit = getattr(exc, "retry", None)
    status = getattr(exc, "status", None)
    retry_after = getattr(exc, "retry_after", None)
    if explicit is None:
        explicit = retryable_status(status, retry_after)
    if explicit is None:
        return None
    if not isinstance(retry_after, (int, float)) or isinstance(retry_after, bool):
        retry_after = None
    return bool(explicit), retry_after


def _backoff_seconds(budget: RetryBudget, failed_attempts: int) -> float:
    """Wait before attempt ``failed_attempts + 1`` when the vendor said nothing.

    Exponential and jittered *downward* only (``RetryBudget.backoff_seconds``),
    so concurrent callers do not retry in lockstep. A server-specified
    ``Retry-After`` never passes through here and is therefore never shortened.
    """
    return budget.backoff_seconds(failed_attempts)


def _others(failures, primary_exc) -> list[tuple[str, BaseException]]:
    """Every failure except the one being raised (compared by identity)."""
    return [(vendor, exc) for vendor, exc in failures if exc is not primary_exc]


def _distinct_kinds(failures: list[tuple[str, BaseException]]) -> list[str]:
    """The failure categories present, most actionable (``_RANK``) first."""
    present = {_kind(exc) for _, exc in failures}
    return [name for name, _ in _RANK if name in present]


def _robust_verdict(
    method: str,
    primary_message: str,
    primary_kind: str | None,
    failures: list[tuple[str, BaseException]],
    no_data_vendors: list[str] | None = None,
    covered: list[str] | None = None,
) -> str:
    """State the chain result without letting the last failure shadow the rest.

    ``primary_message`` is the verdict for ``primary_kind``; it already names one
    vendor's reason. When other categories also failed, every one of them is
    named (by ``_RANK``, not chain order) with every vendor's real cause, so
    swapping the vendors cannot hide, say, a rejected key behind a timeout.

    ``primary_kind=None`` means the caller's sentence names every category it
    lists, so no "also" line is needed; the per-vendor combination is still
    appended (it is the only per-vendor detail when the sentence is a summary).
    ``covered`` extends that to a sentence that already *states* some categories
    as a list ("failed (auth, unavailable)") without naming their remedy.
    """
    remedies = dict(_RANK)
    present = _distinct_kinds(failures)
    if not present:
        return primary_message
    # The primary's own category is described by its sentence; only categories
    # that are *not otherwise* covered need the "also" line.
    described = set(covered or ())
    if primary_kind is not None:
        described.add(primary_kind)
    others = [n for n in present if n not in described]
    if primary_kind is not None and not others:
        # Same category, different vendors: the list below still names both.
        # With a single failure there is nothing to add, so keep the verdict as is.
        extra = _combination(failures, no_data_vendors)
        return f"{primary_message.rstrip()} {extra}".rstrip()
    if primary_kind is None:
        return f"{primary_message.rstrip()} {_combination(failures, no_data_vendors)}".rstrip()
    also = "; ".join(remedies[name] for name in others)
    return (
        f"{primary_message.rstrip()} Mixed failure categories -- also: {also}. "
        f"{_combination(failures, no_data_vendors)}"
    )


def route_to_vendor(method: str, *args, **kwargs):
    """Route method calls to appropriate vendor implementation with fallback support."""
    category = get_category_for_method(method)
    vendor_config = get_vendor(category, method)
    primary_vendors = [v.strip() for v in vendor_config.split(',')]

    if method not in VENDOR_METHODS:
        raise ValueError(f"Method '{method}' not supported")

    all_available_vendors = list(VENDOR_METHODS[method].keys())

    # The configured vendor list IS the chain: we do NOT silently fall back to
    # vendors the user did not choose (#988/#289) �?that returned data from an
    # unexpected source and caused cross-vendor inconsistencies. For multi-vendor
    # fallback, list them in order, e.g. data_vendors="yfinance,alpha_vantage".
    # The "default" sentinel (no explicit config) uses all available vendors.
    explicit = [v for v in primary_vendors if v and v != "default"]
    if explicit:
        vendor_chain = [v for v in explicit if v in VENDOR_METHODS[method]]
        if not vendor_chain:
            raise ValueError(
                f"Configured vendor(s) {explicit} not available for '{method}'. "
                f"Available: {all_available_vendors}."
            )
    else:
        vendor_chain = all_available_vendors

    last_no_data: NoMarketDataError | None = None
    last_unavailable: VendorRateLimitError | None = None
    last_not_configured: VendorNotConfiguredError | None = None
    last_auth: VendorAuthenticationError | None = None
    last_rejected: VendorRequestRejectedError | None = None
    first_error: Exception | None = None
    # Every vendor that reported an absence, not just the last one, so the
    # all-absent verdict can say which searches came back empty.
    no_data_vendors: list[str] = []
    # Every failure in chain order (vendor, exception). The last slot of each
    # kind drives the primary verdict; this list keeps the whole picture so a
    # combined failure is never described by whichever vendor happened to be
    # last -- swapping the chain must not lose a category.
    failures: list[tuple[str, BaseException]] = []

    def record(vendor_name: str, exc: BaseException) -> None:
        failures.append((vendor_name, exc))

    def raise_primary(primary: VendorError, absent=()):
        """Raise the chain's most actionable typed error, keeping the others.

        ``absent`` lists vendors that confirmed an absence in the same chain,
        so the raised error does not hide the fact that the symbol was also
        searched (and not found) elsewhere. Kept on the error, not appended to
        its message, so the type's voice is unchanged.
        """
        primary.with_chain_failures(_others(failures, primary))
        primary.absent_vendors = tuple(absent)
        if absent:
            # An absence alongside a fatal error is still context: log it, so
            # the raise path does not hide that the symbol was also searched
            # (the text path states this in its warning too).
            logger.warning(
                "Raising %s; vendor(s) %s also returned no usable data",
                type(primary).__name__, ", ".join(absent),
            )
        if primary.vendor is None:
            # Usually set by the router's handler; set it here too so a
            # re-used exception object is never attributed to a stale vendor.
            primary.with_vendor(next(v for v, exc in failures if exc is primary))
        raise primary

    # --- Bounded retries, shared by the whole chain ------------------------
    # A retry repeats the SAME vendor function; a different vendor is a
    # fall-through, not a retry. Both spend one shared budget (attempts and
    # wall-clock) so switching vendors cannot reset it, and the decision to
    # retry is made only from the error's own metadata (HTTP status, transport
    # type, Retry-After) -- never from its message text. Authentication, a
    # refused request, missing configuration, an absence, a stale frame, a
    # parse failure and an internal error are never retried: the chain moves on
    # exactly as in the first batch, whose verdicts below are unchanged.
    budget = _retry_budget()
    session = RetrySession(budget)
    breaker_policy = _breaker_policy()
    breakers = _breaker_registry(breaker_policy)

    def handle(vendor, exc) -> BaseException:
        """Record one vendor failure the batch-1 way; return the error to report.

        The returned object is what "the last failure of this kind" becomes; a
        raw exception the router could not classify is returned unchanged so it
        still surfaces as an internal error, not as a vendor condition.
        """
        nonlocal last_no_data, last_unavailable, last_not_configured
        nonlocal last_auth, last_rejected, first_error
        if isinstance(exc, VendorAuthenticationError):
            logger.warning(
                "Vendor %r rejected the configured credentials for %s; trying next vendor.",
                vendor, method,
            )
            last_auth = exc.with_vendor(vendor)
            record(vendor, last_auth)
            return last_auth
        if isinstance(exc, VendorRequestRejectedError):
            logger.warning(
                "Vendor %r refused the request for %s: %s; trying next vendor.",
                vendor, method, type(exc).__name__,
            )
            last_rejected = exc.with_vendor(vendor)
            record(vendor, last_rejected)
            return last_rejected
        if isinstance(exc, VendorNotConfiguredError):
            logger.warning("Vendor %r not configured for %s; trying next vendor.", vendor, method)
            last_not_configured = exc.with_vendor(vendor)
            record(vendor, last_not_configured)
            if first_error is None:
                first_error = exc  # Surface it if no other vendor can serve the call.
            return last_not_configured
        if isinstance(exc, NoMarketDataError):
            no_data_vendors.append(vendor)
            # No data here; another configured vendor may have it. Not a
            # failure: it is the one outcome that speaks about the symbol.
            last_no_data = exc.with_vendor(vendor)
            return last_no_data
        if isinstance(exc, VendorRateLimitError):
            logger.warning(
                "Vendor %r unavailable for %s: %s; trying next vendor.", vendor, method, exc
            )
            # Kept so an all-unavailable chain can say the vendor was the
            # problem, rather than reporting nothing about the symbol.
            last_unavailable = exc.with_vendor(vendor)
            record(vendor, last_unavailable)
            return last_unavailable
        # Don't let one vendor's failure crash the call when another can
        # serve it, but never swallow silently: a broken primary must be
        # visible in the logs (#989), not hidden behind a fallback's verdict.
        logger.warning("Vendor %r failed for %s: %s", vendor, method, exc)
        # A transport error a vendor did not classify still describes the
        # vendor, not the symbol. The classifier is backend-neutral and is
        # given this vendor's name, so a non-Yahoo timeout is never
        # reported as a Yahoo one.
        classified = as_vendor_error(exc, vendor)
        if isinstance(classified, VendorRateLimitError):
            last_unavailable = classified
            record(vendor, classified)
            return classified
        if isinstance(classified, VendorAuthenticationError):
            last_auth = classified
            record(vendor, classified)
            return classified
        if isinstance(classified, VendorRequestRejectedError):
            last_rejected = classified
            record(vendor, classified)
            return classified
        record(vendor, exc)
        # Only an *unclassified* error is a real surprise (a bug or an
        # unknown status). A timeout/429 that we just classified is not,
        # or it would masquerade as an internal error and be reported
        # twice with the wrong category.
        if first_error is None:
            first_error = exc
        return first_error

    def retry_verdict(vendor: str, exc: BaseException) -> tuple[bool, str]:
        """Whether one more invocation of ``vendor`` may fix ``exc``, and the wait.

        Unclassified exceptions never qualify: an internal bug is not a
        transient condition, and a vendor that did not say "come back" is not
        assumed to want that. A vendor that set ``retry`` explicitly wins over
        the generic rule (e.g. an exhausted daily quota is a throttle that
        waiting cannot lift).
        """
        if isinstance(exc, NoMarketDataError):
            return False, "no usable data (an absence, not an outage)"
        meta = _retry_metadata(exc)
        if meta is None:
            return False, "not a retryable vendor condition"
        recoverable, retry_after = meta
        if not recoverable:
            return False, "not transient"
        if retry_after is not None and retry_after > budget.max_retry_after_seconds:
            return False, (
                f"vendor asked to wait {retry_after:g}s, beyond the "
                f"{budget.max_retry_after_seconds:g}s per-wait limit"
            )
        fits, why = session.precheck(vendor)
        if not fits:
            return False, why
        wait = retry_after if retry_after is not None else _backoff_seconds(
            budget, session.vendor_attempts.get(vendor, 0)
        )
        if wait >= session.remaining():
            return False, (
                f"the {wait:g}s wait does not fit the {session.remaining():.1f}s left"
            )
        if wait > session.wait_allowance():
            return False, (
                f"the {wait:g}s wait exceeds the {session.wait_allowance():.1f}s "
                f"left of the chain's cumulative wait cap"
            )
        return True, wait

    for vendor in vendor_chain:
        vendor_impl = VENDOR_METHODS[method][vendor]
        impl_func = vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl

        # One ticket covers this vendor's whole logical call -- first attempt
        # and every retry -- so the breaker counts one final outcome, not each
        # attempt. It is taken *after* the budget gate below (a call the budget
        # already refuses never acquires one) and once per vendor.
        #
        # Everything a closure needs lives on this per-vendor object, *not* in
        # function-scope locals: ``nonlocal`` would bind every iteration of the
        # loop to the same cell, so the previous vendor's "already recorded"
        # flag could suppress this vendor's release (or vice versa).
        state = _VendorCall()
        ticket = None
        pending = None             # last proven vendor result awaiting a retry
        # The category a *guaranteed* release (the finally below) uses when the
        # vendor's verdict was never delivered: NEUTRAL, so an interruption or
        # an unexpected exit can never count for or against the vendor. It is
        # only ever used when no verdict was recorded; a real result is never
        # overwritten.
        ticket_category = NEUTRAL

        def release(category, state=state):
            """Complete this vendor's ticket exactly once, with ``category``.

            Only the first call has an effect: a recorded verdict is never
            replaced, so the retry loop, the ``finally`` and any handler that
            races to release cannot count a result twice.
            """
            if state.ticket is None or state.recorded:
                return
            state.recorded = True
            state.ticket.finish(category)

        # The whole logical call -- retry decision, logging, waiting, the budget
        # gate and the handling of its result -- runs inside this guard. A
        # ``finally`` is the only construct that also runs when one of those
        # steps itself raises (an ``except`` block raising is not re-entered by
        # a sibling ``except BaseException``), so a probe can never be left
        # outstanding by a KeyboardInterrupt during a backoff wait or by a bug
        # in the retry bookkeeping.
        try:
            while True:
                # One gate for every start -- first call, retry and
                # fall-through -- checked immediately before the call and again
                # after any wait.
                allowed, why = session.precheck(vendor)
                if not allowed:
                    session.stop_reason = why
                    logger.warning(
                        "Skipping vendor %r for %s: %s (vendor calls so far: %d, "
                        "HTTP requests: %d, waited: %.1fs).",
                        vendor, method, why, session.attempts,
                        session.http_requests, session.waited,
                    )
                    spent = VendorRateLimitError(
                        f"the data budget ran out before this vendor was tried ({why})"
                    ).with_retry_evidence(retry=False)
                    last_unavailable = spent.with_vendor(vendor)
                    record(vendor, last_unavailable)
                    # A retry the budget refused does not erase what the vendor
                    # already proved; a vendor never reached at all is NEUTRAL.
                    if pending is not None:
                        ticket_category = pending
                    release(ticket_category)
                    break

                # The breaker is asked only when a call could actually start, so
                # a spent budget is never reported as a breaker skip and a
                # breaker skip never consumes an attempt or a request.
                if ticket is None and breakers is not None:
                    skip_reason: list[str] = []
                    acquired = breakers.try_acquire(
                        vendor,
                        scope=breaker_scope(VENDOR_ENDPOINTS.get(vendor, ""), breaker_policy),
                        reason_out=skip_reason,
                    )
                    if acquired is None:
                        reason = skip_reason[0] if skip_reason else "circuit_open"
                        logger.warning(
                            "Skipping vendor %r for %s: circuit breaker %s "
                            "(no attempt, no HTTP request spent).",
                            vendor, method, reason,
                        )
                        skipped = VendorRateLimitError(
                            f"the vendor call was not started by the circuit breaker "
                            f"({reason})"
                        ).with_retry_evidence(retry=False)
                        last_unavailable = skipped.with_vendor(vendor)
                        record(vendor, last_unavailable)
                        break
                    ticket = acquired
                    state.ticket = acquired

                session.note_attempt(vendor)
                try:
                    with retry_session(session):
                        result = impl_func(*args, **kwargs)
                except Exception as exc:
                    # ``handle`` classifies the original -- a bare ``requests.Timeout``
                    # becomes a typed vendor error carrying status/retry evidence.
                    # The breaker reads *that* proof, with the original as witness,
                    # never the raw exception's class.
                    error = handle(vendor, exc)

                    retry, wait = retry_verdict(vendor, error)
                    # The vendor itself proved the condition momentary: its error
                    # said so, and the call ended on it -- our own limits (attempt
                    # allowance, deadline) never make a failure "the vendor's".
                    provable = _classified_vendor_failure(exc, error, budget)
                    breaker_category = _breaker_result(exc, provable=provable, classified=error)
                    if not retry:
                        logger.info(
                            "Vendor %r for %s will not be retried: %s.", vendor, method, wait
                        )
                        release(breaker_category)
                        break
                    logger.warning(
                        "Retrying vendor %r for %s in %.1fs (vendor attempt %d/%d, "
                        "chain attempt %d/%d, waited so far %.1fs of %gs).",
                        vendor, method, wait,
                        session.vendor_attempts.get(vendor, 0), budget.attempts_for(vendor),
                        session.attempts, budget.max_attempts,
                        session.waited, budget.max_cumulative_wait_seconds,
                    )
                    # The failed attempt is superseded by the retry: drop it from the
                    # failure picture so the final verdict names what is still true.
                    failures[:] = [entry for entry in failures if entry[1] is not error]
                    if not session.pause(wait):
                        # The wait did not fit. The vendor *did* say the condition
                        # was momentary, so this is a real vendor failure (the
                        # vendor-side evidence, not our own limit, decides).
                        release(breaker_category)
                        break
                    # The wait is over: the deadline is checked again by precheck at
                    # the top of this loop, before the retry starts. If it refuses,
                    # the vendor's last real result for this call was the failure
                    # above; it is reported then, as a budget stop, not as a new
                    # vendor failure, so nothing must overwrite it with NEUTRAL.
                    pending = breaker_category
                else:
                    # A retry that finally succeeded (or a first success) is a
                    # SUCCESS for the whole logical call: intermediate failures are
                    # not counted.
                    release(SUCCESS)
                    return result
        finally:
            # The one guaranteed exit for every path -- normal break, return,
            # an exception handled above, and an interruption or bug *inside*
            # that handling (a KeyboardInterrupt during the backoff wait, a
            # failing log call, a bug in the retry bookkeeping). Idempotent: a
            # verdict already recorded by ``release`` is never replaced, and a
            # vendor that was never admitted has nothing to finish. Whatever is
            # still outstanding is unfinished work, so it leaves as NEUTRAL --
            # a probe is freed and no success or failure is invented.
            release(ticket_category)

    # Only an absence every configured vendor confirmed is a fact about the
    # symbol. One vendor's empty result next to another's outage, throttle or
    # rejected key says nothing about it, so the verdict below names the
    # actual failures instead of claiming the instrument has no data.
    if (
        last_no_data is not None
        and first_error is None
        and last_unavailable is None
        and last_auth is None
        and last_not_configured is None
        and last_rejected is None
    ):
        sym = last_no_data.symbol
        canonical = last_no_data.canonical
        resolved = "" if canonical == sym else f" (resolved to '{canonical}')"
        # Surface the typed error's detail (e.g. "latest row is 2025-06-11 ...
        # stale") so the agent sees the specific reason �?invalid symbol, no
        # coverage, or stale data �?not just a generic "unavailable".
        reason = f" ({last_no_data.detail})" if last_no_data.detail else ""
        searched = ", ".join(no_data_vendors) if no_data_vendors else "the configured vendor"
        return (
            f"NO_DATA_AVAILABLE: No usable market data for '{sym}'{resolved} from "
            f"the configured vendor(s) ({searched}){reason}. The symbol may be invalid, "
            f"delisted, not covered, or the vendor returned stale data. Do not estimate or "
            f"fabricate values �?report that data is unavailable for this symbol."
        )

    # Decide what *must be raised* before building any absence or degraded
    # text. An absence from one vendor must never downgrade a core error that
    # the contract requires to surface: the no-data branch below would
    # otherwise return plain DATA_UNAVAILABLE for "empty + rejected key".
    # Precedence is ``_RANK``: auth > refused > bug > (absence).
    must_raise: VendorError | None = None
    if category not in OPTIONAL_CATEGORIES:
        must_raise = last_auth or last_rejected or (
            first_error if isinstance(first_error, VendorError) else None
        )
    if must_raise is not None:
        raise_primary(must_raise, absent=no_data_vendors)
    if (
        category not in OPTIONAL_CATEGORIES
        and first_error is not None
        and not isinstance(first_error, VendorError)
    ):
        # An unclassified internal error: core never degrades it to text, even
        # when another vendor's absence would otherwise explain the chain. The
        # absence sources are logged (the bug has no chain context of its own).
        logger.warning(
            "Raising %s for core %s despite absence from %s",
            type(first_error).__name__, method,
            ", ".join(no_data_vendors) or "no vendor",
        )
        raise first_error

    # A configured vendor searched and found nothing, but another failed for a
    # reason that is not about the instrument. State both, and assert neither
    # "no data" nor "every vendor is down".
    if last_no_data is not None and failures:
        searched = ", ".join(no_data_vendors)
        kinds = _distinct_kinds(failures)
        # Name the failing vendors themselves, not just whichever kind happened
        # to be checked first: with three+ vendors the attributed vendor and
        # the actual cause could otherwise disagree.
        failing = ", ".join(vendor for vendor, _ in failures)
        logger.warning(
            "Mixed vendor outcome for %s: no data from %s; failures: %s",
            method, searched,
            "; ".join(f"{v}: {type(e).__name__} ({_cause(e)})" for v, e in failures),
        )
        # The sentence names the absent vendors, the failing vendors and every
        # category (listed by name, with each vendor's real cause further down
        # in the combination), so ``covered`` stops the "also" line repeating
        # it. ``kinds[0]`` is ``_RANK``'s most actionable category, whose
        # remedy ("Check the API key", "retrying may help", ...) would
        # otherwise be lost behind the absence.
        return _robust_verdict(
            method,
            f"DATA_UNAVAILABLE: {method} could not be confirmed for '{last_no_data.symbol}'. "
            f"Vendor(s) {searched} returned no usable data (an absence, not an error), "
            f"while vendor(s) {failing} failed ({', '.join(kinds)}). "
            f"No configured vendor could serve it, so this is not a confirmed "
            f"absence. Do not estimate or fabricate values. ",
            kinds[0],
            failures,
            no_data_vendors,
            covered=kinds,
        )

    # Verdict precedence is ``_RANK``: auth > refused > outage > unconfigured >
    # bug. It is checked in that order, not in chain order, so whichever vendor
    # happened to fail last cannot downgrade a rejected key to "unavailable".
    #
    # A supplied-but-rejected key is actionable and must not read as an outage:
    # the user can fix it, and retrying will not help. Core data surfaces it as
    # the typed exception so a caller cannot mistake it for normal tool content;
    # optional enrichment keeps its sentinel contract and only names the cause.
    # It outranks "not configured" when both occur: a missing key on one vendor
    # is a setup note, but a rejected key is a wrong credential the user must fix.
    if last_auth is not None:
        if category not in OPTIONAL_CATEGORIES:
            raise_primary(last_auth)
        return _robust_verdict(
            method,
            f"DATA_UNAVAILABLE: vendor(s) {last_auth.vendor} rejected the configured "
            f"credentials for {method}: {_cause(last_auth)}. Provide a valid API key; this is a "
            f"configuration problem, not a missing-symbol or outage. ",
            "auth",
            failures,
            no_data_vendors,
        )

    # The vendor answered and refused the request itself (400/404): the
    # instrument or parameters are wrong, which is distinct both from an outage
    # (retrying will not help) and from a confirmed absence (the vendor did not
    # say the symbol has no data, only that it could not serve this request).
    if last_rejected is not None:
        if category not in OPTIONAL_CATEGORIES:
            raise_primary(last_rejected)
        return _robust_verdict(
            method,
            f"DATA_UNAVAILABLE: vendor(s) {last_rejected.vendor} refused the {method} "
            f"request for the supplied parameters ({type(last_rejected).__name__}). "
            f"This is not a confirmed absence; do not estimate or fabricate values. ",
            "rejected",
            failures,
            no_data_vendors,
        )

    # An unknown or unclassified failure outranks an outage in ``_RANK``: a bug
    # must not be described as "temporarily unavailable" just because another
    # vendor timed out. Core raises it; optional keeps its sentinel contract but
    # names the bug by type and lists every vendor with its real cause.
    if first_error is not None:
        if category not in OPTIONAL_CATEGORIES:
            if isinstance(first_error, VendorError):
                raise_primary(first_error)
            raise first_error
        logger.warning("Optional %s unavailable for %s: %s", category, method, first_error)
        return _robust_verdict(
            method,
            f"DATA_UNAVAILABLE: optional {category} could not be retrieved "
            f"({type(first_error).__name__}). Proceed without it; do not fabricate values. ",
            "unknown",
            failures,
            no_data_vendors,
        )

    # Only outcomes that are all degradable reach here as a sentinel: every
    # configured vendor was not configured (its error was already raised above
    # when nothing else failed) or throttled/unreachable. That is a fact about
    # the vendors, not about the instrument, and it must not end the run.
    if last_unavailable is not None:
        return _robust_verdict(
            method,
            f"DATA_UNAVAILABLE: no configured vendor could serve {method} right now "
            f"({last_unavailable}). This says nothing about the instrument; report the "
            f"data as unavailable and do not estimate or fabricate values. ",
            "unavailable",
            failures,
            no_data_vendors,
        )

    raise RuntimeError(f"No available vendor for '{method}'")
