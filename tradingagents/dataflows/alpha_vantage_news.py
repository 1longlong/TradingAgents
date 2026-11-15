"""Alpha Vantage news-adjacent endpoints.

Only :func:`get_insider_transactions` lives here now. The ``NEWS_SENTIMENT``
based ``get_news``/``get_global_news`` were removed in the Finnhub + GDELT news
migration: company news is Finnhub's job and global/macro news is GDELT's, and
keeping an unprovisioned third news path meant several competing entry points
where only one was ever exercised.
"""

from __future__ import annotations

import json

from .alpha_vantage_common import _make_api_request


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
