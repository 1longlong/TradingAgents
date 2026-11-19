"""Phase 3B pre-call budget guard regressions (milestone 2, 2026-11-06).

The 2026-11-06 independent review (finding 2) reproduced an over-budget optional
call: with ``max_calls=1`` the graph still executed Bull and Bear (2 calls) and
only then evaluated, emitting ``budget_exhausted`` after the fact. The pre-call
guard refuses an optional debate call *before* it runs, so the hard call limit is
never exceeded, an incomplete round skips safely to the Research Manager, the
summary reserve stays reachable, and ``enabled=False`` keeps the legacy
behaviour.

These are graph-level deterministic offline tests: fixed stub gate, fake LLM, no
network, no live provider.

Traceability: FR-DDT-003 (budget-safe termination with summary reserve),
NFR-BUD-001 (budget safety); supports INV-7 (budget safety).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langgraph.prebuilt import ToolNode

from tradingagents.debate.budget import (
    can_afford_optional_call,
    resolve_budget_config_from_state,
)
from tradingagents.debate.config import DebateTerminationConfig
from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.propagation import Propagator
from tradingagents.graph.setup import GraphSetup

SYMBOL = "COF"
TARGET = "2026-05-13"

_TURN = (
    "Argument.\nDEBATE_METADATA: stance=Buy; confidence=0.7; cited=run:1; new_claims=growth|run:1;"
)
_RECORD = {
    "evidence_id": "run:1",
    "quality_status": "High",
    "observed_at": "2026-05-01",
    "value_raw": "190",
    "metric_name": "close",
    "unit_normalized": "USD",
}

BULL_SIG = "You are a Bull Analyst advocating for investing in the "
BEAR_SIG = "You are a Bear Analyst making the case against investing in the "


def _fake_llm(content: str = _TURN):
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=None)
    llm.invoke = MagicMock(return_value=MagicMock(content=content))
    bt = RunnableLambda(lambda m: AIMessage(content=content, tool_calls=[]))
    llm.bind_tools = MagicMock(return_value=bt)
    return llm


def _stub_gate_node(verdict: str = "normal"):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        return {
            "data_quality_verdict": verdict,
            "data_quality_gate_decision": {"decision": verdict, "decided_at": "2026-05-13T12:00:00Z"},
            "data_quality_context": f"[Data Quality Gate] Verdict: {verdict}.",
            "data_quality_error": None,
            "data_quality_evidence_records": [_RECORD],
            "data_quality_validation_results": {},
            "data_quality_group_statuses": [],
        }

    return node


def _build_graph(quick, deep, *, config_override=None):
    tool_nodes = {key: ToolNode([]) for key in ("market", "social", "news", "fundamentals")}
    setup = GraphSetup(
        quick,
        deep,
        tool_nodes,
        ConditionalLogic(),
        data_quality_gate_factory=lambda: _stub_gate_node(),
        debate_termination_config=config_override,
    )
    return setup.setup_graph(("market",)).compile()


def _initial_state():
    return Propagator().create_initial_state(SYMBOL, TARGET, asset_type="stock")


def _researcher_prompts(llm):
    prompts = [c.args[0] for c in llm.invoke.call_args_list if isinstance(c.args[0], str)]
    return {
        "bull": any(p.startswith(BULL_SIG) for p in prompts),
        "bear": any(p.startswith(BEAR_SIG) for p in prompts),
    }


class TestCanAffordOptionalCall:
    def test_call_budget_zero_rejects(self):
        cfg = DebateTerminationConfig.from_dict({"max_calls": 1})
        usage = {"calls": 1, "tokens": 0, "seconds": 0.0, "estimated": False}
        assert not can_afford_optional_call(usage, cfg)

    def test_first_call_admitted(self):
        cfg = DebateTerminationConfig.from_dict({"max_calls": 1})
        assert can_afford_optional_call({"calls": 0}, cfg)

    def test_reserve_consumed_rejects(self):
        cfg = DebateTerminationConfig.from_dict(
            {
                "max_calls": 100,
                "max_tokens": 10_000,
                "reserved_summary_tokens": 4_000,
                "max_time": 600.0,
                "reserved_summary_seconds": 90.0,
            }
        )
        usage = {"calls": 1, "tokens": 9_000, "seconds": 1.0, "estimated": True}
        assert not can_afford_optional_call(usage, cfg)

    def test_reserve_only_remaining_is_refused_when_estimate_does_not_fit(self):
        # Second-review reproduction: remaining tokens equal only the reserve, so
        # an optional call would eat the reserve. Must be refused.
        cfg = DebateTerminationConfig.from_dict(
            {
                "max_tokens": 10_000,
                "reserved_summary_tokens": 1_000,
                "next_round_estimate_tokens": 2_000,
                "max_time": 100_000,
            }
        )
        assert can_afford_optional_call({"calls": 0, "tokens": 9_000, "seconds": 0}, cfg) is False

    def test_reserve_plus_estimate_boundary_tokens(self):
        # next_call_estimate_tokens == ceil(2000/2) == 1000. Admitted iff
        # remaining >= reserve(1000) + estimate(1000) == 2000.
        cfg = DebateTerminationConfig.from_dict(
            {
                "max_tokens": 10_000,
                "reserved_summary_tokens": 1_000,
                "next_round_estimate_tokens": 2_000,
                "max_time": 100_000,
            }
        )
        # remaining 2000 -> exactly boundary -> admitted
        assert can_afford_optional_call({"calls": 0, "tokens": 8_000, "seconds": 0}, cfg) is True
        # remaining 1999 -> one short -> refused
        assert can_afford_optional_call({"calls": 0, "tokens": 8_001, "seconds": 0}, cfg) is False

    def test_reserve_plus_estimate_boundary_seconds(self):
        # next_call_estimate_seconds == 60/2 == 30. Admitted iff
        # remaining seconds >= reserve(90) + estimate(30) == 120.
        cfg = DebateTerminationConfig.from_dict(
            {
                "max_tokens": 10_000,
                "reserved_summary_tokens": 1_000,
                "next_round_estimate_tokens": 2_000,
                "max_time": 100_000,
                "reserved_summary_seconds": 90,
                "next_round_estimate_seconds": 60,
            }
        )
        # Plenty of tokens, only seconds tight: remaining 120 -> admitted.
        assert can_afford_optional_call({"calls": 0, "tokens": 0, "seconds": 99_880}, cfg) is True
        # remaining 119.5 -> refused
        assert can_afford_optional_call({"calls": 0, "tokens": 0, "seconds": 99_880.5}, cfg) is False

    def test_seconds_boundary_equal_reserve_refused(self):
        # Remaining seconds equal only the reserve (the second-review case).
        cfg = DebateTerminationConfig.from_dict(
            {
                "max_tokens": 10_000_000,
                "max_time": 100_000,
                "reserved_summary_seconds": 90,
                "next_round_estimate_seconds": 60,
            }
        )
        assert can_afford_optional_call({"calls": 0, "tokens": 0, "seconds": 99_910}, cfg) is False

    def test_disabled_config_always_admits(self):
        cfg = DebateTerminationConfig.from_dict({"enabled": False, "max_calls": 1})
        usage = {"calls": 99, "tokens": 10**9, "seconds": 10**9, "estimated": True}
        assert can_afford_optional_call(usage, cfg)

    def test_resolve_config_prefers_injected(self):
        cfg = DebateTerminationConfig.from_dict({"max_calls": 5})
        assert resolve_budget_config_from_state({}, cfg) is cfg

    def test_resolve_config_from_state_group(self):
        cfg = resolve_budget_config_from_state(
            {"debate_termination_config": {"max_calls": 7}}
        )
        assert cfg.max_calls == 7


class TestMaxCallsOneNeverRunsTwoDebateCalls:
    def test_max_calls_one_executes_exactly_one_call(self):
        cfg = DebateTerminationConfig.from_dict({"max_calls": 1, "max_debate_rounds": 3})
        quick = _fake_llm()
        deep = _fake_llm("Hold")
        graph = _build_graph(quick, deep, config_override=cfg)
        res = graph.invoke(_initial_state())

        assert res["debate_usage"]["calls"] == 1
        # The Bear call was refused before it ran: its prompt never went out.
        prompts = _researcher_prompts(quick)
        assert prompts["bull"] is True
        assert prompts["bear"] is False
        decision = res["debate_termination_decision"]
        assert decision["route"] == "summarize"
        assert decision["stop_reason"] == "budget_exhausted"
        # The incomplete round never produced round metrics (no Bear).
        assert res["investment_debate_state"].get("round_metrics", []) == []
        # The manager still ran (a report exists).
        assert res.get("final_trade_decision")
        # Usage is honestly flagged as an estimate.
        assert res["debate_usage"]["estimated"] is True

    def test_zero_remaining_capacity_refuses_both_speakers(self):
        # max_calls below what the first call needs is a degenerate but legal
        # bound: nothing runs and the run skips straight to the manager.
        cfg = DebateTerminationConfig.from_dict({"max_calls": 1, "max_debate_rounds": 3})
        quick = _fake_llm()
        deep = _fake_llm("Hold")
        graph = _build_graph(quick, deep, config_override=cfg)
        res = graph.invoke(_initial_state())
        assert res["debate_usage"]["calls"] <= cfg.max_calls

    def test_two_calls_admits_both_speakers_then_evaluates(self):
        cfg = DebateTerminationConfig.from_dict(
            {
                "max_calls": 2,
                "max_debate_rounds": 5,
                "max_tokens": 10_000_000,
                "max_time": 100_000.0,
                "reserved_summary_tokens": 100,
                "next_round_estimate_tokens": 100,
            }
        )
        quick = _fake_llm()
        deep = _fake_llm("Hold")
        graph = _build_graph(quick, deep, config_override=cfg)
        res = graph.invoke(_initial_state())
        assert res["debate_usage"]["calls"] == 2
        prompts = _researcher_prompts(quick)
        assert prompts["bull"] and prompts["bear"]
        # A complete round was evaluated by the dynamic evaluator.
        assert len(res["investment_debate_state"]["round_metrics"]) == 1
        decision = res["debate_termination_decision"]
        assert decision["stop_reason"] != "malformed_debate_state"

    def test_refusal_before_first_bull_leaves_zero_calls(self):
        # A caller-supplied usage already at the limit: the pre-call guard must
        # refuse before the first Bull so no optional call is made at all.
        cfg = DebateTerminationConfig.from_dict({"max_calls": 1, "max_debate_rounds": 3})
        quick = _fake_llm()
        deep = _fake_llm("Hold")
        graph = _build_graph(quick, deep, config_override=cfg)
        state = _initial_state()
        state["debate_usage"] = {"calls": 1, "tokens": 0, "seconds": 0.0, "estimated": False}
        res = graph.invoke(state)
        assert res["debate_usage"]["calls"] == 1
        assert _researcher_prompts(quick) == {"bull": False, "bear": False}
        assert res["debate_termination_decision"]["stop_reason"] == "budget_exhausted"


class TestTokenTimePreflightBoundaries:
    """Exact token/time boundaries before the first Bull and before Bear.

    Uses seeded ``debate_usage`` so the exact "remaining == reserve" and
    "remaining == reserve + next-call estimate" cases are exercised through the
    real graph and researcher nodes, not only the helper.
    """

    def _cfg(self, **overrides):
        base = {
            "max_calls": 10,
            "max_tokens": 10_000,
            "reserved_summary_tokens": 1_000,
            "next_round_estimate_tokens": 2_000,
            "max_time": 100_000.0,
            "reserved_summary_seconds": 90.0,
            "next_round_estimate_seconds": 60.0,
            "max_debate_rounds": 3,
        }
        base.update(overrides)
        return DebateTerminationConfig.from_dict(base)

    def test_before_first_bull_only_reserve_remaining_refuses_bull(self):
        cfg = self._cfg()
        quick = _fake_llm()
        deep = _fake_llm("Hold")
        graph = _build_graph(quick, deep, config_override=cfg)
        state = _initial_state()
        # remaining tokens == reserve only -> no optional call may run.
        state["debate_usage"] = {"calls": 0, "tokens": 9_000, "seconds": 0.0, "estimated": True}
        res = graph.invoke(state)
        assert _researcher_prompts(quick) == {"bull": False, "bear": False}
        assert res["debate_termination_decision"]["stop_reason"] == "budget_exhausted"
        # Usage only counted the calls actually made: no optional call, so the
        # seeded usage is unchanged (the guard never fabricated a call).
        assert res["debate_usage"]["calls"] == 0

    def test_before_first_bull_exact_boundary_admits(self):
        cfg = self._cfg()
        quick = _fake_llm()
        deep = _fake_llm("Hold")
        graph = _build_graph(quick, deep, config_override=cfg)
        state = _initial_state()
        # remaining tokens == reserve(1000) + estimate(1000) -> bull admitted.
        state["debate_usage"] = {"calls": 0, "tokens": 8_000, "seconds": 0.0, "estimated": True}
        graph.invoke(state)
        prompts = _researcher_prompts(quick)
        assert prompts["bull"] is True

    def test_before_bear_only_reserve_remaining_refuses_bear(self):
        cfg = self._cfg()
        quick = _fake_llm()
        deep = _fake_llm("Hold")
        graph = _build_graph(quick, deep, config_override=cfg)
        state = _initial_state()
        # Seed at the exact Bull boundary (remaining == reserve + estimate), so
        # the Bull is admitted; its real estimated spend then leaves less than
        # reserve + estimate, so the Bear must be refused even though tokens
        # remain (the second-review reserve-only bug).
        state["debate_usage"] = {"calls": 0, "tokens": 8_000, "seconds": 0.0, "estimated": True}
        res = graph.invoke(state)
        prompts = _researcher_prompts(quick)
        assert prompts["bull"] is True
        assert prompts["bear"] is False
        decision = res["debate_termination_decision"]
        assert decision["stop_reason"] == "budget_exhausted"
        assert decision["trace"][0]["actual"]["refused_speaker"] == "Bear"
        assert decision["trace"][0]["actual"]["estimate_basis"] == "estimated"
        assert decision["trace"][0]["actual"]["scope"] == "debate_calls_only"
        assert decision["trace"][0]["thresholds"]["next_call_estimate_tokens"] == 1_000

    def test_before_first_bull_only_reserve_seconds_refuses(self):
        cfg = self._cfg(max_tokens=10_000_000)
        quick = _fake_llm()
        deep = _fake_llm("Hold")
        graph = _build_graph(quick, deep, config_override=cfg)
        state = _initial_state()
        # remaining seconds == reserve seconds (90) only -> refused.
        state["debate_usage"] = {"calls": 0, "tokens": 0, "seconds": 99_910.0, "estimated": True}
        res = graph.invoke(state)
        assert _researcher_prompts(quick) == {"bull": False, "bear": False}
        assert res["debate_termination_decision"]["stop_reason"] == "budget_exhausted"


class TestDisabledCompatibility:
    def test_disabled_reproduces_legacy_fixed_round(self):
        cfg = DebateTerminationConfig.from_dict(
            {"enabled": False, "max_debate_rounds": 1, "max_calls": 1000}
        )
        quick = _fake_llm()
        deep = _fake_llm("Hold")
        graph = _build_graph(quick, deep, config_override=cfg)
        res = graph.invoke(_initial_state())
        assert res["debate_termination_decision"]["route"] == "summarize"
        assert res["debate_termination_decision"]["stop_reason"] == "max_rounds_reached"
        assert res["debate_usage"]["calls"] == 2

    def test_disabled_ignores_precall_limit(self):
        # Even with max_calls=1, disabled mode preserves the legacy baseline and
        # does not apply the dynamic pre-call guard (it is an opt-in policy).
        cfg = DebateTerminationConfig.from_dict({"enabled": False, "max_calls": 1})
        quick = _fake_llm()
        deep = _fake_llm("Hold")
        graph = _build_graph(quick, deep, config_override=cfg)
        res = graph.invoke(_initial_state())
        assert res["debate_usage"]["calls"] == 2


class TestSummaryReserve:
    def test_reserve_preserved_after_one_round(self):
        cfg = DebateTerminationConfig.from_dict(
            {
                "max_calls": 100,
                "max_tokens": 20_000,
                "max_time": 100_000.0,
                "reserved_summary_tokens": 8_000,
                "reserved_summary_seconds": 90.0,
                "next_round_estimate_tokens": 2_000,
                "max_debate_rounds": 5,
            }
        )
        quick = _fake_llm()
        deep = _fake_llm("Hold")
        graph = _build_graph(quick, deep, config_override=cfg)
        res = graph.invoke(_initial_state())
        used = res["debate_usage"]["tokens"]
        assert used + cfg.reserved_summary_tokens <= cfg.max_tokens

    def test_estimated_usage_is_flagged_not_claimed_exact(self):
        cfg = DebateTerminationConfig.from_dict({"max_calls": 100, "max_debate_rounds": 3})
        quick = _fake_llm()
        deep = _fake_llm("Hold")
        graph = _build_graph(quick, deep, config_override=cfg)
        res = graph.invoke(_initial_state())
        # Char-based estimates are honest estimates, never physical guarantees.
        assert res["debate_usage"]["estimated"] is True

    def test_refused_call_does_not_invoke_model(self):
        # FR-DDT-003 / NFR-BUD-001 / INV-7: a pre-call refusal routes to the
        # manager WITHOUT invoking the refused speaker's model.
        cfg = DebateTerminationConfig.from_dict({"max_calls": 1, "max_debate_rounds": 2})
        quick = _fake_llm()
        deep = _fake_llm("Hold")
        graph = _build_graph(quick, deep, config_override=cfg)
        res = graph.invoke(_initial_state())
        prompts = _researcher_prompts(quick)
        assert prompts["bull"] is True
        # Bear was refused pre-call: no Bear researcher prompt was sent.
        assert prompts["bear"] is False
        assert res["debate_termination_decision"]["stop_reason"] == "budget_exhausted"

    def test_graph_records_measured_seconds(self):
        # A real graph call records a measured elapsed time (>= 0), never the
        # char-derived time basis.
        cfg = DebateTerminationConfig.from_dict({"max_calls": 100, "max_debate_rounds": 1})
        quick = _fake_llm()
        deep = _fake_llm("Hold")
        graph = _build_graph(quick, deep, config_override=cfg)
        res = graph.invoke(_initial_state())
        usage = res["debate_usage"]
        assert usage["seconds"] >= 0.0
        assert usage["provenance"]["seconds"] in ("measured", "mixed")
