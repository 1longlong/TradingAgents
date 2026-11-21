"""Symbol normalization must apply on every data path, not just price fetch.

Regression tests for #983 (instrument identity), #984 (reflection returns), and
the news path: a broker symbol like XAUUSD must resolve through the same
canonical form the price path uses, so identity, realized-return, and news
lookups hit the right instrument instead of failing/mismatching.
"""
import pandas as pd

import tradingagents.agents.utils.agent_utils as au
import tradingagents.graph.trading_graph as tg
from tradingagents.graph.trading_graph import TradingAgentsGraph


def test_identity_lookup_normalizes_symbol(monkeypatch):
    seen = {}

    class FakeTicker:
        def __init__(self, symbol):
            seen["symbol"] = symbol

        @property
        def info(self):
            return {"longName": "Gold Futures", "quoteType": "FUTURE"}

    monkeypatch.setattr(au.yf, "Ticker", FakeTicker)
    au.resolve_instrument_identity.cache_clear()

    identity = au.resolve_instrument_identity("XAUUSD")

    assert seen["symbol"] == "GC=F"  # normalized, not the raw broker symbol
    assert identity.get("company_name") == "Gold Futures"


def test_fetch_returns_normalizes_symbol(monkeypatch):
    queried = []

    class FakeTicker:
        def __init__(self, symbol):
            queried.append(symbol)

        def history(self, *args, **kwargs):
            prices = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0]
            idx = pd.date_range(start="2025-01-02", periods=len(prices), freq="D")
            return pd.DataFrame({"Close": prices}, index=idx)

    monkeypatch.setattr(tg.yf, "Ticker", FakeTicker)

    # _fetch_returns does not use ``self``; call unbound to avoid building the graph.
    raw, alpha, days, resolved = TradingAgentsGraph._fetch_returns(
        None, "XAUUSD", "2025-01-02", holding_days=5, benchmark="SPY"
    )

    assert queried[0] == "GC=F"  # stock symbol normalized (#984)
    assert queried[1] == "SPY"   # benchmark left as the canonical symbol
    assert raw is not None and days is not None
    assert resolved == "2025-01-07"  # resolution date recorded (#1251)


def test_news_lookup_uses_the_canonical_symbol(monkeypatch):
    """The news request must be issued for the canonical symbol, and the
    analyst must still see the user's ticker plus the canonical provenance."""
    import tradingagents.dataflows.finnhub_news as finnhub

    seen = {}

    def _request(url):
        seen["url"] = url
        return 200, "[]", ""

    monkeypatch.setattr(finnhub, "_request", _request)
    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")

    finnhub.fetch_news_finnhub("XAUUSD", "2025-01-01", "2025-01-10")

    # News is queried with the canonical symbol, not the broker alias.
    assert "symbol=GC%3DF" in seen["url"] or "symbol=GC=F" in seen["url"]
