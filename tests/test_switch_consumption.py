"""The graph must consume exactly the switches a spec declares.

These tests drive the **real** ``GraphSetup`` with a stub LLM and intercept the
analyst factories where ``GraphSetup`` actually resolves them
(``tradingagents.graph.setup``). Patching ``tradingagents.agents`` instead would
have no effect -- see V1 ``REMEDIATION.md`` REM-1 -- so the tests assert that
the interception point is non-vacuous by mutating the captured kwargs and
requiring the verifier to fire.
"""

from __future__ import annotations

from typing import Any

import pytest

import tradingagents.graph.setup as setup_mod
from tradingagents.graph.switch_verification import (
    SwitchNotConsumed,
    expected_analyst_kwargs,
    validate_spec_switches,
    verify_news_toolnode,
    verify_switches_consumed,
)

ARMS = {
    "B": {"batch_macro": False, "single_pass": False, "structured": True, "s2_downstream": True},
    "AB": {"batch_macro": True, "single_pass": False, "structured": True, "s2_downstream": True},
    "C0": {"batch_macro": False, "single_pass": True, "structured": True, "s2_downstream": True},
    "CC": {"batch_macro": True, "single_pass": True, "structured": True, "s2_downstream": True},
}


class _Stub:
    """Stands in for any graph node / LLM.

    Deliberately *not* a free-for-all ``__getattr__``: LangGraph introspects
    objects it is handed (``__signature__``, ``__name__``), so an unbounded stub
    breaks graph construction for reasons unrelated to the switches.
    """

    name = "stub"

    def __call__(self, *args, **kwargs):  # pragma: no cover - not exercised
        return self

    def invoke(self, *args, **kwargs):  # pragma: no cover
        return {}

    def add_node(self, *args, **kwargs):
        return self

    def add_edge(self, *args, **kwargs):
        return self

    def add_conditional_edges(self, *args, **kwargs):
        return self

    def set_entry_point(self, *args, **kwargs):
        return self

    def bind_tools(self, *args, **kwargs):
        return self


def _config_for(switches: dict) -> dict:
    return {
        "single_pass_finalization_enabled": switches["single_pass"],
        "structured_analyst_output_enabled": switches["structured"],
        "batch_macro_enabled": switches["batch_macro"],
    }


def build_real_graph(switches: dict, monkeypatch):
    """Run the real ``GraphSetup`` and return the kwargs each analyst received."""
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    from tradingagents.graph.conditional_logic import ConditionalLogic
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    observed: dict[str, dict] = {}

    def _spy(name):
        def _factory(*args, **kwargs):
            observed[name] = dict(kwargs)
            return _Stub()

        return _factory

    # The exact namespace GraphSetup resolves the names from.
    for analyst in ("market", "news", "fundamentals"):
        monkeypatch.setattr(setup_mod, f"create_{analyst}_analyst", _spy(analyst))

    fake_llm = FakeListChatModel(responses=["ok"] * 20)
    tool_nodes = TradingAgentsGraph._create_tool_nodes(None)
    graph = setup_mod.GraphSetup(
        quick_thinking_llm=fake_llm,
        deep_thinking_llm=fake_llm,
        tool_nodes=tool_nodes,
        conditional_logic=ConditionalLogic(),
        config=_config_for(switches),
    )
    # Building the workflow is what actually calls the factories.
    graph.setup_graph(["market", "news", "fundamentals"])
    return observed


@pytest.mark.parametrize("arm", list(ARMS))
def test_real_graph_consumes_the_declared_switches(arm, monkeypatch):
    switches = ARMS[arm]
    observed = build_real_graph(switches, monkeypatch)
    verify_switches_consumed(switches, observed=observed)


@pytest.mark.parametrize("arm", list(ARMS))
def test_expected_kwargs_match_what_the_real_graph_passes(arm, monkeypatch):
    switches = ARMS[arm]
    observed = build_real_graph(switches, monkeypatch)
    expected = expected_analyst_kwargs(switches)
    for analyst, want in expected.items():
        assert observed[analyst] == want, analyst


def test_single_pass_is_and_of_structured(monkeypatch):
    """``single_pass=true, structured=false`` must run single-pass OFF."""
    switches = {"batch_macro": True, "single_pass": True,
                "structured": False, "s2_downstream": True}
    observed = build_real_graph(switches, monkeypatch)
    # The graph really does compute the AND ...
    for analyst in ("market", "news", "fundamentals"):
        assert observed[analyst]["single_pass"] is False, analyst
    # ... and the verifier agrees with the graph rather than with the raw flag.
    verify_switches_consumed(switches, observed=observed)


# --- non-vacuity ------------------------------------------------------------


def test_a_graph_built_with_the_wrong_switch_is_rejected(monkeypatch):
    switches = ARMS["CC"]  # batch_macro=True, single_pass=True
    observed = build_real_graph(switches, monkeypatch)
    tampered = {k: dict(v) for k, v in observed.items()}
    tampered["news"]["single_pass"] = False
    with pytest.raises(SwitchNotConsumed, match="not consumed as specified"):
        verify_switches_consumed(switches, observed=tampered)


def test_a_graph_built_with_batch_macro_off_is_rejected(monkeypatch):
    switches = ARMS["AB"]
    observed = build_real_graph(switches, monkeypatch)
    tampered = {k: dict(v) for k, v in observed.items()}
    tampered["news"]["batch_macro"] = False
    with pytest.raises(SwitchNotConsumed, match="not consumed as specified"):
        verify_switches_consumed(switches, observed=tampered)


def test_a_missing_consumer_is_an_error_not_a_skip(monkeypatch):
    switches = ARMS["B"]
    observed = build_real_graph(switches, monkeypatch)
    del observed["fundamentals"]
    with pytest.raises(SwitchNotConsumed, match="never constructed"):
        verify_switches_consumed(switches, observed=observed)


def test_no_captured_consumers_is_an_error(monkeypatch):
    with pytest.raises(SwitchNotConsumed, match="vacuous"):
        verify_switches_consumed(ARMS["B"], observed=None)


def test_truthy_non_boolean_switch_is_rejected():
    switches = dict(ARMS["B"])
    switches["single_pass"] = "yes"  # truthy but not a bool
    with pytest.raises(SwitchNotConsumed, match="must be a bool"):
        validate_spec_switches(switches)


def test_missing_switch_is_rejected():
    switches = dict(ARMS["B"])
    del switches["structured"]
    with pytest.raises(SwitchNotConsumed, match="missing switch"):
        validate_spec_switches(switches)


def test_s2_downstream_false_is_rejected():
    switches = dict(ARMS["B"])
    switches["s2_downstream"] = False
    with pytest.raises(SwitchNotConsumed, match="s2_downstream"):
        validate_spec_switches(switches)


def test_non_bool_observed_value_is_rejected(monkeypatch):
    switches = ARMS["B"]
    observed = build_real_graph(switches, monkeypatch)
    observed["market"]["structured"] = 1
    with pytest.raises(SwitchNotConsumed, match="non-bool"):
        verify_switches_consumed(switches, observed=observed)


# --- news tool binding ------------------------------------------------------


def test_batch_macro_true_requires_the_batch_tool():
    verify_news_toolnode(ARMS["AB"], {"get_macro_indicators_batch"})
    with pytest.raises(SwitchNotConsumed, match="was not given"):
        verify_news_toolnode(ARMS["AB"], {"get_macro_indicators"})


def test_batch_macro_false_forbids_the_batch_tool():
    verify_news_toolnode(ARMS["B"], {"get_macro_indicators"})
    with pytest.raises(SwitchNotConsumed, match="was given"):
        verify_news_toolnode(ARMS["B"], {"get_macro_indicators_batch"})
