# ADR-012-error-handling-merge-integration.md: contract typing/security, NFR-BC-001, INV-1.
import re
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import requests


def _https_origin(url: str) -> tuple[str, int]:
    """ADR-012 / NFR-PIT-001: reject non-HTTPS and ambiguous feed authorities."""
    try:
        parts = urlsplit(url)
        if (parts.scheme != "https" or not parts.hostname
                or parts.username is not None or parts.password is not None
                or any(char.isspace() or ord(char) < 32 for char in url)):
            raise ValueError("invalid HTTPS authority")
        return parts.hostname.lower(), parts.port or 443
    except ValueError as exc:
        raise URLError("Feed transport requires an HTTPS URL without credentials") from exc


class _FeedRedirectHandler(HTTPRedirectHandler):
    """Keep feed redirects on the validated HTTPS origin (ADR-012)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if _https_origin(newurl) != _https_origin(req.full_url):
            raise URLError("Cross-origin feed redirect refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_https_feed(request: Request, *, timeout: float):
    """Open a public feed with scheme checks on both initial and redirect URLs.

    ADR-012: retain urllib's HTTP errors, response context manager and timeout;
    file/custom schemes, credentialed authorities and off-origin redirects
    never reach a transport handler. Callers keep their existing offline seam.
    """
    _https_origin(request.full_url)
    return build_opener(_FeedRedirectHandler()).open(request, timeout=timeout)

# Tickers can contain letters, digits, dot, dash, underscore, caret
# (index symbols like ^GSPC), equals (futures like GC=F), and plus
# (forex/CFD symbols like XAUUSD+). None of these enable directory
# traversal, so the value never escapes a containing directory when
# interpolated into a path. Anything else is rejected.
_TICKER_PATH_RE = re.compile(r"^[A-Za-z0-9._\-\^=+]+$")


def safe_ticker_component(value: str, *, max_len: int = 32) -> str:
    """Validate ``value`` is safe to interpolate into a filesystem path.

    Tickers come from user CLI input or from LLM tool calls, both of which
    can be influenced by attacker-controlled content (e.g. prompt injection
    embedded in fetched news). Without validation, a value like
    ``"../../../etc/foo"`` flows into ``os.path.join`` / ``Path /`` and
    escapes the configured cache, checkpoint, or results directory.

    Returns ``value`` unchanged when it matches the allowed pattern; raises
    ``ValueError`` otherwise.
    """
    if not isinstance(value, str) or not value:
        raise ValueError(f"ticker must be a non-empty string, got {value!r}")
    if len(value) > max_len:
        raise ValueError(f"ticker exceeds {max_len} chars: {value!r}")
    if not _TICKER_PATH_RE.fullmatch(value):
        raise ValueError(
            f"ticker contains characters not allowed in a filesystem path: {value!r}"
        )
    # The regex above allows '.', so values like '.', '..', '...' would pass,
    # and as a path component they traverse the parent directory. Reject any
    # value that's only dots.
    if set(value) == {"."}:
        raise ValueError(f"ticker cannot consist solely of dots: {value!r}")
    return value


def get_current_date():
    return date.today().strftime("%Y-%m-%d")


def retry_after_seconds(headers) -> float | None:
    """The ``Retry-After`` delay a response asked for, or None when unusable.

    A vendor's own wait instruction is the only *reliable* recovery signal: it
    says a short pause suffices. Both RFC 9110 forms are read -- delta-seconds
    and an HTTP-date (converted against the response's clock, i.e. now, never
    against a keyed URL). Anything absent, malformed or negative is None, so a
    caller never guesses a wait from text.
    """
    value = None
    try:
        value = headers.get("Retry-After")
    except (AttributeError, TypeError):
        return None
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        seconds = float(text)
    except ValueError:
        try:
            when = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
        if when is None:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        seconds = (when - _utc_now()).total_seconds()
    return seconds if seconds >= 0 else None


def _utc_now():
    """The current UTC instant (a seam, so an HTTP-date Retry-After is testable)."""
    return datetime.now(timezone.utc)


def get_scrubbed(
    url: str,
    *,
    params: dict,
    timeout: float,
    secret: str,
    passthrough=(),
    extra_metadata=None,
):
    """``requests.get`` plus ``raise_for_status``, with ``secret`` kept out of errors.

    Vendors that authenticate with a query parameter put the key in the URL, and
    requests quotes the full URL in HTTP, connection and timeout errors, so any
    log or traceback that records one would carry the key (#1324). A requests
    error is re-raised as the same class with the key replaced and nothing
    attached: no request or response (both hold the URL) and no exception chain,
    which is why this raises after the ``except`` block rather than inside it.
    Statuses in ``passthrough`` are returned for the caller to handle.

    The rebuilt error keeps the HTTP status the original carried (on
    ``.response`` and in its message prefix), so a caller can still tell a
    throttle from a rejected key without the response—and therefore the URL
    with the key—being re-attached.

    ``extra_metadata`` maps attribute names to values copied from the *original*
    response; it exists for retention facts that decide a retry (e.g.
    ``Retry-After``) but that the rebuilt error must carry without the response
    being re-attached. Only pass scalars read from headers -- never the
    response, the request or the URL.
    """
    try:
        response = requests.get(url, params=params, timeout=timeout)
        if response.status_code not in passthrough:
            response.raise_for_status()
        return response
    except requests.RequestException as exc:
        if not secret:
            raise
        error = type(exc)(str(exc).replace(secret, "***"))
        original = getattr(exc, "response", None)
        status = getattr(original, "status_code", None)
        if isinstance(status, int):
            # A bare status stub, not the live response; the rebuilt error's
            # own args already carry the status, and the URL is already scrubbed.
            error.response = requests.models.Response()
            error.response.status_code = status
        if extra_metadata:
            for name, value in extra_metadata(original).items():
                if value is not None:
                    setattr(error, name, value)
    raise error


def vendor_reachable(url: str, timeout: float = 5.0) -> bool:
    """Whether the vendor answers at all, for telling silence from an outage.

    A client that returns an empty result instead of raising leaves those two
    cases indistinguishable. Called only when a result is empty.
    """
    try:
        requests.head(url, timeout=timeout, allow_redirects=True)
        return True
    except requests.RequestException:
        return False
