"""Phase 3B offline graph-level tests: budget wiring + evaluation-after-Bear.

No network, no paid LLM. Uses a fixed stub gate (verdict ``normal``) and a fake
LLM so the full LangGraph workflow runs deterministically. Proves that:
- every Bull/Bear researcher call increments the run-level ``debate_usage``
  (calls + deterministic token/time estimates) and writes it back to state;
- the Debate Evaluator runs only after a complete Bull->Bear pair (a single
  Bull turn is never evaluated and fails closed);
- the evaluator consumes that real usage state (never a disconnected zero
  tracker); and
- the decision trace is written JSON-safely for downstream routing.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langgraph.prebuilt import ToolNode

from tradingagents.debate.budget import empty_usage, estimate_tokens_from_chars
from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.propagation import Propagator
from tradingagents.graph.setup import GraphSetup

SYMBOL = "COF"
TARGET = "2026-05-13"

# A well-formed turn content: readable argument + deterministic marker.
_TURN = (
    "My argument here.\n"
    "DEBATE_METADATA: stance=Buy; confidence=0.7; "
    "cited=run:1; new_claims=growth|run:1;"
)

# Evidence record so a cited ID is known, High, and on-before-target.
_RECORD = {
    "evidence_id": "run:1",
    "quality_status": "High",
    "observed_at": "2026-05-01",
    "value_raw": "190",
    "metric_name": "close",
    "unit_normalized": "USD",
}


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


def _build_graph(quick, deep, *, config_override=None, gate_factory=None):
    tool_nodes = {key: ToolNode([]) for key in ("market", "social", "news", "fundamentals")}
    setup = GraphSetup(
        quick,
        deep,
        tool_nodes,
        ConditionalLogic(),
        data_quality_gate_factory=gate_factory or (lambda: _stub_gate_node()),
        debate_termination_config=config_override,
    )
    return setup.setup_graph(("market",)).compile()


def _initial_state():
    return Propagator().create_initial_state(SYMBOL, TARGET, asset_type="stock")


def _capturing_prompts(llm):
    return {c.args[0] for c in llm.invoke.call_args_list if isinstance(c.args[0], str)}


BULL_SIG = "You are a Bull Analyst advocating for investing in the "
BEAR_SIG = "You are a Bear Analyst making the case against investing in the "


class TestBuildGraph:
    def test_debate_usage_tracker_is_single_run_level_and_increments(self):
        from tradingagents.agents.researchers.bull_researcher import create_bull_researcher

        llm = _fake_llm()
        node = create_bull_researcher(llm)
        state = {
            "company_of_interest": SYMBOL,
            "investment_debate_state": {},
            "market_report": "",
            "sentiment_report": "",
            "news_report": "",
            "fundamentals_report": "",
            "asset_type": "stock",
            "data_quality_evidence_records": [_RECORD],
            "trade_date": TARGET,
            "data_quality_context": "[Data Quality Gate] Verdict: normal.",
            "data_quality_verdict": "normal",
            "debate_usage": empty_usage(),
        }
        out = node(state)
        usage = out["debate_usage"]
        # Exactly one researcher call recorded.
        assert usage["calls"] == 1
        assert usage["tokens"] > 0
        assert usage["estimated"] is True
        # Deterministic estimate for the prompt+response character count.
        prompt = llm.invoke.call_args.args[0]
        assert usage["tokens"] == estimate_tokens_from_chars(len(prompt) + len(_TURN))
        # The turn is appended to the debate state.
        turns = out["investment_debate_state"]["turns"]
        assert len(turns) == 1
        assert turns[0]["speaker"] == "Bull"

    def test_bear_researcher_increments_the_same_tracker(self):
        from tradingagents.agents.researchers.bear_researcher import create_bear_researcher

        llm = _fake_llm()
        node = create_bear_researcher(llm)
        state = {
            "company_of_interest": SYMBOL,
            "investment_debate_state": {"turns": [], "count": 0},
            "market_report": "",
            "sentiment_report": "",
            "news_report": "",
            "fundamentals_report": "",
            "asset_type": "stock",
            "data_quality_evidence_records": [_RECORD],
            "trade_date": TARGET,
            "data_quality_context": "[Data Quality Gate] Verdict: normal.",
            "data_quality_verdict": "normal",
            "debate_usage": {"calls": 1, "tokens": 100, "seconds": 5.0, "estimated": True},
        }
        out = node(state)
        assert out["debate_usage"]["calls"] == 2
        assert out["debate_usage"]["tokens"] > 100

    def test_all_researcher_prompts_carry_the_bounded_allowlist(self):
        from tradingagents.agents.researchers.bull_researcher import create_bull_researcher

        llm = _fake_llm()
        node = create_bull_researcher(llm)
        state = {
            "company_of_interest": SYMBOL,
            "investment_debate_state": {},
            "market_report": "",
            "sentiment_report": "",
            "news_report": "",
            "fundamentals_report": "",
            "asset_type": "stock",
            "data_quality_evidence_records": [_RECORD],
            "trade_date": TARGET,
            "data_quality_context": "[Data Quality Gate] Verdict: normal.",
            "data_quality_verdict": "normal",
            "debate_usage": empty_usage(),
        }
        node(state)
        prompt = llm.invoke.call_args.args[0]
        # The allowlist is embedded and lists the validated on-target evidence ID.
        assert "You may cite ONLY these validated evidence IDs" in prompt
        assert "run:1" in prompt
        # The deterministic metadata instruction is appended once.
        assert "DEBATE_METADATA:" in prompt


class TestFullGraphBudgetAndEvaluation:
    def test_evaluation_occurs_only_after_complete_bear_run(self):
        from tradingagents.debate.config import DebateTerminationConfig

        # Enough budget/rounds to reach the evaluator's dynamic rules.
        cfg = DebateTerminationConfig.from_dict(
            {"max_debate_rounds": 100, "max_calls": 1000, "max_tokens": 100000,
             "max_time": 600.0, "reserved_summary_tokens": 100, "next_round_estimate_tokens": 200}
        )
        quick = _fake_llm()
        deep = _fake_llm("Hold")
        graph = _build_graph(quick, deep, config_override=cfg)
        res = graph.invoke(_initial_state())

        # Two researcher calls (Bull then Bear) recorded on the run-level tracker.
        assert res["debate_usage"]["calls"] == 2
        assert res["debate_usage"]["estimated"] is True

        # Exactly one complete round was evaluated.
        rounds = res["investment_debate_state"]["round_metrics"]
        assert len(rounds) == 1
        assert rounds[0]["round_index"] == 1

        # The evaluation decision is present and JSON-safe.
        decision = res["debate_termination_decision"]
        assert isinstance(decision, dict)
        assert decision["route"] in ("continue", "summarize", "stop")
        assert decision["stop_reason"]
        assert isinstance(decision["trace"], list)
        assert json.dumps(decision)

        # The evaluator consumed the real (non-zero) usage, not a zero tracker.
        assert decision["trace"][1]["actual"]["used_calls"] == 2

    def test_enabled_default_round_cap_stops_after_one_round(self):
        quick = _fake_llm()
        deep = _fake_llm("Hold")
        # default config has max_debate_rounds == 1.
        graph = _build_graph(quick, deep)
        res = graph.invoke(_initial_state())
        assert res["debate_termination_decision"]
        # One complete round then routed to the Research Manager.
        assert res["debate_usage"]["calls"] == 2
        assert len(res["investment_debate_state"]["round_metrics"]) == 1

    def test_disabled_mode_preserves_legacy_count_route(self):
        from tradingagents.debate.config import DebateTerminationConfig

        cfg = DebateTerminationConfig.from_dict({"enabled": False, "max_debate_rounds": 1})
        quick = _fake_llm()
        deep = _fake_llm("Hold")
        graph = _build_graph(quick, deep, config_override=cfg)
        res = graph.invoke(_initial_state())
        decision = res["debate_termination_decision"]
        # Disabled reproduces the legacy fixed count route (count>=2*max=2). A
        # disabled evaluator does not append round metrics.
        assert decision["route"] == "summarize"
        assert decision["stop_reason"] == "max_rounds_reached"
        assert res["investment_debate_state"].get("round_metrics", []) == []


class TestEvaluatorOnlyAfterBear:
    def test_node_refuses_single_bull_before_evaluation(self):
        from tradingagents.debate.config import DebateTerminationConfig
        from tradingagents.debate.evaluator_node import create_debate_evaluator_node

        cfg = DebateTerminationConfig.from_dict({"max_debate_rounds": 100})
        node = create_debate_evaluator_node(config=cfg)
        # A single Bull turn is an incomplete pair -> fail closed, no evaluation.
        state = {
            "investment_debate_state": {
                "turns": [
                    {"speaker": "Bull", "content": "x",
                     "stance": "Buy", "confidence": 0.7,
                     "cited_evidence_ids": ["run:1"],
                     "addressed_conflict_ids": [], "new_claims": [],
                     "claim_evidence_links": [], "unresolved_questions": [],
                     "metadata_parse_status": "ok"},
                ]
            },
            "trade_date": TARGET,
            "data_quality_verdict": "normal",
            "data_quality_group_statuses": [],
            "data_quality_evidence_records": [_RECORD],
        }
        out = node(state)
        assert out["debate_termination_decision"]["stop_reason"] == "malformed_debate_state"
        # No round metrics appended for the incomplete pair.
        assert out["investment_debate_state"].get("round_metrics", []) == []
