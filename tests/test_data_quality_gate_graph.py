"""Phase 3A offline tests: Data Quality Gate wired into the LangGraph workflow.

No network, no paid LLM. Uses a fixed monkeypatched snapshot, a fake LLM, and
an injectable gate node (or a stub gate returning a chosen verdict).

Covers, per the authoritative design:
- normal gate -> routes to Bull Researcher;
- degraded gate -> routes to Bull Researcher and the prompt carries explicit
  restrictions;
- blocked gate -> routes to Research Manager and no Bull/Bear node is called;
- gate node exception -> fail-closed blocked (never routes as normal);
- missing/malformed gate state -> routed blocked to Research Manager;
- gate outputs are JSON-serializable and deterministic for a fixed snapshot;
- graph topology places Data Quality Gate after the last selected analyst for
  several analyst selections;
- existing debate/risk route maps remain intact.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langgraph.prebuilt import ToolNode

import tradingagents.dataflows.market_data_validator as validator
from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.data_quality_gate import (
    GATE_CONTEXT_KEY,
    GATE_DECISION_KEY,
    GATE_GROUPS_KEY,
    GATE_OPTIONAL_EVIDENCE_KEY,
    GATE_VERDICT_KEY,
    build_gate_context,
    build_gate_run_id,
    create_data_quality_gate_node,
)
from tradingagents.graph.propagation import Propagator
from tradingagents.graph.setup import (
    DEBATE_PATH_MAP,
    GATE_PATH_MAP,
    RISK_ANALYSIS_PATH_MAP,
    GraphSetup,
)

SYMBOL = "COF"
TARGET = "2026-05-13"
FETCHED = "2026-05-13T12:00:00Z"


# ---------------------------------------------------------------------------
# Deterministic fixed snapshot
# ---------------------------------------------------------------------------


def _fixed_dataframe() -> pd.DataFrame:
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
def fixed_snapshot(monkeypatch):
    """Monkeypatch ``load_ohlcv`` so the gate and validator never touch yfinance."""
    monkeypatch.setattr(validator, "load_ohlcv", lambda s, d, fill_gaps=True: _fixed_dataframe())


def _stub_gate_node(verdict: str, context: str | None = None):
    """A gate node that returns a chosen verdict (for full-graph routing tests)."""
    resolved_context = context if context is not None else f"[Data Quality Gate] Verdict: {verdict}."

    def node(state: dict[str, Any]) -> dict[str, Any]:
        return {
            GATE_VERDICT_KEY: verdict,
            GATE_DECISION_KEY: {"decision": verdict},
            GATE_CONTEXT_KEY: resolved_context,
            "data_quality_error": None,
            "data_quality_evidence_records": [],
            "data_quality_validation_results": {},
            "data_quality_group_statuses": [],
        }

    return node


# ---------------------------------------------------------------------------
# Fake LLM: analysts return AIMessages; everything else returns content.
# ---------------------------------------------------------------------------


def _fake_llm(content: str = "Buy"):
    llm = MagicMock()
    # Structured agents fall back to free text (no real schema binding).
    llm.with_structured_output = MagicMock(return_value=None)
    llm.invoke = MagicMock(return_value=MagicMock(content=content))
    bt = RunnableLambda(lambda m: AIMessage(content=content, tool_calls=[]))
    llm.bind_tools = MagicMock(return_value=bt)
    return llm


def _build_graph(quick, deep, gate_factory=None, analysts=("market",)):
    tool_nodes = {
        key: ToolNode([])
        for key in ("market", "social", "news", "fundamentals")
    }
    setup = GraphSetup(
        quick,
        deep,
        tool_nodes,
        ConditionalLogic(),
        data_quality_gate_factory=gate_factory,
    )
    workflow = setup.setup_graph(analysts)
    return workflow.compile()


def _initial_state():
    return Propagator().create_initial_state(SYMBOL, TARGET, asset_type="stock")


# ---------------------------------------------------------------------------
# Router unit tests
# ---------------------------------------------------------------------------


class TestGateRouter:
    @pytest.mark.parametrize("verdict", ["normal", "degraded"])
    def test_normal_and_degraded_route_to_bull_researcher(self, verdict):
        logic = ConditionalLogic()
        state = {"data_quality_verdict": verdict, "data_quality_gate_decision": {"decision": verdict}}
        assert logic.should_continue_after_data_gate(state) == "Bull Researcher"

    def test_blocked_routes_to_research_manager(self):
        logic = ConditionalLogic()
        state = {
            "data_quality_verdict": "blocked",
            "data_quality_gate_decision": {"decision": "blocked"},
        }
        assert logic.should_continue_after_data_gate(state) == "Research Manager"

    def test_missing_verdict_routes_blocked(self):
        logic = ConditionalLogic()
        assert logic.should_continue_after_data_gate({}) == "Research Manager"

    def test_malformed_verdict_routes_blocked(self):
        logic = ConditionalLogic()
        for bad in ("", "unknown", "normal!", 12345, None):
            state = {
                "data_quality_verdict": bad,
                "data_quality_gate_decision": {"decision": bad},
            }
            assert logic.should_continue_after_data_gate(state) == "Research Manager"

    def test_malformed_decision_routes_blocked(self):
        logic = ConditionalLogic()
        # A non-dict gate decision fails closed; a genuinely malformed gate with
        # a missing decision also blocks. The verdict string alone being
        # "normal" does not matter when the decision object itself is malformed.
        missing = {"data_quality_verdict": "normal"}
        assert logic.should_continue_after_data_gate(missing) == "Research Manager"
        non_dict = {"data_quality_verdict": "normal", "data_quality_gate_decision": "x"}
        assert logic.should_continue_after_data_gate(non_dict) == "Research Manager"

    @pytest.mark.parametrize("invalid_decision", [{}, {"something": "else"}, {"decision": None}])
    def test_empty_or_missing_decision_fails_closed(self, invalid_decision):
        logic = ConditionalLogic()
        state = {"data_quality_verdict": "normal", "data_quality_gate_decision": invalid_decision}
        assert logic.should_continue_after_data_gate(state) == "Research Manager"

    def test_invalid_decision_value_fails_closed(self):
        logic = ConditionalLogic()
        state = {
            "data_quality_verdict": "normal",
            "data_quality_gate_decision": {"decision": "unknown", "some": "field"},
        }
        assert logic.should_continue_after_data_gate(state) == "Research Manager"

    def test_mismatched_decision_and_verdict_fails_closed(self):
        logic = ConditionalLogic()
        # A normal verdict with a blocked (or degraded) decision object is
        # inconsistent gate state and must fail closed, never route as normal.
        for verdict, decision_value in (
            ("normal", "blocked"),
            ("blocked", "normal"),
            ("normal", "degraded"),
            ("degraded", "normal"),
            ("blocked", "degraded"),
        ):
            state = {
                "data_quality_verdict": verdict,
                "data_quality_gate_decision": {"decision": decision_value},
            }
            assert logic.should_continue_after_data_gate(state) == "Research Manager"

    def test_matching_normal_or_degraded_routes_to_bull(self):
        logic = ConditionalLogic()
        for verdict in ("normal", "degraded"):
            state = {
                "data_quality_verdict": verdict,
                "data_quality_gate_decision": {"decision": verdict, "decided_at": "2026-05-13T12:00:00Z"},
            }
            assert logic.should_continue_after_data_gate(state) == "Bull Researcher"

    def test_gate_path_map_is_complete(self):
        logic = ConditionalLogic()
        returns = {
            logic.should_continue_after_data_gate(s)
            for s in (
                {"data_quality_verdict": "normal", "data_quality_gate_decision": {"decision": "normal"}},
                {"data_quality_verdict": "degraded", "data_quality_gate_decision": {"decision": "degraded"}},
                {"data_quality_verdict": "blocked", "data_quality_gate_decision": {"decision": "blocked"}},
                {"data_quality_verdict": "normal", "data_quality_gate_decision": {}},
                {},
            )
        }
        assert returns <= set(GATE_PATH_MAP)
        assert "Bull Researcher" in returns
        assert "Research Manager" in returns


# ---------------------------------------------------------------------------
# Gate node: determinism, JSON-safety, exception fail-closed
# ---------------------------------------------------------------------------


class TestGateNode:
    def test_default_gate_outputs_json_serializable_and_deterministic(self, fixed_snapshot):
        node = create_data_quality_gate_node(now_provider=lambda: FETCHED)
        a = node({"company_of_interest": SYMBOL, "trade_date": TARGET, "asset_type": "stock"})
        b = node({"company_of_interest": SYMBOL, "trade_date": TARGET, "asset_type": "stock"})
        # The Stage 2 multi-category default: with a healthy market snapshot and
        # NO structured optional-category evidence, the optional categories are
        # unavailable and degrade the run to ``degraded`` (policy 2.0).
        assert a["data_quality_verdict"] == "degraded"
        assert json.loads(json.dumps(a)), "gate outputs must be JSON-serializable"
        # Deterministic gate surfaces: verdict, decision, group statuses, context
        # (the evidence record's ``fetched_at`` carries upstream snapshot clock
        # time, so it is not part of the gate's deterministic decision surface).
        assert a["data_quality_verdict"] == b["data_quality_verdict"]
        assert a["data_quality_gate_decision"] == b["data_quality_gate_decision"]
        assert a["data_quality_group_statuses"] == b["data_quality_group_statuses"]
        assert a["data_quality_context"] == b["data_quality_context"]
        # The gate emits one group per evaluated category (market + optional).
        cats = {g["category"]: g["quality_status"] for g in a["data_quality_group_statuses"]}
        assert set(cats) == {"market", "fundamentals", "news", "sentiment"}
        assert cats["market"] in ("High", "Medium", "Low")  # validated, never invented
        for optional in ("fundamentals", "news", "sentiment"):
            assert cats[optional] == "Low", "absent optional evidence degrades, never fabricates"
        assert a["data_quality_gate_decision"]["policy_version"] == "2.0"
        # Stable deterministic run id + evidence ids.
        assert build_gate_run_id(TARGET, "COF") == f"{TARGET}/COF"

    def test_gate_node_exception_fails_closed_to_blocked(self):
        def boom(*args, **kwargs):
            raise RuntimeError("vendor exploded")

        node = create_data_quality_gate_node(snapshot_builder=boom)
        out = node({"company_of_interest": SYMBOL, "trade_date": TARGET, "asset_type": "stock"})
        assert out["data_quality_verdict"] == "blocked"
        assert "Gate exception" in out["data_quality_error"]
        assert "blocked" in out["data_quality_context"]
        # Never a normal continuation.
        assert out["data_quality_gate_decision"]["decision"] == "blocked"

    def test_gate_node_missing_symbol_fails_closed(self):
        node = create_data_quality_gate_node()
        out = node({"company_of_interest": "", "trade_date": TARGET})
        assert out["data_quality_verdict"] == "blocked"
        assert "Missing symbol or trade date" in out["data_quality_error"]

    def test_gate_node_now_provider_failure_fails_closed_to_blocked(self):
        # The injected clock is itself the failing component. The gate must
        # convert this into a serializable blocked output, use a deterministic
        # safe fallback timestamp, and never re-call the same failing provider.
        calls = []

        def broken_now():
            calls.append(True)
            raise RuntimeError("clock provider exploded")

        node = create_data_quality_gate_node(now_provider=broken_now)
        out = node({"company_of_interest": SYMBOL, "trade_date": TARGET, "asset_type": "stock"})
        assert out["data_quality_verdict"] == "blocked"
        assert out["data_quality_gate_decision"]["decision"] == "blocked"
        # The failure handler must not have re-called the failing provider.
        assert len(calls) == 1
        # Deterministic safe fallback timestamp is used, and the output is JSON.
        assert out["data_quality_gate_decision"]["decided_at"] == "1970-01-01T00:00:00Z"
        assert json.loads(json.dumps(out)), "blocked output must be JSON-serializable"

    def test_gate_node_now_provider_failure_with_valid_snapshot_is_still_blocked(self):
        # Even when the snapshot pipeline is healthy, a failing clock must fail
        # the whole gate closed: it must never fall through to a normal verdict
        # (which would depend on a live clock it was told to trust).
        calls = []

        def broken_now():
            calls.append(True)
            raise RuntimeError("clock provider exploded")

        node = create_data_quality_gate_node(now_provider=broken_now)
        out = node({"company_of_interest": SYMBOL, "trade_date": TARGET, "asset_type": "stock"})
        assert out["data_quality_verdict"] == "blocked"
        assert len(calls) == 1
        assert out["data_quality_gate_decision"]["decided_at"] == "1970-01-01T00:00:00Z"
        assert json.loads(json.dumps(out))


# ---------------------------------------------------------------------------
# Stage 2 runtime multi-category gate: normal/degraded/blocked routing
# ---------------------------------------------------------------------------


def _high_optional_group(category: str) -> dict[str, Any]:
    """A JSON-safe HIGH optional-category group (structured contract input)."""
    from tradingagents.evidence import Criticality, EvidenceGroupQuality, QualityStatus

    group = EvidenceGroupQuality(
        category=category,
        quality_status=QualityStatus.HIGH,
        criticality=Criticality.IMPORTANT,
        evidence_ids=[f"structured://{category}/1"],
        source_count=2,
        independent_source_count=2,
        reason_codes=["high"],
        human_readable_reason="ok",
    )
    return group.to_dict()


def _optional_evidence_all_high() -> dict[str, Any]:
    """The explicit structured optional-category evidence contract (all HIGH)."""
    from tradingagents.evidence.policy import OPTIONAL_CATEGORIES

    return {c: _high_optional_group(c) for c in OPTIONAL_CATEGORIES}


class TestMultiCategoryRuntimeGate:
    """Runtime integration of the multi-category gate node.

    Proves: the default node now routes normal/degraded/blocked from the
    multi-category engine; optional structured evidence enters only via the
    explicit state contract; absent optional evidence degrades (never fabricates);
    and determinism/JSON-safety hold.
    """

    def test_structured_optional_evidence_routes_normal(self, fixed_snapshot):
        node = create_data_quality_gate_node(now_provider=lambda: FETCHED)
        state = {
            "company_of_interest": SYMBOL,
            "trade_date": TARGET,
            "asset_type": "stock",
            GATE_OPTIONAL_EVIDENCE_KEY: _optional_evidence_all_high(),
        }
        out = node(state)
        assert out["data_quality_verdict"] == "normal"
        assert out["data_quality_gate_decision"]["decision"] == "normal"
        cats = {g["category"]: g["quality_status"] for g in out["data_quality_group_statuses"]}
        assert cats["market"] in ("High", "Medium")
        for optional in ("fundamentals", "news", "sentiment"):
            assert cats[optional] == "High", "structured optional evidence is honoured"
        assert json.loads(json.dumps(out))

    def test_absent_optional_evidence_routes_degraded(self, fixed_snapshot):
        node = create_data_quality_gate_node(now_provider=lambda: FETCHED)
        out = node({"company_of_interest": SYMBOL, "trade_date": TARGET, "asset_type": "stock"})
        assert out["data_quality_verdict"] == "degraded"
        assert out["data_quality_gate_decision"]["decision"] == "degraded"
        cats = {g["category"]: g["quality_status"] for g in out["data_quality_group_statuses"]}
        for optional in ("fundamentals", "news", "sentiment"):
            assert cats[optional] == "Low"
        # The reason code proves it is an honest unavailable, not a fabricated one.
        import tradingagents.evidence.policy as _policy
        for g_ in out["data_quality_group_statuses"]:
            if g_["category"] in ("fundamentals", "news", "sentiment"):
                assert _policy.REASON_UNAVAILABLE_NO_STRUCTURED_SOURCE in g_["reason_codes"]
                assert g_["source_count"] == 0
                assert g_["evidence_ids"] == []

    def test_mixed_optional_evidence_honoured_per_category(self, fixed_snapshot):
        from tradingagents.evidence.policy import CATEGORY_NEWS

        # One optional category supplied (HIGH), the rest absent -> degraded, and
        # the supplied category is honoured while absent ones degrade.
        evidence = {CATEGORY_NEWS: _high_optional_group(CATEGORY_NEWS)}
        node = create_data_quality_gate_node(now_provider=lambda: FETCHED)
        out = node({
            "company_of_interest": SYMBOL,
            "trade_date": TARGET,
            "asset_type": "stock",
            GATE_OPTIONAL_EVIDENCE_KEY: evidence,
        })
        assert out["data_quality_verdict"] == "degraded"
        cats = {g["category"]: g["quality_status"] for g in out["data_quality_group_statuses"]}
        assert cats[CATEGORY_NEWS] == "High"
        for optional in ("fundamentals", "sentiment"):
            assert cats[optional] == "Low"

    def test_unknown_or_malformed_optional_evidence_ignored(self, fixed_snapshot):
        from tradingagents.evidence.policy import CATEGORY_MARKET

        # A non-optional category (market) and a malformed entry must be ignored,
        # never coerced or parsed from prose: the gate still degrades on absent
        # optional evidence and never fabricates a source.
        node = create_data_quality_gate_node(now_provider=lambda: FETCHED)
        out = node({
            "company_of_interest": SYMBOL,
            "trade_date": TARGET,
            "asset_type": "stock",
            GATE_OPTIONAL_EVIDENCE_KEY: {
                CATEGORY_MARKET: _high_optional_group(CATEGORY_MARKET),
                "news": "not-a-group-dict",
            },
        })
        assert out["data_quality_verdict"] == "degraded"
        cats = {g["category"]: g["quality_status"] for g in out["data_quality_group_statuses"]}
        assert "market" in cats  # critical market group produced by engine
        assert cats["news"] == "Low", "malformed optional evidence is not honoured"

    def test_market_blocked_fails_closed_routes_blocked(self, fixed_snapshot):
        # The routing contract fails closed on a blocked market verdict: even when
        # the state carries a "normal" intent, an explicitly blocked gate decision
        # must route to the Research Manager (never continue the debate).
        logic = ConditionalLogic()
        state = {
            "data_quality_verdict": "blocked",
            "data_quality_gate_decision": {"decision": "blocked"},
        }
        assert logic.should_continue_after_data_gate(state) == "Research Manager"

    def test_point_in_time_blocks_via_node_when_snapshot_lookahead(self, monkeypatch):
        # The node must block when the market snapshot itself carries a
        # look-ahead record; force the snapshot builder to return one via the
        # injectable validator path by making the aggregator produce a blocked
        # market group.
        from tradingagents.evidence import (
            Criticality,
            EvidenceGroupQuality,
            QualityStatus,
        )
        from tradingagents.evidence.policy import CATEGORY_MARKET

        def blocked_aggregator(category, records, results_by_id, policy=None):
            group = EvidenceGroupQuality(
                category=CATEGORY_MARKET,
                quality_status=QualityStatus.BLOCKED,
                criticality=Criticality.CRITICAL,
                evidence_ids=[],
                source_count=0,
                independent_source_count=0,
                reason_codes=["blocked_lookahead"],
                human_readable_reason="Blocked: lookahead.",
            )
            return group, {}

        node = create_data_quality_gate_node(
            now_provider=lambda: FETCHED,
            aggregator=blocked_aggregator,
        )
        out = node({"company_of_interest": SYMBOL, "trade_date": TARGET, "asset_type": "stock"})
        assert out["data_quality_verdict"] == "blocked"
        assert out["data_quality_gate_decision"]["decision"] == "blocked"
        assert json.loads(json.dumps(out))

    def test_deterministic_serialization_across_runs(self, fixed_snapshot):
        node = create_data_quality_gate_node(now_provider=lambda: FETCHED)
        state = {
            "company_of_interest": SYMBOL,
            "trade_date": TARGET,
            "asset_type": "stock",
            GATE_OPTIONAL_EVIDENCE_KEY: _optional_evidence_all_high(),
        }
        a = node(state)
        b = node(dict(state))
        # The gate's deterministic outputs (verdict, decision, group statuses,
        # run ids) are identical for identical structured inputs. The only
        # time-varying field carried by the real snapshot layer is the evidence
        # record's ``fetched_at`` (the upstream snapshot builder stamps wall-clock
        # time); it is not a gate decision input, so compare the gate-decision
        # surface exactly and verify run-id stability on the records.
        assert a[GATE_VERDICT_KEY] == b[GATE_VERDICT_KEY] == "normal"
        assert a[GATE_DECISION_KEY] == b[GATE_DECISION_KEY]
        assert a[GATE_GROUPS_KEY] == b[GATE_GROUPS_KEY]
        assert a[GATE_CONTEXT_KEY] == b[GATE_CONTEXT_KEY]
        # Shuffling the optional-evidence insertion order must not change output.
        flipped = dict(state)
        flipped[GATE_OPTIONAL_EVIDENCE_KEY] = dict(reversed(list(state[GATE_OPTIONAL_EVIDENCE_KEY].items())))
        fa = node(flipped)
        assert fa[GATE_DECISION_KEY] == a[GATE_DECISION_KEY]
        # Stable deterministic run ids + evidence ids.
        for record in a["data_quality_evidence_records"]:
            assert record["run_id"] == build_gate_run_id(TARGET, SYMBOL)
            assert record["evidence_id"].startswith(build_gate_run_id(TARGET, SYMBOL))
        assert json.loads(json.dumps(a)) == a


# ---------------------------------------------------------------------------
# Legacy compatibility: single-category engine + old checkpoints
# ---------------------------------------------------------------------------


class TestLegacyCompatibility:
    def test_legacy_market_only_checkpoint_still_routes(self):
        # A legacy checkpoint carries only the market group statuses (no
        # optional categories). The router only inspects the verdict/decision, so
        # it still routes normally for normal/degraded, blocked for blocked.
        logic = ConditionalLogic()
        for verdict in ("normal", "degraded"):
            state = {
                "data_quality_verdict": verdict,
                "data_quality_gate_decision": {"decision": verdict},
                "data_quality_group_statuses": [
                    {"category": "market", "quality_status": "High"},
                ],
            }
            assert logic.should_continue_after_data_gate(state) == "Bull Researcher"
        blocked = {
            "data_quality_verdict": "blocked",
            "data_quality_gate_decision": {"decision": "blocked"},
            "data_quality_group_statuses": [{"category": "market", "quality_status": "Blocked"}],
        }
        assert logic.should_continue_after_data_gate(blocked) == "Research Manager"

    def test_legacy_single_category_decision_builder_intact(self):
        from tradingagents.evidence import build_gate_decision, build_multi_category_gate_decision

        legacy = build_gate_decision([self._market_high()], decided_at=FETCHED)
        assert legacy.decision.value == "normal"
        # The original single-category builder is unchanged and still returns
        # normal for a market-only HIGH input.
        multi = build_multi_category_gate_decision([self._market_high()], decided_at=FETCHED)
        assert multi.decision.value == "normal"

    @staticmethod
    def _market_high():
        from tradingagents.evidence import Criticality, EvidenceGroupQuality, QualityStatus
        from tradingagents.evidence.policy import CATEGORY_MARKET

        return EvidenceGroupQuality(
            category=CATEGORY_MARKET,
            quality_status=QualityStatus.HIGH,
            criticality=Criticality.CRITICAL,
            evidence_ids=[build_gate_run_id(TARGET, SYMBOL) + "/market/yfinance/close/0"],
            source_count=2,
            independent_source_count=2,
            reason_codes=["high"],
            human_readable_reason="market",
        )


# ---------------------------------------------------------------------------
# Full-graph routing
# ---------------------------------------------------------------------------


def _capturing_prompts(llm):
    """Return a set of all prompt strings the fake LLM was invoked with."""
    return {
        call.args[0]
        for call in llm.invoke.call_args_list
        if isinstance(call.args[0], str)
    }


# Deterministic first line of each researcher's constructed prompt. The Bull and
# Bear researcher nodes always invoke the LLM with a prompt starting with one of
# these, so their presence is a reliable signature the researcher node ran (far
# stronger than grepping for an output marker that a prompt would never carry).
BULL_RESEARCHER_PROMPT_SIGNATURE = "You are a Bull Analyst advocating for investing in the "
BEAR_RESEARCHER_PROMPT_SIGNATURE = "You are a Bear Analyst making the case against investing in the "


def _researcher_prompts(quick, deep):
    """All captured prompts that are unmistakably a Bull/Bear researcher prompt."""
    return [
        p
        for p in (_capturing_prompts(quick) | _capturing_prompts(deep))
        if p.startswith(BULL_RESEARCHER_PROMPT_SIGNATURE)
        or p.startswith(BEAR_RESEARCHER_PROMPT_SIGNATURE)
    ]


class TestBuildGateContext:
    def _decision(self, verdict, reason="Gate blocked: missing_critical_data.", limitations=None):
        from tradingagents.evidence import GateDecision, GateVerdict

        return GateDecision(
            decision=GateVerdict(verdict),
            decided_at="2026-05-13T12:00:00Z",
            group_statuses=[],
            critical_evidence_ids=["run:1", "run:2"],
            limitations=limitations or ["Degraded: confidence capped; limitations apply."],
            reason_codes=["missing_critical_data"],
            human_readable_reason=reason,
            policy_version="1.0",
        )

    @pytest.mark.parametrize("verdict", ["blocked", "degraded", "normal"])
    def test_no_duplicate_punctuation(self, verdict):
        ctx = build_gate_context(self._decision(verdict))
        # A clean context must never contain a doubled terminal period (the
        # reason/limitation strings already carry a trailing period).
        assert ".." not in ctx
        assert ctx.endswith(".")

    def test_blocked_context_state_recovery_conditions(self):
        ctx = build_gate_context(self._decision("blocked"))
        assert "Verdict: blocked." in ctx
        assert "No directional Buy or Sell is permitted." in ctx
        assert "Recovery:" in ctx
        assert "Affected/blocked evidence IDs: run:1, run:2." in ctx

    def test_degraded_context_keeps_evidence_ids_and_capping(self):
        ctx = build_gate_context(self._decision("degraded"))
        assert "Verdict: degraded." in ctx
        assert "Valid evidence IDs: run:1, run:2." in ctx
        assert "Confidence: capped by the quality limitations above." in ctx

    def test_normal_context_is_directional_contract_preserved(self):
        ctx = build_gate_context(self._decision("normal", reason="Gate normal."))
        assert "Verdict: normal." in ctx
        assert "standard bull/bear debate may proceed" in ctx


def _make_gate_factory(verdict: str):
    return lambda: _stub_gate_node(verdict)


class TestGraphRouting:
    def test_normal_routes_through_bull_researcher(self):
        quick = _fake_llm("argument")
        deep = _fake_llm("plan")
        graph = _build_graph(quick, deep, gate_factory=_make_gate_factory("normal"))
        res = graph.invoke(_initial_state())
        assert res["data_quality_verdict"] == "normal"
        # The bull researcher was invoked (its prompt includes gate context).
        prompts = _capturing_prompts(quick)
        assert any("Bull Analyst" in p for p in prompts)

    def test_degraded_injects_restrictions_into_bull_and_manager_prompts(self):
        quick = _fake_llm("argument")
        deep = _fake_llm("plan")
        # The stub gate must carry a degraded gate context string.
        def gate_factory():
            def node(state):
                return {
                    GATE_VERDICT_KEY: "degraded",
                    GATE_DECISION_KEY: {"decision": "degraded"},
                    GATE_CONTEXT_KEY: (
                        "[Data Quality Gate]\nVerdict: degraded.\n"
                        "Low evidence cannot be decisive; only ids X,Y may be "
                        "cited; confidence is capped. If the core view is "
                        "supported only by Low evidence choose Hold."
                    ),
                    "data_quality_error": None,
                    "data_quality_evidence_records": [],
                    "data_quality_validation_results": {},
                    "data_quality_group_statuses": [],
                }

            return node

        graph = _build_graph(quick, deep, gate_factory=gate_factory)
        res = graph.invoke(_initial_state())
        assert res["data_quality_verdict"] == "degraded"
        prompts = _capturing_prompts(quick) | _capturing_prompts(deep)
        bull_prompts = [p for p in prompts if "Bull Analyst" in p]
        assert bull_prompts, "bull researcher should be reached on degraded"
        assert any("degraded" in p for p in bull_prompts)

    def test_blocked_routes_to_research_manager_and_skips_bull_bear(self):
        quick = _fake_llm("argument")
        deep_capture = _fake_llm("plan")
        # The manager LLM is the deep LLM. A blocked run must never reach a
        # Researcher node: we run the graph and assert that NO captured prompt
        # carries a Bull/Bear researcher signature. Because every researcher
        # invocation builds a prompt with that signature, this is a definitive
        # proof the two researcher nodes never ran.
        graph = _build_graph(quick, deep_capture, gate_factory=_make_gate_factory("blocked"))
        res = graph.invoke(_initial_state())
        assert res["data_quality_verdict"] == "blocked"
        assert _researcher_prompts(quick, deep_capture) == []
        # The research manager node was reached and produced a plan.
        assert res.get("investment_plan")

    def test_blocked_manager_prompt_is_restricted_and_non_directional(self):
        quick = _fake_llm("argument")
        deep = _fake_llm("Hold")
        graph = _build_graph(quick, deep, gate_factory=_make_gate_factory("blocked"))
        res = graph.invoke(_initial_state())
        assert res["data_quality_verdict"] == "blocked"
        # The deep LLM (research manager) prompt must carry the block directive.
        mgr_prompts = [p for p in _capturing_prompts(deep) if "DEBATE WAS BLOCKED" in p]
        assert mgr_prompts, "research manager must receive the blocked directive"
        assert any("MUST NOT produce a strong directional Buy or Sell" in p for p in mgr_prompts)
        # Even if the model returns a directional word, the directive is present.
        # The authoritative non-direction requirement is enforced by the prompt;
        # the router forbids the normal debate entirely.

    def test_exception_in_real_gate_routes_blocked_end_to_end(self):
        # Use the real gate node but with an exploding snapshot builder. The gate
        # node must fail closed and the graph must route to Research Manager.
        def boom(*args, **kwargs):
            raise RuntimeError("snapshot fetch exploded")

        real_gate = create_data_quality_gate_node(snapshot_builder=boom)
        quick = _fake_llm("argument")
        deep = _fake_llm("plan")
        graph = _build_graph(quick, deep, gate_factory=lambda: real_gate)
        res = graph.invoke(_initial_state())
        assert res["data_quality_verdict"] == "blocked"
        assert _researcher_prompts(quick, deep) == []
        assert res.get("investment_plan")


# ---------------------------------------------------------------------------
# Graph topology
# ---------------------------------------------------------------------------


class TestGraphTopology:
    def _edges(self, analysts):
        quick = _fake_llm("x")
        deep = _fake_llm("y")
        tool_nodes = {k: ToolNode([]) for k in ("market", "social", "news", "fundamentals")}
        setup = GraphSetup(quick, deep, tool_nodes, ConditionalLogic())
        wf = setup.setup_graph(analysts)
        return wf.compile().get_graph().edges

    def _ordered_source_ids(self, edges):
        seen = []
        for e in edges:
            src = getattr(e.source, "id", getattr(e.source, "name", e.source))
            tgt = getattr(e.target, "id", getattr(e.target, "name", e.target))
            if not getattr(e, "conditional", False):
                seen.append((src, tgt))
        return seen

    @pytest.mark.parametrize(
        "analysts,last_clear,clear_nodes",
        [
            (("market", "news", "fundamentals"), "Msg Clear Fundamentals",
             ("Msg Clear Market", "Msg Clear News", "Msg Clear Fundamentals")),
            (("market", "social"), "Msg Clear Sentiment",
             ("Msg Clear Market", "Msg Clear Sentiment")),
            (("news", "fundamentals", "market"), "Msg Clear Market",
             ("Msg Clear News", "Msg Clear Fundamentals", "Msg Clear Market")),
            (("market",), "Msg Clear Market", ("Msg Clear Market",)),
        ],
    )
    def test_gate_follows_last_selected_analyst_clear_node(
        self, analysts, last_clear, clear_nodes
    ):
        edges = self._edges(analysts)
        plain = self._ordered_source_ids(edges)
        # The last analyst's clear node must feed the Data Quality Gate directly.
        assert (last_clear, "Data Quality Gate") in plain
        # No earlier analyst's clear node may feed the gate directly: the gate
        # must run only after the last analyst (it is not interleaved).
        for clear in clear_nodes:
            if clear == last_clear:
                continue
            assert (clear, "Data Quality Gate") not in plain

    def test_gate_conditional_edges_target_bull_and_research_manager(self):
        edges = self._edges(("market", "news"))
        targets = {
            getattr(e.target, "id", e.target)
            for e in edges
            if getattr(e, "conditional", False)
            and getattr(e.source, "id", e.source) == "Data Quality Gate"
        }
        assert targets == {"Bull Researcher", "Research Manager"}

    def test_debate_and_risk_route_maps_intact(self):
        # The pre-existing debate/risk path maps must remain complete so a
        # fall-through router return can never crash LangGraph mid-run (#1088).
        assert DEBATE_PATH_MAP == {
            "Bull Researcher": "Bull Researcher",
            "Bear Researcher": "Bear Researcher",
            "Research Manager": "Research Manager",
        }
        assert RISK_ANALYSIS_PATH_MAP == {
            "Aggressive Analyst": "Aggressive Analyst",
            "Conservative Analyst": "Conservative Analyst",
            "Neutral Analyst": "Neutral Analyst",
            "Portfolio Manager": "Portfolio Manager",
        }
        assert GATE_PATH_MAP == {
            "Bull Researcher": "Bull Researcher",
            "Research Manager": "Research Manager",
        }


# ---------------------------------------------------------------------------
# Gate node vs router fail-closed on missing gate state (backward compat)
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    def test_prompt_helpers_default_safely_without_gate_fields(self):
        # Direct unit tests construct minimal state dicts without gate fields;
        # the helper must not crash and must present a fail-closed block.
        from tradingagents.agents.utils.agent_utils import (
            get_data_quality_context_from_state,
        )

        ctx = get_data_quality_context_from_state({"company_of_interest": "AAPL"})
        assert isinstance(ctx, str) and ctx
        assert "blocked" in ctx

        ctx_normal = get_data_quality_context_from_state({"data_quality_verdict": "normal"})
        assert "normal" in ctx_normal
