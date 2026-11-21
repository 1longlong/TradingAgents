"""StockTwits response-shape validation and the sentiment pre-fetch contract.

A response that cannot be read as the documented payload is reported for the
whole fetch: ``<stocktwits unavailable: ...>`` with a safe reason code. It is
never turned into "no discussion", never trimmed to its readable records, and
never used for a sentiment ratio. Well-shaped payloads (including the existing
optional fields) keep their previous behaviour, and a valid but empty stream
still goes through the window-coverage judgement.

The sentiment node's news pre-fetch passes the run date explicitly and keeps the
news error contract: only StockTwits/Reddit degrade; news errors propagate.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from tradingagents.agents.analysts import sentiment_analyst
from tradingagents.agents.schemas import SentimentReport
from tradingagents.dataflows import stocktwits

WINDOW = {"start_date": "2026-05-01", "end_date": "2026-05-08"}


class _JsonResp:
    """Minimal urlopen() context-manager stub returning a JSON body."""

    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body


def _serve(monkeypatch, payload):
    monkeypatch.setattr(stocktwits, "urlopen", lambda *a, **k: _JsonResp(payload))


def _msg(created="2026-05-05T12:00:00Z", sentiment="Bullish", body="text", user="u"):
    return {
        "created_at": created,
        "user": {"username": user},
        "entities": {"sentiment": {"basic": sentiment}} if sentiment is not None else None,
        "body": body,
    }


def _fetch(**kwargs):
    return stocktwits.fetch_stocktwits_messages("AAPL", **{**WINDOW, **kwargs})


# --- rejected shapes: unavailable, never silence, never a ratio -------------

@pytest.mark.unit
@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"messages": "not-a-list"}, "messages_not_list"),
        ({"messages": {"a": 1}}, "messages_not_list"),
        ({"messages": None}, None),
        ({"messages": []}, None),
    ],
    ids=["messages-str", "messages-dict", "messages-none", "messages-empty"],
)
def test_messages_field_must_be_a_list(monkeypatch, payload, reason):
    _serve(monkeypatch, payload)
    out = _fetch()
    if reason is None:
        # Existing optional/empty behaviour is unchanged.
        assert "messages_not_list" not in out
        assert "<no StockTwits messages" in out or "unavailable" in out
    else:
        assert out == f"<stocktwits unavailable: {reason}>"
        assert "no StockTwits messages" not in out
        assert "Bullish:" not in out  # no ratio computed


@pytest.mark.unit
@pytest.mark.parametrize(
    "payload",
    [[], "oops", 42],
    ids=["top-level-list", "top-level-str", "top-level-int"],
)
def test_top_level_must_be_an_object(monkeypatch, payload):
    _serve(monkeypatch, payload)
    out = _fetch()
    assert out == "<stocktwits unavailable: top_level_not_object>"
    assert "no StockTwits messages" not in out


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad_entry",
    ["oops", 1, None, ["x"]],
    ids=["str", "int", "null", "list"],
)
def test_non_object_entry_rejects_whole_response(monkeypatch, bad_entry):
    _serve(monkeypatch, {"messages": [_msg(), bad_entry, _msg()]})
    out = _fetch()
    assert out == "<stocktwits unavailable: entry_not_object>"
    # The good neighbours must not be rendered as the complete result.
    assert "Bullish: 2" not in out
    assert "Total:" not in out


@pytest.mark.unit
@pytest.mark.parametrize(
    ("entry", "reason"),
    [
        ({**_msg(), "user": "alice"}, "user_not_object"),
        ({**_msg(), "user": ["alice"]}, "user_not_object"),
        ({**_msg(), "user": {"username": 7}}, "user_username_not_string"),
        ({**_msg(), "entities": "Bullish"}, "entities_not_object"),
        ({**_msg(), "entities": {"sentiment": "Bullish"}}, "entities_sentiment_not_object"),
        ({**_msg(), "entities": {"sentiment": {"basic": 1}}}, "sentiment_basic_not_string"),
        ({**_msg(), "created_at": 12345}, "created_at_not_string"),
        ({**_msg(), "body": {"text": "x"}}, "body_not_string"),
        ({**_msg(), "body": ["x"]}, "body_not_string"),
    ],
    ids=[
        "user-str", "user-list", "username-int", "entities-str", "sentiment-str",
        "sentiment-basic-int", "created-at-int", "body-dict", "body-list",
    ],
)
def test_nested_field_with_wrong_type_rejects_whole_response(monkeypatch, entry, reason):
    _serve(monkeypatch, {"messages": [entry]})
    out = _fetch()
    assert out == f"<stocktwits unavailable: {reason}>"
    assert "Total:" not in out


# --- compatible shapes: unchanged behaviour --------------------------------

@pytest.mark.unit
def test_valid_messages_render_and_ratio(monkeypatch):
    _serve(monkeypatch, {"messages": [
        _msg(sentiment="Bullish"), _msg(sentiment="Bearish"), _msg(sentiment=None),
    ]})
    out = _fetch()
    assert "Bullish: 1 (33%)" in out
    assert "Bearish: 1 (33%)" in out
    assert "Unlabeled: 1" in out
    assert "Total: 3" in out


@pytest.mark.unit
@pytest.mark.parametrize(
    "entry",
    [
        _msg(sentiment=None),
        {**_msg(), "entities": {}},
        {**_msg(), "entities": {"sentiment": None}},
        {**_msg(), "user": {}},
        {**_msg(), "user": None},
        {**_msg(), "body": None},
        {**_msg(), "body": ""},
        _msg(body="kept"),  # body present: the message survives the window
    ],
    ids=[
        "null-entities", "empty-entities", "null-sentiment", "empty-user",
        "null-user", "null-body", "empty-body", "baseline",
    ],
)
def test_optional_and_empty_fields_stay_compatible(monkeypatch, entry):
    _serve(monkeypatch, {"messages": [entry]})
    out = _fetch()
    assert "unavailable" not in out
    assert "Total: 1" in out


@pytest.mark.unit
def test_valid_empty_stream_keeps_window_coverage_judgement(monkeypatch):
    # Unchanged semantics: an empty (well-shaped) stream over a past window is
    # a coverage gap, not a shape rejection.
    _serve(monkeypatch, {"messages": []})
    out = _fetch()
    assert "unavailable" in out and "not an absence" in out
    assert "messages_not_list" not in out and "top_level_not_object" not in out


@pytest.mark.unit
def test_valid_empty_stream_without_window_is_silence(monkeypatch):
    _serve(monkeypatch, {"messages": []})
    out = stocktwits.fetch_stocktwits_messages("AAPL")
    assert out.startswith("<no StockTwits messages found")


# --- logs carry reason codes only ------------------------------------------

@pytest.mark.unit
def test_log_carries_reason_code_not_payload(monkeypatch, caplog):
    with caplog.at_level("WARNING", logger=stocktwits.logger.name):
        _serve(monkeypatch, {"messages": "secret-body"})
        _fetch()
    assert "messages_not_list" in caplog.text
    assert "secret-body" not in caplog.text


# --- the sentiment node's pre-fetch contract -------------------------------

def _state():
    return {
        "company_of_interest": "NVDA",
        "trade_date": "2026-01-15",
        "asset_type": "stock",
        "messages": [],
    }


def _structured_llm():
    structured = MagicMock()
    structured.invoke.return_value = {
        "raw": MagicMock(tool_calls=[]),
        "parsed": SentimentReport(
            overall_band="Neutral", overall_score=5.0,
            confidence="low", narrative="n",
        ),
        "parsing_error": None,
    }
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm, structured


def _stub_social(monkeypatch, stocktwits_out="st", reddit_out="rd"):
    monkeypatch.setattr(sentiment_analyst, "fetch_stocktwits_messages",
                        lambda *a, **k: stocktwits_out)
    monkeypatch.setattr(sentiment_analyst, "fetch_reddit_posts",
                        lambda *a, **k: reddit_out)


@pytest.mark.unit
def test_news_receives_the_run_date_and_window(monkeypatch):
    _stub_social(monkeypatch)
    calls = []
    monkeypatch.setattr(sentiment_analyst.get_news, "func",
                        lambda *a, **k: calls.append((a, k)) or "news", raising=False)
    llm, _ = _structured_llm()
    sentiment_analyst.create_sentiment_analyst(llm)(_state())
    assert calls == [(("NVDA", "2026-01-08", "2026-01-15"), {"trade_date": "2026-01-15"})]


@pytest.mark.unit
def test_news_fatal_error_propagates_and_model_is_not_called(monkeypatch):
    from tradingagents.dataflows.errors import VendorAuthenticationError

    _stub_social(monkeypatch)
    monkeypatch.setattr(sentiment_analyst.get_news, "func",
                        lambda *a, **k: (_ for _ in ()).throw(
                            VendorAuthenticationError("401")), raising=False)
    llm, structured = _structured_llm()
    with pytest.raises(VendorAuthenticationError):
        sentiment_analyst.create_sentiment_analyst(llm)(_state())
    structured.invoke.assert_not_called()
    llm.invoke.assert_not_called()


@pytest.mark.unit
def test_news_unknown_internal_error_propagates(monkeypatch):
    _stub_social(monkeypatch)
    monkeypatch.setattr(sentiment_analyst.get_news, "func",
                        lambda *a, **k: (_ for _ in ()).throw(TypeError("bug")),
                        raising=False)
    llm, _ = _structured_llm()
    with pytest.raises(TypeError):
        sentiment_analyst.create_sentiment_analyst(llm)(_state())


@pytest.mark.unit
def test_news_keyboard_interrupt_is_not_swallowed(monkeypatch):
    _stub_social(monkeypatch)
    monkeypatch.setattr(sentiment_analyst.get_news, "func",
                        lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()),
                        raising=False)
    llm, structured = _structured_llm()
    with pytest.raises(KeyboardInterrupt):
        sentiment_analyst.create_sentiment_analyst(llm)(_state())
    structured.invoke.assert_not_called()


@pytest.mark.unit
def test_stocktwits_keyboard_interrupt_is_not_swallowed(monkeypatch):
    # Only OSError/HTTPException/JSONDecodeError are handled; an interruption
    # during the request keeps propagating out of the fetcher.
    def interrupted(*a, **k):
        raise KeyboardInterrupt()

    monkeypatch.setattr(stocktwits, "urlopen", interrupted)
    with pytest.raises(KeyboardInterrupt):
        stocktwits.fetch_stocktwits_messages("AAPL", **WINDOW)


@pytest.mark.unit
def test_malformed_stocktwits_still_fetches_news_and_calls_the_model(monkeypatch):
    # End-to-end through the node: a malformed StockTwits body degrades inside
    # the fetcher, so news and the model still run.
    monkeypatch.setattr(stocktwits, "urlopen",
                        lambda *a, **k: _JsonResp({"messages": "oops"}))
    monkeypatch.setattr(sentiment_analyst, "fetch_reddit_posts",
                        lambda *a, **k: "rd")
    news_calls = []
    monkeypatch.setattr(sentiment_analyst.get_news, "func",
                        lambda *a, **k: news_calls.append(a) or "NEWS", raising=False)
    llm, structured = _structured_llm()
    out = sentiment_analyst.create_sentiment_analyst(llm)(_state())
    assert out["sentiment_report"]
    assert news_calls  # news still fetched
    prompt = structured.invoke.call_args.args[0]
    assert "stocktwits unavailable: messages_not_list" in str(prompt)


@pytest.mark.unit
def test_unavailable_stocktwits_does_not_block_reddit(monkeypatch):
    """When StockTwits is unavailable, Reddit is still fetched and reaches the prompt."""
    monkeypatch.setattr(stocktwits, "urlopen",
                        lambda *a, **k: _JsonResp({"messages": "oops"}))
    reddit_calls = []

    def fake_reddit(*a, **k):
        reddit_calls.append((a, k))
        return "REDDIT-BLOCK"

    monkeypatch.setattr(sentiment_analyst, "fetch_reddit_posts", fake_reddit)
    monkeypatch.setattr(sentiment_analyst.get_news, "func",
                        lambda *a, **k: "NEWS", raising=False)
    llm, structured = _structured_llm()
    sentiment_analyst.create_sentiment_analyst(llm)(_state())
    assert len(reddit_calls) == 1
    prompt = str(structured.invoke.call_args.args[0])
    assert "REDDIT-BLOCK" in prompt
    assert "stocktwits unavailable: messages_not_list" in prompt
