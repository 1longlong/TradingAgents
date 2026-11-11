"""One taxonomy for every way a news request can fail to produce real content.

Before this module, each vendor classified its own failures differently, and the
router could only react to exception *type*. That produced two distinct lies:

* a **retired endpoint** (Yahoo's ``xhr/ncp``, HTTP 404) was mapped to
  ``VendorRateLimitError`` -> "transient, try again", when it is permanent;
* an **HTTP 200** carrying a vendor error message or recent-only items was
  indistinguishable from real news in the text handed to the analyst.

Twelve classes, one meaning each. They are the *observable status* of a news
request, and they are what the analyst reads. The rule that makes them worth
having is in :func:`render_status`: only ``SUCCESS_REAL_CONTENT`` ever reads as
news; every other class reads as an explicit statement that the vendor could
not answer. Nothing else is allowed to become neutrality.

The list is deliberately closed. Adding a class means adding a distinct
downstream reaction, which is what the old three-exception hierarchy could not
express.
"""

from __future__ import annotations

from enum import Enum

__all__ = [
    "NewsStatus",
    "CLASSES",
    "PROVES_REAL_NEWS",
    "TRANSIENT",
    "is_status_token",
    "render_status",
]


class NewsStatus(str, Enum):
    """The twelve observable outcomes of asking a news vendor for a window."""

    #: The vendor returned at least one article that was verified to be real,
    #: relevant to the requested instrument, and published inside the window.
    SUCCESS_REAL_CONTENT = "SUCCESS_REAL_CONTENT"
    #: The vendor answered authoritatively and there genuinely were no articles
    #: in the window. This is a fact about the instrument, not an outage.
    EMPTY_VALID = "EMPTY_VALID"
    #: The asked-for window is older than the vendor archives (e.g. GDELT's
    #: rolling ~3 months). The vendor was never able to answer.
    HISTORICAL_UNSUPPORTED = "HISTORICAL_UNSUPPORTED"
    #: The vendor answered, but every item it returned falls outside the
    #: requested window: it only serves recent content and cannot reach back.
    OUT_OF_WINDOW = "OUT_OF_WINDOW"
    #: No credential is configured for the vendor.
    AUTH_MISSING = "AUTH_MISSING"
    #: A credential was sent and the vendor rejected it.
    AUTH_INVALID = "AUTH_INVALID"
    #: The vendor throttled the request (HTTP 429 or its own rate-limit error).
    RATE_LIMITED = "RATE_LIMITED"
    #: The request timed out.
    TIMEOUT = "TIMEOUT"
    #: The vendor is permanently (or for this endpoint) not serving requests:
    #: a retired endpoint, a 404 on a known API path, or a "service down" body.
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    #: A non-transient HTTP error that is none of the above (400, 4xx, 5xx).
    HTTP_ERROR = "HTTP_ERROR"
    #: The vendor answered with something that could not be parsed as news.
    PARSE_ERROR = "PARSE_ERROR"
    #: The vendor is switched off in configuration.
    CONFIG_DISABLED = "CONFIG_DISABLED"


#: Every class, in a stable order, for documentation and exhaustive tests.
CLASSES: tuple[NewsStatus, ...] = tuple(NewsStatus)

#: The only class that asserts news content exists. Everything else must never
#: be rendered as, or read as, a news signal.
PROVES_REAL_NEWS: frozenset[NewsStatus] = frozenset({NewsStatus.SUCCESS_REAL_CONTENT})

#: Classes worth retrying within a single run. A permanent condition (auth,
#: retired endpoint, unsupported window) is *not* retried: retrying it burns
#: the probe budget and delays the run for a guaranteed failure.
TRANSIENT: frozenset[NewsStatus] = frozenset(
    {NewsStatus.RATE_LIMITED, NewsStatus.TIMEOUT, NewsStatus.HTTP_ERROR}
)

#: Human-readable detail prefixed to every non-success status, so a reader (and
#: a grep) can tell an outage from an absence without parsing free text.
_STATUS_TEXT = {
    NewsStatus.EMPTY_VALID: "the vendor answered and had no articles in this window",
    NewsStatus.HISTORICAL_UNSUPPORTED: "this window is older than the vendor archives",
    NewsStatus.OUT_OF_WINDOW: "the vendor only serves recent items, none in this window",
    NewsStatus.AUTH_MISSING: "no credential is configured for this vendor",
    NewsStatus.AUTH_INVALID: "the vendor rejected the credential",
    NewsStatus.RATE_LIMITED: "the vendor throttled the request",
    NewsStatus.TIMEOUT: "the request timed out",
    NewsStatus.PROVIDER_UNAVAILABLE: "the vendor endpoint is not serving (retired or down)",
    NewsStatus.HTTP_ERROR: "the vendor returned an HTTP error",
    NewsStatus.PARSE_ERROR: "the vendor response could not be parsed as news",
    NewsStatus.CONFIG_DISABLED: "the vendor is disabled in configuration",
}


def is_status_token(text: str | None) -> bool:
    """Whether ``text`` names a status token (used when reading tool output)."""
    if not text:
        return False
    return any(token.value in text for token in NewsStatus)


def render_status(
    status: NewsStatus,
    *,
    vendor: str,
    subject: str,
    start_date: str,
    end_date: str,
    detail: str | None = None,
) -> str:
    """Render one non-success status as analyst-facing text.

    Deliberately worded so the analyst cannot mistake it for news *or* for an
    empty result about the instrument (except :class:`NewsStatus.EMPTY_VALID`,
    which genuinely is one). Every other class says the vendor could not answer,
    which is a fact about the vendor.
    """
    if status in PROVES_REAL_NEWS:
        raise ValueError("render_status is for failure classes, not success")

    reason = _STATUS_TEXT[status]
    extra = f" ({detail})" if detail else ""
    # EMPTY_VALID is the one class that *is* a statement about the instrument.
    if status is NewsStatus.EMPTY_VALID:
        return (
            f"NEWS_STATUS={status.value}: no articles about {subject} were published "
            f"between {start_date} and {end_date} — {reason}{extra}. "
            "This is a real absence: do not infer that the instrument is quiet "
            "in any particular direction."
        )
    return (
        f"NEWS_STATUS={status.value}: {vendor} could not answer for {subject} "
        f"({start_date}..{end_date}) — {reason}{extra}. This says nothing about the "
        "instrument; report the news as unavailable rather than as neutral."
    )
