from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from tradingagents.dataflows.date_window import as_of, as_of_window, publication_cutoff
from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_news(
    ticker: Annotated[str, "Ticker symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
    trade_date: Annotated[str, InjectedState("trade_date")] = "",
) -> str:
    """
    Retrieve news data for a given ticker symbol.
    Uses the configured news_data vendor.
    Args:
        ticker (str): Ticker symbol
        start_date (str): Start date in yyyy-mm-dd format
        end_date (str): End date in yyyy-mm-dd format
    Returns:
        str: A formatted string containing news data
    """
    start_date, end_date = as_of_window(start_date, end_date, trade_date)
    # The window end is only a *date*: a vendor asked for 2026-09-23 may still
    # return a story filed at 21:15 that day, which is after the decision. The
    # run's trade_date is the point-in-time boundary, so inject it as the
    # exclusive publication cutoff (F1). Vendors that take no cutoff are
    # unaffected; vendors that do can no longer admit post-decision news.
    #
    # A missing trade_date used to drop the cutoff entirely, so a call made
    # outside a graph run (where InjectedState is empty) silently lost the
    # look-ahead defence and admitted news through the end of ``end_date``.
    # Falling back to ``end_date`` keeps the boundary on every call and only
    # defaults the *date being decided on*, which is the tool's own window
    # (independent audit A-02).
    decided_for = trade_date or end_date
    cutoff = publication_cutoff(decided_for)
    if cutoff is None:
        return route_to_vendor("get_news", ticker, start_date, end_date)
    return route_to_vendor(
        "get_news", ticker, start_date, end_date, as_of_cutoff=cutoff
    )

@tool
def get_global_news(
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: Annotated[int | None, "Days to look back; omit to use the configured default"] = None,
    limit: Annotated[int | None, "Max articles to return; omit to use the configured default"] = None,
    trade_date: Annotated[str, InjectedState("trade_date")] = "",
) -> str:
    """
    Retrieve global news data.
    Uses the configured news_data vendor. Defaults for look_back_days and
    limit come from DEFAULT_CONFIG (global_news_lookback_days,
    global_news_article_limit); pass explicit values to override.

    Args:
        curr_date (str): Current date in yyyy-mm-dd format
        look_back_days (int): Number of days to look back; omit to inherit config
        limit (int): Maximum number of articles to return; omit to inherit config

    Returns:
        str: A formatted string containing global news data
    """
    curr_date = as_of(curr_date, trade_date)
    # Same F1 rule as ``get_news``: the window end is a date, not an instant, so
    # a macro story filed after the decision would otherwise slip in. Inject the
    # trade_date as the exclusive publication cutoff where the vendor honours it.
    cutoff = publication_cutoff(trade_date)
    if cutoff is None:
        return route_to_vendor("get_global_news", curr_date, look_back_days, limit)
    return route_to_vendor(
        "get_global_news", curr_date, look_back_days, limit, as_of_cutoff=cutoff
    )

@tool
def get_insider_transactions(
    ticker: Annotated[str, "ticker symbol"],
    trade_date: Annotated[str, InjectedState("trade_date")] = "",
) -> str:
    """
    Retrieve insider transaction information about a company.
    Uses the configured news_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
    Returns:
        str: A report of insider transaction data
    """
    return route_to_vendor("get_insider_transactions", ticker, trade_date or None)
