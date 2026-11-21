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

from requests.models import Response


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

    ``status`` and ``retry_after`` are the *retry decision's* metadata, kept
    separate from the free-text message so the router never guesses a cause from
    wording. ``status`` is the HTTP status the vendor answered with (None for a
    transport failure, which has none). ``retry_after`` is the delay a 429 asked
    for, in seconds, read from the response's ``Retry-After`` header.

    Whether a condition is recoverable is not a property of the class: a
    ``VendorRateLimitError`` covers both a minute-long 429 and a daily quota
    the vendor will not restore by waiting. ``retry`` records the verdict the
    raiser reached from its own facts (``True``/``False``), and ``None`` means
    it stated none -- the router then applies ``as_vendor_error``'s status and
    transport rules, and decides *not* to retry when those are inconclusive.
    """

    vendor: str | None = None

    def __init__(self, *args):
        super().__init__(*args)
        self.chain_failures: tuple[tuple[str, BaseException], ...] = ()
        self.absent_vendors: tuple[str, ...] = ()
        self.status: int | None = None
        self.retry_after: float | None = None
        self.retry: bool | None = None

    def describe_for_retry(self) -> str:
        """The status and wait this failure carried, without the message text."""
        parts = []
        if self.status is not None:
            parts.append(f"HTTP {self.status}")
        if self.retry_after is not None:
            parts.append(f"Retry-After {self.retry_after:g}s")
        return ", ".join(parts)

    def with_vendor(self, vendor: str) -> VendorError:
        """Attach the routing layer's vendor label unless one is already set."""
        if self.vendor is None:
            self.vendor = vendor
        return self

    def with_chain_failures(self, failures) -> VendorError:
        """Record the other failures of the chain this error was raised from."""
        self.chain_failures = tuple(failures)
        return self

    def with_retry_evidence(
        self,
        *,
        status: int | None = None,
        retry_after: float | None = None,
        retry: bool | None = None,
    ) -> VendorError:
        """Attach the facts a retry decision needs, without touching the message."""
        if status is not None:
            self.status = status
        if retry_after is not None:
            self.retry_after = retry_after
        if retry is not None:
            self.retry = retry
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


# Statuses that say "the service is momentarily unable", not "your request is
# wrong": safe to repeat after a pause. 501 (not implemented) and 505 (HTTP
# version) are excluded -- retrying cannot change them.
TRANSIENT_SERVICE_STATUSES = (502, 503, 504)

# The wait a request may be repeated after a 429 that says nothing itself. Small
# on purpose: the router also enforces its own (short) time budget, and a
# throttle that needs longer is the next vendor's turn instead.
DEFAULT_RATE_LIMIT_WAIT_SECONDS = 2.0


def retryable_status(status: int | None, retry_after: float | None = None) -> bool | None:
    """Whether an HTTP status is recoverable by retrying the *same* vendor.

    ``True`` for 429 (throttled), 502/503/504 (transiently unavailable) and a
    500 that carries a ``Retry-After`` (the vendor itself expects the caller
    back). ``False`` for 500 without one, 501/505 and every other status: not
    proven recoverable, so it is never retried on a guess. ``None`` for no
    status at all (a transport failure, handled by the caller).
    """
    if status is None:
        return None
    if status == 429 or status in TRANSIENT_SERVICE_STATUSES:
        return True
    if status == 500:
        return retry_after is not None
    return False


def http_status(exc: BaseException, http_error_types: tuple[type[BaseException], ...] = ()):
    """The HTTP status an exception carries, if it carries one.

    Backend-neutral: ``http_error_types`` names the HTTP-error class(es) of the
    client in use, so only *their* own message template is trusted for a status
    ("NNN Client Error: ..." / "HTTP Error NNN: ..."). ``requests``/``curl_cffi``
    keep the status on ``.response``; a re-raised scrubbed error has that
    response detached and keeps only its message in ``.args``.

    A status is read from an ``HTTPError``'s message only once its response has
    been *detached*: one still attached and present is authoritative, and a
    client error without one was never raised by the client.
    """
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        return status
    if not http_error_types or not isinstance(exc, http_error_types):
        return None
    if isinstance(response, Response):
        # An HTTPError raised by ``raise_for_status`` always carries its
        # response; one that does not was constructed by hand (e.g. a mock),
        # and its message must not be mined for a status it never had.
        return None
    for arg in getattr(exc, "args", ()):
        if not isinstance(arg, str):
            continue
        # Require the client library's own template, so free text that merely
        # begins with digits ("404 pages were not found") is never a status.
        client_error = (
            len(arg) >= 5
            and arg[:3].isdigit()
            and arg[3] == " "
            and arg[4:].startswith(("Client Error:", "Server Error:"))
        )
        if client_error:
            return int(arg[:3])
        prefix = arg[:15]
        if prefix.startswith("HTTP Error ") and arg[11:14].isdigit():
            return int(arg[11:14])
    return None


def retryable_transport_error(exc: BaseException) -> bool:
    """Whether a statusless failure is a momentary network condition.

    A timeout or a refused/reset connection may succeed on a fresh attempt. A
    TLS failure or an unusable URL will not: those are configuration, not an
    outage, so they are never retried. An exception of an unknown type is not
    assumed transient.
    """
    try:
        import requests
    except ImportError:  # pragma: no cover - requests is a hard dependency
        return False
    if isinstance(
        exc,
        (
            requests.exceptions.SSLError,
            requests.exceptions.InvalidURL,
            requests.exceptions.MissingSchema,
            requests.exceptions.InvalidSchema,
        ),
    ):
        return False
    if isinstance(
        exc,
        (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
            TimeoutError,
        ),
    ):
        return True
    # yfinance may run on curl_cffi instead of requests; its classes are
    # unrelated, so both backends are named. Only the network ones qualify (its
    # ``CurlError`` family also carries malformed-body failures).
    try:
        from curl_cffi import requests as curl_client

        curl_exc = curl_client.exceptions
        if isinstance(
            exc,
            tuple(
                getattr(curl_exc, name)
                for name in ("SSLError", "CertificateVerifyError", "InvalidURL", "MissingSchema")
                if hasattr(curl_exc, name)
            ),
        ):
            return False
        return isinstance(
            exc,
            tuple(
                getattr(curl_exc, name)
                for name in (
                    "Timeout", "ConnectTimeout", "ReadTimeout", "ConnectionError",
                    "ChunkedEncodingError",
                )
                if hasattr(curl_exc, name)
            ),
        )
    except ImportError:
        return False
