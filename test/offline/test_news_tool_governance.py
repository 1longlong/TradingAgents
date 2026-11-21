"""Offline tests for the opt-in news-analyst tool governance.

The suite builds a **real** news graph slice (the news analyst, the four
governance nodes, the msg-clear node) on a scripted model and fake tools, so the
state-update and message-merge mechanics exercised are the ones the production
graph uses. No network, no vendor, no real LLM: the vendor router each news tool
calls is patched.

Covered:

* the switch is off by default, its caps default to 4/8, illegal config is
  refused, and it stays independent of the market and fundamentals switches;
* permission is exactly the four bound news tools; ``get_insider_transactions``
  never runs for this analyst, and a batch with an unbound tool is final;
* a normal run finishes early on the analyst's own text, written straight to
  ``news_report`` -- no second generation;
* ``max_rounds=1`` / ``max_calls=1`` bound the real call count;
* after the final allowed round the run goes straight to the single wrap-up:
  the model-call count and the wrap-up prompt (evidence-only, date window,
  macro ``as_of``, prediction-market limit) are checked;
* repeated and all-blocked requests terminate and every call id is paired;
* a refusal / truncation / blank first answer makes exactly one model request;
* a tool exception after registration does not charge the round twice;
* the run date is injected into every tool call and clamps requested dates;
* each governed analyst maps to its own node, and records/reports stay apart;
* the checkpoint signature distinguishes the news switch.
"""

import copy
import tempfile
from unittest.mock import patch

import pytest
from langchain_core.language_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from tradingagents.agents.analysts import news_analyst as news_module
from tradingagents.agents.utils import (
    macro_data_tools,
    news_data_tools,
    prediction_markets_tools,
)
from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.agents.utils.agent_utils import create_msg_delete
from tradingagents.dataflows.config import set_config
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph import news_tool_governance as ntg
from tradingagents.graph.analyst_execution import ANALYST_NODE_SPECS
from tradingagents.graph.conditional_logic import ConditionalLogic, _analyst_node
from tradingagents.graph.fundamentals_governance import parse_fundamentals_tool_governance
from tradingagents.graph.market_governance import parse_market_tool_governance
from tradingagents.graph.news_governance import NEWS_TOOLS, parse_news_tool_governance
from tradingagents.graph.setup import GraphSetup

TRADE_DATE = "2026-08-14"

NEWS = {"ticker": "AAPL", "start_date": "2026-08-07", "end_date": TRADE_DATE}
GLOBAL = {"curr_date": TRADE_DATE, "look_back_days": 7, "limit": 10}
MACRO = {"indicator": "cpi", "curr_date": TRADE_DATE, "look_back_days": 30}
ODDS = {"topic": "Fed rate cut", "limit": 5}

NEWS_TOOL_OBJECTS = [
    news_data_tools.get_news,
    news_data_tools.get_global_news,
    macro_data_tools.get_macro_indicators,
    prediction_markets_tools.get_prediction_markets,
]


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _call(call_id, name, args):
    return {"id": call_id, "name": name, "args": dict(args)}


def _ai(*calls, text=""):
    return AIMessage(content=text, tool_calls=list(calls))


class ScriptedModel(FakeMessagesListChatModel):
    """A chat model answering from a fixed script and recording invocations.

    It **stops at the last response** instead of cycling and records what each
    invocation was sent, so a test can assert on the wrap-up prompt.
    """

    sent: list = []

    def __init__(self, responses):
        super().__init__(responses=list(responses))
        self.sent = []

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.sent.append(list(messages))
        index = min(self.i, len(self.responses) - 1)
        self.i = min(self.i + 1, len(self.responses) - 1)
        return ChatResult(
            generations=[ChatGeneration(message=copy.deepcopy(self.responses[index]))]
        )

    @property
    def calls(self):
        return len(self.sent)


def _config(**overrides):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["data_cache_dir"] = tempfile.mkdtemp()
    cfg["results_dir"] = tempfile.mkdtemp()
    cfg.update(overrides)
    return cfg


def _enabled(*, max_rounds=4, max_calls=8, **overrides):
    return _config(
        news_tool_governance={
            "enabled": True,
            "max_rounds": max_rounds,
            "max_calls": max_calls,
        },
        **overrides,
    )


def _initial(cfg, run_id="run-test"):
    return {
        "messages": [("human", "AAPL")],
        "company_of_interest": "AAPL",
        "asset_type": "stock",
        "instrument_context": "",
        "trade_date": TRADE_DATE,
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
            "current_neutral_response": "",
            "judge_decision": "",
            "count": 0,
        },
        "tool_governance": {"run_id": run_id},
        "run_config": cfg,
    }


def _news_slice(cfg, responses, *, tools=None, tool_node=None):
    """Compile the real news slice of the graph on a scripted model."""
    set_config(cfg)
    llm = ScriptedModel(responses)
    tools = tools if tools is not None else NEWS_TOOL_OBJECTS
    node = tool_node if tool_node is not None else ToolNode(tools)
    with (
        patch.object(news_module, "get_news", news_data_tools.get_news),
        patch.object(news_module, "get_global_news", news_data_tools.get_global_news),
        patch.object(news_module, "get_macro_indicators", macro_data_tools.get_macro_indicators),
        patch.object(
            news_module,
            "get_prediction_markets",
            prediction_markets_tools.get_prediction_markets,
        ),
    ):
        analyst = news_module.create_news_analyst(llm)
    nodes = ntg.create_news_governance_nodes(llm=llm, tool_node=node)

    graph = StateGraph(AgentState)
    graph.add_node("News Analyst", analyst)
    graph.add_node("Msg Clear News", create_msg_delete())
    graph.add_node("news_tool_prepare", nodes["prepare"])
    graph.add_node("news_tool_execute", nodes["execute"])
    graph.add_node("news_finish", nodes["finish"])
    graph.add_node("news_wrap_up", nodes["wrap_up"])
    graph.add_edge(START, "News Analyst")

    logic = ConditionalLogic()
    graph.add_conditional_edges(
        "News Analyst",
        logic.should_continue_news_governed,
        ["news_tool_prepare", "news_wrap_up", "news_finish"],
    )
    graph.add_conditional_edges(
        "news_tool_prepare",
        logic.should_execute_news_prepared,
        ["news_tool_execute", "news_wrap_up", "News Analyst"],
    )
    graph.add_conditional_edges(
        "news_tool_execute",
        logic.should_continue_news_after_execute,
        ["News Analyst", "news_wrap_up"],
    )
    graph.add_edge("news_finish", "Msg Clear News")
    graph.add_edge("news_wrap_up", "Msg Clear News")
    graph.add_edge("Msg Clear News", END)
    return graph.compile(), llm


class _Router:
    """A fake vendor router recording every call the patched tools make.

    ``crash`` may be set to a tool name whose call raises instead of answering.
    """

    def __init__(self, crash=None):
        self.calls = []
        self.crash = crash

    def __call__(self, method, *args, **kwargs):
        self.calls.append((method, args, kwargs))
        if self.crash == method:
            raise RuntimeError("vendor exploded")
        return f"{method} RESULT for {args}"

    def methods(self):
        return [method for method, *_ in self.calls]


def _vendor_router(router=None, **kwargs):
    """Patch the one router every news/macro/prediction tool calls (no network)."""
    r = router if router is not None else _Router(**kwargs)
    return (
        patch.object(news_data_tools, "route_to_vendor", r),
        patch.object(macro_data_tools, "route_to_vendor", r),
        patch.object(prediction_markets_tools, "route_to_vendor", r),
    ), r


def _run(cfg, responses, *, run_id="run-test", tools=None, tool_node=None, router=None):
    """Run the slice to completion and capture its final governance record.

    The run ends at the msg-clear node, which replaces the conversation; the
    governance record is the per-node update that must survive to the end, so
    it is captured while streaming, together with every report written.
    """
    graph, llm = _news_slice(cfg, responses, tools=tools, tool_node=tool_node)
    governance: dict = {}
    report = ""
    patches, r = _vendor_router(router)
    with patches[0], patches[1], patches[2]:
        for step in graph.stream(
            _initial(cfg, run_id), {"recursion_limit": 80}, stream_mode="updates"
        ):
            for update in step.values():
                if not isinstance(update, dict):
                    continue
                if "tool_governance" in update:
                    governance = update["tool_governance"]
                if update.get("news_report"):
                    report = update["news_report"]
    return report, llm, governance, r


def _final_governance(graph, initial, router):
    """Stream a compiled slice and return the last governance record seen."""
    patches, _ = _vendor_router(router)
    governance: dict = {}
    with patches[0], patches[1], patches[2]:
        for step in graph.stream(initial, {"recursion_limit": 80}, stream_mode="updates"):
            for update in step.values():
                if isinstance(update, dict) and "tool_governance" in update:
                    governance = update["tool_governance"]
    return governance


def _scope(out):
    return out["tool_governance"]["analysts"]["news"]


_WRAP_UP_SENTINEL = "The tool-call allowance for this run is spent"
_NEWS_SENTINEL = "You are a news researcher"


def _system_text(sent):
    """The system prompt of one recorded model invocation."""
    return "\n".join(
        message.content
        for message in sent
        if isinstance(message, SystemMessage) and isinstance(message.content, str)
    )


def _requested_wrap_up(sent):
    system = _system_text(sent)
    return _WRAP_UP_SENTINEL in system and "News Analyst" in system


def _requested_analyst(sent):
    system = _system_text(sent)
    return _NEWS_SENTINEL in system and _WRAP_UP_SENTINEL not in system


# ---------------------------------------------------------------------------
# Toggle
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_governance_is_off_by_default():
    assert parse_news_tool_governance(DEFAULT_CONFIG).enabled is False
    assert parse_news_tool_governance(None).enabled is False
    assert parse_news_tool_governance({}).enabled is False


@pytest.mark.unit
def test_default_config_defaults_to_four_rounds_and_eight_calls():
    section = DEFAULT_CONFIG["news_tool_governance"]
    assert section == {"enabled": False, "max_rounds": 4, "max_calls": 8}
    parsed = parse_news_tool_governance({"news_tool_governance": {"enabled": True}})
    assert parsed.enabled is True
    assert (parsed.max_rounds, parsed.max_calls) == (4, 8)
    limits = parsed.limits()
    assert (limits.max_rounds, limits.max_calls) == (4, 8)


@pytest.mark.unit
def test_disabled_section_ignores_caps_but_refuses_nonsense():
    parsed = parse_news_tool_governance(
        {"news_tool_governance": {"enabled": False, "max_rounds": 9}}
    )
    assert parsed.enabled is False
    assert parsed.max_rounds is None and parsed.max_calls is None
    with pytest.raises(ValueError):
        parse_news_tool_governance(
            {"news_tool_governance": {"enabled": False, "max_rounds": 0}}
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    "section",
    [
        {"enabled": True, "max_rounds": 0},
        {"enabled": True, "max_rounds": -1},
        {"enabled": True, "max_rounds": 2.5},
        {"enabled": True, "max_rounds": True},
        {"enabled": True, "max_rounds": None},
        {"enabled": True, "max_calls": 0},
        {"enabled": True, "max_calls": None},
        {"enabled": True, "max_calls": "8"},
        {"enabled": True, "typo_key": 1},
        {"enabled": "yes"},
        {"enabled": 1},
        {"enabled": None},
    ],
)
def test_invalid_config_is_refused(section):
    with pytest.raises(ValueError):
        parse_news_tool_governance({"news_tool_governance": section})


@pytest.mark.unit
def test_toggle_section_must_be_a_mapping():
    with pytest.raises(ValueError):
        parse_news_tool_governance({"news_tool_governance": True})


@pytest.mark.unit
def test_news_switch_is_independent_of_the_other_two():
    """Enabling one section never enables (or re-caps) another."""
    only_n = {"news_tool_governance": {"enabled": True}}
    assert parse_news_tool_governance(only_n).enabled is True
    assert parse_market_tool_governance(only_n).enabled is False
    assert parse_fundamentals_tool_governance(only_n).enabled is False

    only_m = {"market_tool_governance": {"enabled": True, "max_calls": 3}}
    assert parse_news_tool_governance(only_m).enabled is False

    # A cap in one section never leaks into the news defaults.
    both = {
        "market_tool_governance": {"enabled": True, "max_calls": 3},
        "news_tool_governance": {"enabled": True, "max_rounds": 1},
    }
    assert parse_market_tool_governance(both).max_calls == 3
    n_parsed = parse_news_tool_governance(both)
    assert (n_parsed.max_rounds, n_parsed.max_calls) == (1, 8)


# ---------------------------------------------------------------------------
# Toggle off: today's graph, and the four-tool permission set
# ---------------------------------------------------------------------------


NEWS_GOVERNANCE_NODES = {
    "news_tool_prepare",
    "news_tool_execute",
    "news_wrap_up",
    "news_finish",
}


def _assert_no_governance_nodes(workflow):
    assert not NEWS_GOVERNANCE_NODES & set(workflow.nodes)


def _setup(cfg):
    return GraphSetup(
        ScriptedModel([AIMessage("x")]),
        ScriptedModel([AIMessage("x")]),
        {"news": ToolNode(NEWS_TOOL_OBJECTS)},
        ConditionalLogic(),
        config=cfg,
    )


@pytest.mark.unit
def test_graph_with_governance_off_has_only_the_old_news_nodes():
    workflow = _setup(_config(news_tool_governance={"enabled": False})).setup_graph(("news",))
    assert "tools_news" in workflow.nodes
    _assert_no_governance_nodes(workflow)
    assert ("tools_news", "News Analyst") in {
        (source, target) for source, target, *_ in workflow.edges
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    "section",
    [
        {"market_tool_governance": {"enabled": True}},
        {"fundamentals_tool_governance": {"enabled": True}},
        {
            "market_tool_governance": {"enabled": True},
            "fundamentals_tool_governance": {"enabled": True},
        },
    ],
)
def test_other_switches_alone_leave_news_on_the_old_path(section):
    workflow = _setup(_config(**section)).setup_graph(("news",))
    _assert_no_governance_nodes(workflow)
    assert ("tools_news", "News Analyst") in {
        (source, target) for source, target, *_ in workflow.edges
    }


@pytest.mark.unit
def test_graph_with_governance_on_adds_its_own_news_path():
    workflow = _setup(_enabled()).setup_graph(("news",))
    assert set(workflow.nodes) >= NEWS_GOVERNANCE_NODES
    edges = {(source, target) for source, target, *_ in workflow.edges}
    assert ("news_wrap_up", "Msg Clear News") in edges
    assert ("news_finish", "Msg Clear News") in edges
    # The governed path never feeds the plain tool node.
    assert not any(target == "tools_news" for _, target, *_ in edges)

    compiled = workflow.compile()

    def ends(source):
        return {
            target
            for spec in compiled.builder.branches.get(source, {}).values()
            for target in (spec.ends or ())
        }

    assert ends("News Analyst") == {
        "news_tool_prepare",
        "news_wrap_up",
        "news_finish",
    }
    assert ends("news_tool_execute") == {"News Analyst", "news_wrap_up"}


@pytest.mark.unit
def test_permission_is_exactly_the_four_bound_tools():
    node = ToolNode(NEWS_TOOL_OBJECTS)
    permitted = ntg._permitted_tools(node)
    assert {tool.name for tool in permitted} == set(NEWS_TOOLS)


@pytest.mark.unit
def test_an_unbound_tool_is_never_permitted():
    """The graph's news ToolNode also holds insider transactions: not granted."""
    widened = ToolNode([*NEWS_TOOL_OBJECTS, news_data_tools.get_insider_transactions])
    allowed = ntg._permitted_tools(widened)
    assert {tool.name for tool in allowed} == set(NEWS_TOOLS)
    assert "get_insider_transactions" not in {tool.name for tool in allowed}


@pytest.mark.unit
def test_unbound_tool_request_is_final_and_nothing_runs():
    """An invalid request fails the run instead of being recorded as blocked."""
    cfg = _enabled()
    router = _Router()
    graph, llm = _news_slice(
        cfg,
        [_ai(_call("c1", "get_insider_transactions", {"ticker": "AAPL"})), AIMessage("DECOY")],
    )
    report = ""
    patches, r = _vendor_router(router)
    with patches[0], patches[1], patches[2], pytest.raises(ntg.NewsGovernanceError):
        for step in graph.stream(
            _initial(cfg), {"recursion_limit": 80}, stream_mode="updates"
        ):
            for update in step.values():
                if isinstance(update, dict) and update.get("news_report"):
                    report = update["news_report"]
    assert report == ""
    assert router.calls == [], "the unbound tool must never run"
    assert llm.calls == 1, "the decoy must not be requested"


# ---------------------------------------------------------------------------
# Normal runs
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_analyst_finishes_early_on_its_own_report():
    cfg = _enabled(max_rounds=6, max_calls=8)
    responses = [
        _ai(_call("c1", "get_news", NEWS)),
        AIMessage("ANALYST FINAL: news based"),
    ]
    out, llm, governance, router = _run(cfg, responses)

    # The analyst's own text *is* the report: no wrap-up generation.
    assert out == "ANALYST FINAL: news based"
    scope = governance["analysts"]["news"]
    assert (scope["rounds"], scope["executed"]) == (1, 1)
    assert scope["finished"] and scope["closed"]
    assert llm.calls == 2
    assert _requested_analyst(llm.sent[1])
    assert router.methods() == ["get_news"]


@pytest.mark.unit
def test_two_rounds_then_a_report():
    cfg = _enabled(max_rounds=4, max_calls=8)
    responses = [
        _ai(
            _call("c1", "get_news", NEWS),
            _call("c2", "get_global_news", GLOBAL),
        ),
        _ai(_call("c3", "get_macro_indicators", MACRO)),
        AIMessage("FINAL: three sources"),
    ]
    out, llm, governance, router = _run(cfg, responses)
    scope = governance["analysts"]["news"]
    assert (scope["rounds"], scope["executed"]) == (2, 3)
    assert out.startswith("FINAL")
    assert sorted(router.methods()) == ["get_global_news", "get_macro_indicators", "get_news"]


@pytest.mark.unit
def test_real_call_count_respects_max_rounds_one():
    cfg = _enabled(max_rounds=1, max_calls=8)
    responses = [
        _ai(
            _call("c1", "get_news", NEWS),
            _call("c2", "get_global_news", GLOBAL),
        ),
        AIMessage("WRAP: one round only"),
    ]
    graph, llm = _news_slice(cfg, responses)
    router = _Router()
    governance = _final_governance(graph, _initial(cfg), router)
    scope = governance["analysts"]["news"]
    assert scope["rounds"] == 1
    assert scope["executed"] == 2
    assert sorted(router.methods()) == ["get_global_news", "get_news"]
    # Round 1 runs; the next turn is over the allowance -> wrap-up directly.
    assert llm.calls == 2
    assert _requested_wrap_up(llm.sent[1])


@pytest.mark.unit
def test_real_call_count_respects_max_calls_one():
    cfg = _enabled(max_rounds=4, max_calls=1)
    responses = [
        _ai(
            _call("c1", "get_news", NEWS),
            _call("c2", "get_global_news", GLOBAL),
        ),
        AIMessage("WRAP: one call only"),
    ]
    graph, llm = _news_slice(cfg, responses)
    router = _Router()
    governance = _final_governance(graph, _initial(cfg), router)
    scope = governance["analysts"]["news"]
    assert scope["executed"] == 1
    assert scope["blocked"] == 1
    assert len(router.calls) == 1
    # Every call of the batch is paired before the wrap-up.
    assert [m.tool_call_id for m in llm.sent[-1] if isinstance(m, ToolMessage)] == [
        "c1",
        "c2",
    ]
    assert llm.calls == 2
    assert _requested_wrap_up(llm.sent[1])


@pytest.mark.unit
def test_final_round_executes_then_wraps_up_without_another_analyst_turn():
    """The last allowed batch runs fully, then the wrap-up is the next turn."""
    cfg = _enabled(max_rounds=2, max_calls=8)
    responses = [
        _ai(_call("c1", "get_news", NEWS)),
        # The batch that spends the last round: both calls must still run.
        _ai(
            _call("c2", "get_global_news", GLOBAL),
            _call("c3", "get_macro_indicators", MACRO),
        ),
        AIMessage("WRAPUP: two rounds done"),
    ]
    graph, llm = _news_slice(cfg, responses)
    router = _Router()
    governance = _final_governance(graph, _initial(cfg), router)

    scope = governance["analysts"]["news"]
    assert (scope["rounds"], scope["executed"]) == (2, 3)
    assert sorted(router.methods()) == ["get_global_news", "get_macro_indicators", "get_news"]
    # Analyst, analyst, wrap-up: the analyst is not asked again just to be told
    # its allowance is spent.
    assert llm.calls == 3
    assert _requested_analyst(llm.sent[0]) and _requested_analyst(llm.sent[1])
    assert _requested_wrap_up(llm.sent[2])


@pytest.mark.unit
def test_wrap_up_prompt_forbids_invention_and_keeps_point_in_time_rules():
    cfg = _enabled(max_rounds=1, max_calls=2)
    responses = [
        _ai(
            _call("c1", "get_news", NEWS),
            _call("c2", "get_prediction_markets", ODDS),
        ),
        AIMessage("WRAPUP: evidence only"),
    ]
    out, llm, _, _ = _run(cfg, responses)
    assert out == "WRAPUP: evidence only"
    sent = llm.sent[-1]
    system = _system_text(sent)
    for phrase in (
        "News Analyst",
        "ONLY",
        "Do not invent news, headlines, publishers, sources, URLs, dates",
        "macro figures or event probabilities",
        "missing data from confirmed absence",
        "Keep the news date window",
        "trade date",
        "as_of",
        "Prediction markets serve only live odds",
        "never describe a live probability as evidence",
        "missing or",
    ):
        assert phrase in system, phrase
    # The evidence the analyst collected is in the conversation.
    tool_texts = [m.content for m in sent if isinstance(m, ToolMessage)]
    assert any("get_news" in str(text) for text in tool_texts)
    assert any("get_prediction_markets" in str(text) for text in tool_texts)


# ---------------------------------------------------------------------------
# The run date is injected into every tool call
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_run_date_is_injected_and_historical_limits_preserved():
    """A model asking for future/absent dates never reaches past the run date."""
    cfg = _enabled(max_rounds=1, max_calls=4)
    responses = [
        _ai(
            # Window ends after the run date: clamped to it.
            _call(
                "c1",
                "get_news",
                {"ticker": "AAPL", "start_date": "2026-08-07", "end_date": "2027-01-01"},
            ),
            # Window wholly after the run date: its length is kept, moved back.
            _call(
                "c2",
                "get_news",
                {"ticker": "AAPL", "start_date": "2026-09-01", "end_date": "2026-09-20"},
            ),
            # Macro date after the run date: clamped.
            _call("c3", "get_macro_indicators", {"indicator": "cpi", "curr_date": "2030-01-01"}),
            # Prediction markets: the run date reaches the vendor as the vintage.
            _call("c4", "get_prediction_markets", ODDS),
        ),
        AIMessage("WRAPUP: dates"),
    ]
    graph, llm = _news_slice(cfg, responses)
    router = _Router()
    _final_governance(graph, _initial(cfg), router)

    by_method: dict[str, list] = {}
    for method, args, _kwargs in router.calls:
        by_method.setdefault(method, []).append(args)
    assert by_method["get_news"][0] == ("AAPL", "2026-08-07", TRADE_DATE)
    # 19 days before the run date, so the window keeps its length.
    assert by_method["get_news"][1] == ("AAPL", "2026-07-26", TRADE_DATE)
    assert by_method["get_macro_indicators"][0][1] == TRADE_DATE
    assert by_method["get_prediction_markets"][0][2] == TRADE_DATE
    for method, args, _kwargs in router.calls:
        if method == "get_news":
            assert args[2] <= TRADE_DATE
        if method == "get_macro_indicators":
            assert args[1] <= TRADE_DATE


# ---------------------------------------------------------------------------
# Repeated / all-blocked requests terminate, every call id paired
# ---------------------------------------------------------------------------


def _assert_every_call_paired(llm, scripted_ids):
    """Every tool call the model ever issued has exactly one answer in the run."""
    counts: dict[str, int] = {}
    for message in llm.sent[-1]:
        if isinstance(message, ToolMessage):
            counts[message.tool_call_id] = counts.get(message.tool_call_id, 0) + 1
    assert sorted(counts) == sorted(scripted_ids)
    assert all(count == 1 for count in counts.values()), counts


@pytest.mark.unit
def test_repeated_tool_requests_stop_at_the_round_cap_and_pair_every_call():
    cfg = _enabled(max_rounds=2, max_calls=8)
    responses = [
        _ai(_call("c1", "get_news", NEWS)),
        _ai(_call("c2", "get_news", NEWS)),
        AIMessage("WRAPUP: repeated requests"),
    ]
    graph, llm = _news_slice(cfg, responses)
    router = _Router()
    governance = _final_governance(graph, _initial(cfg), router)

    scope = governance["analysts"]["news"]
    assert scope["rounds"] == 2
    # Success reuse stays off: the identical repeat is blocked, not served.
    assert scope["executed"] == 1
    assert scope["blocked"] == 1
    assert scope["reused"] == 0
    assert router.methods() == ["get_news"], "the repeat is not fetched again"
    assert llm.calls == 3
    assert _requested_analyst(llm.sent[0]) and _requested_analyst(llm.sent[1])
    assert _requested_wrap_up(llm.sent[2])
    _assert_every_call_paired(llm, {"c1", "c2"})


@pytest.mark.unit
def test_multi_tool_batch_over_the_call_cap_pairs_every_call():
    cfg = _enabled(max_rounds=2, max_calls=2)
    responses = [
        _ai(
            _call("c1", "get_news", NEWS),
            _call("c2", "get_global_news", GLOBAL),
            _call("c3", "get_macro_indicators", MACRO),
        ),
        AIMessage("WRAPUP: partial batch"),
    ]
    graph, llm = _news_slice(cfg, responses)
    router = _Router()
    governance = _final_governance(graph, _initial(cfg), router)

    scope = governance["analysts"]["news"]
    assert scope["executed"] == 2
    assert scope["blocked"] == 1
    assert sorted(router.methods()) == ["get_global_news", "get_news"]
    assert [m.tool_call_id for m in llm.sent[-1] if isinstance(m, ToolMessage)] == [
        "c1",
        "c2",
        "c3",
    ]
    assert llm.calls == 2
    assert _requested_wrap_up(llm.sent[1])
    _assert_every_call_paired(llm, {"c1", "c2", "c3"})


@pytest.mark.unit
def test_all_blocked_request_still_terminates_and_pairs_every_call():
    """Success reuse is off, so a batch of already-answered calls is blocked."""
    cfg = _enabled(max_rounds=3, max_calls=1)
    responses = [
        _ai(
            _call("c1", "get_news", NEWS),
            _call("c2", "get_global_news", GLOBAL),
            _call("c3", "get_macro_indicators", MACRO),
        ),
        AIMessage("WRAPUP: every call blocked"),
    ]
    out, llm, governance, router = _run(cfg, responses)

    scope = governance["analysts"]["news"]
    assert scope["executed"] == 1
    assert scope["blocked"] == 2
    assert scope["closed"]
    assert out == "WRAPUP: every call blocked"
    assert router.methods() == ["get_news"]
    # The batch never reached a second analyst turn.
    assert llm.calls == 2
    assert _requested_wrap_up(llm.sent[1])
    _assert_every_call_paired(llm, {"c1", "c2", "c3"})


# ---------------------------------------------------------------------------
# Unusable answers: one model request, no fabricated report
# ---------------------------------------------------------------------------

_BAD_ANALYST_ANSWERS = {
    "refusal": AIMessage(
        content="", additional_kwargs={"refusal": "I can't help with that."}
    ),
    "truncated": AIMessage(
        content="NEWS REPORT: the company announced",
        response_metadata={"finish_reason": "length"},
    ),
    "empty": AIMessage(content=""),
}


@pytest.mark.unit
@pytest.mark.parametrize("kind", sorted(_BAD_ANALYST_ANSWERS))
def test_unusable_first_answer_makes_exactly_one_model_request(kind):
    """Refusal / truncation / blank fails at the first response.

    A normal report is scripted as a **decoy** second answer. If the router
    treated the unusable turn as something to wrap up, the decoy would be spent
    and stored as ``news_report``. Instead the run raises after one model call,
    saves no report and runs no tool.
    """
    cfg = _enabled(max_rounds=2, max_calls=10)
    responses = [
        _BAD_ANALYST_ANSWERS[kind],
        AIMessage("DECOY: this report must never be requested"),
    ]
    graph, llm = _news_slice(cfg, responses)
    router = _Router()
    patches, _ = _vendor_router(router)
    report = ""
    with patches[0], patches[1], patches[2], pytest.raises(ntg.NewsGovernanceError):
        for step in graph.stream(
            _initial(cfg), {"recursion_limit": 80}, stream_mode="updates"
        ):
            for node, update in step.items():
                assert node != "Msg Clear News"
                if isinstance(update, dict) and update.get("news_report"):
                    report = update["news_report"]

    assert llm.calls == 1, "the decoy must not be requested"
    assert router.calls == [], "no tool may run after an unusable answer"
    assert report == "", "nothing may be saved as the news report"
    assert all(
        "DECOY" not in str(message.content) for sent in llm.sent for message in sent
    )


@pytest.mark.unit
@pytest.mark.parametrize("kind", sorted(_BAD_ANALYST_ANSWERS))
def test_wrap_up_raises_instead_of_storing_an_unusable_answer(kind):
    """The wrap-up exit rejects the same answers; it never retries."""
    cfg = _enabled()
    state = _initial(cfg)
    state["messages"] = [*state["messages"], _ai(_call("c1", "get_news", NEWS))]
    llm = ScriptedModel([_BAD_ANALYST_ANSWERS[kind]])
    nodes = ntg.create_news_governance_nodes(
        llm=llm, tool_node=ToolNode(NEWS_TOOL_OBJECTS)
    )
    with pytest.raises(ntg.NewsGovernanceError):
        nodes["wrap_up"](state)
    assert llm.calls == 1, "an unusable wrap-up answer is final"


# ---------------------------------------------------------------------------
# A tool exception resumes without re-charging the round
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_tool_exception_keeps_registration_and_resume_does_not_recharge():
    """The round is saved before it runs, so a crash cannot charge it twice."""
    cfg = _enabled(max_rounds=3, max_calls=10)
    state = _initial(cfg)
    nodes = ntg.create_news_governance_nodes(
        llm=ScriptedModel([]), tool_node=ToolNode(NEWS_TOOL_OBJECTS)
    )
    state["messages"] = [_ai(_call("c1", "get_news", NEWS))]

    # 1) Prepare registers the round and saves it: nothing has run yet.
    saved = nodes["prepare"](state)
    state.update(saved)
    scope = state["tool_governance"]["analysts"]["news"]
    assert scope["rounds"] == 1
    assert scope["executed"] == 1  # charged for the call it intends to run

    # 2) Execute dispatches the saved round and the tool raises.
    patches, _ = _vendor_router(_Router(crash="get_news"))
    with patches[0], patches[1], patches[2], pytest.raises(RuntimeError, match="vendor exploded"):
        nodes["execute"](state)

    after_crash = state["tool_governance"]["analysts"]["news"]
    assert after_crash["rounds"] == 1
    assert after_crash["charged_rounds"] == scope["charged_rounds"]

    # 3) Resume the same node: the same round, not a new one, and one answer.
    ok_patches, _ = _vendor_router(_Router())
    with ok_patches[0], ok_patches[1], ok_patches[2]:
        update = nodes["execute"](state)
    resumed = update["tool_governance"]["analysts"]["news"]
    assert resumed["rounds"] == 1, "the resumed round must not be charged again"
    assert resumed["executed"] == 1
    assert [m.tool_call_id for m in update["messages"]] == ["c1"]


# ---------------------------------------------------------------------------
# Each analyst maps to its own node; records and reports stay apart
# ---------------------------------------------------------------------------


def _all_three_enabled(*, news_rounds=4, news_calls=8):
    return _config(
        market_tool_governance={"enabled": True, "max_rounds": 4, "max_calls": 8},
        fundamentals_tool_governance={"enabled": True, "max_rounds": 4, "max_calls": 8},
        news_tool_governance={
            "enabled": True,
            "max_rounds": news_rounds,
            "max_calls": news_calls,
        },
    )


@pytest.mark.unit
@pytest.mark.parametrize("analyst", ["market", "fundamentals", "news"])
def test_analyst_node_is_the_registered_node_for_each_analyst(analyst):
    assert _analyst_node(analyst) == ANALYST_NODE_SPECS[analyst].agent_node


@pytest.mark.unit
@pytest.mark.parametrize("analyst", ["", "newsroom", "News Analyst", "fundamentals "])
def test_unknown_analyst_name_fails_instead_of_borrowing_a_node(analyst):
    with pytest.raises(ValueError):
        _analyst_node(analyst)


@pytest.mark.unit
def test_governed_routers_return_each_analysts_own_node():
    """A governed analyst is never routed back into another analyst's node."""
    logic = ConditionalLogic()
    cfg = _all_three_enabled()
    for router, node in (
        (logic.should_execute_market_prepared, "Market Analyst"),
        (logic.should_execute_fundamentals_prepared, "Fundamentals Analyst"),
        (logic.should_execute_news_prepared, "News Analyst"),
    ):
        # No tool call, no saved plan: the router goes back to the analyst.
        assert router(_initial(cfg)) == node


@pytest.mark.unit
def test_graph_with_all_three_switches_on_gets_three_governance_paths():
    from tradingagents.agents.utils import core_stock_tools, fundamental_data_tools

    cfg = _all_three_enabled()
    tools = {
        "market": ToolNode([core_stock_tools.get_stock_data]),
        "fundamentals": ToolNode([fundamental_data_tools.get_fundamentals]),
        "news": ToolNode(NEWS_TOOL_OBJECTS),
    }
    setup = GraphSetup(
        ScriptedModel([AIMessage("x")]),
        ScriptedModel([AIMessage("x")]),
        tools,
        ConditionalLogic(),
        config=cfg,
    )
    workflow = setup.setup_graph(("market", "fundamentals", "news"))
    for prefix in ("market", "fundamentals", "news"):
        assert {
            f"{prefix}_tool_prepare",
            f"{prefix}_tool_execute",
            f"{prefix}_wrap_up",
            f"{prefix}_finish",
        } <= set(workflow.nodes)
    edges = {(source, target) for source, target, *_ in workflow.edges}
    assert ("news_wrap_up", "Msg Clear News") in edges
    assert ("news_finish", "Msg Clear News") in edges
    # The news path only ever reaches its own nodes, the analyst and its clear.
    for source, target in edges:
        if source.startswith("news_") or source == "News Analyst":
            assert target.startswith("news_") or target in {
                "News Analyst",
                "Msg Clear News",
            }, (source, target)


@pytest.mark.unit
def test_news_record_is_isolated_in_one_state():
    """Charging a news round leaves the other analysts' records untouched."""
    cfg = _all_three_enabled(news_rounds=2, news_calls=4)
    market_scope = {
        "analyst": "market",
        "run_id": "run-test",
        "rounds": 2,
        "requested": 2,
        "executed": 1,
        "reused": 0,
        "blocked": 1,
        "finished": False,
        "closed": True,
    }
    fundamentals_scope = {
        "analyst": "fundamentals",
        "run_id": "run-test",
        "rounds": 1,
        "requested": 1,
        "executed": 1,
        "reused": 0,
        "blocked": 0,
        "finished": True,
        "closed": True,
        "results": {"f1": {"status": "error", "text": "FUNDAMENTALS DATA"}},
    }
    state = _initial(cfg)
    state["tool_governance"] = {
        "run_id": "run-test",
        "analysts": {"market": market_scope, "fundamentals": fundamentals_scope},
    }
    state["messages"] = [_ai(_call("c1", "get_news", NEWS))]
    nodes = ntg.create_news_governance_nodes(
        llm=ScriptedModel([]), tool_node=ToolNode(NEWS_TOOL_OBJECTS)
    )
    governance = nodes["prepare"](state)["tool_governance"]

    news_scope = governance["analysts"]["news"]
    assert news_scope["rounds"] == 1
    assert news_scope["run_id"] == "run-test", "the run id is shared, not re-minted"
    assert governance["analysts"]["market"] == market_scope
    assert governance["analysts"]["fundamentals"] == fundamentals_scope
    assert news_scope is not market_scope
    assert news_scope is not fundamentals_scope
    # Nothing from the other analysts' results leaks into the news record.
    assert "f1" not in (news_scope.get("results") or {})


@pytest.mark.unit
def test_news_finish_writes_only_the_news_report():
    cfg = _enabled()
    state = _initial(cfg)
    state["market_report"] = "MARKET REPORT"
    state["fundamentals_report"] = "FUNDAMENTALS REPORT"
    state["sentiment_report"] = "SENTIMENT REPORT"
    state["messages"] = [_ai(text="NEWS FINAL")]
    nodes = ntg.create_news_governance_nodes(
        llm=ScriptedModel([]), tool_node=ToolNode(NEWS_TOOL_OBJECTS)
    )
    update = nodes["finish"](state)
    assert update["news_report"] == "NEWS FINAL"
    assert "market_report" not in update
    assert "fundamentals_report" not in update
    assert "sentiment_report" not in update


@pytest.mark.unit
def test_two_runs_have_independent_counters():
    cfg = _enabled(max_rounds=4, max_calls=10)
    responses = [
        _ai(_call("c1", "get_news", NEWS)),
        _ai(_call("c2", "get_news", NEWS)),
        AIMessage("FINAL: one article set"),
    ]
    out_a, _, gov_a, _ = _run(cfg, responses, run_id="run-a")
    out_b, _, gov_b, _ = _run(cfg, responses, run_id="run-b")

    assert out_a == out_b == "FINAL: one article set"
    for gov, run_id in ((gov_a, "run-a"), (gov_b, "run-b")):
        scope = gov["analysts"]["news"]
        assert scope["run_id"] == run_id
        # Success reuse is off: the repeated call is neither cached nor
        # inherited, so each run made its own call and the repeat was blocked.
        assert scope["rounds"] == 2
        assert scope["executed"] == 1
        assert scope["reused"] == 0
        assert scope["blocked"] == 1
        assert scope["cache"] == {}
    assert gov_a["analysts"]["news"]["run_id"] != gov_b["analysts"]["news"]["run_id"]


# ---------------------------------------------------------------------------
# Checkpoint signature distinguishes the news switch
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_run_signature_distinguishes_the_news_switch():
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = object.__new__(TradingAgentsGraph)
    graph.selected_analysts = ("news",)
    base_cfg = {"max_debate_rounds": 1, "max_risk_discuss_rounds": 1}
    graph.config = dict(base_cfg)
    base = graph._run_signature("stock")
    assert "news_gov=False" in base

    graph.config = {**base_cfg, "news_tool_governance": {"enabled": True}}
    with_n = graph._run_signature("stock")
    assert with_n != base
    assert "news_gov=True" in with_n
    # Stable for identical config.
    assert with_n == graph._run_signature("stock")
    # The market switch also changes the signature, independently.
    graph.config = {**base_cfg, "market_tool_governance": {"enabled": True}}
    with_m = graph._run_signature("stock")
    assert with_m != base
    assert "market_gov=True" in with_m and "news_gov=False" in with_m
    # And with fundamentals news stays visible on its own.
    graph.config = {**base_cfg, "fundamentals_tool_governance": {"enabled": True}}
    with_f = graph._run_signature("stock")
    assert "fundamentals_gov=True" in with_f and "news_gov=False" in with_f
