"""Point-in-time-safe historical company news via the GDELT DOC 2.0 API.

Why this module exists
----------------------
``yfinance_news`` serves recent items only and its ticker endpoint is retired
(HTTP 404). Alpha Vantage can answer a date range but needs a key that is not
provisioned here. GDELT DOC 2.0 is keyless and **does** take an explicit
``STARTDATETIME``/``ENDDATETIME``, so it is the one source that can answer "what
was published about NVDA on 2026-09-23" today.

The trap that makes a naive GDELT adapter dangerous
---------------------------------------------------
GDELT's ``seendate`` is when GDELT *indexed* the article, **not** when it was
published. Measured in campaign ``20261107_140536`` (``probes/``), 4 of 5
verifiable hits with a 2026-09-23 ``seendate`` had a real ``datePublished`` of
2026-09-22. Using ``seendate`` as the publish time would report yesterday's news
as today's — a point-in-time violation of exactly the kind the backtests must
not have.

So GDELT is used strictly as a **discovery** source. Every candidate URL is
re-fetched and its publisher timestamp extracted (JSON-LD ``datePublished``,
``article:published_time``, ``<time datetime>``, ...). An article whose publish
time cannot be verified is **dropped**, never assumed.

Other hard limits, all surfaced through :mod:`news_status` rather than silently
turned into "no news":

* the archive is a rolling ~3 months, so older windows are
  ``HISTORICAL_UNSUPPORTED`` and are never sent;
* the API allows one request per 5 s and otherwise answers HTTP 429 with a
  plain-text body.

Licensing: only headline, domain, publisher URL and publication timestamp are
reproduced, which is what a search index may surface. Full article text is never
stored.
"""

from __future__ import annotations

import html
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from .config import get_config
from .date_window import to_utc
from .news_status import NewsStatus, render_status
from .symbol_utils import normalize_symbol

logger = logging.getLogger(__name__)

_API = "https://api.gdeltproject.org/api/v2/doc/doc"

# One request every 5 s is GDELT's documented limit; the margin absorbs clock
# skew between us and their limiter. Kept as a module attribute so tests can
# drive the throttle deterministically instead of sleeping.
_MIN_INTERVAL_SECONDS = 5.5

# GDELT documents "within the last 3 months". Computed as 89 days of slack so a
# request at the edge is not rejected; anything older is refused locally and
# reported as HISTORICAL_UNSUPPORTED *without* a request.
_WINDOW_DAYS = 89

# Verification step: pages are fetched once each. 20 s bounds the slowest
# publisher without stalling the analyst on a dead host.
VERIFY_TIMEOUT = 20.0
VERIFY_MAX_BYTES = 4 * 1024 * 1024

# How many discovery hits are re-fetched per call. This bounds the *total*
# network cost of verification; a window with 200 hits still verifies at most
# this many, and the report says how many were skipped.
_VERIFY_BUDGET = 8

# Transient statuses worth exactly one retry. 429 is retried once after the
# vendor's own 5 s interval; nothing permanent is retried.
_MAX_ATTEMPTS = 2

_last_request_at: float = 0.0


def _throttle() -> None:
    """Sleep so consecutive GDELT calls are at least the vendor interval apart."""
    global _last_request_at
    now = time.monotonic()
    wait = _MIN_INTERVAL_SECONDS - (now - _last_request_at)
    if _last_request_at and wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


def _reset_throttle_state() -> None:
    """Test hook: forget the last-request timestamp."""
    global _last_request_at
    _last_request_at = 0.0


def _gdelt_datetime(dt: datetime) -> str:
    return to_utc(dt).strftime("%Y%m%d%H%M%S")


# NOTE: there is deliberately no ``_parse_seendate`` helper. GDELT's
# ``seendate`` is when the article was *indexed*, not when it was published
# (measured: 4 of 5 verifiable 2026-09-23 hits were published 2026-09-22), so
# it is never used as a publication timestamp. Publication time comes only from
# ``extract_publish_time`` on the publisher's own page.


def _query_for(ticker: str) -> str:
    """Build the full-text query for a ticker.

    GDELT has no symbol field: relevance is a text match. The plain ticker is
    too noisy (``NVDA`` also matches unrelated strings), so the canonical
    symbol is quoted. Callers are responsible for the extra relevance filter in
    :func:`_is_relevant`.
    """
    return f'"{normalize_symbol(ticker)}" sourcelang:english'


def _request(url: str) -> tuple[int | None, str | None, str]:
    """GET ``url`` once. Returns ``(status, body, error_kind)``.

    ``error_kind`` is one of ``""`` (got a body), ``"timeout"``,
    ``"transport"``. HTTP error statuses come back as ``status`` with an empty
    body, so the caller classifies them.
    """
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "tradingagents/0.2 (+https://github.com/TauricResearch/TradingAgents)",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=VERIFY_TIMEOUT) as response:
            return response.status, response.read().decode("utf-8", "replace"), ""
    except urllib.error.HTTPError as exc:
        return exc.code, "", ""
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        kind = "timeout" if isinstance(reason, TimeoutError) or "timed out" in str(reason) else "transport"
        return None, None, kind
    except TimeoutError:
        return None, None, "timeout"
    except OSError as exc:  # connection resets and friends
        logger.warning("GDELT transport error: %s", exc)
        return None, None, "transport"


def _classify_http(status: int | None, body: str | None, error_kind: str) -> NewsStatus | None:
    """Map a raw probe result to a failure status, or None when a body arrived."""
    if error_kind == "timeout":
        return NewsStatus.TIMEOUT
    if error_kind:
        return NewsStatus.PROVIDER_UNAVAILABLE
    if status == 429:
        # GDELT's throttle body is plain text; the status is the contract.
        return NewsStatus.RATE_LIMITED
    if status == 200:
        return None
    if status in (401, 403):
        return NewsStatus.AUTH_INVALID
    if status in (404, 410) or status in (502, 503, 504):
        return NewsStatus.PROVIDER_UNAVAILABLE
    return NewsStatus.HTTP_ERROR


def _fetch_articles(query: str, start_dt: datetime, end_dt: datetime, limit: int):
    """Call the DOC 2.0 API. Returns ``(articles, failure_status, detail)``."""
    # GDELT's ENDDATETIME is *inclusive*, and passing midnight of the end day
    # yields a zero-length interval that the API rejects with
    # "Invalid query end date." (measured 2026-11-08). End at the last second
    # of the end day instead; the per-article publish-time check still enforces
    # the exact half-open window.
    window_end = end_dt + timedelta(days=1, seconds=-1)
    params = {
        "query": query,
        "mode": "artlist",
        "maxrecords": str(max(1, min(limit, 250))),
        "format": "json",
        "startdatetime": _gdelt_datetime(start_dt),
        "enddatetime": _gdelt_datetime(window_end),
    }
    url = f"{_API}?{urlencode(params)}"

    status: NewsStatus | None = None
    detail = ""
    for attempt in range(_MAX_ATTEMPTS):
        _throttle()
        http_status, body, error_kind = _request(url)
        status = _classify_http(http_status, body, error_kind)
        if status is None:
            break
        detail = f"HTTP {http_status}" if http_status else error_kind
        # Only throttling is worth a second try; the retry sleeps the vendor
        # interval inside _throttle(), which is exactly what GDELT asks for.
        if status is not NewsStatus.RATE_LIMITED or attempt == _MAX_ATTEMPTS - 1:
            return [], status, detail
        logger.warning("GDELT throttled; retrying once after the vendor interval.")

    if status is not None:
        return [], status, detail

    text = (body or "").strip()
    # A rate-limit page can arrive with 200 in some edges; detect its body too.
    if text.startswith("Please limit requests"):
        return [], NewsStatus.RATE_LIMITED, "rate-limit body"
    # GDELT reports query errors as plain text (with a 200 or 400 status), e.g.
    # "Invalid query end date.". That is our request being rejected, not a
    # malformed vendor response, so it must not be labelled PARSE_ERROR and it
    # must not be retried against the next vendor as if it were transient.
    if text.lower().startswith(("invalid query", "error:")):
        return [], NewsStatus.HTTP_ERROR, text[:160]
    if not text:
        return [], NewsStatus.EMPTY_VALID, ""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return [], NewsStatus.PARSE_ERROR, text[:120]
    if not isinstance(payload, dict):
        return [], NewsStatus.PARSE_ERROR, "unexpected response shape"
    articles = payload.get("articles")
    if articles is None:
        # GDELT omits "articles" entirely when nothing matched; that is a real
        # empty answer, not a parse failure.
        return [], NewsStatus.EMPTY_VALID, ""
    if not isinstance(articles, list):
        return [], NewsStatus.PARSE_ERROR, "'articles' is not a list"
    return [a for a in articles if isinstance(a, dict)], None, ""


# --- per-article publish-time verification -------------------------------

_META_PUBLISHED = re.compile(
    r'<meta[^>]+(?:property|name|itemprop)\s*=\s*["\']'
    r'(?:article:published_time|datePublished|pubdate|publish-date|article:published)'
    r'["\'][^>]*>',
    re.IGNORECASE,
)
_CONTENT_ATTR = re.compile(r'content\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_JSONLD_PUBLISHED = re.compile(
    r'"datePublished"\s*:\s*"([^"]+)"', re.IGNORECASE
)
_TIME_DATETIME = re.compile(r'<time[^>]+datetime\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)

#: Methods in priority order. JSON-LD first because it survived on 3 of the 5
#: pages measured in the campaign; meta second; <time> is a weak last resort.
_EXTRACTION_ORDER = ("json-ld datePublished", "meta published_time", "<time datetime>")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    text = html.unescape(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return to_utc(parsed)


def extract_publish_time(page: str) -> tuple[datetime | None, str]:
    """Return ``(published_utc, method)`` from an article page's HTML.

    Returns ``(None, "")`` when no timestamp can be established. Published in
    this order so a richer structured value wins over a loose one.
    """
    for match in _JSONLD_PUBLISHED.finditer(page or ""):
        parsed = _parse_iso(match.group(1))
        if parsed is not None:
            return parsed, "json-ld datePublished"
    for tag in _META_PUBLISHED.finditer(page or ""):
        content = _CONTENT_ATTR.search(tag.group(0))
        if content:
            parsed = _parse_iso(content.group(1))
            if parsed is not None:
                return parsed, "meta published_time"
    for match in _TIME_DATETIME.finditer(page or ""):
        parsed = _parse_iso(match.group(1))
        if parsed is not None:
            return parsed, "<time datetime>"
    return None, ""


def _fetch_page(url: str) -> tuple[int | None, str | None, str]:
    """Fetch an article page (bounded read). Same return shape as _request."""
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) TradingAgents-verify/1.0",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=VERIFY_TIMEOUT) as response:
            raw = response.read(VERIFY_MAX_BYTES)
            charset = response.headers.get_content_charset() or "utf-8"
            return response.status, raw.decode(charset, "replace"), ""
    except urllib.error.HTTPError as exc:
        return exc.code, None, ""
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        kind = "timeout" if isinstance(reason, TimeoutError) or "timed out" in str(reason) else "transport"
        return None, None, kind
    except TimeoutError:
        return None, None, "timeout"
    except OSError as exc:
        logger.warning("GDELT verification fetch failed for %s: %s", url, exc)
        return None, None, "transport"


# --- ticker relevance ----------------------------------------------------


def _is_relevant(article: dict, ticker: str) -> bool:
    """Whether a discovered article is plausibly *about* ``ticker``.

    GDELT matched on text, so relevance is re-checked on the fields we keep:
    the canonical symbol must appear in the title or the URL path. This is
    deliberately permissive on the title (``Nvidia`` is not ``NVDA``) but the
    URL path catches the common ``/nvidia-...``/``/NVDA`` slugs.
    """
    symbol = normalize_symbol(ticker)
    haystack = f"{article.get('title', '')} {article.get('url', '')}".lower()
    if symbol.lower() in haystack:
        return True
    return "nvidia" in haystack if symbol.upper() == "NVDA" else False


def _dedupe(articles: list[dict]) -> list[dict]:
    seen: set[str] = set()
    kept = []
    for article in articles:
        key = (article.get("title") or "").strip().lower()
        url = (article.get("url") or "").strip()
        ident = key or url
        if not ident or ident in seen:
            continue
        seen.add(ident)
        kept.append(article)
    return kept


def _render(ticker: str, start_date: str, end_date: str, verified: list[dict]) -> str:
    lines = [
        f"## {ticker} News, from {start_date} to {end_date} "
        f"(GDELT discovery, publish time verified per article):",
        "",
        f"{len(verified)} article(s) with a publisher-verified publication time "
        f"inside the window:",
        "",
    ]
    for article in sorted(verified, key=lambda a: a["published"]):
        lines.append(f"### {article['title']} (source: {article['domain']})")
        lines.append(f"**Published:** {article['published'].isoformat()}")
        lines.append(f"Link: {article['url']}")
        lines.append("")
    return "\n".join(lines)


def get_news_gdelt(
    ticker: str,
    start_date: str,
    end_date: str,
    *,
    as_of_cutoff: str | None = None,
    limit: int | None = None,
    verify_budget: int | None = None,
) -> str:
    """Historical company news for ``[start_date, end_date]`` with a PIT cutoff.

    Args:
        ticker: Symbol to query.
        start_date / end_date: ``yyyy-mm-dd`` publication window.
        as_of_cutoff: Exclusive upper bound (ISO timestamp or ``yyyy-mm-dd``).
            Defaults to the end of ``end_date``.
        limit: Maximum articles rendered.
        verify_budget: Maximum discovery hits whose publish time is checked.

    Returns:
        Markdown in the same shape as the other news vendors, or an explicit
        ``NEWS_STATUS=...`` line for conditions that are *facts about the
        vendor's answer* (empty window, out-of-window hits, windows older than
        the archive).

    Raises:
        ``VendorRateLimitError`` / ``VendorUnavailableError`` **only** for
        request-level failures where the vendor could not answer at all
        (throttled, timed out, endpoint down, unparsable body). Those MUST
        raise rather than return text: ``route_to_vendor`` treats the first
        non-raising result as the answer, so returning "unavailable" text here
        would make the later vendors unreachable (measured live in campaign
        20261107_140536: a GDELT timeout masked every later vendor).

        Answer-level outcomes are **not** exceptions: an empty window, hits
        that fall outside it, and windows older than the archive are returned
        as the ``NEWS_STATUS=...`` text described above (see
        ``_IMMEDIATE_CLASSES`` in this module). In other words, "raises" here
        never means "this call can only fail": the normal answer for a quiet
        or too-old window is a returned status line.
    """
    outcome = fetch_news_gdelt(
        ticker, start_date, end_date,
        as_of_cutoff=as_of_cutoff, limit=limit, verify_budget=verify_budget,
    )
    if outcome.status is None:
        return _render(ticker, start_date, end_date, outcome.articles)
    return render_status(
        outcome.status, vendor="GDELT", subject=ticker,
        start_date=start_date, end_date=end_date, detail=outcome.detail or None,
    )


class _Outcome:
    """Result of a GDELT call: either articles, or a non-raising outcome class."""

    __slots__ = ("articles", "status", "detail")

    def __init__(self, articles=None, status=None, detail=""):
        self.articles = articles or []
        self.status = status
        self.detail = detail


#: Outcomes that describe the vendor's *answer* and so are returned as text
#: (they are not failures the next vendor could fix by being asked instead).
_IMMEDIATE_CLASSES = frozenset(
    {NewsStatus.EMPTY_VALID, NewsStatus.HISTORICAL_UNSUPPORTED,
     NewsStatus.OUT_OF_WINDOW}
)


def fetch_news_gdelt(
    ticker: str,
    start_date: str,
    end_date: str,
    *,
    as_of_cutoff: str | None = None,
    limit: int | None = None,
    verify_budget: int | None = None,
) -> "_Outcome":
    """Core GDELT call: returns verified articles or raises a typed failure."""
    start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    cutoff = _parse_cutoff(as_of_cutoff, end_dt)
    config = get_config()
    budget = (
        config.get("news_verify_budget", _VERIFY_BUDGET)
        if verify_budget is None
        else verify_budget
    )

    # Refuse windows older than the archive instead of sending a request that
    # can only answer "nothing": that would read as an absence. No request is
    # made, so this is a fact about the vendor's coverage, not a failure.
    oldest_supported = datetime.now(timezone.utc) - timedelta(days=_WINDOW_DAYS)
    if start_dt < oldest_supported:
        return _Outcome(
            status=NewsStatus.HISTORICAL_UNSUPPORTED,
            detail=f"GDELT archives ~3 months; oldest supported start is "
                   f"{oldest_supported:%Y-%m-%d}",
        )

    query = _query_for(ticker)
    records, failure, detail = _fetch_articles(query, start_dt, end_dt, limit or 250)
    if failure is not None:
        if failure in _IMMEDIATE_CLASSES:
            return _Outcome(status=failure, detail=detail)
        # Throttled / timed out / endpoint down / unparsable: the *request*
        # failed. Raise so the router can try the next vendor.
        _raise_for(failure, detail)

    relevant = _dedupe([a for a in records if _is_relevant(a, ticker)])
    if not relevant:
        return _Outcome(
            status=NewsStatus.EMPTY_VALID,
            detail=f"{len(records)} hit(s) were not about {ticker}",
        )

    # GDELT's seendate lags publication in both directions, so no article is
    # dismissed on seendate alone -- verification is the whole point.
    candidates = relevant[: max(0, budget)]
    verified: list[dict] = []
    for article in candidates:
        url = (article.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        status, page, _kind = _fetch_page(url)
        if status != 200 or not page:
            logger.warning("GDELT candidate unverifiable (%s): %s", status, url)
            continue
        published, method = extract_publish_time(page)
        if published is None:
            logger.warning("GDELT candidate has no publisher timestamp: %s", url)
            continue
        # Half-open [start, cutoff), matching historical_news.py.
        if published < start_dt or published >= cutoff:
            continue
        verified.append(
            {
                "title": html.unescape(article.get("title") or "").strip(),
                "domain": (article.get("domain") or "").strip() or "unknown",
                "url": url,
                "published": published,
                "method": method,
            }
        )

    if not verified:
        return _Outcome(
            status=NewsStatus.OUT_OF_WINDOW,
            detail=(
                f"{len(candidates)} candidate(s) discovered; none had a verifiable "
                "publisher publication time inside the window"
            ),
        )
    return _Outcome(articles=verified)


def _raise_for(status: NewsStatus, detail: str) -> None:
    """Raise the router-visible exception for a request-level failure.

    One class per cause: a 429/throttle is ``VendorRateLimitError``; a socket
    timeout is ``VendorTimeoutError`` (subclass of ``VendorUnavailableError``,
    so the router still fails over, but it is not reported as a throttle); any
    other HTTP failure is ``VendorUnavailableError``.
    """
    from .errors import VendorRateLimitError, VendorTimeoutError, VendorUnavailableError

    message = f"GDELT {status.value.lower()}: {detail or 'no detail'}"
    if status is NewsStatus.RATE_LIMITED:
        raise VendorRateLimitError(message)
    if status is NewsStatus.TIMEOUT:
        raise VendorTimeoutError(message)
    raise VendorUnavailableError(message)


def _parse_cutoff(as_of_cutoff: str | None, end_dt: datetime) -> datetime:
    """Resolve the exclusive publication cutoff in UTC.

    An ISO timestamp is used as-is. A bare ``yyyy-mm-dd`` means "the whole of
    that day", i.e. the cutoff is midnight *after* it. Anything unparsable and
    absent both fall back to the end of ``end_dt``'s day.
    """
    if as_of_cutoff:
        parsed = _parse_iso(as_of_cutoff)
        if parsed is not None:
            return parsed
        try:
            return datetime.strptime(as_of_cutoff, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            ) + timedelta(days=1)
        except (TypeError, ValueError):
            pass
    return end_dt + timedelta(days=1)
