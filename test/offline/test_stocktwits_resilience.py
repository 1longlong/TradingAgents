"""StockTwits fetch: transport-error resilience (#1024) and crypto symbol
mapping (#1113).

StockTwits lists crypto under ``<BASE>.X`` (Yahoo's ``BTC-USD`` 404s), and any
transport error must degrade to a placeholder rather than raise.
"""

from __future__ import annotations

import http.client
from unittest.mock import patch
from urllib.error import HTTPError

import pytest

from tradingagents.dataflows import stocktwits


def _raise(exc):
    class _Resp:
        def __enter__(self_inner):
            return self_inner

        def __exit__(self_inner, *a):
            return False

        def read(self_inner):
            raise exc
    return _Resp()


@pytest.mark.unit
class TestStockTwitsResilience:
    @pytest.mark.parametrize(
        "exc",
        [
            http.client.IncompleteRead(b""),
            HTTPError("url", 503, "down", {}, None),
            TimeoutError("slow"),
        ],
    )
    def test_transport_errors_return_placeholder(self, exc):
        with patch.object(stocktwits, "urlopen", return_value=_raise(exc)):
            out = stocktwits.fetch_stocktwits_messages("NVDA")
        assert "unavailable" in out.lower()
        assert out.startswith("<stocktwits unavailable")


@pytest.mark.unit
class TestStockTwitsCryptoSymbols:
    @pytest.mark.parametrize(
        ("ticker", "expected"),
        [
            ("BTC-USD", "BTC.X"),
            ("eth-usd", "ETH.X"),
            ("SOL-USD", "SOL.X"),
            ("BTCUSD", "BTC.X"),      # undashed broker form
            ("BTC-USDT", "BTC.X"),    # stablecoin quote
            ("AMD", "AMD"),
            ("BRK-B", "BRK-B"),       # dashed class share: untouched
            ("GOLD", "GOLD"),         # real equity (aliases elsewhere): untouched here
            ("XYZ-USD", "XYZ-USD"),   # unknown base: not treated as crypto
        ],
    )
    def test_symbol_mapping(self, ticker, expected):
        assert stocktwits._stocktwits_symbol(ticker) == expected

    def test_crypto_pair_requests_dot_x_endpoint(self):
        seen = {}

        def fake_urlopen(req, timeout=None):
            seen["url"] = req.full_url
            raise TimeoutError("stop after capturing the URL")

        with patch.object(stocktwits, "urlopen", side_effect=fake_urlopen):
            stocktwits.fetch_stocktwits_messages("BTC-USD")
        assert "/symbol/BTC.X.json" in seen["url"]



def test_stocktwits_refuses_non_https_feed_before_io(monkeypatch):
    """ADR-012 / NFR-OFF-001: unsafe scheme is an outage, never empty sentiment."""
    from tradingagents.dataflows import stocktwits, utils

    opened = []
    monkeypatch.setattr(stocktwits, "_API", "file:///never-opened/{ticker}")
    monkeypatch.setattr(utils, "build_opener", lambda *args: opened.append(args))
    result = stocktwits.fetch_stocktwits_messages("NVDA")
    assert "unavailable" in result.lower()
    assert "no messages" not in result.lower()
    assert opened == []
