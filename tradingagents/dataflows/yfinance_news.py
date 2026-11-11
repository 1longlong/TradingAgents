"""yfinance-based news data fetching functions."""

import contextlib
from datetime import datetime, timezone

import curl_cffi.requests.exceptions as curl_errors
import requests
import yfinance as yf
from dateutil.relativedelta import relativedelta
from yfinance.exceptions import YFDataException, YFRateLimitError

from .config import get_config
from .date_window import coverage_gap, in_window
from .errors import NoMarketDataError, VendorRateLimitError, VendorUnavailableError
from .stockstats_utils import yf_retry
from .symbol_utils import normalize_symbol

# HTTP statuses that mean "this vendor cannot serve this call right now", as
# opposed to "this vendor has no data for this symbol". 408/429/5xx are classic
# transience; 401/403 mean the vendor refused *this* request (expired cookie,
# blocked client), which is a fact about the request, not about the instrument.
# Deliberately NOT ``VendorNotConfiguredError``: news is a core category with a
# single configured vendor, and the router re-raises that type when nothing
# serves the call (``interface.py``), which would abort the whole run.
_TRANSIENT_HTTP_STATUS = frozenset({401, 403, 408, 429}) | frozenset(range(500, 600))

# Statuses that mean the *endpoint* is gone, not that the symbol is unlisted.
# Yahoo retired ``xhr/ncp`` (yfinance's ticker-news path) and answers HTTP 404;
# treating that as ``NoMarketDataError`` would tell the analyst "NVDA has no
# news", and treating it as rate-limiting would say "try again later" about an
# API that is never coming back (campaign 20261107_140536, probes/PROBE_LOG.md).
_RETIRED_ENDPOINT_STATUS = frozenset({404, 410})


def _is_retired_endpoint_error(exc: Exception) -> bool:
    """Whether ``exc`` is the retired-endpoint signature rather than a bad symbol.

    yfinance raises a bare ``YFDataException`` (``*** YAHOO! FINANCE IS
    CURRENTLY DOWN! ***``) when ``get_news`` gets a non-JSON body. That message
    is emitted for a dead endpoint, so it is classified as permanent. A plain
    HTTP 404 from another path stays "no data for the symbol" (the existing
    behaviour, asserted by ``test_missing_symbol_still_reports_absence``).
    """
    message = str(exc)
    if isinstance(exc, YFDataException) and "CURRENTLY DOWN" in message.upper():
        return True
    request = getattr(exc, "request", None)
    url = getattr(request, "url", None) if request is not None else None
    return isinstance(url, str) and "xhr/ncp" in url


# yfinance 1.x fetches through ``curl_cffi``, whose exception classes are NOT
# subclasses of ``requests``'. Both stacks are listed so a transport failure is
# recognised whichever client actually raised it.
_TRANSPORT_ERRORS = (
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    curl_errors.Timeout,
    curl_errors.ConnectionError,
)


def _status_of(exc: Exception) -> int | None:
    """Extract an HTTP status from either transport's HTTPError."""
    if isinstance(exc, (requests.exceptions.HTTPError, curl_errors.HTTPError)):
        return getattr(getattr(exc, "response", None), "status_code", None)
    return None


def _classify_news_failure(exc: Exception, symbol: str, canonical: str, detail: str):
    """Map a raw vendor exception onto the router's existing error taxonomy.

    The router reacts by exception *type* (see ``errors.py``), so the type is
    what decides whether the analyst is told "the vendor is down" (a fact about
    the vendor) or "no data for this symbol" (a fact about the instrument).
    Anything unrecognised keeps the historical ``NoMarketDataError`` behaviour.
    """
    if _is_retired_endpoint_error(exc):
        # Permanent: a retired endpoint. Say so, and never "try again later".
        return VendorUnavailableError(f"{detail}: Yahoo ticker-news endpoint is retired ({exc})")
    if isinstance(exc, (YFRateLimitError, YFDataException) + _TRANSPORT_ERRORS):
        # ``YFDataException`` is yfinance's own "the request failed" signal
        # (e.g. the literal ``*** YAHOO! FINANCE IS CURRENTLY DOWN! ***``).
        # Its "missing data" subclasses (``YFPricesMissingError`` and friends)
        # derive from ``YFException`` instead, so they are *not* caught here.
        return VendorRateLimitError(f"{detail}: {exc}")
    status = _status_of(exc)
    if status in _TRANSIENT_HTTP_STATUS:
        return VendorRateLimitError(f"{detail}: HTTP {status} ({exc})")
    return NoMarketDataError(symbol, canonical, f"{detail}: {exc}")


def _extract_article_data(article: dict) -> dict:
    """Extract article data from yfinance news format (handles nested 'content' structure)."""
    # Handle nested content structure
    if "content" in article:
        content = article["content"]
        title = content.get("title", "No title")
        summary = content.get("summary", "")
        provider = content.get("provider", {})
        publisher = provider.get("displayName", "Unknown")

        # Get URL from canonicalUrl or clickThroughUrl
        url_obj = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
        link = url_obj.get("url", "")

        # Get publish date
        pub_date_str = content.get("pubDate", "")
        pub_date = None
        if pub_date_str:
            with contextlib.suppress(ValueError, AttributeError):
                pub_date = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))

        return {
            "title": title,
            "summary": summary,
            "publisher": publisher,
            "link": link,
            "pub_date": pub_date,
        }
    else:
        # Fallback for flat structure. Parse the epoch publish time so flat
        # articles are date-filterable too (otherwise they bypass the
        # historical window and leak future news, #992/#1007).
        pub_date = None
        ts = article.get("providerPublishTime")
        if ts:
            # Epoch seconds are UTC; parse them as UTC-aware so filtering does
            # not shift with the host timezone (#1126).
            with contextlib.suppress(ValueError, OSError, TypeError):
                pub_date = datetime.fromtimestamp(ts, tz=timezone.utc)
        return {
            "title": article.get("title", "No title"),
            "summary": article.get("summary", ""),
            "publisher": article.get("publisher", "Unknown"),
            "link": article.get("link", ""),
            "pub_date": pub_date,
        }


def get_news_yfinance(
    ticker: str,
    start_date: str,
    end_date: str,
) -> str:
    """
    Retrieve news for a specific stock ticker using yfinance.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL")
        start_date: Start date in yyyy-mm-dd format
        end_date: End date in yyyy-mm-dd format

    Returns:
        Formatted string containing news articles
    """
    article_limit = get_config()["news_article_limit"]
    # Query Yahoo with the canonical symbol, like every other yfinance path —
    # a raw broker/forex/crypto alias (XAUUSD, BTCUSD) otherwise silently
    # returns no news. Keep the user's ticker in the report header.
    canonical = normalize_symbol(ticker)
    resolved = "" if canonical == ticker else f" (resolved to {canonical})"
    try:
        stock = yf.Ticker(canonical)
        news = yf_retry(lambda: stock.get_news(count=article_limit)) or []

        # Parse date range for filtering
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        news_str = ""
        filtered_count = 0

        for article in news:
            data = _extract_article_data(article)

            # Keep only articles within the requested window (look-ahead safe).
            if not in_window(data["pub_date"], start_dt, end_dt):
                continue

            news_str += f"### {data['title']} (source: {data['publisher']})\n"
            if data["summary"]:
                news_str += f"{data['summary']}\n"
            if data["link"]:
                news_str += f"Link: {data['link']}\n"
            news_str += "\n"
            filtered_count += 1

        if filtered_count == 0:
            gap = coverage_gap(
                (_extract_article_data(a)["pub_date"] for a in news),
                start_date, end_date, "Yahoo Finance news", f"news for {ticker}{resolved}",
            )
            return gap or f"No news found for {ticker}{resolved} between {start_date} and {end_date}"

        return f"## {ticker}{resolved} News, from {start_date} to {end_date}:\n\n{news_str}"

    except Exception as e:
        raise _classify_news_failure(
            e, ticker, ticker, "news unavailable"
        ) from e


def get_global_news_yfinance(
    curr_date: str,
    look_back_days: int | None = None,
    limit: int | None = None,
) -> str:
    """
    Retrieve global/macro economic news using yfinance Search.

    Args:
        curr_date: Current date in yyyy-mm-dd format
        look_back_days: Number of days to look back. ``None`` falls back to
            ``global_news_lookback_days`` from the active config.
        limit: Maximum number of articles to return. ``None`` falls back to
            ``global_news_article_limit`` from the active config.

    Returns:
        Formatted string containing global news articles
    """
    config = get_config()
    if look_back_days is None:
        look_back_days = config["global_news_lookback_days"]
    if limit is None:
        limit = config["global_news_article_limit"]
    search_queries = config["global_news_queries"]

    curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = curr_dt - relativedelta(days=look_back_days)
    start_date = start_dt.strftime("%Y-%m-%d")

    in_window_news = []
    seen_titles = set()

    try:
        for query in search_queries:
            search = yf_retry(lambda q=query: yf.Search(
                query=q,
                news_count=limit,
                enable_fuzzy_query=True,
            ))

            for article in search.news or []:
                # Window first: the limit counts what the run may read, so an
                # out-of-window article must not spend the budget or cut the
                # remaining searches short (#1356). Flat articles are filtered
                # on the same rule, so none can leak future news (#1007).
                data = _extract_article_data(article)
                if not in_window(data["pub_date"], start_dt, curr_dt):
                    continue
                if data["title"] and data["title"] not in seen_titles:
                    seen_titles.add(data["title"])
                    in_window_news.append(data)

            if len(in_window_news) >= limit:
                break

        news_str = ""
        for data in in_window_news[:limit]:
            news_str += f"### {data['title']} (source: {data['publisher']})\n"
            if data["summary"]:
                news_str += f"{data['summary']}\n"
            if data["link"]:
                news_str += f"Link: {data['link']}\n"
            news_str += "\n"

        # Nothing fell inside the window -> say so rather than return an
        # empty-bodied report (#993).
        if not news_str:
            # Results merge several fuzzy searches, so their timestamps prove no
            # continuous coverage; judge the window against the present only.
            gap = coverage_gap((), start_date, curr_date, "Yahoo Finance global news", "market news")
            return gap or f"No global news found between {start_date} and {curr_date}"

        return f"## Global Market News, from {start_date} to {curr_date}:\n\n{news_str}"

    except Exception as e:
        raise _classify_news_failure(
            e, "global news", "global news", "unavailable"
        ) from e
