"""Point-in-time-safe historical news via Alpha Vantage NEWS_SENTIMENT.

Why this module exists
----------------------
Every news vendor configured before this one serves *recent* articles only:
``yfinance.Ticker.get_news`` takes no date argument, and ``get_global_news``
is a ranked live feed. Asking either for a window that ended weeks ago can
only produce a coverage notice, which is why no run in this project's history
ever put a real headline in front of the News Analyst.

Alpha Vantage's ``NEWS_SENTIMENT`` endpoint does take ``time_from``/``time_to``,
so it can genuinely answer "what was published about NVDA on 2026-09-23".
This module is the adapter that makes that usable:

* it normalises the vendor's JSON into the same markdown shape
  :func:`~tradingagents.dataflows.yfinance_news.get_news_yfinance` produces, so
  the analyst prompt does not change;
* it applies the point-in-time cutoff **explicitly** (``as_of_cutoff``), so an
  article published after the trading decision cannot enter the prompt;
* it distinguishes *no articles in the window* from *the vendor could not be
  asked*, so an outage never reads as "NVDA had no news".

Licensing: only the headline, publisher, publication timestamp, URL and the
vendor's own summary/sentiment fields are reproduced, which is what the
NEWS_SENTIMENT endpoint is licensed to return. Full article text is never
fetched or stored.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .alpha_vantage_common import (
    AlphaVantageNotConfiguredError,
    AlphaVantageRateLimitError,
)
from .alpha_vantage_news import get_news as _alpha_vantage_news
from .date_window import parse_publication_time
from .errors import VendorRateLimitError, VendorUnavailableError
from .news_status import NewsStatus, render_status

_HEADER = "## {ticker} News, from {start} to {end}:"


def _unavailable(ticker: str, start: str, end: str, status: NewsStatus, detail: str) -> str:
    """Render one non-success class with the shared news taxonomy.

    Alpha Vantage is a *keyed* vendor: a missing or rejected key is a permanent
    condition, and a connection failure is a fact about the vendor. Both are
    rendered explicitly rather than as a bare "unavailable", so the analyst (and
    ``classify_news_source_availability``) can tell them from an empty window.
    """
    return render_status(
        status, vendor="Alpha Vantage", subject=ticker,
        start_date=start, end_date=end, detail=detail,
    )


def _parse_cutoff(as_of_cutoff: str | None, end_date: str) -> datetime:
    """Resolve the exclusive publication cutoff in UTC."""
    if as_of_cutoff:
        parsed = parse_publication_time(as_of_cutoff)
        if parsed is not None:
            return parsed
    end = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return end.replace(hour=23, minute=59, second=59)


def _sentiment_label(score) -> str:
    """Map the vendor's -1..1 score onto the labels it documents."""
    try:
        value = float(score)
    except (TypeError, ValueError):
        return ""
    if value >= 0.35:
        return "vendor sentiment: positive"
    if value <= -0.15:
        return "vendor sentiment: negative"
    return "vendor sentiment: neutral"


def _format_article(article: dict) -> tuple[datetime, str] | None:
    """Render one vendor article as (published, markdown), or None if unplaceable.

    An article with no parsable ``time_published`` cannot be proven to fall
    inside the window, so it is dropped rather than guessed at — the same rule
    ``in_window`` applies to undated items (date_window.py).
    """
    published = parse_publication_time(article.get("time_published"))
    if published is None:
        return None
    title = (article.get("title") or "").strip()
    if not title:
        return None
    source = (article.get("source") or article.get("source_domain") or "unknown").strip()
    url = (article.get("url") or "").strip()
    summary = (article.get("summary") or "").strip()

    lines = [f"### {title} (source: {source})", f"**Published:** {published.isoformat()}"]
    if summary:
        lines.append(summary)
    if url:
        lines.append(f"Link: {url}")
    label = _sentiment_label(article.get("overall_sentiment_score"))
    if label:
        lines.append(f"_{label}_")
    return published, "\n".join(lines)


def _dedupe(articles: list[tuple[datetime, str]]) -> list[tuple[datetime, str]]:
    """Drop repeated headlines, keeping the earliest publication of each.

    The vendor returns one row per ticker mention, so a single Reuters story
    tagged for NVDA, AMD and SOXX appears several times.
    """
    seen: set[str] = set()
    kept: list[tuple[datetime, str]] = []
    for published, block in sorted(articles, key=lambda item: item[0]):
        key = block.split("\n", 1)[0].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        kept.append((published, block))
    return kept


def get_news_historical(
    ticker: str,
    start_date: str,
    end_date: str,
    *,
    as_of_cutoff: str | None = None,
    limit: int | None = None,
) -> str:
    """Historical company news for ``[start_date, end_date]`` with a PIT cutoff.

    Args:
        ticker: Symbol to query.
        start_date / end_date: ``yyyy-mm-dd`` publication window.
        as_of_cutoff: Exclusive upper bound on publication time, as an ISO
            timestamp or ``yyyy-mm-dd``. Defaults to the end of ``end_date``.
            Articles published at or after it are excluded, so a decision made
            before the close cannot see post-close news.
        limit: Maximum articles; ``None`` uses ``news_article_limit``.

    Returns:
        Markdown in the same shape as the live yfinance vendor, or an explicit
        coverage/absence notice. A missing/rejected key raises
        ``VendorUnavailableError`` and a transport failure raises
        ``VendorRateLimitError``, so the router can try the next vendor instead
        of accepting the first vendor's failure as the answer (campaign
        20261107_140536: returning failure *text* made every later vendor
        unreachable). An empty window returns ``NEWS_STATUS=EMPTY_VALID``.
    """
    cutoff = _parse_cutoff(as_of_cutoff, end_date)
    try:
        raw = _alpha_vantage_news(ticker, start_date, end_date)
    except AlphaVantageNotConfiguredError as exc:
        # Permanent: no key, or the vendor rejected it. Raising a typed error
        # (rather than returning text) is what lets the router fall through to
        # the next vendor -- a string would be returned as "the answer" and
        # GDELT would never be asked.
        raise VendorUnavailableError(
            f"no usable Alpha Vantage credential ({exc})"
        ) from exc
    except AlphaVantageRateLimitError as exc:
        raise VendorRateLimitError(f"Alpha Vantage throttled the request: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - vendor transports raise many types
        # Connection refused, reset, TLS failure, timeout... All mean "this
        # vendor cannot answer right now", which is exactly VendorRateLimitError's
        # contract (skip to the next vendor; do not blame the instrument).
        raise VendorRateLimitError(
            f"Alpha Vantage request failed: {type(exc).__name__}: {exc}"
        ) from exc

    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return _unavailable(ticker, start_date, end_date, NewsStatus.PARSE_ERROR,
                                "the vendor returned an unparsable response")
    if not isinstance(raw, dict):
        return _unavailable(ticker, start_date, end_date, NewsStatus.PARSE_ERROR,
                            "the vendor returned an unexpected response shape")

    feed = raw.get("feed")
    if not isinstance(feed, list):
        # The endpoint reports errors in free-text fields rather than HTTP codes.
        reason = raw.get("Note") or raw.get("Information") or raw.get("Error Message")
        return _unavailable(ticker, start_date, end_date, NewsStatus.AUTH_INVALID,
                            str(reason) if reason else "no article feed in the response")

    start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    placed: list[tuple[datetime, str]] = []
    for article in feed:
        if not isinstance(article, dict):
            continue
        rendered = _format_article(article)
        if rendered is None:
            continue
        published, block = rendered
        # Half-open [start, cutoff): the start day is included, anything at or
        # after the decision cutoff is not.
        if published < start_dt or published >= cutoff:
            continue
        placed.append((published, block))

    if not placed:
        # The vendor was asked and answered: this is a real, observed absence.
        return _unavailable(ticker, start_date, end_date, NewsStatus.EMPTY_VALID, "")

    kept = _dedupe(placed)
    if limit is not None:
        kept = kept[:limit]
    body = "\n\n".join(block for _published, block in kept)
    return (
        _HEADER.format(ticker=ticker, start=start_date, end=end_date)
        + f"\n\n{len(kept)} article(s), point-in-time filtered to publications before "
        + f"{cutoff.strftime('%Y-%m-%dT%H:%M')}Z:\n\n"
        + body
    )
