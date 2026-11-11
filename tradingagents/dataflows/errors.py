"""Vendor data-error taxonomy.

A single hierarchy so the routing layer reacts by *behavior*, not by vendor:
every condition where a vendor cannot return usable data derives from
``VendorError``, and the router catches the base types. A new vendor raises
these (or a thin vendor-named subclass) and needs no new ``except`` clause.

    VendorError
    ├── NoMarketDataError          no usable rows (empty result OR stale data)
    ├── VendorRateLimitError       transient throttle -> skip to next vendor
    ├── VendorUnavailableError     endpoint not serving -> skip to next vendor
    │   └── VendorTimeoutError     socket timeout -> skip to next vendor, but
    │                              NOT a throttle, so no retry/backoff advice
    └── VendorNotConfiguredError   missing API key/config -> vendor unavailable

The number of types is the number of distinct router reactions, not the number
of human-describable causes: empty and stale data get identical handling, so
they share ``NoMarketDataError`` and differ only in the free-text ``detail``.
"""

from __future__ import annotations


class VendorError(Exception):
    """Base for any condition where a vendor could not return usable data."""


class NoMarketDataError(VendorError):
    """A vendor returned no usable rows for a symbol (empty result or stale data).

    Carries both the symbol the user requested and the canonical symbol the
    vendor was actually queried with, plus a free-text ``detail``, so callers
    can build a clear message instead of emitting a vendor-specific empty
    string into the data channel.
    """

    def __init__(self, symbol: str, canonical: str | None = None, detail: str = ""):
        self.symbol = symbol
        self.canonical = canonical or symbol
        self.detail = detail
        msg = f"No market data for {symbol!r}"
        if canonical and canonical != symbol:
            msg += f" (queried as {canonical!r})"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)


class VendorRateLimitError(VendorError):
    """A vendor throttled the request; the router skips to the next vendor."""


class VendorNotConfiguredError(VendorError, ValueError):
    """A vendor was selected but its API key/configuration is missing.

    Also a ``ValueError`` so existing callers that catch ``ValueError`` keep
    working while the routing layer can treat it as "vendor unavailable".
    """


class VendorUnavailableError(VendorError):
    """A vendor endpoint is permanently not serving (retired, removed, shut down).

    Distinct from ``VendorRateLimitError``, which promises "try again later":
    this one is final for the endpoint in question. The router treats it like a
    rate-limit error (skip to the next vendor, and if none serves the call,
    return ``DATA_UNAVAILABLE``) rather than re-raising, because the news
    category is core and a retired third-party API must not end the run.
    """


class VendorTimeoutError(VendorUnavailableError):
    """A vendor request did not answer before the socket timeout.

    Distinct from ``VendorRateLimitError``: a timeout says nothing about how
    fast the caller may retry, and folding it into the throttle class made the
    two indistinguishable in logs and in the failure matrix. It subclasses
    ``VendorUnavailableError`` so the router's existing reaction (skip to the
    next vendor, end in ``DATA_UNAVAILABLE`` when none serves) applies
    unchanged; a timeout must *not* take the rate-limit path.

    Note this is "unavailable *for this call*", not the parent's usual
    "permanently retired": the router only branches on the base class, so the
    subclass changes the *label* callers see and which ``except`` clauses match,
    not the routing.
    """
