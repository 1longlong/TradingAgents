"""Vendor data-error taxonomy.

A single hierarchy so the routing layer reacts by *behavior*, not by vendor:
every condition where a vendor cannot return usable data derives from
``VendorError``, and the router catches the base types. A new vendor raises
these (or a thin vendor-named subclass) and needs no new ``except`` clause.

    VendorError
    ├── NoMarketDataError          no usable rows (empty result OR stale data)
    ├── VendorRateLimitError       transient throttle -> skip to next vendor
    ├── VendorAuthenticationError  key supplied but rejected (401/403)
    ├── VendorRequestRejectedError vendor refused the request (400/404)
    └── VendorNotConfiguredError   missing API key/config -> vendor unavailable

The number of types is the number of distinct router reactions, not the number
of human-describable causes: empty and stale data get identical handling, so
they share ``NoMarketDataError`` and differ only in the free-text ``detail``.

Two distinctions the types above deliberately keep apart:

- A *transport* failure (timeout, refused connection, DNS) is not "no data".
  ``NoMarketDataError`` makes a claim about the instrument; an outage says
  nothing about it, so the router must not report one as the other. Callers
  therefore let ``requests``/socket exceptions cover to the router, which
  treats a non-``VendorError`` exception as an error, never as an absence.
- A vendor's *own* identity is not the vendor's job to know. ``vendor`` is
  optional and filled in once, at the routing boundary, so the final verdict
  can name which sources failed without every vendor module hardcoding itself.
"""

from __future__ import annotations


class VendorError(Exception):
    """Base for any condition where a vendor could not return usable data.

    ``vendor`` optionally records which source raised (filled by
    ``route_to_vendor`` when the raiser did not set it), so a chain-level
    summary can name its members without the raiser knowing its own label.

    ``chain_failures`` is filled only by the routing layer when several vendors
    failed at once and one exception has to be raised: it holds every other
    failure as ``(vendor, exception)`` pairs, in chain order, so the raised
    error never hides a coexisting condition (e.g. an internal bug behind a
    rejected key). ``absent_vendors`` likewise names vendors that confirmed an
    absence in the same chain, so "the symbol was also searched and not found"
    is not lost when another failure must surface. Both stay empty for a single
    failure.
    """

    vendor: str | None = None

    def __init__(self, *args):
        super().__init__(*args)
        self.chain_failures: tuple[tuple[str, BaseException], ...] = ()
        self.absent_vendors: tuple[str, ...] = ()

    def with_vendor(self, vendor: str) -> VendorError:
        """Attach the routing layer's vendor label unless one is already set."""
        if self.vendor is None:
            self.vendor = vendor
        return self

    def with_chain_failures(self, failures) -> VendorError:
        """Record the other failures of the chain this error was raised from."""
        self.chain_failures = tuple(failures)
        return self


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

    A key that was supplied but *rejected* (HTTP 401/403) is NOT a
    configuration error -- the caller did configure the vendor and cannot fix
    it by setting an env var. ``VendorAuthenticationError`` covers that case so
    the router's message can tell the two apart.
    """


class VendorAuthenticationError(VendorError):
    """A credential was supplied but the vendor rejected it (HTTP 401/403).

    Distinct from ``VendorNotConfiguredError`` (nothing was supplied): the fix
    is to correct the key, not to add one. Deliberately not a ``ValueError`` so
    it cannot be confused with "the vendor was never configured".
    """


class VendorRequestRejectedError(VendorError):
    """The vendor refused this request on its merits (HTTP 400/404, unknown symbol).

    The credential worked and the service is up, so this is neither an outage
    to retry nor an absence to report as "the instrument has no data": the
    request itself was wrong or the resource does not exist. Kept separate so
    the router can say exactly that instead of guessing between the two.
    """
