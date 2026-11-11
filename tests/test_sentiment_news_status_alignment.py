"""Regression tests: sentiment must read NEWS_STATUS the way news does, and a
failed news prefetch must not crash the node.

Two defects closed in campaign 20260808/final_quality_closure:

1. **Classifier asymmetry.** ``classify_news_source_availability`` rejects a
   ``NEWS_STATUS=EMPTY_VALID`` result (the vendor answered and had no
   articles), but ``_classify_sentiment_source`` matched no marker for it and
   fell through to AVAILABLE. The same string was "no company news" for the
   News Analyst and "real sentiment data" for the Sentiment Analyst, so an
   empty news window could still carry a scored sentiment band.

2. **D-5 crash.** ``news_data`` is a core category, so ``route_to_vendor``
   re-raises an *untyped* vendor exception and ``record_prefetch_call``
   re-raises again, aborting the sentiment node. ``_prefetch_or_degrade``
   converts that residual case into a visible sentinel.
"""

from __future__ import annotations

import pytest

from tradingagents.agents.analysts.sentiment_analyst import create_sentiment_analyst
from tradingagents.agents.schemas import (
    SentimentBand,
    SentimentDataStatus,
    SentimentReport,
    _classify_sentiment_source,
    classify_sentiment_sources,
)

NEWS_EMPTY_VALID = (
    "NEWS_STATUS=EMPTY_VALID: no articles about NVDA were published between "
    "2026-09-16 and 2026-09-23 - the vendor answered and had no articles in "
    "this window. This is a real absence: do not infer that the instrument is "
    "quiet in any particular direction."
)
NEWS_SUCCESS = (
    "NEWS_STATUS=SUCCESS_REAL_CONTENT\n\n"
    "### Nvidia ships new accelerator (source: Reuters)\n"
    "https://example.com/a\nPublished 2026-09-22"
)
REAL_ST = "Bullish: 18 (60%) - Bearish: 4 (13%) - Total: 30 most-recent messages"
REAL_REDDIT = "r/wallstreetbets - 12 recent posts mentioning NVDA"


class TestClassifierAlignment:
    def test_empty_valid_is_not_available(self):
        assert _classify_sentiment_source(NEWS_EMPTY_VALID) is not SentimentDataStatus.AVAILABLE

    def test_every_failure_status_is_not_available(self):
        for status in (
            "EMPTY_VALID",
            "OUT_OF_WINDOW",
            "RATE_LIMITED",
            "TIMEOUT",
            "PARSE_ERROR",
            "PROVIDER_UNAVAILABLE",
            "AUTH_INVALID",
        ):
            text = f"NEWS_STATUS={status}: something"
            assert _classify_sentiment_source(text) is not SentimentDataStatus.AVAILABLE, status

    def test_success_status_with_article_is_available(self):
        assert _classify_sentiment_source(NEWS_SUCCESS) is SentimentDataStatus.AVAILABLE

    def test_real_news_without_status_token_is_still_available(self):
        text = "## NVDA News\n\n### Nvidia ships x (source: Reuters)"
        assert _classify_sentiment_source(text) is SentimentDataStatus.AVAILABLE

    def test_empty_news_with_two_real_sources_is_partial_not_available(self):
        verdict = classify_sentiment_sources(NEWS_EMPTY_VALID, REAL_ST, REAL_REDDIT)
        assert verdict is not SentimentDataStatus.AVAILABLE
        assert verdict is SentimentDataStatus.PARTIAL

    def test_empty_news_alone_is_unavailable(self):
        verdict = classify_sentiment_sources(NEWS_EMPTY_VALID, "", "")
        assert verdict is SentimentDataStatus.UNAVAILABLE


def _report():
    return SentimentReport(
        overall_band=SentimentBand.NEUTRAL,
        overall_score=5.0,
        confidence="low",
        narrative="body",
    )


class TestPrefetchDegradesInsteadOfCrashing:
    def _node(self, monkeypatch, news_behavior):
        import tradingagents.agents.analysts.sentiment_analyst as mod

        def fake_prefetch(name, fn, *a, **k):
            if name == "news":
                return news_behavior()
            if name == "stocktwits":
                return REAL_ST
            return REAL_REDDIT

        monkeypatch.setattr(mod, "record_prefetch_call", fake_prefetch)
        captured = {}

        class _Structured:
            def invoke(self, prompt):
                captured["prompt"] = prompt
                return _report()

        class _LLM:
            def with_structured_output(self, _schema):
                return _Structured()

        return create_sentiment_analyst(_LLM()), captured

    def _state(self):
        return {
            "company_of_interest": "NVDA",
            "trade_date": "2026-09-23",
            "messages": [],
        }

    def test_untyped_news_exception_does_not_abort_the_node(self, monkeypatch):
        def boom():
            raise RuntimeError("untyped vendor blowup")

        node, captured = self._node(monkeypatch, boom)
        # Must not raise: D-5 is exactly the crash this replaces.
        result = node(self._state())
        report = result["sentiment_report"]
        assert isinstance(report, str) and report.strip()
        # The failure stays visible to the model as a sentinel, not as silence.
        prompt_text = str(captured.get("prompt", ""))
        assert "DATA_UNAVAILABLE" in prompt_text
        assert "RuntimeError" in prompt_text

    def test_degraded_news_is_not_counted_as_real_data(self, monkeypatch):
        def boom():
            raise RuntimeError("untyped vendor blowup")

        node, _captured = self._node(monkeypatch, boom)
        report = node(self._state())["sentiment_report"]
        # news is unavailable, ST + Reddit are real -> PARTIAL, never AVAILABLE
        assert "**Data status:** AVAILABLE" not in report
        assert "**Data status:** PARTIAL" in report

    def test_the_node_still_works_when_news_succeeds(self, monkeypatch):
        node, captured = self._node(monkeypatch, lambda: NEWS_SUCCESS)
        report = node(self._state())["sentiment_report"]
        assert isinstance(report, str) and report.strip()
        assert "RuntimeError" not in str(captured.get("prompt", ""))
