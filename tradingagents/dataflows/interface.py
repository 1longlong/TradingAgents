import logging

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
)
from .fred import get_macro_data as get_fred_macro_data
from .polymarket import get_prediction_markets as get_polymarket_prediction_markets
from .sec_edgar import (
    get_balance_sheet as get_sec_edgar_balance_sheet,
    get_cashflow as get_sec_edgar_cashflow,
    get_income_statement as get_sec_edgar_income_statement,
)
from .stockstats_utils import as_vendor_error
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
    # vendors the user did not choose (#988/#289) — that returned data from an
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

    for vendor in vendor_chain:
        vendor_impl = VENDOR_METHODS[method][vendor]
        impl_func = vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl

        try:
            return impl_func(*args, **kwargs)
        except VendorRateLimitError as e:
            logger.warning(
                "Vendor %r unavailable for %s: %s; trying next vendor.", vendor, method, e
            )
            # Kept so an all-unavailable chain can say the vendor was the
            # problem, rather than reporting nothing about the symbol.
            last_unavailable = e.with_vendor(vendor)
            record(vendor, last_unavailable)
            continue
        except VendorAuthenticationError as e:
            logger.warning(
                "Vendor %r rejected the configured credentials for %s; trying next vendor.",
                vendor, method,
            )
            last_auth = e.with_vendor(vendor)
            record(vendor, last_auth)
            continue
        except VendorRequestRejectedError as e:
            logger.warning(
                "Vendor %r refused the request for %s: %s; trying next vendor.",
                vendor, method, type(e).__name__,
            )
            last_rejected = e.with_vendor(vendor)
            record(vendor, last_rejected)
            continue
        except VendorNotConfiguredError as e:
            logger.warning("Vendor %r not configured for %s; trying next vendor.", vendor, method)
            last_not_configured = e.with_vendor(vendor)
            record(vendor, last_not_configured)
            if first_error is None:
                first_error = e  # Surface it if no other vendor can serve the call.
            continue
        except NoMarketDataError as e:
            no_data_vendors.append(vendor)
            # No data here; another configured vendor may have it. Not a
            # failure: it is the one outcome that speaks about the symbol.
            last_no_data = e.with_vendor(vendor)
            continue
        except Exception as e:
            # Don't let one vendor's failure crash the call when another can
            # serve it, but never swallow silently: a broken primary must be
            # visible in the logs (#989), not hidden behind a fallback's verdict.
            logger.warning("Vendor %r failed for %s: %s", vendor, method, e)
            # A transport error a vendor did not classify still describes the
            # vendor, not the symbol. The classifier is backend-neutral and is
            # given this vendor's name, so a non-Yahoo timeout is never
            # reported as a Yahoo one.
            classified = as_vendor_error(e, vendor)
            if isinstance(classified, VendorRateLimitError):
                last_unavailable = classified
                record(vendor, classified)
            elif isinstance(classified, VendorAuthenticationError):
                last_auth = classified
                record(vendor, classified)
            elif isinstance(classified, VendorRequestRejectedError):
                last_rejected = classified
                record(vendor, classified)
            else:
                record(vendor, e)
                # Only an *unclassified* error is a real surprise (a bug or an
                # unknown status). A timeout/429 that we just classified is not,
                # or it would masquerade as an internal error and be reported
                # twice with the wrong category.
                if first_error is None:
                    first_error = e
            continue

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
        # stale") so the agent sees the specific reason — invalid symbol, no
        # coverage, or stale data — not just a generic "unavailable".
        reason = f" ({last_no_data.detail})" if last_no_data.detail else ""
        searched = ", ".join(no_data_vendors) if no_data_vendors else "the configured vendor"
        return (
            f"NO_DATA_AVAILABLE: No usable market data for '{sym}'{resolved} from "
            f"the configured vendor(s) ({searched}){reason}. The symbol may be invalid, "
            f"delisted, not covered, or the vendor returned stale data. Do not estimate or "
            f"fabricate values — report that data is unavailable for this symbol."
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
