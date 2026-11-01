"""Credential-free Phase 1 tests for :mod:`tradingagents.observability`.

These tests exercise the observability infrastructure in isolation: agent scope,
LLM/tool callback events, token usage extraction, prompt diagnostics, tool
execution, and the run-scoped collector. They never touch a network, an API key,
or any trading/business behavior.
"""

import concurrent.futures
import json
import time
import uuid
from typing import TypedDict

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from tradingagents import observability as o


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
class _UsageModel(FakeListChatModel):
    """A fake chat model that stamps provider-reported usage on its response."""

    def __init__(self, responses, usage=None):
        super().__init__(responses=responses)
        self._usage = usage

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        result = super()._generate(messages, stop, run_manager, **kwargs)
        message = result.generations[0].message
        if self._usage is not None:
            message.usage_metadata = self._usage.get("usage_metadata")
            if self._usage.get("response_metadata") is not None:
                message.response_metadata = self._usage["response_metadata"]
        return result


def _invoke_llm(responses, callbacks, usage=None, prompt="hello"):
    """Invoke a fake chat model with our callbacks, return the handler/collector."""
    model = _UsageModel(responses=responses, usage=usage)
    model.invoke(prompt, config={"callbacks": callbacks})
    return model


# ---------------------------------------------------------------------------
# Agent scope
# ---------------------------------------------------------------------------
class TestAgentScope:
    def test_current_agent_id_default_none(self):
        assert o.get_current_agent_id() is None

    def test_scope_sets_and_restores(self):
        with o.agent_scoped(o.AGENT_MARKET_ANALYST):
            assert o.get_current_agent_id() == o.AGENT_MARKET_ANALYST
        assert o.get_current_agent_id() is None

    def test_nested_scope_restores_outer(self):
        with o.agent_scoped(o.AGENT_MARKET_ANALYST):
            with o.agent_scoped(o.AGENT_TRADER):
                assert o.get_current_agent_id() == o.AGENT_TRADER
            assert o.get_current_agent_id() == o.AGENT_MARKET_ANALYST
        assert o.get_current_agent_id() is None

    def test_exception_restores_scope(self):
        with pytest.raises(RuntimeError), o.agent_scoped(o.AGENT_BULL_RESEARCHER):
            assert o.get_current_agent_id() == o.AGENT_BULL_RESEARCHER
            raise RuntimeError("boom")
        assert o.get_current_agent_id() is None

    def test_none_is_noop(self):
        with o.agent_scoped(o.AGENT_NEWS_ANALYST), o.agent_scoped(None):
            assert o.get_current_agent_id() == o.AGENT_NEWS_ANALYST

    def test_concurrent_isolation(self):
        """Concurrent scopes in different threads do not leak agent ids."""
        results = {}

        def worker(agent_id):
            with o.agent_scoped(agent_id):
                # Give the other thread a chance to set its own scope.
                time.sleep(0.05)
                inner = o.get_current_agent_id()
            results[agent_id] = (inner, o.get_current_agent_id())

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(worker, [o.AGENT_MARKET_ANALYST, o.AGENT_TRADER,
                                 o.AGENT_NEWS_ANALYST, o.AGENT_UNATTRIBUTED]))

        for agent_id, (inner, outer) in results.items():
            assert inner == agent_id, results
            assert outer is None, results


class TestStableAgentIds:
    def test_all_ids_defined(self):
        assert o.AGENT_MARKET_ANALYST == "market_analyst"
        assert o.AGENT_SENTIMENT_ANALYST == "sentiment_analyst"
        assert o.AGENT_NEWS_ANALYST == "news_analyst"
        assert o.AGENT_FUNDAMENTALS_ANALYST == "fundamentals_analyst"
        assert o.AGENT_BULL_RESEARCHER == "bull_researcher"
        assert o.AGENT_BEAR_RESEARCHER == "bear_researcher"
        assert o.AGENT_RESEARCH_MANAGER == "research_manager"
        assert o.AGENT_TRADER == "trader"
        assert o.AGENT_AGGRESSIVE_ANALYST == "aggressive_analyst"
        assert o.AGENT_CONSERVATIVE_ANALYST == "conservative_analyst"
        assert o.AGENT_NEUTRAL_ANALYST == "neutral_analyst"
        assert o.AGENT_PORTFOLIO_MANAGER == "portfolio_manager"
        assert o.AGENT_UNATTRIBUTED == "unattributed"

    def test_all_in_collection(self):
        assert len(o.ALL_AGENT_IDS) == 13
        assert o.AGENT_UNATTRIBUTED in o.ALL_AGENT_IDS


# ---------------------------------------------------------------------------
# Determinism helpers
# ---------------------------------------------------------------------------
class TestDeterminism:
    def test_utf8_byte_size(self):
        assert o.utf8_byte_size("abc") == 3
        assert o.utf8_byte_size("café") == len("café".encode())
        assert o.utf8_byte_size(b"xy") == 2

    def test_canonical_serialize_ignores_key_order(self):
        a = {"a": 1, "b": {"x": 2, "y": 3}}
        b = {"b": {"y": 3, "x": 2}, "a": 1}
        assert o.canonical_serialize(a) == o.canonical_serialize(b)

    def test_sha256_deterministic(self):
        assert o.sha256_fingerprint({"k": 1}) == o.sha256_fingerprint({"k": 1})
        assert o.sha256_fingerprint({"k": 1}) != o.sha256_fingerprint({"k": 2})

    def test_tool_fingerprint_ignores_key_order(self):
        f1 = o.fingerprint_tool_arguments("agent", "tool", {"b": 2, "a": 1})
        f2 = o.fingerprint_tool_arguments("agent", "tool", {"a": 1, "b": 2})
        assert f1 == f2

    def test_tool_fingerprint_differs_for_diff_args(self):
        f1 = o.fingerprint_tool_arguments("agent", "tool", {"a": 1})
        f2 = o.fingerprint_tool_arguments("agent", "tool", {"a": 2})
        assert f1 != f2

    def test_tool_fingerprint_differs_per_agent(self):
        f1 = o.fingerprint_tool_arguments("agent1", "tool", {"a": 1})
        f2 = o.fingerprint_tool_arguments("agent2", "tool", {"a": 1})
        assert f1 != f2


# ---------------------------------------------------------------------------
# LLM callbacks
# ---------------------------------------------------------------------------
class TestLLMCallbacks:
    def test_start_end_single_event(self):
        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        with o.observe_run(collector, o.AGENT_MARKET_ANALYST):
            _invoke_llm(["hi"], [handler])
        assert len(collector.llm_calls) == 1
        event = collector.llm_calls[0]
        assert event.agent_id == o.AGENT_MARKET_ANALYST
        assert event.success is True
        assert event.error_class is None
        assert event.duration_s is not None

    def test_duplicate_start_same_runid_no_double_count(self):
        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        rid = str(uuid.uuid4())
        with o.observe_run(collector, o.AGENT_TRADER):
            handler.on_chat_model_start(
                {}, [[HumanMessage("hi")]], run_id=rid, parent_run_id=None
            )
            # Duplicate delivery of the same start hook.
            handler.on_chat_model_start(
                {}, [[HumanMessage("hi")]], run_id=rid, parent_run_id=None
            )
            handler.on_llm_start({}, ["hi"], run_id=rid, parent_run_id=None)
            handler.on_llm_end(_llm_result(AIMessage(content="ok")), run_id=rid)
        assert len(collector.llm_calls) == 1

    def test_duplicate_end_delivery_no_double_count(self):
        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        rid = str(uuid.uuid4())
        with o.observe_run(collector, o.AGENT_NEWS_ANALYST):
            handler.on_chat_model_start({}, [[HumanMessage("hi")]], run_id=rid)
            handler.on_llm_end(_llm_result(AIMessage(content="ok")), run_id=rid)
            # Duplicate end delivery.
            handler.on_llm_end(_llm_result(AIMessage(content="ok")), run_id=rid)
        assert len(collector.llm_calls) == 1

    def test_end_uses_frozen_agent_attribution(self):
        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        rid = str(uuid.uuid4())
        with o.observe_run(collector, o.AGENT_BULL_RESEARCHER):
            handler.on_chat_model_start({}, [[HumanMessage("hi")]], run_id=rid)
            # The scope changes before end; attribution must stay frozen.
            with o.agent_scoped(o.AGENT_BEAR_RESEARCHER):
                handler.on_llm_end(_llm_result(AIMessage(content="ok")), run_id=rid)
        assert collector.llm_calls[0].agent_id == o.AGENT_BULL_RESEARCHER

    def test_missing_start_is_safe(self):
        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        rid = str(uuid.uuid4())
        with o.observe_run(collector):
            # End / error with no preceding start: must not crash or record.
            handler.on_llm_end(_llm_result(AIMessage(content="ok")), run_id=rid)
            handler.on_llm_error(RuntimeError("boom"), run_id=rid)
        assert len(collector.llm_calls) == 0

    def test_unattributed_when_no_scope(self):
        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        rid = str(uuid.uuid4())
        with o.observe_run(collector):
            handler.on_chat_model_start({}, [[HumanMessage("hi")]], run_id=rid)
            handler.on_llm_end(_llm_result(AIMessage(content="ok")), run_id=rid)
        assert collector.llm_calls[0].agent_id == o.AGENT_UNATTRIBUTED

    def test_error_records_sanitized_class(self):
        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        rid = str(uuid.uuid4())
        with o.observe_run(collector, o.AGENT_PORTFOLIO_MANAGER):
            handler.on_chat_model_start({}, [[HumanMessage("hi")]], run_id=rid)
            handler.on_llm_error(ValueError("bad"), run_id=rid)
        event = collector.llm_calls[0]
        assert event.success is False
        assert event.error_class == "ValueError"
        assert collector.llm_error_count == 1
        assert collector.llm_success_count == 0

    def test_model_attribution(self):
        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        rid = str(uuid.uuid4())
        with o.observe_run(collector):
            handler.on_chat_model_start(
                {"model": "gpt-test"}, [[HumanMessage("hi")]], run_id=rid
            )
            handler.on_llm_end(_llm_result(AIMessage(content="ok")), run_id=rid)
        assert collector.llm_calls[0].model == "gpt-test"


# ---------------------------------------------------------------------------
# Token usage
# ---------------------------------------------------------------------------
class TestTokenUsage:
    def test_normal_usage_extracted(self):
        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        usage = {
            "usage_metadata": {"input_tokens": 9, "output_tokens": 4, "total_tokens": 13},
        }
        with o.observe_run(collector, o.AGENT_TRADER):
            _invoke_llm(["x"], [handler], usage=usage)
        event = collector.llm_calls[0]
        assert event.reported_input_tokens == 9
        assert event.reported_output_tokens == 4
        assert event.usage_source == "provider"
        assert event.usage_complete is True

    def test_missing_usage_is_unknown_not_zero(self):
        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        with o.observe_run(collector, o.AGENT_TRADER):
            _invoke_llm(["x"], [handler])  # no usage metadata
        event = collector.llm_calls[0]
        assert event.reported_input_tokens is None
        assert event.reported_output_tokens is None
        assert event.usage_source is None
        assert event.usage_complete is False
        # Completeness stays explicit: partial, not complete.
        assert collector.usage_complete is False

    def test_missing_usage_marks_without_usage(self):
        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        with o.observe_run(collector, o.AGENT_TRADER):
            _invoke_llm(["x"], [handler])
        assert collector.llm_calls_without_provider_usage == 1
        assert collector.llm_calls_with_provider_usage == 0

    def test_reasoning_extraction(self):
        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        usage = {
            "usage_metadata": {
                "input_tokens": 9,
                "output_tokens": 4,
                "total_tokens": 13,
                "output_token_details": {"reasoning": 2},
            }
        }
        with o.observe_run(collector, o.AGENT_TRADER):
            _invoke_llm(["x"], [handler], usage=usage)
        event = collector.llm_calls[0]
        assert event.reported_reasoning_tokens == 2
        # Reasoning is informational; logical totals do NOT include it.
        assert event.reported_output_tokens == 4
        assert collector.reported_output_tokens_sum == 4

    def test_cached_input_extraction(self):
        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        usage = {
            "usage_metadata": {
                "input_tokens": 9,
                "output_tokens": 4,
                "total_tokens": 13,
                "input_token_details": {"cache_read": 3, "cache_creation": 2},
            }
        }
        with o.observe_run(collector, o.AGENT_TRADER):
            _invoke_llm(["x"], [handler], usage=usage)
        event = collector.llm_calls[0]
        assert event.reported_cached_input_tokens == 5
        # Cached input is a detail of input_tokens; logical totals do NOT add it.
        assert event.reported_input_tokens == 9
        assert collector.reported_input_tokens_sum == 9

    def test_response_metadata_fallback(self):
        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        usage = {
            "response_metadata": {
                "token_usage": {"prompt_tokens": 6, "completion_tokens": 2, "total_tokens": 8}
            }
        }
        with o.observe_run(collector, o.AGENT_TRADER):
            _invoke_llm(["x"], [handler], usage=usage)
        event = collector.llm_calls[0]
        assert event.reported_input_tokens == 6
        assert event.reported_output_tokens == 2

    def test_no_double_add_of_reasoning_or_cached(self):
        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        usage = {
            "usage_metadata": {
                "input_tokens": 10,
                "output_tokens": 6,
                "total_tokens": 16,
                "input_token_details": {"cache_read": 4},
                "output_token_details": {"reasoning": 2},
            }
        }
        with o.observe_run(collector, o.AGENT_TRADER):
            _invoke_llm(["x"], [handler], usage=usage)
        assert collector.reported_input_tokens_sum == 10
        assert collector.reported_output_tokens_sum == 6
        assert collector.reported_reasoning_tokens_sum == 2
        assert collector.reported_cached_input_tokens_sum == 4

    def test_partial_usage_keeps_known_side_never_zero(self):
        # Known side preserved; missing side stays None (never invented as 0);
        # completeness is False so coverage is explicit, not conflated.
        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        usage = {
            "usage_metadata": {
                "input_tokens": 5,
                "output_tokens": None,
                "total_tokens": 5,
            }
        }
        with o.observe_run(collector, o.AGENT_TRADER):
            _invoke_llm(["x"], [handler], usage=usage)
        event = collector.llm_calls[0]
        assert event.reported_input_tokens == 5
        assert event.reported_output_tokens is None
        assert event.usage_complete is False
        assert collector.reported_input_tokens_sum == 5
        # The run-level coverage is not claimed complete.
        assert collector.usage_complete is False


# ---------------------------------------------------------------------------
# Prompt diagnostics
# ---------------------------------------------------------------------------
class TestPromptDiagnostics:
    def test_prompt_byte_size_and_counts(self):
        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        rid = str(uuid.uuid4())
        with o.observe_run(collector, o.AGENT_MARKET_ANALYST):
            handler.on_chat_model_start(
                {},
                [[HumanMessage("hello"), ToolMessage(content="tool out", tool_call_id="call1")]],
                run_id=rid,
            )
            handler.on_llm_end(_llm_result(AIMessage(content="ok")), run_id=rid)
        event = collector.llm_calls[0]
        assert event.prompt_message_count == 1
        assert event.prompt_utf8_bytes == len(b"hello")
        assert event.tool_message_count == 1
        assert event.tool_message_utf8_bytes == len(b"tool out")

    def test_no_raw_content_persisted(self):
        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        rid = str(uuid.uuid4())
        with o.observe_run(collector, o.AGENT_MARKET_ANALYST):
            handler.on_chat_model_start(
                {}, [[HumanMessage("secret-prompt-content")]], run_id=rid
            )
            handler.on_llm_end(_llm_result(AIMessage(content="secret-response")), run_id=rid)
        event = collector.llm_calls[0]
        # No promissory strings leak into the recorded event.
        blob = json.dumps(vars(event), default=repr)
        assert "secret-prompt-content" not in blob
        assert "secret-response" not in blob


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------
class TestToolExecution:
    def test_one_tool_one_event(self):
        from langchain_core.tools import tool

        @tool
        def add(a: int, b: int) -> int:
            """Add two integers."""
            return a + b

        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        with o.observe_run(collector, o.AGENT_BULL_RESEARCHER):
            add.invoke({"a": 1, "b": 2}, config={"callbacks": [handler]})
        assert len(collector.tool_calls) == 1
        event = collector.tool_calls[0]
        assert event.tool_name == "add"
        assert event.success is True
        assert event.error_type is None
        assert event.agent_id == o.AGENT_BULL_RESEARCHER

    def test_tool_failure_recorded(self):
        from langchain_core.tools import tool

        @tool
        def bad() -> int:
            """Always raise."""
            raise ValueError("nope")

        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        with o.observe_run(collector, o.AGENT_NEWS_ANALYST), pytest.raises(ValueError):
            bad.invoke({}, config={"callbacks": [handler]})
        event = collector.tool_calls[0]
        assert event.success is False
        assert event.error_type == "ValueError"

    def test_output_size_and_hash_recorded(self):
        from langchain_core.tools import tool

        @tool
        def echo(text: str) -> str:
            """Echo back the input text."""
            return text

        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        with o.observe_run(collector, o.AGENT_TRADER):
            echo.invoke({"text": "hello world"}, config={"callbacks": [handler]})
        event = collector.tool_calls[0]
        assert event.result_utf8_bytes is not None
        assert event.result_sha256 is not None
        assert event.result_utf8_bytes == len(b"hello world")

    def test_raw_result_not_persisted(self):
        from langchain_core.tools import tool

        @tool
        def echo(text: str) -> str:
            """Echo back the input text."""
            return text

        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        with o.observe_run(collector, o.AGENT_TRADER):
            echo.invoke({"text": "TOP-SECRET-TOOL-OUTPUT"}, config={"callbacks": [handler]})
        event = collector.tool_calls[0]
        blob = json.dumps(vars(event), default=repr)
        assert "TOP-SECRET-TOOL-OUTPUT" not in blob
        assert event.result_utf8_bytes == len(b"TOP-SECRET-TOOL-OUTPUT")

    def test_duplicate_count_increments_but_not_blocked(self):
        from langchain_core.tools import tool

        @tool
        def add(a: int, b: int) -> int:
            """Add two integers."""
            return a + b

        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        with o.observe_run(collector, o.AGENT_MARKET_ANALYST):
            add.invoke({"a": 1, "b": 2}, config={"callbacks": [handler]})
            # Same agent, tool, args — duplicate execution, not blocked.
            add.invoke({"a": 1, "b": 2}, config={"callbacks": [handler]})
        assert len(collector.tool_calls) == 2
        assert collector.duplicate_tool_call_count == 1
        assert collector.tool_calls[1].duplicate_count == 1
        # Both executions actually ran (each produced a result).
        assert all(ev.success for ev in collector.tool_calls)


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------
class TestCollector:
    def test_unique_run_ids(self):
        ids = {o.RunMetricsCollector().telemetry_run_id for _ in range(50)}
        assert len(ids) == 50

    def test_sequential_runs_do_not_leak(self):
        c1 = o.RunMetricsCollector()
        c2 = o.RunMetricsCollector()
        h1 = o.ObservabilityCallbackHandler(collector=c1)
        h2 = o.ObservabilityCallbackHandler(collector=c2)
        with o.observe_run(c1, o.AGENT_MARKET_ANALYST):
            _invoke_llm(["a"], [h1])
        # Second collector starts untouched; even same-handler usage is run-local.
        assert c2.llm_calls_count == 0
        with o.observe_run(c2, o.AGENT_TRADER):
            _invoke_llm(["b"], [h2])
        assert c1.llm_calls_count == 1
        assert c2.llm_calls_count == 1
        assert c1.telemetry_run_id != c2.telemetry_run_id
        assert c1.llm_calls[0].telemetry_run_id == c1.telemetry_run_id
        assert c2.llm_calls[0].telemetry_run_id == c2.telemetry_run_id

    def test_two_collector_isolation_concurrent(self):
        c1 = o.RunMetricsCollector()
        c2 = o.RunMetricsCollector()

        def run_llm(collector, agent_id):
            handler = o.ObservabilityCallbackHandler(collector=collector)
            with o.observe_run(collector, agent_id):
                _invoke_llm(["x"], [handler])
            return collector.llm_calls_count

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            f1 = ex.submit(run_llm, c1, o.AGENT_MARKET_ANALYST)
            f2 = ex.submit(run_llm, c2, o.AGENT_TRADER)
            assert f1.result() == 1
            assert f2.result() == 1
        assert c1.llm_calls[0].agent_id == o.AGENT_MARKET_ANALYST
        assert c2.llm_calls[0].agent_id == o.AGENT_TRADER
        assert c1.telemetry_run_id != c2.telemetry_run_id

    def test_finalize_is_idempotent(self):
        c = o.RunMetricsCollector()
        c.finalize()
        c.finalize()
        assert c.is_finalized() is True

    def test_record_after_finalize_is_noop(self):
        c = o.RunMetricsCollector()
        c.finalize()
        seq = c.record_llm_call(o.LLMCallEvent(
            telemetry_run_id=c.telemetry_run_id, callback_run_id="r",
            agent_id=o.AGENT_TRADER, global_sequence=0, agent_sequence=0,
        ))
        assert seq == -1
        assert c.llm_calls_count == 0

    def test_global_sequence_monotonic(self):
        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        with o.observe_run(collector, o.AGENT_TRADER):
            _invoke_llm(["x"], [handler])
            _invoke_llm(["y"], [handler])
            from langchain_core.tools import tool

            @tool
            def t() -> int:
                """Return one."""
                return 1
            t.invoke({}, config={"callbacks": [handler]})
        seqs = [e.global_sequence for e in collector.llm_calls + collector.tool_calls]
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == len(seqs)

    def test_agent_local_sequence(self):
        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        with o.observe_run(collector, o.AGENT_TRADER):
            _invoke_llm(["x"], [handler])
            _invoke_llm(["y"], [handler])
        assert [e.agent_sequence for e in collector.llm_calls] == [0, 1]

    def test_serialize_metrics_deterministic(self):
        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        with o.observe_run(collector, o.AGENT_TRADER):
            _invoke_llm(["x"], [handler])
        assert o.canonical_serialize(collector.snapshot()) == collector.serialize_metrics()


def _llm_result(message):
    """Build an ``LLMResult`` around ``message`` for on_llm_end tests."""
    return LLMResult(generations=[[ChatGeneration(message=message)]], llm_output=None)


# ---------------------------------------------------------------------------
# Phase 2: agent node / tool-name wiring
# ---------------------------------------------------------------------------
class TestNodeAgentWiring:
    def test_node_to_agent_maps_display_names(self):
        assert o.NODE_TO_AGENT["Market Analyst"] == o.AGENT_MARKET_ANALYST
        assert o.NODE_TO_AGENT["Sentiment Analyst"] == o.AGENT_SENTIMENT_ANALYST
        assert o.NODE_TO_AGENT["Portfolio Manager"] == o.AGENT_PORTFOLIO_MANAGER

    def test_agent_id_for_node_known_and_unknown(self):
        assert o.agent_id_for_node("Trader") == o.AGENT_TRADER
        assert o.agent_id_for_node("No Such Node") is None

    def test_every_agent_display_name_maps_to_stable_id(self):
        # Every business node name maps to an id in ALL_AGENT_IDS (or unattributed).
        for agent_id in o.NODE_TO_AGENT.values():
            assert agent_id in o.ALL_AGENT_IDS

    def test_analyst_key_to_agent(self):
        assert o.ANALYST_KEY_TO_AGENT["market"] == o.AGENT_MARKET_ANALYST
        assert o.ANALYST_KEY_TO_AGENT["social"] == o.AGENT_SENTIMENT_ANALYST
        assert o.ANALYST_KEY_TO_AGENT["news"] == o.AGENT_NEWS_ANALYST
        assert o.ANALYST_KEY_TO_AGENT["fundamentals"] == o.AGENT_FUNDAMENTALS_ANALYST

    def test_analyst_agent_id_for_key_known_and_fallback(self):
        assert o.analyst_agent_id_for_key("social") == o.AGENT_SENTIMENT_ANALYST
        # Unknown wire key falls back to the key itself (identity, never None).
        assert o.analyst_agent_id_for_key("mystery") == "mystery"


class TestAttribAgentNode:
    def test_node_scopes_and_records_event(self):
        collector = o.RunMetricsCollector()

        def node(state):
            # Inside the wrapper the scope is set to the agent id.
            assert o.get_current_agent_id() == o.AGENT_NEWS_ANALYST
            return {"handled": True}

        wrapped = o.attrib_agent_node(o.AGENT_NEWS_ANALYST, node)
        with o.observe_run(collector):
            result = wrapped({"messages": [], "report": "x"})

        assert result == {"handled": True}
        assert o.get_current_agent_id() is None  # restored after scope
        assert len(collector.node_events) == 1
        ev = collector.node_events[0]
        assert ev.agent_id == o.AGENT_NEWS_ANALYST
        assert ev.status == "ok"
        assert ev.wall_time_ms >= 0

    def test_node_failure_records_error_and_reraises(self):
        collector = o.RunMetricsCollector()

        def bad(state):
            raise ValueError("node boom")

        wrapped = o.attrib_agent_node(o.AGENT_TRADER, bad)
        with o.observe_run(collector), pytest.raises(ValueError):
            wrapped({"messages": []})
        assert collector.node_events[0].status == "error"
        assert collector.node_events[0].error_type == "ValueError"

    def test_node_context_size_measured(self):
        collector = o.RunMetricsCollector()

        def node(state):
            return {}

        state = {
            "company_of_interest": "AAPL",
            "messages": [HumanMessage(content="hello")],
            "market_report": "the market report body",
        }
        wrapped = o.attrib_agent_node(o.AGENT_MARKET_ANALYST, node)
        with o.observe_run(collector):
            wrapped(state)
        ev = collector.node_events[0]
        # context_bytes only holds whitelisted field sizes (counts/sizes, no text).
        assert "market_report" in ev.context_bytes
        for key, value in ev.context_bytes.items():
            assert isinstance(value, int)

    def test_wraps_functools_partial_and_executes(self):
        """Regression: ``attrib_agent_node`` must wrap a ``functools.partial``.

        The real Trader is ``functools.partial(trader_node, name="Trader")``,
        which has no ``__name__``. It must execute and return exactly the
        original result, recording node telemetry, without mutating the partial.
        """
        import functools

        collector = o.RunMetricsCollector()

        def trader_node(state, name="Trader"):
            assert name == "Trader"
            return {"decision": "buy", "sender": name}

        partial = functools.partial(trader_node, name="Trader")
        wrapped = o.attrib_agent_node(o.AGENT_TRADER, partial)
        with o.observe_run(collector):
            result = wrapped({"company_of_interest": "NVDA"})

        assert result == {"decision": "buy", "sender": "Trader"}
        # The underlying partial is never mutated.
        assert not hasattr(partial, "__name__")
        assert isinstance(partial, functools.partial)
        assert len(collector.node_events) == 1
        ev = collector.node_events[0]
        assert ev.agent_id == o.AGENT_TRADER
        assert ev.status == "ok"
        assert ev.wall_time_ms >= 0

    def test_partial_records_explicit_stable_node_name(self):
        """When an explicit stable node name is supplied it is used verbatim.

        The graph/business name (``"Trader"``) must win over the callable's
        generic class name (``"partial"``) or its ``func.__name__``.
        """
        import functools

        collector = o.RunMetricsCollector()

        def trader_node(state):
            return {"decision": "hold"}

        partial = functools.partial(trader_node)
        wrapped = o.attrib_agent_node(o.AGENT_TRADER, partial, node_name="Trader")
        with o.observe_run(collector):
            wrapped({"company_of_interest": "NVDA"})

        assert collector.node_events[0].node == "Trader"

    def test_partial_failure_records_error_and_reraises(self):
        """A failing partial records a failed node event and re-raises the same
        exception (not a wrapper-created one)."""
        import functools

        collector = o.RunMetricsCollector()

        def bad(state):
            raise ValueError("trader boom")

        partial = functools.partial(bad)
        wrapped = o.attrib_agent_node(o.AGENT_TRADER, partial)
        with o.observe_run(collector), pytest.raises(ValueError, match="trader boom"):
            wrapped({"company_of_interest": "NVDA"})

        assert collector.node_events[0].status == "error"
        assert collector.node_events[0].error_type == "ValueError"
        assert o.get_current_agent_id() is None  # scope restored after failure

    def test_ordinary_function_unchanged(self):
        """An ordinary function node behaves exactly as before."""

        def node(state):
            return {"ok": True}

        wrapped = o.attrib_agent_node(o.AGENT_MARKET_ANALYST, node)
        assert wrapped.__name__ == "node"  # function identity preserved
        result = wrapped({"company_of_interest": "NVDA"})
        assert result == {"ok": True}


class TestAttribToolRound:
    def test_one_invocation_records_one_round(self):
        from langchain_core.tools import tool

        @tool
        def add(a: int, b: int) -> int:
            """Add two integers."""
            return a + b

        collector = o.RunMetricsCollector()
        tool_node = lambda state: {"messages": state.get("messages", [])}
        wrapped = o.attrib_tool_round(o.AGENT_MARKET_ANALYST, tool_node)

        ai = AIMessage(content="", tool_calls=[
            {"name": "add", "args": {"a": 1, "b": 2}, "id": "c1", "type": "tool_call"},
            {"name": "add", "args": {"a": 3, "b": 4}, "id": "c2", "type": "tool_call"},
        ])
        with o.observe_run(collector):
            wrapped({"messages": [ai]})
        assert len(collector.tool_rounds) == 1
        assert collector.tool_rounds[0].number_of_tool_calls == 2
        assert collector.tool_rounds[0].agent_id == o.AGENT_MARKET_ANALYST
        assert collector.tool_rounds[0].status == "ok"

    def test_real_toolnode_wraps_registers_and_executes(self):
        """Regression: a REAL ``langgraph.prebuilt.ToolNode`` must be wrappable,
        registrable in a StateGraph, compiled, and executed correctly.

        Previously ``attrib_tool_round`` set ``__wrapped__`` to the ToolNode
        *instance*, which made LangGraph's ``inspect.signature(follow_wrapped=
        True)`` descend into the ToolNode and raise ``TypeError: descriptor
        '__call__' for 'type' objects doesn't apply to a 'ToolNode' object``
        during ``StateGraph.add_node``; and because a ToolNode is a Runnable it
        was not directly callable. That broke real end-to-end CLI runs before
        graph compilation.
        """
        from langgraph.graph import END, StateGraph
        from langgraph.prebuilt import ToolNode
        from langchain_core.tools import tool

        @tool
        def increment(a: int) -> int:
            """Return a + 1."""
            return a + 1

        real_tool_node = ToolNode([increment])
        # 1. A real project-style ToolNode can be wrapped without triggering
        #    inspect.signature following an unsafe __wrapped__ instance reference.
        wrapped = o.attrib_tool_round(o.AGENT_MARKET_ANALYST, real_tool_node)
        assert not hasattr(wrapped, "__wrapped__")

        # 2. The wrapped ToolNode registers and compiles.
        class S(TypedDict):
            messages: list

        workflow = StateGraph(S)
        workflow.add_node("tool", wrapped)
        workflow.add_edge("tool", END)
        workflow.set_entry_point("tool")
        graph = workflow.compile()

        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        # CLI-style run scope (begin + bind, finalized automatically).
        with o.run_telemetry([handler], results_dir="/tmp", write=False, ticker="AAPL", trade_date="2026-01-02") as c:
            assert c is collector
            ai = AIMessage(
                content="",
                tool_calls=[{"name": "increment", "args": {"a": 1}, "id": "c1", "type": "tool_call"}],
            )
            # 3. Executing preserves ToolNode behavior (returns ToolMessage with the result).
            out = graph.invoke({"messages": [ai]}, config={"callbacks": [handler]})

        result_tool_message = out["messages"][-1]
        assert result_tool_message.type == "tool"
        assert result_tool_message.content == "2"

        # 4. One ToolNode execution records exactly one round.
        assert len(collector.tool_rounds) == 1
        assert collector.tool_rounds[0].number_of_tool_calls == 1
        assert collector.tool_rounds[0].agent_id == o.AGENT_MARKET_ANALYST
        assert collector.tool_rounds[0].status == "ok"

        # 5. The actual tool execution stays a tool_call, not conflated with the round.
        assert len(collector.tool_calls) == 1
        call = collector.tool_calls[0]
        assert call.tool_name == "increment"
        assert call.agent_id == o.AGENT_MARKET_ANALYST
        assert call.success is True

    def test_count_tool_calls_in_state(self):
        assert o.count_tool_calls_in_state({}) == 0
        assert o.count_tool_calls_in_state({"messages": []}) == 0
        plain = AIMessage(content="no tools")
        assert o.count_tool_calls_in_state({"messages": [plain]}) == 0
        ai = AIMessage(content="", tool_calls=[
            {"name": "t", "args": {}, "id": "1", "type": "tool_call"},
            {"name": "t", "args": {}, "id": "2", "type": "tool_call"},
            {"name": "t", "args": {}, "id": "3", "type": "tool_call"},
        ])
        assert o.count_tool_calls_in_state({"messages": [ai]}) == 3
        assert o.count_tool_calls_in_state(None) == 0

    def test_round_scopes_toolnode_agent(self):
        from langchain_core.tools import tool

        @tool
        def t() -> int:
            """Return one."""
            return 1

        collector = o.RunMetricsCollector()

        def tool_node(state):
            assert o.get_current_agent_id() == o.AGENT_SENTIMENT_ANALYST
            return {"messages": []}

        wrapped = o.attrib_tool_round(o.AGENT_SENTIMENT_ANALYST, tool_node)
        ai = AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "1", "type": "tool_call"}])
        with o.observe_run(collector):
            wrapped({"messages": [ai]})
        assert o.get_current_agent_id() is None
        assert collector.tool_rounds[0].agent_id == o.AGENT_SENTIMENT_ANALYST

    def test_round_failure_records_error(self):
        collector = o.RunMetricsCollector()

        def bad(state):
            raise RuntimeError("tool node boom")

        wrapped = o.attrib_tool_round(o.AGENT_TRADER, bad)
        ai = AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "1", "type": "tool_call"}])
        with o.observe_run(collector), pytest.raises(RuntimeError):
            wrapped({"messages": [ai]})
        ev = collector.tool_rounds[0]
        assert ev.status == "error"
        assert ev.error_type == "RuntimeError"

    def test_round_usable_as_decorator(self):
        collector = o.RunMetricsCollector()

        @o.attrib_tool_round(o.AGENT_BULL_RESEARCHER)
        def tool_node(state):
            return {"messages": []}

        ai = AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "1", "type": "tool_call"}])
        with o.observe_run(collector):
            tool_node({"messages": [ai]})
        assert collector.tool_rounds[0].agent_id == o.AGENT_BULL_RESEARCHER


# ---------------------------------------------------------------------------
# Regression: real ToolNode graph construction (the end-to-end run that
# previously raised before graph compilation).
# ---------------------------------------------------------------------------
class TestRealToolNodeGraphConstruction:
    def test_real_setup_graph_compiles_with_real_toolnodes(self):
        """Credential-free proof that the full analyst graph registers and
        compiles using the REAL ``langgraph.prebuilt.ToolNode`` instances.

        This exercises ``GraphSetup.setup_graph`` -> ``wrap_tool_node`` ->
        ``StateGraph.add_node`` (the exact path that regressed and raised
        ``TypeError: descriptor '__call__' for 'type' objects doesn't apply to a
        'ToolNode' object`` before graph compilation / LLM execution).
        """
        from langchain_core.language_models.fake_chat_models import FakeListChatModel

        from tradingagents.graph.conditional_logic import ConditionalLogic
        from tradingagents.graph.setup import GraphSetup
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        fake_llm = FakeListChatModel(responses=["ok"] * 20)
        # The same real per-analyst ToolNodes the CLI constructs.
        tool_nodes = TradingAgentsGraph._create_tool_nodes(None)
        assert set(tool_nodes) == {"market", "social", "news", "fundamentals"}

        setup = GraphSetup(fake_llm, fake_llm, tool_nodes, ConditionalLogic())
        graph = setup.setup_graph(("market", "social", "news", "fundamentals"))
        compiled = graph.compile()
        assert compiled is not None

    def test_real_trader_partial_wrapped_and_executes(self):
        """Regression: the REAL Trader node is a ``functools.partial``, so the
        observability wrapper must not assume ``node.__name__``.

        This exercises the real ``GraphSetup.setup_graph`` path -> ``wrap_agent_node``
        -> ``attrib_agent_node`` -> ``StateGraph.add_node`` with the actual
        ``create_trader`` partial, then executes ONLY the wrapped ``Trader`` node
        through the compiled graph (credential-free, no external LLM / tool
        execution). The recorded node telemetry must use the stable business name
        ``"Trader"`` rather than the generic ``"partial"``.
        """
        import functools

        from langchain_core.language_models.fake_chat_models import FakeListChatModel

        from tradingagents.agents.trader.trader import create_trader
        from tradingagents.graph.conditional_logic import ConditionalLogic
        from tradingagents.graph.propagation import Propagator
        from tradingagents.graph.setup import GraphSetup
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        # FakeListChatModel does not implement bind_tools / with_structured_output,
        # so every agent falls back to free-text generation — credential-free.
        fake_llm = FakeListChatModel(responses=["**Action**: Buy\n\nStrong setup.\n\n"
                                                "FINAL TRANSACTION PROPOSAL: **BUY**"])
        tool_nodes = TradingAgentsGraph._create_tool_nodes(None)
        setup = GraphSetup(fake_llm, fake_llm, tool_nodes, ConditionalLogic())
        graph = setup.setup_graph(("market", "social", "news", "fundamentals"))
        compiled = graph.compile()

        # The real Trader registered by setup_graph is indeed a functools.partial.
        assert isinstance(create_trader(fake_llm), functools.partial)

        collector = o.RunMetricsCollector()
        state = Propagator().create_initial_state("NVDA", "2026-01-02")
        state["investment_plan"] = "**Recommendation**: Buy"
        with o.observe_run(collector):
            out = compiled.nodes["Trader"].invoke(state, compiled.config)

        # The wrapped Trader partial executed and returned its real result.
        assert out.get("sender") == "Trader"
        assert "**Action**: Buy" in out["trader_investment_plan"]

        # The recorded node name is the explicit, stable business name.
        ev = collector.node_events[0]
        assert ev.node == "Trader"
        assert ev.agent_id == o.AGENT_TRADER
        assert ev.status == "ok"


# ---------------------------------------------------------------------------
# Phase 2: sentiment prefetch instrumentation
# ---------------------------------------------------------------------------
class TestPrefetch:
    def test_prefetch_success_records_size(self):
        collector = o.RunMetricsCollector()
        with o.observe_run(collector, o.AGENT_SENTIMENT_ANALYST):
            result = o.record_prefetch_call("news", lambda x: "DATA" * 10, "t")
        assert result == "DATA" * 10
        assert len(collector.prefetch_events) == 1
        ev = collector.prefetch_events[0]
        assert ev.source == "news"
        assert ev.success is True
        assert ev.agent_id == o.AGENT_SENTIMENT_ANALYST
        assert ev.result_utf8_bytes == len(b"DATA" * 10)

    def test_prefetch_failure_records_and_reraises(self):
        collector = o.RunMetricsCollector()

        def bad(x):
            raise RuntimeError("fetch boom")

        with o.observe_run(collector, o.AGENT_SENTIMENT_ANALYST), pytest.raises(RuntimeError):
            o.record_prefetch_call("reddit", bad, "t")
        ev = collector.prefetch_events[0]
        assert ev.success is False
        assert ev.error_type == "RuntimeError"
        assert ev.result_utf8_bytes == 0

    def test_prefetch_no_collector_is_safe(self):
        # No bound collector -> no event recorded, result still returned.
        assert o.record_prefetch_call("news", lambda x: "ok", "t") == "ok"

    def test_prefetch_source_is_not_raw_content(self):
        collector = o.RunMetricsCollector()
        secret = "SENSITIVE-FEED-CONTENT-SHOULD-NOT-MATTER"
        with o.observe_run(collector):
            o.record_prefetch_call("stocktwits", lambda x: x, secret)
        # The event records only size — the underlying content is never stored.
        ev = collector.prefetch_events[0]
        blob = json.dumps(vars(ev), default=repr)
        assert "SENSITIVE-FEED-CONTENT-SHOULD-NOT-MATTER" not in blob
        assert ev.result_utf8_bytes == len(secret.encode())


# ---------------------------------------------------------------------------
# Phase 2: structured-output instrumentation
# ---------------------------------------------------------------------------
class TestStructuredOutput:
    def test_bind_success_records_success(self):
        from tradingagents.agents.utils import structured as st

        class FakeLLM:
            def with_structured_output(self, schema):
                class X:
                    pass
                return X()

        collector = o.RunMetricsCollector()
        with o.observe_run(collector, o.AGENT_PORTFOLIO_MANAGER):
            assert st.bind_structured(FakeLLM(), dict, "Portfolio Manager") is not None
        assert collector.structured_events[0].kind == "success"
        assert collector.structured_events[0].agent_id == o.AGENT_PORTFOLIO_MANAGER

    def test_bind_unsupported_records_unsupported(self):
        from tradingagents.agents.utils import structured as st

        class FakeLLM:
            def with_structured_output(self, schema):
                raise NotImplementedError("no support")

        collector = o.RunMetricsCollector()
        with o.observe_run(collector):
            assert st.bind_structured(FakeLLM(), dict, "Trader") is None
        assert collector.structured_events[0].kind == "unsupported"

    def test_invoke_success(self):
        from tradingagents.agents.utils import structured as st

        class Structured:
            def invoke(self, prompt):
                class R:
                    content = "rendered"
                return R()

        collector = o.RunMetricsCollector()
        with o.observe_run(collector, o.AGENT_RESEARCH_MANAGER):
            out = st.invoke_structured_or_freetext(
                Structured(), None, "p", lambda x: x.content, "Research Manager"
            )
        assert out == "rendered"
        ev = collector.structured_events[-1]
        assert ev.kind == "success"
        assert ev.used_fallback is False

    def test_invoke_failure_falls_back(self):
        from tradingagents.agents.utils import structured as st

        class Structured:
            def invoke(self, prompt):
                raise ValueError("malformed")

        class Plain:
            def invoke(self, prompt):
                class R:
                    content = "fallback"
                return R()

        collector = o.RunMetricsCollector()
        with o.observe_run(collector):
            out = st.invoke_structured_or_freetext(
                Structured(), Plain(), "p", lambda x: x.content, "Trader"
            )
        assert out == "fallback"
        ev = collector.structured_events[0]
        assert ev.kind == "failure"
        assert ev.used_fallback is True
        assert ev.error_type == "ValueError"

    def test_invoke_unsupported_freetext_records_runtime_unsupported(self):
        # When bind_structured reported the provider does not support structured
        # output (structured_llm is None), the invocation path still falls back
        # to free text. The unsupported status must be observable at runtime (in
        # run scope), not only at construction time.
        from tradingagents.agents.utils import structured as st

        class Plain:
            def invoke(self, prompt):
                class R:
                    content = "free text"
                return R()

        collector = o.RunMetricsCollector()
        with o.observe_run(collector, o.AGENT_TRADER):
            out = st.invoke_structured_or_freetext(
                None, Plain(), "p", lambda x: x.content, "Trader"
            )
        assert out == "free text"
        ev = collector.structured_events[0]
        assert ev.kind == "unsupported"
        assert ev.used_fallback is True
        assert ev.agent_id == o.AGENT_TRADER

    def test_invoke_failure_already_present_still_falls_back(self):
        from tradingagents.agents.utils import structured as st

        class Structured:
            def invoke(self, prompt):
                raise ValueError("x")

        class Plain:
            def invoke(self, prompt):
                class R:
                    content = "fb"
                return R()

        collector = o.RunMetricsCollector()
        with o.observe_run(collector):
            out = st.invoke_structured_or_freetext(
                Structured(), Plain(), "p", lambda x: x.content, "Trader"
            )
        assert out == "fb"


# ---------------------------------------------------------------------------
# Phase 2: node context diagnostics
# ---------------------------------------------------------------------------
class TestNodeContextDiagnostics:
    def test_size_agent_state_context_whitelisted(self):
        state = {
            "messages": [HumanMessage(content="hi"), AIMessage(content="yo")],
            "company_of_interest": "AAPL",
            "trade_date": "2026-01-01",
            "sentiment_report": {"band": "bullish"},
        }
        sizes = o.size_agent_state_context(state)
        assert isinstance(sizes, dict)
        # Only whitelisted report fields are sized; contents never leak in.
        assert set(sizes) <= set(o.AGENT_STATE_CONTEXT_WHITELIST)
        assert "sentiment_report" in sizes
        for value in sizes.values():
            assert isinstance(value, int)
        blob = json.dumps(sizes)
        assert "bullish" not in blob

    def test_size_agent_state_context_non_dict(self):
        assert o.size_agent_state_context(None) == {}
        assert o.size_agent_state_context("just a string") == {}

    def test_node_event_context_contains_only_sizes(self):
        collector = o.RunMetricsCollector()

        def node(state):
            return {}

        wrapped = o.attrib_agent_node(o.AGENT_CONSERVATIVE_ANALYST, node)
        secret_state = {"messages": [HumanMessage(content="NOT-A-SECRET"), ],
                        "secret_plan": lambda: 0, "memory": {"key": "hidden"}}
        with o.observe_run(collector):
            wrapped(secret_state)
        blob = json.dumps(vars(collector.node_events[0]), default=repr)
        assert "NOT-A-SECRET" not in blob
        for key, value in collector.node_events[0].context_bytes.items():
            assert isinstance(value, int)


# ---------------------------------------------------------------------------
# Phase 2: run aggregates / metadata / telemetry payload
# ---------------------------------------------------------------------------
class TestRunAggregates:
    def _collect(self, agent_id):
        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        # One LLM call with usage for the agent.
        with o.observe_run(collector, agent_id):
            _invoke_llm(["hi"], [handler], usage={
                "usage_metadata": {"input_tokens": 10, "output_tokens": 5,
                                   "total_tokens": 15},
            })
        return collector

    def test_telemetry_builds_run_metadata(self):
        collector = self._collect(o.AGENT_MARKET_ANALYST)
        collector.begin_run(ticker="AAPL", trade_date="2026-01-01", asset_type="stock",
                            selected_analysts=[o.AGENT_MARKET_ANALYST], llm_provider="openai")
        telemetry = collector.build_telemetry()
        assert telemetry["schema_version"] == o.TELEMETRY_SCHEMA_VERSION
        run = telemetry["run"]
        assert run["ticker"] == "AAPL"
        assert run["trade_date"] == "2026-01-01"
        assert run["selected_analysts"] == [o.AGENT_MARKET_ANALYST]
        assert run["run_status"] == "running"

    def test_per_agent_aggregates(self):
        collector = self._collect(o.AGENT_MARKET_ANALYST)
        telemetry = collector.build_telemetry()
        agent_agg = telemetry["agents"][o.AGENT_MARKET_ANALYST]
        assert agent_agg["llm_calls"] == 1
        assert agent_agg["llm_success_count"] == 1
        assert agent_agg["calls_with_provider_usage"] == 1

    def test_run_totals_are_sum_of_agents(self):
        collector = self._collect(o.AGENT_MARKET_ANALYST)
        telemetry = collector.build_telemetry()
        assert telemetry["run_totals"]["llm_calls"] == telemetry["agents"][o.AGENT_MARKET_ANALYST]["llm_calls"]

    def test_unattributed_tracked(self):
        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        # No agent scope -> LLM call attributed to unattributed pseudo-agent.
        with o.observe_run(collector):
            _invoke_llm(["hi"], [handler])
        telemetry = collector.build_telemetry()
        assert telemetry["unattributed_llm_events"] == 1
        assert o.AGENT_UNATTRIBUTED in telemetry["agents"]

    def test_usage_coverage_complete_and_partial(self):
        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        with o.observe_run(collector, o.AGENT_TRADER):
            _invoke_llm(["with usage"], [handler], usage={
                "usage_metadata": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            })
        assert collector.build_telemetry()["usage_coverage"]["complete"] is True

        collector2 = o.RunMetricsCollector()
        handler2 = o.ObservabilityCallbackHandler(collector=collector2)
        with o.observe_run(collector2, o.AGENT_TRADER):
            _invoke_llm(["no usage"], [handler2])
        cov = collector2.build_telemetry()["usage_coverage"]
        assert cov["complete"] is False
        assert cov["calls_without_provider_usage"] == 1

    def test_audit_quality_attribution_complete(self):
        collector = self._collect(o.AGENT_MARKET_ANALYST)
        collector.finish_run("completed")
        collector.mark_telemetry_written()
        audit = collector.build_telemetry()["audit_quality"]
        assert audit["attribution_complete"] is True
        assert audit["telemetry_complete"] is True

    def test_agent_aggregate_includes_phase2_counts(self):
        collector = o.RunMetricsCollector()
        with o.observe_run(collector, o.AGENT_SENTIMENT_ANALYST):
            o.record_prefetch_call("news", lambda x: "D" * 10, "t")
            o.record_prefetch_call("reddit", lambda x: "R" * 20, "t")
        # A fake structured-unsupported event via direct collector method.
        collector.record_structured(o.StructuredOutputEvent(
            telemetry_run_id=collector.telemetry_run_id, agent_id=o.AGENT_SENTIMENT_ANALYST,
            agent_name="Sentiment Analyst", kind="unsupported",
            started_at=time.time(), ended_at=time.time(), duration_ms=0.0,
            error_type=None, used_fallback=False,
        ))
        telemetry = collector.build_telemetry()
        agg = telemetry["agents"][o.AGENT_SENTIMENT_ANALYST]
        assert agg["prefetched_data_calls"] == 2
        assert agg["structured_unsupported"] == 1


# ---------------------------------------------------------------------------
# Phase 2: telemetry JSON persistence + privacy
# ---------------------------------------------------------------------------
class TestTelemetryPersistence:
    def test_write_telemetry_artifact_path_and_content(self, tmp_path):
        collector = o.RunMetricsCollector()
        collector.begin_run(ticker="AAPL", trade_date="2026-01-01", asset_type="stock")
        collector.finish_run("completed")
        path = o.write_telemetry_artifact(collector, results_dir=str(tmp_path))
        assert path is not None
        assert path.exists()
        assert path.name == f"{collector.telemetry_run_id}.json"
        data = json.loads(path.read_text())
        assert data["schema_version"] == o.TELEMETRY_SCHEMA_VERSION
        assert data["run"]["ticker"] == "AAPL"
        assert data["audit_quality"]["telemetry_complete"] is True
        assert collector.has_telemetry_been_written() is True

    def test_telemetry_path_property_matches(self, tmp_path):
        collector = o.RunMetricsCollector()
        collector.results_dir = str(tmp_path)
        collector.begin_run(ticker="AAPL", trade_date="2026-01-01")
        written = o.write_telemetry_artifact(collector)
        assert collector.telemetry_path == str(written)

    def test_privacy_no_raw_content_in_artifact(self, tmp_path):
        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        with o.observe_run(collector, o.AGENT_TRADER):
            _invoke_llm(["TOP-SECRET-PROMPT"], [handler])
        collector.begin_run(ticker="AAPL", trade_date="2026-01-01")
        collector.finish_run("completed")
        path = o.write_telemetry_artifact(collector, results_dir=str(tmp_path))
        blob = path.read_text()
        assert "TOP-SECRET-PROMPT" not in blob
        assert "unattributed" in blob or o.AGENT_TRADER in blob

    def test_privacy_excludes_wide_forbidden_content_set(self, tmp_path):
        # Prove the artifact never contains raw prompt / message / tool-result /
        # fetched-content bodies, secrets, auth material, environment dumps or
        # state/memory. Only hashes + byte sizes are allowed.
        from langchain_core.tools import tool

        secret_prompt = "SECRET-PROMPT-BODY-9f2e"
        secret_tool_result = "SECRET-TOOL-RESULT-c41a"
        secret_args = {"q": "SECRET-ARGS-77b1"}

        @tool
        def lookup(q: str) -> str:
            """Return a secret."""
            return secret_tool_result

        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        with o.observe_run(collector, o.AGENT_TRADER):
            _invoke_llm([secret_prompt], [handler])
            lookup.invoke(secret_args, config={"callbacks": [handler]})
            # Also record a prefetch + structured outcome + a node-context event.
            o.record_prefetch_call("reddit", lambda _x, **_: "SECRET-REDDIT-BODY", "AAPL")

        collector.begin_run(ticker="AAPL", trade_date="2026-01-01")
        collector.finish_run("completed")
        blob = o.write_telemetry_artifact(collector, results_dir=str(tmp_path)).read_text()

        forbidden = [
            secret_prompt,
            secret_tool_result,
            secret_args["q"],
            "SECRET-REDDIT-BODY",
            "Authorization: Bearer",
            "api_key",
            "sk-",
            "Bearer ",
        ]
        for item in forbidden:
            assert item not in blob, f"forbidden content leaked: {item!r}"

    def test_write_is_idempotent_single_artifact(self, tmp_path):
        collector = o.RunMetricsCollector()
        collector.begin_run(ticker="AAPL", trade_date="2026-01-01")
        collector.finish_run("completed")
        p1 = o.write_telemetry_artifact(collector, results_dir=str(tmp_path))
        p2 = o.write_telemetry_artifact(collector, results_dir=str(tmp_path))
        assert p1 == p2
        assert p1.exists()
        # Same run id -> same path, not duplicated.
        assert len(list(p1.parent.glob("*.json"))) == 1

    def test_write_never_raises_on_bad_results_dir(self, tmp_path):
        collector = o.RunMetricsCollector()
        collector.begin_run(ticker="AAPL", trade_date="2026-01-01")
        collector.finish_run("completed")
        # The results dir is a *file*, so mkdir fails; write must return None,
        # never raise.
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("occupied")
        assert o.write_telemetry_artifact(collector, results_dir=str(blocker)) is None


# ---------------------------------------------------------------------------
# Phase 2: run lifecycle (begin / finish / run_telemetry) + idempotency
# ---------------------------------------------------------------------------
class TestRunLifecycle:
    def test_begin_run_sets_started_once(self):
        collector = o.RunMetricsCollector()
        collector.begin_run(ticker="AAPL")
        collector.begin_run(ticker="TSLA")  # second begin ignored
        assert collector.is_run_started() is True
        assert collector.ticker == "AAPL"
        assert collector.run_status == "running"

    def test_finish_run_idempotent(self):
        collector = o.RunMetricsCollector()
        collector.begin_run()
        collector.finish_run("completed")
        collector.finish_run("failed")  # ignored
        assert collector.run_status == "completed"
        assert collector.is_run_finished() is True

    def test_resolve_observability_collector(self):
        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        assert o.resolve_observability_collector([handler]) is collector
        assert o.resolve_observability_collector([]) is None
        assert o.resolve_observability_collector(None) is None
        assert o.resolve_observability_collector([object()]) is None

    def test_begin_resolves_from_handler(self):
        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        resolved = o.begin_observability_run([handler], results_dir="/tmp")
        assert resolved is collector
        assert resolved.is_run_started() is True

    def test_begin_creates_fresh_when_no_handler(self):
        resolved = o.begin_observability_run(None)
        assert isinstance(resolved, o.RunMetricsCollector)
        assert resolved.is_run_started() is True

    def test_programmatic_sequential_runs_use_independent_collectors(self):
        # A plain (collector-less) observability handler is what `propagate`
        # passes; each programmatic run must get its OWN fresh collector (not
        # reuse one shared via the handler) so two sequential propagate() calls
        # cannot leak metrics across runs.
        handler = o.ObservabilityCallbackHandler()  # no explicit collector
        c1 = o.begin_observability_run([handler], results_dir="/tmp", ticker="AAPL")
        c2 = o.begin_observability_run([handler], results_dir="/tmp", ticker="TSLA")
        assert c1 is not c2
        assert c1.telemetry_run_id != c2.telemetry_run_id

    def test_run_telemetry_completed_and_written(self, tmp_path):
        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        with o.run_telemetry([handler], results_dir=str(tmp_path), ticker="AAPL", trade_date="2026-01-01") as c:
            assert c is collector
        assert collector.is_run_finished() is True
        assert collector.run_status == "completed"
        assert collector.has_telemetry_been_written() is True

    def test_run_telemetry_failed_still_writes_and_reraises(self, tmp_path):
        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        with pytest.raises(ValueError):
            with o.run_telemetry([handler], results_dir=str(tmp_path), ticker="AAPL", trade_date="2026-01-01"):
                raise ValueError("app boom")
        assert collector.is_run_finished() is True
        assert collector.run_status == "failed"
        assert collector.failure_type == "ValueError"
        assert collector.has_telemetry_been_written() is True

    def test_finalize_idempotent_and_never_raises(self, tmp_path):
        collector = o.RunMetricsCollector()
        collector.begin_run(ticker="AAPL", trade_date="2026-01-01")
        collector.results_dir = str(tmp_path)
        o.finalize_observability_run(collector, status="completed", write=True)
        # Second finalize is a no-op win (no double write / no raise).
        o.finalize_observability_run(collector, status="completed", write=True)
        assert collector.has_telemetry_been_written() is True
        assert collector.telemetry_path.startswith(str(tmp_path))

    def test_finalize_none_is_noop(self):
        assert o.finalize_observability_run(None) is None

    def test_bind_unbind_scope(self):
        collector = o.RunMetricsCollector()
        token = o.bind_run_scope(collector)
        try:
            assert o.get_current_collector() is collector
        finally:
            o.unbind_run_scope(token)
        assert o.get_current_collector() is None

    def test_unbind_none_and_double_reset_safe(self):
        assert o.unbind_run_scope(None) is None
        collector = o.RunMetricsCollector()
        token = o.bind_run_scope(collector)
        o.unbind_run_scope(token)
        # Double reset is a no-op (never raises).
        o.unbind_run_scope(token)

    def test_cli_style_lifecycle_records_phase2(self, tmp_path):
        """The CLI path: begin + explicit scope bind streams phase-2 events."""
        collector = o.RunMetricsCollector()
        handler = o.ObservabilityCallbackHandler(collector=collector)
        o.begin_observability_run(
            [handler], results_dir=str(tmp_path), ticker="AAPL", trade_date="2026-01-01"
        )
        token = o.bind_run_scope(collector)
        try:
            # A node wrapper executes inside the bound scope.
            def node(state):
                return {}

            wrapped = o.attrib_agent_node(o.AGENT_TRADER, node)
            wrapped({"messages": [], "market_report": "x"})
            # Prefetch / structured-record directly via scope binding.
            o.record_prefetch_call("news", lambda x: "D" * 10, "t")
        finally:
            o.unbind_run_scope(token)
        o.finalize_observability_run(collector, status="completed")
        assert collector.node_events[0].agent_id == o.AGENT_TRADER
        assert collector.prefetch_events[0].source == "news"
        assert collector.is_run_finished() is True
        assert collector.run_status == "completed"


# ---------------------------------------------------------------------------
# Phase 2: CLI stats handler summary compaction
# ---------------------------------------------------------------------------
class TestStatsHandlerSummary:
    def _make(self):
        from cli.stats_handler import StatsCallbackHandler

        return StatsCallbackHandler()

    def test_get_stats_legacy_keys_present(self):
        handler = self._make()
        stats = handler.get_stats()
        for key in ("llm_calls", "tool_calls", "tokens_in", "tokens_out"):
            assert key in stats

    def test_get_stats_observability_fields(self):
        handler = self._make()
        collector = handler.collector
        with o.observe_run(collector, o.AGENT_TRADER):
            o.record_prefetch_call("news", lambda x: "D" * 10, "t")
        stats = handler.get_stats()
        assert "agents" in stats
        assert stats["agents"][o.AGENT_TRADER]["prefetch_calls"] == 1
        assert "usage_complete" in stats
        assert "unattributed_llm" in stats
        assert "structured_fallbacks" in stats
        assert "duplicate_tool_calls" in stats
        assert "telemetry_path" in stats

    def test_agent_summary_counts_tool_rounds_and_nodes(self):
        handler = self._make()
        collector = handler.collector

        def node(state):
            return {}

        wrapped = o.attrib_agent_node(o.AGENT_TRADER, node)
        with o.observe_run(collector):
            wrapped({"messages": []})

        ai = AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "1", "type": "tool_call"}])
        tool_wrapped = o.attrib_tool_round(o.AGENT_TRADER, lambda s: {"messages": []})
        with o.observe_run(collector):
            tool_wrapped({"messages": [ai]})

        stats = handler.get_stats()
        agg = stats["agents"][o.AGENT_TRADER]
        assert agg["node_invocations"] == 1
        assert agg["tool_rounds"] == 1
