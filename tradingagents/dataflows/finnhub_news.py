"""Point-in-time-safe company and market news via the Finnhub REST API.

Why this module exists
----------------------
Finnhub is the primary **company-specific** news source. It takes an explicit
``symbol`` and an explicit ``from``/``to`` date range, so unlike the retired
Yahoo ticker endpoint it can answer "what was published about NVDA between
2026-09-16 and 2026-09-23" without guessing. GDELT (``gdelt_news``) stays the
secondary, discovery-style source for global / industry / macro events; the two
are deliberately **not** concatenated blindly — see ``news_merge``.

Endpoint
--------
``GET https://finnhub.io/api/v1/company-news?symbol=<SYM>&from=<yyyy-mm-dd>
&to=<yyyy-mm-dd>&token=<KEY>``

Key handling
------------
The key is read from ``FINNHUB_API_KEY`` at call time and is never logged,
rendered into an exception message, or written to disk by this module. Outbound
URLs are redacted before they reach any log line or exception string.

Point-in-time
-------------
``datetime`` is a Unix epoch in **seconds** (UTC). Every article is filtered
against the half-open window ``[start_date 00:00Z, cutoff)`` where the cutoff
defaults to midnight after ``end_date`` — the same convention as
``gdelt_news`` and ``date_window.publication_cutoff``. An article is **never**
admitted just
because the vendor returned it: a missing, non-numeric or unparsable timestamp
is dropped, and anything at or after the cutoff is dropped. With no
publishable timestamp there is no way to prove the article is not future
information, so it is treated as future.

Relevance
---------
Finnhub's ``related`` field lists tickers the article mentions. A ``related``
hit does **not** establish that the article is substantively about the requested
company (an article "Nvidia, AMD and Intel earnings" is related to all three but
may be an AMD story), so ``related`` is preserved as metadata and is only a
*weak* signal: it is recorded, never used alone to claim relevance. See
``_is_about``.

Licensing: only headline, source, URL, publication timestamp and the
vendor-provided short summary are reproduced — the same fields a licensed news
feed may surface. No full article text is stored.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone

from .config import get_config
from .date_window import to_utc
from .news_relevance import is_about_company
from .news_status import NewsStatus, render_status
from .symbol_utils import normalize_symbol

logger = logging.getLogger(__name__)

_API = "https://finnhub.io/api/v1/company-news"

#: Bounded transport budget. Finnhub is usually fast; a slow answer means the
#: service is unhealthy and the analyst should not wait on it.
REQUEST_TIMEOUT = 20.0

#: Transient statuses worth exactly one retry. 401/403/404 are permanent by
#: definition, so retrying them only burns the request budget.
_MAX_ATTEMPTS = 2

#: Statuses never worth a retry.
_PERMANENT = frozenset({401, 403, 404})

#: Hard server-side row limit for one ``company-news`` call. There is no
#: pagination parameter, so a range returning this many records may be
#: truncated at its *oldest* end. A single dense day can still reach the limit —
#: the cap is *detected* and disclosed, not eliminated.
_MAX_RECORDS_PER_CALL = 250

#: Upper bound on sub-ranges sent for one request. Windows up to this many days
#: are fetched one day at a time; wider windows are split into equal sub-ranges
#: of ``ceil(days / _MAX_CHUNKS)`` days so the request count stays bounded.
_MAX_CHUNKS = 16

_TOKEN_PARAM = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(token|apikey|api_key|access_token|key|secret|password)"
    r"=[^&\s\"']+"
)

#: Analyst-facing wording per failure class, used when a provider raises so the
#: merged block can state the reason without inventing vendor detail.
_STATUS_REASON = {
    NewsStatus.AUTH_MISSING: "no credential is configured for this provider",
    NewsStatus.AUTH_INVALID: "the provider rejected the credential",
    NewsStatus.RATE_LIMITED: "the provider throttled the request",
    NewsStatus.TIMEOUT: "the request timed out",
    NewsStatus.PROVIDER_UNAVAILABLE: "the provider endpoint is not serving",
    NewsStatus.HTTP_ERROR: "the provider returned an error",
    NewsStatus.PARSE_ERROR: "the response could not be parsed as news",
    NewsStatus.EMPTY_VALID: "the provider answered and had no articles in this window",
}


def _redact(text: str) -> str:
    """Strip any ``token=...`` from a URL before it is logged or raised."""
    return _TOKEN_PARAM.sub(r"\1=<redacted>", text or "")


def get_api_key() -> str:
    """Return ``FINNHUB_API_KEY`` or raise a typed "not configured" error.

    The value is returned to the caller only; it is never placed in a log line,
    an exception message, or any rendered news text.
    """
    import os

    from .errors import VendorNotConfiguredError

    key = (os.getenv("FINNHUB_API_KEY") or "").strip()
    if not key:
        raise VendorNotConfiguredError(
            "Finnhub API key is not configured: set FINNHUB_API_KEY in the "
            "environment or .env file."
        )
    return key


def _request(url: str) -> tuple[int | None, str | None, str]:
    """GET ``url`` once. Returns ``(status, body, error_kind)``.

    ``error_kind`` is ``""`` when a body arrived, or ``"timeout"`` /
    ``"transport"``. HTTP error statuses come back through ``status`` with an
    empty body so the caller classifies them.
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
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
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
        logger.warning("Finnhub transport error: %s", _redact(str(exc)))
        return None, None, "transport"
    except Exception as exc:  # noqa: BLE001 - a transport bug must not abort the node
        # An unexpected error inside the HTTP stack is still a failed request:
        # classify it so the router can fail over instead of the exception
        # reaching the analyst as a crash.
        logger.warning("Finnhub client error: %s", _redact(f"{type(exc).__name__}: {exc}"))
        return None, None, "transport"


def _classify_http(status: int | None, error_kind: str) -> NewsStatus | None:
    """Map a raw probe result to a failure status, or None when a body arrived."""
    if error_kind == "timeout":
        return NewsStatus.TIMEOUT
    if error_kind:
        return NewsStatus.PROVIDER_UNAVAILABLE
    if status == 200:
        return None
    if status == 429:
        return NewsStatus.RATE_LIMITED
    if status in (401, 403):
        # Finnhub answers an unknown/invalid token with 401; a plan that does
        # not cover the endpoint answers 403. Both mean "this credential cannot
        # ask this question", never "no news".
        return NewsStatus.AUTH_INVALID
    if status in (404, 410, 502, 503, 504):
        return NewsStatus.PROVIDER_UNAVAILABLE
    return NewsStatus.HTTP_ERROR


def _parse_published(value) -> datetime | None:
    """Parse Finnhub's epoch-seconds ``datetime`` into an aware UTC instant.

    Returns ``None`` for anything that is not a plausible epoch integer. A
    fractional value is truncated; a value in milliseconds (``> 1e11``) is
    detected and converted, because some deployments have emitted ms.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text or not text.lstrip("-").isdigit():
            return None
        value = int(text)
    if not isinstance(value, (int, float)):
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    if seconds > 1e11:  # milliseconds since epoch
        seconds /= 1000.0
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _parse_cutoff(as_of_cutoff: str | None, end_dt: datetime) -> datetime:
    """Resolve the exclusive publication cutoff in UTC (see ``gdelt_news``)."""
    if as_of_cutoff:
        text = str(as_of_cutoff).strip()
        if text:
            iso = text.replace("Z", "+00:00")
            try:
                parsed = datetime.fromisoformat(iso)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return to_utc(parsed)
            except ValueError:
                try:
                    return datetime.strptime(text, "%Y-%m-%d").replace(
                        tzinfo=timezone.utc
                    ) + timedelta(days=1)
                except ValueError:
                    pass
    return end_dt + timedelta(days=1)


def _related_tickers(item: dict) -> list[str]:
    """Normalise the ``related`` field into a list of upper-case tickers.

    Finnhub emits it as a comma-separated string (``"NVDA,AMD"``); some proxies
    emit a list. Anything else becomes ``[]`` rather than crashing the call, and
    a malformed entry is dropped instead of being rendered.
    """
    raw = item.get("related")
    if isinstance(raw, str):
        parts = raw.split(",")
    elif isinstance(raw, (list, tuple)):
        parts = list(raw)
    else:
        return []
    out: list[str] = []
    for part in parts:
        if not isinstance(part, str):
            continue
        token = part.strip().upper()
        # A real ticker is short and alphanumeric with optional ./- suffixes.
        if token and len(token) <= 12 and re.fullmatch(r"[A-Z0-9.\-]+", token):
            out.append(token)
    return out


def _is_about(item: dict, ticker: str) -> bool:
    """Whether an article is substantively *about* ``ticker``.

    A ``related`` match alone is **not** sufficient: the field lists every
    company a piece mentions, so a sector round-up carries ``related="NVDA"``
    while being about the industry. Measured on the live feeds, such rows were
    common. Relevance is delegated to :mod:`news_relevance`, which both
    providers share, so "relevant" means the same thing everywhere. ``related``
    is still preserved on the record as metadata.
    """
    return is_about_company(
        item.get("headline") or "",
        item.get("summary") or "",
        item.get("url") or "",
        ticker,
    )


def _dedupe(items: list[dict]) -> list[dict]:
    """Drop duplicate articles by URL, falling back to the normalised headline."""
    seen: set[str] = set()
    kept: list[dict] = []
    for item in items:
        url = str(item.get("url") or "").strip().lower()
        headline = re.sub(r"\s+", " ", str(item.get("headline") or "")).strip().lower()
        ident = url or headline
        if not ident or ident in seen:
            continue
        seen.add(ident)
        kept.append(item)
    return kept


def _normalise(item: dict, ticker: str, published: datetime) -> dict:
    """Map one Finnhub record onto the project's canonical news shape."""
    headline = re.sub(r"\s+", " ", str(item.get("headline") or "")).strip()
    summary = re.sub(r"\s+", " ", str(item.get("summary") or "")).strip()
    source = str(item.get("source") or "").strip() or "unknown"
    return {
        "ticker": normalize_symbol(ticker),
        "headline": headline,
        "summary": summary,
        "source": source,
        "url": str(item.get("url") or "").strip(),
        "published_at": published,
        # Provenance is explicit so a merged report can always say which
        # provider an item came from and how it was obtained.
        "provider": "finnhub",
        "related": _related_tickers(item),
        "status": NewsStatus.SUCCESS_REAL_CONTENT,
    }


def _render(
    ticker: str,
    start_date: str,
    end_date: str,
    articles: list[dict],
    coverage_note: str = "",
) -> str:
    """Render Finnhub articles in the shape the News Analyst already parses."""
    lines = [
        f"## {ticker} News, from {start_date} to {end_date} "
        f"(Finnhub company news, publish time verified per article):",
        "",
        f"{len(articles)} article(s) published inside the window:",
        "",
    ]
    if coverage_note:
        # Truncation is a fact about coverage, so the analyst must see it in the
        # text it reads, not only in a server log.
        lines.append(f"**Coverage note:** {coverage_note}")
        lines.append("")
    for article in sorted(articles, key=lambda a: a["published_at"]):
        lines.append(f"### {article['headline']} (source: {article['source']})")
        lines.append(f"**Published:** {article['published_at'].isoformat()}")
        if article["summary"]:
            lines.append(article["summary"])
        if article["related"]:
            lines.append(f"Related tickers: {', '.join(article['related'])}")
        lines.append(f"Link: {article['url']}")
        lines.append("")
    return "\n".join(lines)


class _Outcome:
    """Result of a Finnhub call: articles, or a non-raising outcome class."""

    __slots__ = ("articles", "status", "detail")

    def __init__(self, articles=None, status=None, detail=""):
        self.articles = articles or []
        self.status = status
        self.detail = detail


def _day_chunks(start_dt: datetime, end_dt: datetime) -> list[tuple[str, str]]:
    """Split ``[start_dt, end_dt]`` into ``(from, to)`` date ranges.

    Finnhub's 250-record cap truncates the oldest end of a range, so ranges are
    narrowed to keep the cap from plausibly biting. Windows of up to
    ``_MAX_CHUNKS`` days become one chunk per day. Wider windows become equal
    multi-day chunks so the request count stays bounded. The final day is always
    present, because the point-in-time cutoff normally falls at the end.
    """
    days = (end_dt.date() - start_dt.date()).days + 1
    days = max(1, days)
    if days <= _MAX_CHUNKS:
        return [
            (
                f"{start_dt.date() + timedelta(days=offset):%Y-%m-%d}",
                f"{start_dt.date() + timedelta(days=offset):%Y-%m-%d}",
            )
            for offset in range(days)
        ]
    # Wide window: equal sub-ranges whose size just keeps the count in budget.
    span = max(1, -(-days // _MAX_CHUNKS))
    chunks: list[tuple[str, str]] = []
    offset = 0
    while offset < days:
        first = start_dt.date() + timedelta(days=offset)
        last = start_dt.date() + timedelta(days=min(offset + span - 1, days - 1))
        chunks.append((f"{first:%Y-%m-%d}", f"{last:%Y-%m-%d}"))
        offset += span
    return chunks


def _fetch_range(
    ticker: str, from_date: str, to_date: str, key: str
) -> tuple[list | None, NewsStatus | None, str]:
    """One ``company-news`` call for an inclusive date range.

    Returns ``(records, failure_status, detail)``: ``failure_status`` is set for
    request-level problems, ``records`` is ``None`` when the body could not be
    parsed, and otherwise the raw JSON list is returned unchanged.
    """
    # Finnhub's own range is inclusive of both days; the per-article cutoff
    # below enforces the exact half-open window.
    query = f"?symbol={normalize_symbol(ticker)}&from={from_date}&to={to_date}"
    # The token is appended after logging so it never reaches a log line.
    url = f"{_API}{query}"

    status: NewsStatus | None = None
    detail = ""
    body: str | None = None
    for attempt in range(_MAX_ATTEMPTS):
        full_url = f"{url}&token={key}"
        http_status, body, error_kind = _request(full_url)
        status = _classify_http(http_status, error_kind)
        if status is None:
            break
        detail = f"HTTP {http_status}" if http_status else error_kind
        retryable = status is NewsStatus.RATE_LIMITED or (
            status is NewsStatus.HTTP_ERROR and http_status == 500
        )
        if not retryable or attempt == _MAX_ATTEMPTS - 1:
            break
        logger.warning(
            "Finnhub %s for %s; retrying once.", detail, normalize_symbol(ticker)
        )
        time.sleep(min(2.0, 1.0))

    if status is not None:
        return None, status, detail

    text = (body or "").strip()
    if not text:
        return [], None, "empty response body"
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # A non-JSON body can echo the request (and therefore the token), so it
        # is redacted before it can reach the analyst (final audit F6).
        return None, None, _redact(text[:120])
    if isinstance(parsed, dict) and "error" in parsed:
        # Finnhub returns ``{"error": "..."}`` for some auth/plan failures with
        # HTTP 200. That is a request problem, never an empty news day.
        return None, NewsStatus.PROVIDER_UNAVAILABLE, _redact(
            f"Finnhub rejected the request: {str(parsed['error'])[:160]}"
        )
    if not isinstance(parsed, list):
        return None, None, "expected a JSON list"
    return parsed, None, ""


def fetch_news_finnhub(
    ticker: str,
    start_date: str,
    end_date: str,
    *,
    as_of_cutoff: str | None = None,
    limit: int | None = None,
) -> _Outcome:
    """Core Finnhub call: returns PIT-filtered articles or raises a typed failure.

    Request-level failures (auth, throttle, timeout, unparsable) raise so the
    router can try the next vendor. An authoritative empty answer returns an
    ``EMPTY_VALID`` outcome, which is a fact about the company, not an outage.
    """
    from .errors import VendorRateLimitError, VendorTimeoutError, VendorUnavailableError

    start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    cutoff = _parse_cutoff(as_of_cutoff, end_dt)
    if start_dt >= cutoff:
        return _Outcome(
            status=NewsStatus.OUT_OF_WINDOW,
            detail="the requested start is at or after the point-in-time cutoff",
        )

    key = get_api_key()
    config = get_config()
    article_limit = config.get("news_article_limit", 20) if limit is None else limit

    # Finnhub's company-news endpoint returns at most 250 records per call and
    # there is no pagination parameter. The cap truncates the *oldest* end of
    # the requested range, so a wide window over a dense ticker can come back
    # containing **nothing** inside the window that actually matters.
    #
    # Measured on 2026-11-15 (NVDA, ``from=2026-09-16&to=2026-09-24``): 247
    # records, ALL published 2026-09-23T16:45 or later, i.e. zero articles
    # before the 2026-09-23 cutoff even though NVDA publishes ~100-180 items a
    # day. Splitting the same range into short sub-ranges recovered 707
    # in-window articles. Reporting the wide-window answer as EMPTY_VALID would
    # have stated "no NVDA news" about a week that was densely covered.
    #
    # Each requested day is therefore fetched as its own one-day range. A dense
    # ticker can still exceed 250 in a single day, so the number of chunks is
    # bounded and any truncation is recorded in ``detail`` rather than hidden.
    chunks = _day_chunks(start_dt, end_dt)
    payload: list = []
    truncated_chunks = 0
    status: NewsStatus | None = None
    detail = ""
    for chunk_start, chunk_end in chunks:
        chunk_payload, chunk_status, chunk_detail = _fetch_range(
            ticker, chunk_start, chunk_end, key
        )
        if chunk_status is not None:
            # A request-level failure on any chunk means the window is not fully
            # covered: raise so the router can fail over, never report partial
            # coverage as an absence.
            message = (
                f"Finnhub {chunk_status.value.lower()}: "
                f"{chunk_detail or 'no detail'}"
            )
            if chunk_status is NewsStatus.RATE_LIMITED:
                raise VendorRateLimitError(message)
            if chunk_status is NewsStatus.TIMEOUT:
                raise VendorTimeoutError(message)
            raise VendorUnavailableError(message)
        if chunk_payload is None:
            # Per-chunk PARSE_ERROR already returned as a null payload; treat the
            # whole call as unparsable.
            return _Outcome(
                status=NewsStatus.PARSE_ERROR,
                detail=chunk_detail or "unparsable response body",
            )
        if len(chunk_payload) >= _MAX_RECORDS_PER_CALL:
            truncated_chunks += 1
        payload.extend(chunk_payload)

    if truncated_chunks:
        detail = (
            f"{truncated_chunks} day chunk(s) hit Finnhub's "
            f"{_MAX_RECORDS_PER_CALL}-record cap; oldest items in those days "
            f"may be missing"
        )
        logger.warning("Finnhub %s: %s", normalize_symbol(ticker), detail)

    if not payload:
        # Every sub-range answered with zero records. That is an authoritative
        # empty answer for the window, not a transport problem.
        return _Outcome(
            status=NewsStatus.EMPTY_VALID,
            detail=f"no records returned for {len(chunks)} day chunk(s)",
        )

    # --- point-in-time filter: this is the only thing that admits an article --
    admitted: list[dict] = []
    undated = 0
    future = 0
    for item in payload:
        if not isinstance(item, dict):
            continue
        published = _parse_published(item.get("datetime"))
        if published is None:
            undated += 1
            continue
        if published < start_dt or published >= cutoff:
            future += 1
            continue
        admitted.append(_normalise(item, ticker, published))

    admitted = _dedupe([a for a in admitted if _is_about(a, ticker)])
    if not admitted:
        if payload:
            # Every item was dropped, but *why* differs: an item outside the
            # window means the vendor cannot reach back; an item with no usable
            # timestamp or no relevance means the vendor answered but nothing
            # qualified. Saying "only serves recent news" in the latter case
            # would be a false statement about the vendor.
            if future and not undated:
                return _Outcome(
                    status=NewsStatus.OUT_OF_WINDOW,
                    detail=(
                        f"{len(payload)} item(s) returned, all {future} outside "
                        f"the publication window"
                    ),
                )
            return _Outcome(
                status=NewsStatus.EMPTY_VALID,
                detail=(
                    f"{len(payload)} item(s) returned inside the window, none "
                    f"substantively about {ticker} ({undated} undated)"
                ),
            )
        return _Outcome(status=NewsStatus.EMPTY_VALID)

    if article_limit:
        admitted = admitted[: int(article_limit)]
    return _Outcome(articles=admitted, detail=detail)


def get_news_finnhub(
    ticker: str,
    start_date: str,
    end_date: str,
    *,
    as_of_cutoff: str | None = None,
    limit: int | None = None,
) -> str:
    """Company news for ``[start_date, end_date]`` with a point-in-time cutoff.

    Returns markdown in the shape the News Analyst parses, or an explicit
    ``NEWS_STATUS=...`` line for answer-level outcomes. Request-level failures
    raise (see ``fetch_news_finnhub``) so ``route_to_vendor`` can fail over.
    """
    outcome = fetch_news_finnhub(
        ticker, start_date, end_date, as_of_cutoff=as_of_cutoff, limit=limit
    )
    if outcome.status is None:
        return _render(
            ticker, start_date, end_date, outcome.articles,
            coverage_note=outcome.detail,
        )
    return render_status(
        outcome.status, vendor="Finnhub", subject=ticker,
        start_date=start_date, end_date=end_date, detail=outcome.detail or None,
    )


# --- vendor entry points --------------------------------------------------
#
# Two entry points exist under the ``finnhub`` vendor key:
#
# * :func:`get_news_finnhub_only` -- the **production and experiment** path. It
#   asks Finnhub and nothing else. GDELT is never contacted, so a Finnhub outage
#   can never be masked by a second provider and no experiment arm can acquire
#   silent GDELT coverage.
# * :func:`get_news_combined` -- a legacy two-provider merge kept only so the
#   historical evidence scripts under ``token_benchmarks/`` still run. It is
#   **not** reachable through ``route_to_vendor`` and is not used by the
#   Pipeline.


def _safe_call(provider: str, func, ticker: str, start_date: str, end_date: str,
               /, **kwargs) -> "ProviderOutcome":
    """Call one provider and turn any failure into an explicit outcome.

    A provider raising is *not* allowed to hide the other provider: the
    exception is classified into the same closed status taxonomy and rendered,
    so the analyst sees "this provider could not answer", never silence.
    """
    from .errors import (
        VendorNotConfiguredError,
        VendorRateLimitError,
        VendorTimeoutError,
        VendorUnavailableError,
    )
    from .news_merge import ProviderOutcome

    try:
        text = func(ticker, start_date, end_date, **kwargs)
        if not (text or "").strip():
            # A provider that returns nothing at all has not answered; calling
            # that "no news" would turn a swallow into a false absence.
            status = NewsStatus.PARSE_ERROR
            detail = "the provider returned no text at all"
        else:
            return ProviderOutcome(provider, text)
    except VendorNotConfiguredError as exc:
        status, detail = NewsStatus.AUTH_MISSING, str(exc)
    except VendorTimeoutError as exc:
        status, detail = NewsStatus.TIMEOUT, str(exc)
    except VendorRateLimitError as exc:
        status, detail = NewsStatus.RATE_LIMITED, str(exc)
    except VendorUnavailableError as exc:
        status, detail = NewsStatus.PROVIDER_UNAVAILABLE, str(exc)
    except Exception as exc:  # noqa: BLE001 - a provider must never abort the node
        logger.warning("%s news provider failed: %s", provider, type(exc).__name__)
        status, detail = NewsStatus.HTTP_ERROR, f"{type(exc).__name__}: {exc}"

    # This text reaches the analyst and the saved report, so a credential in an
    # exception message must be masked exactly as it is for logs (audit H-1).
    detail = _redact(detail)

    # State the provider's own reason, in the taxonomy's wording, so the
    # analyst reads "this provider could not answer" rather than silence.
    rendered = (
        f"NEWS_STATUS={status.value}: {provider} could not answer for "
        f"{normalize_symbol(ticker)} ({start_date}..{end_date}) — "
        f"{_STATUS_REASON.get(status, 'the provider failed')}"
        f"{f' ({detail})' if detail else ''}. This says nothing about the "
        "instrument; report the news as unavailable rather than as neutral."
    )
    return ProviderOutcome(provider, rendered, status=status)


def get_news_finnhub_only(
    ticker: str,
    start_date: str,
    end_date: str,
    *,
    as_of_cutoff: str | None = None,
    limit: int | None = None,
) -> str:
    """Company news from **Finnhub only** — the production and experiment path.

    This is what ``route_to_vendor("get_news", ...)`` resolves to under the
    ``finnhub`` vendor key. GDELT is deliberately not contacted: the exported
    experiment scope is Finnhub-only company news, so no arm may acquire
    supplementary coverage from a second provider, and a Finnhub failure must be
    visible as a Finnhub failure rather than hidden behind a merge.

    Failures are rendered through the same closed status taxonomy, so a
    throttle, an unconfigured key or a retired endpoint can never read as "no
    news about the instrument".
    """
    from .news_merge import merge_news_sections

    finnhub = _safe_call(
        "Finnhub", get_news_finnhub, ticker, start_date, end_date,
        as_of_cutoff=as_of_cutoff, limit=limit,
    )
    return merge_news_sections(
        [finnhub],
        ticker=normalize_symbol(ticker),
        start_date=start_date,
        end_date=end_date,
    )


def get_global_news_finnhub(
    curr_date: str,
    look_back_days: int | None = None,
    limit: int | None = None,
    *,
    as_of_cutoff: str | None = None,
    ticker: str | None = None,
) -> str:
    """Global/macro news is **not provided by Finnhub** — return CONFIG_DISABLED.

    Finnhub's free tier serves symbol-scoped company news only; it has no
    global/macro endpoint. Presenting company news as "global news" would
    silently mislabel a company feed as macro context, so this path is disabled
    explicitly rather than approximated.

    The rendered line uses :attr:`NewsStatus.CONFIG_DISABLED`, which the status
    taxonomy defines as "the vendor is switched off in configuration". That
    keeps a deliberate absence distinguishable from an outage, a throttle and a
    genuine empty window (``EMPTY_VALID``).
    """
    from .date_window import publication_cutoff as _cutoff
    from .news_status import NewsStatus, render_status

    # Resolve the window end so the message names the same window the caller
    # asked about. ``publication_cutoff`` is only used for its date, never to
    # filter anything (nothing is fetched).
    end = _cutoff(as_of_cutoff) if as_of_cutoff else None
    end_date = end.date().isoformat() if end is not None else str(curr_date)
    start_date = str(curr_date)

    return render_status(
        NewsStatus.CONFIG_DISABLED,
        vendor="Finnhub",
        subject="global market news",
        start_date=start_date,
        end_date=end_date,
        detail=(
            "Finnhub serves company news only and has no global/macro endpoint; "
            "this path is disabled for the Finnhub-only scope"
        ),
    )


def get_news_combined(
    ticker: str,
    start_date: str,
    end_date: str,
    *,
    as_of_cutoff: str | None = None,
    limit: int | None = None,
) -> str:
    """**Legacy** company + global news from Finnhub **and** GDELT, merged honestly.

    NOT reachable through ``route_to_vendor`` and not used by the Pipeline: the
    production path is :func:`get_news_finnhub_only`. This function is retained
    only so the historical evidence scripts under ``token_benchmarks/`` (which
    measured the earlier two-provider design) keep running unchanged.
    """
    from .gdelt_news import get_news_gdelt
    from .news_merge import merge_news_sections

    shared = {"as_of_cutoff": as_of_cutoff}
    finnhub = _safe_call(
        "Finnhub", get_news_finnhub, ticker, start_date, end_date, **shared
    )
    gdelt = _safe_call(
        "GDELT", get_news_gdelt, ticker, start_date, end_date, **shared
    )
    return merge_news_sections(
        [finnhub, gdelt],
        ticker=normalize_symbol(ticker),
        start_date=start_date,
        end_date=end_date,
    )
