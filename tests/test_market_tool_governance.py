"""Offline tests for the opt-in market-analyst tool governance.

The suite builds a **real** market graph slice (the market analyst, the three
governance nodes, the msg-clear node) on a scripted model and fake tools, so the
state-update and message-merge mechanics exercised are the ones the production
graph uses. No network, no vendor, no real LLM.

Covered:

* the switch is off by default and its shape is the old one;
* a normal run finishes early on the analyst's own text;
* repeated identical requests, all-reuse and all-block each terminate;
* a round with more tools than the remaining call allowance never overruns it;
* the final round pairs every ``tool_call_id``;
* after a batch executes, the router decides the next step: the analyst while
  rounds remain, ``market_wrap_up`` directly once the allowance is spent (no
  extra analyst generation), with both caps verified on the real graph;
* an unusable analyst answer (refusal / explicit truncation / blank) fails at
  the first response -- no wrap-up generation, no stored report;
* the wrap-up is called exactly once, runs no tool, writes ``market_report`` and
  leaves the loop (a tool call from it fails instead of looping);
* a tool exception after registration keeps the saved round and a resume does
  not charge it again;
* two runs have independent counters and caches.
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

from tradingagents.agents.analysts import market_analyst as market_module
from tradingagents.agents.utils import (
    core_stock_tools,
    market_data_validation_tools,
    technical_indicators_tools,
)
from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.agents.utils.agent_utils import create_msg_delete
from tradingagents.dataflows.config import set_config
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph import market_tool_governance as mtg
from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.market_governance import parse_market_tool_governance
from tradingagents.graph.setup import GraphSetup

TRADE_DATE = "2026-08-14"
STOCK = {"symbol": "AAPL", "start_date": "2026-08-01", "end_date": TRADE_DATE}
RSI = {"symbol": "AAPL", "indicator": "rsi", "curr_date": TRADE_DATE}

TOOLS = [
    core_stock_tools.get_stock_data,
    technical_indicators_tools.get_indicators,
    market_data_validation_tools.get_verified_market_snapshot,
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

    Unlike the base fake model, this one **stops at the last response** instead
    of cycling: a test must never silently replay a tool-call response where a
    final text answer was scripted. It also records what each invocation was
    sent, so a test can assert on the wrap-up prompt.
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


class _CountingToolNode:
    """Wraps a real ``ToolNode`` and records every dispatch (for isolation)."""

    def __init__(self, tools):
        self.inner = ToolNode(tools)
        self.tools_by_name = self.inner.tools_by_name
        self.rounds = []

    def __call__(self, state):
        return self.inner.invoke(state)


def _config(**overrides):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["data_cache_dir"] = tempfile.mkdtemp()
    cfg["results_dir"] = tempfile.mkdtemp()
    cfg.update(overrides)
    return cfg


def _enabled(*, max_rounds=4, max_calls=10, **overrides):
    return _config(
        market_tool_governance={
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


def _market_slice(cfg, responses, *, tools=None, tool_node=None):
    """Compile the real market slice of the graph on a scripted model."""
    set_config(cfg)
    llm = ScriptedModel(responses)
    tools = tools if tools is not None else TOOLS
    node = tool_node if tool_node is not None else ToolNode(tools)
    with (
        patch.object(market_module, "get_stock_data", tools[0]),
        patch.object(market_module, "get_indicators", tools[1]),
        patch.object(
            market_module, "get_verified_market_snapshot", tools[2]
        ),
    ):
        analyst = market_module.create_market_analyst(llm)
    nodes = mtg.create_market_governance_nodes(llm=llm, tool_node=node)

    graph = StateGraph(AgentState)
    graph.add_node("Market Analyst", analyst)
    graph.add_node("Msg Clear Market", create_msg_delete())
    graph.add_node("market_tool_prepare", nodes["prepare"])
    graph.add_node("market_tool_execute", nodes["execute"])
    graph.add_node("market_finish", nodes["finish"])
    graph.add_node("market_wrap_up", nodes["wrap_up"])
    graph.add_edge(START, "Market Analyst")

    logic = ConditionalLogic()
    graph.add_conditional_edges(
        "Market Analyst",
        logic.should_continue_market_governed,
        ["market_tool_prepare", "market_wrap_up", "market_finish"],
    )
    graph.add_conditional_edges(
        "market_tool_prepare",
        logic.should_execute_market_prepared,
        ["market_tool_execute", "market_wrap_up", "Market Analyst"],
    )
    graph.add_conditional_edges(
        "market_tool_execute",
        logic.should_continue_market_after_execute,
        ["Market Analyst", "market_wrap_up"],
    )
    graph.add_edge("market_finish", "Msg Clear Market")
    graph.add_edge("market_wrap_up", "Msg Clear Market")
    graph.add_edge("Msg Clear Market", END)
    return graph.compile(), llm


def _vendor(cfg, *, stock=None, indicators=None):
    """Patch the routers the fake tools call (no network)."""
    stock_text = stock or (lambda m, *a: f"OHLCV rows for {a[0]}")
    ind_text = indicators or (lambda m, *a: f"{a[2]} for {a[0]}: 42")
    return (
        patch.object(core_stock_tools, "route_to_vendor", stock_text),
        patch.object(technical_indicators_tools, "route_to_vendor", ind_text),
    )


def _run(cfg, responses, *, run_id="run-test", tools=None, tool_node=None, **kwargs):
    graph, llm = _market_slice(cfg, responses, tools=tools, tool_node=tool_node)
    stock, indicators = _vendor(cfg)
    with stock, indicators:
        out = graph.invoke(_initial(cfg, run_id), {"recursion_limit": 80})
    return out, llm


def _scope(out):
    return out["tool_governance"]["analysts"]["market"]


_WRAP_UP_SENTINEL = "The tool-call allowance for this run is spent"
_ANALYST_SENTINEL = "You are a trading assistant tasked with analyzing financial markets"


def _system_text(sent):
    """The system prompt of one recorded model invocation."""
    return "\n".join(
        message.content
        for message in sent
        if isinstance(message, SystemMessage) and isinstance(message.content, str)
    )


def _requested_wrap_up(sent):
    """Whether this invocation was the single wrap-up, not the analyst turn."""
    system = _system_text(sent)
    return _WRAP_UP_SENTINEL in system and _ANALYST_SENTINEL not in system


def _requested_analyst(sent):
    """Whether this invocation was the normal analyst turn."""
    system = _system_text(sent)
    return _ANALYST_SENTINEL in system and _WRAP_UP_SENTINEL not in system


# ---------------------------------------------------------------------------
# Toggle
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_governance_is_off_by_default():
    assert parse_market_tool_governance(DEFAULT_CONFIG).enabled is False
    assert parse_market_tool_governance(None).enabled is False
    assert parse_market_tool_governance({}).enabled is False


@pytest.mark.unit
def test_disabled_section_ignores_caps():
    parsed = parse_market_tool_governance(
        {"market_tool_governance": {"enabled": False, "max_rounds": 9}}
    )
    assert parsed.enabled is False
    assert parsed.max_rounds is None and parsed.max_calls is None


@pytest.mark.unit
def test_enabled_caps_default_when_omitted():
    parsed = parse_market_tool_governance({"market_tool_governance": {"enabled": True}})
    assert parsed.enabled is True
    assert parsed.max_rounds == 4 and parsed.max_calls == 10
    limits = parsed.limits()
    assert (limits.max_rounds, limits.max_calls) == (4, 10)


@pytest.mark.unit
@pytest.mark.parametrize(
    "section",
    [
        {"enabled": True, "max_rounds": None},
        {"enabled": True, "max_calls": None},
        {"enabled": True, "max_rounds": None, "max_calls": None},
        # A partial section still cannot leave the other cap open.
        {"enabled": True, "max_calls": None, "max_rounds": 3},
        {"enabled": True, "max_rounds": None, "max_calls": 5},
    ],
)
def test_explicit_none_cap_is_refused_when_enabled(section):
    """Enabling governance cannot accidentally remove a cap.

    ``None`` under the positive-int contract means "no cap"; only *omitting*
    the key selects the finite default, so an explicit ``None`` must be
    refused -- and refused even when only one of the two caps is ``None``.
    """
    with pytest.raises(ValueError, match="positive int"):
        parse_market_tool_governance({"market_tool_governance": section})


@pytest.mark.unit
def test_dataclass_refuses_enabled_without_finite_caps():
    """The validated object itself cannot represent enabled-without-cap."""
    from tradingagents.graph.market_governance import MarketToolGovernance

    with pytest.raises(ValueError, match="max_rounds"):
        MarketToolGovernance(enabled=True, max_rounds=None, max_calls=5)
    with pytest.raises(ValueError, match="max_calls"):
        MarketToolGovernance(enabled=True, max_rounds=4, max_calls=None)
    ok = MarketToolGovernance(enabled=True, max_rounds=4, max_calls=10)
    assert (ok.max_rounds, ok.max_calls) == (4, 10)


@pytest.mark.unit
def test_partial_enabled_section_fills_the_other_cap_with_its_default():
    parsed = parse_market_tool_governance(
        {"market_tool_governance": {"enabled": True, "max_calls": 3}}
    )
    assert (parsed.max_rounds, parsed.max_calls) == (4, 3)


@pytest.mark.unit
def test_default_config_enables_no_unbounded_state():
    from tradingagents.default_config import DEFAULT_CONFIG

    section = DEFAULT_CONFIG["market_tool_governance"]
    assert section["max_rounds"] == 4 and section["max_calls"] == 10
    enabled = parse_market_tool_governance(
        {"market_tool_governance": {**section, "enabled": True}}
    )
    assert enabled.enabled is True
    assert enabled.max_rounds and enabled.max_calls


@pytest.mark.unit
@pytest.mark.parametrize(
    "section",
    [
        {"enabled": True, "max_rounds": 0},
        {"enabled": True, "max_rounds": -1},
        {"enabled": True, "max_rounds": 2.5},
        {"enabled": True, "max_rounds": True},
        {"enabled": True, "max_calls": 0},
        {"enabled": True, "max_calls": "3"},
        {"enabled": True, "typo_key": 1},
        {"enabled": "yes"},
        {"enabled": 1},
    ],
)
def test_invalid_toggle_values_are_refused(section):
    with pytest.raises(ValueError):
        parse_market_tool_governance({"market_tool_governance": section})


@pytest.mark.unit
def test_toggle_section_must_be_a_mapping():
    with pytest.raises(ValueError):
        parse_market_tool_governance({"market_tool_governance": True})


# ---------------------------------------------------------------------------
# Toggle off: today's graph
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_graph_with_governance_off_has_only_the_old_market_nodes():
    cfg = _config(market_tool_governance={"enabled": False})
    setup = GraphSetup(
        ScriptedModel([AIMessage("x")]),
        ScriptedModel([AIMessage("x")]),
        {"market": ToolNode(TOOLS)},
        ConditionalLogic(),
        config=cfg,
    )
    workflow = setup.setup_graph(("market",))
    assert "tools_market" in workflow.nodes
    assert not {"market_tool_prepare", "market_tool_execute", "market_wrap_up"} & set(
        workflow.nodes
    )
    # The analyst's plain tool node still leads back to the analyst.
    assert ("tools_market", "Market Analyst") in {
        (source, target) for source, target, *_ in workflow.edges
    }


@pytest.mark.unit
def test_graph_with_governance_on_adds_its_own_market_path():
    cfg = _enabled()
    setup = GraphSetup(
        ScriptedModel([AIMessage("x")]),
        ScriptedModel([AIMessage("x")]),
        {"market": ToolNode(TOOLS)},
        ConditionalLogic(),
        config=cfg,
    )
    workflow = setup.setup_graph(("market",))
    assert {"market_tool_prepare", "market_tool_execute", "market_wrap_up"} <= set(
        workflow.nodes
    )
    # The prepare step can send an answered batch back to the analyst, run the
    # plan, or wrap up.
    edges = {(source, target) for source, target, *_ in workflow.edges}
    assert ("market_wrap_up", "Msg Clear Market") in edges
    # The governed path never feeds the plain tool node.
    assert not any(target == "tools_market" for _, target, *_ in workflow.edges)
    # No unconditional edge leaves execute: the next step is decided there.
    assert not any(source == "market_tool_execute" for source, *_ in workflow.edges)

    compiled = workflow.compile()

    def ends(source):
        return {
            target
            for spec in compiled.builder.branches.get(source, {}).values()
            for target in (spec.ends or ())
        }

    assert {"market_tool_prepare", "market_wrap_up", "market_finish"} <= ends(
        "Market Analyst"
    )
    assert {"market_tool_execute", "market_wrap_up", "Market Analyst"} <= ends(
        "market_tool_prepare"
    )
    # After a completed batch: back to the analyst while rounds remain, or
    # straight to the single wrap-up once the allowance is spent.
    assert ends("market_tool_execute") == {"Market Analyst", "market_wrap_up"}


# ---------------------------------------------------------------------------
# Normal runs
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_analyst_finishes_early_on_its_own_report():
    cfg = _enabled(max_rounds=6, max_calls=10)
    responses = [_ai(_call("c1", "get_stock_data", STOCK)), AIMessage("ANALYST FINAL: rows based")]
    out, llm = _run(cfg, responses)

    assert out["market_report"] == "ANALYST FINAL: rows based"
    scope = _scope(out)
    assert (scope["rounds"], scope["executed"]) == (1, 1)
    assert scope["finished"] and scope["closed"]
    # No wrap-up model call: the analyst's own text is the report.
    assert llm.calls == 2


@pytest.mark.unit
def test_two_rounds_then_a_report():
    cfg = _enabled(max_rounds=4, max_calls=10)
    responses = [
        _ai(_call("c1", "get_stock_data", STOCK)),
        _ai(_call("c2", "get_indicators", RSI)),
        AIMessage("FINAL: stock rows and rsi"),
    ]
    out, _ = _run(cfg, responses)

    scope = _scope(out)
    assert (scope["rounds"], scope["executed"]) == (2, 2)
    assert out["market_report"].startswith("FINAL")


# ---------------------------------------------------------------------------
# Repetition terminates
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_repeated_identical_requests_terminate():
    cfg = _enabled(max_rounds=3, max_calls=10)
    # A real model gives each turn a fresh id; the request is identical. Round 1
    # runs it, rounds 2 and 3 are charged and blocked (success reuse is off),
    # then the model is asked for its report.
    responses = [
        _ai(_call("r0", "get_stock_data", STOCK)),
        _ai(_call("r1", "get_stock_data", STOCK)),
        _ai(_call("r2", "get_stock_data", STOCK)),
        AIMessage("FINAL: one fetch, repeats blocked"),
    ]
    out, llm = _run(cfg, responses)

    scope = _scope(out)
    assert (scope["rounds"], scope["executed"], scope["blocked"]) == (3, 1, 2)
    assert scope["finished"] and scope["closed"]
    assert out["market_report"] == "FINAL: one fetch, repeats blocked"


@pytest.mark.unit
def test_all_reuse_terminates():
    # Two identical requests in the *same* batch: the first runs, the second is
    # blocked as a duplicate in the batch (it cannot be a success reuse: see
    # ``confirms_success``), so the run is finite and every call is paired.
    cfg = _enabled(max_rounds=2, max_calls=10)
    responses = [
        _ai(_call("c1", "get_stock_data", STOCK), _call("c2", "get_stock_data", STOCK)),
        AIMessage("WRAPUP: duplicates in one batch"),
    ]
    out, llm = _run(cfg, responses)

    scope = _scope(out)
    assert scope["executed"] == 1
    assert scope["reused"] == 0
    assert scope["blocked"] == 1
    assert scope["rounds"] == 1
    assert scope["finished"] and scope["closed"]
    assert out["market_report"] == "WRAPUP: duplicates in one batch"
    paired = {m.tool_call_id for m in llm.sent[-1] if isinstance(m, ToolMessage)}
    assert paired == {"c1", "c2"}


@pytest.mark.unit
def test_all_block_each_round_terminates():
    # A call naming a tool the analyst is not bound to cannot be planned: it is
    # refused (blocked, never executed), and the run still finishes.
    cfg = _enabled(max_rounds=3, max_calls=10)
    responses = [
        _ai(
            _call("b1", "not_a_market_tool", {"symbol": "AAPL"}),
            _call("b2", "not_a_market_tool", {"symbol": "MSFT"}),
        ),
        AIMessage("WRAPUP: blocked"),
    ]
    out, _ = _run(cfg, responses)

    scope = _scope(out)
    assert scope["executed"] == 0
    assert scope["blocked"] == 2
    assert scope["closed"]
    assert out["market_report"] == "WRAPUP: blocked"


# ---------------------------------------------------------------------------
# Call cap within one round
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_one_round_with_many_tools_never_exceeds_the_call_cap():
    cfg = _enabled(max_rounds=5, max_calls=2)
    responses = [
        _ai(
            _call("a", "get_stock_data", STOCK),
            _call("b", "get_stock_data", dict(STOCK, symbol="MSFT")),
            _call("c", "get_stock_data", dict(STOCK, symbol="NVDA")),
        ),
        AIMessage("WRAPUP: cap hit"),
    ]
    out, _ = _run(cfg, responses)

    scope = _scope(out)
    assert scope["executed"] == 2  # the cap, not the three requested
    assert scope["blocked"] == 1
    assert scope["finished"] and scope["closed"]


@pytest.mark.unit
def test_default_round_allowance_executes_the_fourth_round_too():
    """The default cap is 4 rounds, and the 4th one runs its calls.

    A regression that stopped at the third round (or that blocked the round
    that spent the allowance) would leave the fourth batch unanswered. The
    check is on the real vendor record, not just the counter.
    """
    cfg = _enabled()  # defaults: max_rounds=4, max_calls=10
    seen, patches = _recording_vendor()
    symbols = ["S1", "S2", "S3", "S4"]
    responses = [
        _ai(_call(f"q{i}", "get_stock_data", dict(STOCK, symbol=s)))
        for i, s in enumerate(symbols, start=1)
    ]
    responses.append(AIMessage("WRAPUP: four rounds"))
    with patches[0], patches[1]:
        graph, llm = _market_slice(cfg, responses)
        out = graph.invoke(_initial(cfg), {"recursion_limit": 80})

    assert [args[0] for _, args in seen] == symbols, "every round ran its call"
    scope = _scope(out)
    assert (scope["rounds"], scope["executed"], scope["blocked"]) == (4, 4, 0)
    assert scope["finished"] and scope["closed"]
    assert out["market_report"] == "WRAPUP: four rounds"
    assert llm.calls == 5  # four analyst turns, then one wrap-up
    paired = {m.tool_call_id for m in llm.sent[-1] if isinstance(m, ToolMessage)}
    assert paired == {f"q{i}" for i in range(1, 5)}


@pytest.mark.unit
def test_a_new_batch_after_the_cap_is_never_requested():
    """Once the allowance is spent, the analyst is not asked for a new batch.

    With ``max_rounds=1`` and an analyst batch then an unbound wrap-up report,
    the run has exactly two model calls. The old path asked the analyst a third
    time after the cap, and its tool-call turn could then only be blocked; the
    conditional edge after execute removes that pointless generation.
    """
    cfg = _enabled(max_rounds=1, max_calls=10)
    seen, patches = _recording_vendor()
    responses = [
        _ai(_call("c1", "get_stock_data", STOCK)),
        AIMessage("WRAPUP: second batch never asked"),
    ]
    with patches[0], patches[1]:
        graph, llm = _market_slice(cfg, responses)
        out = graph.invoke(_initial(cfg), {"recursion_limit": 80})

    assert seen == [("get_stock_data", ("AAPL", "2026-08-01", TRADE_DATE))]
    scope = _scope(out)
    assert (scope["rounds"], scope["executed"], scope["blocked"]) == (1, 1, 0)
    assert out["market_report"] == "WRAPUP: second batch never asked"
    assert llm.calls == 2
    # The second call is the wrap-up prompt, not the analyst prompt.
    assert _requested_wrap_up(llm.sent[-1])
    tools = [m for m in llm.sent[-1] if isinstance(m, ToolMessage)]
    assert [m.tool_call_id for m in tools] == ["c1"]
    assert not tools[0].content.startswith(mtg.BLOCK_PREFIX)


# ---------------------------------------------------------------------------
# Fix: the last allowed round still runs what it approved
# ---------------------------------------------------------------------------


def _recording_vendor():
    """Route the fake stock/indicator tools to recorders; return the record."""
    seen = []

    def stock(m, *a):
        seen.append(("get_stock_data", a))
        return f"OHLCV rows for {a[0]}"

    def indicators(m, *a):
        seen.append(("get_indicators", a))
        return f"{a[2]} for {a[0]}: 42"

    return seen, (
        patch.object(core_stock_tools, "route_to_vendor", stock),
        patch.object(technical_indicators_tools, "route_to_vendor", indicators),
    )


@pytest.mark.unit
def test_last_allowed_round_still_executes_its_approved_calls():
    """``max_rounds=1``: round 1 runs and is paired, then the run wraps up.

    The script has exactly two answers: the batch and the (unbound) wrap-up
    report. The old unconditional ``execute -> Market Analyst`` edge asked the
    analyst again after the cap, which spent a third generation only to be told
    it could not use tools and to invent a second batch. Now the batch is
    completed and paired first, the allowance is seen to be spent, and the
    run goes straight to ``market_wrap_up`` -- since that edge was removed, a
    third response could not be consumed even if it existed.
    """
    cfg = _enabled(max_rounds=1, max_calls=10)
    seen, patches = _recording_vendor()
    responses = [
        _ai(
            _call("r1", "get_stock_data", STOCK),
            _call("r1b", "get_indicators", RSI),
        ),
        AIMessage("WRAPUP: only round one ran"),
    ]
    with patches[0], patches[1]:
        graph, llm = _market_slice(cfg, responses)
        out = graph.invoke(_initial(cfg), {"recursion_limit": 80})

    # Both approved calls of round 1 really reached their tools.
    assert [name for name, _ in seen] == ["get_stock_data", "get_indicators"]
    assert seen[0][1][0] == "AAPL"
    assert seen[1][1][:3] == ("AAPL", "rsi", TRADE_DATE)
    scope = _scope(out)
    # Round 1 ran its two calls; no later batch was attempted.
    assert (scope["rounds"], scope["executed"], scope["blocked"]) == (1, 2, 0)
    assert scope["finished"] and scope["closed"]
    assert out["market_report"] == "WRAPUP: only round one ran"
    # Two model calls: the analyst's batch and the single wrap-up.
    assert llm.calls == 2
    # Both calls are paired in the wrap-up prompt.
    paired = {m.tool_call_id for m in llm.sent[-1] if isinstance(m, ToolMessage)}
    assert paired == {"r1", "r1b"}


@pytest.mark.unit
def test_call_cap_executes_exactly_one_and_blocks_the_rest_with_messages():
    """``max_calls=1``: one real call runs, the others get block messages.

    The pairing is checked on the graph's own message stream: every call id
    has exactly one ``ToolMessage``, the blocked ones start with the block
    marker, and only the approved call reached the vendor.
    """
    cfg = _enabled(max_rounds=5, max_calls=1)
    seen, patches = _recording_vendor()
    responses = [
        _ai(
            _call("p1", "get_stock_data", STOCK),
            _call("p2", "get_indicators", RSI),
            _call("p3", "get_stock_data", dict(STOCK, symbol="MSFT")),
        ),
        AIMessage("WRAPUP: cap hit"),
    ]
    captured = {}
    with patches[0], patches[1]:
        graph, llm = _market_slice(cfg, responses)
        # Capture the graph's messages before ``Msg Clear Market`` wipes them.
        for step in graph.stream(_initial(cfg), {"recursion_limit": 80}):
            for update in step.values():
                if isinstance(update, dict) and "messages" in update:
                    captured.setdefault("messages", []).extend(update["messages"])
                    captured["report"] = update.get(
                        "market_report", captured.get("report")
                    )
                    if "tool_governance" in update:
                        captured["scope"] = update["tool_governance"]["analysts"]["market"]

    # Exactly one approved call ran -- the first one.
    assert seen == [("get_stock_data", ("AAPL", "2026-08-01", TRADE_DATE))]
    tools = [m for m in captured["messages"] if isinstance(m, ToolMessage)]
    assert [m.tool_call_id for m in tools] == ["p1", "p2", "p3"]
    assert not tools[0].content.startswith(mtg.BLOCK_PREFIX)
    for blocked in tools[1:]:
        assert blocked.content.startswith(mtg.BLOCK_PREFIX)
    assert captured["report"] == "WRAPUP: cap hit"
    scope = captured["scope"]
    assert (scope["rounds"], scope["executed"], scope["blocked"]) == (1, 1, 2)
    # Exactly two model calls: the batch and the single wrap-up -- the call cap
    # spent inside round 1 also closes the loop.
    assert llm.calls == 2
    # The wrap-up saw a paired message for every call of the batch.
    paired = {m.tool_call_id for m in llm.sent[-1] if isinstance(m, ToolMessage)}
    assert paired == {"p1", "p2", "p3"}


# ---------------------------------------------------------------------------
# Fix: conditional edge after execute (no analyst turn once the cap is spent)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_max_rounds_one_runs_the_batch_then_wraps_up_without_another_turn():
    """Real graph, ``max_rounds=1``: batch first, then the wrap-up directly.

    The script has only two answers -- the analyst's tool request and the
    unbound wrap-up model's report -- so a third analyst turn could not be
    served even if the edge still existed. The assertions pin the whole path:
    the tool really ran, there are exactly two model calls, and the second one
    is the wrap-up prompt (not the analyst prompt) and already holds the
    paired tool result.
    """
    cfg = _enabled(max_rounds=1, max_calls=10)
    seen, patches = _recording_vendor()
    responses = [
        _ai(_call("c1", "get_stock_data", STOCK)),
        AIMessage("WRAPUP: report from round one"),
    ]
    with patches[0], patches[1]:
        graph, llm = _market_slice(cfg, responses)
        out = graph.invoke(_initial(cfg), {"recursion_limit": 80})

    assert seen == [("get_stock_data", ("AAPL", "2026-08-01", TRADE_DATE))]
    assert llm.calls == 2
    assert _requested_analyst(llm.sent[0])
    assert _requested_wrap_up(llm.sent[1]), "the second call is the wrap-up"
    # ``Msg Clear Market`` wiped the graph's messages; the wrap-up prompt still
    # carries the paired result of the call that ran.
    tools = [m for m in llm.sent[1] if isinstance(m, ToolMessage)]
    assert [m.tool_call_id for m in tools] == ["c1"]
    assert tools[0].content == "OHLCV rows for AAPL"
    assert out["market_report"] == "WRAPUP: report from round one"
    scope = _scope(out)
    assert (scope["rounds"], scope["executed"]) == (1, 1)
    assert scope["finished"] and scope["closed"]


@pytest.mark.unit
def test_max_calls_spent_mid_batch_wraps_up_without_another_turn():
    """Real graph, ``max_calls=1``: the batch is answered, then wrap-up.

    Round 1 approves one call and blocks the other two; both block messages are
    emitted before the routing decision, so the wrap-up prompt is fully paired.
    The cap spent by that execution sends the run straight to
    ``market_wrap_up``: exactly two model calls, the second one the wrap-up.
    """
    cfg = _enabled(max_rounds=5, max_calls=1)
    seen, patches = _recording_vendor()
    responses = [
        _ai(
            _call("p1", "get_stock_data", STOCK),
            _call("p2", "get_indicators", RSI),
            _call("p3", "get_stock_data", dict(STOCK, symbol="MSFT")),
        ),
        AIMessage("WRAPUP: one call ran, two blocked"),
    ]
    with patches[0], patches[1]:
        graph, llm = _market_slice(cfg, responses)
        out = graph.invoke(_initial(cfg), {"recursion_limit": 80})

    assert seen == [("get_stock_data", ("AAPL", "2026-08-01", TRADE_DATE))]
    assert llm.calls == 2
    assert _requested_analyst(llm.sent[0])
    assert _requested_wrap_up(llm.sent[1]), "the second call is the wrap-up"
    tools = [m for m in llm.sent[1] if isinstance(m, ToolMessage)]
    assert [m.tool_call_id for m in tools] == ["p1", "p2", "p3"]
    assert not tools[0].content.startswith(mtg.BLOCK_PREFIX)
    for blocked in tools[1:]:
        assert blocked.content.startswith(mtg.BLOCK_PREFIX)
    assert out["market_report"] == "WRAPUP: one call ran, two blocked"
    scope = _scope(out)
    assert (scope["rounds"], scope["executed"], scope["blocked"]) == (1, 1, 2)
    assert scope["closed"] and scope["finished"]



@pytest.mark.unit
def test_final_round_pairs_every_tool_call_id():
    # A call cap of 1 leaves the second call of the round un-runnable: it is
    # paired (blocked) and the report is written from what ran.
    cfg = _enabled(max_rounds=5, max_calls=1)
    responses = [
        _ai(_call("p1", "get_stock_data", STOCK), _call("p2", "get_indicators", RSI)),
        AIMessage("WRAPUP: one round only"),
    ]
    out, llm = _run(cfg, responses)

    wrap_prompt = llm.sent[-1]
    paired = [m.tool_call_id for m in wrap_prompt if isinstance(m, ToolMessage)]
    assert sorted(paired) == ["p1", "p2"]
    assert len(paired) == len(set(paired))
    scope = _scope(out)
    assert scope["executed"] == 1 and scope["blocked"] == 1
    assert out["market_report"] == "WRAPUP: one round only"


# ---------------------------------------------------------------------------
# Wrap-up
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_wrap_up_is_called_once_and_runs_no_tool():
    cfg = _enabled(max_rounds=2, max_calls=10)
    responses = [
        _ai(_call("c1", "get_stock_data", STOCK)),
        _ai(_call("c2", "get_indicators", RSI)),
        AIMessage("WRAPUP: report from evidence"),
    ]
    calls_seen = []

    def stock(m, *a):
        calls_seen.append(("stock", a[0]))
        return "OHLCV rows"

    def indicators(m, *a):
        calls_seen.append(("ind", a[0]))
        return "rsi 42"

    with patch.object(core_stock_tools, "route_to_vendor", stock), patch.object(
        technical_indicators_tools, "route_to_vendor", indicators
    ):
        graph, llm = _market_slice(cfg, responses)
        out = graph.invoke(_initial(cfg), {"recursion_limit": 80})

    # Two analyst requests, then exactly one wrap-up answer.
    assert llm.calls == 3
    # Round 2 *is* the last allowed round: the cap forbids a new batch, it does
    # not revoke the call that round already approved. Both calls really run.
    assert calls_seen == [("stock", "AAPL"), ("ind", "AAPL")]
    scope = _scope(out)
    assert (scope["rounds"], scope["executed"]) == (2, 2)
    assert scope["finished"] and scope["closed"]
    assert out["market_report"] == "WRAPUP: report from evidence"
    # The wrap-up never ran a tool and was handed paired results.
    paired = {
        m.tool_call_id for m in llm.sent[-1] if isinstance(m, ToolMessage)
    }
    assert paired == {"c1", "c2"}


@pytest.mark.unit
def test_wrap_up_asking_for_tools_fails_instead_of_looping():
    cfg = _enabled(max_rounds=1, max_calls=10)
    responses = [
        _ai(_call("c1", "get_stock_data", STOCK)),
        _ai(_call("c2", "get_indicators", RSI), text="more tools"),
    ]
    with pytest.raises(mtg.MarketGovernanceError, match="asked for tools"):
        _run(cfg, responses)


@pytest.mark.unit
def test_wrap_up_with_an_empty_answer_fails():
    cfg = _enabled(max_rounds=1, max_calls=10)
    responses = [_ai(_call("c1", "get_stock_data", STOCK)), AIMessage("   ")]
    with pytest.raises(mtg.MarketGovernanceError, match="no content|empty"):
        _run(cfg, responses)


# ---------------------------------------------------------------------------
# Fix: refusal / truncation / blank never becomes the report
# ---------------------------------------------------------------------------


def _direct_nodes():
    """The governance nodes alone, over a tool node the calls never reach."""
    return mtg.create_market_governance_nodes(
        llm=ScriptedModel([]), tool_node=ToolNode(TOOLS)
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "response",
    [
        AIMessage(
            content="",
            additional_kwargs={"refusal": "I cannot provide trading advice."},
        ),
        AIMessage(
            content=[{"type": "refusal", "refusal": "I won't analyse this."}]
        ),
        AIMessage(
            content="MARKET REPORT SO FAR",
            response_metadata={"finish_reason": "length"},
        ),
        AIMessage(
            content="partial",
            additional_kwargs={"finish_reason": "max_tokens"},
        ),
        AIMessage(content=""),
        AIMessage(content="   \n  "),
    ],
    ids=[
        "refusal-additional-kwargs",
        "refusal-content-block",
        "truncated-finish-reason",
        "truncated-max-tokens",
        "empty-string",
        "blank",
    ],
)
def test_finish_rejects_a_refusal_truncation_or_blank(response):
    """The analyst's own text is held to the same rules as the wrap-up."""
    state = _initial(_enabled())
    state["messages"] = [response]
    with pytest.raises(mtg.MarketGovernanceError):
        _direct_nodes()["finish"](state)
    # ``analyst_report`` reports nothing usable, so the router never sends a
    # refusal to finish in the first place.
    assert mtg.analyst_report(response) == ""


@pytest.mark.unit
@pytest.mark.parametrize(
    "response",
    [
        AIMessage(
            content="",
            response_metadata={"finish_reason": "length"},
        ),
        AIMessage(
            content=[{"type": "refusal", "refusal": "no"}],
        ),
        AIMessage(content=""),
    ],
    ids=["truncated", "refused", "blank"],
)
def test_wrap_up_rejects_a_refusal_truncation_or_blank(response):
    """The single generation is never saved when it is unusable."""
    state = _initial(_enabled())
    state["messages"] = [_ai(_call("c1", "get_stock_data", STOCK))]
    nodes = mtg.create_market_governance_nodes(
        llm=ScriptedModel([response]),
        tool_node=ToolNode(TOOLS),
    )
    with pytest.raises(mtg.MarketGovernanceError):
        nodes["wrap_up"](state)


@pytest.mark.unit
def test_finish_and_wrap_up_store_nothing_on_failure():
    """No ``market_report``, not ``finished``, and no second generation."""
    state = _initial(_enabled())
    state["messages"] = [AIMessage(content="", additional_kwargs={"refusal": "no"})]
    with pytest.raises(mtg.MarketGovernanceError):
        _direct_nodes()["finish"](state)
    assert state["market_report"] == "", "a refusal is not a report"
    assert not (state.get("tool_governance") or {}).get("analysts")

    # The wrap-up: a refusing model is invoked exactly once.
    state = _initial(_enabled())
    state["messages"] = [_ai(_call("c1", "get_stock_data", STOCK))]
    llm = ScriptedModel(
        [AIMessage(content="", additional_kwargs={"refusal": "no"})]
    )
    nodes = mtg.create_market_governance_nodes(llm=llm, tool_node=ToolNode(TOOLS))
    with pytest.raises(mtg.MarketGovernanceError):
        nodes["wrap_up"](state)
    assert llm.calls == 1, "a refusal is final: no second generation"


@pytest.mark.unit
def test_analyst_refusal_in_the_graph_fails_instead_of_becoming_the_report():
    """End to end: a refusing analyst turn fails the run immediately.

    The script has a normal report as a **decoy** second answer: if the
    refusal were routed to the wrap-up, that decoy would be spent and stored
    as ``market_report``. It must not be: the refusal is final, exactly one
    model call is made, and nothing is written.
    """
    cfg = _enabled(max_rounds=2, max_calls=10)
    responses = [
        AIMessage(
            content="", additional_kwargs={"refusal": "I can't help with that."}
        ),
        AIMessage("DECOY: this report must never be requested"),
    ]
    seen, patches = _recording_vendor()
    with patches[0], patches[1]:
        graph, llm = _market_slice(cfg, responses)
        with pytest.raises(mtg.MarketGovernanceError):
            graph.invoke(_initial(cfg), {"recursion_limit": 80})
    assert seen == [], "a refusal is not a reason to run tools"
    assert llm.calls == 1


_BAD_ANALYST_ANSWERS = {
    "refusal": AIMessage(
        content="", additional_kwargs={"refusal": "I can't help with that."}
    ),
    "truncated": AIMessage(
        content="MARKET REPORT: the trend is up and",
        response_metadata={"finish_reason": "length"},
    ),
    "empty": AIMessage(content=""),
}


@pytest.mark.unit
@pytest.mark.parametrize("kind", sorted(_BAD_ANALYST_ANSWERS))
def test_unusable_analyst_answer_fails_before_any_second_request(kind):
    """Real graph: refusal / truncation / blank fails after one model call.

    A normal report is scripted as a **decoy** second answer. If the router
    treated the unusable turn as "needs a wrap-up", the decoy would be spent
    and stored as ``market_report``. Instead the run raises at the first
    answer: ``llm.calls == 1``, no report is saved, and the analyst is not
    marked ``finished``. The state is inspected before ``Msg Clear Market``,
    which would otherwise wipe the messages.
    """
    cfg = _enabled(max_rounds=2, max_calls=10)
    seen, patches = _recording_vendor()
    responses = [
        _BAD_ANALYST_ANSWERS[kind],
        AIMessage("DECOY: this report must never be requested"),
    ]
    updates = {"market_report": None}
    with patches[0], patches[1]:
        graph, llm = _market_slice(cfg, responses)
        with pytest.raises(mtg.MarketGovernanceError):
            for step in graph.stream(
                _initial(cfg), {"recursion_limit": 80}, stream_mode="updates"
            ):
                for node, update in step.items():
                    assert node != "Msg Clear Market"
                    if isinstance(update, dict) and "market_report" in update:
                        updates["market_report"] = update["market_report"]

    assert llm.calls == 1, "the decoy must not be requested"
    assert seen == [], "no tool may run after an unusable answer"
    assert not updates["market_report"], "nothing may be saved as the market report"
    # Not finished: the only observed update is the analyst's own turn (it
    # writes no governance state); only ``market_finish``/``market_wrap_up``
    # mark the analyst finished, and neither ran.
    assert len(llm.sent) == 1
    # The decoy's text never entered the conversation either.
    assert all(
        "DECOY" not in str(message.content) for sent in llm.sent for message in sent
    )


@pytest.mark.unit
def test_a_tool_call_still_enters_governance_and_text_still_finishes():
    """The stricter router does not disturb the two legitimate branches."""
    cfg = _enabled(max_rounds=2, max_calls=10)
    responses = [
        _ai(_call("c1", "get_stock_data", STOCK)),  # tools -> prepare
        AIMessage("ANALYST FINAL: written by the analyst"),  # text -> finish
    ]
    seen, patches = _recording_vendor()
    with patches[0], patches[1]:
        graph, llm = _market_slice(cfg, responses)
        out = graph.invoke(_initial(cfg), {"recursion_limit": 80})

    assert seen == [("get_stock_data", ("AAPL", "2026-08-01", TRADE_DATE))]
    assert llm.calls == 2
    assert _requested_analyst(llm.sent[1])
    assert out["market_report"] == "ANALYST FINAL: written by the analyst"
    assert _scope(out)["finished"]


@pytest.mark.unit
def test_a_valid_report_with_a_stop_finish_reason_is_kept():
    """The guard does not reject a normal answer (no false positives)."""
    message = AIMessage(
        content="MARKET REPORT\n\n**Summary**",
        response_metadata={"finish_reason": "stop"},
    )
    state = _initial(_enabled())
    state["messages"] = [message]
    update = _direct_nodes()["finish"](state)
    assert update["market_report"] == "MARKET REPORT\n\n**Summary**"
    assert update["tool_governance"]["analysts"]["market"]["finished"] is True


# ---------------------------------------------------------------------------
# Fix: success reuse needs explicit evidence (off by default)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "text",
    [
        "A generic note that is not a data confirmation.",
        "No recent data was found for this symbol.",
        "WARNING: upstream returned an unexpected payload.",
        "{}",
    ],
)
def test_unknown_text_is_not_confirmed_as_success(text):
    """Unknown text never becomes a cached success.

    ``confirms_success`` is the only source of a success claim; an
    unrecognised non-empty text must not be promoted to one.
    """
    call = _call("c1", "get_stock_data", STOCK)
    message = {"tool_call_id": "c1", "name": "get_stock_data", "content": text}
    assert mtg.confirms_success(call, message) is False


@pytest.mark.unit
def test_market_confirmer_does_not_confirm_even_an_error_free_result():
    call = _call("c1", "get_stock_data", STOCK)
    ok = {
        "tool_call_id": "c1",
        "name": "get_stock_data",
        "content": "Date,Open,High,Low,Close,Volume\n2026-08-14,1,2,0.5,1.5,100",
        "status": "success",
    }
    assert mtg.confirms_success(call, ok) is False


@pytest.mark.unit
def test_explicitly_confirmed_valid_result_is_reusable():
    """With explicit evidence, the same request is served from cache.

    Uses the executor directly so the confirmer is the *explicit* one; this is
    the behaviour the market confirmer is expected to enable once a tool can
    vouch for its payload.
    """
    from tradingagents.agents.utils.tool_governance import (
        ToolContext,
        ToolExecutor,
        ToolLimits,
        new_state,
    )

    calls = []

    def tool(symbol, start_date, end_date):
        calls.append(symbol)
        return "Date,Open,High,Low,Close,Volume\n2026-08-14,1,2,0.5,1.5,100"

    tool.name = "get_stock_data"
    tool.tool_call_schema = core_stock_tools.get_stock_data.tool_call_schema

    def explicit(call, message):
        return str(message.get("content", "")).startswith("Date,Open")

    run_state = {"trade_date": TRADE_DATE}

    def runner(node, batch, *, state, config):
        # Dispatch subset: answer each execute call (no real ToolNode needed).
        return [
            ToolMessage(
                content=tool(c["args"]["symbol"], "", ""),
                tool_call_id=c["id"],
                name=c["name"],
            )
            for c in batch
        ]

    executor = ToolExecutor(
        [tool],
        node=ToolNode([]),
        analyst="market",
        run_id="run-cache",
        limits=ToolLimits(max_rounds=4, max_calls=10),
        context=ToolContext(analyst="market", run_id="run-cache", instrument="AAPL"),
        confirms_success=explicit,
        runner=runner,
    )
    first = _call("a1", "get_stock_data", STOCK)
    second = _call("a2", "get_stock_data", STOCK)
    state = new_state("run-cache")
    prepared = executor.prepare(state, [first], run_state=run_state, config={})
    execution = executor.execute(prepared)
    scope = execution.scope
    assert scope["cache"], "an explicitly confirmed result is cached"

    prepared2 = executor.prepare(
        execution.state["tool_governance"], [second], run_state=run_state, config={}
    )
    execution2 = executor.execute(prepared2)
    assert execution2.scope["reused"] == 1
    assert calls == ["AAPL"], "the second identical request ran no tool"


@pytest.mark.unit
def test_market_run_never_serves_a_cached_success():
    """The market confirmer means a repeat is blocked, never served as success."""
    cfg = _enabled(max_rounds=4, max_calls=10)
    seen, patches = _recording_vendor()
    responses = [
        _ai(_call("c1", "get_stock_data", STOCK)),
        _ai(_call("c2", "get_stock_data", STOCK)),
        AIMessage("WRAPUP: repeat blocked"),
    ]
    with patches[0], patches[1]:
        graph, llm = _market_slice(cfg, responses)
        out = graph.invoke(_initial(cfg), {"recursion_limit": 80})
    assert len(seen) == 1
    scope = _scope(out)
    assert scope["reused"] == 0
    assert scope["cache"] == {}
    assert scope["blocked"] == 1


# ---------------------------------------------------------------------------
# Register before execute: an exception does not re-charge
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_tool_exception_keeps_registration_and_resume_does_not_recharge():
    """The round is saved before it runs, so a crash cannot charge it twice.

    The prepare node's update is applied to graph state (this is the
    registration the graph saves), then the execute node dispatches and the
    tool blows up. Re-running the execute node -- what a resume does -- must
    neither spend a second round nor lose the saved plan.
    """
    cfg = _enabled(max_rounds=3, max_calls=10)
    state = _initial(cfg)
    node = ToolNode(TOOLS)
    nodes = mtg.create_market_governance_nodes(llm=ScriptedModel([]), tool_node=node)

    state["messages"] = [_ai(_call("c1", "get_stock_data", STOCK))]

    # 1) Prepare registers the round and saves it: nothing has run yet.
    saved = nodes["prepare"](state)
    state.update(saved)
    scope = state["tool_governance"]["analysts"]["market"]
    assert scope["rounds"] == 1
    assert scope["executed"] == 1  # charged for the call it intends to run
    assert str(scope["charged_rounds"]), "the charge marker must be saved"

    # 2) Execute dispatches the saved round and the tool raises.
    def crash(*args, **kwargs):
        raise RuntimeError("vendor exploded")

    ok_stock, ok_indicators = _vendor(cfg)
    with (
        patch.object(core_stock_tools, "route_to_vendor", crash),
        ok_indicators,
        pytest.raises(RuntimeError, match="vendor exploded"),
    ):
        nodes["execute"](state)

    # The crash left the registration intact (it was written before dispatch).
    after_crash = state["tool_governance"]["analysts"]["market"]
    assert after_crash["rounds"] == 1
    assert after_crash["charged_rounds"] == scope["charged_rounds"]

    # 3) Resume the same node: the same round, not a new one, and one answer.
    with ok_stock, ok_indicators:
        update = nodes["execute"](state)
    resumed = update["tool_governance"]["analysts"]["market"]
    assert resumed["rounds"] == 1, "the resumed round must not be charged again"
    assert resumed["executed"] == 1
    assert [m.tool_call_id for m in update["messages"]] == ["c1"]


@pytest.mark.unit
def test_execute_without_a_saved_registration_refuses_to_charge():
    cfg = _enabled()
    state = _initial(cfg)
    state["messages"] = [_ai(_call("c1", "get_stock_data", STOCK))]
    nodes = mtg.create_market_governance_nodes(
        llm=ScriptedModel([]), tool_node=ToolNode(TOOLS)
    )
    with pytest.raises(mtg.MarketGovernanceError, match="registration"):
        nodes["execute"](state)


# ---------------------------------------------------------------------------
# Two runs are isolated
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_two_runs_have_independent_counters_and_caches():
    cfg = _enabled(max_rounds=4, max_calls=10)
    responses = [
        _ai(_call("c1", "get_stock_data", STOCK)),
        _ai(_call("c2", "get_stock_data", STOCK)),
        AIMessage("FINAL: one fetch"),
    ]
    out_a, _ = _run(cfg, responses, run_id="run-a")
    out_b, _ = _run(cfg, responses, run_id="run-b")

    for out, run_id in ((out_a, "run-a"), (out_b, "run-b")):
        scope = _scope(out)
        assert scope["run_id"] == run_id
        # Each run fetched once, then the repeat is blocked in its own run:
        # neither the counters nor the (disabled) cache are shared.
        assert scope["rounds"] == 2
        assert scope["executed"] == 1
        assert scope["reused"] == 0
        assert scope["blocked"] == 1
        assert scope["cache"] == {}
