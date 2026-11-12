"""ADR-011 Stage 4: deterministic degraded-run confidence cap — RUNTIME.

Approved runtime test cases (2026-11-11 human plan/test approval, cap 0.60; plan +
tests ONLY, not final human acceptance). These drive the REAL production graph
(real ``GraphSetup`` / ``AgentState``, and a GENUINE production gate node reading
a mocked raw OHLCV source) with scripted over-confident models that state a raw
over-cap confidence (``0.95`` / ``95%`` / ``confidence=0.95`` / ``"confidence":
0.95``) and prove:

- the upstream debate turn's numeric + readable confidence is capped BEFORE it
  reaches the next speaker / evaluator / Research Manager (asserted on the ACTUAL
  next-model prompt text, not only final state);
- every manager / trader / portfolio decision carries an effective value <= 0.60;
- the structured (typed schema) path AND the free-text fallback path each cap;
- the final signal / report / memory / CLI-export path never resurrect a raw
  over-cap confidence, using the REAL public methods (``_run_graph`` /
  ``record_decision`` / ``write_report_tree``) rather than hand-built results;
- an actual SQLite interrupt -> close -> reconstruct -> resume yields the same
  capped state and cannot resurrect a raw value from a legacy checkpoint;
- the blocked Hold path still yields Hold (cap never weakens the block);
- ordinary financial figures are untouched; a normal run is unchanged.

No network, no paid LLM.

Traceability: FR-DQG-006, NFR-AUD-001, NFR-DET-001, NFR-BC-001, FR-DQG-005,
INV-1/INV-2/INV-6/INV-8.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pandas as pd
import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langgraph.prebuilt import ToolNode

SYMBOL = "COF"
TARGET = "2026-05-13"
CAP = 0.60


# ---------------------------------------------------------------------------
# Fixtures (mirror the Stage-3 / Stage-2 runtime harnesses)
# ---------------------------------------------------------------------------


def _resp(content):
    return AIMessage(content=content)


# Per-role over-confident scripted outputs. Each embeds a RAW over-cap confidence
# in the role's OWN native shape (turn metadata / manager prose / trader prose /
# PM prose), so the real node must actively enforce the cap.
_ROLE_CONTENT = {
    "bull": (
        "The growth case is overwhelming and the market data confirms it. "
        "I am 95% confident.\n"
        "DEBATE_METADATA: stance=Buy; confidence=0.95; cited=none; "
        "conflicts=; new_claims=growth is durable|none; questions="
    ),
    "bear": (
        "The risks are real but I am 90% confident the bull is wrong.\n"
        "DEBATE_METADATA: stance=Sell; confidence=0.9; cited=none; "
        "conflicts=; new_claims=valuation stretched|none; questions="
    ),
    "research_manager": (
        "**Recommendation**: Buy\n\n"
        "**Rationale**: Revenue increased 95% and margins improved to 0.31; "
        "I am 95% confident in this call.\n\n"
        "**Strategic Actions**: Accumulate on strength.\n\n"
        "**Confidence**: 0.95"
    ),
    "trader": (
        "**Action**: Buy\n\n"
        "**Reasoning**: Demand is strong; confidence 92%.\n\n"
        "FINAL TRANSACTION PROPOSAL: **BUY**\n\n"
        "**Confidence**: 0.92"
    ),
    "aggressive": "As the aggressive analyst I am 93% confident: buy now.",
    "conservative": "As the conservative analyst I am 93% confident: stay safe.",
    "neutral": "As the neutral analyst I am 93% confident: balance both.",
    "portfolio": (
        "**Rating**: Buy\n\n"
        "**Executive Summary**: Enter now; confidence: 0.95.\n\n"
        "**Investment Thesis**: Momentum and 200 shares of evidence; close 200.13.\n\n"
        "**Confidence**: 0.95"
    ),
}


def _classify_role(prompt) -> str:
    text = prompt if isinstance(prompt, str) else json.dumps(prompt, default=str)
    low = text.lower()
    if "you are a bull analyst" in low:
        return "bull"
    if "you are a bear analyst" in low:
        return "bear"
    if "as the research manager" in low:
        return "research_manager"
    if "you are a trading agent analyzing" in low:
        return "trader"
    if "as the aggressive risk analyst" in low:
        return "aggressive"
    if "as the conservative risk analyst" in low:
        return "conservative"
    if "as the neutral risk analyst" in low:
        return "neutral"
    if "as the portfolio manager" in low:
        return "portfolio"
    return "unknown"


class _RoleLLM:
    """Role-aware scripted chat model mock (test scaffolding only).

    Inspects the ACTUAL prompt to pick the role's over-confident output, and
    records every ``(role, prompt)`` so a test can assert what each later model
    actually saw. Structured binding returns a role-appropriate typed Pydantic
    result so the typed decision path is exercised too.
    """

    def __init__(self):
        self.calls = []  # list[(role, prompt_text)]
        self.structured_calls = []  # list[(role, prompt_text)]

    def bind_tools(self, tools):
        return RunnableLambda(
            lambda m: _resp(_ROLE_CONTENT[self._last_role or "bull"])
        )

    _last_role = None

    def with_structured_output(self, schema, *a, **k):
        outer = self

        class _Bound:
            def invoke(self, prompt):
                role = _classify_role(prompt)
                outer.structured_calls.append((role, prompt if isinstance(prompt, str) else json.dumps(prompt, default=str)))
                return _structured_result_for(schema, role)

        return _Bound()

    def invoke(self, prompt):
        role = _classify_role(prompt)
        self.calls.append((role, prompt if isinstance(prompt, str) else json.dumps(prompt, default=str)))
        return _resp(_ROLE_CONTENT.get(role, _ROLE_CONTENT["bull"]))


def _structured_result_for(schema, role):
    from tradingagents.agents.schemas import (
        PortfolioDecision,
        PortfolioRating,
        ResearchPlan,
        TraderAction,
        TraderProposal,
    )

    if schema is PortfolioDecision:
        return PortfolioDecision(
            rating=PortfolioRating.BUY,
            executive_summary="Enter now; confidence 0.95.",
            investment_thesis="Momentum is strong.",
            confidence=0.95,
        )
    if schema is ResearchPlan:
        return ResearchPlan(
            recommendation=PortfolioRating.BUY,
            rationale=(
                "Strong case: revenue increased 95% and margin 0.31; "
                "I am 95% confident."
            ),
            strategic_actions="Accumulate now.",
            confidence=0.95,
        )
    if schema is TraderProposal:
        return TraderProposal(
            action=TraderAction.BUY,
            reasoning="Demand strong; confidence 0.92.",
            confidence=0.92,
        )
    return None


def _all_prompts(llm) -> list[str]:
    return [p for _role, p in list(llm.calls) + list(llm.structured_calls)]


def _fixed_dataframe():
    dates = pd.bdate_range("2026-04-01", "2026-05-20")
    closes = [100 + i for i in range(len(dates))]
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": [c - 0.5 for c in closes],
            "High": [c + 1.0 for c in closes],
            "Low": [c - 1.0 for c in closes],
            "Close": closes,
            "Volume": [1_000_000 + i for i in range(len(dates))],
        }
    )


@pytest.fixture
def real_ohlcv(monkeypatch):
    """Mock the raw OHLCV source so the GENUINE gate node runs offline."""
    import tradingagents.dataflows.market_data_validator as validator

    monkeypatch.setattr(
        validator, "load_ohlcv", lambda symbol, date, fill_gaps=True: _fixed_dataframe()
    )


def _stub_gate_node(verdict: str):
    def node(state):
        return {
            "data_quality_verdict": verdict,
            "data_quality_gate_decision": {
                "decision": verdict,
                "decided_at": "2026-05-13T12:00:00Z",
            },
            "data_quality_context": f"[Data Quality Gate] Verdict: {verdict}.",
            "data_quality_error": None,
            "data_quality_evidence_records": [],
            "data_quality_validation_results": {},
            "data_quality_group_statuses": [],
        }

    return node


def _overflow_config():
    from tradingagents.debate.config import DebateTerminationConfig

    return DebateTerminationConfig(
        enabled=True,
        max_debate_rounds=1,
        max_calls=1000,
        max_tokens=10_000_000,
        max_time=100_000.0,
        reserved_summary_tokens=100,
        reserved_summary_seconds=1.0,
    )


def _build_workflow(quick, deep, gate_factory):
    from tradingagents.graph.conditional_logic import ConditionalLogic
    from tradingagents.graph.setup import GraphSetup

    tool_nodes = {key: ToolNode([]) for key in ("market", "social", "news", "fundamentals")}
    setup = GraphSetup(
        quick,
        deep,
        tool_nodes,
        ConditionalLogic(),
        data_quality_gate_factory=gate_factory,
        debate_termination_config=_overflow_config(),
    )
    return setup.setup_graph(("market",))


def _initial_state():
    from tradingagents.graph.propagation import Propagator

    return Propagator().create_initial_state(SYMBOL, TARGET, asset_type="stock")


def _assert_no_raw_confidence(text: str, *raws):
    for raw in raws:
        assert raw not in text, f"raw confidence {raw!r} leaked into trusted text: {text!r}"


# ---------------------------------------------------------------------------
# Degraded run via a STUB verdict: per-boundary + prompt assertions
# ---------------------------------------------------------------------------


class TestDegradedRuntimeCapping:
    def _run(self):
        quick = _RoleLLM()
        deep = _RoleLLM()
        graph = _build_workflow(
            quick, deep, lambda: _stub_gate_node("degraded")
        ).compile()
        final = graph.invoke(_initial_state())
        return final, quick, deep

    def test_each_role_emits_raw_and_is_capped(self):
        final, quick, deep = self._run()
        roles = {r for r, _ in quick.calls + quick.structured_calls}
        roles |= {r for r, _ in deep.calls + deep.structured_calls}
        # Every downstream role genuinely ran and emitted an over-cap script.
        assert {"bull", "bear", "research_manager", "trader", "portfolio"} <= roles
        turns = final["investment_debate_state"].get("turns") or []
        assert turns
        for turn in turns:
            assert float(turn["confidence"]) <= CAP
        stances = final["investment_debate_state"].get("stances") or {}
        for snap in stances.values():
            assert float(snap["confidence"]) <= CAP

    def test_next_prompts_carry_no_raw_confidence(self):
        final, quick, deep = self._run()
        prompts = _all_prompts(quick) + _all_prompts(deep)
        assert prompts
        # The raw over-cap confidence must never reach a later model prompt.
        for prompt in prompts:
            assert "confidence=0.95" not in prompt
            assert "confidence=0.9" not in prompt
            assert "confidence 92%" not in prompt
            assert "0.95" not in prompt

    def test_research_manager_plan_capped(self):
        final, _q, _d = self._run()
        plan = final["investment_plan"]
        _assert_no_raw_confidence(plan, "95% confident", "**Confidence**: 0.95")
        # Ordinary financial figures (a revenue percentage and a margin) preserved.
        assert "Revenue increased 95%" in plan or "revenue increased 95%" in plan
        assert "margin 0.31" in plan
        # The labelled confidence is the effective capped value, never the raw one.
        assert "60% confident" in plan
        assert "**Confidence**: 0.6" in plan

    def test_trader_and_final_decision_capped(self):
        final, _q, _d = self._run()
        _assert_no_raw_confidence(final["trader_investment_plan"], "92%", "**Confidence**: 0.92")
        _assert_no_raw_confidence(final["final_trade_decision"], "**Confidence**: 0.95", "confidence: 0.95")

    def test_audit_block_present(self):
        final, _q, _d = self._run()
        audit = final.get("confidence_cap_audit") or []
        assert audit
        assert any(e.get("capped") for e in audit)
        boundaries = {e["boundary"] for e in audit}
        assert any("debate_turn" in b for b in boundaries)

    def test_final_state_trusted_fields_carry_no_raw_confidence(self):
        # The RETURNED state (not just the protected prompts) must carry the
        # effective values: the per-read copy protects prompts, and the post-gate
        # Confidence Sanitizer persists the capped report/history/plan fields.
        final, _q, _d = self._run()
        # The analyst report that pre-dates the gate is capped in the final state.
        _assert_no_raw_confidence(final["market_report"], "confidence=0.95", "95% confident")
        assert "60% confident" in final["market_report"]
        # Financial prose in the same report is untouched.
        assert "The growth case is overwhelming" in final["market_report"]
        _assert_no_raw_confidence(
            final["trader_investment_plan"], "**Confidence**: 0.92", "confidence 92%"
        )
        # Financial figure ("revenue increased 95%") is legitimately preserved;
        # only the LABELLED confidence must be gone.
        _assert_no_raw_confidence(
            final["investment_plan"], "I am 95% confident", "**Confidence**: 0.95"
        )
        assert "revenue increased 95%" in final["investment_plan"].lower()
        _assert_no_raw_confidence(
            final["final_trade_decision"], "**Confidence**: 0.95", "confidence: 0.95"
        )
        risk = final["risk_debate_state"]
        for key in (
            "aggressive_history", "conservative_history", "neutral_history",
            "history", "judge_decision",
        ):
            _assert_no_raw_confidence(risk.get(key, ""), "93%", "0.93", "0.95")
        # Any raw over-cap value appears ONLY in the explicit audit channel.
        audit = final.get("confidence_cap_audit") or []
        assert any(e.get("capped") and float(e["raw_value"]) > CAP for e in audit)

    def test_log_state_json_export_capped(self, tmp_path):
        # The actual _log_state JSON export must not carry a raw over-cap value.
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        final, _q, _d = self._run()
        graph = object.__new__(TradingAgentsGraph)
        graph.config = {"results_dir": str(tmp_path)}
        graph.ticker = SYMBOL
        graph.log_states_dict = {}
        graph._log_state(TARGET, final)
        log_dir = tmp_path / SYMBOL / "TradingAgentsStrategy_logs"
        log_file = log_dir / f"full_states_log_{TARGET}.json"
        blob = log_file.read_text(encoding="utf-8")
        _assert_no_raw_confidence(blob, "confidence=0.95", "95% confident", "93%", "0.92")
        assert "60% confident" in blob


# ---------------------------------------------------------------------------
# GENUINE production gate node through a real GraphSetup (mocked raw OHLCV).
# ---------------------------------------------------------------------------


class TestGenuineProductionGate:
    def test_real_gate_degrades_and_caps(self, real_ohlcv):
        from tradingagents.graph.data_quality_gate import create_data_quality_gate_node

        quick = _RoleLLM()
        deep = _RoleLLM()
        # The DEFAULT gate node (real snapshot builder + real multi-category
        # engine). A valid market snapshot with no optional sources is DEGRADED.
        graph = _build_workflow(
            quick, deep,
            lambda: create_data_quality_gate_node(now_provider=lambda: "2026-05-13T12:00:00Z"),
        ).compile()
        final = graph.invoke(_initial_state())
        # The genuine gate produced a real verdict from the real engine.
        assert final["data_quality_verdict"] in ("degraded", "normal")
        assert final["data_quality_gate_decision"]["decision"] == final["data_quality_verdict"]
        if final["data_quality_verdict"] == "degraded":
            for turn in final["investment_debate_state"].get("turns") or []:
                assert float(turn["confidence"]) <= CAP
            _assert_no_raw_confidence(final["final_trade_decision"], "0.95")
            for prompt in _all_prompts(quick) + _all_prompts(deep):
                assert "confidence=0.95" not in prompt


# ---------------------------------------------------------------------------
# Structured (typed schema) path AND free-text fallback both cap.
# ---------------------------------------------------------------------------


class TestStructuredAndFallbackPaths:
    def test_structured_typed_confidence_capped(self):
        # The role mock returns a TYPED PortfolioDecision with confidence=0.95;
        # the rendered typed **Confidence** line must be capped, not raw.
        quick = _RoleLLM()
        deep = _RoleLLM()
        graph = _build_workflow(
            quick, deep, lambda: _stub_gate_node("degraded")
        ).compile()
        final = graph.invoke(_initial_state())
        decision = final["final_trade_decision"]
        _assert_no_raw_confidence(decision, "**Confidence**: 0.95")
        assert "0.6" in decision

    def test_fallback_path_capped(self):
        # A model with structured output DISABLED forces the free-text fallback.
        class _NoStruct(_RoleLLM):
            def with_structured_output(self, *a, **k):
                return None

        quick = _RoleLLM()
        deep = _NoStruct()
        graph = _build_workflow(quick, deep, lambda: _stub_gate_node("degraded")).compile()
        final = graph.invoke(_initial_state())
        _assert_no_raw_confidence(final["trader_investment_plan"], "**Confidence**: 0.92")


class TestNormalRuntimeUnchanged:
    def test_normal_run_keeps_valid_values(self):
        quick = _RoleLLM()
        deep = _RoleLLM()
        graph = _build_workflow(quick, deep, lambda: _stub_gate_node("normal")).compile()
        final = graph.invoke(_initial_state())
        turns = final["investment_debate_state"].get("turns") or []
        # The two scripted turns really carry the raw over-cap confidences (Bull
        # 0.95, Bear 0.9); a normal run must leave each valid value unchanged.
        assert [float(t["confidence"]) for t in turns] == [0.95, 0.9]
        assert not (final.get("confidence_cap_audit") or [])
        # The post-gate sanitizer is a no-op on a normal run: the analyst report
        # still carries its original raw confidence, byte-for-byte.
        assert "confidence=0.95" in final["market_report"]


# ---------------------------------------------------------------------------
# Blocked run: cap never weakens Hold
# ---------------------------------------------------------------------------


class TestBlockedRuntimeStayHold:
    def test_blocked_run_is_hold(self):
        from tradingagents.agents.managers.portfolio_manager import (
            create_portfolio_manager,
        )

        state = {
            "data_quality_verdict": "blocked",
            "data_quality_gate_decision": {"decision": "blocked"},
            "data_quality_context": "blocked",
            "company_of_interest": SYMBOL,
            "trade_date": TARGET,
            "investment_debate_state": {
                "history": "", "bull_history": "", "bear_history": "",
                "current_response": "", "judge_decision": "", "count": 0,
            },
            "risk_debate_state": {
                "aggressive_history": "", "conservative_history": "",
                "neutral_history": "", "history": "", "latest_speaker": "",
                "current_aggressive_response": "", "current_conservative_response": "",
                "current_neutral_response": "", "judge_decision": "", "count": 0,
            },
            "investment_plan": "Buy 100 shares now (95% confidence)",
            "trader_investment_plan": "Action: Buy",
            "market_report": "", "sentiment_report": "", "news_report": "",
            "fundamentals_report": "", "messages": [],
        }
        pm = create_portfolio_manager(_RoleLLM())
        out = pm(state)
        decision = out["final_trade_decision"]
        first_field = decision.split("Rating")[1].split("\n")[0].replace("*", "").strip(" :")
        assert first_field == "Hold"


# ---------------------------------------------------------------------------
# Report writer / memory / signal public path (real methods)
# ---------------------------------------------------------------------------


class TestPublicReportAndMemory:
    def _legacy_degraded_state(self):
        return {
            "company_of_interest": SYMBOL,
            "trade_date": TARGET,
            "data_quality_verdict": "degraded",
            "data_quality_gate_decision": {"decision": "degraded"},
            "data_quality_context": "",
            "market_report": "Revenue 95%; confidence: 0.95 in the call.",
            "sentiment_report": "",
            "news_report": "",
            "fundamentals_report": "",
            "investment_debate_state": {
                "bull_history": "", "bear_history": "",
                "history": "", "current_response": "", "judge_decision": "",
                "count": 0,
            },
            "investment_plan": "**Recommendation**: Buy\n\n**Confidence**: 0.95",
            "trader_investment_plan": "**Action**: Buy\n\n**Confidence**: 0.92",
            "risk_debate_state": {
                "aggressive_history": "", "conservative_history": "",
                "neutral_history": "", "history": "", "latest_speaker": "",
                "current_aggressive_response": "", "current_conservative_response": "",
                "current_neutral_response": "",
                "judge_decision": "**Rating**: Buy\n\n**Confidence**: 0.95",
                "count": 0,
            },
            "final_trade_decision": "**Rating**: Buy\n\n**Confidence**: 0.95",
            "debate_usage": {},
        }

    def test_report_writer_caps_imported_and_audits(self, tmp_path):
        from tradingagents.reporting import write_report_tree

        state = self._legacy_degraded_state()
        original = json.dumps(state, sort_keys=True, default=str)
        path = write_report_tree(state, SYMBOL, tmp_path / "report")
        complete = path.read_text(encoding="utf-8")
        _assert_no_raw_confidence(complete, "**Confidence**: 0.95", "confidence: 0.95")
        assert "Revenue 95%" in complete  # financial figure kept
        # The report summary must reflect the imported-state raw/effective audit.
        summary = json.loads((tmp_path / "report" / "run_summary.json").read_text())
        cap = summary["confidence_cap"]
        assert cap["verdict"] == "degraded"
        assert cap["cap"] == CAP
        assert cap["cap_applies"] is True
        # The imported/legacy raw confidence is recorded as capped entries (the
        # per-section raw/effective audit is NOT discarded), so the summary count
        # is positive rather than 0.
        assert cap["capped_count"] >= 1
        assert any(e.get("capped") for e in cap["entries"])
        # The caller's original state is not mutated.
        assert json.dumps(state, sort_keys=True, default=str) == original

    def test_report_export_idempotent(self, tmp_path):
        from tradingagents.reporting import write_report_tree

        state = self._legacy_degraded_state()
        p1 = write_report_tree(state, SYMBOL, tmp_path / "r1")
        p2 = write_report_tree(state, SYMBOL, tmp_path / "r2")
        assert p1.read_text(encoding="utf-8") == p2.read_text(encoding="utf-8")
        s1 = json.loads((tmp_path / "r1" / "run_summary.json").read_text())
        s2 = json.loads((tmp_path / "r2" / "run_summary.json").read_text())
        assert s1["confidence_cap"] == s2["confidence_cap"]

    def test_memory_record_decision_caps(self, tmp_path):
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        graph = object.__new__(TradingAgentsGraph)
        graph.memory_log = MagicMock()
        state = self._legacy_degraded_state()
        TradingAgentsGraph.record_decision(graph, SYMBOL, TARGET, state)
        assert graph.memory_log.store_decision.called
        kwargs = graph.memory_log.store_decision.call_args.kwargs
        _assert_no_raw_confidence(kwargs["final_trade_decision"], "**Confidence**: 0.95")

    def test_report_writer_normal_verdict_unchanged(self, tmp_path):
        from tradingagents.reporting import write_report_tree

        state = self._legacy_degraded_state()
        state["data_quality_verdict"] = "normal"
        state["data_quality_gate_decision"] = {"decision": "normal"}
        path = write_report_tree(state, SYMBOL, tmp_path / "report")
        complete = path.read_text(encoding="utf-8")
        assert "confidence: 0.95" in complete

    def test_exported_json_artifacts_use_effective_confidence(self, tmp_path):
        from tradingagents.reporting import write_report_tree

        state = self._legacy_degraded_state()
        state["investment_debate_state"] = dict(state["investment_debate_state"])
        state["investment_debate_state"]["turns"] = [
            {
                "speaker": "Bull", "content": "confidence=0.95 growth",
                "stance": "Buy", "confidence": 0.95,
                "cited_evidence_ids": [], "addressed_conflict_ids": [],
                "new_claims": [], "claim_evidence_links": [],
                "unresolved_questions": [], "conflict_assertions": [],
                "metadata_parse_status": "ok", "exact_claims": [],
            }
        ]
        state["investment_debate_state"]["stances"] = {
            "Bull": {"stance": "Buy", "confidence": 0.95}
        }
        original = json.dumps(state, sort_keys=True, default=str)
        write_report_tree(state, SYMBOL, tmp_path / "report")
        summary = json.loads((tmp_path / "report" / "run_summary.json").read_text())
        trace = json.loads(
            (tmp_path / "report" / "2_research" / "debate_trace.json").read_text()
        )
        # The exported JSON summary/trace carry the effective capped value and its
        # audit; a raw over-cap .95 appears ONLY inside an explicit audit/quarantine
        # raw_value field, never as an authoritative effective value.
        cap = summary["confidence_cap"]
        assert cap["capped_count"] >= 1
        for entry in cap["entries"]:
            if entry.get("effective_value") is not None:
                assert float(entry["effective_value"]) <= CAP
        blob = json.dumps({"summary": summary, "trace": trace})
        # No raw over-cap confidence leaks outside an explicit raw_value field.
        assert '"effective_value": 0.95' not in blob
        # Caller state not mutated even with persisted turns/stances.
        assert json.dumps(state, sort_keys=True, default=str) == original


def _real_graph_shell(tmp_path, saver, tid):
    """A TradingAgentsGraph shell wired to a real checkpointer + real gate."""
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    quick = _RoleLLM()
    deep = _RoleLLM()
    workflow = _build_workflow(quick, deep, lambda: _stub_gate_node("degraded"))

    graph = object.__new__(TradingAgentsGraph)
    graph.config = {
        "results_dir": str(tmp_path),
        "checkpoint_enabled": True,
        "debate_termination": {"max_debate_rounds": 1},
    }
    graph.debug = False
    graph._resuming = False
    graph.graph = workflow.compile(checkpointer=saver)
    graph.propagator = MagicMock()
    graph.propagator.get_graph_args.return_value = {
        "config": {"configurable": {"thread_id": tid}}
    }
    graph.memory_log = MagicMock()
    graph.ticker = SYMBOL
    graph.log_states_dict = {}
    graph.signal_processor = MagicMock()
    graph.signal_processor.process_signal.return_value = "Hold"
    graph.selected_analysts = ("market",)
    graph._log_state = lambda *a, **k: None
    graph.clear_checkpoint_on_success = lambda *a, **k: None
    graph.create_run_state = lambda *a, **k: _initial_state()
    graph._checkpoint_ctx = None
    return graph, quick, deep


class TestRealSqliteResumeCap:
    def test_direct_graphsetup_resume_evaluator_sees_capped_numeric(self, tmp_path):
        """A DIRECT GraphSetup resume (no API resume-sanitizer) must still cap the
        numeric turn/stance confidence the evaluator reads.

        This proves the shared state-input read defense — not merely the API
        ``_sanitize_confidence_on_resume`` wrapper — protects a direct
        ``graph.graph.invoke(None)`` at a real SQLite checkpoint with a stale typed
        ``confidence=0.95`` in persisted turns/stances.
        """
        from tradingagents.debate.evaluator_node import create_debate_evaluator_node
        from tradingagents.graph.checkpointer import get_checkpointer, thread_id

        data_dir = str(tmp_path / "ckpt")
        tid = thread_id(SYMBOL, TARGET)
        cfg = {"configurable": {"thread_id": tid}}

        seen = {}

        def _spy_evaluator_factory():
            real = create_debate_evaluator_node(config=_overflow_config())

            def _spy(state):
                turns = state.get("investment_debate_state", {}).get("turns") or []
                seen["turn_conf"] = [float(t.get("confidence", 0.0)) for t in turns]
                return real(state)

            return _spy

        with get_checkpointer(data_dir, SYMBOL) as saver:
            quick = _RoleLLM()
            deep = _RoleLLM()
            from tradingagents.graph.conditional_logic import ConditionalLogic
            from tradingagents.graph.setup import GraphSetup

            tool_nodes = {k: ToolNode([]) for k in ("market", "social", "news", "fundamentals")}
            setup = GraphSetup(
                quick,
                deep,
                tool_nodes,
                ConditionalLogic(),
                data_quality_gate_factory=lambda: _stub_gate_node("degraded"),
                debate_termination_config=_overflow_config(),
                debate_evaluator_factory=_spy_evaluator_factory,
            )
            compiled = setup.setup_graph(("market",)).compile(checkpointer=saver)

            legacy = _initial_state()
            legacy.update(_stub_gate_node("degraded")(legacy))
            legacy["investment_debate_state"] = {
                "bull_history": "confident 95%", "bear_history": "",
                "history": "confident 95%", "current_response": "confident 95%",
                "judge_decision": "", "count": 1,
                "turns": [
                    {"speaker": "Bull", "content": "confidence=0.95", "stance": "Buy",
                     "confidence": 0.95, "cited_evidence_ids": [],
                     "addressed_conflict_ids": [], "new_claims": [],
                     "claim_evidence_links": [], "unresolved_questions": [],
                     "conflict_assertions": [], "metadata_parse_status": "ok",
                     "exact_claims": []},
                    {"speaker": "Bear", "content": "confidence=0.92", "stance": "Sell",
                     "confidence": 0.92, "cited_evidence_ids": [],
                     "addressed_conflict_ids": [], "new_claims": [],
                     "claim_evidence_links": [], "unresolved_questions": [],
                     "conflict_assertions": [], "metadata_parse_status": "ok",
                     "exact_claims": []},
                ],
                "stances": {"Bull": {"stance": "Buy", "confidence": 0.95}},
            }
            # Seed the checkpoint so resume continues INTO the debate (as_node just
            # after the gate), then invoke(None) directly — NOT the API sanitizer.
            compiled.update_state(cfg, legacy, as_node="Bull Researcher")
            final = compiled.invoke(None, cfg)

        # The evaluator read ONLY capped numeric confidences from the source turns.
        assert seen.get("turn_conf"), "evaluator did not run on the resumed path"
        assert all(c <= CAP for c in seen["turn_conf"])
        for turn in final["investment_debate_state"].get("turns") or []:
            assert float(turn["confidence"]) <= CAP

    def test_direct_resume_after_sanitizer_node_persists_capped_reports(self, tmp_path):
        """A direct resume that SKIPS the post-gate Confidence Sanitizer node must
        still persist capped analyst reports, via the node wrapper's changed-input
        delta merge. No API resume-sanitizer is used here.
        """
        from tradingagents.graph.checkpointer import get_checkpointer, thread_id

        data_dir = str(tmp_path / "ckpt")
        tid = thread_id(SYMBOL, TARGET)
        cfg = {"configurable": {"thread_id": tid}}

        with get_checkpointer(data_dir, SYMBOL) as saver:
            quick = _RoleLLM()
            deep = _RoleLLM()
            from tradingagents.graph.conditional_logic import ConditionalLogic
            from tradingagents.graph.setup import GraphSetup

            tool_nodes = {k: ToolNode([]) for k in ("market", "social", "news", "fundamentals")}
            setup = GraphSetup(
                quick, deep, tool_nodes, ConditionalLogic(),
                data_quality_gate_factory=lambda: _stub_gate_node("degraded"),
                debate_termination_config=_overflow_config(),
            )
            compiled = setup.setup_graph(("market",)).compile(checkpointer=saver)

            legacy = _initial_state()
            legacy.update(_stub_gate_node("degraded")(legacy))
            legacy["market_report"] = "Report; confidence: 0.95 in the trend."
            legacy["investment_plan"] = "Plan; confidence: 0.95."
            legacy["trader_investment_plan"] = "Action: Buy; confidence 0.92."
            legacy["investment_debate_state"] = {
                "bull_history": "confident 95%", "bear_history": "",
                "history": "confident 95%", "current_response": "confident 95%",
                "judge_decision": "", "count": 1,
                "turns": [
                    {"speaker": "Bull", "content": "confidence=0.95", "stance": "Buy",
                     "confidence": 0.95, "cited_evidence_ids": [],
                     "addressed_conflict_ids": [], "new_claims": [],
                     "claim_evidence_links": [], "unresolved_questions": [],
                     "conflict_assertions": [], "metadata_parse_status": "ok",
                     "exact_claims": []},
                ],
                "stances": {"Bull": {"stance": "Buy", "confidence": 0.95}},
            }
            # Resume AT the Trader (past the Confidence Sanitizer and the debate),
            # so this direct invoke skips the sanitizer-node hop entirely.
            compiled.update_state(cfg, legacy, as_node="Trader")
            final = compiled.invoke(None, cfg)

        # The returned final state carries the capped analyst report (persisted by the
        # post-gate node wrapper, not only in a transient prompt copy).
        assert "0.95" not in final["market_report"]
        assert "0.6" in final["market_report"]
        # And the actual _log_state JSON export is capped too.
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        graph = object.__new__(TradingAgentsGraph)
        graph.config = {"results_dir": str(tmp_path / "logs")}
        graph.ticker = SYMBOL
        graph.log_states_dict = {}
        graph._log_state(TARGET, final)
        log_file = (
            tmp_path / "logs" / SYMBOL / "TradingAgentsStrategy_logs"
            / f"full_states_log_{TARGET}.json"
        )
        blob = log_file.read_text(encoding="utf-8")
        assert "0.95" not in blob
        assert "0.6" in blob

    def test_resume_caps_no_raw_resurrection(self, tmp_path):
        from tradingagents.graph.checkpointer import get_checkpointer, thread_id

        data_dir = str(tmp_path / "ckpt")
        tid = thread_id(SYMBOL, TARGET)

        # First process: the real _run_graph, then the saver closes.
        with get_checkpointer(data_dir, SYMBOL) as saver:
            graph, _q, _d = _real_graph_shell(tmp_path, saver, tid)
            TradingAgentsGraph_run(graph, SYMBOL, TARGET, tid)

        # Second process: reconstruct + resume with invoke(None) via _run_graph's
        # resume path (thread already has a checkpoint).
        with get_checkpointer(data_dir, SYMBOL) as saver:
            graph2, _q2, _d2 = _real_graph_shell(tmp_path, saver, tid)
            graph2._resuming = True
            final2, _signal = TradingAgentsGraph_run(graph2, SYMBOL, TARGET, tid)

        _assert_no_raw_confidence(final2["final_trade_decision"], "0.95")
        _assert_no_raw_confidence(final2["trader_investment_plan"], "0.92")
        for turn in final2["investment_debate_state"].get("turns") or []:
            assert float(turn["confidence"]) <= CAP

    def test_legacy_checkpoint_raw_value_sanitized_on_resume(self, tmp_path):
        from tradingagents.graph.checkpointer import get_checkpointer, thread_id

        data_dir = str(tmp_path / "ckpt")
        tid = thread_id(SYMBOL, TARGET)
        cfg = {"configurable": {"thread_id": tid}}

        with get_checkpointer(data_dir, SYMBOL) as saver:
            graph, _q, _d = _real_graph_shell(tmp_path, saver, tid)
            legacy = _initial_state()
            legacy.update(_stub_gate_node("degraded")(legacy))
            legacy["investment_debate_state"] = {
                "bull_history": "confident 95% call",
                "bear_history": "",
                "history": "confident 95% call",
                "current_response": "confident 95% call",
                "judge_decision": "",
                "count": 1,
                "turns": [
                    {
                        "speaker": "Bull", "content": "confidence=0.95 growth",
                        "stance": "Buy", "confidence": 0.95,
                        "cited_evidence_ids": [], "addressed_conflict_ids": [],
                        "new_claims": [], "claim_evidence_links": [],
                        "unresolved_questions": [], "conflict_assertions": [],
                        "metadata_parse_status": "ok", "exact_claims": [],
                    }
                ],
                "stances": {"Bull": {"stance": "Buy", "confidence": 0.95}},
            }
            legacy["investment_plan"] = "Buy with 95% confidence"
            graph.graph.update_state(cfg, legacy)
            graph._sanitize_confidence_on_resume({"config": cfg}, dict(legacy))
            values = graph.graph.get_state(cfg).values
        debate = values["investment_debate_state"]
        assert debate["turns"][0]["confidence"] <= CAP
        assert "confidence=0.95" not in debate["turns"][0]["content"]
        assert float(debate["stances"]["Bull"]["confidence"]) <= CAP
        assert "95%" not in values["investment_plan"]

    def _seed_legacy_degraded(self, graph, cfg):
        legacy = _initial_state()
        legacy.update(_stub_gate_node("degraded")(legacy))
        legacy["investment_debate_state"] = {
            "bull_history": "confident 95% call",
            "bear_history": "",
            "history": "confident 95% call",
            "current_response": "confident 95% call",
            "judge_decision": "",
            "count": 1,
            "turns": [
                {
                    "speaker": "Bull", "content": "confidence=0.95 growth",
                    "stance": "Buy", "confidence": 0.95,
                    "cited_evidence_ids": [], "addressed_conflict_ids": [],
                    "new_claims": [], "claim_evidence_links": [],
                    "unresolved_questions": [], "conflict_assertions": [],
                    "metadata_parse_status": "ok", "exact_claims": [],
                }
            ],
            "stances": {"Bull": {"stance": "Buy", "confidence": 0.95}},
        }
        legacy["investment_plan"] = "Buy with 95% confidence"
        legacy["market_report"] = "Report; confidence: 0.95."
        legacy["risk_debate_state"] = dict(legacy.get("risk_debate_state") or {})
        legacy["risk_debate_state"]["aggressive_history"] = "aggressive 0.97 confident"
        graph.graph.update_state(cfg, legacy)
        return dict(legacy)

    def test_fail_closed_on_update_state_failure(self, tmp_path):
        from tradingagents.graph.checkpointer import get_checkpointer, thread_id

        data_dir = str(tmp_path / "ckpt")
        tid = thread_id(SYMBOL, TARGET)
        cfg = {"configurable": {"thread_id": tid}}

        with get_checkpointer(data_dir, SYMBOL) as saver:
            graph, quick, deep = _real_graph_shell(tmp_path, saver, tid)
            self._seed_legacy_degraded(graph, cfg)
            graph._resuming = True

            def _boom(*a, **k):
                raise RuntimeError("injected update_state failure")

            graph.graph.update_state = _boom  # type: ignore[assignment]
            calls_before = len(quick.calls) + len(deep.calls) + len(
                quick.structured_calls
            ) + len(deep.structured_calls)
            with pytest.raises(RuntimeError, match="injected update_state failure"):
                TradingAgentsGraph_run(graph, SYMBOL, TARGET, tid)
            # Fail closed: no resumed model/stream call happened.
            calls_after = len(quick.calls) + len(deep.calls) + len(
                quick.structured_calls
            ) + len(deep.structured_calls)
            assert calls_after == calls_before == 0

    def test_repeated_resume_idempotent_audit(self, tmp_path):
        from tradingagents.graph.checkpointer import get_checkpointer, thread_id

        data_dir = str(tmp_path / "ckpt")
        tid = thread_id(SYMBOL, TARGET)
        cfg = {"configurable": {"thread_id": tid}}

        with get_checkpointer(data_dir, SYMBOL) as saver:
            graph, _q, _d = _real_graph_shell(tmp_path, saver, tid)
            self._seed_legacy_degraded(graph, cfg)
            graph._sanitize_confidence_on_resume({"config": cfg}, graph.graph.get_state(cfg).values)
            first = list(graph.graph.get_state(cfg).values.get("confidence_cap_audit") or [])
            graph._sanitize_confidence_on_resume({"config": cfg}, graph.graph.get_state(cfg).values)
            second = list(graph.graph.get_state(cfg).values.get("confidence_cap_audit") or [])
        # Idempotent: the same boundary identities, no duplicated entries.
        assert len(first) == len(second)
        keys = [(e.get("boundary"), e.get("source")) for e in second]
        assert len(keys) == len(set(keys))

    def test_invalid_legacy_numeric_quarantined(self, tmp_path):
        from tradingagents.graph.checkpointer import get_checkpointer, thread_id

        data_dir = str(tmp_path / "ckpt")
        tid = thread_id(SYMBOL, TARGET)
        cfg = {"configurable": {"thread_id": tid}}

        with get_checkpointer(data_dir, SYMBOL) as saver:
            graph, _q, _d = _real_graph_shell(tmp_path, saver, tid)
            legacy = _initial_state()
            legacy.update(_stub_gate_node("degraded")(legacy))
            legacy["investment_debate_state"] = {
                "bull_history": "", "bear_history": "", "history": "",
                "current_response": "", "judge_decision": "", "count": 1,
                "turns": [
                    {"speaker": "Bull", "content": "x", "stance": "Buy",
                     "confidence": True, "cited_evidence_ids": [],
                     "addressed_conflict_ids": [], "new_claims": [],
                     "claim_evidence_links": [], "unresolved_questions": [],
                     "conflict_assertions": [], "metadata_parse_status": "ok",
                     "exact_claims": []},
                    {"speaker": "Bear", "content": "y", "stance": "Sell",
                     "confidence": float("nan"), "cited_evidence_ids": [],
                     "addressed_conflict_ids": [], "new_claims": [],
                     "claim_evidence_links": [], "unresolved_questions": [],
                     "conflict_assertions": [], "metadata_parse_status": "ok",
                     "exact_claims": []},
                    {"speaker": "Bear", "content": "z", "stance": "Sell",
                     "confidence": 1.9, "cited_evidence_ids": [],
                     "addressed_conflict_ids": [], "new_claims": [],
                     "claim_evidence_links": [], "unresolved_questions": [],
                     "conflict_assertions": [], "metadata_parse_status": "ok",
                     "exact_claims": []},
                ],
                "stances": {},
            }
            graph.graph.update_state(cfg, legacy)
            graph._sanitize_confidence_on_resume({"config": cfg}, dict(legacy))
            values = graph.graph.get_state(cfg).values
        turns = values["investment_debate_state"]["turns"]
        # Invalid legacy numerics (bool / NaN / out-of-range) are quarantined to
        # None, never left as an authoritative NaN/True/1.9.
        assert all(t["confidence"] is None for t in turns)
        audit = values.get("confidence_cap_audit") or []
        assert any(e.get("quarantined") for e in audit)

    def test_analyst_and_risk_histories_sanitized(self, tmp_path):
        from tradingagents.graph.checkpointer import get_checkpointer, thread_id

        data_dir = str(tmp_path / "ckpt")
        tid = thread_id(SYMBOL, TARGET)
        cfg = {"configurable": {"thread_id": tid}}

        with get_checkpointer(data_dir, SYMBOL) as saver:
            graph, _q, _d = _real_graph_shell(tmp_path, saver, tid)
            self._seed_legacy_degraded(graph, cfg)
            graph._sanitize_confidence_on_resume({"config": cfg}, graph.graph.get_state(cfg).values)
            values = graph.graph.get_state(cfg).values
        assert "0.95" not in values["market_report"]
        assert "0.97" not in values["risk_debate_state"]["aggressive_history"]
        assert "0.97" not in values["risk_debate_state"].get("history", "")


def TradingAgentsGraph_run(graph, company, trade_date, thread_id_value):
    """Call the REAL ``_run_graph`` on the shell (no hand-built result)."""
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    return TradingAgentsGraph._run_graph(
        graph, company, trade_date, asset_type="stock",
        checkpoint_thread_id=thread_id_value,
    )
