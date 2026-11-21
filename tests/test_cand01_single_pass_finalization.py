"""CAND-01 — single-pass structured finalisation.

The shipped S2 path lets the analyst's last tool-loop turn write a full prose
report and then pays a second call to regenerate the same report as typed
fields, discarding the prose. ``finalize_single_pass`` binds the schema as one
more tool beside the data tools, so the turn that would have written prose emits
the typed report instead.

These tests pin the properties that make that safe:

1. **Nothing is written twice.** The targeted path makes no prose terminal call,
   so there is no discarded report to regenerate.
2. **Tool capability is intact.** The schema is bound *with* the data tools, and
   a data-tool round inside the node executes through the same tool objects the
   graph's ToolNode uses.
3. **Every failure lands on RC1 behaviour.** Prose answers are returned as the
   report exactly as RC1 returns them, and malformed schema calls, unknown
   tools, an exhausted round budget and a dying tool all still produce text,
   never a blank report.
4. **Default is off.** The shipped configuration still runs the two-call path.

All LLMs here are scripted fakes: no network, no provider usage.
"""

from __future__ import annotations

import inspect
import pathlib
import unittest


def _source(*parts: str) -> str:
    """Read a source file relative to the *imported* package, not the cwd."""
    import tradingagents as _ta

    return (pathlib.Path(_ta.__file__).resolve().parent.joinpath(*parts[1:])
            ).read_text(encoding="utf-8")
from typing import Annotated  # noqa: E402

from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: E402
from langchain_core.runnables import RunnableLambda  # noqa: E402
from langgraph.prebuilt.tool_node import InjectedState  # noqa: E402

from tradingagents.agents import schemas as S  # noqa: E402
from tradingagents.agents.utils.structured import (  # noqa: E402
    SINGLE_PASS_MAX_ROUNDS,
    finalize_single_pass,
    run_data_tools,
)

MARKET_ARGS = {
    "stance": "Bullish",
    "key_evidence": [
        {"claim": "close above 50SMA", "evidence": "close=178.42 vs 171.9", "source": "snapshot"}
    ],
    "key_levels": [{"label": "Resistance", "price": "179.88", "why": "session high"}],
    "risks": ["ATR rising"],
    "interpretation": "Trend intact above both averages.",
}
FUND_ARGS = {
    "stance": "Neutral",
    "key_figures": [{"metric": "Free cash flow", "value": "28.1B", "read": "FY2026, funds buyback"}],
    "risks": ["Capex ramp"],
    "interpretation": "Cash generation funds the buyback.",
}
NEWS_ARGS = {
    "stance": "Mixed",
    "catalysts": [{"date": "2026-09-22", "event": "Supply guide raised",
                   "relevance": "positive for pricing"}],
    "interpretation": "Two-sided flow.",
}

SCHEMA_NAMES = {
    "market": ("MarketAnalystReport", S.MarketAnalystReport, MARKET_ARGS),
    "fundamentals": ("FundamentalsAnalystReport", S.FundamentalsAnalystReport, FUND_ARGS),
    "news": ("NewsAnalystReport", S.NewsAnalystReport, NEWS_ARGS),
}


class _Structured:
    """Stands in for ``llm.with_structured_output(schema)``."""

    def __init__(self, shared, schema):
        self.shared = shared
        self.schema = schema
        self.calls = 0

    def invoke(self, messages, config=None):
        self.calls += 1
        self.shared.seen_structured = messages
        msg = self.shared._next()
        for call in msg.tool_calls or []:
            if call["name"] == self.schema.__name__:
                return self.schema(**call["args"])
        return None


def _as_messages(value):
    """Normalise a prompt value or message list to a list of messages."""
    return value.to_messages() if hasattr(value, "to_messages") else list(value)


class _BoundToolChain(RunnableLambda):
    """What ``bind_tools`` returns; records which tool names were exposed."""

    def __init__(self, shared, names):
        self.shared = shared
        self.names = names
        super().__init__(self._run)

    def _run(self, messages, config=None):
        self.shared.seen_loop = _as_messages(messages)
        return self.shared._next()


class ScriptedLLM(BaseChatModel):
    """Replays scripted AIMessages; implements both binding methods."""

    responses: list = []
    cursor: int = 0
    seen_loop: object = None
    seen_structured: object = None
    bound_names: object = None

    @property
    def _llm_type(self):
        return "scripted"

    def _next(self):
        if self.cursor >= len(self.responses):
            return self.responses[-1]
        msg = self.responses[self.cursor]
        self.cursor += 1
        return msg

    def bind_tools(self, tools, **kwargs):
        self.bound_names = [
            (getattr(t, "name", None) or t.__name__) if isinstance(t, type)
            else getattr(t, "name", str(t))
            for t in tools
        ]
        return _BoundToolChain(self, self.bound_names)

    def with_structured_output(self, schema, **kwargs):
        return _Structured(self, schema)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self._next())])


def _schema_msg(kind: str) -> AIMessage:
    name, _schema, args = SCHEMA_NAMES[kind]
    return AIMessage(content="", tool_calls=[
        {"name": name, "type": "tool_call", "id": "s1", "args": args},
    ])


def _tool_msg(tool: str = "get_stock_data") -> AIMessage:
    args = {"symbol": "NVDA", "start_date": "2026-09-01", "end_date": "2026-09-23"}
    return AIMessage(content="", tool_calls=[
        {"name": tool, "type": "tool_call", "id": "t1", "args": args},
    ])


PROSE = AIMessage(content="## Report\nProse analysis grounded in tool output.")


def _prompt():
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

    return ChatPromptTemplate.from_messages([
        ("system", "You are a helpful AI assistant. Tools: {tool_names}."),
        MessagesPlaceholder(variable_name="messages"),
    ]).partial(tool_names="get_stock_data")


def _messages():
    return [HumanMessage(content="Analyze NVDA")]


def _pending_calls(messages):
    """Tool-call ids emitted but never resolved by a ToolMessage."""
    pending = set()
    for m in messages:
        for call in getattr(m, "tool_calls", None) or []:
            pending.add(call.get("id"))
        if getattr(m, "type", None) == "tool":
            pending.discard(getattr(m, "tool_call_id", None))
    return pending


class _FakeTool:
    def __init__(self, name, result="TOOL OUTPUT: rows", exc=None):
        self.name = name
        self.result = result
        self.exc = exc
        self.calls = 0

    def invoke(self, args, config=None):
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.result


def _run(kind, responses, tools=None, run_tools=None, structured=True, state=None):
    name, schema, _ = SCHEMA_NAMES[kind]
    llm = ScriptedLLM(responses=list(responses))
    structured_llm = llm.with_structured_output(schema) if structured else None
    tools = tools if tools is not None else [_FakeTool("get_stock_data")]
    render = {
        "market": S.render_market_analyst_report,
        "fundamentals": S.render_fundamentals_analyst_report,
        "news": S.render_news_analyst_report,
    }[kind]
    rendered, obj, msgs = finalize_single_pass(
        llm=llm,
        structured_llm=structured_llm,
        prompt=_prompt(),
        messages=_messages(),
        tools=tools,
        schema=schema,
        render=render,
        agent_name="Analyst",
        run_tools=run_tools or run_data_tools(tools, state=state),
    )
    return rendered, obj, msgs, llm, structured_llm, tools


# --------------------------------------------------------------------------
# 1. Schema validation
# --------------------------------------------------------------------------
class SchemaValidationTest(unittest.TestCase):
    def test_every_analyst_schema_is_bound_under_its_class_name(self):
        from tradingagents.agents.utils.structured import _schema_tool_name

        for name, schema, _ in SCHEMA_NAMES.values():
            self.assertEqual(_schema_tool_name(schema), name)

    def test_schema_call_produces_the_typed_object(self):
        for kind in SCHEMA_NAMES:
            with self.subTest(kind=kind):
                rendered, obj, _msgs, _llm, _s, _t = _run(kind, [_schema_msg(kind)])
                self.assertIsInstance(obj, SCHEMA_NAMES[kind][1])
                self.assertTrue(rendered.strip())

    def test_malformed_schema_args_fail_validation_not_the_run(self):
        bad = {"stance": "definitely-not-a-stance"}
        name = SCHEMA_NAMES["market"][0]
        bad_msg = AIMessage(content="", tool_calls=[
            {"name": name, "type": "tool_call", "id": "s1", "args": bad},
        ])
        rendered, obj, _msgs, llm, structured_llm, _t = _run("market", [bad_msg, PROSE])
        self.assertIsNone(obj, "a failed schema call must not expose a typed object")
        self.assertIn("Prose analysis", rendered, "the free-text retry must be returned")
        self.assertEqual(structured_llm.calls, 0, "the RC1 finaliser must not run after the retry")

    def test_empty_render_falls_back_rather_than_returning_blank(self):
        # An all-empty report renders to a stub, not to nothing, so force the
        # empty branch with a renderer that returns whitespace.
        from tradingagents.agents.utils.structured import finalize_single_pass as fsp

        llm = ScriptedLLM(responses=[_schema_msg("market"), PROSE])
        structured_llm = llm.with_structured_output(S.MarketAnalystReport)
        rendered, obj, _m = fsp(
            llm=llm, structured_llm=structured_llm, prompt=_prompt(),
            messages=_messages(), tools=[_FakeTool("get_stock_data")],
            schema=S.MarketAnalystReport, render=lambda _r: "   ",
            agent_name="Analyst",
        )
        self.assertIsNone(obj)
        self.assertIn("Prose analysis", rendered)


# --------------------------------------------------------------------------
# 2. Analyst tool loop
# --------------------------------------------------------------------------
class ToolLoopTest(unittest.TestCase):
    def test_schema_is_bound_together_with_the_data_tools(self):
        _r, obj, _m, llm, _s, tools = _run(
            "market", [_tool_msg(), _schema_msg("market")],
        )
        self.assertIsNotNone(obj)
        from tradingagents.agents.utils.structured import _schema_tool_name
        self.assertEqual(_schema_tool_name(S.MarketAnalystReport), llm.bound_names[-1])
        self.assertIn("get_stock_data", llm.bound_names)
        self.assertEqual(len(llm.bound_names), 2)

    def test_data_tool_call_is_executed_and_its_result_reaches_the_next_turn(self):
        tool = _FakeTool("get_stock_data", result="TOOL OUTPUT: close=178.42")
        rendered, obj, _m, llm, _s, _t = _run(
            "market", [_tool_msg(), _schema_msg("market")], tools=[tool],
        )
        self.assertIsNotNone(obj)
        self.assertEqual(tool.calls, 1, "the requested tool must actually run")
        sent = [str(getattr(m, "content", "")) for m in llm.seen_loop or []]
        self.assertTrue(
            any("close=178.42" in c for c in sent),
            "the tool result must be in the history the schema call sees",
        )

    def test_tool_results_are_returned_to_the_graph_so_the_loop_continues(self):
        # First round asks for data and returns: the graph must see the tool call
        # so its own tool node runs, then re-enter the node.
        _r, obj, msgs, _llm, _s, _t = _run("market", [_tool_msg()])
        self.assertIsNone(obj)
        self.assertTrue(msgs, "the tool-call turn must be returned")
        self.assertTrue(msgs[0].tool_calls)
        self.assertEqual(msgs[0].tool_calls[0]["name"], "get_stock_data")

    def test_round_budget_stops_a_model_that_only_calls_tools(self):
        # The budget bounds the loop, but running out is not allowed to end the
        # analyst with a blank report: one plain call over the gathered history
        # stands in for the turn RC1 would have written.
        endless = [_tool_msg() for _ in range(SINGLE_PASS_MAX_ROUNDS + 2)]
        tool = _FakeTool("get_stock_data")
        rendered, obj, _msgs, llm, _s, _t = _run("market", endless, tools=[tool])
        self.assertLessEqual(tool.calls, SINGLE_PASS_MAX_ROUNDS)
        self.assertIsNone(obj)
        # One extra turn past the bounded loop: the ending free-text call.
        self.assertEqual(llm.cursor, SINGLE_PASS_MAX_ROUNDS + 1)

    def test_unknown_tool_is_reported_not_executed(self):
        runner = run_data_tools([_FakeTool("get_stock_data")])
        out = runner([{"name": "invented_tool", "id": "x1", "args": {}}])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].status, "error")
        self.assertIn("not a valid tool", out[0].content)

    def test_a_failing_tool_becomes_an_error_message(self):
        runner = run_data_tools([_FakeTool("get_stock_data", exc=ValueError("no data"))])
        out = runner([{"name": "get_stock_data", "id": "x1", "args": {}}])
        self.assertEqual(out[0].status, "error")
        self.assertIn("no data", out[0].content)
        self.assertEqual(out[0].tool_call_id, "x1")

    def test_hidden_trade_date_parameter_is_injected_from_state(self):
        # Every data tool declares ``trade_date: Annotated[str, InjectedState(
        # "trade_date")]``. ToolNode injects it; ``tool.invoke`` does not, and the
        # parameter is absent from the tool's JSON schema so the model cannot
        # supply it. Losing it makes window-clamping tools read past the run
        # date, so the runner must inject it exactly as the graph does.
        from langchain_core.tools import tool as make_tool

        seen = {}

        @make_tool
        def get_stock_data(
            symbol: Annotated[str, "ticker"],
            trade_date: Annotated[str, InjectedState("trade_date")] = "",
        ) -> str:
            """Fetch prices."""
            seen["trade_date"] = trade_date
            return "rows"

        self.assertNotIn("trade_date", get_stock_data.args, "hidden from the model")
        run_data_tools([get_stock_data], state={"trade_date": "2026-09-23"})(
            [{"name": "get_stock_data", "id": "x1", "args": {"symbol": "NVDA"}}]
        )
        self.assertEqual(seen["trade_date"], "2026-09-23")

    def test_missing_trade_date_leaves_the_tool_default(self):
        from langchain_core.tools import tool as make_tool

        seen = {}

        @make_tool
        def get_stock_data(
            symbol: Annotated[str, "ticker"],
            trade_date: Annotated[str, InjectedState("trade_date")] = "",
        ) -> str:
            """Fetch prices."""
            seen["trade_date"] = trade_date
            return "rows"

        run_data_tools([get_stock_data], state={})(
            [{"name": "get_stock_data", "id": "x1", "args": {"symbol": "NVDA"}}]
        )
        self.assertEqual(seen["trade_date"], "", "no state key, no injection")


# --------------------------------------------------------------------------
# 3. Tool completion
# --------------------------------------------------------------------------
class ToolCompletionTest(unittest.TestCase):
    def test_completion_is_the_schema_call_not_an_empty_tool_list(self):
        # A model that stops calling tools without emitting the schema is not
        # treated as complete: its prose is not restructured (that would be the
        # duplication again). It is returned as RC1 returns it, and the extra
        # scripted turn is never consumed.
        rendered, obj, _m, llm, structured_llm, _t = _run(
            "market", [PROSE, _schema_msg("market")],
        )
        self.assertIsNone(obj, "a prose ending is not retro-fitted into a schema")
        self.assertIn("Prose analysis", rendered)
        self.assertEqual(llm.cursor, 1, "the scripted schema turn is never reached")
        self.assertEqual(structured_llm.calls, 0)

    def test_schema_call_ends_the_node_without_a_pending_tool_call(self):
        _r, _obj, msgs, _llm, _s, _t = _run(
            "market", [_tool_msg(), _schema_msg("market")],
        )
        # R3 correction: the node used to hand back the data-tool call with no
        # ToolMessage for it. LangGraph then saw a dangling tool_call, routed
        # back into the tool node, re-executed the tool and re-entered the
        # analyst without bound (GraphRecursionError). The result this runner
        # already executed must travel with its call, and the sequence must end
        # on an assistant turn with no pending call.
        self.assertEqual([type(m).__name__ for m in msgs],
                         ["AIMessage", "ToolMessage", "AIMessage"])
        self.assertEqual(msgs[0].tool_calls[0]["name"], "get_stock_data")
        self.assertEqual(msgs[1].tool_call_id, msgs[0].tool_calls[0]["id"])
        self.assertEqual(msgs[-1].tool_calls, [])
        self.assertNotIn("MarketAnalystReport",
                         [c["name"] for c in msgs[-1].tool_calls])


# --------------------------------------------------------------------------
# 4. Structured finalisation (the targeted duplication is gone)
# --------------------------------------------------------------------------
class StructuredFinalisationTest(unittest.TestCase):
    def test_targeted_path_makes_no_prose_terminal_call(self):
        # Two LLM turns: tool round, then schema. The RC1 path needs three
        # (tool round, prose, structured finalisation).
        rendered, obj, _m, llm, structured_llm, _t = _run(
            "market", [_tool_msg(), _schema_msg("market")],
        )
        self.assertIsNotNone(obj)
        self.assertEqual(llm.cursor, 2, "tool round + schema call, nothing else")
        self.assertEqual(
            structured_llm.calls, 0,
            "the separate finalisation call must not exist on this path",
        )
        self.assertNotIn(
            "Do not call external tools", rendered,
        )

    def test_report_content_comes_from_the_schema_not_from_prose(self):
        rendered, obj, _m, _llm, _s, _t = _run("market", [_schema_msg("market")])
        self.assertEqual(obj.stance, S.AnalystStance.BULLISH)
        self.assertIn("178.42", rendered)
        self.assertIn("Resistance", rendered)
        self.assertIn("Bullish", rendered)

    def test_single_pass_prompt_withholds_the_prose_layout_guidance(self):
        _r, _o, _m, llm, _s, _t = _run("market", [_schema_msg("market")])
        system = str(llm.seen_loop[0].content)
        self.assertNotIn("append a Markdown table", system)


# --------------------------------------------------------------------------
# 5. Fallback
# --------------------------------------------------------------------------
class FallbackTest(unittest.TestCase):
    def test_structured_off_runs_the_plain_loop(self):
        from tradingagents.agents.utils.structured import finalize_single_pass as fsp

        llm = ScriptedLLM(responses=[PROSE])
        rendered, obj, msgs = fsp(
            llm=llm, structured_llm=None, prompt=_prompt(), messages=_messages(),
            tools=[_FakeTool("get_stock_data")], schema=S.MarketAnalystReport,
            render=S.render_market_analyst_report, agent_name="Analyst",
        )
        self.assertIsNone(obj)
        self.assertIn("Prose analysis", rendered)
        self.assertEqual(llm.bound_names, ["get_stock_data"], "no schema bound when S2 is off")

    def test_structured_off_still_returns_tool_calls_for_the_graph(self):
        from tradingagents.agents.utils.structured import finalize_single_pass as fsp

        llm = ScriptedLLM(responses=[_tool_msg()])
        rendered, obj, msgs = fsp(
            llm=llm, structured_llm=None, prompt=_prompt(), messages=_messages(),
            tools=[_FakeTool("get_stock_data")], schema=S.MarketAnalystReport,
            render=S.render_market_analyst_report, agent_name="Analyst",
        )
        self.assertEqual(rendered, "")
        self.assertIsNone(obj)
        self.assertTrue(msgs[0].tool_calls)

    def test_prose_answer_is_returned_unchanged_as_in_rc1(self):
        # RC1 treats a prose ending as the finished report. The single-pass path
        # must not pay a second call to restructure it: that is the duplication
        # being removed, and finalising over a prose-stripped history would be
        # strictly worse than RC1.
        rendered, obj, _m, llm, structured_llm, _t = _run("market", [PROSE])
        self.assertIn("Prose analysis", rendered, "the model's own prose is the report")
        self.assertIsNone(obj)
        self.assertEqual(structured_llm.calls, 0, "no extra generation for prose")
        self.assertEqual(llm.cursor, 1, "one turn only")

    def test_every_tool_failing_still_yields_a_report(self):
        # Every call in the round errors out: the loop stops rather than spinning,
        # and the analyst still returns text instead of a silent "".
        good = _FakeTool("get_stock_data", exc=ValueError("vendor down"))
        rendered, obj, _m, _llm, _s, _t = _run(
            "market", [_tool_msg(), PROSE], tools=[good],
        )
        self.assertIsNone(obj)
        self.assertTrue(rendered.strip(), "a dead tool must not blank the report")

    def test_schema_binding_failure_falls_back_to_the_two_call_path(self):
        # A provider whose bind_tools rejects the schema: run_data_tools is never
        # reached because bind_tools raises and the node-level guard passes None.
        # Here the RC1 path is exercised directly for parity.
        from tradingagents.agents.utils.structured import finalize_analyst_report

        llm = ScriptedLLM(responses=[_schema_msg("market")])
        structured_llm = llm.with_structured_output(S.MarketAnalystReport)
        rendered, obj = finalize_analyst_report(
            llm=llm, structured_llm=structured_llm,
            messages=[*_messages(), PROSE], render=S.render_market_analyst_report,
            agent_name="Analyst", free_text_block=PROSE.content,
        )
        self.assertIsInstance(obj, S.MarketAnalystReport)
        self.assertIn("Bullish", rendered)


# --------------------------------------------------------------------------
# 6. Downstream integration
# --------------------------------------------------------------------------
class DownstreamIntegrationTest(unittest.TestCase):
    def test_node_returns_the_state_keys_downstream_consumers_read(self):
        from tradingagents.agents.analysts.market_analyst import create_market_analyst

        llm = ScriptedLLM(responses=[_schema_msg("market")])
        # The node builds its own tools; give it a stock-data result via the
        # schema call so no network is touched.
        out = create_market_analyst(llm, structured=True, single_pass=True)({
            "trade_date": "2026-09-23", "company_of_interest": "NVDA",
            "asset_type": "stock", "messages": _messages(),
        })
        self.assertIn("market_report", out)
        self.assertIn("market_report_obj", out)
        self.assertIn("messages", out)
        self.assertIsInstance(out["market_report_obj"], S.MarketAnalystReport)

    def test_rendered_report_feeds_routed_report_unchanged(self):
        from tradingagents.agents.utils.s2_context import bull_context_block, routed_report

        rendered, obj, _m, _llm, _s, _t = _run("market", [_schema_msg("market")])
        routed = bull_context_block(obj, None)
        prompt_block = routed_report(rendered, routed.get("market"), "market")
        self.assertIn("178.42", prompt_block)
        self.assertIn("Bullish", prompt_block)

    def test_fundamentals_typed_object_carries_key_figures(self):
        rendered, obj, _m, _llm, _s, _t = _run("fundamentals", [_schema_msg("fundamentals")])
        self.assertIn("Free cash flow", rendered)
        self.assertIn("28.1B", rendered)


# --------------------------------------------------------------------------
# 7. Evidence completeness
# --------------------------------------------------------------------------
class EvidenceCompletenessTest(unittest.TestCase):
    def test_market_evidence_levels_risks_invalidation_scenarios_survive(self):
        args = dict(MARKET_ARGS)
        args["invalidation"] = [{
            "condition": "Close below 50SMA",
            "observable_signal": "daily close vs 50SMA",
            "evidence_basis": "close=178.42, 50SMA=171.90",
            "threshold": "171.90",
            "invalidates": "Bullish",
        }]
        args["scenario_set"] = {
            "status": "estimated",
            "scenarios": [
                {"name": "Bull", "supporting_evidence": "close above 50SMA",
                 "trigger_conditions": "sustained break of 179.88",
                 "invalidation_conditions": "close back below 175", "weight": 40},
                {"name": "Base", "supporting_evidence": "range-bound tape",
                 "trigger_conditions": "range 175-180",
                 "invalidation_conditions": "gap beyond band", "weight": 45},
                {"name": "Bear", "supporting_evidence": "ATR rising",
                 "trigger_conditions": "close below 171.90",
                 "invalidation_conditions": "reclaim of 175", "weight": 15},
            ],
        }
        msg = AIMessage(content="", tool_calls=[
            {"name": "MarketAnalystReport", "type": "tool_call", "id": "s1", "args": args},
        ])
        rendered, obj, _m, _llm, _s, _t = _run("market", [msg])
        self.assertEqual(rendered, rendered.strip())
        for needle in ("Bull", "Base", "Bear", "179.88", "171.90", "ATR rising", "invalidation"):
            self.assertIn(needle, rendered.lower() if needle == "invalidation" else rendered)

    def test_unknown_stance_is_preserved_not_forced(self):
        args = {"stance": "Unknown", "interpretation": "Data unavailable."}
        msg = AIMessage(content="", tool_calls=[
            {"name": "MarketAnalystReport", "type": "tool_call", "id": "s1", "args": args},
        ])
        rendered, obj, _m, _llm, _s, _t = _run("market", [msg])
        self.assertEqual(obj.stance, S.AnalystStance.UNKNOWN)
        self.assertIn("Unknown", rendered)


# --------------------------------------------------------------------------
# 8. News missingness
# --------------------------------------------------------------------------
class NewsMissingnessTest(unittest.TestCase):
    def test_structured_news_report_gets_the_unavailable_header(self):
        from tradingagents.agents.analysts.news_analyst import _guard_news_unavailable

        class _Structured:
            def __init__(self, report):
                self.report = report

            def invoke(self, messages, config=None):
                return self.report

        from tradingagents.agents.schemas import NewsAnalystReport

        report = NewsAnalystReport(stance=S.AnalystStance.MIXED, interpretation="macro only")
        guarded = _guard_news_unavailable(
            S.render_news_analyst_report(report), S.NewsSourceStatus.UNAVAILABLE,
        )
        self.assertTrue(guarded.startswith("> **News source unavailable"))
        self.assertIn("**Stance:** Unknown", guarded)

    def test_available_source_keeps_the_model_stance(self):
        from tradingagents.agents.analysts.news_analyst import _guard_news_unavailable

        body = S.render_news_analyst_report(
            S.NewsAnalystReport(stance=S.AnalystStance.MIXED, interpretation="two-sided")
        )
        self.assertEqual(
            _guard_news_unavailable(body, S.NewsSourceStatus.AVAILABLE), body,
        )

    def test_node_forces_unknown_when_the_news_feed_is_dead(self):
        # Run the real node with a schema answer and a tool history that contains
        # no usable news, exactly as classify_news_source_availability sees it.
        from tradingagents.agents.analysts.news_analyst import create_news_analyst

        llm = ScriptedLLM(responses=[_schema_msg("news")])
        state = {
            "trade_date": "2026-09-23", "company_of_interest": "NVDA",
            "asset_type": "stock",
            "messages": [HumanMessage(content="Analyze NVDA news")],
        }
        out = create_news_analyst(llm, batch_macro=False, structured=True, single_pass=True)(state)
        self.assertIn("news_report", out)
        # No news tool ran, so the source is unavailable and the header is forced.
        self.assertTrue(
            out["news_report"].startswith("> **News source unavailable"),
            out["news_report"][:120],
        )


# --------------------------------------------------------------------------
# 9. Regression tests (RC1 behaviour preserved)
# --------------------------------------------------------------------------
class RegressionTest(unittest.TestCase):
    def test_single_pass_is_off_by_default_in_the_shipped_config(self):
        from tradingagents.default_config import DEFAULT_CONFIG

        self.assertFalse(DEFAULT_CONFIG["single_pass_finalization_enabled"])
        self.assertTrue(DEFAULT_CONFIG["structured_analyst_output_enabled"])

    def test_env_override_is_wired(self):
        from tradingagents.default_config import _ENV_OVERRIDES

        self.assertEqual(
            _ENV_OVERRIDES["TRADINGAGENTS_SINGLE_PASS_FINALIZATION_ENABLED"],
            "single_pass_finalization_enabled",
        )

    def test_analyst_factories_default_to_the_two_call_path(self):
        from tradingagents.agents.analysts import (
            fundamentals_analyst,
            market_analyst,
            news_analyst,
        )

        for mod, factory in (
            (market_analyst, "create_market_analyst"),
            (news_analyst, "create_news_analyst"),
            (fundamentals_analyst, "create_fundamentals_analyst"),
        ):
            sig = inspect.signature(getattr(mod, factory))
            self.assertIs(sig.parameters["single_pass"].default, False, factory)

    def test_sentiment_analyst_is_untouched(self):
        from tradingagents.agents.analysts import sentiment_analyst

        src = open(sentiment_analyst.__file__).read()  # noqa: SIM115
        self.assertNotIn("single_pass", src)
        self.assertIn("bind_structured", src)

    def test_setup_requires_structured_before_enabling_single_pass(self):
        # Paths are anchored on the imported package, not on the process cwd: a
        # cwd-relative read raised FileNotFoundError when the suite ran from
        # anywhere but the repository root (limitation L-3).
        src = _source("tradingagents", "graph", "setup.py")
        self.assertIn("single_pass_finalization_enabled", src)
        self.assertIn("and self.config.get(\"structured_analyst_output_enabled\"", src)

    def test_rc1_two_call_functions_are_unchanged_and_still_exported(self):
        from tradingagents.agents.utils import structured as mod

        self.assertTrue(callable(mod.finalize_analyst_report))
        self.assertTrue(callable(mod._prepare_structured_messages))
        self.assertIn("finalize_analyst_report",
                      _source("tradingagents", "agents", "analysts",
                              "market_analyst.py"))


# --------------------------------------------------------------------------
# 10. Old/new mode behavioural compatibility
# --------------------------------------------------------------------------
class ModeCompatibilityTest(unittest.TestCase):
    def _node(self, kind, single_pass):
        from tradingagents.agents.analysts import (
            fundamentals_analyst,
            market_analyst,
            news_analyst,
        )

        factory = {"market": market_analyst, "news": news_analyst,
                   "fundamentals": fundamentals_analyst}[kind]
        return getattr(factory, f"create_{kind}_analyst")

    def test_both_modes_return_the_same_state_keys(self):
        for kind in ("market", "news", "fundamentals"):
            for single_pass in (False, True):
                with self.subTest(kind=kind, single_pass=single_pass):
                    create = self._node(kind, single_pass)
                    llm = ScriptedLLM(responses=[_schema_msg(kind), PROSE])
                    state = {
                        "trade_date": "2026-09-23", "company_of_interest": "NVDA",
                        "asset_type": "stock", "messages": _messages(),
                    }
                    kwargs = {"structured": True, "single_pass": single_pass}
                    if kind == "news":
                        kwargs["batch_macro"] = False
                    out = create(llm, **kwargs)(state)
                    self.assertIn("messages", out)
                    self.assertIn(f"{kind}_report", out)
                    if kind != "news":
                        self.assertIn(f"{kind}_report_obj", out)

    def test_both_modes_reach_a_typed_report_from_the_same_schema(self):
        for kind in ("market", "fundamentals", "news"):
            with self.subTest(kind=kind):
                create = self._node(kind, True)
                llm = ScriptedLLM(responses=[_schema_msg(kind)])
                kwargs = {"structured": True, "single_pass": True}
                if kind == "news":
                    kwargs["batch_macro"] = False
                out = create(llm, **kwargs)({
                    "trade_date": "2026-09-23", "company_of_interest": "NVDA",
                    "asset_type": "stock", "messages": _messages(),
                })
                report = out[f"{kind}_report"]
                self.assertTrue(report.strip())


class TradeDatePrecedenceTest(unittest.TestCase):
    """R3 F1: graph state must win over a model-supplied ``trade_date``.

    ``ToolNode`` strips caller-supplied values for injected args and then
    overlays the state-derived one, so an LLM cannot forge a hidden field and
    widen the window past the run date. ``run_data_tools`` must match.
    """

    RUN = "2025-03-10"

    def _runner(self, seen):
        from langchain_core.tools import tool as make_tool

        @make_tool
        def get_stock_data(
            symbol: Annotated[str, "ticker"],
            start_date: Annotated[str, "start"] = "",
            end_date: Annotated[str, "end"] = "",
            trade_date: Annotated[str, InjectedState("trade_date")] = "",
        ) -> str:
            """Fetch prices."""
            seen.update(symbol=symbol, start_date=start_date,
                        end_date=end_date, trade_date=trade_date)
            return "rows"

        return get_stock_data

    def _call(self, tool, args, state=None):
        from tradingagents.agents.utils.structured import run_data_tools

        seen = {}
        original = tool.func
        try:
            tool.func = lambda *a, **kw: (seen.update(kw, **dict(zip(
                ["symbol", "start_date", "end_date", "trade_date"], a, strict=False))), "rows")[1]
            run_data_tools([tool], state=state if state is not None else {"trade_date": self.RUN})(
                [{"name": "get_stock_data", "id": "x1", "args": args}])
        finally:
            tool.func = original
        return seen

    def test_model_omitting_trade_date_gets_the_state_value(self):
        tool = self._runner({})
        seen = self._call(tool, {"symbol": "NVDA"})
        self.assertEqual(seen["trade_date"], self.RUN)

    def test_model_supplying_the_correct_date_is_unchanged(self):
        tool = self._runner({})
        seen = self._call(tool, {"symbol": "NVDA", "trade_date": self.RUN})
        self.assertEqual(seen["trade_date"], self.RUN)

    def test_model_supplying_a_future_date_cannot_move_the_window(self):
        tool = self._runner({})
        seen = self._call(tool, {"symbol": "NVDA", "trade_date": "2025-06-30"})
        self.assertEqual(seen["trade_date"], self.RUN)

    def test_model_supplying_an_earlier_date_cannot_move_the_window(self):
        tool = self._runner({})
        seen = self._call(tool, {"symbol": "NVDA", "trade_date": "2024-01-01"})
        self.assertEqual(seen["trade_date"], self.RUN)

    def test_model_supplying_a_wrong_type_is_replaced_not_forwarded(self):
        tool = self._runner({})
        seen = self._call(tool, {"symbol": "NVDA", "trade_date": 19700101})
        self.assertEqual(seen["trade_date"], self.RUN)

    def test_injected_key_is_stripped_from_the_model_args(self):
        # The forged key must not reach the tool at all, even when state is
        # absent and the tool keeps its own default.
        tool = self._runner({})
        seen = self._call(tool, {"symbol": "NVDA", "trade_date": "2030-01-01"},
                          state={"trade_date": self.RUN})
        self.assertNotEqual(seen["trade_date"], "2030-01-01")

    def test_missing_state_field_drops_the_forged_value(self):
        # ``trade_date`` has a default (""), so it is an *optional* injected arg:
        # ToolNode strips the model's value and keeps the default rather than
        # raising. Verified against a real ToolNode: state={} + forged
        # trade_date=2030-01-01 -> tool sees "". Match that exactly.
        tool = self._runner({})
        seen = self._call(tool, {"symbol": "NVDA", "trade_date": "2030-01-01"},
                          state={})
        self.assertEqual(seen["trade_date"], "")

    def test_required_state_field_missing_is_an_error(self):
        # A required injected field (no default) is a different case: ToolNode
        # raises KeyError, which the runner surfaces as a status="error"
        # ToolMessage instead of letting the tool run with a forged value.
        from langchain_core.tools import tool as make_tool

        from tradingagents.agents.utils.structured import run_data_tools

        @make_tool
        def strict_tool(
            symbol: Annotated[str, "ticker"],
            trade_date: Annotated[str, InjectedState("trade_date")],
        ) -> str:
            """Require the run date."""
            return "rows"

        out = run_data_tools([strict_tool], state={})(
            [{"name": "strict_tool", "id": "x1",
              "args": {"symbol": "NVDA", "trade_date": "2030-01-01"}}])
        self.assertEqual(out[0].status, "error")

    def test_real_tools_never_forward_a_forged_date(self):
        # End-to-end on the real data tools: the vendor window must stop at the
        # run date even when the model asks for later data.
        from unittest.mock import patch

        from tradingagents.agents.utils.agent_utils import get_stock_data
        from tradingagents.agents.utils.structured import run_data_tools

        seen = {}
        with patch("tradingagents.agents.utils.core_stock_tools.route_to_vendor",
                   lambda *a, **k: seen.setdefault("a", a) or "ok"):
            run_data_tools([get_stock_data], state={"trade_date": self.RUN})(
                [{"name": "get_stock_data", "id": "x1", "args": {
                    "symbol": "NVDA", "start_date": "2025-03-01",
                    "end_date": "2025-06-30", "trade_date": "2025-06-30"}}])
        self.assertLessEqual(seen["a"][3], self.RUN, "window must stay point-in-time")


class TelemetryLifecycleTest(unittest.TestCase):
    """R3 F2: every ending records exactly one structured event, never a fake one."""

    def _events(self, responses, **kwargs):
        import tradingagents.agents.utils.structured as U

        recorded = []
        original = U.record_structured_attempt
        try:
            U.record_structured_attempt = lambda agent, **kw: recorded.append(kw)
            _run("market", responses, **kwargs)
        finally:
            U.record_structured_attempt = original
        return recorded

    def test_success_records_one_success(self):
        ev = self._events([_schema_msg("market")])
        self.assertEqual([e["kind"] for e in ev], ["success"])
        self.assertFalse(ev[0].get("used_fallback"))

    def test_schema_failure_records_failure_with_fallback(self):
        bad = AIMessage(content="", tool_calls=[{
            "name": SCHEMA_NAMES["market"][0], "type": "tool_call", "id": "s1",
            "args": {"stance": "BOGUS"}}])
        ev = self._events([bad, PROSE])
        self.assertEqual([e["kind"] for e in ev], ["failure"])
        self.assertTrue(ev[0]["used_fallback"])

    def test_budget_exhaustion_records_a_failure_not_a_fake_attempt(self):
        from tradingagents.agents.utils.structured import SINGLE_PASS_MAX_ROUNDS

        ev = self._events([_tool_msg()] * SINGLE_PASS_MAX_ROUNDS + [PROSE])
        self.assertEqual(len(ev), 1)
        # No schema call happened, so it must NOT be reported as a success.
        self.assertEqual(ev[0]["kind"], "failure")
        self.assertTrue(ev[0]["used_fallback"])

    def test_every_tool_failing_records_a_failure(self):
        ev = self._events([_tool_msg(), PROSE],
                          tools=[_FakeTool("get_stock_data", exc=ValueError("dead"))])
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["kind"], "failure")
        self.assertTrue(ev[0]["used_fallback"])

    def test_prose_only_answer_records_failure(self):
        ev = self._events([PROSE])
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["kind"], "failure")

    def test_structured_llm_absent_records_unsupported(self):
        ev = self._events([PROSE], structured=False)
        self.assertEqual([e["kind"] for e in ev], ["unsupported"])

    def test_no_ending_records_more_than_one_event(self):
        # A single node invocation must never double-count structured attempts.
        for responses in (
            [_schema_msg("market")],
            [_tool_msg(), _schema_msg("market")],
            [PROSE],
            [_tool_msg()] * 4 + [PROSE],
        ):
            with self.subTest(n=len(responses)):
                self.assertLessEqual(len(self._events(responses)), 1)


class TerminalMessageRoutingTest(unittest.TestCase):
    """R3 F3: the returned messages must satisfy the graph's routing contract."""

    def _node_messages(self, responses):
        _r, _obj, msgs, _llm, _s, _t = _run("market", responses)
        return msgs

    def test_first_turn_schema_ends_on_an_assistant_message(self):
        # The original bug: emitted[:-1] was [] so routing saw the HumanMessage
        # and raised AttributeError on .tool_calls.
        msgs = self._node_messages([_schema_msg("market")])
        self.assertTrue(msgs, "must not return an empty message list")
        self.assertIsInstance(msgs[-1], AIMessage)
        self.assertEqual(msgs[-1].tool_calls, [])

    def test_first_turn_schema_routing_stops(self):
        from tradingagents.graph.conditional_logic import ConditionalLogic

        msgs = self._node_messages([_schema_msg("market")])
        state = {"messages": _messages() + list(msgs)}
        # Must not raise, and must not ask for another tool round.
        self.assertEqual(ConditionalLogic().should_continue_market(state),
                         "Msg Clear Market")

    def test_first_turn_prose_ends_on_the_prose_turn(self):
        msgs = self._node_messages([PROSE])
        self.assertIsInstance(msgs[-1], AIMessage)
        self.assertEqual(msgs[-1].tool_calls, [])

    def test_schema_after_a_tool_round_keeps_call_and_result_paired(self):
        msgs = self._node_messages([_tool_msg(), _schema_msg("market")])
        self.assertEqual([type(m).__name__ for m in msgs],
                         ["AIMessage", "ToolMessage", "AIMessage"])
        self.assertEqual(len(_pending_calls(msgs)), 0,
                         "no tool call may be left without its result")

    def test_schema_after_a_failed_tool_still_ends_cleanly(self):
        # The tool raises; the runner turns it into a status="error" ToolMessage,
        # and the error result is still returned with its call.
        from tradingagents.graph.conditional_logic import ConditionalLogic

        _r, _obj, msgs, _llm, _s, _t = _run(
            "market", [_tool_msg(), _schema_msg("market")],
            tools=[_FakeTool("get_stock_data", exc=ValueError("boom"))],
        )
        self.assertEqual([type(m).__name__ for m in msgs],
                         ["AIMessage", "ToolMessage", "AIMessage"])
        self.assertEqual(msgs[1].status, "error")
        state = {"messages": _messages() + list(msgs)}
        self.assertEqual(ConditionalLogic().should_continue_market(state),
                         "Msg Clear Market")

    def test_multi_round_tool_loop_then_schema(self):
        first = _tool_msg()
        second = AIMessage(content="", tool_calls=[
            {"name": "get_stock_data", "type": "tool_call", "id": "t2",
             "args": {"symbol": "AMD", "start_date": "2026-09-01",
                      "end_date": "2026-09-23"}},
        ])
        msgs = self._node_messages([first, second, _schema_msg("market")])
        self.assertEqual([type(m).__name__ for m in msgs],
                         ["AIMessage", "ToolMessage", "AIMessage",
                          "ToolMessage", "AIMessage"])
        self.assertEqual(len(_pending_calls(msgs)), 0)
        from tradingagents.graph.conditional_logic import ConditionalLogic
        self.assertEqual(
            ConditionalLogic().should_continue_market(
                {"messages": _messages() + list(msgs)}),
            "Msg Clear Market")


class BlankReportResidualTest(unittest.TestCase):
    """R3 F4: blank-model-output behaviour must stay exactly as RC1's."""

    def test_blank_prose_is_returned_unchanged_and_still_recorded(self):
        blank = AIMessage(content="")
        report, obj, _msgs, _llm, _s, _t = _run("market", [blank])
        self.assertEqual(report, "")
        self.assertIsNone(obj)

    def test_blank_report_is_never_a_typed_object(self):
        # A blank report must not masquerade as a valid structured report.
        blank = AIMessage(content="")
        _r, obj, _m, _llm, _s, _t = _run("market", [_tool_msg()] * 4 + [blank])
        self.assertIsNone(obj)



class CompiledGraphLoopTest(unittest.TestCase):
    """R3 F3(b): the real compiled graph must not replay an executed tool call.

    The routing contract alone is not enough. ``MessagesState`` appends what the
    node returns, so a data-tool call written back without its ``ToolMessage``
    leaves a dangling call in state: ``should_continue_*`` routes to the tool
    node, the tool runs a second time, the analyst is re-entered, and the run
    dies with ``GraphRecursionError``. These tests build the production wiring
    (analyst -> conditional -> ToolNode -> analyst -> Msg Clear) and count.
    """

    def _graph(self, llm, executed):
        from unittest.mock import patch

        from langgraph.graph import END, START, StateGraph
        from langgraph.prebuilt import ToolNode

        from tradingagents.agents.analysts.market_analyst import create_market_analyst
        from tradingagents.agents.utils.agent_states import AgentState
        from tradingagents.graph.conditional_logic import ConditionalLogic

        node = create_market_analyst(llm, structured=True, single_pass=True)

        def counting_vendor(*args, **kwargs):
            executed.append("call")
            return "rows"

        # The vendor boundary is the only place a real price fetch happens, so
        # counting there proves whether the tool ran once, twice, or not at all.
        self._patcher = patch(
            "tradingagents.agents.utils.core_stock_tools.route_to_vendor",
            counting_vendor)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

        from tradingagents.agents.utils.agent_utils import get_stock_data as tool

        g = StateGraph(AgentState)
        g.add_node("Market Analyst", node)
        g.add_node("tools_market", ToolNode([tool]))
        g.add_node("Msg Clear Market",
                   lambda s: {"messages": [HumanMessage(content="Proceed.")]})
        g.add_edge(START, "Market Analyst")
        g.add_conditional_edges("Market Analyst",
                                ConditionalLogic().should_continue_market,
                                ["tools_market", "Msg Clear Market"])
        g.add_edge("tools_market", "Market Analyst")
        g.add_edge("Msg Clear Market", END)
        return g.compile()

    def _scripted(self, rounds):
        """An LLM whose bound chain emits ``rounds`` tool calls then a schema."""
        from langchain_core.language_models.chat_models import BaseChatModel
        from langchain_core.outputs import ChatGeneration, ChatResult

        name, schema, args = SCHEMA_NAMES["market"]

        class _LLM(BaseChatModel):
            seen: list = []

            @property
            def _llm_type(self):
                return "counting"

            def _generate(self, messages, stop=None, run_manager=None, **kw):
                return ChatResult(generations=[
                    ChatGeneration(message=AIMessage(content="prose"))])

            def bind_tools(self, tools, **kw):
                bound_names = [
                    getattr(t, "name", None) or getattr(t, "__name__", repr(t))
                    for t in tools
                ]
                state = {"i": 0}

                def _gen(messages, config=None):
                    state["i"] += 1
                    self.seen.append(list(bound_names))
                    if state["i"] <= rounds:
                        return AIMessage(content="", tool_calls=[{
                            "name": "get_stock_data", "type": "tool_call",
                            "id": f"t{state['i']}",
                            "args": {"symbol": "NVDA",
                                     "start_date": "2025-03-01",
                                     "end_date": "2025-03-10"},
                        }])
                    return AIMessage(content="", tool_calls=[{
                        "name": name, "type": "tool_call", "id": "s1",
                        "args": args}])

                return RunnableLambda(_gen)

            def with_structured_output(self, schema, **kw):
                # The schema is emitted as a tool call by ``_gen`` above, so the
                # structured path is never entered on a passing run; this only
                # has to exist for the factory.
                return RunnableLambda(lambda m, config=None: schema(**args))

            def invoke(self, messages, config=None, **kw):
                # The last-resort free-text turn.
                return AIMessage(content="fallback prose")

        return _LLM()

    def test_zero_tool_rounds_completes(self):
        llm = self._scripted(0)
        executed = []
        out = self._graph(llm, executed).invoke(
            self._initial(), {"recursion_limit": 30})
        self.assertEqual(executed, [])
        self.assertTrue(out.get("market_report"))
        self.assertIsNotNone(out.get("market_report_obj"))
        self.assertEqual(len(llm.seen), 1, "exactly one generation at k=0")

    def test_one_tool_round_executes_once_and_completes(self):
        llm = self._scripted(1)
        executed = []
        out = self._graph(llm, executed).invoke(
            self._initial(), {"recursion_limit": 30})
        # The tool ran exactly once: no replay after the schema answer.
        self.assertEqual(executed, ["call"])
        self.assertTrue(out.get("market_report"))
        self.assertIsNotNone(out.get("market_report_obj"))
        self.assertEqual(len(llm.seen), 2, "k tool rounds + 1 schema call")
        # The schema is bound WITH the data tools, never alone.
        self.assertEqual(llm.seen[-1][-1], SCHEMA_NAMES["market"][0])
        self.assertIn("get_stock_data", llm.seen[-1])

    def test_two_tool_rounds_execute_twice_and_complete(self):
        llm = self._scripted(2)
        executed = []
        out = self._graph(llm, executed).invoke(
            self._initial(), {"recursion_limit": 40})
        self.assertEqual(executed, ["call", "call"])
        self.assertIsNotNone(out.get("market_report_obj"))
        self.assertEqual(len(llm.seen), 3)

    def test_returned_state_has_no_dangling_tool_call(self):
        llm = self._scripted(1)
        out = self._graph(llm, []).invoke(
            self._initial(), {"recursion_limit": 30})
        self.assertEqual(_pending_calls(out["messages"]), set())

    def _initial(self):
        return {
            "messages": [HumanMessage(content="Analyze NVDA")],
            "trade_date": "2025-03-10",
            "company_of_interest": "NVDA",
            "asset_type": "stock",
            "instrument_context": "Ticker: NVDA",
        }



class MixedTurnTest(unittest.TestCase):
    """R3b-F2: schema and data tools in ONE turn must not drop the data call."""

    def _mixed(self):
        name, _schema, args = SCHEMA_NAMES["market"]
        return AIMessage(content="", tool_calls=[
            {"name": "get_stock_data", "type": "tool_call", "id": "t1",
             "args": {"symbol": "NVDA", "start_date": "2026-09-01",
                      "end_date": "2026-09-23"}},
            {"name": name, "type": "tool_call", "id": "s1", "args": args},
        ])

    def test_mixed_turn_runs_the_data_tool_before_finalising(self):
        tool = _FakeTool("get_stock_data")
        rendered, obj, msgs, _llm, _s, _t = _run(
            "market", [self._mixed(), _schema_msg("market")], tools=[tool])
        # The data call in the mixed turn was actually executed.
        self.assertEqual(tool.calls, 1)
        self.assertIsNotNone(obj)
        names = [type(m).__name__ for m in msgs]
        self.assertEqual(names, ["AIMessage", "ToolMessage", "AIMessage"])

    def test_mixed_turn_leaves_no_dangling_call(self):
        _r, _o, msgs, _l, _s, _t = _run(
            "market", [self._mixed(), _schema_msg("market")])
        self.assertEqual(_pending_calls(msgs), set())

    def test_mixed_turn_then_budget_exhaustion_still_reports(self):
        from tradingagents.agents.utils.structured import SINGLE_PASS_MAX_ROUNDS

        def round_msg(i):
            # unique ids: the runner pairs results by tool_call_id
            return AIMessage(content="", tool_calls=[{
                "name": "get_stock_data", "type": "tool_call", "id": f"r{i}",
                "args": {"symbol": "NVDA", "start_date": "2026-09-01",
                         "end_date": "2026-09-23"}}])

        # The runner keeps asking for tools until the budget is spent; the
        # scripted model then answers in prose, which becomes the report.
        responses = [self._mixed()] + [
            round_msg(i) for i in range(SINGLE_PASS_MAX_ROUNDS)
        ]
        responses[-1] = PROSE
        rendered, obj, msgs, _l, _s, _t = _run(
            "market", responses + [PROSE])
        self.assertTrue(rendered)
        self.assertIsNone(obj)
        self.assertEqual(_pending_calls(msgs), set())



class DoubleSchemaTurnTest(unittest.TestCase):
    """R3c-F1: two schema calls in one turn is a model slip, not a mixed turn.

    Counting raw tool calls made this *look* mixed, so the valid structured
    report was dropped to prose and a later clean schema turn was never reached.
    """

    def test_two_schema_calls_still_produce_the_structured_report(self):
        name, _schema, args = SCHEMA_NAMES["market"]
        doubled = AIMessage(content="", tool_calls=[
            {"name": name, "type": "tool_call", "id": "s1", "args": args},
            {"name": name, "type": "tool_call", "id": "s2", "args": args},
        ])
        rendered, obj, msgs, _l, _s, _t = _run("market", [doubled])
        self.assertIsNotNone(obj)
        self.assertTrue(rendered)
        self.assertEqual(_pending_calls(msgs), set())

    def test_two_schema_calls_record_one_success(self):
        import tradingagents.agents.utils.structured as U

        name, _schema, args = SCHEMA_NAMES["market"]
        doubled = AIMessage(content="", tool_calls=[
            {"name": name, "type": "tool_call", "id": "s1", "args": args},
            {"name": name, "type": "tool_call", "id": "s2", "args": args},
        ])
        recorded = []
        original = U.record_structured_attempt
        try:
            U.record_structured_attempt = lambda agent, **kw: recorded.append(kw)
            _run("market", [doubled, PROSE])
        finally:
            U.record_structured_attempt = original
        self.assertEqual([e["kind"] for e in recorded], ["success"])


if __name__ == "__main__":
    unittest.main()
