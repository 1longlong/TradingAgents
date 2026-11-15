"""Point-in-time-safe company, industry and macro news via the GDELT DOC 2.0 API.

Why this module exists
----------------------
GDELT DOC 2.0 is keyless and **does** take an explicit
``STARTDATETIME``/``ENDDATETIME``, so it complements Finnhub's symbol-specific
``company-news`` endpoint with the discovery and macro coverage Finnhub does not
provide. The two are complements, not interchangeable feeds: see
:mod:`news_merge` for how their results are combined.

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
from .news_relevance import company_name, is_about_company
from .news_status import NewsStatus, render_status
from .symbol_utils import normalize_symbol

logger = logging.getLogger(__name__)

_API = "https://api.gdeltproject.org/api/v2/doc/doc"

#: Query parameters that carry a credential. GDELT itself needs no key, but the
#: publisher URLs it returns are arbitrary, and a transport exception can echo
#: the full request URL — neither may reach a log line verbatim.
_SECRET_PARAM = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(token|apikey|api_key|access_token|key|secret|password)"
    r"=[^&\s\"']+"
)


def _redact(text: str) -> str:
    """Mask any credential-looking query parameter before logging."""
    return _SECRET_PARAM.sub(r"\1=<redacted>", text or "")

# One request every 5 s is GDELT's documented limit, but measured behaviour is
# stricter (see ``_MIN_INTERVAL_SECONDS`` below). Kept as a module attribute so
# tests can drive the throttle deterministically instead of sleeping.
#
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

# Transient statuses worth exactly one retry. 429 is retried once after a
# backoff well past the vendor's documented 5 s interval; nothing permanent is
# retried. Measured 2026-11-15: GDELT returns no ``Retry-After`` header, and a
# 5.5 s retry still 429s, so the backoff must be longer than the docs imply.
_MAX_ATTEMPTS = 2

#: Wait before the single retry of a 429. The vendor sends no server hint, so
#: this is a measured value: see ``_MIN_INTERVAL_SECONDS``.
_RATE_LIMIT_BACKOFF_SECONDS = 60.0

#: Hard ceiling on DOC-API requests issued by one news call.
_MAX_REQUESTS_PER_CALL = 12

#: Minimum spacing between *any* two GDELT DOC-API requests from this process.
#:
#: The documented fair-use interval is one request every 5 s, but measured
#: behaviour on 2026-11-15 was far stricter and is what governs this constant:
#:
#:   spacing  requests  accepted   note
#:   -------  --------  ---------  --------------------------------------------
#:   5.5 s    9         1 of 9     the shipped pacing before this round
#:   10 s     13        1 of 13    bursts of one macro query per class
#:   20 s     9         4 of 9     mixed with retries; not reproducible
#:   30 s     1         0 of 1
#:   45 s     1         0 of 1
#:   60 s     1         1 of 1     accepted on a *partially idle* host
#:   90 s     1         1 of 1     accepted on a *partially idle* host
#:
#: A later probe measured the TRUE start-to-start delta while the host was
#: still loaded by earlier requests, which is the condition a burst actually
#: sees:
#:
#:   spacing  accepted
#:   -------  --------
#:   80 s     0 of 1
#:   95 s     0 of 1
#:   110 s    1 of 1
#:
#: So 60 s is enough only after the host has been idle long enough, and too low
#: for a host that is still recovering. The threshold is host-state dependent
#: and unobservable (no ``Retry-After`` header), so 60 s is kept as a
#: reasonable-cost value rather than a guaranteed-safe one. A burst of the five
#: default macro queries consequently costs about four minutes of wall clock.
#: Known limitation, tracked in ``REMAINING_ISSUES.md`` R-1; GDELT is excluded
#: from the frozen 16-run experiment.
_MIN_INTERVAL_SECONDS = 60.0

_last_request_at: float = 0.0


def _throttle() -> None:
    """Sleep so consecutive GDELT calls are at least the vendor interval apart."""
    global _last_request_at
    now = time.monotonic()
    wait = _MIN_INTERVAL_SECONDS - (now - _last_request_at)
    if _last_request_at and wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


def _request_budget() -> int:
    """Maximum DOC-API requests one news call may issue.

    The global path sends one request per configured macro query. With five
    default queries a single analyst call is five requests; the budget bounds
    it so a misconfigured (or very long) query list cannot turn one analyst
    turn into an unbounded burst against a throttled third party.
    """
    try:
        value = int(get_config().get("news_max_requests_per_call", _MAX_REQUESTS_PER_CALL))
    except (TypeError, ValueError):
        value = _MAX_REQUESTS_PER_CALL
    return max(1, value)


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


#: Shortest quoted phrase GDELT accepts. Measured live: ``"AAPL"`` and
#: ``"NVDA"`` answer HTTP 200 with the plain-text body ``The specified phrase is
#: too short.``, so a 4-character symbol must not be quoted either.
_MIN_QUOTED_PHRASE = 4


def _query_for(ticker: str) -> str:
    """Build the full-text query for a ticker.

    GDELT has no symbol field: relevance is a text match. Two live constraints
    measured 2026-11-15 decide the shape of this query:

    * a **quoted phrase of 2-3 characters is rejected** — ``"AAPL"
      sourcelang:english`` answers HTTP 200 with the plain-text body ``The
      specified phrase is too short.``, and the short term poisons the whole
      query even when OR'd with a valid one. So short tickers are never quoted;
      the company name (``"Apple"``, ``"JPMorgan"``) carries the phrase instead.
    * unquoted tickers match plenty of unrelated text, so the canonical symbol
      is quoted **when long enough** to be a legal phrase.

    Callers are responsible for the extra relevance filter in
    :func:`_is_relevant`; this only decides what to *ask*.
    """
    symbol = normalize_symbol(ticker)
    name = company_name(ticker)
    if len(symbol) <= _MIN_QUOTED_PHRASE:
        # Quote the company name, never the symbol: a 2-4 char phrase is a hard
        # GDELT error, and the name is what these articles actually say.
        terms = [f'"{name}"'] if name and name.upper() != symbol else []
        if not terms:
            # No known name to lean on: fall back to the bare symbol, which
            # GDELT accepts unquoted. Relevance filtering keeps the noise out.
            terms = [symbol]
        return " OR ".join(terms) + " sourcelang:english"
    return f'"{symbol}" sourcelang:english'


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
        logger.warning("GDELT transport error: %s", _redact(str(exc)))
        return None, None, "transport"
    except Exception as exc:  # noqa: BLE001 - a transport bug must not abort the node
        logger.warning("GDELT client error: %s: %s", type(exc).__name__, _redact(str(exc)))
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
        if status is not NewsStatus.RATE_LIMITED or attempt == _MAX_ATTEMPTS - 1:
            return [], status, detail
        # Measured 2026-11-15: GDELT sends **no** ``Retry-After`` and no other
        # rate-limit header, so there is no server hint to honour. The
        # documented "one request every 5 seconds" is not sufficient in
        # practice: a burst at 5.5 s spacing was rejected 8 times out of 9,
        # while isolated requests 20 s apart were accepted 3 times out of 3.
        # The retry therefore backs off well past the documented interval
        # instead of repeating the same 5.5 s sleep that had just failed.
        backoff = _RATE_LIMIT_BACKOFF_SECONDS * (2 ** attempt)
        logger.warning(
            "GDELT throttled; backing off %.0fs before one retry.", backoff
        )
        time.sleep(backoff)

    if status is not None:
        return [], status, detail

    text = (body or "").strip()
    # A rate-limit page can arrive with 200 in some edges; detect its body too.
    if text.startswith("Please limit requests"):
        return [], NewsStatus.RATE_LIMITED, "rate-limit body"
    # GDELT reports query errors as plain text (with a 200 or 400 status), e.g.
    # "Invalid query end date." or "The specified phrase is too short.". That is
    # our request being rejected, not a malformed vendor response, so it must not
    # be labelled PARSE_ERROR and it must not be retried against the next vendor
    # as if it were transient.
    if text.lower().startswith(("invalid query", "error:")) or _is_query_rejection(text):
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


def _is_query_rejection(text: str) -> bool:
    """Whether a plain-text GDELT body is a complaint about *our* query.

    GDELT answers a syntactically rejected query with ``HTTP 200`` and English
    prose instead of JSON. Measured bodies: ``The specified phrase is too
    short.`` and ``Invalid query end date.``. Classifying these as
    ``PARSE_ERROR`` made a client-side bug look like a vendor outage (live run,
    2026-11-15), so they are recognised explicitly.
    """
    lowered = (text or "").lower()
    return (
        "phrase is too short" in lowered
        or "invalid query" in lowered
        # Measured live 2026-11-15: a non-OR parenthesised group is rejected with
        # "Parentheses may only be used around OR'd statements."
        or "parentheses may only be used" in lowered
        or "unsupported query" in lowered
    )


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
        logger.warning("GDELT verification fetch failed for %s: %s",
                       _redact(url), _redact(str(exc)))
        return None, None, "transport"
    except Exception as exc:  # noqa: BLE001 - a transport bug must not abort the node
        logger.warning("GDELT article fetch failed for %s: %s",
                       _redact(url), _redact(f"{type(exc).__name__}: {exc}"))
        return None, None, "transport"


# --- ticker relevance ----------------------------------------------------


def _is_relevant(article: dict, ticker: str) -> bool:
    """Whether a discovered article is substantively *about* ``ticker``.

    GDELT matches on free text, so relevance is re-checked on the fields kept.
    The rule lives in :mod:`news_relevance` so Finnhub and GDELT agree: symbol in
    the title/slug, a company alias (``Nvidia``, ``Exxon Mobil``), or a
    name-plus-subject body match. A sector-only piece that merely names the
    industry is excluded.
    """
    return is_about_company(
        article.get("title") or "",
        article.get("summary") or "",
        article.get("url") or "",
        ticker,
    )


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
    fetch_failed = undated = out_of_window = 0
    for article in candidates:
        url = (article.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            fetch_failed += 1
            continue
        status, page, _kind = _fetch_page(url)
        if status != 200 or not page:
            logger.warning("GDELT candidate unverifiable (%s): %s", status, _redact(url))
            fetch_failed += 1
            continue
        published, method = extract_publish_time(page)
        if published is None:
            logger.warning("GDELT candidate has no publisher timestamp: %s", _redact(url))
            undated += 1
            continue
        # Half-open [start, cutoff), matching the company-news adapters.
        if published < start_dt or published >= cutoff:
            out_of_window += 1
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
        total = len(candidates)
        counts = (f"{total} candidate(s): {fetch_failed} unreadable, "
                  f"{undated} undated, {out_of_window} outside the window")
        if total and out_of_window == 0 and undated == 0 and fetch_failed == total:
            # Every publisher page was unreadable. That is an outage on the
            # verification path, not a fact about GDELT's coverage -- reporting
            # it as OUT_OF_WINDOW would tell the analyst "this vendor only
            # serves recent items", which is false (audit H-2).
            _raise_for(
                NewsStatus.PROVIDER_UNAVAILABLE,
                f"GDELT could not be queried: every candidate page was "
                f"unreadable ({counts})",
            )
        if out_of_window:
            # We proved publication times and they fell outside the window.
            return _Outcome(
                status=NewsStatus.OUT_OF_WINDOW,
                detail=f"none of the discovered articles was published inside the "
                       f"window ({counts})",
            )
        # Nothing was verified and nothing was proved out of window: the pages
        # were readable but carried no usable date.
        return _Outcome(
            status=NewsStatus.PARSE_ERROR,
            detail=f"no publisher publication time could be read ({counts})",
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


# --- global / macro news -------------------------------------------------
#
# GDELT is the project's global-news provider: it is keyless, takes an explicit
# date range, and every article's publisher timestamp is re-verified. The
# queries come from ``global_news_queries`` in the active config, so coverage can
# be broadened without a code change.


def _global_query(query: str, ticker: str | None) -> str:
    """Build one GDELT query from a macro phrase, optionally scoped to a ticker.

    A bare ticker inside a macro query would drag in unrelated symbol matches and
    also make GDELT treat the phrase terms as optional, so the ticker is supplied
    as a quoted company-name term that must co-occur, not as a loose alternative.
    The macro phrase itself stays the primary subject, and the per-article
    relevance check is *not* applied to global news: these articles are about the
    topic, and requiring the company name would discard every valid macro item.

    GDELT's boolean grammar allows parentheses **only around OR'd statements**;
    wrapping a plain AND list in ``(...)`` is rejected with "Parentheses may only
    be used around OR'd statements." (measured live, 2026-11-15). A configured
    phrase is therefore emitted as bare space-separated terms, which GDELT reads
    as an AND, and any explicit ``OR`` the operator wrote is parenthesised.
    """
    text = (query or "").strip()
    if not text:
        return ""
    expression = _gdelt_phrase(text)
    if not expression:
        return ""
    if ticker:
        name = company_name(ticker)
        return f'{expression} "{name}" sourcelang:english'
    return f"{expression} sourcelang:english"


def _gdelt_phrase(query: str) -> str:
    """Render a configured phrase in GDELT boolean syntax.

    ``"a OR b c"`` becomes ``(a OR b) c``. Without an ``OR`` the phrase is
    returned as bare terms; adding parentheses there is a syntax error.

    GDELT rejects keywords containing characters it treats as operators. The
    measured case is a bare ``&``: the default macro query ``S&P 500`` was
    answered with "One or more of your keywords contained an illegal character"
    (2026-11-15 audit), so a token carrying ``&`` (or any of ``| ! ( ) , ; :``)
    is quoted, which is GDELT's documented remedy for punctuation.
    """
    words = [w for w in query.split() if w]
    if not words:
        return ""
    words = [_quote_illegal(w) for w in words]
    if any(w.upper() == "OR" for w in words):
        # Parenthesise the whole OR group so the remaining terms are ANDed to it.
        return "(" + " ".join(words) + ")"
    # Quote multi-word proper-noun-ish runs as phrases so GDELT requires them
    # adjacent; individual words stay loose terms.
    return " ".join(words)


#: Characters GDELT's query parser reads as operators rather than text.
_ILLEGAL_QUERY_CHARS = re.compile(r"[&|!(),;:]")


def _quote_illegal(word: str) -> str:
    """Quote ``word`` when it carries a character GDELT treats as an operator."""
    if word.startswith('"') or not _ILLEGAL_QUERY_CHARS.search(word):
        return word
    return '"' + word.replace('"', "") + '"'


def get_global_news_gdelt(
    curr_date: str,
    look_back_days: int | None = None,
    limit: int | None = None,
    *,
    as_of_cutoff: str | None = None,
    ticker: str | None = None,
) -> str:
    """Global / macro news for the ``look_back_days`` window ending ``curr_date``.

    Args:
        curr_date: ``yyyy-mm-dd`` analysis date (the window end).
        look_back_days: Days to look back; ``None`` uses the configured default.
        limit: Maximum articles; ``None`` uses the configured default.
        as_of_cutoff: Exclusive publication cutoff, defaulting to the end of
            ``curr_date``. Post-cutoff articles are dropped, never rendered.
        ticker: Optional symbol to corroborate each macro query.

    Returns:
        Markdown in the same shape as the company-news vendors, or an explicit
        ``NEWS_STATUS=...`` line. Request-level failures raise so the router can
        fail over (see :func:`get_news_gdelt`).
    """
    from .errors import VendorUnavailableError

    config = get_config()
    if look_back_days is None:
        look_back_days = config.get("global_news_lookback_days", 7)
    if limit is None:
        limit = config.get("global_news_article_limit", 10)
    queries = list(config.get("global_news_queries", []))
    # Bound the requests: one per configured query, never more than the budget.
    request_budget = _request_budget()
    if len(queries) > request_budget:
        logger.warning(
            "GDELT global news: %d configured queries exceed the per-call request "
            "budget of %d; only the first %d are queried.",
            len(queries), request_budget, request_budget,
        )
        queries = queries[:request_budget]

    end_dt = datetime.strptime(curr_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    start_dt = end_dt - timedelta(days=int(look_back_days))
    start_date = f"{start_dt:%Y-%m-%d}"
    cutoff = _parse_cutoff(as_of_cutoff, end_dt)

    oldest_supported = datetime.now(timezone.utc) - timedelta(days=_WINDOW_DAYS)
    if start_dt < oldest_supported:
        return render_status(
            NewsStatus.HISTORICAL_UNSUPPORTED, vendor="GDELT", subject="global news",
            start_date=start_date, end_date=curr_date,
            detail=f"GDELT archives ~3 months; oldest supported start is "
                   f"{oldest_supported:%Y-%m-%d}",
        )

    seen: set[str] = set()
    verified: list[dict] = []
    failures: list[NewsStatus] = []
    # Verification re-fetches each publisher page, which is the expensive part of
    # this call. The company path bounds that work with ``verify_budget``; this
    # path previously did not, so N macro queries x ``limit`` hits meant up to
    # N*limit page fetches per call with no ceiling (audit finding, 2026-11-15).
    # The same budget now applies, shared across all queries.
    budget = int(config.get("news_verify_budget", _VERIFY_BUDGET))
    fetch_failed = undated = out_of_window = 0
    attempts = 0
    for query in queries:
        built = _global_query(query, ticker)
        if not built:
            continue
        records, failure, detail = _fetch_articles(built, start_dt, end_dt, limit)
        if failure is not None:
            if failure in _IMMEDIATE_CLASSES:
                # An empty answer for one query is not fatal; keep the others.
                failures.append(failure)
                continue
            # A request-level failure means GDELT cannot answer at all right
            # now: surface it rather than silently reporting fewer articles.
            _raise_for(failure, detail)
        for article in records:
            title = html.unescape(article.get("title") or "").strip()
            url = (article.get("url") or "").strip()
            key = (title.lower() or url)
            if not key or key in seen:
                continue
            if not url.startswith(("http://", "https://")):
                continue
            # Record the hit *before* consulting the budget: a discovered but
            # unverified candidate is evidence of coverage we did not confirm,
            # not evidence that nothing matched. Moving this after the budget
            # check made an exhausted budget report EMPTY_VALID ("no macro news
            # was published"), which is a false claim about the world.
            seen.add(key)
            if attempts >= budget:
                continue
            attempts += 1
            status, page, _kind = _fetch_page(url)
            if status != 200 or not page:
                fetch_failed += 1
                continue
            published, method = extract_publish_time(page)
            if published is None:
                undated += 1
                continue
            # Half-open [start, cutoff): the same rule as company news.
            if published < start_dt or published >= cutoff:
                out_of_window += 1
                continue
            verified.append({
                "title": title,
                "domain": (article.get("domain") or "").strip() or "unknown",
                "url": url,
                "published": published,
                "method": method,
            })
            if len(verified) >= int(limit):
                break
        if len(verified) >= int(limit):
            break

    if not verified:
        # Distinguish "every query answered that nothing matched" from a mix of
        # causes. Reporting EMPTY_VALID requires that *no* query implied a
        # coverage gap (final audit F3: one EMPTY_VALID + one OUT_OF_WINDOW was
        # being reported as a real absence).
        coverage_note = (
            f"{attempts} candidate page(s) checked against a budget of {budget}"
            if attempts else ""
        )
        stats = (
            f"{len(seen)} hit(s) discovered; {len(verified)} verified inside the "
            f"window ({fetch_failed} page(s) unreachable, {undated} undated, "
            f"{out_of_window} outside the window"
            + (f"; {coverage_note}" if coverage_note else "")
            + ")"
        )
        if failures and all(f is NewsStatus.EMPTY_VALID for f in failures) and not seen:
            # Every query answered "nothing in this window": a real absence.
            # ``seen`` having entries means another query did return hits that
            # could not be verified, which is a coverage gap, not an absence.
            return render_status(
                NewsStatus.EMPTY_VALID, vendor="GDELT", subject="global news",
                start_date=start_date, end_date=curr_date,
            )
        if failures:
            for failure in failures:
                if failure is not NewsStatus.EMPTY_VALID:
                    return render_status(
                        failure, vendor="GDELT", subject="global news",
                        start_date=start_date, end_date=curr_date,
                    )
        if not seen:
            # No query returned a single hit at all: GDELT answered, and the
            # answer was "nothing matched". That is an absence, not an outage —
            # claiming "could not verify" here would disguise a real empty
            # result as a vendor failure.
            return render_status(
                NewsStatus.EMPTY_VALID, vendor="GDELT", subject="global news",
                start_date=start_date, end_date=curr_date,
            )
        # Hits existed but none carried a publisher timestamp inside the window:
        # the queries answered, the articles were merely older, undated, or the
        # verification budget ran out before one could be confirmed. Say which,
        # rather than attributing every case to the articles' age.
        return render_status(
            NewsStatus.OUT_OF_WINDOW, vendor="GDELT", subject="global news",
            start_date=start_date, end_date=curr_date,
            detail=(
                f"{len(seen)} hit(s) discovered; {len(verified)} verified inside the "
                f"window ({stats})"
            ),
        )

    lines = [
        f"## Global Market News, from {start_date} to {curr_date} "
        f"(GDELT discovery, publish time verified per article):",
        "",
        f"{len(verified)} article(s) with a publisher-verified publication time "
        f"before {cutoff.strftime('%Y-%m-%dT%H:%M')}Z:",
        "",
    ]
    for article in sorted(verified, key=lambda a: a["published"]):
        lines.append(f"### {article['title']} (source: {article['domain']})")
        lines.append(f"**Published:** {article['published'].isoformat()}")
        lines.append(f"Link: {article['url']}")
        lines.append("")
    return "\n".join(lines)
