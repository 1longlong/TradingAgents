"""Regressions for the defects the final independent audit proved.

Each test here failed before its fix, so the file doubles as evidence of what
"fixed" means. They belong together because they all concern the boundary the
migration is judged at: what the *analyst* is told happened, as opposed to what
a single function returned.

Numbering follows the audit's finding ids where one exists.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

import tradingagents.dataflows.finnhub_news as fn
import tradingagents.dataflows.gdelt_news as gn
from tradingagents.agents.schemas import (
    NewsSourceStatus,
    classify_news_source_availability,
)
from tradingagents.dataflows.news_merge import (
    ProviderOutcome,
    combine_status,
    merge_news_sections,
)
from tradingagents.dataflows.news_status import NewsStatus

START, END = "2026-09-16", "2026-09-23"

#: Two providers' worth of sections, the shape ``merge_news_sections`` emits.
_MERGED = "## NVDA News, from {s} to {e}\n\nOverall status: SUCCESS_REAL_CONTENT\n\n"
_ARTICLE = (
    "#### Finnhub — verified articles in window\n\n"
    "## NVDA News\n\n"
    "### {headline} (source: reuters)\n"
    "**Published:** 2026-09-20T12:00:00+00:00\n"
    "Link: https://example.invalid/{n}\n"
)


class _Msg:
    """The slice of a LangChain ToolMessage the classifier touches."""

    type = "tool"
    name = "get_news"

    def __init__(self, content: str):
        self.content = content


def _merged(finnhub: str, gdelt: str) -> str:
    return (
        _MERGED.format(s=START, e=END)
        + finnhub
        + "\n#### GDELT — discovery and verification\n\n"
        + gdelt
    )


# --- F2: a real article outranks every prose marker --------------------------


def test_a_headline_containing_an_outage_phrase_is_still_news():
    # "Nvidia says cloud service is unavailable for Europe customers" is a real
    # article; "unavailable for" is also a marker phrase. The article must win.
    text = _merged(
        _ARTICLE.format(headline="Nvidia says cloud service is unavailable for Europe customers", n=1),
        "NEWS_STATUS=EMPTY_VALID: nothing",
    )
    assert classify_news_source_availability([_Msg(text)]) is NewsSourceStatus.AVAILABLE


@pytest.mark.parametrize("headline", [
    "Nvidia chips are unavailable for two quarters, partner says",
    "DATA_UNAVAILABLE was the error page, Nvidia says in filing",
    "What Nvidia's 'no news found' guidance actually means for buyers",
])
def test_no_marker_phrase_in_a_headline_can_erase_a_real_article(headline):
    text = _merged(_ARTICLE.format(headline=headline, n=2), "NEWS_STATUS=TIMEOUT: down")
    assert classify_news_source_availability([_Msg(text)]) is NewsSourceStatus.AVAILABLE


def test_the_merged_block_still_reports_success_for_that_article():
    outcome_fh = ProviderOutcome(
        "Finnhub",
        "### Nvidia says cloud service is unavailable for Europe customers (source: reuters)",
    )
    outcome_gt = ProviderOutcome("GDELT", "NEWS_STATUS=EMPTY_VALID: nothing")
    text = merge_news_sections([outcome_fh, outcome_gt], ticker="NVDA",
                               start_date=START, end_date=END)
    assert "no NVDA articles were published" not in text
    assert combine_status([outcome_fh, outcome_gt]) is NewsStatus.SUCCESS_REAL_CONTENT


# --- F1: a two-provider merged block is judged per section -------------------


def test_one_degraded_provider_does_not_erase_the_other_in_a_two_provider_block():
    # The exact CAND-01 shape: Finnhub has an article, GDELT timed out. Before
    # the fix a two-section block was mistaken for a single vendor's output and
    # the GDELT token erased Finnhub's article.
    text = _merged(
        _ARTICLE.format(headline="Nvidia beats estimates", n=3),
        "NEWS_STATUS=TIMEOUT: GDELT timed out",
    )
    assert classify_news_source_availability([_Msg(text)]) is NewsSourceStatus.AVAILABLE


def test_a_two_provider_block_with_no_articles_anywhere_is_unavailable():
    text = _merged(
        "NEWS_STATUS=EMPTY_VALID: nothing",
        "NEWS_STATUS=RATE_LIMITED: 429",
    )
    assert classify_news_source_availability([_Msg(text)]) is NewsSourceStatus.UNAVAILABLE


@pytest.mark.parametrize("gdelt_status", [
    "TIMEOUT", "AUTH_MISSING", "AUTH_INVALID", "RATE_LIMITED", "HTTP_ERROR",
    "PROVIDER_UNAVAILABLE", "PARSE_ERROR", "OUT_OF_WINDOW",
    "HISTORICAL_UNSUPPORTED", "EMPTY_VALID",
])
def test_every_gdelt_status_leaves_a_finnhub_article_available(gdelt_status):
    text = _merged(
        _ARTICLE.format(headline="Nvidia raises guidance", n=4),
        f"NEWS_STATUS={gdelt_status}: x",
    )
    assert classify_news_source_availability([_Msg(text)]) is NewsSourceStatus.AVAILABLE


# --- F3: EMPTY_VALID requires every provider to have answered empty ----------


def test_a_query_that_imply_a_coverage_gap_is_not_reported_as_a_real_absence():
    empty = ProviderOutcome("Finnhub", "NEWS_STATUS=EMPTY_VALID: nothing")
    throttled = ProviderOutcome("GDELT", "NEWS_STATUS=RATE_LIMITED: 429")
    assert combine_status([empty, throttled]) is not NewsStatus.EMPTY_VALID
    text = merge_news_sections([empty, throttled], ticker="NVDA",
                               start_date=START, end_date=END)
    assert "genuine absence" not in text


def test_an_answered_but_empty_provider_does_not_outvote_a_real_absence():
    # Both are facts about the window rather than failures, so either may be
    # reported without hiding an outage.
    empty = ProviderOutcome("Finnhub", "NEWS_STATUS=EMPTY_VALID: nothing")
    out_of_window = ProviderOutcome("GDELT", "NEWS_STATUS=OUT_OF_WINDOW: old")
    assert combine_status([empty, out_of_window]) in (
        NewsStatus.EMPTY_VALID, NewsStatus.OUT_OF_WINDOW
    )


def test_the_global_gdelt_path_does_not_call_mixed_answers_a_real_absence():
    # One query answered empty, another only had out-of-window hits. That is a
    # coverage gap, so EMPTY_VALID would be an affirmative claim the data does
    # not support.
    def fake_fetch(_query, _start, _end, _limit):
        if "one" in _query:
            return [], NewsStatus.EMPTY_VALID, "none"
        return [{"title": "Nvidia thing", "url": "https://ex.invalid/a",
                 "domain": "ex.invalid"}], None, ""

    config = {"global_news_queries": ["one", "two"],
              "global_news_lookback_days": 7,
              "global_news_article_limit": 5}
    # A readable page that carries no date: the second query did return hits,
    # they simply could not be verified inside the window.
    undated = "<html><head></head><body>nothing dated here</body></html>"
    with patch.object(gn, "_fetch_articles", side_effect=fake_fetch), \
            patch.object(gn, "_fetch_page", return_value=(200, undated, "")), \
            patch.object(gn, "get_config", return_value=config):
        out = gn.get_global_news_gdelt(curr_date="2026-09-23")
    assert "NEWS_STATUS=EMPTY_VALID" not in out
    assert "NEWS_STATUS=OUT_OF_WINDOW" in out


# --- F6: no credential can ride an exception or a parse detail ----------------
#
# The transport wrappers are stubbed by ``tests/conftest.py``; these tests go
# through the real classification path with a fake token, which is enough to
# prove the redaction is applied where the text is composed.


def test_a_parse_error_detail_is_redacted():
    body = "not json, echoing " + "https://finnhub.io/api/v1/x?token=FAKELEAK123"
    with patch.object(fn, "_request", return_value=(200, body, "")), \
            patch.object(fn, "get_api_key", return_value="test-key"), \
            patch.object(fn, "get_config", return_value={"news_article_limit": 20}):
        outcome = fn.fetch_news_finnhub("NVDA", START, END)
    assert outcome.status is NewsStatus.PARSE_ERROR
    assert "FAKELEAK123" not in (outcome.detail or "")


def test_a_provider_exception_carrying_the_key_reaches_the_analyst_redacted():
    def boom(*_a, **_k):
        raise RuntimeError("GET https://finnhub.io/api/v1/company-news?token=FAKELEAK999")

    with patch.object(fn, "get_news_finnhub", side_effect=boom), \
            patch.object(gn, "get_news_gdelt", return_value="NEWS_STATUS=EMPTY_VALID: x"):
        text = fn.get_news_combined("NVDA", START, END)
    assert "FAKELEAK999" not in text
    assert "<redacted>" in text


# --- the GDELT query must never quote a phrase GDELT rejects -----------------


@pytest.mark.parametrize("ticker,name", [
    ("NVDA", "NVIDIA"),
    ("AAPL", "Apple"),
    ("MSFT", "Microsoft"),
    ("AMZN", "Amazon"),
    ("TSLA", "Tesla"),
    ("XOM", "Exxon"),
    ("JPM", "JPMorgan"),
])
def test_no_query_quotes_a_four_character_symbol(ticker, name):
    # GDELT rejects any quoted phrase of 4 characters or fewer with HTTP 200 and
    # the plain text "The specified phrase is too short." A 4-char guard was one
    # short, so every mega-cap symbol poisoned its own query (live run
    # 2026-11-15). The company name must carry the phrase instead.
    query = gn._query_for(ticker)
    assert f'"{ticker}"' not in query
    assert "phrase" not in query
    if len(ticker) <= gn._MIN_QUOTED_PHRASE:
        assert f'"{name}"' in query or ticker in query


def test_a_long_symbol_is_still_quoted():
    query = gn._query_for("GOOGL")
    assert '"GOOGL"' in query


@pytest.mark.parametrize("body", [
    "The specified phrase is too short.",
    "Invalid query end date.",
])
def test_a_plain_text_query_rejection_is_not_reported_as_a_vendor_outage(body):
    # These arrive with HTTP 200 and English prose. Calling them PARSE_ERROR
    # raised VendorUnavailableError and sent the router to the next vendor for
    # what was our own malformed query.
    start_dt = datetime(2026, 9, 16, tzinfo=timezone.utc)
    end_dt = datetime(2026, 9, 23, tzinfo=timezone.utc)
    with patch.object(gn, "_request", return_value=(200, body, "")), \
            patch.object(gn, "_throttle", lambda: None):
        _articles, status, detail = gn._fetch_articles(
            "(x) sourcelang:english", start_dt, end_dt, 5)
    assert status is NewsStatus.HTTP_ERROR
    assert detail


# --- F5: the PIT cutoff reaches the vendor from every entry point ------------

def test_the_sentiment_prefetch_passes_the_trade_date_as_the_cutoff():
    # The sentiment analyst calls ``get_news.func`` directly. Without
    # ``trade_date`` the tool cannot compute a cutoff and the look-ahead guard is
    # silently off for that path, so the argument itself is asserted here.
    import tradingagents.agents.analysts.sentiment_analyst as mod

    seen = {}

    def fake_prefetch(name, target, *args, **kwargs):
        if name == "news":
            seen["kwargs"] = kwargs
            seen["target"] = target
            return "NEWS"
        return "OTHER"

    class _Structured:
        def invoke(self, _prompt):
            raise AssertionError("structured output must not be needed for this test")

    class _LLM:
        def with_structured_output(self, _schema):
            return _Structured()

    state = {
        "company_of_interest": "NVDA",
        "trade_date": "2026-09-23",
        "market_report": "",
        "sentiment_report": "",
        "news_report": "",
        "fundamentals_report": "",
        "past_context": "",
    }
    node = mod.create_sentiment_analyst(_LLM())
    with patch.object(mod, "record_prefetch_call", side_effect=fake_prefetch), \
            patch.object(mod, "get_instrument_context_from_state", return_value="ctx"):
        try:
            node(state)
        except Exception:  # noqa: BLE001 - the LLM stub is deliberately minimal
            pass
    assert seen.get("kwargs", {}).get("trade_date") == "2026-09-23"
