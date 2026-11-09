"""Offline tests for the opt-in fundamentals-analyst tool governance.

The suite builds a **real** fundamentals graph slice (the fundamentals analyst,
the four governance nodes, the msg-clear node) on a scripted model and fake
tools, so the state-update and message-merge mechanics exercised are the ones
the production graph uses. No network, no vendor, no real LLM.

Covered:

* the switch is off by default, its caps default to 4/8, and illegal config is
  refused (bool / None / fractional / unknown keys), independently of market;
* a normal run finishes early on the analyst's own text, written straight to
  ``fundamentals_report`` -- no second generation;
* ``max_rounds=1`` / ``max_calls=1`` bound the real call count;
* after the final allowed round the run goes straight to the single wrap-up:
  the model-call count and the wrap-up prompt are checked;
* repeated and all-blocked requests terminate and every call id is paired;
* a refusal / truncation / blank first answer makes exactly one model request;
* a tool exception after registration does not charge the round twice;
* market and fundamentals enabled together keep separate counters and reports;
* two runs are isolated.
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

from tradingagents.agents.analysts import (
    fundamentals_analyst as fundamentals_module,
)
from tradingagents.agents.utils import (
    core_stock_tools,
    fundamental_data_tools,
    market_data_validation_tools,
    technical_indicators_tools,
)
from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.agents.utils.agent_utils import create_msg_delete
from tradingagents.dataflows.config import set_config
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph import fundamentals_tool_governance as ftg, market_tool_governance as mtg
from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.fundamentals_governance import (
    FUNDAMENTALS_TOOLS,
    parse_fundamentals_tool_governance,
)
from tradingagents.graph.market_governance import parse_market_tool_governance
from tradingagents.graph.setup import GraphSetup

TRADE_DATE = "2026-08-14"

FUNDAMENTALS = {"ticker": "AAPL", "curr_date": TRADE_DATE}
BALANCE = {"ticker": "AAPL", "freq": "annual", "curr_date": TRADE_DATE}
CASHFLOW = {"ticker": "AAPL", "freq": "quarterly", "curr_date": TRADE_DATE}
INCOME = {"ticker": "AAPL", "freq": "annual", "curr_date": TRADE_DATE}

STOCK = {"symbol": "AAPL", "start_date": "2026-08-01", "end_date": TRADE_DATE}
RSI = {"symbol": "AAPL", "indicator": "rsi", "curr_date": TRADE_DATE}

FUNDAMENTAL_TOOLS = [
    fundamental_data_tools.get_fundamentals,
    fundamental_data_tools.get_balance_sheet,
    fundamental_data_tools.get_cashflow,
    fundamental_data_tools.get_income_statement,
]
MARKET_TOOLS = [
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
        fundamentals_tool_governance={
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


def _fundamentals_slice(cfg, responses, *, tools=None, tool_node=None):
    """Compile the real fundamentals slice of the graph on a scripted model."""
    set_config(cfg)
    llm = ScriptedModel(responses)
    tools = tools if tools is not None else FUNDAMENTAL_TOOLS
    node = tool_node if tool_node is not None else ToolNode(tools)
    with (
        patch.object(fundamentals_module, "get_fundamentals", tools[0]),
        patch.object(fundamentals_module, "get_balance_sheet", tools[1]),
        patch.object(fundamentals_module, "get_cashflow", tools[2]),
        patch.object(fundamentals_module, "get_income_statement", tools[3]),
    ):
        analyst = fundamentals_module.create_fundamentals_analyst(llm)
    nodes = ftg.create_fundamentals_governance_nodes(llm=llm, tool_node=node)

    graph = StateGraph(AgentState)
    graph.add_node("Fundamentals Analyst", analyst)
    graph.add_node("Msg Clear Fundamentals", create_msg_delete())
    graph.add_node("fundamentals_tool_prepare", nodes["prepare"])
    graph.add_node("fundamentals_tool_execute", nodes["execute"])
    graph.add_node("fundamentals_finish", nodes["finish"])
    graph.add_node("fundamentals_wrap_up", nodes["wrap_up"])
    graph.add_edge(START, "Fundamentals Analyst")

    logic = ConditionalLogic()
    graph.add_conditional_edges(
        "Fundamentals Analyst",
        logic.should_continue_fundamentals_governed,
        ["fundamentals_tool_prepare", "fundamentals_wrap_up", "fundamentals_finish"],
    )
    graph.add_conditional_edges(
        "fundamentals_tool_prepare",
        logic.should_execute_fundamentals_prepared,
        ["fundamentals_tool_execute", "fundamentals_wrap_up", "Fundamentals Analyst"],
    )
    graph.add_conditional_edges(
        "fundamentals_tool_execute",
        logic.should_continue_fundamentals_after_execute,
        ["Fundamentals Analyst", "fundamentals_wrap_up"],
    )
    graph.add_edge("fundamentals_finish", "Msg Clear Fundamentals")
    graph.add_edge("fundamentals_wrap_up", "Msg Clear Fundamentals")
    graph.add_edge("Msg Clear Fundamentals", END)
    return graph.compile(), llm


def _fundamental_vendor(*, fundamentals=None, statement=None):
    """Patch the router the fake fundamental tools call (no network).

    ``get_fundamentals`` calls the router as ``(method, ticker, date)``; the
    three statements add a frequency. One fake router serves both shapes.
    """
    f_text = fundamentals or (lambda *a: f"FUNDAMENTALS REPORT for {a[1]}")

    def router(method, *args):
        if method == "get_fundamentals":
            return f_text(method, *args)
        ticker, freq, curr = args
        if statement is not None:
            return statement(method, ticker, freq, curr)
        return f"{method} ({freq}) for {ticker} as of {curr}"

    return patch.object(fundamental_data_tools, "route_to_vendor", router)


def _run(cfg, responses, *, run_id="run-test", tools=None, tool_node=None, **kwargs):
    """Run the slice to completion and capture its final governance record.

    The run ends at the msg-clear node, which replaces the conversation; the
    governance record is the per-node update that must survive to the end, so
    it is captured while streaming, together with every report written.
    """
    graph, llm = _fundamentals_slice(
        cfg, responses, tools=tools, tool_node=tool_node, **kwargs
    )
    governance: dict = {}
    report = ""
    with _fundamental_vendor():
        for step in graph.stream(
            _initial(cfg, run_id), {"recursion_limit": 80}, stream_mode="updates"
        ):
            for update in step.values():
                if not isinstance(update, dict):
                    continue
                if "tool_governance" in update:
                    governance = update["tool_governance"]
                if update.get("fundamentals_report"):
                    report = update["fundamentals_report"]
    return report, llm, governance


def _final_governance(graph, initial):
    """Stream a compiled slice and return the last governance record seen."""
    governance: dict = {}
    for step in graph.stream(initial, {"recursion_limit": 80}, stream_mode="updates"):
        for update in step.values():
            if isinstance(update, dict) and "tool_governance" in update:
                governance = update["tool_governance"]
    return governance


def _scope(out):
    return out["tool_governance"]["analysts"]["fundamentals"]


_WRAP_UP_SENTINEL = "The tool-call allowance for this run is spent"
_FUNDAMENTALS_SENTINEL = "You are a researcher tasked with analyzing fundamental"


def _system_text(sent):
    """The system prompt of one recorded model invocation."""
    return "\n".join(
        message.content
        for message in sent
        if isinstance(message, SystemMessage) and isinstance(message.content, str)
    )


def _requested_wrap_up(sent, analyst="fundamentals"):
    system = _system_text(sent)
    marker = "Market Analyst" if analyst == "market" else "Fundamentals Analyst"
    return _WRAP_UP_SENTINEL in system and marker in system


def _requested_analyst(sent):
    system = _system_text(sent)
    return _FUNDAMENTALS_SENTINEL in system and _WRAP_UP_SENTINEL not in system


# ---------------------------------------------------------------------------
# Toggle
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_governance_is_off_by_default():
    assert parse_fundamentals_tool_governance(DEFAULT_CONFIG).enabled is False
    assert parse_fundamentals_tool_governance(None).enabled is False
    assert parse_fundamentals_tool_governance({}).enabled is False


@pytest.mark.unit
def test_default_config_defaults_to_four_rounds_and_eight_calls():
    section = DEFAULT_CONFIG["fundamentals_tool_governance"]
    assert section == {"enabled": False, "max_rounds": 4, "max_calls": 8}
    parsed = parse_fundamentals_tool_governance(
        {"fundamentals_tool_governance": {"enabled": True}}
    )
    assert parsed.enabled is True
    assert (parsed.max_rounds, parsed.max_calls) == (4, 8)
    limits = parsed.limits()
    assert (limits.max_rounds, limits.max_calls) == (4, 8)


@pytest.mark.unit
def test_disabled_section_ignores_caps_but_refuses_nonsense():
    parsed = parse_fundamentals_tool_governance(
        {"fundamentals_tool_governance": {"enabled": False, "max_rounds": 9}}
    )
    assert parsed.enabled is False
    assert parsed.max_rounds is None and parsed.max_calls is None
    with pytest.raises(ValueError):
        parse_fundamentals_tool_governance(
            {"fundamentals_tool_governance": {"enabled": False, "max_rounds": 0}}
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
        parse_fundamentals_tool_governance({"fundamentals_tool_governance": section})


@pytest.mark.unit
def test_toggle_section_must_be_a_mapping():
    with pytest.raises(ValueError):
        parse_fundamentals_tool_governance({"fundamentals_tool_governance": True})


@pytest.mark.unit
def test_fundamentals_and_market_switches_are_independent():
    """Enabling one section never enables (or re-caps) the other."""
    only_f = {"fundamentals_tool_governance": {"enabled": True}}
    assert parse_fundamentals_tool_governance(only_f).enabled is True
    assert parse_market_tool_governance(only_f).enabled is False

    only_m = {"market_tool_governance": {"enabled": True, "max_calls": 3}}
    assert parse_market_tool_governance(only_m).enabled is True
    assert parse_fundamentals_tool_governance(only_m).enabled is False

    # A cap in one section never leaks into the other's defaults.
    both = {
        "market_tool_governance": {"enabled": True, "max_calls": 3},
        "fundamentals_tool_governance": {"enabled": True, "max_rounds": 1},
    }
    assert parse_market_tool_governance(both).max_calls == 3
    assert parse_fundamentals_tool_governance(both).max_calls == 8
    f_parsed = parse_fundamentals_tool_governance(both)
    assert (f_parsed.max_rounds, f_parsed.max_calls) == (1, 8)


# ---------------------------------------------------------------------------
# Toggle off: today's graph, and the four-tool permission set
# ---------------------------------------------------------------------------


def _assert_no_governance_nodes(workflow):
    assert not {
        "fundamentals_tool_prepare",
        "fundamentals_tool_execute",
        "fundamentals_wrap_up",
        "fundamentals_finish",
    } & set(workflow.nodes)


@pytest.mark.unit
def test_graph_with_governance_off_has_only_the_old_fundamentals_nodes():
    cfg = _config(fundamentals_tool_governance={"enabled": False})
    setup = GraphSetup(
        ScriptedModel([AIMessage("x")]),
        ScriptedModel([AIMessage("x")]),
        {"fundamentals": ToolNode(FUNDAMENTAL_TOOLS)},
        ConditionalLogic(),
        config=cfg,
    )
    workflow = setup.setup_graph(("fundamentals",))
    assert "tools_fundamentals" in workflow.nodes
    _assert_no_governance_nodes(workflow)
    assert ("tools_fundamentals", "Fundamentals Analyst") in {
        (source, target) for source, target, *_ in workflow.edges
    }


@pytest.mark.unit
def test_market_switch_alone_leaves_fundamentals_on_the_old_path():
    cfg = _config(market_tool_governance={"enabled": True})
    setup = GraphSetup(
        ScriptedModel([AIMessage("x")]),
        ScriptedModel([AIMessage("x")]),
        {"fundamentals": ToolNode(FUNDAMENTAL_TOOLS)},
        ConditionalLogic(),
        config=cfg,
    )
    workflow = setup.setup_graph(("fundamentals",))
    _assert_no_governance_nodes(workflow)
    assert ("tools_fundamentals", "Fundamentals Analyst") in {
        (source, target) for source, target, *_ in workflow.edges
    }


@pytest.mark.unit
def test_graph_with_governance_on_adds_its_own_fundamentals_path():
    cfg = _enabled()
    setup = GraphSetup(
        ScriptedModel([AIMessage("x")]),
        ScriptedModel([AIMessage("x")]),
        {"fundamentals": ToolNode(FUNDAMENTAL_TOOLS)},
        ConditionalLogic(),
        config=cfg,
    )
    workflow = setup.setup_graph(("fundamentals",))
    assert {
        "fundamentals_tool_prepare",
        "fundamentals_tool_execute",
        "fundamentals_wrap_up",
        "fundamentals_finish",
    } <= set(workflow.nodes)
    edges = {(source, target) for source, target, *_ in workflow.edges}
    assert ("fundamentals_wrap_up", "Msg Clear Fundamentals") in edges
    # The governed path never feeds the plain tool node.
    assert not any(target == "tools_fundamentals" for _, target, *_ in edges)

    compiled = workflow.compile()

    def ends(source):
        return {
            target
            for spec in compiled.builder.branches.get(source, {}).values()
            for target in (spec.ends or ())
        }

    assert ends("Fundamentals Analyst") == {
        "fundamentals_tool_prepare",
        "fundamentals_wrap_up",
        "fundamentals_finish",
    }
    assert ends("fundamentals_tool_execute") == {
        "Fundamentals Analyst",
        "fundamentals_wrap_up",
    }


@pytest.mark.unit
def test_permission_is_exactly_the_four_bound_tools():
    node = ToolNode(FUNDAMENTAL_TOOLS)
    permitted = ftg._permitted_tools(node)
    assert {tool.name for tool in permitted} == set(FUNDAMENTALS_TOOLS)
    assert mtg.scope_of  # the shared helpers are reused, not re-implemented


@pytest.mark.unit
def test_an_unbound_tool_is_refused_before_anything_runs():
    """Even a widened ToolNode grants nothing beyond the four tools."""
    dev = ScriptedModel.__new__(ScriptedModel)
    del dev
    widened = {tool.name: tool for tool in FUNDAMENTAL_TOOLS}
    widened["get_stock_data"] = core_stock_tools.get_stock_data
    allowed = ftg._permitted_tools(type("N", (), {"tools_by_name": widened})())
    assert {tool.name for tool in allowed} == set(FUNDAMENTALS_TOOLS)
    assert "get_stock_data" not in {tool.name for tool in allowed}


@pytest.mark.unit
def test_market_tools_are_not_permitted_to_the_fundamentals_executor():
    """A market tool name never runs for this analyst (blocked, paired once)."""
    cfg = _enabled()
    state = _initial(cfg)
    state["messages"] = [_ai(_call("c1", "get_stock_data", STOCK))]
    nodes = ftg.create_fundamentals_governance_nodes(
        llm=ScriptedModel([]), tool_node=ToolNode(FUNDAMENTAL_TOOLS)
    )
    update = nodes["prepare"](state)
    scope = update["tool_governance"]["analysts"]["fundamentals"]
    assert scope["blocked"] == 1
    assert scope["executed"] == 0
    assert scope["finished"] is False
    # The one message pairs the call: it reports the refusal, never data.
    messages = update["messages"]
    paired = [m for m in messages if getattr(m, "tool_call_id", None) == "c1"]
    assert len(paired) == 1
    assert "refused before execution" in paired[0].content
    assert all(getattr(m, "tool_call_id", None) != "c1" or m.content for m in messages)


# ---------------------------------------------------------------------------
# Normal runs
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_analyst_finishes_early_on_its_own_report():
    cfg = _enabled(max_rounds=6, max_calls=8)
    responses = [
        _ai(_call("c1", "get_fundamentals", FUNDAMENTALS)),
        AIMessage("ANALYST FINAL: fundamentals based"),
    ]
    out, llm, governance = _run(cfg, responses)

    # The analyst's own text *is* the report: no wrap-up generation.
    assert out == "ANALYST FINAL: fundamentals based"
    scope = governance["analysts"]["fundamentals"]
    assert (scope["rounds"], scope["executed"]) == (1, 1)
    assert scope["finished"] and scope["closed"]
    assert llm.calls == 2
    assert _requested_analyst(llm.sent[1])


@pytest.mark.unit
def test_two_rounds_then_a_report():
    cfg = _enabled(max_rounds=4, max_calls=8)
    responses = [
        _ai(
            _call("c1", "get_balance_sheet", BALANCE),
            _call("c2", "get_income_statement", INCOME),
        ),
        _ai(_call("c3", "get_cashflow", CASHFLOW)),
        AIMessage("FINAL: three statements"),
    ]
    out, llm, governance = _run(cfg, responses)
    scope = governance["analysts"]["fundamentals"]
    assert (scope["rounds"], scope["executed"]) == (2, 3)
    assert out.startswith("FINAL")


@pytest.mark.unit
def test_real_call_count_respects_max_rounds_one():
    cfg = _enabled(max_rounds=1, max_calls=8)
    seen = []

    def statement(method, ticker, freq, curr):
        seen.append(method)
        return f"{method} for {ticker}"

    # Only two answers are scripted: the one allowed batch and the wrap-up.
    # A third (analyst) answer would mean the spent allowance was ignored.
    responses = [
        _ai(
            _call("c1", "get_balance_sheet", BALANCE),
            _call("c2", "get_income_statement", INCOME),
        ),
        AIMessage("WRAP: one round only"),
    ]
    graph, llm = _fundamentals_slice(cfg, responses)
    with _fundamental_vendor(statement=statement):
        governance = _final_governance(graph, _initial(cfg))
    scope = governance["analysts"]["fundamentals"]
    assert scope["rounds"] == 1
    assert scope["executed"] == 2
    assert sorted(seen) == ["get_balance_sheet", "get_income_statement"]
    # Round 1 runs; the next turn is over the allowance -> wrap-up directly.
    assert llm.calls == 2
    assert _requested_wrap_up(llm.sent[1])


@pytest.mark.unit
def test_real_call_count_respects_max_calls_one():
    cfg = _enabled(max_rounds=4, max_calls=1)
    seen = []

    def statement(method, ticker, freq, curr):
        seen.append(method)
        return f"{method} for {ticker}"

    responses = [
        _ai(
            _call("c1", "get_balance_sheet", BALANCE),
            _call("c2", "get_income_statement", INCOME),
        ),
        AIMessage("WRAP: one call only"),
    ]
    graph, llm = _fundamentals_slice(cfg, responses)
    with _fundamental_vendor(statement=statement):
        governance = _final_governance(graph, _initial(cfg))
    scope = governance["analysts"]["fundamentals"]
    assert scope["executed"] == 1
    assert scope["blocked"] == 1
    assert len(seen) == 1
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
    seen = []

    def statement(method, ticker, freq, curr):
        seen.append(method)
        return f"{method} for {ticker}"

    responses = [
        _ai(_call("c1", "get_balance_sheet", BALANCE)),
        # The batch that spends the last round: both calls must still run.
        _ai(
            _call("c2", "get_cashflow", CASHFLOW),
            _call("c3", "get_income_statement", INCOME),
        ),
        AIMessage("WRAPUP: two rounds done"),
    ]
    graph, llm = _fundamentals_slice(cfg, responses)
    with _fundamental_vendor(statement=statement):
        governance = _final_governance(graph, _initial(cfg))

    scope = governance["analysts"]["fundamentals"]
    assert (scope["rounds"], scope["executed"]) == (2, 3)
    assert sorted(seen) == ["get_balance_sheet", "get_cashflow", "get_income_statement"]
    # Analyst, analyst, wrap-up: the analyst is not asked again just to be told
    # its allowance is spent.
    assert llm.calls == 3
    assert _requested_analyst(llm.sent[0]) and _requested_analyst(llm.sent[1])
    assert _requested_wrap_up(llm.sent[2])


@pytest.mark.unit
def test_wrap_up_prompt_forbids_inventing_figures_and_names_missing_statements():
    cfg = _enabled(max_rounds=1, max_calls=1)
    responses = [
        _ai(_call("c1", "get_balance_sheet", BALANCE)),
        AIMessage("WRAPUP: evidence only"),
    ]
    out, llm, _ = _run(cfg, responses)
    assert out == "WRAPUP: evidence only"
    sent = llm.sent[-1]
    system = _system_text(sent)
    for phrase in (
        "Fundamentals Analyst",
        "ONLY",
        "Do not invent financial figures",
        "reporting periods",
        "which financial statements",
        "trade date",
    ):
        assert phrase in system
    # The evidence the analyst collected is in the conversation.
    assert any(
        isinstance(m, AIMessage) and m.tool_calls for m in sent
    )
    tool_texts = [m.content for m in sent if isinstance(m, ToolMessage)]
    assert any("get_balance_sheet" in str(text) for text in tool_texts)


# ---------------------------------------------------------------------------
# Repeated / all-blocked requests terminate, every call id paired
# ---------------------------------------------------------------------------


def _paired_ids(sent):
    return sorted(
        m.tool_call_id for m in sent if isinstance(m, ToolMessage)
    )


def _assert_every_call_paired(llm, scripted_ids):
    """Every tool call the model ever issued has exactly one answer in the run.

    The conversation the model is shown is the graph state itself, so the
    *final* prompt holds the whole run: each call id must appear there exactly
    once (no dangling call, no duplicate answer).
    """
    counts: dict[str, int] = {}
    for message in llm.sent[-1]:
        if isinstance(message, ToolMessage):
            counts[message.tool_call_id] = counts.get(message.tool_call_id, 0) + 1
    assert sorted(counts) == sorted(scripted_ids)
    assert all(count == 1 for count in counts.values()), counts


@pytest.mark.unit
def test_repeated_tool_requests_stop_at_the_round_cap_and_pair_every_call():
    """The analyst asks for the same statement every round; the cap ends it.

    ``max_rounds=2``: the third identical batch can never run. The run must
    reach the single wrap-up without a third analyst generation, and every
    call id -- including the ones nobody could run -- is answered once.
    """
    cfg = _enabled(max_rounds=2, max_calls=8)
    seen = []

    def statement(method, ticker, freq, curr):
        seen.append(method)
        return f"{method} for {ticker}"

    # Two identical batches (the second spends the allowance) and the wrap-up.
    # A third analyst batch is not scripted: it would only be asked for if the
    # cap were ignored.
    responses = [
        _ai(_call("c1", "get_balance_sheet", BALANCE)),
        _ai(_call("c2", "get_balance_sheet", BALANCE)),
        AIMessage("WRAPUP: repeated requests"),
    ]
    graph, llm = _fundamentals_slice(cfg, responses)
    with _fundamental_vendor(statement=statement):
        governance = _final_governance(graph, _initial(cfg))

    scope = governance["analysts"]["fundamentals"]
    assert scope["rounds"] == 2
    # The identical repeat is never run twice; it is blocked and paired.
    assert scope["executed"] == 1
    assert scope["blocked"] == 1
    assert seen == ["get_balance_sheet"], "the repeat is not fetched again"
    # Two analyst answers (the two rounds), then the single wrap-up: the
    # analyst is never asked again once its allowance is spent.
    assert llm.calls == 3
    assert _requested_analyst(llm.sent[0]) and _requested_analyst(llm.sent[1])
    assert _requested_wrap_up(llm.sent[2])
    _assert_every_call_paired(llm, {"c1", "c2"})


@pytest.mark.unit
def test_all_blocked_requests_still_terminate_and_pair_every_call():
    """Every call names a tool this analyst is not bound to: blocked, not run."""
    cfg = _enabled(max_rounds=3, max_calls=10)
    responses = [
        _ai(
            _call("b1", "get_stock_data", STOCK),
            _call("b2", "get_indicators", RSI),
        ),
        AIMessage("WRAPUP: every call blocked"),
    ]
    out, llm, governance = _run(cfg, responses)

    scope = governance["analysts"]["fundamentals"]
    assert scope["executed"] == 0
    assert scope["blocked"] == 2
    assert scope["closed"]
    assert out == "WRAPUP: every call blocked"
    # The batch never reached execution and no second analyst turn was spent.
    assert llm.calls == 2
    assert _requested_wrap_up(llm.sent[1])
    _assert_every_call_paired(llm, {"b1", "b2"})


# ---------------------------------------------------------------------------
# Unusable first answer: one model request, no fabricated report
# ---------------------------------------------------------------------------

_BAD_ANALYST_ANSWERS = {
    "refusal": AIMessage(
        content="", additional_kwargs={"refusal": "I can't help with that."}
    ),
    "truncated": AIMessage(
        content="FUNDAMENTALS REPORT: revenue grew and",
        response_metadata={"finish_reason": "length"},
    ),
    "empty": AIMessage(content=""),
}


@pytest.mark.unit
@pytest.mark.parametrize("kind", sorted(_BAD_ANALYST_ANSWERS))
def test_unusable_first_answer_makes_exactly_one_model_request(kind):
    """Refusal / truncation / blank fails at the first response.

    A normal report is scripted as a **decoy** second answer. If the router
    treated the unusable turn as something to wrap up, the decoy would be
    spent and stored as ``fundamentals_report``. Instead the run raises after
    one model call, saves no report and runs no tool.
    """
    cfg = _enabled(max_rounds=2, max_calls=10)
    seen: list[str] = []

    def statement(method, ticker, freq, curr):
        seen.append(method)
        return f"{method} for {ticker}"

    responses = [
        _BAD_ANALYST_ANSWERS[kind],
        AIMessage("DECOY: this report must never be requested"),
    ]
    graph, llm = _fundamentals_slice(cfg, responses)
    report = ""
    with _fundamental_vendor(statement=statement), pytest.raises(
        ftg.FundamentalsGovernanceError
    ):
        for step in graph.stream(
            _initial(cfg), {"recursion_limit": 80}, stream_mode="updates"
        ):
            for node, update in step.items():
                assert node != "Msg Clear Fundamentals"
                if isinstance(update, dict) and update.get("fundamentals_report"):
                    report = update["fundamentals_report"]

    assert llm.calls == 1, "the decoy must not be requested"
    assert seen == [], "no tool may run after an unusable answer"
    assert report == "", "nothing may be saved as the fundamentals report"
    assert all(
        "DECOY" not in str(message.content) for sent in llm.sent for message in sent
    )


@pytest.mark.unit
@pytest.mark.parametrize("kind", sorted(_BAD_ANALYST_ANSWERS))
def test_wrap_up_raises_instead_of_storing_an_unusable_answer(kind):
    """The wrap-up exit rejects the same answers; it never retries."""
    cfg = _enabled()
    state = _initial(cfg)
    state["messages"] = [*state["messages"], _ai(_call("c1", "get_balance_sheet", BALANCE))]
    llm = ScriptedModel([_BAD_ANALYST_ANSWERS[kind]])
    nodes = ftg.create_fundamentals_governance_nodes(
        llm=llm, tool_node=ToolNode(FUNDAMENTAL_TOOLS)
    )
    with pytest.raises(ftg.FundamentalsGovernanceError):
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
    nodes = ftg.create_fundamentals_governance_nodes(
        llm=ScriptedModel([]), tool_node=ToolNode(FUNDAMENTAL_TOOLS)
    )
    state["messages"] = [_ai(_call("c1", "get_balance_sheet", BALANCE))]

    # 1) Prepare registers the round and saves it: nothing has run yet.
    saved = nodes["prepare"](state)
    state.update(saved)
    scope = state["tool_governance"]["analysts"]["fundamentals"]
    assert scope["rounds"] == 1
    assert scope["executed"] == 1  # charged for the call it intends to run

    # 2) Execute dispatches the saved round and the tool raises.
    def crash(*args, **kwargs):
        raise RuntimeError("vendor exploded")

    ok = _fundamental_vendor(statement=lambda m, t, f, c: f"{m} for {t}")
    with (
        patch.object(fundamental_data_tools, "route_to_vendor", crash),
        pytest.raises(RuntimeError, match="vendor exploded"),
    ):
        nodes["execute"](state)

    after_crash = state["tool_governance"]["analysts"]["fundamentals"]
    assert after_crash["rounds"] == 1
    assert after_crash["charged_rounds"] == scope["charged_rounds"]

    # 3) Resume the same node: the same round, not a new one, and one answer.
    with ok:
        update = nodes["execute"](state)
    resumed = update["tool_governance"]["analysts"]["fundamentals"]
    assert resumed["rounds"] == 1, "the resumed round must not be charged again"
    assert resumed["executed"] == 1
    assert [m.tool_call_id for m in update["messages"]] == ["c1"]


# ---------------------------------------------------------------------------
# Market and fundamentals enabled together: independent state
# ---------------------------------------------------------------------------


def _both_enabled(*, market_calls=10, f_rounds=4, f_calls=8):
    return _config(
        market_tool_governance={"enabled": True, "max_rounds": 4, "max_calls": market_calls},
        fundamentals_tool_governance={
            "enabled": True,
            "max_rounds": f_rounds,
            "max_calls": f_calls,
        },
    )


@pytest.mark.unit
def test_graph_with_both_switches_on_gets_both_governance_paths():
    cfg = _both_enabled()
    tools = {
        "market": ToolNode(MARKET_TOOLS),
        "fundamentals": ToolNode(FUNDAMENTAL_TOOLS),
    }
    setup = GraphSetup(
        ScriptedModel([AIMessage("x")]),
        ScriptedModel([AIMessage("x")]),
        tools,
        ConditionalLogic(),
        config=cfg,
    )
    workflow = setup.setup_graph(("market", "fundamentals"))
    for prefix in ("market", "fundamentals"):
        assert {
            f"{prefix}_tool_prepare",
            f"{prefix}_tool_execute",
            f"{prefix}_wrap_up",
            f"{prefix}_finish",
        } <= set(workflow.nodes)


@pytest.mark.unit
def test_market_and_fundamentals_records_are_independent_in_one_state():
    """One run's governance value holds two records with separate counters."""
    cfg = _both_enabled(market_calls=2, f_rounds=4, f_calls=8)
    cfg["fundamentals_tool_governance"] = {
        "enabled": True,
        "max_rounds": 4,
        "max_calls": 8,
    }
    state = _initial(cfg)
    state["messages"] = [_ai(_call("c1", "get_balance_sheet", BALANCE))]

    market_nodes = mtg.create_market_governance_nodes(
        llm=ScriptedModel([]), tool_node=ToolNode(MARKET_TOOLS)
    )
    f_nodes = ftg.create_fundamentals_governance_nodes(
        llm=ScriptedModel([]), tool_node=ToolNode(FUNDAMENTAL_TOOLS)
    )
    # Charge a market round first, then a fundamentals round in the same state.
    # Each step gets its own message list (a node may annotate the list in
    # place), while the governance value carries over.
    market_state = dict(state, messages=[_ai(_call("m1", "get_stock_data", STOCK))])
    market_state.update(market_nodes["prepare"](market_state))
    f_state = dict(
        market_state, messages=[_ai(_call("c1", "get_balance_sheet", BALANCE))]
    )
    f_state.update(f_nodes["prepare"](f_state))

    governance = f_state["tool_governance"]
    market_scope = mtg.scope_of(governance)
    f_scope = mtg.scope_of(governance, analyst="fundamentals")
    assert market_scope["rounds"] == 1
    assert f_scope["rounds"] == 1
    # Each record owns its own calls: the market's m1 is not fundamentals' c1.
    def planned(scope):
        return {
            call_id
            for round_ in (scope.get("planned_rounds") or {}).values()
            for call_id in round_
            if not str(call_id).startswith("_")
        }

    assert planned(market_scope) == {"m1"}
    assert planned(f_scope) == {"c1"}
    # Each analyst only ever reports into its own field; records never alias.
    assert market_scope["run_id"] == f_scope["run_id"]
    assert governance["analysts"]["market"] is not governance["analysts"]["fundamentals"]


@pytest.mark.unit
def test_a_spent_fundamentals_cap_leaves_the_market_counters_alone():
    cfg = _both_enabled(f_rounds=1, f_calls=1)
    cfg["fundamentals_tool_governance"] = {
        "enabled": True,
        "max_rounds": 1,
        "max_calls": 1,
    }
    state = _initial(cfg)
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
    state["tool_governance"] = {
        "run_id": "run-test",
        "analysts": {"market": market_scope},
    }
    state["messages"] = [
        _ai(
            _call("c1", "get_balance_sheet", BALANCE),
            _call("c2", "get_income_statement", INCOME),
        )
    ]
    nodes = ftg.create_fundamentals_governance_nodes(
        llm=ScriptedModel([]), tool_node=ToolNode(FUNDAMENTAL_TOOLS)
    )
    update = nodes["prepare"](state)
    governance = update["tool_governance"]
    # The fundamentals cap is spent; the market record is untouched.
    assert mtg.scope_of(governance) == market_scope
    assert mtg.scope_of(governance, analyst="fundamentals")["rounds"] == 1


# ---------------------------------------------------------------------------
# Runs are isolated
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_two_runs_have_independent_counters():
    cfg = _enabled(max_rounds=4, max_calls=10)
    responses = [
        _ai(_call("c1", "get_balance_sheet", BALANCE)),
        _ai(_call("c2", "get_balance_sheet", BALANCE)),
        AIMessage("FINAL: one statement"),
    ]
    out_a, _, gov_a = _run(cfg, responses, run_id="run-a")
    out_b, _, gov_b = _run(cfg, responses, run_id="run-b")

    assert out_a == out_b == "FINAL: one statement"
    for gov, run_id in ((gov_a, "run-a"), (gov_b, "run-b")):
        scope = gov["analysts"]["fundamentals"]
        assert scope["run_id"] == run_id
        # Each run charged its own two rounds; with success reuse off the
        # repeated call is neither served from a cache nor inherited, so each
        # run made its own single tool call and the repeat was blocked.
        assert scope["rounds"] == 2
        assert scope["executed"] == 1
        assert scope["reused"] == 0
        assert scope["blocked"] == 1
        assert scope["cache"] == {}
    # Different run ids: no record is shared between the two runs.
    assert gov_a["analysts"]["fundamentals"]["run_id"] != (
        gov_b["analysts"]["fundamentals"]["run_id"]
    )


# ---------------------------------------------------------------------------
# Checkpoint signature distinguishes the fundamentals switch
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_run_signature_distinguishes_the_fundamentals_switch():
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = object.__new__(TradingAgentsGraph)
    graph.selected_analysts = ("market", "fundamentals")
    base_cfg = {"max_debate_rounds": 1, "max_risk_discuss_rounds": 1}
    graph.config = dict(base_cfg)
    base = graph._run_signature("stock")
    assert "fundamentals_gov=False" in base

    graph.config = {
        **base_cfg,
        "fundamentals_tool_governance": {"enabled": True},
    }
    with_f = graph._run_signature("stock")
    assert with_f != base
    assert "fundamentals_gov=True" in with_f
    # Stable for identical config.
    assert with_f == graph._run_signature("stock")
    # The market switch alone also changes the signature, independently.
    graph.config = {
        **base_cfg,
        "market_tool_governance": {"enabled": True},
    }
    with_m = graph._run_signature("stock")
    assert with_m != base
    assert "market_gov=True" in with_m and "fundamentals_gov=False" in with_m
