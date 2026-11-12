import json

from .alpha_vantage_common import _make_api_request, format_datetime_for_api
from .config import get_config
from .evidence_capture import capture_news_articles


def get_news(ticker, start_date, end_date) -> dict[str, str] | str:
    """Returns live and historical market news & sentiment data from premier news outlets worldwide.

    Covers stocks, cryptocurrencies, forex, and topics like fiscal policy, mergers & acquisitions, IPOs.

    Args:
        ticker: Stock symbol for news articles.
        start_date: Start date for news search.
        end_date: End date for news search.

    Returns:
        Dictionary containing news sentiment data or JSON string.
    """

    # Without a limit the endpoint returns 50 articles, each with per-ticker
    # sentiment arrays, and all of it reaches the prompt.
    params = {
        "tickers": ticker,
        "time_from": format_datetime_for_api(start_date),
        "time_to": format_datetime_for_api(end_date, end_of_day=True),
        "limit": str(get_config()["news_article_limit"]),
    }

    response = _make_api_request("NEWS_SENTIMENT", params)
    _capture_news_sentiment_feed(response, ticker, "alpha_vantage_news", "get_news")
    return response

def _capture_news_sentiment_feed(response, ticker: str, source_name: str, tool: str) -> None:
    """Capture Alpha Vantage NEWS_SENTIMENT articles as typed news evidence.

    The endpoint returns a JSON ``feed`` of original article objects with
    ``title``/``url``/``source``/``time_published`` and per-ticker sentiment
    arrays. Only the article-level fields are captured here (news category); the
    per-ticker sentiment is left to the sentiment adapters, never inferred from
    a machine label onto an arbitrary text. A non-JSON body or an absent feed is
    a no-op (the caller still receives the original ``response`` unchanged).
    """
    if not isinstance(response, str):
        return
    try:
        payload = json.loads(response)
    except (ValueError, TypeError):
        return
    if not isinstance(payload, dict):
        return
    feed = payload.get("feed")
    if not isinstance(feed, list):
        return
    articles = []
    for item in feed:
        if not isinstance(item, dict):
            continue
        published = item.get("time_published")
        # AV format is YYYYMMDDTHHMMSS; normalize to ISO date for the adapter.
        if isinstance(published, str) and len(published) >= 8:
            published = f"{published[0:4]}-{published[4:6]}-{published[6:8]}"
        articles.append(
            {
                "title": item.get("title"),
                "publisher": item.get("source") or "",
                "url": item.get("url") or "",
                "published": published,
            }
        )
    capture_news_articles(ticker, articles, source_name=source_name, tool=tool)

def get_global_news(curr_date, look_back_days: int | None = None, limit: int | None = None) -> dict[str, str] | str:
    """Returns global market news & sentiment data without ticker-specific filtering.

    Covers broad market topics like financial markets, economy, and more.

    Args:
        curr_date: Current date in yyyy-mm-dd format.
        look_back_days: Number of days to look back; ``None`` uses
            ``global_news_lookback_days`` from the active config.
        limit: Maximum number of articles; ``None`` uses
            ``global_news_article_limit`` from the active config.

    Returns:
        Dictionary containing global news sentiment data or JSON string.
    """
    from datetime import datetime, timedelta

    config = get_config()
    if look_back_days is None:
        look_back_days = config["global_news_lookback_days"]
    if limit is None:
        limit = config["global_news_article_limit"]

    curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = curr_dt - timedelta(days=look_back_days)
    start_date = start_dt.strftime("%Y-%m-%d")

    params = {
        "topics": "financial_markets,economy_macro,economy_monetary",
        "time_from": format_datetime_for_api(start_date),
        "time_to": format_datetime_for_api(curr_date, end_of_day=True),
        "limit": str(limit),
    }

    response = _make_api_request("NEWS_SENTIMENT", params)
    _capture_news_sentiment_feed(response, "GLOBAL", "alpha_vantage_global_news", "get_global_news")
    return response


def get_insider_transactions(symbol: str, curr_date: str | None = None) -> dict[str, str] | str:
    """Returns latest and historical insider transactions by key stakeholders.

    Covers transactions by founders, executives, board members, etc.

    Args:
        symbol: Ticker symbol. Example: "IBM".
        curr_date: When given, only transactions on or before it (yyyy-mm-dd).

    Returns:
        Dictionary containing insider transaction data or JSON string.
    """

    params = {
        "symbol": symbol,
    }

    response = _make_api_request("INSIDER_TRANSACTIONS", params)
    if not curr_date:
        return response
    payload = json.loads(response)
    payload["data"] = [t for t in payload["data"] if t["transaction_date"] <= curr_date]
    return json.dumps(payload)
