"""System-component attribution (Reflector) — real callback path, mock LLM.

The pre-graph reflector makes a legitimate provider call before any graph node
exists. It must be attributed to a declared *system component*, never to an
agent and never left as ``unattributed``. These tests drive the real callback
handler and the real ``Reflector`` with a fake chat model, so the assertion is
about the event pipeline rather than about a hand-written helper.
"""
from __future__ import annotations

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from tradingagents import observability as o
from tradingagents.graph.reflection import Reflector


class _UsageModel(FakeListChatModel):
    """A fake chat model that reports provider usage on every response."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        result = super()._generate(messages, stop, run_manager, **kwargs)
        result.generations[0].message.usage_metadata = {
            "input_tokens": 11, "output_tokens": 4, "total_tokens": 15,
        }
        return result


def _handler_and_collector():
    collector = o.RunMetricsCollector()
    collector.begin_run(ticker="NVDA", trade_date="2026-09-23")
    handler = o.ObservabilityCallbackHandler(collector=collector)
    return handler, collector


def _reflect(handler, *, response="reflection text", responses=None):
    model = _UsageModel(responses=responses or [response])
    model.callbacks = [handler]
    reflector = Reflector(model)
    return reflector.reflect_on_final_decision(
        final_decision="Rating: Hold", raw_return=0.01, alpha_return=0.0,
        benchmark_name="SPY", holding_days=5)


class TestReflectorAttribution:
    def test_reflector_call_is_a_system_component_not_an_agent(self):
        handler, collector = _handler_and_collector()
        _reflect(handler)
        collector.finish_run("completed")
        payload = collector.build_telemetry()

        assert payload["attribution"]["system_calls"] == 1
        assert payload["attribution"]["agent_calls"] == 0
        assert payload["attribution"]["unattributed_calls"] == 0
        assert payload["attribution"]["system_components"] == ["pre_graph_reflector"]
        assert "pre_graph_reflector" in payload["system_components"]
        assert "unattributed" not in payload["agents"]
        assert payload["audit_quality"]["attribution_complete"] is True
        event = payload["llm_call_events"][0]
        assert event["attribution_type"] == o.ATTRIBUTION_SYSTEM
        assert event["component_id"] == "pre_graph_reflector"
        assert event["agent_id"] == o.AGENT_UNATTRIBUTED  # not relabelled as an agent
        assert event["reported_input_tokens"] == 11
        assert event["reported_output_tokens"] == 4

    def test_totals_close_across_agents_and_system_components(self):
        handler, collector = _handler_and_collector()
        with o.agent_scoped(o.AGENT_MARKET_ANALYST):
            _UsageModel(responses=["agent answer"], callbacks=[handler]).invoke("hi")
        _reflect(handler)
        collector.finish_run("completed")
        payload = collector.build_telemetry()

        totals = payload["run_totals"]
        attribution = payload["attribution"]
        assert totals["llm_calls"] == 2
        assert totals["reported_input_tokens_sum"] == 22
        assert totals["reported_output_tokens_sum"] == 8
        assert attribution["agent_tokens"] == 15
        assert attribution["system_tokens"] == 15
        assert attribution["unattributed_tokens"] == 0
        assert (attribution["agent_tokens"] + attribution["system_tokens"]
                + attribution["unattributed_tokens"]) == 30
        assert payload["audit_quality"]["attribution_complete"] is True

    def test_scope_is_restored_after_the_reflector(self):
        handler, collector = _handler_and_collector()
        with o.agent_scoped(o.AGENT_NEWS_ANALYST):
            _reflect(handler)
            assert o.get_current_attribution().attribution_type == o.ATTRIBUTION_AGENT
            assert o.get_current_agent_id() == o.AGENT_NEWS_ANALYST
        assert o.get_current_attribution().attribution_type == o.ATTRIBUTION_NONE

    def test_inside_an_agent_scope_the_system_scope_wins_for_the_call(self):
        handler, collector = _handler_and_collector()
        seen = {}

        class _Probe(FakeListChatModel):
            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                seen["type"] = o.get_current_attribution().attribution_type
                seen["component"] = o.get_current_component_id()
                return super()._generate(messages, stop, run_manager, **kwargs)

        with o.agent_scoped(o.AGENT_MARKET_ANALYST):
            Reflector(_Probe(responses=["x"], callbacks=[handler])).reflect_on_final_decision(
                "Rating: Hold", 0.0, 0.0)
        assert seen == {"type": o.ATTRIBUTION_SYSTEM, "component": "pre_graph_reflector"}
        collector.finish_run("completed")
        payload = collector.build_telemetry()
        assert payload["attribution"]["system_calls"] == 1
        assert payload["attribution"]["agent_calls"] == 0

    def test_reflector_exception_is_still_attributed_and_restores_scope(self):
        handler, collector = _handler_and_collector()

        class _Boom(FakeListChatModel):
            def _generate(self, *args, **kwargs):
                raise RuntimeError("provider exploded")

        with pytest.raises(RuntimeError):
            Reflector(_Boom(responses=["x"], callbacks=[handler])).reflect_on_final_decision(
                "Rating: Hold", 0.0, 0.0)
        assert o.get_current_attribution().attribution_type == o.ATTRIBUTION_NONE
        collector.finish_run("failed")
        payload = collector.build_telemetry()
        assert payload["attribution"]["system_calls"] == 1
        assert payload["llm_call_events"][0]["success"] is False
        assert payload["audit_quality"]["attribution_complete"] is True

    def test_two_consecutive_reflector_calls_are_both_attributed(self):
        handler, collector = _handler_and_collector()
        _reflect(handler, responses=["a", "b"])
        _reflect(handler, responses=["c"])
        collector.finish_run("completed")
        payload = collector.build_telemetry()
        assert payload["attribution"]["system_calls"] == 2
        assert payload["system_components"]["pre_graph_reflector"]["llm_calls"] == 2

    def test_an_unscoped_call_is_none_and_makes_the_run_incomplete(self):
        handler, collector = _handler_and_collector()
        _UsageModel(responses=["no scope"], callbacks=[handler]).invoke("hi")
        collector.finish_run("completed")
        payload = collector.build_telemetry()
        assert payload["attribution"]["unattributed_calls"] == 1
        assert payload["audit_quality"]["attribution_complete"] is False
        event = payload["llm_call_events"][0]
        assert event["attribution_type"] == o.ATTRIBUTION_NONE
        assert event["agent_id"] == o.AGENT_UNATTRIBUTED

    def test_system_component_scope_requires_a_name(self):
        with pytest.raises(ValueError), o.system_component_scoped(""):
            pass
        with pytest.raises(ValueError), o.system_component_scoped(None):
            pass


class TestHarnessAcceptsSystemAttribution:
    @staticmethod
    def _payload():
        return {
            "schema_version": 2,
            "run": {"run_status": "completed"},
            "usage_coverage": {"complete": True, "llm_calls": 2,
                               "calls_with_provider_usage": 2,
                               "calls_without_provider_usage": 0,
                               "calls_missing_input_tokens": 0,
                               "calls_missing_output_tokens": 0},
            "audit_quality": {"usage_complete": True, "attribution_complete": True,
                              "telemetry_complete": True},
            "run_totals": {"reported_input_tokens_sum": 22,
                           "reported_output_tokens_sum": 8, "llm_calls": 2,
                           "tool_calls": 1},
            "attribution": {"agent_calls": 1, "system_calls": 1,
                            "unattributed_calls": 0, "agent_tokens": 15,
                            "system_tokens": 15, "unattributed_tokens": 0,
                            "system_components": ["pre_graph_reflector"]},
            "system_components": {"pre_graph_reflector": {"llm_calls": 1}},
            "llm_call_events": [
                {"callback_run_id": "a", "reported_input_tokens": 11,
                 "reported_output_tokens": 4, "usage_source": "provider",
                 "attribution_type": "agent", "component_id": None},
                {"callback_run_id": "b", "reported_input_tokens": 11,
                 "reported_output_tokens": 4, "usage_source": "provider",
                 "attribution_type": "system", "component_id": "pre_graph_reflector"},
            ],
        }

    def test_a_valid_system_component_keeps_the_run_valid(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        import token_benchmark as tb

        metrics = tb.extract_run_metrics(self._payload(), None, 0)
        assert metrics["valid"] is True
        assert metrics["usage_verdict"]["state"] == tb.USAGE_VALID

    def test_an_unattributed_event_still_invalidates_it(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        import token_benchmark as tb

        payload = self._payload()
        payload["audit_quality"]["attribution_complete"] = False
        payload["attribution"]["unattributed_calls"] = 1
        metrics = tb.extract_run_metrics(payload, None, 0)
        assert metrics["valid"] is False
        assert metrics["invalid_reason"] == tb.INVALID_USAGE_INCOMPLETE
