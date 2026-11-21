"""Sentiment missingness: UNKNOWN must never be rendered as Neutral 5.0.

The defect this guards against: every saved sentiment report began
``**Overall Sentiment:** **Neutral** (Score: 5.0/10)`` even when all three
prefetched sources were placeholders, because the schema forced a band and the
prompt made ``Neutral`` the only silence-compatible choice. Absence of data was
therefore rendered as evidence of a balanced market, and that header is the
first line six downstream agents read.

The cases below are the ones the brief requires: all-unavailable, single
source, partial, genuine neutral, bullish, bearish, timeout, rate limit,
historical no-coverage, and the downstream UNKNOWN-vs-Neutral distinction.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from tradingagents.agents.analysts.sentiment_analyst import create_sentiment_analyst
from tradingagents.agents.schemas import (
    SentimentBand,
    SentimentDataStatus,
    SentimentReport,
    classify_sentiment_sources,
    render_sentiment_report,
)


# --- The exact placeholder strings the fetchers produce ---------------------
COVERAGE_ST = (
    "<StockTwits unavailable for 2026-09-16..2026-09-23: it only serves recent "
    "items (coverage starts 2026-11-06), so this is not an absence of messages "
    "about $NVDA>"
)
COVERAGE_REDDIT = (
    "<Reddit unavailable for 2026-09-16..2026-09-23: it only serves recent items "
    "(coverage starts 2026-11-02), so this is not an absence of discussion about $NVDA>"
)
ROUTED_NEWS = (
    "DATA_UNAVAILABLE: no configured vendor could serve get_news right now "
    "(news unavailable). This says nothing about the instrument."
)
REAL_ST = "Bullish: 18 (60%) · Bearish: 4 (13%) · Total: 30 most-recent messages"
REAL_REDDIT = "r/wallstreetbets — 12 recent posts mentioning NVDA"
REAL_NEWS = "## NVDA News, from 2026-09-16 to 2026-09-23:\n\n### Nvidia ships x (source: Reuters)"


def _report(**kw):
    base = dict(
        overall_band=SentimentBand.NEUTRAL,
        overall_score=5.0,
        confidence="low",
        narrative="body",
    )
    base.update(kw)
    return SentimentReport(**base)


class TestClassifier:
    """Availability is decided in Python from the strings, not by the model."""

    def test_all_three_unavailable(self):
        assert classify_sentiment_sources(
            ROUTED_NEWS, COVERAGE_ST, COVERAGE_REDDIT
        ) is SentimentDataStatus.UNAVAILABLE

    def test_single_source_available_is_partial(self):
        assert classify_sentiment_sources(
            ROUTED_NEWS, REAL_ST, COVERAGE_REDDIT
        ) is SentimentDataStatus.PARTIAL

    def test_multiple_partial(self):
        assert classify_sentiment_sources(
            REAL_NEWS, REAL_ST, COVERAGE_REDDIT
        ) is SentimentDataStatus.PARTIAL

    def test_all_available(self):
        assert classify_sentiment_sources(
            REAL_NEWS, REAL_ST, REAL_REDDIT
        ) is SentimentDataStatus.AVAILABLE

    def test_coverage_gap_is_not_an_error(self):
        # A feed that did not reach the window fetched successfully; calling
        # that ERROR would misdescribe the vendor's behaviour.
        assert classify_sentiment_sources(
            COVERAGE_ST, COVERAGE_ST, COVERAGE_REDDIT
        ) is SentimentDataStatus.UNAVAILABLE

    def test_timeout_is_error(self):
        assert classify_sentiment_sources(
            ROUTED_NEWS, "<stocktwits unavailable: TimeoutError>", COVERAGE_REDDIT
        ) is SentimentDataStatus.ERROR

    def test_rate_limit_is_error(self):
        assert classify_sentiment_sources(
            ROUTED_NEWS,
            "<Reddit unavailable: fetch failed (HTTP 429 rate limit exceeded); "
            "this is not an absence of discussion>",
            COVERAGE_ST,
        ) is SentimentDataStatus.ERROR

    def test_historical_no_coverage(self):
        assert classify_sentiment_sources(
            ROUTED_NEWS, COVERAGE_ST, COVERAGE_REDDIT
        ) is SentimentDataStatus.UNAVAILABLE

    def test_empty_strings_are_unavailable_not_error(self):
        assert classify_sentiment_sources("", "", "") is SentimentDataStatus.UNAVAILABLE


class TestRender:
    def test_unscored_report_has_no_number(self):
        md = render_sentiment_report(_report(overall_band=SentimentBand.UNKNOWN, overall_score=None))
        assert "**Unknown**" in md
        assert "not scored" in md
        assert "5.0/10" not in md

    def test_scored_report_still_shows_number(self):
        md = render_sentiment_report(_report(overall_score=7.5, overall_band=SentimentBand.BULLISH))
        assert "7.5/10" in md

    def test_genuine_neutral_keeps_its_score(self):
        # Real sources that genuinely balance still produce Neutral with a
        # number: only *missing* data is unscored.
        md = render_sentiment_report(
            _report(overall_band=SentimentBand.NEUTRAL, overall_score=5.0,
                    data_status=SentimentDataStatus.AVAILABLE)
        )
        assert "**Neutral**" in md
        assert "5.0/10" in md

    def test_data_status_is_rendered(self):
        md = render_sentiment_report(_report(data_status=SentimentDataStatus.PARTIAL))
        assert "**Data status:** PARTIAL" in md


class TestAnalystNode:
    """End-to-end through the node, with the real prefetch replaced."""

    def _node(self, monkeypatch, blocks, model_report):
        import tradingagents.agents.analysts.sentiment_analyst as mod

        monkeypatch.setattr(mod, "record_prefetch_call",
                            lambda name, fn, *a, **k: blocks[name])

        class _Structured:
            def invoke(self, _prompt):
                return model_report

        class _LLM:
            def with_structured_output(self, _schema):
                return _Structured()

        return create_sentiment_analyst(_LLM())

    def _state(self):
        return {
            "company_of_interest": "NVDA",
            "trade_date": "2026-09-23",
            "messages": [],
        }

    def test_all_unavailable_overrides_model_neutral_five(
        self, monkeypatch
    ):
        # The model still says Neutral 5.0 — exactly what it always did. The
        # node must not let that reach the state.
        node = self._node(
            monkeypatch,
            {"news": ROUTED_NEWS, "stocktwits": COVERAGE_ST, "reddit": COVERAGE_REDDIT},
            _report(overall_band=SentimentBand.NEUTRAL, overall_score=5.0),
        )
        out = node(self._state())["sentiment_report"]
        assert "**Unknown**" in out
        assert "5.0/10" not in out
        assert "**Data status:** UNAVAILABLE" in out
        assert "not Neutral" in out

    def test_bullish_with_real_data_is_preserved(self, monkeypatch):
        node = self._node(
            monkeypatch,
            {"news": REAL_NEWS, "stocktwits": REAL_ST, "reddit": REAL_REDDIT},
            _report(overall_band=SentimentBand.BULLISH, overall_score=8.0),
        )
        out = node(self._state())["sentiment_report"]
        assert "**Bullish**" in out
        assert "8.0/10" in out

    def test_bearish_with_real_data_is_preserved(self, monkeypatch):
        node = self._node(
            monkeypatch,
            {"news": REAL_NEWS, "stocktwits": REAL_ST, "reddit": REAL_REDDIT},
            _report(overall_band=SentimentBand.BEARISH, overall_score=2.0),
        )
        assert "2.0/10" in node(self._state())["sentiment_report"]

    def test_partial_keeps_model_reading(self, monkeypatch):
        # One real source is still a measurement; the model's band stands.
        node = self._node(
            monkeypatch,
            {"news": ROUTED_NEWS, "stocktwits": REAL_ST, "reddit": COVERAGE_REDDIT},
            _report(overall_band=SentimentBand.MILDLY_BULLISH, overall_score=6.0),
        )
        out = node(self._state())["sentiment_report"]
        assert "Mildly Bullish" in out
        assert "6.0/10" in out

    def test_freetext_fallback_cannot_emit_neutral_five(self, monkeypatch):
        import tradingagents.agents.analysts.sentiment_analyst as mod
        monkeypatch.setattr(mod, "record_prefetch_call",
                            lambda name, fn, *a, **k: {"news": ROUTED_NEWS,
                                                       "stocktwits": COVERAGE_ST,
                                                       "reddit": COVERAGE_REDDIT}[name])

        class _LLM:
            def with_structured_output(self, _schema):
                raise NotImplementedError

            def invoke(self, _prompt):
                return AIMessage(
                    content="**Overall Sentiment:** **Neutral** (Score: 5.0/10)\nbody"
                )

        node = create_sentiment_analyst(_LLM())
        out = node(self._state())["sentiment_report"]
        # The model's own header survives inside the prose, but the authoritative
        # header comes first and says Unknown, so a reader or parser that takes
        # the first line cannot see 5.0.
        assert out.startswith("**Overall Sentiment:** **Unknown**")
        assert "not Neutral" in out


class TestDownstream:
    def test_unknown_is_not_neutral_to_researchers(self):
        from tradingagents.agents.utils.agent_utils import report_or_absent
        text = render_sentiment_report(
            _report(overall_band=SentimentBand.UNKNOWN, overall_score=None,
                    data_status=SentimentDataStatus.UNAVAILABLE)
        )
        passed = report_or_absent(text, "sentiment")
        assert "Unknown" in passed
        assert "Neutral" not in passed
        assert "5.0" not in passed

    def test_schema_rejects_out_of_range_score(self):
        with pytest.raises(Exception):
            SentimentReport(
                overall_band=SentimentBand.BULLISH, overall_score=11.0,
                confidence="low", narrative="x",
            )

    def test_unknown_band_is_a_valid_enum_member(self):
        assert SentimentBand("Unknown") is SentimentBand.UNKNOWN
