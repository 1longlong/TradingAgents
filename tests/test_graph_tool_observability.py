"""Regression: tool executions must be observable from the graph path.

An E2E benchmark run recorded ``tool_rounds > 0`` together with
``tool_calls == 0`` and ``tool_result_utf8_bytes_sum == 0``. Root cause:
``TradingAgentsGraph._run_graph`` invoked the graph without callbacks, so
LangGraph never delivered ``on_tool_start/end`` to the handlers — the
``attrib_tool_round`` wrapper still recorded each round, but no per-tool
execution events were emitted.

Everything here is credential-free: fake models, local tools, no network.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from tradingagents import observability as o

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOL_OUTPUT = "A" * 64


@tool
def synthetic_quote(symbol: str) -> str:
    """Return a synthetic, fixed-size quote blob (no network)."""
    return TOOL_OUTPUT


def _build_two_step_graph(handler):
    """agent -> tools -> END, both nodes wrapped like GraphSetup does."""

    def agent(_state):
        return {"messages": [AIMessage(content="", tool_calls=[
            {"name": "synthetic_quote", "args": {"symbol": "NVDA"},
             "id": "call_1", "type": "tool_call"},
        ])]}

    def should_continue(state):
        return "tools" if getattr(state["messages"][-1], "tool_calls", None) else END

    self_ = None  # noqa: F841 - keep the graph self-contained
    builder = StateGraph(MessagesState)
    builder.add_node(
        "Market Analyst",
        o.attrib_agent_node(o.AGENT_MARKET_ANALYST, agent, "Market Analyst"),
    )
    builder.add_node(
        "tools_market",
        o.attrib_tool_round(o.AGENT_MARKET_ANALYST, ToolNode([synthetic_quote])),
    )
    builder.add_edge(START, "Market Analyst")
    builder.add_conditional_edges(
        "Market Analyst", should_continue,
        {"tools": "tools_market", END: END},
    )
    builder.add_edge("tools_market", END)
    return builder.compile()


class TestGraphInvocationPassesCallbacks:
    """`_run_graph` must hand its callbacks to the graph invocation config."""

    def test_run_graph_passes_callbacks(self, monkeypatch):
        from tradingagents.graph import trading_graph as tg

        seen = {}

        class _Cfg:
            recursion_limit = 10

        class _Propagator:
            def get_graph_args(self, callbacks=None):
                seen["callbacks"] = callbacks
                return {"stream_mode": "values", "config": _Cfg()}

        class _Graph:
            def invoke(self, *_a, **_kw):
                return {"messages": [AIMessage(content="done")]}

        graph = tg.TradingAgentsGraph.__new__(tg.TradingAgentsGraph)
        handler = object()
        graph.callbacks = [handler]
        graph.propagator = _Propagator()
        graph.graph = _Graph()
        graph.debug = False
        graph.curr_state = None

        state = {"messages": [HumanMessage("hi")], "company_of_interest": "NVDA",
                 "trade_date": "2026-09-23"}
        monkeypatch.setattr(tg.TradingAgentsGraph, "create_run_state",
                            lambda *a, **k: state, raising=False)
        monkeypatch.setattr(tg.TradingAgentsGraph, "_log_state",
                            lambda *a, **k: None, raising=False)
        try:
            # The remaining post-run steps are irrelevant to callback wiring.
            graph._run_graph("NVDA", "2026-09-23")
        except Exception:  # noqa: BLE001 - only the callback hand-off is under test
            pass
        assert seen.get("callbacks") == [handler]

    def test_source_passes_self_callbacks(self):
        """Static guard: the call site must pass ``self.callbacks``."""
        src = (PROJECT_ROOT / "tradingagents" / "graph" / "trading_graph.py").read_text()
        tree = ast.parse(src)
        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get_graph_args"
        ]
        assert calls, "expected at least one get_graph_args() call"
        run_graph_calls = [
            c for c in calls
            if any(kw.arg == "callbacks" for kw in c.keywords)
        ]
        assert run_graph_calls, (
            "TradingAgentsGraph._run_graph must call "
            "get_graph_args(callbacks=self.callbacks); otherwise tool-call "
            "events are never recorded."
        )


class TestToolEventsThroughGraph:
    """Executing through a graph records tool events at run and agent level."""

    def test_tool_events_recorded_with_callbacks_in_config(self, tmp_path):
        from cli.stats_handler import StatsCallbackHandler

        handler = StatsCallbackHandler()
        payload = {}
        with o.run_telemetry([handler], results_dir=str(tmp_path), ticker="NVDA",
                             trade_date="2026-09-23") as collector:
            graph = _build_two_step_graph(handler)
            # Mirror the fixed `_run_graph`: callbacks in the invoke config.
            graph.invoke({"messages": [HumanMessage("hi")]},
                         config={"callbacks": [handler]})
            payload = collector.build_telemetry()

        rt = payload["run_totals"]
        assert rt["tool_rounds"] == 1
        assert rt["tool_calls"] == 1
        assert rt["tool_success_count"] == 1
        # Non-zero result bytes (LangChain reports a ToolMessage wrapper).
        assert rt["tool_result_utf8_bytes_sum"] > 0

        events = payload["tool_call_events"]
        market = payload["agents"][o.AGENT_MARKET_ANALYST]
        # Run-level and per-agent metrics agree with the recorded events.
        assert len(payload["tool_round_events"]) == rt["tool_rounds"]
        assert len(events) == rt["tool_calls"] == market["tool_calls"]
        assert sum(ev["result_utf8_bytes"] or 0 for ev in events) == \
            rt["tool_result_utf8_bytes_sum"] == market["tool_result_utf8_bytes_sum"]
        assert market["tool_rounds"] == 1
        assert all(ev["agent_id"] == o.AGENT_MARKET_ANALYST for ev in events)
        assert payload["audit_quality"]["attribution_complete"] is True

    def test_without_callbacks_rounds_alone_reproduce_discrepancy(self, tmp_path):
        """Documents the original symptom: rounds recorded, zero tool calls."""
        from cli.stats_handler import StatsCallbackHandler

        handler = StatsCallbackHandler()
        with o.run_telemetry([handler], results_dir=str(tmp_path), ticker="NVDA", trade_date="2026-09-23") as c:
            graph = _build_two_step_graph(handler)
            # Old behavior: callbacks only on the LLM constructor, none on invoke.
            graph.invoke({"messages": [HumanMessage("hi")]})
            payload = c.build_telemetry()
        rt = payload["run_totals"]
        assert rt["tool_rounds"] > 0
        assert rt["tool_calls"] == 0
        assert rt["tool_result_utf8_bytes_sum"] == 0
        assert payload["tool_call_events"] == []

    def test_no_raw_tool_output_in_events(self, tmp_path):
        from cli.stats_handler import StatsCallbackHandler

        handler = StatsCallbackHandler()
        with o.run_telemetry([handler], results_dir=str(tmp_path), ticker="NVDA", trade_date="2026-09-23") as c:
            graph = _build_two_step_graph(handler)
            graph.invoke({"messages": [HumanMessage("hi")]},
                         config={"callbacks": [handler]})
            payload = c.build_telemetry()
        blob = json.dumps(payload)
        assert TOOL_OUTPUT not in blob
        assert "synthetic_quote" in blob


class TestDualCallbackPathsDoNotDoubleCount:
    """The same handler arrives via the LLM constructor *and* the invoke config.

    Production wires one ``StatsCallbackHandler`` into ``ChatOpenAI(callbacks=)``
    and hands the same instance to ``graph.invoke(config={"callbacks": ...})``.
    Both paths must converge on a single event set: no duplicated LLM calls, no
    duplicated tool executions, and no doubled tool-result bytes.
    """

    def _build_llm_attached_graph(self, handler):
        from langchain_core.language_models.fake_chat_models import (
            GenericFakeChatModel,
        )

        responses = [
            AIMessage(content="", tool_calls=[
                {"name": "synthetic_quote", "args": {"symbol": "NVDA"},
                 "id": "call_dual", "type": "tool_call"},
            ]),
            AIMessage(content="final"),
        ]
        llm = GenericFakeChatModel(messages=iter(responses), callbacks=[handler])

        def agent(state):
            return {"messages": [llm.invoke(state["messages"])]}

        def should_continue(state):
            return "tools" if getattr(state["messages"][-1], "tool_calls", None) else END

        builder = StateGraph(MessagesState)
        builder.add_node(
            "Market Analyst",
            o.attrib_agent_node(o.AGENT_MARKET_ANALYST, agent, "Market Analyst"),
        )
        builder.add_node(
            "tools_market",
            o.attrib_tool_round(o.AGENT_MARKET_ANALYST, ToolNode([synthetic_quote])),
        )
        builder.add_edge(START, "Market Analyst")
        builder.add_conditional_edges(
            "Market Analyst", should_continue,
            {"tools": "tools_market", END: END},
        )
        builder.add_edge("tools_market", "Market Analyst")
        return builder.compile()

    def test_constructor_and_config_callbacks_count_each_event_once(self, tmp_path):
        from cli.stats_handler import StatsCallbackHandler

        handler = StatsCallbackHandler()
        with o.run_telemetry([handler], results_dir=str(tmp_path), ticker="NVDA",
                            trade_date="2026-09-23") as collector:
            graph = self._build_llm_attached_graph(handler)
            graph.invoke({"messages": [HumanMessage("hi")]},
                         config={"callbacks": [handler]})
            payload = collector.build_telemetry()

        rt = payload["run_totals"]
        # Two LLM turns (tool request + final answer) and one tool execution.
        assert rt["llm_calls"] == 2
        assert len(payload["llm_call_events"]) == 2
        assert rt["tool_calls"] == 1
        assert rt["tool_rounds"] == 1
        assert rt["tool_success_count"] == 1
        assert rt["tool_result_utf8_bytes_sum"] > 0
        assert len(payload["tool_call_events"]) == 1
        # A duplicated handler would double every counter above.
        assert handler.llm_calls == 2
        assert handler.tool_calls == 1
        assert payload["audit_quality"]["attribution_complete"] is True
        assert rt["tool_calls"] == payload["agents"][o.AGENT_MARKET_ANALYST]["tool_calls"]


class TestHarnessChildWiring:
    """The benchmark child must use the same callback-propagating path."""

    def test_run_single_uses_propagate(self):
        src = (PROJECT_ROOT / "scripts" / "token_benchmark.py").read_text()
        tree = ast.parse(src)
        funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        run_single = funcs["_run_single"]
        propagate_calls = [
            n for n in ast.walk(run_single)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "propagate"
        ]
        assert propagate_calls, "_run_single must execute via graph.propagate()"
        assert "callbacks" in src.split("def _run_single", 1)[1].split("graph.propagate", 1)[0], (
            "the graph must be constructed with the observability callback handler"
        )
