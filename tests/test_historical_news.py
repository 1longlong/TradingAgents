"""Historical news adapter: PIT cutoff, dedupe, and honest failure classes.

The project's news vendors before this one could only serve recent articles, so
a backtest window produced a coverage notice every time. Alpha Vantage's
NEWS_SENTIMENT accepts a date range, and these tests pin the properties that
make it safe to put in front of the analyst:

* an article published after the decision cutoff is excluded;
* duplicate rows for one headline collapse to one;
* "the vendor returned no articles" is a different string from "the vendor
  could not be asked", so an outage never reads as an absence of news.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import tradingagents.dataflows.historical_news as hn
from tradingagents.dataflows.date_window import parse_publication_time
from tradingagents.dataflows.errors import VendorRateLimitError, VendorUnavailableError


def _feed(*articles):
    return json.dumps({"feed": list(articles)})


def _article(title, time_published, source="Reuters", url=None, summary="", score=None):
    art = {"title": title, "time_published": time_published, "source": source}
    if url:
        art["url"] = url
    if summary:
        art["summary"] = summary
    if score is not None:
        art["overall_sentiment_score"] = score
    return art


def _run(payload, **kwargs):
    kwargs.setdefault("as_of_cutoff", "2026-09-23T20:00:00Z")
    with patch.object(hn, "_alpha_vantage_news", lambda *a, **k: payload):
        return hn.get_news_historical("NVDA", "2026-09-16", "2026-09-23", **kwargs)


class TestPIT:
    def test_article_after_cutoff_is_excluded(self):
        out = _run(_feed(
            _article("Before close", "20260923T143000"),
            _article("After close scoop", "20260923T211500"),
        ))
        assert "Before close" in out
        assert "After close scoop" not in out

    def test_article_before_window_is_excluded(self):
        out = _run(_feed(_article("Too old", "20260901T100000")))
        assert "Too old" not in out
        assert "NEWS_STATUS=EMPTY_VALID" in out

    def test_start_day_boundary_is_inclusive(self):
        out = _run(_feed(_article("Start day", "20260916T000000")))
        assert "Start day" in out

    def test_undated_article_is_dropped_not_guessed(self):
        out = _run(_feed(_article("No timestamp", "")))
        assert "No timestamp" not in out

    def test_default_cutoff_is_end_of_end_date(self):
        # No explicit cutoff: 23:59 on the analysis day is allowed, 00:00 the
        # next day is not.
        with patch.object(hn, "_alpha_vantage_news", lambda *a, **k: _feed(
            _article("Same day late", "20260923T235800"),
            _article("Next day", "20260924T000100"),
        )):
            out = hn.get_news_historical("NVDA", "2026-09-16", "2026-09-23")
        assert "Same day late" in out
        assert "Next day" not in out


class TestFormatAndDedupe:
    def test_duplicate_headlines_collapse(self):
        out = _run(_feed(
            _article("Same story", "20260923T100000", url="https://a/1"),
            _article("Same story", "20260923T110000", url="https://a/1"),
        ))
        assert out.count("### Same story") == 1

    def test_ordered_oldest_first(self):
        out = _run(_feed(
            _article("Later", "20260923T180000"),
            _article("Earlier", "20260923T090000"),
        ))
        assert out.index("Earlier") < out.index("Later")

    def test_success_header_matches_yfinance_contract(self):
        out = _run(_feed(_article("Headline", "20260923T120000")))
        assert out.startswith("## NVDA News, from 2026-09-16 to 2026-09-23:")

    def test_article_keeps_source_date_and_url(self):
        out = _run(_feed(_article(
            "Headline", "20260923T120000", source="Bloomberg", url="https://b/1",
        )))
        assert "(source: Bloomberg)" in out
        assert "2026-09-23T12:00:00" in out
        assert "https://b/1" in out

    def test_limit_applies(self):
        arts = [_article(f"H{i}", f"20260923T1{i}0000") for i in range(5)]
        out = _run(_feed(*arts), limit=2)
        assert out.count("### H") == 2


class TestFailureClasses:
    """Failure classes must be *typed*, not text.

    Campaign 20261107_140536 found that returning failure text made the vendor
    chain unreachable: ``route_to_vendor`` accepts the first non-raising result
    as the answer, so Alpha Vantage's "unavailable" string stopped GDELT from
    ever being asked. These tests therefore assert the raise, not a message.
    """

    def test_no_key_is_typed_unavailable_not_absence(self):
        def boom(*a, **k):
            raise hn.AlphaVantageNotConfiguredError("ALPHA_VANTAGE_API_KEY not set")
        with patch.object(hn, "_alpha_vantage_news", boom):
            with pytest.raises(VendorUnavailableError):
                hn.get_news_historical("NVDA", "2026-09-16", "2026-09-23")

    def test_rate_limit_is_typed_and_skippable(self):
        def boom(*a, **k):
            raise hn.AlphaVantageRateLimitError("25 requests/day")
        with patch.object(hn, "_alpha_vantage_news", boom):
            with pytest.raises(VendorRateLimitError) as ctx:
                hn.get_news_historical("NVDA", "2026-09-16", "2026-09-23")
        assert "throttl" in str(ctx.value).lower() and "25 requests/day" in str(ctx.value)

    def test_vendor_note_is_unavailable(self):
        out = _run(json.dumps({"Note": "Thank you for using Alpha Vantage! 25 requests/day"}))
        assert "NEWS_STATUS=AUTH_INVALID" in out
        assert "No news found" not in out

    def test_empty_feed_is_a_real_absence(self):
        out = _run(_feed())
        assert "NEWS_STATUS=EMPTY_VALID" in out
        assert "DATA_UNAVAILABLE" not in out
        assert "real absence" in out

    def test_unparsable_response_is_unavailable(self):
        out = _run("not json{{")
        assert "NEWS_STATUS=PARSE_ERROR" in out
        assert "No news found" not in out

    def test_network_error_is_typed_and_skippable(self):
        def boom(*a, **k):
            raise TimeoutError("timed out")
        with patch.object(hn, "_alpha_vantage_news", boom):
            with pytest.raises(VendorRateLimitError):
                hn.get_news_historical("NVDA", "2026-09-16", "2026-09-23")

    def test_zero_length_output_is_never_produced(self):
        # Every path returns analyst-readable text, never "".
        for payload in (_feed(), json.dumps({}), "garbage"):
            assert _run(payload).strip()


class TestPublicationParser:
    @pytest.mark.parametrize("raw,expected", [
        ("20260923T143000", "2026-09-23 14:30:00+00:00"),
        ("2026-09-23T14:30:00Z", "2026-09-23 14:30:00+00:00"),
        ("2026-09-23", "2026-09-23 00:00:00+00:00"),
    ])
    def test_parses_known_shapes(self, raw, expected):
        assert str(parse_publication_time(raw)) == expected

    def test_offset_is_normalised_to_utc(self):
        parsed = parse_publication_time("2026-09-23T10:30:00-04:00")
        assert str(parsed) == "2026-09-23 14:30:00+00:00"

    @pytest.mark.parametrize("raw", ["", None, "garbage", "2026-13-45"])
    def test_unparsable_returns_none(self, raw):
        assert parse_publication_time(raw) is None


class TestRouting:
    def test_historical_vendor_is_registered_first(self):
        from tradingagents.dataflows.interface import VENDOR_METHODS
        order = list(VENDOR_METHODS["get_news"])
        assert order[0] == "alpha_vantage_historical"
        assert "yfinance" in order

    def test_router_returns_string_not_exception_without_key(self):
        from tradingagents.dataflows.interface import route_to_vendor
        out = route_to_vendor("get_news", "NVDA", "2026-09-16", "2026-09-23")
        assert isinstance(out, str) and out.strip()
