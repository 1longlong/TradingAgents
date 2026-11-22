"""Alpha Vantage request hardening.

Regressions for #990 (no request timeout -> can hang), #991 (invalid-key
responses mislabeled as rate limits and silently treated as transient), and
#1115 (fundamentals look-ahead filter never ran because the payload is a JSON
string, not a dict), and the date trim that keeps post-end_date bars out of a
historical run.
"""
import json

import pytest

import tradingagents.dataflows.alpha_vantage_common as av
import tradingagents.dataflows.alpha_vantage_fundamentals as avf
import tradingagents.dataflows.alpha_vantage_stock as avs
import tradingagents.dataflows.utils as utils


class _FakeResponse:
    status_code = 200

    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def _patched_get(body, capture=None):
    def fake_get(url, params=None, **kwargs):
        if capture is not None:
            capture.update(kwargs)
        return _FakeResponse(body)
    return fake_get


@pytest.mark.unit
def test_request_passes_timeout(monkeypatch):
    captured = {}
    monkeypatch.setattr(utils.requests, "get", _patched_get("Date,Close\n2025-01-02,1.0", captured))
    av._make_api_request("TIME_SERIES_DAILY", {"symbol": "AAPL"})
    assert captured.get("timeout") == av.REQUEST_TIMEOUT  # #990


@pytest.mark.unit
def test_rate_limit_detected(monkeypatch):
    body = '{"Information": "Our standard API rate limit is 25 requests per day. ... your API key ..."}'
    monkeypatch.setattr(utils.requests, "get", _patched_get(body))
    with pytest.raises(av.AlphaVantageRateLimitError):
        av._make_api_request("TIME_SERIES_DAILY", {"symbol": "AAPL"})


@pytest.mark.unit
def test_invalid_key_not_mislabeled_as_rate_limit(monkeypatch):
    # AV's invalid-key notice mentions "API key"; it must NOT be treated as a
    # (transient) rate limit, but surface as a real configuration error (#991).
    body = ('{"Information": "the parameter apikey is invalid or missing. '
            'Please claim your free API key on (https://www.alphavantage.co/support/#api-key)."}')
    monkeypatch.setattr(utils.requests, "get", _patched_get(body))
    with pytest.raises(av.AlphaVantageNotConfiguredError):
        av._make_api_request("TIME_SERIES_DAILY", {"symbol": "AAPL"})
    with pytest.raises(av.AlphaVantageRateLimitError):  # sanity: rate-limit path still distinct
        monkeypatch.setattr(utils.requests, "get", _patched_get('{"Note": "API call frequency is 5 calls per minute."}'))
        av._make_api_request("TIME_SERIES_DAILY", {"symbol": "AAPL"})


_FUNDAMENTALS_JSON = json.dumps({
    "symbol": "AAPL",
    "annualReports": [
        {"fiscalDateEnding": "2025-12-31", "totalAssets": "1"},   # future -> must drop
        {"fiscalDateEnding": "2023-12-31", "totalAssets": "2"},   # past   -> must keep
    ],
    "quarterlyReports": [
        {"fiscalDateEnding": "2024-06-30", "totalAssets": "3"},   # future -> must drop
        {"fiscalDateEnding": "2023-09-30", "totalAssets": "4"},   # past   -> must keep
    ],
})


@pytest.mark.unit
def test_fundamentals_look_ahead_filter_runs_on_json_string(monkeypatch):
    # #1115: the payload arrives as a JSON *string*; the old dict-only guard let
    # future-dated fiscal periods leak into historical runs.
    monkeypatch.setattr(avf, "_make_api_request", lambda fn, params: _FUNDAMENTALS_JSON)
    out = avf.get_balance_sheet("AAPL", curr_date="2024-01-01")
    assert isinstance(out, str)  # callers still receive a str
    parsed = json.loads(out)
    assert [r["fiscalDateEnding"] for r in parsed["annualReports"]] == ["2023-12-31"]
    assert [r["fiscalDateEnding"] for r in parsed["quarterlyReports"]] == ["2023-09-30"]


@pytest.mark.unit
def test_fundamentals_no_curr_date_passes_through(monkeypatch):
    monkeypatch.setattr(avf, "_make_api_request", lambda fn, params: _FUNDAMENTALS_JSON)
    assert avf.get_income_statement("AAPL") == _FUNDAMENTALS_JSON


@pytest.mark.unit
def test_fundamentals_non_json_body_unchanged(monkeypatch):
    monkeypatch.setattr(avf, "_make_api_request", lambda fn, params: "not-json")
    assert avf.get_cashflow("AAPL", curr_date="2024-01-01") == "not-json"


# ---------------------------------------------------------------------------
# Date trim (see the rationale on the unguarded trim in alpha_vantage_common)
# ---------------------------------------------------------------------------

_DAILY_CSV = (
    "timestamp,open,high,low,close,volume\n"
    "2024-05-13,1,1,1,1,10\n"   # after end_date -> must never be served
    "2024-05-10,1,1,1,1,10\n"
    "2024-05-09,1,1,1,1,10\n"
)


@pytest.mark.unit
def test_stock_data_is_trimmed_to_the_requested_window(monkeypatch):
    monkeypatch.setattr(avs, "_make_api_request", lambda *a, **k: _DAILY_CSV)
    out = avs.get_stock("IBM", "2024-05-09", "2024-05-10")
    assert "2024-05-10" in out and "2024-05-09" in out
    assert "2024-05-13" not in out, "bar after end_date leaked into the window"


@pytest.mark.unit
def test_unparseable_body_is_never_served_untrimmed(monkeypatch):
    """The trim used to swallow the failure and return the whole body, putting
    bars after end_date into a backtest. It must raise instead."""
    monkeypatch.setattr(avs, "_make_api_request",
                        lambda *a, **k: "timestamp,close\nnot-a-date,1\n")

    with pytest.raises(ValueError):
        avs.get_stock("IBM", "2024-05-09", "2024-05-10")


@pytest.mark.unit
def test_empty_body_still_passes_through(monkeypatch):
    monkeypatch.setattr(avs, "_make_api_request", lambda *a, **k: "")
    assert avs.get_stock("IBM", "2024-05-09", "2024-05-10") == ""


def test_request_error_message_carries_no_key(monkeypatch):
    # Alpha Vantage also sends its key in the URL (#1324).
    import requests
    key = "AVKEY1234567890XYZ"
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", key)

    def boom(*a, **k):
        raise requests.Timeout(f"Read timed out. url: https://www.alphavantage.co/query?apikey={key}")

    monkeypatch.setattr(utils.requests, "get", boom)
    with pytest.raises(requests.Timeout) as caught:
        av._make_api_request("OVERVIEW", {"symbol": "IBM"})
    assert key not in str(caught.value)


@pytest.mark.unit
def test_global_news_omitted_optionals_use_the_configured_defaults(monkeypatch):
    """The tool passes None for an omitted look_back_days or limit (#1326).

    The macro-news vendor is GDELT since the Finnhub + GDELT migration; the
    contract is unchanged: an omitted optional must fall back to the configured
    default rather than silently becoming "today only" or unlimited. The window
    must stay inside GDELT's ~3-month archive, so a recent date is used.
    """
    from datetime import datetime, timedelta, timezone

    from tradingagents.dataflows import gdelt_news

    curr = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")
    captured = {}

    def _fake_fetch(query, start_dt, end_dt, limit):
        captured.update({"start": start_dt, "end": end_dt, "limit": limit})
        return [], None, ""

    monkeypatch.setattr(gdelt_news, "_fetch_articles", _fake_fetch)
    monkeypatch.setattr(gdelt_news, "_fetch_page", lambda *a, **k: (None, None, "transport"))
    monkeypatch.setattr(gdelt_news, "_throttle", lambda: None)
    monkeypatch.setattr(
        gdelt_news, "get_config",
        lambda: {
            "global_news_lookback_days": 3,
            "global_news_article_limit": 9,
            "global_news_queries": ["Federal Reserve interest rates"],
        },
    )

    gdelt_news.get_global_news_gdelt(curr, None, None)

    # 3 configured look-back days ending on the analysis date.
    assert (captured["end"] - captured["start"]).days == 3
    assert captured["limit"] == 9


@pytest.mark.unit
def test_the_news_window_includes_the_analysis_day(monkeypatch):
    """time_to was midnight at the start of the end date, so everything
    published during the analysis day, the most decision-relevant day, was
    excluded. The live chain includes the whole analysis day.

    The window is now fetched as a series of per-day ranges (Finnhub's 250-record
    cap truncates the oldest end of a wide range), so the assertion is made over
    every requested range rather than only the last one.
    """
    from tradingagents.dataflows import finnhub_news as fn

    requested: list[str] = []

    def _request(url):
        requested.append(url)
        return 200, "[]", ""

    monkeypatch.setattr(fn, "_request", _request)
    monkeypatch.setattr(fn, "get_api_key", lambda: "test-key")
    monkeypatch.setattr(fn, "get_config", lambda: {"news_article_limit": 20})

    fn.fetch_news_finnhub("AAPL", "2026-03-10", "2026-03-14")

    assert requested, "no request was made"
    # Every day of the window is covered, including the analysis day itself.
    starts = [u.split("from=")[1].split("&")[0] for u in requested]
    ends = [u.split("to=")[1].split("&")[0] for u in requested]
    assert "2026-03-10" in starts
    assert "2026-03-14" in ends
    assert min(starts) == "2026-03-10"
    assert max(ends) == "2026-03-14"


@pytest.mark.unit
@pytest.mark.parametrize("indicator", ["vwma", "mfi"])
def test_an_indicator_this_vendor_lacks_lets_the_next_one_serve_it(indicator):
    """Returning prose counts as success to the router, so the chain stops at a
    vendor that cannot compute the indicator while the next one can."""
    from tradingagents.dataflows import alpha_vantage_indicator
    from tradingagents.dataflows.errors import VendorError

    with pytest.raises(VendorError):
        alpha_vantage_indicator.get_indicator("AAPL", indicator, "2026-05-08", 30)


@pytest.mark.unit
def test_ticker_news_asks_for_only_as_many_articles_as_configured(monkeypatch):
    """The vendor's default page size reaches the prompt in full; the adapter
    must ask for, and keep, only the configured number of articles."""
    from tradingagents.dataflows import finnhub_news as fn

    articles = [
        {"headline": f"NVDA story {i}", "datetime": 1790173800 + i,
         "source": "Reuters", "url": f"https://x/{i}", "summary": "Nvidia news.",
         "related": "NVDA"}
    for i in range(20)]
    monkeypatch.setattr(fn, "_request", lambda url: (200, json.dumps(articles), ""))
    monkeypatch.setattr(fn, "get_api_key", lambda: "test-key")
    # ``finnhub_news`` binds ``get_config`` at import, so patch it there.
    monkeypatch.setattr(fn, "get_config", lambda: {"news_article_limit": 8})

    outcome = fn.fetch_news_finnhub("NVDA", "2026-09-16", "2026-09-23")

    assert len(outcome.articles) == 8
