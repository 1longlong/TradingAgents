"""Offline tests for the opt-in sentiment prefetch split.

The suite drives the **real** sentiment slice of the graph -- the prefetch
node, the sentiment analyst, the msg-clear node and the downstream edge, or
the ``GraphSetup`` shape itself -- on a scripted model. The three source
fetchers (news router, StockTwits, Reddit) are patched, so no network, vendor
or real LLM is involved.

Covered:

* the switch is strictly boolean, defaults off, and leaves the original
  one-node path (``create_sentiment_analyst(llm)`` included) unchanged;
* the normal split path fetches each source exactly once, the generation node
  fetches nothing, and prefetch writes only ``sentiment_inputs``;
* generation judges the saved input against the current run's config
  (``state["run_config"]``), not the global config and not the saved identity:
  a run-config change is refused before the model, an unrelated global change
  is ignored, and a resumed checkpoint keeps its own run config;
* a **real** checkpoint taken after the prefetch saved its input and before
  the model raised is resumed by a fresh graph: the model succeeds and the
  three sources are still fetched exactly once in total;
* a changed ticker / date window / run_id / source parameter makes the saved
  input unusable (it is neither consumed nor re-fetched);
* a missing, partial or wrong-version input fails before the model runs;
* an ``<... unavailable ...>`` placeholder is saved and resumed verbatim;
* the prefetch fetches and labels under one context-local config snapshot:
  a concurrent ``set_config`` neither changes the request nor is overwritten,
  two interleaved snapshots never share values, and the snapshot is released
  on a normal return, an exception and a cancellation; the saved vendor chain
  comes from the same snapshot as the fetch;
* a fatal prefetch error never reaches the model; cancellation/interrupts
  propagate;
* ``social`` is entered through its prefetch node first and mid-plan, and the
  other analysts are unchanged.
"""

from __future__ import annotations

import copy
import json
import tempfile
from unittest.mock import MagicMock

import pytest
from langgraph.graph import END, START, StateGraph

from tradingagents.agents.analysts import sentiment_analyst as sentiment
from tradingagents.agents.schemas import SentimentBand, SentimentReport
from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.agents.utils.agent_utils import create_msg_delete
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.errors import VendorAuthenticationError
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph import sentiment_prefetch as sp
from tradingagents.graph.checkpointer import checkpoint_step, get_checkpointer, thread_id
from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.setup import GraphSetup
from tradingagents.graph.trading_graph import TradingAgentsGraph

TRADE_DATE = "2026-08-14"
START_DATE = "2026-08-07"
PREFETCH_NODE = sp.PREFETCH_NODE
ANALYST_NODE = "Sentiment Analyst"


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


class _ScriptedModel:
    """A minimal chat model: ``with_structured_output`` returns the model and
    ``invoke`` returns a :class:`SentimentReport`, recording every invocation.

    ``fail_first`` makes the first ``invoke`` raise (the model failure the
    resume path recovers from); later invocations succeed.
    """

    def __init__(self, narrative="REPORT from the model"):
        self.narrative = narrative
        self.invocations = 0
        self.fail_first = False
        self.error = None  # exception instance used when failing
        self.sent = []

    def with_structured_output(self, schema, **kwargs):
        return self

    def invoke(self, messages, **kwargs):
        self.invocations += 1
        self.sent.append(list(messages))
        if self.fail_first and self.invocations == 1:
            error = self.error or RuntimeError("model exploded")
            self.fail_first = False
            raise error
        return SentimentReport(
            overall_band=SentimentBand.NEUTRAL,
            overall_score=5.0,
            confidence="low",
            narrative=self.narrative,
        )

    @property
    def calls(self):
        return self.invocations


class _Sources:
    """Patched source fetchers that record every call."""

    def __init__(self, news="NEWS BLOCK", stocktwits="ST BLOCK", reddit="REDDIT BLOCK"):
        self.news = news
        self.stocktwits = stocktwits
        self.reddit = reddit
        self.news_calls = []
        self.stocktwits_calls = []
        self.reddit_calls = []
        self.news_error = None
        self.stocktwits_error = None
        self.reddit_error = None

    def _news(self, *args, **kwargs):
        self.news_calls.append((args, kwargs))
        if self.news_error is not None:
            raise self.news_error
        return self.news

    def _stocktwits(self, *args, **kwargs):
        self.stocktwits_calls.append((args, kwargs))
        if self.stocktwits_error is not None:
            raise self.stocktwits_error
        return self.stocktwits

    def _reddit(self, *args, **kwargs):
        self.reddit_calls.append((args, kwargs))
        if self.reddit_error is not None:
            raise self.reddit_error
        return self.reddit

    def install(self, monkeypatch):
        monkeypatch.setattr(sentiment, "get_news", MagicMock(func=self._news))
        monkeypatch.setattr(sentiment, "fetch_stocktwits_messages", self._stocktwits)
        monkeypatch.setattr(sentiment, "fetch_reddit_posts", self._reddit)

    def counts(self):
        return (
            len(self.news_calls),
            len(self.stocktwits_calls),
            len(self.reddit_calls),
        )


def _config(**overrides):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["data_cache_dir"] = tempfile.mkdtemp()
    cfg["results_dir"] = tempfile.mkdtemp()
    cfg.update(overrides)
    return cfg


def _split_config(**overrides):
    return _config(sentiment_prefetch={"enabled": True}, **overrides)


def _activate(config):
    """Install ``config`` as the global config.

    Used only to set up the *external* config (what other callers see). The
    prefetch itself never writes the global config: it fetches under the
    state's ``run_config`` via a context-local snapshot.
    """
    set_config(config)


@pytest.fixture(autouse=True)
def _restore_live_config():
    yield
    set_config(copy.deepcopy(DEFAULT_CONFIG))


def _initial(cfg, *, ticker="AAPL", run_id="run-test", trade_date=TRADE_DATE):
    return {
        "messages": [("human", ticker)],
        "company_of_interest": ticker,
        "asset_type": "stock",
        "instrument_context": "",
        "trade_date": trade_date,
        "past_context": "",
        "portfolio_context": "",
        "market_report": "",
        "fundamentals_report": "",
        "sentiment_report": "",
        "news_report": "",
        "investment_debate_state": {
            "bull_history": "",
            "bear_history": "",
            "history": "",
            "current_response": "",
            "judge_decision": "",
            "count": 0,
        },
        "risk_debate_state": {
            "aggressive_history": "",
            "conservative_history": "",
            "neutral_history": "",
            "history": "",
            "latest_speaker": "",
            "current_aggressive_response": "",
            "current_conservative_response": "",
            "neutral_current_response": "",
            "judge_decision": "",
            "count": 0,
        },
        "tool_governance": {"run_id": run_id},
        "run_config": cfg,
    }


def _sentiment_slice(model):
    """The real two-node sentiment slice: prefetch -> analyst -> clear -> end."""
    workflow = StateGraph(AgentState)
    workflow.add_node(PREFETCH_NODE, sentiment.create_sentiment_prefetch_node())
    workflow.add_node(ANALYST_NODE, sentiment.create_sentiment_analyst(model, True))
    workflow.add_node("Msg Clear Sentiment", create_msg_delete())
    workflow.add_edge(START, PREFETCH_NODE)
    workflow.add_edge(PREFETCH_NODE, ANALYST_NODE)
    workflow.add_edge(ANALYST_NODE, "Msg Clear Sentiment")
    workflow.add_edge("Msg Clear Sentiment", END)
    return workflow


# ---------------------------------------------------------------------------
# The switch
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_switch_defaults_off():
    assert sp.parse_sentiment_prefetch(None).enabled is False
    assert sp.parse_sentiment_prefetch({}).enabled is False
    assert sp.parse_sentiment_prefetch({"sentiment_prefetch": {}}).enabled is False
    # Default config carries a disabled section.
    assert DEFAULT_CONFIG["sentiment_prefetch"] == {"enabled": False}


@pytest.mark.unit
@pytest.mark.parametrize(
    "section",
    [
        True,
        {"enabled": "yes"},
        {"enabled": 1},
        {"enabled": None},
        {"enabled": True, "typo": 1},
        {"enabled": True, "max_rounds": 2},
    ],
)
def test_switch_is_strictly_boolean(section):
    with pytest.raises(ValueError):
        sp.parse_sentiment_prefetch({"sentiment_prefetch": section})


@pytest.mark.unit
def test_switch_on_is_read():
    assert sp.parse_sentiment_prefetch(
        {"sentiment_prefetch": {"enabled": True}}
    ).enabled is True


@pytest.mark.unit
@pytest.mark.parametrize("raw,expected", [
    ("true", True), ("1", True), ("false", False), ("off", False),
])
def test_switch_is_env_configurable(monkeypatch, raw, expected):
    import importlib

    import tradingagents.default_config as dc

    monkeypatch.setenv("TRADINGAGENTS_SENTIMENT_PREFETCH_ENABLED", raw)
    reloaded = importlib.reload(dc)
    try:
        assert reloaded.DEFAULT_CONFIG["sentiment_prefetch"] == {"enabled": expected}
    finally:
        monkeypatch.delenv("TRADINGAGENTS_SENTIMENT_PREFETCH_ENABLED", raising=False)
        importlib.reload(dc)


# ---------------------------------------------------------------------------
# Off: the original single-node path
# ---------------------------------------------------------------------------


ALL_TOOLS = {key: MagicMock() for key in ("market", "social", "news", "fundamentals")}


def _setup(cfg):
    quick = _ScriptedModel()
    return GraphSetup(
        quick,
        _ScriptedModel(),
        dict(ALL_TOOLS),
        ConditionalLogic(),
        config=cfg,
    ), quick


@pytest.mark.unit
def test_off_keeps_the_single_node_graph():
    cfg = _config(sentiment_prefetch={"enabled": False})
    setup, _ = _setup(cfg)
    workflow = setup.setup_graph(("social",))
    assert PREFETCH_NODE not in workflow.nodes
    edges = _edges(workflow)
    assert ("START", ANALYST_NODE) in edges
    # The analyst keeps its original tool/clear routing.
    assert ("tools_social", ANALYST_NODE) in edges
    assert ("Msg Clear Sentiment", "Bull Researcher") in edges


@pytest.mark.unit
def test_off_keeps_create_sentiment_analyst_compatible(monkeypatch):
    """The legacy factory fetches all three itself, exactly as before."""
    sources = _Sources()
    sources.install(monkeypatch)
    model = _ScriptedModel()
    node = sentiment.create_sentiment_analyst(model)  # no prefetch_split kwarg
    out = node(_initial(_config()))

    assert set(out) == {"messages", "sentiment_report"}
    assert "REPORT from the model" in out["sentiment_report"]
    assert sources.counts() == (1, 1, 1)
    assert sources.news_calls[0] == (("AAPL", START_DATE, TRADE_DATE),
                                     {"trade_date": TRADE_DATE})
    assert sources.stocktwits_calls[0][0] == ("AAPL",)
    assert sources.stocktwits_calls[0][1] == {
        "limit": 30, "start_date": START_DATE, "end_date": TRADE_DATE}


@pytest.mark.unit
def test_other_switches_alone_do_not_split_sentiment():
    cfg = _config(news_tool_governance={"enabled": True})
    setup, _ = _setup(cfg)
    workflow = setup.setup_graph(("news", "social"))
    assert PREFETCH_NODE not in workflow.nodes


# ---------------------------------------------------------------------------
# Normal split path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_split_node_fetches_once_and_writes_only_sentiment_inputs(monkeypatch):
    sources = _Sources(news="NEWS", stocktwits="<stocktwits unavailable: X>",
                       reddit="REDDIT")
    sources.install(monkeypatch)
    prefetch = sentiment.create_sentiment_prefetch_node()
    state = _initial(_split_config())
    update = prefetch(state)

    assert set(update) == {sp.STATE_KEY}
    assert update[sp.STATE_KEY]["blocks"] == {
        "news": "NEWS",
        "stocktwits": "<stocktwits unavailable: X>",
        "reddit": "REDDIT",
    }
    identity = update[sp.STATE_KEY]["identity"]
    assert identity["schema_version"] == sp.SCHEMA_VERSION
    assert identity["run_id"] == "run-test"
    assert identity["analyst"] == "social"
    assert identity["ticker"] == "AAPL"
    assert identity["asset_type"] == "stock"
    assert identity["start_date"] == START_DATE
    assert identity["end_date"] == TRADE_DATE
    assert identity["stocktwits_limit"] == 30
    assert identity["news_article_limit"] == DEFAULT_CONFIG["news_article_limit"]
    assert "news_vendor_chain" in identity
    assert identity["stocktwits_vendor"] == "stocktwits"
    assert identity["reddit_vendor"] == "reddit"
    # Plain, serializable data only.
    json.dumps(update[sp.STATE_KEY])
    # Same three calls, same window as the single-node path.
    assert sources.counts() == (1, 1, 1)
    assert sources.news_calls[0][0] == ("AAPL", START_DATE, TRADE_DATE)


@pytest.mark.unit
def test_generation_node_consumes_saved_input_and_never_fetches(monkeypatch):
    base = _initial(_split_config())
    # The saved input is produced by the prefetch node itself, not hand-built.
    sources = _Sources(news="SAVED NEWS", stocktwits="SAVED ST", reddit="SAVED RD")
    sources.install(monkeypatch)
    saved = _saved_for(base)
    state = {**base, **saved}

    model = _ScriptedModel()
    node = sentiment.create_sentiment_analyst(model, prefetch_split=True)
    out = node(state)

    assert "REPORT from the model" in out["sentiment_report"]
    assert model.calls == 1
    assert sources.counts() == (1, 1, 1), "only the prefetch node fetched"
    prompt = str(model.sent[0])
    assert "SAVED NEWS" in prompt and "SAVED ST" in prompt
    assert "SAVED RD" in prompt


@pytest.mark.unit
def test_split_run_fetches_each_source_once(monkeypatch):
    sources = _Sources()
    sources.install(monkeypatch)
    model = _ScriptedModel()
    _activate(_split_config())
    out = _sentiment_slice(model).compile().invoke(
        _initial(_split_config()), {"recursion_limit": 20})

    assert sources.counts() == (1, 1, 1)
    assert model.calls == 1
    assert "REPORT from the model" in out["sentiment_report"]
    assert out[sp.STATE_KEY]["blocks"]["news"] == "NEWS BLOCK"
    # The prompt was built from the saved blocks.
    prompt = str(model.sent[0])
    assert "NEWS BLOCK" in prompt and "ST BLOCK" in prompt and "REDDIT BLOCK" in prompt


@pytest.mark.unit
def test_saved_input_excludes_config_credentials(monkeypatch):
    sources = _Sources()
    sources.install(monkeypatch)
    cfg = _split_config(alpha_vantage_api_key="SECRET-KEY",
                        data_vendors={"news_data": "yfinance"})
    update = _saved_for(_initial(cfg))
    serialized = json.dumps(update[sp.STATE_KEY])
    assert "SECRET-KEY" not in serialized
    assert update[sp.STATE_KEY]["identity"]["news_vendor_chain"] == ("yfinance",)


# ---------------------------------------------------------------------------
# Identity mismatches: the old input is never consumed
# ---------------------------------------------------------------------------


def _saved_for(state):
    """Run the real prefetch node for ``state`` and return its update.

    The node fetches under ``state["run_config"]`` through a context-local
    snapshot; the global config is left alone.
    """
    return sentiment.create_sentiment_prefetch_node()(state)


def _state_with_saved(saved, base, **overrides):
    merged = {**base, **saved, **overrides}
    return merged


@pytest.mark.unit
def test_ticker_change_is_refused_not_refetched(monkeypatch):
    sources = _Sources()
    sources.install(monkeypatch)
    base = _initial(_split_config())
    saved = _saved_for(base)
    other = {**base, "company_of_interest": "MSFT"}
    model = _ScriptedModel()
    with pytest.raises(sp.SentimentInputError, match="ticker"):
        sentiment.create_sentiment_analyst(model, True)(_state_with_saved(saved, other))
    assert model.calls == 0
    assert sources.counts() == (1, 1, 1)


@pytest.mark.unit
def test_date_change_is_refused(monkeypatch):
    sources = _Sources()
    sources.install(monkeypatch)
    base = _initial(_split_config())
    saved = _saved_for(base)
    other = {**base, "trade_date": "2026-08-13"}
    model = _ScriptedModel()
    with pytest.raises(sp.SentimentInputError, match="start_date|end_date"):
        sentiment.create_sentiment_analyst(model, True)(_state_with_saved(saved, other))
    assert model.calls == 0
    assert sources.counts() == (1, 1, 1)


@pytest.mark.unit
def test_run_id_change_is_refused(monkeypatch):
    sources = _Sources()
    sources.install(monkeypatch)
    base = _initial(_split_config())
    saved = _saved_for(base)
    other = {**base, "tool_governance": {"run_id": "run-other"}}
    model = _ScriptedModel()
    with pytest.raises(sp.SentimentInputError, match="run_id"):
        sentiment.create_sentiment_analyst(model, True)(_state_with_saved(saved, other))
    assert model.calls == 0


@pytest.mark.unit
@pytest.mark.parametrize(
    "identity,field",
    [
        ({"news_vendor_chain": ["alpha_vantage"]}, "news_vendor_chain"),
        ({"stocktwits_limit": 5}, "stocktwits_limit"),
        ({"reddit_vendor": "other"}, "reddit_vendor"),
    ],
)
def test_source_parameter_change_is_refused(monkeypatch, identity, field):
    sources = _Sources()
    sources.install(monkeypatch)
    base = _initial(_split_config())
    saved = _saved_for(base)
    changed = copy.deepcopy(saved)
    changed[sp.STATE_KEY]["identity"].update(identity)
    model = _ScriptedModel()
    with pytest.raises(sp.SentimentInputError, match=field):
        sentiment.create_sentiment_analyst(model, True)({**base, **changed})
    assert model.calls == 0
    assert sources.counts() == (1, 1, 1)


# ---------------------------------------------------------------------------
# news_article_limit is part of the input identity
# ---------------------------------------------------------------------------


def _news_article_limit_now():
    from tradingagents.dataflows.config import get_config

    return get_config()["news_article_limit"]


class _NewsVendor:
    """The vendor seam the real ``get_news`` tool body calls.

    ``route_to_vendor`` is patched in ``news_data_tools`` so the real tool body
    runs (``as_of_window`` + method dispatch) and only the vendor boundary is
    faked. ``asked`` records the ``count`` the vendor implementation received,
    read from the live config the way both news vendors read it.
    """

    def __init__(self):
        self.asked = []

    def route(self, method, ticker, start_date, end_date):
        assert method == "get_news"
        count = _news_article_limit_now()
        self.asked.append((ticker, start_date, end_date, count))
        return f"NEWS[{count}]"

    def counts(self):
        return len(self.asked)


@pytest.mark.unit
def test_article_limit_unchanged_roundtrip_and_resume(monkeypatch):
    cfg = _split_config(news_article_limit=100)
    sources = _Sources()
    sources.install(monkeypatch)
    base = _initial(cfg)
    saved = _saved_for(base)
    _activate(cfg)

    identity = saved[sp.STATE_KEY]["identity"]
    assert identity["news_article_limit"] == 100

    # The saved value survives a JSON round trip.
    roundtripped = json.loads(json.dumps(saved))
    assert roundtripped[sp.STATE_KEY]["identity"]["news_article_limit"] == 100

    model = _ScriptedModel()
    out = sentiment.create_sentiment_analyst(model, True)({**base, **roundtripped})
    assert "REPORT from the model" in out["sentiment_report"]
    assert model.calls == 1
    assert sources.counts() == (1, 1, 1), "resume consumed the saved text, no refetch"


@pytest.mark.unit
@pytest.mark.parametrize("saved_limit,now_limit", [(100, 1), (1, 100)])
def test_article_limit_change_is_refused_without_fetch(monkeypatch, saved_limit, now_limit):
    cfg = _split_config(news_article_limit=saved_limit)
    sources = _Sources()
    sources.install(monkeypatch)
    base = _initial(cfg)
    saved = _saved_for(base)
    assert saved[sp.STATE_KEY]["identity"]["news_article_limit"] == saved_limit

    # The current *run* config now asks for a different article count. The
    # global config is left as it was: the decision is about this run.
    _activate(cfg)
    changed = {**base, "run_config": {**cfg, "news_article_limit": now_limit}}
    model = _ScriptedModel()
    with pytest.raises(sp.SentimentInputError, match="news_article_limit"):
        sentiment.create_sentiment_analyst(model, True)(_state_with_saved(saved, changed))
    assert model.calls == 0
    assert sources.counts() == (1, 1, 1), "only the prefetch fetched; nothing re-fetched"


@pytest.mark.unit
def test_old_identity_without_article_limit_is_refused(monkeypatch):
    cfg = _split_config(news_article_limit=20)
    sources = _Sources()
    sources.install(monkeypatch)
    base = _initial(cfg)
    saved = _saved_for(base)
    old = copy.deepcopy(saved)
    old[sp.STATE_KEY]["identity"].pop("news_article_limit")  # pre-fix identity

    _activate(cfg)
    model = _ScriptedModel()
    with pytest.raises(sp.SentimentInputError, match="news_article_limit"):
        sentiment.create_sentiment_analyst(model, True)({**base, **old})
    assert model.calls == 0
    assert sources.counts() == (1, 1, 1)


@pytest.mark.unit
def test_recorded_article_limit_matches_the_vendor_count(monkeypatch):
    """The identity's count is the count the vendor actually received.

    The real ``get_news`` tool body runs; only its vendor seam is faked. The
    run config asks for 100, so the vendor is asked for 100 -- and the
    identity says 100. A resume whose run config asks for 1 is refused.
    """
    cfg = _split_config(news_article_limit=100)
    monkeypatch.setattr(sentiment, "fetch_stocktwits_messages", lambda *a, **k: "ST")
    monkeypatch.setattr(sentiment, "fetch_reddit_posts", lambda *a, **k: "RD")
    vendor = _NewsVendor()
    monkeypatch.setattr(
        "tradingagents.agents.utils.news_data_tools.route_to_vendor", vendor.route
    )

    base = _initial(cfg)
    _activate(cfg)
    saved = sentiment.create_sentiment_prefetch_node()(base)

    assert vendor.counts() == 1
    assert saved[sp.STATE_KEY]["identity"]["news_article_limit"] == 100
    # The vendor saw exactly the recorded article count.
    assert saved[sp.STATE_KEY]["blocks"]["news"] == "NEWS[100]"

    # Same limit: consumed.
    model = _ScriptedModel()
    sentiment.create_sentiment_analyst(model, True)({**base, **saved})
    assert model.calls == 1

    # Different limit in the current run: refused before the model, and the
    # vendor is not called again. The global config still says 100.
    changed = {**base, "run_config": {**cfg, "news_article_limit": 1}}
    _activate(cfg)
    model = _ScriptedModel()
    with pytest.raises(sp.SentimentInputError, match="news_article_limit"):
        sentiment.create_sentiment_analyst(model, True)(_state_with_saved(saved, changed))
    assert model.calls == 0
    assert vendor.counts() == 1


@pytest.mark.unit
def test_snapshot_is_not_relabelled_after_the_fetch(monkeypatch):
    """The recorded limit is the one used to fetch, even if the global config
    changes *during* the fetch (the result is never stamped from a later read).

    The global config is left at 1 before the prefetch starts; the prefetch
    fetches under its run's snapshot (100), so the vendor is asked for 100 and
    the identity says 100. Nothing global was pinned or restored.
    """
    cfg = _split_config(news_article_limit=100)
    monkeypatch.setattr(sentiment, "fetch_reddit_posts", lambda *a, **k: "RD")
    vendor = _NewsVendor()

    def mutating_stocktwits(*args, **kwargs):
        # Someone else updates the global config while the prefetch runs.
        set_config({**cfg, "news_article_limit": 1})
        return "ST"

    monkeypatch.setattr(sentiment, "fetch_stocktwits_messages", mutating_stocktwits)
    monkeypatch.setattr(
        "tradingagents.agents.utils.news_data_tools.route_to_vendor", vendor.route
    )
    base = _initial(cfg)
    _activate({**cfg, "news_article_limit": 1})

    saved = sentiment.create_sentiment_prefetch_node()(base)

    assert vendor.counts() == 1
    assert vendor.asked[0][3] == 100, "the vendor was asked for the snapshot's count"
    assert saved[sp.STATE_KEY]["identity"]["news_article_limit"] == 100
    assert saved[sp.STATE_KEY]["blocks"]["news"] == "NEWS[100]"
    # The other caller's update is still the global config after the prefetch.
    assert _news_article_limit_now() == 1


# ---------------------------------------------------------------------------
# The snapshot is context-local: no global writes, no leakage
# ---------------------------------------------------------------------------


def _news_vendor_chain_now():
    from tradingagents.dataflows.interface import get_vendor

    return tuple(
        v.strip() for v in str(get_vendor("news_data", "get_news")).split(",")
        if v.strip()
    )


@pytest.mark.unit
def test_config_snapshot_never_writes_the_global_config():
    from tradingagents.dataflows.config import config_snapshot

    _activate({**_split_config(), "news_article_limit": 7})
    with config_snapshot({**_split_config(), "news_article_limit": 99}) as pinned:
        assert pinned["news_article_limit"] == 99
        # The global config is untouched while the snapshot is active.
    assert _news_article_limit_now() == 7


@pytest.mark.unit
def test_snapshot_and_identity_agree_when_global_changes_mid_request(monkeypatch):
    """External config changes after the snapshot, before the vendor reads.

    The vendor reads from the snapshot, so the request and the identity agree;
    the global update survives the prefetch.
    """
    cfg = _split_config(
        news_article_limit=100, data_vendors={"news_data": "yfinance"}
    )
    vendor = _NewsVendor()

    def change_global_then_read(*args, **kwargs):
        # A concurrent caller updates the global config just before the read.
        set_config({**_split_config(news_article_limit=1), "news_article_limit": 1,
                    "data_vendors": {"news_data": "alpha_vantage"}})
        return _NewsVendor.route(vendor, *args, **kwargs)

    monkeypatch.setattr(
        "tradingagents.agents.utils.news_data_tools.route_to_vendor",
        change_global_then_read,
    )
    monkeypatch.setattr(sentiment, "fetch_stocktwits_messages", lambda *a, **k: "ST")
    monkeypatch.setattr(sentiment, "fetch_reddit_posts", lambda *a, **k: "RD")
    base = _initial(cfg)
    _activate({**cfg, "news_article_limit": 1})

    saved = sentiment.create_sentiment_prefetch_node()(base)

    identity = saved[sp.STATE_KEY]["identity"]
    # The request used the snapshot, and so does the identity.
    assert vendor.asked == [("AAPL", START_DATE, TRADE_DATE, 100)]
    assert identity["news_article_limit"] == 100
    assert identity["news_vendor_chain"] == ("yfinance",)
    # The external update was not overwritten by the prefetch.
    assert _news_article_limit_now() == 1
    assert _news_vendor_chain_now() == ("alpha_vantage",)


@pytest.mark.unit
def test_refuses_before_request_when_the_context_snapshot_is_replaced(monkeypatch):
    """A replaced context snapshot fails the prefetch before the vendor call.

    ``refuse_changed_fetch_parameters`` is the guard the prefetch runs before
    it saves: if the context no longer serves the snapshot that fetched, the
    run fails instead of saving a label from a later read.
    """
    from tradingagents.dataflows.config import config_snapshot

    snapshot = sp.FetchSnapshot(
        config={"news_article_limit": 100}, parameters=sp.FetchParameters(100)
    )
    with config_snapshot({"news_article_limit": 1}), pytest.raises(
        sp.SentimentInputError, match="news_article_limit"
    ):
        sp.refuse_changed_fetch_parameters(
            snapshot, sp.current_fetch_parameters()
        )
    # Same snapshot: accepted.
    with config_snapshot(snapshot.config):
        sp.refuse_changed_fetch_parameters(snapshot, sp.current_fetch_parameters())


@pytest.mark.unit
def test_interleaved_snapshots_do_not_share_values():
    """Two live snapshots in different contexts never see each other's config."""
    import threading

    from tradingagents.dataflows.config import config_snapshot

    seen = {}

    def worker(name, limit):
        with config_snapshot({"news_article_limit": limit}):
            barrier.wait(timeout=5)
            seen[name] = _news_article_limit_now()
            barrier.wait(timeout=5)
            seen[name + "-after"] = _news_article_limit_now()

    barrier = threading.Barrier(2)
    threads = [
        threading.Thread(target=worker, args=("a", 100)),
        threading.Thread(target=worker, args=("b", 1)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert seen == {"a": 100, "b": 1, "a-after": 100, "b-after": 1}


@pytest.mark.unit
def test_snapshots_interleaved_in_one_thread_restore_the_outer_one():
    from tradingagents.dataflows.config import config_snapshot

    _activate({**_split_config(), "news_article_limit": 7})
    with config_snapshot({"news_article_limit": 100}):
        assert _news_article_limit_now() == 100
        with config_snapshot({"news_article_limit": 1}):
            assert _news_article_limit_now() == 1
        # The inner snapshot is released; the outer one is back.
        assert _news_article_limit_now() == 100
    assert _news_article_limit_now() == 7


@pytest.mark.unit
@pytest.mark.parametrize("exc", [RuntimeError("boom"), BaseException("cancel")])
def test_snapshot_is_released_on_exception_and_cancellation(exc):
    from tradingagents.dataflows.config import config_snapshot

    _activate({**_split_config(), "news_article_limit": 7})
    with pytest.raises(type(exc)), config_snapshot(
        {**_split_config(), "news_article_limit": 99}
    ):
        assert _news_article_limit_now() == 99
        raise exc
    assert _news_article_limit_now() == 7


@pytest.mark.unit
def test_prefetch_failure_releases_snapshot_and_keeps_global_update(monkeypatch):
    """A failing fetch leaves no snapshot behind and no global write."""
    cfg = _split_config(news_article_limit=100, data_vendors={"news_data": "yfinance"})

    def failing_news(*args, **kwargs):
        set_config({**_split_config(news_article_limit=3), "news_article_limit": 3,
                    "data_vendors": {"news_data": "alpha_vantage"}})
        raise RuntimeError("news exploded")

    monkeypatch.setattr(
        "tradingagents.agents.utils.news_data_tools.route_to_vendor", failing_news
    )
    monkeypatch.setattr(sentiment, "fetch_stocktwits_messages", lambda *a, **k: "ST")
    monkeypatch.setattr(sentiment, "fetch_reddit_posts", lambda *a, **k: "RD")
    base = _initial(cfg)
    _activate({**cfg, "news_article_limit": 1})

    with pytest.raises(RuntimeError, match="news exploded"):
        sentiment.create_sentiment_prefetch_node()(base)

    # No snapshot residue: the next read is the global config again.
    assert _news_article_limit_now() == 3
    assert _news_vendor_chain_now() == ("alpha_vantage",)


@pytest.mark.unit
def test_saved_vendor_chain_comes_from_the_fetch_snapshot(monkeypatch):
    """The chain saved is the one the fetch routed through, not a later read."""
    cfg = _split_config(
        news_article_limit=20, data_vendors={"news_data": "alpha_vantage"}
    )
    monkeypatch.setattr(sentiment, "get_news", MagicMock(func=lambda *a, **k: "NEWS"))
    monkeypatch.setattr(sentiment, "fetch_stocktwits_messages", lambda *a, **k: "ST")
    monkeypatch.setattr(sentiment, "fetch_reddit_posts", lambda *a, **k: "RD")
    base = _initial(cfg)
    # The global config now names a different vendor chain.
    _activate({**cfg, "data_vendors": {"news_data": "yfinance"}})

    saved = sentiment.create_sentiment_prefetch_node()(base)
    assert saved[sp.STATE_KEY]["identity"]["news_vendor_chain"] == ("alpha_vantage",)


# ---------------------------------------------------------------------------
# Generation judges the saved input against the current run's config
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_generation_ignores_a_global_change_when_run_config_matches(monkeypatch):
    """Run config 100, saved 100, global changed to 1: still consumed.

    The global config is what *other* callers see; the run's own config is
    unchanged, so the saved input still matches and nothing is re-fetched.
    """
    cfg = _split_config(news_article_limit=100)
    sources = _Sources()
    sources.install(monkeypatch)
    base = _initial(cfg)
    saved = _saved_for(base)
    assert saved[sp.STATE_KEY]["identity"]["news_article_limit"] == 100

    _activate({**cfg, "news_article_limit": 1})
    model = _ScriptedModel()
    out = sentiment.create_sentiment_analyst(model, True)({**base, **saved})
    assert "REPORT from the model" in out["sentiment_report"]
    assert model.calls == 1
    assert sources.counts() == (1, 1, 1), "no re-fetch on generation"
    # The external update is still the global config afterwards.
    assert _news_article_limit_now() == 1


@pytest.mark.unit
def test_run_config_limit_change_is_refused_before_model(monkeypatch):
    """Run config 100 -> 1 while the global config stays 100: refused.

    The expected value comes from the run's config, so an unchanged global
    config cannot keep a now-incompatible saved input alive.
    """
    cfg = _split_config(news_article_limit=100)
    sources = _Sources()
    sources.install(monkeypatch)
    base = _initial(cfg)
    saved = _saved_for(base)

    _activate(cfg)
    changed = {**base, "run_config": {**cfg, "news_article_limit": 1}}
    model = _ScriptedModel()
    with pytest.raises(sp.SentimentInputError, match="news_article_limit"):
        sentiment.create_sentiment_analyst(model, True)(_state_with_saved(saved, changed))
    assert model.calls == 0
    assert sources.counts() == (1, 1, 1), "only the prefetch fetched"
    assert _news_article_limit_now() == 100


@pytest.mark.unit
def test_run_config_vendor_chain_change_is_refused(monkeypatch):
    """The run config's news chain changed while the global chain stayed: refuse."""
    cfg = _split_config(
        news_article_limit=20, data_vendors={"news_data": "yfinance"}
    )
    sources = _Sources()
    sources.install(monkeypatch)
    base = _initial(cfg)
    saved = _saved_for(base)
    assert saved[sp.STATE_KEY]["identity"]["news_vendor_chain"] == ("yfinance",)

    _activate(cfg)
    changed = {**base, "run_config": {**cfg, "data_vendors": {"news_data": "alpha_vantage"}}}
    model = _ScriptedModel()
    with pytest.raises(sp.SentimentInputError, match="news_vendor_chain"):
        sentiment.create_sentiment_analyst(model, True)(_state_with_saved(saved, changed))
    assert model.calls == 0
    assert sources.counts() == (1, 1, 1)
    assert _news_vendor_chain_now() == ("yfinance",)


@pytest.mark.unit
def test_global_vendor_chain_change_does_not_affect_consumption(monkeypatch):
    """An external global chain change is ignored: the run config is unchanged."""
    cfg = _split_config(
        news_article_limit=20, data_vendors={"news_data": "yfinance"}
    )
    sources = _Sources()
    sources.install(monkeypatch)
    base = _initial(cfg)
    saved = _saved_for(base)

    _activate({**cfg, "data_vendors": {"news_data": "alpha_vantage"}})
    model = _ScriptedModel()
    out = sentiment.create_sentiment_analyst(model, True)({**base, **saved})
    assert "REPORT from the model" in out["sentiment_report"]
    assert model.calls == 1
    assert sources.counts() == (1, 1, 1)
    assert _news_vendor_chain_now() == ("alpha_vantage",)


@pytest.mark.unit
def test_generation_does_not_derive_expectations_from_the_saved_identity(monkeypatch):
    """A tampered identity is refused even though it is self-consistent.

    The expected values come from the run config; a saved identity that simply
    agrees with itself cannot pass.
    """
    cfg = _split_config(news_article_limit=100, data_vendors={"news_data": "yfinance"})
    sources = _Sources()
    sources.install(monkeypatch)
    base = _initial(cfg)
    saved = _saved_for(base)
    tampered = copy.deepcopy(saved)
    tampered[sp.STATE_KEY]["identity"].update(
        {"news_article_limit": 5, "news_vendor_chain": ["alpha_vantage"]}
    )

    _activate(cfg)
    model = _ScriptedModel()
    with pytest.raises(sp.SentimentInputError, match="news_article_limit"):
        sentiment.create_sentiment_analyst(model, True)({**base, **tampered})
    assert model.calls == 0
    assert sources.counts() == (1, 1, 1)


# ---------------------------------------------------------------------------
# Missing / incomplete / wrong-version: fail before the model
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda s: s.pop(sp.STATE_KEY), id="no-saved-input"),
        pytest.param(lambda s: s[sp.STATE_KEY].pop("identity"), id="no-identity"),
        pytest.param(lambda s: s[sp.STATE_KEY]["identity"].pop("ticker"),
                     id="identity-incomplete"),
        pytest.param(lambda s: s[sp.STATE_KEY]["identity"].pop("news_vendor_chain"),
                     id="identity-missing-source-param"),
        pytest.param(lambda s: s[sp.STATE_KEY]["identity"].pop("news_article_limit"),
                     id="identity-missing-article-limit"),
        pytest.param(lambda s: s[sp.STATE_KEY]["identity"].__setitem__(
            "news_article_limit", None), id="identity-null-article-limit"),
        pytest.param(lambda s: s[sp.STATE_KEY].pop("blocks"), id="no-blocks"),
        pytest.param(lambda s: s[sp.STATE_KEY]["blocks"].pop("reddit"),
                     id="missing-reddit"),
        pytest.param(lambda s: s[sp.STATE_KEY]["blocks"].__setitem__("news", 7),
                     id="non-text-news"),
        pytest.param(lambda s: s[sp.STATE_KEY]["identity"].__setitem__(
            "schema_version", "sentiment-inputs/v0"), id="old-schema"),
    ],
)
def test_bad_input_fails_before_model(monkeypatch, mutate):
    sources = _Sources()
    sources.install(monkeypatch)
    base = _initial(_split_config())
    saved = _saved_for(base)
    state = copy.deepcopy({**base, **saved})
    mutate(state)
    model = _ScriptedModel()
    with pytest.raises(sp.SentimentInputError):
        sentiment.create_sentiment_analyst(model, True)(state)
    assert model.calls == 0
    assert sources.counts() == (1, 1, 1), "nothing was re-fetched"


@pytest.mark.unit
def test_missing_input_fails_before_model(monkeypatch):
    sources = _Sources()
    sources.install(monkeypatch)
    model = _ScriptedModel()
    with pytest.raises(sp.SentimentInputError):
        sentiment.create_sentiment_analyst(model, True)(_initial(_split_config()))
    assert model.calls == 0
    assert sources.counts() == (0, 0, 0)


# ---------------------------------------------------------------------------
# Unavailable placeholders survive save and resume verbatim
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_unavailable_text_is_saved_and_reused_verbatim(monkeypatch):
    placeholder = "<stocktwits unavailable: messages_not_list>"
    reddit_placeholder = (
        "<Reddit unavailable: fetch failed (HTTPError); this is not an absence of discussion>"
    )
    sources = _Sources(stocktwits=placeholder, reddit=reddit_placeholder)
    sources.install(monkeypatch)
    base = _initial(_split_config())
    saved = _saved_for(base)
    assert saved[sp.STATE_KEY]["blocks"]["stocktwits"] == placeholder
    assert saved[sp.STATE_KEY]["blocks"]["reddit"] == reddit_placeholder

    # A later fetch would return fresh text; the resume must not see it.
    fresh = _Sources(stocktwits="FRESH ST", reddit="FRESH RD")
    fresh.install(monkeypatch)
    model = _ScriptedModel()
    out = sentiment.create_sentiment_analyst(model, True)({**base, **saved})
    assert "REPORT from the model" in out["sentiment_report"]
    assert fresh.counts() == (0, 0, 0)
    prompt = str(model.sent[0])
    assert placeholder in prompt and reddit_placeholder in prompt
    assert "FRESH" not in prompt


# ---------------------------------------------------------------------------
# Fatal prefetch errors: no model, nothing swallowed
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "error,expected",
    [
        (VendorAuthenticationError("401"), VendorAuthenticationError),
        (TypeError("bug"), TypeError),
        (KeyboardInterrupt(), KeyboardInterrupt),
        (RuntimeError("cancelled"), RuntimeError),
    ],
)
def test_fatal_prefetch_error_does_not_reach_model(monkeypatch, error, expected):
    sources = _Sources()
    sources.news_error = error
    sources.install(monkeypatch)
    model = _ScriptedModel()
    with pytest.raises(expected):
        sentiment.create_sentiment_prefetch_node()(_initial(_split_config()))
    assert model.calls == 0


@pytest.mark.unit
def test_prefetch_failure_saves_nothing(monkeypatch):
    """A failure in the second fetch leaves no partial save anywhere."""
    sources = _Sources()
    sources.stocktwits_error = RuntimeError("boom")
    sources.install(monkeypatch)
    with pytest.raises(RuntimeError):
        sentiment.create_sentiment_prefetch_node()(_initial(_split_config()))
    # News was tried once, StockTwits failed, Reddit never ran: nothing saved,
    # so a resume would fetch again (the documented boundary).
    assert sources.counts() == (1, 1, 0)
    assert sources.reddit_calls == []


# ---------------------------------------------------------------------------
# Real checkpoint: prefetch saved, model raised, resume without re-fetching
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_real_checkpoint_resume_after_model_failure_fetches_once(tmp_path, monkeypatch):
    sources = _Sources(news="NEWS-SAVED", stocktwits="ST-SAVED", reddit="RD-SAVED")
    sources.install(monkeypatch)
    cfg = _split_config(data_cache_dir=str(tmp_path))
    init = _initial(cfg, run_id="run-resume")
    tid = thread_id("AAPL", TRADE_DATE, "sentiment_prefetch=True")
    graph_config = {"configurable": {"thread_id": tid}, "recursion_limit": 40}

    # Run 1: the prefetch node saves its input, the model then raises.
    failing = _ScriptedModel()
    failing.fail_first = True
    with get_checkpointer(cfg["data_cache_dir"], "AAPL") as saver:
        graph1 = _sentiment_slice(failing).compile(checkpointer=saver)
        with pytest.raises(RuntimeError, match="model exploded"):
            graph1.invoke(init, graph_config)

    assert sources.counts() == (1, 1, 1), "prefetch ran once before the failure"
    step = checkpoint_step(cfg["data_cache_dir"], "AAPL", TRADE_DATE,
                           "sentiment_prefetch=True")
    assert step is not None

    # Between the crash and the resume, an external caller changes the global
    # config. The resumed run keeps its own run config from the checkpoint, so
    # the saved input is still consumed.
    _activate({**cfg, "news_article_limit": 1,
               "data_vendors": {"news_data": "alpha_vantage"}})

    # Run 2: a fresh graph + the real saved checkpoint. The model succeeds
    # this time and no source is fetched again. The saved state was produced
    # by run 1's prefetch node, not rebuilt by the test.
    succeeding = _ScriptedModel(narrative="RECOVERED")
    with get_checkpointer(cfg["data_cache_dir"], "AAPL") as saver:
        graph2 = _sentiment_slice(succeeding).compile(checkpointer=saver)
        out = graph2.invoke(None, graph_config)

    assert succeeding.calls == 1
    assert "RECOVERED" in out["sentiment_report"]
    prompt = str(succeeding.sent[0])
    assert "NEWS-SAVED" in prompt and "ST-SAVED" in prompt and "RD-SAVED" in prompt
    assert out[sp.STATE_KEY]["blocks"] == {
        "news": "NEWS-SAVED",
        "stocktwits": "ST-SAVED",
        "reddit": "RD-SAVED",
    }
    assert sources.counts() == (1, 1, 1), "resume must not fetch again"
    # The external global update was not overwritten by the run.
    assert _news_article_limit_now() == 1
    assert _news_vendor_chain_now() == ("alpha_vantage",)


# ---------------------------------------------------------------------------
# Graph wiring: prefetch is always the entry to social
# ---------------------------------------------------------------------------


def _edges(workflow):
    # LangGraph registers the entry point as ``__start__``.
    return {
        ("START" if source == START else source, target)
        for source, target, *_ in workflow.edges
    }


@pytest.mark.unit
def test_split_social_first_enters_prefetch():
    setup, _ = _setup(_split_config())
    workflow = setup.setup_graph(("social", "news"))
    edges = _edges(workflow)
    assert PREFETCH_NODE in workflow.nodes
    assert ("START", PREFETCH_NODE) in edges
    assert (PREFETCH_NODE, ANALYST_NODE) in edges
    assert ("Msg Clear Sentiment", "News Analyst") in edges
    # No second generation, no tool loop added, and no extra path into the
    # prefetch node.
    assert [t for s, t in edges if s == PREFETCH_NODE] == [ANALYST_NODE]
    assert not any(target == "tools_social" for _, target in edges)


@pytest.mark.unit
def test_split_social_not_first_still_enters_prefetch():
    setup, _ = _setup(_split_config())
    workflow = setup.setup_graph(("market", "news", "social"))
    edges = _edges(workflow)
    assert ("START", "Market Analyst") in edges
    assert ("Msg Clear News", PREFETCH_NODE) in edges
    assert (PREFETCH_NODE, ANALYST_NODE) in edges
    # Only one edge leaves the prefetch: straight into generation.
    assert [t for s, t in edges if s == PREFETCH_NODE] == [ANALYST_NODE]
    assert ("Msg Clear Sentiment", "Bull Researcher") in edges


@pytest.mark.unit
def test_split_does_not_change_other_analysts():
    analysts = ("market", "social", "news", "fundamentals")
    off, _ = _setup(_config())
    on, _ = _setup(_split_config())
    off_workflow, on_workflow = off.setup_graph(analysts), on.setup_graph(analysts)
    off_edges, on_edges = _edges(off_workflow), _edges(on_workflow)
    assert PREFETCH_NODE not in off_workflow.nodes
    assert PREFETCH_NODE in on_workflow.nodes
    # The only change is how the sentiment analyst is entered: its one entry
    # edge becomes an entry through the prefetch node.
    assert off_edges - on_edges == {("Msg Clear Market", ANALYST_NODE)}
    assert on_edges - off_edges == {
        ("Msg Clear Market", PREFETCH_NODE), (PREFETCH_NODE, ANALYST_NODE)}
    # Every original node is still there, and so are the other analysts'
    # tool/clear nodes.
    for node in off_workflow.nodes:
        assert node in on_workflow.nodes
    for key in ("tools_market", "tools_news", "tools_fundamentals"):
        assert key in on_workflow.nodes
    # Fundamental's chain into the researcher is where it always was.
    assert ("Msg Clear Fundamentals", "Bull Researcher") in on_edges


# ---------------------------------------------------------------------------
# Checkpoint signature distinguishes the switch
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_run_signature_distinguishes_the_sentiment_prefetch_switch():
    graph = object.__new__(TradingAgentsGraph)
    graph.selected_analysts = ("social",)
    base_cfg = {"max_debate_rounds": 1, "max_risk_discuss_rounds": 1}
    graph.config = dict(base_cfg)
    base = graph._run_signature("stock")
    assert "sentiment_prefetch=False" in base

    graph.config = {**base_cfg, "sentiment_prefetch": {"enabled": True}}
    with_split = graph._run_signature("stock")
    assert with_split != base
    assert "sentiment_prefetch=True" in with_split
    assert with_split == graph._run_signature("stock")
    # Independent of the other shape switches.
    graph.config = {**base_cfg, "news_tool_governance": {"enabled": True}}
    with_news = graph._run_signature("stock")
    assert "sentiment_prefetch=False" in with_news and "news_gov=True" in with_news
