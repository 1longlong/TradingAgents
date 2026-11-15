"""Regressions from independent audit C (usage, tests, safety).

C-1 is a pre-existing RC1 defect, not a Plan C2 regression: it reproduces
identically at ``9948bf8``. It is fixed here because the 16-run study is a
*token* study and a completion-model call that silently vanishes from telemetry
would bias every arm's token totals.

C-3 is a gap in this round's own work: ``ANALYST_CONSUMERS`` was declared but
never checked against the real ``GraphSetup``, so deleting an analyst from that
table (and thereby from the verification) left every test green.
"""

from __future__ import annotations

import pytest

import tradingagents.graph.setup as setup_mod
from tradingagents.graph.switch_verification import (
    ANALYST_CONSUMERS,
    SwitchNotConsumed,
    consume_switches_from_setup,
    verify_switches_consumed,
)


# --- C-1: a completion-model call must reach telemetry ---------------------


def _invoke_completion_model(prompt: str):
    """One real ``BaseLLM`` call through the real callback handler."""
    from langchain_core.language_models.fake import FakeListLLM

    from cli.stats_handler import StatsCallbackHandler
    from tradingagents.observability import RunMetricsCollector

    collector = RunMetricsCollector()
    handler = StatsCallbackHandler()
    handler._collector = collector
    FakeListLLM(responses=["hi"]).invoke(prompt, config={"callbacks": [handler]})
    return collector


def test_a_completion_model_call_is_recorded() -> None:
    """The audited bug: ``prompts=None`` raised inside the callback and the call
    disappeared from telemetry entirely."""
    collector = _invoke_completion_model("a reasonably long prompt string")
    assert len(collector.llm_calls) == 1, (
        "a completion-model call produced no telemetry event"
    )


def test_a_completion_model_call_records_its_prompt_size() -> None:
    prompt = "a reasonably long prompt string"
    collector = _invoke_completion_model(prompt)
    event = collector.llm_calls[0]
    assert event.prompt_message_count == 1
    assert event.prompt_utf8_bytes == len(prompt.encode("utf-8"))


def test_the_callback_handler_receives_the_real_prompts() -> None:
    """Pin the defect at its source, not only at the observable outcome."""
    from tradingagents.observability import ObservabilityCallbackHandler

    seen = {}

    handler = ObservabilityCallbackHandler()

    def _spy(run_id, parent_run_id, serialized, prompts=None, messages=None):
        seen["prompts"] = prompts

    original = handler._handle_llm_start
    handler._handle_llm_start = _spy
    try:
        handler.on_llm_start({"name": "stub"}, ["one", "two"], run_id="rid-1")
    finally:
        handler._handle_llm_start = original
    assert seen["prompts"] == ["one", "two"]


# --- C-3: every declared switch consumer must be verified ------------------


def test_the_consumer_table_has_no_analyst_the_verifier_skips() -> None:
    """A consumer in the table must not be silently dropped by the verifier."""
    for analyst in ANALYST_CONSUMERS:
        assert analyst != "social", (
            "social has no switches; putting it in ANALYST_CONSUMERS would make "
            "the verifier skip it via a special case"
        )


def test_removing_an_analyst_from_the_observed_map_is_caught() -> None:
    switches = {"batch_macro": True, "single_pass": True,
                "structured": True, "s2_downstream": True}
    observed = {
        "market": {"structured": True, "single_pass": True},
        "fundamentals": {"structured": True, "single_pass": True},
    }
    with pytest.raises(SwitchNotConsumed, match="news.*never constructed"):
        verify_switches_consumed(switches, observed=observed)


def test_dropping_single_pass_from_one_analyst_is_caught() -> None:
    switches = {"batch_macro": True, "single_pass": True,
                "structured": True, "s2_downstream": True}
    observed = {
        "market": {"structured": True, "single_pass": True},
        "news": {"batch_macro": True, "structured": True, "single_pass": True},
        "fundamentals": {"structured": True},
    }
    with pytest.raises(SwitchNotConsumed, match="fundamentals.*single_pass"):
        verify_switches_consumed(switches, observed=observed)


@pytest.mark.parametrize("arm", ["B", "AB", "C0", "CC"])
def test_the_consumer_table_matches_what_graphsetup_passes(arm, monkeypatch) -> None:
    """The table must describe the *real* GraphSetup, not an intention."""
    from tests.test_switch_consumption import ARMS, build_real_graph

    switches = ARMS[arm]
    observed = build_real_graph(switches, monkeypatch)
    assert set(observed) == set(ANALYST_CONSUMERS), (
        "ANALYST_CONSUMERS disagrees with the analysts GraphSetup constructs"
    )
    for analyst, keys in ANALYST_CONSUMERS.items():
        assert set(observed[analyst]) == set(keys), analyst


@pytest.mark.parametrize("analyst,switch", [
    ("market", "structured"),
    ("market", "single_pass"),
    ("news", "batch_macro"),
    ("news", "structured"),
    ("news", "single_pass"),
    ("fundamentals", "structured"),
    ("fundamentals", "single_pass"),
])
def test_every_declared_consumer_switch_is_really_passed(analyst, switch, monkeypatch) -> None:
    from tests.test_switch_consumption import ARMS, build_real_graph

    observed = build_real_graph(ARMS["CC"], monkeypatch)
    assert switch in observed[analyst], (analyst, switch)


def test_consume_from_setup_covers_every_consumer() -> None:
    """The run path's read-back must cover exactly the declared consumers."""

    class _Setup:
        pass

    setup = _Setup()
    setup.config = {"batch_macro_enabled": True,
                    "structured_analyst_output_enabled": True,
                    "single_pass_finalization_enabled": True}
    mirrored = consume_switches_from_setup(setup)
    assert set(mirrored) == set(ANALYST_CONSUMERS)
    for analyst, keys in ANALYST_CONSUMERS.items():
        assert set(mirrored[analyst]) == set(keys), analyst
