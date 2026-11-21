"""Integration boundaries: NFR-AUD-001, NFR-BUD-001, NFR-BC-001, NFR-OFF-001.

Exercise production graph wiring, real SQLite checkpoints and the usage ledger
with source/model transports replaced. No socket or paid model is used.
"""

import copy

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.prebuilt import ToolNode

from tradingagents.agents.analysts import sentiment_analyst
from tradingagents.agents.utils.news_data_tools import get_news
from tradingagents.dataflows import interface
from tradingagents.dataflows.evidence_capture import capture_news_articles
from tradingagents.debate.usage_capture import UsageCapture, use_usage_capture
from tradingagents.debate.usage_ledger import UsageLedger, new_run_id
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.evidence.ingest import use_collector
from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.run_identity import execution_digest, execution_identity
from tradingagents.graph.setup import GraphSetup

DAY = "2026-05-13"


class Model(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def _response(content="", **kwargs):
    return AIMessage(
        content=content,
        usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
        **kwargs,
    )


def _capture_article():
    capture_news_articles(
        "NVDA",
        [{"title": "Observed news", "publisher": "Example", "url": "https://example.com/a",
          "published": "2026-05-12T12:00:00Z"}],
        source_name="yfinance_news", tool="get_news",
    )


def _state(config):
    return {
        "company_of_interest": "NVDA", "trade_date": DAY, "asset_type": "stock",
        "messages": [HumanMessage(content="Analyze NVDA")],
        "tool_governance": {"run_id": "merge-test"}, "run_config": config,
    }


@pytest.mark.parametrize("stop", ["news_tool_execute", "news_wrap_up"])
def test_governed_news_persists_evidence_and_counts_wrap_up(tmp_path, monkeypatch, stop):
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["news_tool_governance"] = {"enabled": True, "max_rounds": 1, "max_calls": 1}
    config["tool_vendors"] = {"get_news": "yfinance"}
    config["results_dir"] = str(tmp_path)
    responses = [
        _response(tool_calls=[{"id": "news-1", "name": "get_news", "args": {
            "ticker": "NVDA", "start_date": "2026-05-06", "end_date": DAY,
        }}]),
        _response("News report from the observed source."),
    ]
    model = Model(responses=responses)
    dispatched = []

    def vendor(*args, **kwargs):
        dispatched.append(args)
        _capture_article()
        return "Observed news"

    monkeypatch.setitem(interface.VENDOR_METHODS, "get_news", {"yfinance": vendor})
    # The run config is installed just as TradingAgentsGraph does before tools.
    from tradingagents.dataflows.config import config_snapshot

    rid = new_run_id("NVDA", DAY, nonce="merge-news")
    ledger = UsageLedger(tmp_path / "usage.db")
    ledger.begin_run(rid)
    capture = UsageCapture(run_id=rid, ledger=ledger)
    workflow = GraphSetup(model, model, {"news": ToolNode([get_news])},
                          ConditionalLogic(), config=config).setup_graph(["news"])
    run = {"configurable": {"thread_id": "merge-news"}}
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.db")) as saver:
        graph = workflow.compile(checkpointer=saver, interrupt_after=[stop])
        with config_snapshot(config), use_collector("NVDA", DAY), use_usage_capture(capture):
            graph.invoke(_state(config), run)
        saved = saver.get_tuple(run).checkpoint["channel_values"]
    # A new collector/process can recover the actual evidence from this exact
    # boundary, before message clearing or the later Gate has run.
    assert saved["data_quality_ingested_evidence"]
    assert saved["data_quality_source_attempt_envelopes"]
    assert len(dispatched) == 1
    tool_messages = [m for m in saved["messages"] if getattr(m, "tool_call_id", None)]
    assert [m.tool_call_id for m in tool_messages] == ["news-1"]
    events = ledger.read_run_spend(rid).events
    count = 1 if stop == "news_tool_execute" else 2
    assert len(events) == count
    assert all(e.phase == "analyst" and e.total_tokens == 12 for e in events)
    if stop == "news_wrap_up":
        assert saved["news_report"] == "News report from the observed source."


def test_split_prefetch_checkpoint_also_retains_evidence(tmp_path, monkeypatch):
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["sentiment_prefetch"] = {"enabled": True}

    def fetch(*args, **kwargs):
        _capture_article()
        return {"news": "Observed news", "stocktwits": "unavailable", "reddit": "unavailable"}

    monkeypatch.setattr(sentiment_analyst, "_fetch_sources", fetch)
    model = Model(responses=[_response("Must not run before the interrupt")])
    workflow = GraphSetup(model, model, {"social": ToolNode([])}, ConditionalLogic(),
                          config=config).setup_graph(["social"])
    run = {"configurable": {"thread_id": "merge-social"}}
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.db")) as saver:
        graph = workflow.compile(checkpointer=saver, interrupt_after=["Sentiment Prefetch"])
        with use_collector("NVDA", DAY):
            graph.invoke(_state(config), run)
        saved = saver.get_tuple(run).checkpoint["channel_values"]
    assert saved["sentiment_inputs"]
    assert saved["data_quality_ingested_evidence"]
    assert not saved.get("sentiment_report")
    assert len(saved["messages"]) == 1


def test_checkpoint_identity_includes_the_effective_debate_policy():
    base = copy.deepcopy(DEFAULT_CONFIG)
    explicit = copy.deepcopy(base)
    explicit["debate_termination"] = {"enabled": True}
    assert execution_digest(base) == execution_digest(explicit)
    changed = copy.deepcopy(base)
    changed["debate_termination"] = {"enabled": False}
    assert execution_digest(changed) != execution_digest(base)
    changed["debate_termination"] = {"max_calls": 123}
    assert execution_digest(changed) != execution_digest(base)
    # Old graphs had no Gate/evaluator: their checkpoint version is incompatible.
    assert execution_identity(base)["version"] == "run-identity/v2"
