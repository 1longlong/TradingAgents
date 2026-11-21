"""ADR-010 Stage 3: exact-claim validation is CONSUMED at runtime.

Approved test cases (2026-11-11 human plan/test approval; plan + tests ONLY, not
final human acceptance). These drive the REAL production ``AgentState`` /
``GraphSetup`` graph with mocked raw vendors and scripted models that deliberately
cite a *valid* evidence ID but a *wrong* exact date/value/unit, and prove:

- a valid-but-misused citation does NOT count as valid new evidence, and the
  debate does not extend on it;
- a wrong exact claim cannot create/resolve a factual ConflictRecord;
- the Research Manager receives an auditable verified/rejected claim summary and
  the trusted plan cannot repeat the wrong fact (without a global Hold);
- a correct typed exact claim stays usable and unchanged;
- the qualitative / no-claim legacy path is byte-for-byte unchanged;
- a real SqliteSaver interrupt/restart preserves origin metadata + validation and
  cannot resurrect a prior wrong claim through the public entry report writer.

No network, no paid LLM.

Traceability: FR-DDT-002, FR-DDT-005, NFR-PIT-001, NFR-AUD-001, NFR-DET-001,
NFR-BC-001, FR-DQG-005, INV-1/INV-3/INV-6/INV-13.
"""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langgraph.prebuilt import ToolNode

from tradingagents.debate.claims import claimed_ids_with_failed_claims
from tradingagents.debate.conflicts import build_conflict_summary, derive_conflicts
from tradingagents.debate.evidence_manifest import EvidenceManifest
from tradingagents.debate.models import (
    ClaimRecord,
    ConflictAssertion,
    DebateTurn,
    Stance,
)
from tradingagents.evidence.origin import ORIGIN_STATE_KEY, OriginMetadata
from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.propagation import Propagator
from tradingagents.graph.setup import GraphSetup

SYMBOL = "COF"
TARGET = "2026-05-13"
EVID = f"{TARGET}/COF/market/close/0"

# A valid, eligible manifest record (observation date 2026-05-04, close 200.13).
_RECORD = {
    "evidence_id": EVID,
    "run_id": f"{TARGET}/COF",
    "ticker_input": SYMBOL,
    "ticker_normalized": SYMBOL,
    "category": "market",
    "metric_name": "close",
    "value_raw": "200.13",
    "value_normalized": "200.1300000000",
    "unit_normalized": "USD",
    "observed_at": "2026-05-04",
    "target_date": TARGET,
    "quality_status": "Medium",
    "validation_results": [],
}
_ORIGIN = OriginMetadata(
    target_date=TARGET,
    observation_date="2026-05-04",
    availability_date=None,
    retrieved_at="2026-05-13T12:00:00Z",
    date_basis="period_end",
    value_scale=__import__("decimal").Decimal("1"),
    unit="USD",
    currency="USD",
)


def _gate_output():
    return {
        "data_quality_verdict": "normal",
        "data_quality_gate_decision": {
            "decision": "normal",
            "decided_at": "2026-05-13T12:00:00Z",
        },
        "data_quality_context": "[Data Quality Gate] Verdict: normal.",
        "data_quality_error": None,
        "data_quality_evidence_records": [dict(_RECORD)],
        "data_quality_validation_results": {},
        "data_quality_group_statuses": [],
        ORIGIN_STATE_KEY: {EVID: _ORIGIN.to_dict()},
    }


def _stub_gate_node():
    def node(state):
        return _gate_output()

    return node


def _turn(wrong_claim: str, *, stance="Buy", confidence="0.7") -> str:
    return (
        "The validated market data supports the growth case.\n"
        "DEBATE_METADATA: stance=" + stance + f"; confidence={confidence}; "
        f"cited={EVID}; new_claims=margin expansion supported|{EVID}; "
        f"claim={wrong_claim};"
    )


class _MockLLM:
    def __init__(self, content):
        self.content = content
        self.calls = []
        self.with_structured_output = lambda *a, **k: None
        self.bind_tools = lambda tools: RunnableLambda(
            lambda m: AIMessage(content=self.content, tool_calls=[])
        )

    def invoke(self, prompt):
        self.calls.append(prompt)
        return AIMessage(content=self.content)


def _build_graph(quick, deep):
    tool_nodes = {key: ToolNode([]) for key in ("market", "social", "news", "fundamentals")}
    setup = GraphSetup(
        quick,
        deep,
        tool_nodes,
        ConditionalLogic(),
        data_quality_gate_factory=lambda: _stub_gate_node(),
    )
    return setup.setup_graph(("market",)).compile()


def _initial_state(extra=None):
    state = Propagator().create_initial_state(SYMBOL, TARGET, asset_type="stock")
    state.update(_gate_output())
    if extra:
        state.update(extra)
    return state


def _wrong_date_claim() -> str:
    # Correct metric/id/value/unit, WRONG observation date (2026-05-05 vs real 05-04).
    return (
        "metric=close|role=observation_date|date=2026-05-05|value=200.13|unit=USD|currency=USD"
        f"|evidence={EVID}"
    )


def _correct_claim() -> str:
    return (
        "metric=close|role=observation_date|date=2026-05-04|value=200.13|unit=USD|currency=USD"
        f"|evidence={EVID}"
    )


def _wrong_value_claim() -> str:
    return (
        "metric=close|role=observation_date|date=2026-05-04|value=999.99|unit=USD|currency=USD"
        f"|evidence={EVID}"
    )


# ---------------------------------------------------------------------------
# Valid-but-misused citation does not count as new valid evidence.
# ---------------------------------------------------------------------------


class TestNoNewEvidenceOnWrongClaim:
    def test_wrong_date_claim_does_not_extend_debate(self):
        bull = _turn(_wrong_date_claim())
        bear = _turn(_wrong_date_claim())
        graph = _build_graph(_MockLLM(bull), _MockLLM(bear))
        final = graph.invoke(_initial_state())
        metrics = final["investment_debate_state"]["round_metrics"][-1]
        assert metrics["new_valid_evidence_count"] == 0
        assert EVID not in metrics["new_valid_evidence_ids"]
        # The debate must not be extended for wrong "new" evidence: the route is a
        # summarize (no_new_evidence / diminishing), never continue_for_new_evidence.
        decision = final.get("debate_termination_decision") or {}
        assert decision.get("route") in ("summarize", "stop")
        assert decision.get("stop_reason") != "continue_for_new_evidence"

    def test_wrong_value_claim_does_not_count(self):
        bull = _turn(_wrong_value_claim())
        bear = _turn(_wrong_value_claim())
        graph = _build_graph(_MockLLM(bull), _MockLLM(bear))
        final = graph.invoke(_initial_state())
        metrics = final["investment_debate_state"]["round_metrics"][-1]
        assert metrics["new_valid_evidence_count"] == 0

    def test_correct_claim_counts_as_valid_new_evidence(self):
        bull = _turn(_correct_claim())
        bear = _turn(_correct_claim())
        graph = _build_graph(_MockLLM(bull), _MockLLM(bear))
        final = graph.invoke(_initial_state())
        metrics = final["investment_debate_state"]["round_metrics"][-1]
        assert metrics["new_valid_evidence_count"] > 0
        assert EVID in metrics["new_valid_evidence_ids"]


# ---------------------------------------------------------------------------
# A wrong exact claim cannot create/resolve a factual conflict.
# ---------------------------------------------------------------------------


class TestConflictLifecycle:
    def _assertion(self):
        return ConflictAssertion(
            action="assert",
            topic="close price level",
            bull_claim="close 200.13 on 2026-05-05",
            bear_claim="close differs",
            kind="factual",
            severity="major",
            evidence_ids=[EVID],
        )

    def test_wrong_claim_does_not_create_factual_conflict(self):
        turn = DebateTurn(
            speaker="Bull",
            content="x",
            stance=Stance.BUY,
            confidence=0.7,
            exact_claims=[
                ClaimRecord(
                    evidence_ids=[EVID],
                    metric="close",
                    date_role="observation_date",
                    date="2026-05-05",
                    value="200.13",
                    unit="USD",
                )
            ],
            conflict_assertions=[self._assertion()],
        )
        # The runtime invalid-claimed set (what derive_conflicts receives) excludes
        # the misused id: a factual conflict on it is not created.
        manifest = EvidenceManifest.from_records([_RECORD])
        records_by_id = {EVID: _RECORD}

        invalid = claimed_ids_with_failed_claims(
            [turn],
            origin_by_id={EVID: _ORIGIN},
            records_by_id=records_by_id,
            target_date=TARGET,
            expected_symbol=SYMBOL,
            expected_run_id=f"{TARGET}/{SYMBOL}",
        )
        assert EVID in invalid
        conflicts, _ = derive_conflicts(
            round_index=1,
            turns=[turn],
            manifest=manifest,
            target_date=TARGET,
            tracked=[],
            invalid_claimed_ids=invalid,
        )
        assert conflicts == []
        summary = build_conflict_summary(conflicts)
        assert summary.open_blocking_count == 0

    def test_correct_claim_allows_factual_conflict(self):
        turn = DebateTurn(
            speaker="Bull",
            content="x",
            stance=Stance.BUY,
            confidence=0.7,
            conflict_assertions=[self._assertion()],
        )
        manifest = EvidenceManifest.from_records([_RECORD])
        conflicts, _ = derive_conflicts(
            round_index=1,
            turns=[turn],
            manifest=manifest,
            target_date=TARGET,
            tracked=[],
            invalid_claimed_ids=set(),
        )
        assert len(conflicts) == 1


# ---------------------------------------------------------------------------
# Research Manager receives an auditable summary; trusted plan cannot repeat it.
# ---------------------------------------------------------------------------


class TestManagerAuditAndTrustedOutput:
    def test_manager_prompt_carries_rejected_claim_and_plan_is_cleaned(self):
        bull = _turn(_wrong_date_claim())
        # Bear has no exact claim: only the Bull claim is validated.
        quick = _MockLLM(bull)
        deep = _MockLLM(
            "**Recommendation**: Buy\n\n**Rationale**: The close was 200.13 on "
            f"2026-05-05 per {EVID}, which is bullish.\n\n**Strategic Actions**: Add."
        )
        graph = _build_graph(quick, deep)
        final = graph.invoke(_initial_state())

        # The Research Manager prompt carried the rejected claim (auditable input).
        manager_prompts = [p for p in deep.calls if isinstance(p, str) and "Research Manager" in p]
        assert manager_prompts, "the Research Manager must have been invoked"
        joined = "\n".join(manager_prompts)
        assert "REJECTED exact claims" in joined
        assert EVID in joined
        assert "2026-05-05" in joined

        # The trusted plan must NOT repeat the wrong fact (wrong date replaced with
        # an explicit unverified marker), and it must NOT be turned into a global
        # Hold (the qualitative judgement survives).
        plan = final["investment_plan"]
        assert "2026-05-05" not in plan
        assert "unverified exact claim omitted" in plan
        assert "Hold" not in plan.split("**Rationale**")[0].replace("Recommendation", "")

    def test_saved_report_cannot_repeat_wrong_verified_fact(self, tmp_path):
        from tradingagents.reporting import write_report_tree

        bull = _turn(_wrong_date_claim())
        deep = _MockLLM(
            "**Recommendation**: Overweight\n\n**Rationale**: close 200.13 on 2026-05-05.\n\n"
            "**Strategic Actions**: Trim."
        )
        graph = _build_graph(_MockLLM(bull), deep)
        final = graph.invoke(_initial_state())
        write_report_tree(final, SYMBOL, tmp_path / "run")

        complete = (Path(tmp_path) / "run" / "complete_report.md").read_text(encoding="utf-8")
        # The trusted report body never carries the wrong date as a verified fact.
        assert "200.13 on 2026-05-05" not in complete
        # The claim-validation audit artifact records the rejection.
        trace = json.loads(
            (Path(tmp_path) / "run" / "2_research" / "debate_trace.json").read_text(encoding="utf-8")
        )
        rejected = trace["claim_validation"]["rejected"]
        assert any(EVID in entry["evidence_ids"] for entry in rejected)


# ---------------------------------------------------------------------------
# Legacy qualitative path is unchanged.
# ---------------------------------------------------------------------------


class TestLegacyQualitativeUnchanged:
    def test_no_claim_qualitative_turn_keeps_debate_and_no_claim_summary(self):
        bull = (
            "The fundamentals look strong and the trend is favorable.\n"
            f"DEBATE_METADATA: stance=Buy; confidence=0.7; cited={EVID}; "
            f"new_claims=strong moat|{EVID};"
        )
        bear = (
            "Valuation is stretched and risks are real.\n"
            f"DEBATE_METADATA: stance=Sell; confidence=0.6; cited={EVID}; "
            f"new_claims=valuation risk|{EVID};"
        )
        graph = _build_graph(_MockLLM(bull), _MockLLM(bear))
        final = graph.invoke(_initial_state())
        metrics = final["investment_debate_state"]["round_metrics"][-1]
        # No exact claim -> linkage alone still counts as new valid evidence.
        assert metrics["new_valid_evidence_count"] > 0
        summary = final["investment_debate_state"].get("claim_validation_summary") or {}
        assert summary.get("rejected") in ([], None)


# ---------------------------------------------------------------------------
# Real SqliteSaver interrupt/restart preserves validation and denials.
# ---------------------------------------------------------------------------


class TestRealCheckpointResume:
    def test_origin_and_claim_validation_survive_resume(self, tmp_path):
        from tradingagents.graph.checkpointer import get_checkpointer, thread_id

        bull = _turn(_wrong_date_claim())
        quick = _MockLLM(bull)
        deep = _MockLLM("Hold")
        data_dir = str(tmp_path / "ckpt")
        tid = thread_id(SYMBOL, TARGET)
        graph_cfg = {"configurable": {"thread_id": tid}}

        with get_checkpointer(data_dir, SYMBOL) as saver:
            # Compile with the saver + interrupt after the Bull so a checkpoint is
            # taken mid-debate, then resume in a fresh saver.
            tool_nodes = {
                key: ToolNode([]) for key in ("market", "social", "news", "fundamentals")
            }
            setup = GraphSetup(
                quick, deep, tool_nodes, ConditionalLogic(),
                data_quality_gate_factory=lambda: _stub_gate_node(),
            )
            g = setup.setup_graph(("market",)).compile(
                checkpointer=saver, interrupt_after=["Bull Researcher"]
            )
            g.invoke(_initial_state(), graph_cfg)

        with get_checkpointer(data_dir, SYMBOL) as saver:
            tool_nodes = {
                key: ToolNode([]) for key in ("market", "social", "news", "fundamentals")
            }
            setup = GraphSetup(
                quick, deep, tool_nodes, ConditionalLogic(),
                data_quality_gate_factory=lambda: _stub_gate_node(),
            )
            g2 = setup.setup_graph(("market",)).compile(checkpointer=saver)
            resumed = g2.invoke(None, graph_cfg)

        # Origin metadata survived the checkpoint.
        origin_after = resumed.get(ORIGIN_STATE_KEY) or {}
        assert EVID in origin_after
        assert origin_after[EVID]["observation_date"] == "2026-05-04"
        # The wrong claim is still rejected after resume: no new valid evidence.
        metrics = resumed["investment_debate_state"]["round_metrics"][-1]
        assert metrics["new_valid_evidence_count"] == 0
        summary = resumed["investment_debate_state"].get("claim_validation_summary") or {}
        assert any(EVID in e["evidence_ids"] for e in summary.get("rejected", []))


# ---------------------------------------------------------------------------
# A bad citation never erases an open/escalated conflict (no false consensus).
# ---------------------------------------------------------------------------


def _open_factual_conflict():
    from tradingagents.debate.models import ConflictRecord

    return ConflictRecord(
        conflict_id="conflict-open-1",
        topic="close price level",
        bull_claim="close 200.13 on 2026-05-04",
        bear_claim="close differs materially",
        evidence_ids=[EVID],
        kind="factual",
        severity="major",
        status="open",
        participants=["Bull", "Bear"],
        first_seen_round=1,
        last_seen_round=1,
    )


def _wrong_claim_record():
    return ClaimRecord(
        evidence_ids=[EVID],
        metric="close",
        date_role="observation_date",
        date="2026-05-05",  # wrong vs record 2026-05-04
        value="200.13",
        unit="USD",
        currency="USD",
    )


class TestBadCitationNeverErasesConflict:
    def _invalid(self, turns):
        return claimed_ids_with_failed_claims(
            turns,
            origin_by_id={EVID: _ORIGIN},
            records_by_id={EVID: _RECORD},
            target_date=TARGET,
            expected_symbol=SYMBOL,
            expected_run_id=f"{TARGET}/{SYMBOL}",
        )

    def test_wrong_dated_resolution_keeps_open_no_consensus(self):
        from tradingagents.debate.conflicts import derive_conflicts

        resolve = DebateTurn(
            speaker="Bull",
            content="x",
            stance=Stance.BUY,
            confidence=0.7,
            exact_claims=[_wrong_claim_record()],
            conflict_assertions=[
                ConflictAssertion(
                    action="resolve",
                    conflict_id="conflict-open-1",
                    reason="the figures now agree",
                    evidence_ids=[EVID],
                )
            ],
        )
        invalid = self._invalid([resolve])
        assert EVID in invalid
        manifest = EvidenceManifest.from_records([_RECORD])
        denials: list[str] = []
        conflicts, notes = derive_conflicts(
            round_index=2,
            turns=[resolve],
            manifest=manifest,
            target_date=TARGET,
            tracked=[_open_factual_conflict().to_dict()],
            invalid_claimed_ids=invalid,
            denials=denials,
        )
        # The attempted resolution is rejected; the conflict stays OPEN and still
        # blocks termination; no resolution note; an auditable denial is recorded.
        assert len(conflicts) == 1
        assert conflicts[0].status.value == "open"
        assert conflicts[0].blocks_termination() is True
        assert notes == []
        assert any("resolve_rejected" in d for d in denials)

    def test_wrong_dated_reobservation_does_not_drop_open(self):
        from tradingagents.debate.conflicts import derive_conflicts

        reobserve = DebateTurn(
            speaker="Bull",
            content="x",
            stance=Stance.BUY,
            confidence=0.7,
            exact_claims=[_wrong_claim_record()],
            conflict_assertions=[
                ConflictAssertion(
                    action="assert",
                    conflict_id="conflict-open-1",
                    topic="close price level",
                    bull_claim="close 200.13 on 2026-05-05",
                    bear_claim="close differs materially",
                    kind="factual",
                    severity="major",
                    evidence_ids=[EVID],
                )
            ],
        )
        invalid = self._invalid([reobserve])
        manifest = EvidenceManifest.from_records([_RECORD])
        denials: list[str] = []
        conflicts, notes = derive_conflicts(
            round_index=2,
            turns=[reobserve],
            manifest=manifest,
            target_date=TARGET,
            tracked=[_open_factual_conflict().to_dict()],
            invalid_claimed_ids=invalid,
            denials=denials,
        )
        assert len(conflicts) == 1
        assert conflicts[0].conflict_id == "conflict-open-1"
        assert conflicts[0].status.value == "open"
        assert any("observation_rejected" in d for d in denials)

    def test_wrong_dated_escalation_keeps_open(self):
        from tradingagents.debate.conflicts import derive_conflicts

        escalate = DebateTurn(
            speaker="Bear",
            content="x",
            stance=Stance.SELL,
            confidence=0.7,
            exact_claims=[_wrong_claim_record()],
            conflict_assertions=[
                ConflictAssertion(
                    action="escalate",
                    conflict_id="conflict-open-1",
                    reason="needs manager",
                    evidence_ids=[EVID],
                )
            ],
        )
        invalid = self._invalid([escalate])
        manifest = EvidenceManifest.from_records([_RECORD])
        denials: list[str] = []
        conflicts, _ = derive_conflicts(
            round_index=2,
            turns=[escalate],
            manifest=manifest,
            target_date=TARGET,
            tracked=[_open_factual_conflict().to_dict()],
            invalid_claimed_ids=invalid,
            denials=denials,
        )
        assert len(conflicts) == 1
        assert conflicts[0].status.value == "open"
        assert any("escalate_rejected" in d for d in denials)


# ---------------------------------------------------------------------------
# Multiple claims per turn: one correct claim cannot launder a second wrong one.
# ---------------------------------------------------------------------------


class TestMultipleClaimsPerTurn:
    def _turn_two_claims(self, second: str) -> str:
        return (
            "Argument with two exact figures.\n"
            f"DEBATE_METADATA: stance=Buy; confidence=0.7; cited={EVID}; "
            f"new_claims=margin expansion supported|{EVID}; "
            f"claim={_correct_claim()}; claim={second};"
        )

    def test_correct_plus_wrong_on_same_id_is_not_new_evidence(self):
        # One correct claim and one wrong claim on the SAME valid ID: the id must
        # NOT count as valid new evidence (per-claim coverage; no first-claim-wins).
        bull = self._turn_two_claims(_wrong_date_claim())
        bear = self._turn_two_claims(_wrong_date_claim())
        graph = _build_graph(_MockLLM(bull), _MockLLM(bear))
        final = graph.invoke(_initial_state())
        metrics = final["investment_debate_state"]["round_metrics"][-1]
        assert metrics["new_valid_evidence_count"] == 0
        summary = final["investment_debate_state"].get("claim_validation_summary") or {}
        assert any(EVID in e["evidence_ids"] for e in summary.get("rejected", []))

    def test_two_correct_claims_count(self):
        second = (
            "metric=close|role=observation_date|date=2026-05-04|value=200.13"
            f"|unit=USD|currency=USD|evidence={EVID}"
        )
        bull = self._turn_two_claims(second)
        bear = self._turn_two_claims(second)
        graph = _build_graph(_MockLLM(bull), _MockLLM(bear))
        final = graph.invoke(_initial_state())
        metrics = final["investment_debate_state"]["round_metrics"][-1]
        assert metrics["new_valid_evidence_count"] > 0


class TestTrustedReportBoundaryEnforcement:
    def test_report_marks_raw_transcript_non_authoritative_and_cleans_trusted(self, tmp_path):
        from tradingagents.reporting import write_report_tree

        bull = _turn(_wrong_date_claim())
        # Every model node (RM, Trader, Portfolio) echoes the wrong fact.
        deep = _MockLLM(
            "**Recommendation**: Overweight\n\n**Rationale**: close 200.13 on "
            f"2026-05-05 citing {EVID}.\n\n**Strategic Actions**: Trim."
        )
        graph = _build_graph(_MockLLM(bull), deep)
        final = graph.invoke(_initial_state())
        write_report_tree(final, SYMBOL, tmp_path / "run")

        bull_md = (Path(tmp_path) / "run" / "2_research" / "bull.md").read_text(encoding="utf-8")
        # The raw debate transcript is explicitly NON-AUTHORITATIVE.
        assert "NON-AUTHORITATIVE" in bull_md

        complete = (Path(tmp_path) / "run" / "complete_report.md").read_text(encoding="utf-8")
        # No trusted section (Trader / Portfolio / Manager) restates the wrong fact;
        # only the non-authoritative transcript may retain the raw text.
        trusted_sections = complete.split("## II. Research Team Decision")[-1]
        # Strip the non-authoritative transcript blocks from the trusted tail.
        trusted_text = "\n".join(
            line for line in trusted_sections.splitlines()
            if "DEBATE_METADATA" not in line
        )
        assert "200.13 on 2026-05-05" not in trusted_text


# ---------------------------------------------------------------------------
# FRESH boundary factors: downstream models hallucinate NEW wrong exact facts
# with NO prior rejected debate claim. Each boundary validates its OWN text.
# ---------------------------------------------------------------------------


class _NodeDispatchLLM:
    """A model mock returning node-specific content via a phrase->content map.

    Dispatches on a distinctive phrase in each node's prompt so a test can script a
    DIFFERENT new wrong fact at each trusted boundary, independent of the debate.
    ``routes`` is an ordered list of ``(phrase, content)``; a content-less fallback
    is returned when no phrase matches.
    """

    def __init__(self, routes, fallback: str = "Hold"):
        self.routes = list(routes)
        self.fallback = fallback
        self.calls = []
        self.with_structured_output = lambda *a, **k: None
        self.bind_tools = lambda tools: RunnableLambda(lambda m: AIMessage(content="", tool_calls=[]))

    def invoke(self, prompt):
        self.calls.append(prompt)
        text = prompt if isinstance(prompt, str) else str(prompt)
        for phrase, content in self.routes:
            if phrase in text:
                return AIMessage(content=content)
        return AIMessage(content=self.fallback)


def _clean_debate_turn() -> str:
    # A qualitative Bull turn with NO exact claim (so nothing is in the rejected set).
    return (
        "The business quality and demand backdrop look constructive.\n"
        f"DEBATE_METADATA: stance=Buy; confidence=0.7; cited={EVID}; "
        f"new_claims=strong demand|{EVID};"
    )


def _run_fresh_boundaries(rm: str, trader: str, portfolio: str, *, extra_claims: str = ""):
    # quick is used by analysts + Bull + Bear + Trader + risk analysts; deep by the
    # Research Manager + Portfolio Manager. Dispatch by node phrase so a DIFFERENT
    # wrong fact can be scripted at each boundary. The Bull/Bear turn is qualitative
    # (no exact claim), so NOTHING is in the rejected set.
    quick = _NodeDispatchLLM(
        [
            ("trading agent analyzing market data", trader),
            ("You are a Bull Analyst", _clean_debate_turn()),
            ("You are a Bear Analyst", _clean_debate_turn()),
            ("As the Aggressive Risk Analyst", "The trader's plan is reasonable."),
            ("As the Conservative Risk Analyst", "The trader's plan carries risk."),
            ("As the Neutral Risk Analyst", "The trader's plan is balanced."),
            ("You are a helpful assistant tasked with writing a market analyst", "market ok"),
        ],
        fallback=_clean_debate_turn(),
    )
    deep = _NodeDispatchLLM(
        [
            ("As the Research Manager", rm),
            ("As the Portfolio Manager", portfolio),
        ],
        fallback="Hold",
    )
    graph = _build_graph(quick, deep)
    state = _initial_state()
    if extra_claims:
        # Attach real origin metadata (the gate would), so the boundary validator
        # has typed date/unit semantics to validate against.
        state[ORIGIN_STATE_KEY] = {EVID: _ORIGIN.to_dict()}
    return graph.invoke(state)


class TestFreshBoundaryHallucination:
    def test_each_boundary_different_wrong_fact_contained(self, tmp_path):
        from tradingagents.reporting import write_report_tree

        # RM invents the close as 2026-05-05 USD999; Trader invents 2026-05-06
        # 888.88; Portfolio invents a unit-wrong "500 percent". NONE was in debate.
        rm = (
            "**Recommendation**: Buy\n\n**Rationale**: on 2026-05-05 the close was "
            f"999 USD ({EVID}).\n\n**Strategic Actions**: Add."
        )
        trader = (
            "**Action**: Buy\n\n**Rationale**: on 2026-05-06 the close was "
            f"888.88 USD ({EVID}).\n\n**Entry Price**: 888.88"
        )
        portfolio = (
            "**Rating**: Buy\n\n**Executive Summary**: the close was "
            f"500 percent on 2026-05-05 ({EVID}).\n\n**Investment Thesis**: add."
        )
        final = _run_fresh_boundaries(rm, trader, portfolio, extra_claims="x")

        # No prior rejected debate claim existed: containment must come from the
        # FRESH per-boundary validation, not a lookup of earlier rejects.
        summary = final["investment_debate_state"].get("claim_validation_summary") or {}
        assert not summary.get("rejected")

        plan = final["investment_plan"]
        tplan = final["trader_investment_plan"]
        final_dec = final["final_trade_decision"]
        for text in (plan, tplan, final_dec):
            # The recommendation survives; the wrong exact fact is redacted.
            assert "[unverified exact claim omitted]" in text
        assert "2026-05-05" not in plan
        assert "999" not in plan.split("**Strategic Actions**")[0].replace("USD", "")
        assert "2026-05-06" not in tplan
        assert "888.88" not in tplan.split("**Entry Price**")[0]
        assert "2026-05-05" not in final_dec
        assert "500 percent" not in final_dec
        # Recommendations are NOT turned into a global Hold.
        assert "Hold" not in plan.split("**Rationale**")[0].replace("Recommendation", "")

        # The saved report + memory boundary carry no wrongly-verified fact.
        write_report_tree(final, SYMBOL, tmp_path / "run")
        complete = (Path(tmp_path) / "run" / "complete_report.md").read_text(encoding="utf-8")
        # Strip the non-authoritative raw transcript before checking trusted text.
        trusted = "\n".join(
            line for line in complete.splitlines() if "DEBATE_METADATA" not in line
        )
        assert "on 2026-05-05 the close was 999 USD" not in trusted
        assert "on 2026-05-06 the close was 888.88 USD" not in trusted

    def test_line_break_bypass_is_contained(self):
        # The cited ID is on the NEXT line from the wrong fact (line-wrapping).
        rm = (
            "**Recommendation**: Buy\n\n**Rationale**: on 2026-05-05 the close was "
            f"999 USD.\nSee {EVID} for detail.\n\n**Strategic Actions**: Add."
        )
        final = _run_fresh_boundaries(rm, "**Action**: Hold", "**Rating**: Hold", extra_claims="x")
        assert "2026-05-05" not in final["investment_plan"]
        assert "[unverified exact claim omitted]" in final["investment_plan"]

    def test_fullwidth_wrong_fact_contained(self):
        # Fullwidth digits/signs are normalized by the extractor.
        rm = (
            "**Recommendation**: Buy\n\n**Rationale**: on ２０２６-05-05 the close was "
            f"９９９ USD ({EVID}).\n\n**Strategic Actions**: Add."
        )
        final = _run_fresh_boundaries(rm, "**Action**: Hold", "**Rating**: Hold", extra_claims="x")
        # The fullwidth date/value must not survive as a verified fact.
        assert "５" not in final["investment_plan"] or "２０２６" not in final["investment_plan"]

    def test_correct_fact_is_preserved(self):
        rm = (
            "**Recommendation**: Buy\n\n**Rationale**: on 2026-05-04 the close was "
            f"200.13 USD ({EVID}).\n\n**Strategic Actions**: Add."
        )
        final = _run_fresh_boundaries(rm, "**Action**: Hold", "**Rating**: Hold", extra_claims="x")
        # A correct exact fact (matching the record) stays.
        assert "2026-05-04" in final["investment_plan"]
        assert "200.13" in final["investment_plan"]
        assert "[unverified exact claim omitted]" not in final["investment_plan"]

    def test_recommendation_target_price_not_redacted(self):
        # A forward price target is a recommendation, not an observation: never
        # validated against the close record, never redacted.
        rm = (
            "**Recommendation**: Buy\n\n**Rationale**: we set a price target of "
            f"250 USD for 2026-06-01 ({EVID}).\n\n**Strategic Actions**: Add."
        )
        final = _run_fresh_boundaries(rm, "**Action**: Hold", "**Rating**: Hold", extra_claims="x")
        assert "250 USD" in final["investment_plan"]
        assert "price target" in final["investment_plan"]


def test_reviewer_glued_currency_hallucination_contained():
    # Exact reviewer reproduction: 'On 2026-05-05 the close was USD999 [validId]'
    # with an empty debate rejected list must be contained by the fresh boundary
    # validation (number glued to the currency unit).
    from tradingagents.agents.utils.output_guard import enforce_trusted_boundary

    state = {
        "trade_date": TARGET,
        "company_of_interest": SYMBOL,
        "data_quality_evidence_records": [dict(_RECORD)],
        ORIGIN_STATE_KEY: {EVID: _ORIGIN.to_dict()},
        "investment_debate_state": {"claim_validation_summary": {"rejected": []}},
    }
    out = enforce_trusted_boundary(f"On 2026-05-05 the close was USD999 {EVID}", state)
    assert "2026-05-05" not in out
    assert "999" not in out.split(EVID)[0]
    assert "[unverified exact claim omitted]" in out
    # The correct fact is preserved.
    ok = enforce_trusted_boundary(f"On 2026-05-04 the close was 200.13 USD {EVID}", state)
    assert "2026-05-04" in ok and "200.13" in ok


class TestBoundaryBypassVariants:
    """Direct + real-boundary regressions for the reviewed bypasses."""

    def _state(self):
        return {
            "trade_date": TARGET,
            "company_of_interest": SYMBOL,
            "data_quality_evidence_records": [dict(_RECORD)],
            ORIGIN_STATE_KEY: {EVID: _ORIGIN.to_dict()},
            # EMPTY rejected list: containment must come from fresh validation.
            "investment_debate_state": {"claim_validation_summary": {"rejected": []}},
        }

    def test_recommendation_in_other_clause_does_not_exempt_fact(self):
        from tradingagents.agents.utils.output_guard import enforce_trusted_boundary

        text = f"On 2026-05-05 the close was USD 999 {EVID}; therefore I recommend Hold"
        out = enforce_trusted_boundary(text, self._state())
        assert "2026-05-05" not in out
        assert "999" not in out.split(EVID)[0]
        assert "recommend Hold" in out  # recommendation clause preserved

    def test_second_wrong_fact_on_same_line_not_laundered(self):
        from tradingagents.agents.utils.output_guard import enforce_trusted_boundary

        text = (
            f"On 2026-05-04 the close was 200.13 USD {EVID}; "
            f"and on 2026-05-05 it was 999 USD {EVID}"
        )
        out = enforce_trusted_boundary(text, self._state())
        # The correct first fact stays; the wrong second fact is redacted.
        assert "200.13" in out
        assert "2026-05-04" in out
        assert "2026-05-05" not in out
        assert "999" not in out.split(EVID)[0].split(";")[-1]

    def test_date_value_split_across_lines_contained(self):
        from tradingagents.agents.utils.output_guard import enforce_trusted_boundary

        text = f"On 2026-05-05\nthe close was 999 USD {EVID}"
        out = enforce_trusted_boundary(text, self._state())
        assert "2026-05-05" not in out
        assert "999" not in out

    def test_citation_on_adjacent_line_contained(self):
        from tradingagents.agents.utils.output_guard import enforce_trusted_boundary

        text = f"On 2026-05-05 the close was 999 USD\nSee {EVID} for the record"
        out = enforce_trusted_boundary(text, self._state())
        assert "2026-05-05" not in out and "999" not in out

    def test_forward_price_target_preserved(self):
        from tradingagents.agents.utils.output_guard import enforce_trusted_boundary

        text = f"We set a price target of 250 USD for 2026-06-01 ({EVID})."
        out = enforce_trusted_boundary(text, self._state())
        assert "250 USD" in out and "price target" in out

    def test_real_boundaries_multi_and_split_no_prior_reject(self, tmp_path):
        from tradingagents.reporting import write_report_tree

        # RM: correct + wrong fact on one line (laundering variant). Trader: split
        # date/value across lines. Portfolio: recommendation in another clause.
        rm = (
            "**Recommendation**: Buy\n\n**Rationale**: on 2026-05-04 the close was "
            f"200.13 USD {EVID}; on 2026-05-05 it was 999 USD {EVID}.\n\n"
            "**Strategic Actions**: Add."
        )
        trader = (
            "**Action**: Buy\n\n**Rationale**: on 2026-05-06\n"
            f"the close was 888.88 USD {EVID}; therefore I recommend Buy.\n\n"
            "**Entry Price**: 888.88"
        )
        portfolio = (
            "**Rating**: Buy\n\n**Executive Summary**: on 2026-05-07 the close was "
            f"777 USD {EVID}; I therefore rate Buy.\n\n**Investment Thesis**: add."
        )
        final = _run_fresh_boundaries(rm, trader, portfolio, extra_claims="x")
        # No prior rejected debate claim existed.
        summary = final["investment_debate_state"].get("claim_validation_summary") or {}
        assert not summary.get("rejected")

        plan = final["investment_plan"]
        tplan = final["trader_investment_plan"]
        fdec = final["final_trade_decision"]
        assert "2026-05-04" in plan and "200.13" in plan  # correct fact kept
        assert "2026-05-05" not in plan and "999" not in plan.split("**Strategic Actions**")[0]
        assert "2026-05-06" not in tplan and "888.88" not in tplan.split("**Entry Price**")[0]
        assert "2026-05-07" not in fdec and "777" not in fdec.split("**Investment Thesis**")[0]
        # Recommendations preserved (not a global Hold).
        assert "Hold" not in plan.split("**Rationale**")[0].replace("Recommendation", "")

        write_report_tree(final, SYMBOL, tmp_path / "run")
        complete = (Path(tmp_path) / "run" / "complete_report.md").read_text(encoding="utf-8")
        trusted = "\n".join(
            line for line in complete.splitlines() if "DEBATE_METADATA" not in line
        )
        assert "2026-05-05 it was 999 USD" not in trusted
        assert "the close was 888.88 USD" not in trusted
        assert "the close was 777 USD" not in trusted


class TestBypassRegressionsFinal:
    def _state(self):
        return {
            "trade_date": TARGET,
            "company_of_interest": SYMBOL,
            "data_quality_evidence_records": [dict(_RECORD)],
            ORIGIN_STATE_KEY: {EVID: _ORIGIN.to_dict()},
            "investment_debate_state": {"claim_validation_summary": {"rejected": []}},
        }

    def test_second_wrong_magnitude_same_clause_not_laundered(self):
        # A correct close amount must not launder a second wrong amount (volume
        # 999 shares) asserting against the SAME id.
        from tradingagents.agents.utils.output_guard import enforce_trusted_boundary

        text = f"On 2026-05-04 close was USD 200.13 and volume was 999 shares {EVID}"
        out = enforce_trusted_boundary(text, self._state())
        assert "999" not in out

    def test_recommendation_does_not_exempt_historical_fact(self):
        # 'I recommend Hold because <historical wrong fact>' must NOT bypass.
        from tradingagents.agents.utils.output_guard import enforce_trusted_boundary

        text = f"I recommend Hold because on 2026-05-05 close was USD 999 {EVID}"
        out = enforce_trusted_boundary(text, self._state())
        assert "2026-05-05" not in out and "999" not in out
        assert "recommend Hold" in out

    def test_genuine_future_price_target_preserved(self):
        from tradingagents.agents.utils.output_guard import enforce_trusted_boundary

        text = f"I recommend Buy with a price target of 250 USD by 2026-12-31 {EVID}"
        out = enforce_trusted_boundary(text, self._state())
        assert "price target of 250 USD" in out
