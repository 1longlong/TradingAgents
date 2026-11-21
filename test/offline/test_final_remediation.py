"""Final remediation regressions: R12 fallback, DSML reports, tool rounds.

Every test here is written against the *failure* observed in the V3 batch:

* R12: a failed single-pass schema call was replayed with the schema-carrying
  assistant turn still in the history (dangling ``tool_calls``) and without the
  analyst system prompt -> provider 400.
* R07/R14: tool-call protocol markup (``｜｜DSML｜｜``) was stored as the market
  report.
* Every single-pass run reported ``tool_rounds = 0`` although rounds happened.
"""
from __future__ import annotations

from typing import Literal

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from pydantic import BaseModel

from tradingagents import observability as o
from tradingagents.agents.utils.structured import (
    REPORT_UNAVAILABLE_TEMPLATE,
    _schema_tool_name,
    finalize_analyst_report,
    finalize_single_pass,
    looks_like_protocol_markup,
    run_data_tools,
    sanitize_analyst_text,
)


class _Stance(BaseModel):
    stance: Literal["Bullish", "Bearish", "Neutral"]
    summary: str


def _render(report: _Stance) -> str:
    return report.summary


class _Scripted:
    """Scripted chat model: records every request, returns the next reply."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen: list[list] = []

    def __call__(self, messages, **kwargs):
        if hasattr(messages, "to_messages"):
            messages = messages.to_messages()
        self.seen.append(list(messages))
        if not self.replies:
            raise AssertionError("scripted model ran out of replies")
        return self.replies.pop(0)

    def bind_tools(self, tools, **kwargs):
        from langchain_core.runnables import RunnableLambda

        return RunnableLambda(self)


def _prompt():
    return ChatPromptTemplate.from_messages(
        [("system", "ANALYST SYSTEM PROMPT"), MessagesPlaceholder("messages")]
    )


def _schema_call(args: dict, call_id: str = "schema-1") -> AIMessage:
    return AIMessage(content="", tool_calls=[
        {"name": _schema_tool_name(_Stance), "args": args, "id": call_id,
         "type": "tool_call"}])


def _run(replies, tools=None, run_tools=None):
    llm = _Scripted(replies)
    prompt = _prompt()
    return finalize_single_pass(
        llm=llm, structured_llm=llm, prompt=prompt,
        messages=[HumanMessage(content="JPM")], tools=tools or [],
        schema=_Stance, render=_render, agent_name="market_analyst",
        run_tools=run_tools, state={},
    ), llm


def _pairing_errors(messages) -> list[str]:
    """Every tool_call id that has no ToolMessage right after its turn."""
    errors, pending = [], set()
    for message in messages:
        if pending and getattr(message, "type", None) != "tool":
            errors.extend(sorted(pending))
            pending = set()
        if getattr(message, "tool_calls", None):
            pending = {call.get("id") for call in message.tool_calls}
        if getattr(message, "type", None) == "tool" and getattr(message, "tool_call_id", None) in pending:
            pending.discard(message.tool_call_id)
    errors.extend(sorted(pending))
    return errors


class TestR12Fallback:
    def test_invalid_stance_retry_has_no_dangling_tool_call(self):
        (text, _report, _messages), llm = _run([
            _schema_call({"stance": "Mildly Bearish", "summary": "x"}),
            AIMessage(content="fallback prose report"),
        ])
        assert text == "fallback prose report"
        assert len(llm.seen) == 2, "the failed schema call must trigger exactly one retry"
        retry = llm.seen[1]
        assert _pairing_errors(retry) == [], (
            "the retry replayed an assistant tool_call with no ToolMessage")

    def test_retry_keeps_the_analyst_system_prompt(self):
        (_text, _report, _messages), llm = _run([
            _schema_call({"stance": "Mildly Bearish", "summary": "x"}),
            AIMessage(content="prose"),
        ])
        retry = llm.seen[1]
        assert any(isinstance(m, SystemMessage) for m in retry), (
            "the fallback dropped the system prompt")
        assert "ANALYST SYSTEM PROMPT" in retry[0].content

    def test_a_complete_tool_pairing_is_not_broken(self):
        calls = [{"name": "get_indicators", "args": {"symbol": "JPM"},
                  "id": "call-1", "type": "tool_call"}]

        def run_tools(batch):
            return [ToolMessage(content="indicator data", name="get_indicators",
                                tool_call_id=batch[0]["id"])]

        (text, _report, _messages), llm = _run([
            AIMessage(content="", tool_calls=calls),
            _schema_call({"stance": "Neutral", "summary": "structured ok"}, "s-2"),
        ], run_tools=run_tools)
        assert text == "structured ok"
        # Only one schema turn after the tool round: no retry call.
        assert len(llm.seen) == 2
        for request in llm.seen:
            assert _pairing_errors(request) == []

    def test_a_second_failure_is_reported_not_swallowed(self):
        class _Boom(_Scripted):
            def __call__(self, messages, **kwargs):
                self.seen.append(list(messages))
                if len(self.seen) == 1:
                    return _schema_call({"stance": "Mildly Bearish", "summary": "x"})
                raise RuntimeError("provider down")

        llm = _Boom([])
        with pytest.raises(RuntimeError, match="provider down"):
            finalize_single_pass(
                llm=llm, structured_llm=llm, prompt=_prompt(),
                messages=[HumanMessage(content="JPM")], tools=[],
                schema=_Stance, render=_render, agent_name="market_analyst",
                run_tools=lambda batch: [], state={},
            )

    def test_normal_structured_output_is_unchanged(self):
        (text, _report, _messages), llm = _run([_schema_call({"stance": "Neutral", "summary": "clean report"})])
        assert text == "clean report"
        assert len(llm.seen) == 1


class TestAuditAFollowUps:
    """Findings from independent audit A on the first remediation candidate."""

    def test_a_non_empty_prose_turn_is_sanitized_too(self):
        markup = ('<｜｜DSML｜｜ calls> <｜｜DSML｜｜ invoke name="get_verified_market_snapshot"> '
                  '<｜｜DSML｜｜ parameter name="symbol">XOM</｜｜DSML｜｜ parameter> '
                  '</｜｜DSML｜｜ invoke> </｜｜DSML｜｜ calls>')
        (text, _report, _messages), _llm = _run([AIMessage(content=markup)])
        assert not looks_like_protocol_markup(text)
        assert text.strip()

    def test_structured_llm_none_still_sanitizes_the_two_call_fallback(self):
        markup = TestDsmlSanitizer.R07_LIKE
        text, report = finalize_analyst_report(
            llm=None, structured_llm=None, messages=[HumanMessage(content="AAPL")],
            render=_render, agent_name="market_analyst", free_text_block=markup)
        assert report is None
        assert not looks_like_protocol_markup(text)
        assert "AAPL closed at 336.76" in text

    def test_a_mixed_schema_plus_data_turn_leaves_no_dangling_call(self):
        schema_name = _schema_tool_name(_Stance)
        data_call = {"name": "get_indicators", "args": {"symbol": "JPM"},
                     "id": "d-1", "type": "tool_call"}
        schema_call = {"name": schema_name, "args": {"stance": "Mildly Bearish",
                       "summary": "x"}, "id": "s-1", "type": "tool_call"}

        def run_tools(batch):
            return [ToolMessage(content="data", name=c["name"], tool_call_id=c["id"])
                    for c in batch]

        (text, _report, _messages), llm = _run([
            AIMessage(content="", tool_calls=[data_call, schema_call]),
            _schema_call({"stance": "Neutral", "summary": "final"}, "s-2"),
        ], run_tools=run_tools)
        assert text == "final"
        assert len(llm.seen) == 2
        assert _pairing_errors(llm.seen[1]) == [], (
            "the mixed turn's schema call id was still unresolved on the next request")

    def test_analysis_before_markup_is_kept(self):
        prose = ("XOM trades at 112.40 above its 50-day average with rising volume and a "
                 "constructive MACD; support sits at 108.20 and resistance at 118.00. "
                 "The trend is intact but extended. ")
        mixed = prose + ('<｜｜DSML｜｜ calls> <｜｜DSML｜｜ invoke name="get_prediction_markets"> '
                         '<｜｜DSML｜｜ parameter name="symbol">XOM</｜｜DSML｜｜ parameter> '
                         '</｜｜DSML｜｜ invoke> </｜｜DSML｜｜ calls>')
        text, info = sanitize_analyst_text(mixed, agent_name="market_analyst")
        assert info["markup"] is True
        assert text.strip() == prose.strip()
        assert not looks_like_protocol_markup(text)

    def test_schema_fields_beyond_summary_are_recovered(self):
        markup = ('<｜｜DSML｜｜ calls> <｜｜DSML｜｜ invoke name="final_report"> '
                  '<｜｜DSML｜｜ parameter name="interpretation">MACD crossed above its signal line on 2026-09-21 and RSI is 58, so momentum is constructive but not extended.</｜｜DSML｜｜ parameter> '
                  '<｜｜DSML｜｜ parameter name="risks">A daily close below 321.16 invalidates the setup, and a gap through 333.52 would force a fast reduction.</｜｜DSML｜｜ parameter> '
                  '<｜｜DSML｜｜ parameter name="key_levels">Support sits at 321.16 and 333.52; resistance is 344.50 and 345.08.</｜｜DSML｜｜ parameter> '
                  '</｜｜DSML｜｜ invoke> </｜｜DSML｜｜ calls>')
        text, info = sanitize_analyst_text(markup, agent_name="market_analyst")
        assert info["recovered_chars"] > 0
        assert "MACD" in text and "321.16" in text and "344.50" in text


class TestDsmlSanitizer:
    R07_LIKE = ('<｜｜DSML｜｜ calls> <｜｜DSML｜｜ invoke name="final_report"> '
                '<｜｜DSML｜｜ parameter name="symbol" string="true">AAPL</｜｜DSML｜｜ parameter> '
                '<｜｜DSML｜｜ parameter name="summary" string="true">'
                + "AAPL closed at 336.76 above the 10 EMA and 50 SMA; MACD histogram "
                  "expanded and RSI is 61, so the trend remains constructive with "
                  "support at 321.16 and a stop below 333.52." +
                '</｜｜DSML｜｜ parameter> </｜｜DSML｜｜ invoke> </｜｜DSML｜｜ calls>')
    R14_LIKE = ('<｜｜DSML｜｜ calls> <｜｜DSML｜｜ invoke name="get_verified_market_snapshot"> '
                '<｜｜DSML｜｜ parameter name="symbol" string="true">XOM</｜｜DSML｜｜ parameter> '
                '<｜｜DSML｜｜ parameter name="curr_date" string="true">2026-09-23</｜｜DSML｜｜ parameter> '
                '</｜｜DSML｜｜ invoke> </｜｜DSML｜｜ calls>')

    def test_clean_text_is_untouched(self):
        text, info = sanitize_analyst_text("plain analysis", agent_name="market_analyst")
        assert text == "plain analysis"
        assert info["markup"] is False

    def test_r07_markup_is_recovered_without_markers(self):
        text, info = sanitize_analyst_text(self.R07_LIKE, agent_name="market_analyst")
        assert not looks_like_protocol_markup(text)
        assert info["markup"] is True and info["recovered_chars"] > 0
        assert "AAPL closed at 336.76" in text
        assert "SMA" in text and "MACD" in text and "RSI" in text

    def test_r14_markup_becomes_an_explicit_unavailable_report(self):
        text, info = sanitize_analyst_text(self.R14_LIKE, agent_name="market_analyst")
        assert not looks_like_protocol_markup(text)
        assert text.strip(), "must never silently become an empty report"
        assert text == REPORT_UNAVAILABLE_TEMPLATE.format(agent="market_analyst")
        assert info["recovered_chars"] == 0

    def test_markup_in_the_single_pass_fallback_never_reaches_the_report(self):
        (text, _report, _messages), _llm = _run([
            _schema_call({"stance": "Mildly Bearish", "summary": "x"}),
            AIMessage(content=self.R07_LIKE),
        ])
        assert not looks_like_protocol_markup(text)
        assert "SMA" in text


class TestMarkupTelemetry:
    def test_one_markup_fallback_is_one_attempt_with_its_own_counter(self):
        """Audit A/B: the markup event must be recorded, but not as a second
        structured attempt (attempts == success + failure + unsupported)."""
        markup = TestDsmlSanitizer.R14_LIKE
        collector = o.RunMetricsCollector()
        collector.begin_run(ticker="XOM", trade_date="2026-09-23")
        llm = _Scripted([
            _schema_call({"stance": "Mildly Bearish", "summary": "x"}),
            AIMessage(content=markup),
        ])
        with o.run_scoped(collector), o.agent_scoped("market_analyst"):
            text, _report, _messages = finalize_single_pass(
                llm=llm, structured_llm=llm, prompt=_prompt(),
                messages=[HumanMessage(content="XOM")], tools=[], schema=_Stance,
                render=_render, agent_name="market_analyst",
                run_tools=lambda batch: [], state={},
            )
        collector.finish_run("completed")
        payload = collector.build_telemetry()
        agg = payload["agents"]["market_analyst"]
        kinds = [e["kind"] for e in payload["structured_events"]]
        assert "markup_sanitized" in kinds
        assert agg["structured_attempts"] == 1
        assert agg["structured_markup_sanitized"] == 1
        assert agg["structured_attempts"] == (
            agg["structured_successes"] + agg["structured_failures"]
            + agg["structured_unsupported"])
        assert payload["run_totals"]["structured_markup_sanitized"] == 1
        assert not looks_like_protocol_markup(text)


class TestToolRounds:
    class _Tool:
        name = "t"

        def invoke(self, args):
            return "ok"

    def _collector(self):
        collector = o.RunMetricsCollector()
        collector.begin_run(ticker="JPM", trade_date="2026-09-23")
        return collector

    def test_one_model_turn_with_two_calls_is_one_round(self):
        collector = self._collector()
        runner = run_data_tools([self._Tool()], state={})
        calls = [{"name": "t", "args": {}, "id": "1"},
                 {"name": "t", "args": {}, "id": "2"}]
        with o.run_scoped(collector), o.agent_scoped("market_analyst"):
            runner(calls)
        assert len(collector.tool_rounds) == 1
        assert collector.tool_rounds[0].number_of_tool_calls == 2
        assert collector.tool_rounds[0].agent_id == "market_analyst"

    def test_two_rounds_are_two_rounds(self):
        collector = self._collector()
        runner = run_data_tools([self._Tool()], state={})
        with o.run_scoped(collector), o.agent_scoped("market_analyst"):
            runner([{"name": "t", "args": {}, "id": "1"}])
            runner([{"name": "t", "args": {}, "id": "2"},
                    {"name": "t", "args": {}, "id": "3"}])
        assert [r.number_of_tool_calls for r in collector.tool_rounds] == [1, 2]

    def test_no_tool_call_is_no_round(self):
        collector = self._collector()
        runner = run_data_tools([self._Tool()], state={})
        with o.run_scoped(collector), o.agent_scoped("market_analyst"):
            runner([])
        assert collector.tool_rounds == []

    def test_rounds_reach_the_telemetry_payload(self):
        collector = self._collector()
        runner = run_data_tools([self._Tool()], state={})
        with o.run_scoped(collector), o.agent_scoped("market_analyst"):
            runner([{"name": "t", "args": {}, "id": "1"}])
        collector.finish_run("completed")
        payload = collector.build_telemetry()
        assert payload["run_totals"]["tool_rounds"] == 1
        assert payload["agents"]["market_analyst"]["tool_rounds"] == 1

    def test_a_failing_tool_still_counts_as_a_round(self):
        class _Broken(self._Tool):
            def invoke(self, args):
                raise RuntimeError("tool down")

        collector = self._collector()
        runner = run_data_tools([_Broken()], state={})
        with o.run_scoped(collector), o.agent_scoped("market_analyst"):
            result = runner([{"name": "t", "args": {}, "id": "1"}])
        assert result[0].status == "error"
        assert len(collector.tool_rounds) == 1
        assert collector.tool_rounds[0].number_of_tool_calls == 1
        assert collector.tool_rounds[0].status == "error", (
            "a round whose every call failed should not be recorded as ok")
