"""Phase 3B offline tests for the authoritative Debate Evaluator decision rules.

No network, no LLM. Covers the exact 8-rule priority order, every branch,
priority collisions, complete Bull->Bear pair timing, malformed/out-of-order
turn sequences (fail-closed summary), and JSON-safe decision tracing.
"""

from __future__ import annotations

import json

import pytest

from tradingagents.debate.config import DebateTerminationConfig
from tradingagents.debate.evaluator import _SideReference, evaluate_round
from tradingagents.debate.evaluator_node import create_debate_evaluator_node
from tradingagents.debate.evidence_manifest import EvidenceManifest
from tradingagents.debate.models import (
    ConflictKind,
    ConflictRecord,
    ConflictSeverity,
    ConflictStatus,
    DebateRoute,
    DebateTurn,
    Stance,
    StopReason,
)

TARGET = "2026-05-13"

# A well-funded budget that never trips rule 2 for the branch tests.
_FUNDED_USAGE = {"calls": 2, "tokens": 100, "seconds": 10.0, "estimated": True}


def _cfg(**overrides) -> DebateTerminationConfig:
    base = {
        "enabled": True,
        "no_new_evidence_patience": 1,
        "stance_distance_threshold": 1.0,
        "confidence_delta_threshold": 0.25,
        "max_calls": 1_000_000,
        "max_tokens": 1_000_000,
        "max_time": 600.0,
        "max_debate_rounds": 100,
    }
    base.update(overrides)
    return DebateTerminationConfig.from_dict(base)


def _rec(evidence_id: str, status: str = "High", observed: str | None = "2026-05-01") -> dict:
    return {
        "evidence_id": evidence_id,
        "quality_status": status,
        "observed_at": observed,
        "value_raw": "1",
        "metric_name": "m",
        "unit_normalized": "",
    }


def _manifest(*records: dict) -> EvidenceManifest:
    return EvidenceManifest.from_records(list(records) if records else [_rec("ev:1")])


def _link(claim: str, *evidence_ids: str):
    from tradingagents.debate.models import ClaimEvidenceLink

    return ClaimEvidenceLink(claim=claim, evidence_ids=list(evidence_ids))


def _turn(
    speaker: str,
    stance: Stance = Stance.HOLD,
    confidence: float = 0.5,
    *,
    cited: list[str] | None = None,
    links: list | None = None,
    claims: list[str] | None = None,
) -> DebateTurn:
    return DebateTurn(
        speaker=speaker,
        content=f"{speaker} argument",
        stance=stance,
        confidence=confidence,
        cited_evidence_ids=list(cited or []),
        new_claims=list(claims or []),
        claim_evidence_links=list(links or []),
    )


def _bull_bear_round(
    bull: DebateTurn | None = None,
    bear: DebateTurn | None = None,
) -> list[DebateTurn]:
    return [bull if bull is not None else _turn("Bull"), bear if bear is not None else _turn("Bear")]


def _conflict(
    kind: ConflictKind = ConflictKind.INTERPRETIVE,
    severity: ConflictSeverity = ConflictSeverity.CRITICAL,
    status: ConflictStatus = ConflictStatus.OPEN,
) -> ConflictRecord:
    return ConflictRecord(
        conflict_id="c1",
        topic="t",
        bull_claim="b",
        bear_claim="r",
        kind=kind,
        severity=severity,
        status=status,
    )


def _call(
    *,
    round_index: int = 1,
    round_turns: list[DebateTurn] | None = None,
    previously_cited: set[str] | None = None,
    conflicts: list[ConflictRecord] | None = None,
    bull_stance: Stance = Stance.HOLD,
    bear_stance: Stance = Stance.HOLD,
    bull_confidence: float = 0.5,
    bear_confidence: float = 0.5,
    cfg: DebateTerminationConfig | None = None,
    usage: dict | None = None,
    gate_verdict: str | None = "normal",
    gate_group_statuses: list[dict] | None = None,
    manifest: EvidenceManifest | None = None,
    manifest_index: dict | None = None,
    prior_no_new: int = 0,
    prior_bull=None,
    prior_bear=None,
    bull_evidence=(),
    bull_reasons=(),
    bear_evidence=(),
    bear_reasons=(),
):
    return evaluate_round(
        round_index=round_index,
        round_turns=round_turns if round_turns is not None else _bull_bear_round(),
        previously_cited=previously_cited or set(),
        manifest=manifest or _manifest(),
        target_date=TARGET,
        conflicts=conflicts or [],
        bull_stance=bull_stance,
        bear_stance=bear_stance,
        bull_confidence=bull_confidence,
        bear_confidence=bear_confidence,
        config=cfg or _cfg(),
        usage=usage if usage is not None else _FUNDED_USAGE,
        gate_verdict=gate_verdict,
        gate_group_statuses=gate_group_statuses or [],
        manifest_index=manifest_index,
        prior_no_new_evidence_streak=prior_no_new,
        prior_bull=prior_bull,
        prior_bear=prior_bear,
        bull_evidence_ids=bull_evidence,
        bull_reasons=bull_reasons,
        bear_evidence_ids=bear_evidence,
        bear_reasons=bear_reasons,
    )


# ---------------------------------------------------------------------------
# Priority: exact ordering
# ---------------------------------------------------------------------------


class TestPriorityOrder:
    def test_new_evidence_round_without_blocking_reaches_consensus(self):
        # new evidence present, but zero open blocking conflicts + close stances,
        # and no gate/budget/max -> consensus (rule 5) fires before rule 6.
        turns = _bull_bear_round(
            bull=_turn("Bull", Stance.BUY, 0.7, cited=["ev:1"], links=[_link("grow", "ev:1")]),
        )
        metrics, decision = _call(round_turns=turns, conflicts=[])
        assert decision.route == DebateRoute.SUMMARIZE
        assert decision.stop_reason == StopReason.CONSENSUS_REACHED
        assert metrics.new_valid_evidence_count == 1
        assert decision.trace[-1].rule == "consensus"

    def test_gate_blocked_outranks_everything(self):
        turns = _bull_bear_round(
            bull=_turn("Bull", Stance.BUY, 0.7, cited=["ev:1"], links=[_link("g", "ev:1")]),
        )
        # blocked gate must fire even with new evidence + rounds available.
        metrics, decision = _call(
            round_turns=turns,
            gate_verdict="blocked",
            conflicts=[],
        )
        assert decision.route == DebateRoute.STOP
        assert decision.stop_reason == StopReason.INSUFFICIENT_EVIDENCE
        assert decision.trace[0].rule == "gate_blocked"

    def test_critical_group_blocked_outranks(self):
        turns = _bull_bear_round()
        metrics, decision = _call(
            round_turns=turns,
            gate_verdict="normal",
            gate_group_statuses=[{"quality_status": "Blocked", "criticality": "critical"}],
        )
        assert decision.stop_reason == StopReason.INSUFFICIENT_EVIDENCE

    def test_budget_outranks_max_rounds(self):
        # Budget exhausted (reserve cannot be guaranteed) must fire before rule 3.
        cfg = _cfg(max_tokens=1000, reserved_summary_tokens=100, next_round_estimate_tokens=200, max_debate_rounds=100)
        usage = {"calls": 2, "tokens": 800, "seconds": 10.0, "estimated": True}
        metrics, decision = _call(round_index=100, cfg=cfg, usage=usage)
        assert decision.stop_reason == StopReason.BUDGET_EXHAUSTED
        assert decision.route == DebateRoute.SUMMARIZE
        assert decision.trace[1].rule == "budget"

    def test_max_rounds_outranks_no_new_evidence(self):
        # round_index >= max_debate_rounds and no new evidence: rule 3 fires.
        cfg = _cfg(max_debate_rounds=2, no_new_evidence_patience=1)
        metrics, decision = _call(round_index=2, cfg=cfg, prior_no_new=1)
        assert decision.stop_reason == StopReason.MAX_ROUNDS_REACHED
        assert decision.trace[2].rule == "max_rounds"

    def test_no_new_evidence_outranks_consensus(self):
        # No new evidence (patience 1) even if stances are close / no conflict:
        # rule 4 fires before rule 5.
        metrics, decision = _call(conflicts=[])
        assert decision.stop_reason == StopReason.NO_NEW_EVIDENCE
        assert decision.trace[3].rule == "no_new_evidence"

    def test_consensus_outranks_continue(self):
        # new evidence + zero blocking conflict + close stances + fundable ->
        # rule 5 consensus fires before rule 6 continue.
        turns = _bull_bear_round(
            bull=_turn("Bull", Stance.BUY, 0.7, cited=["ev:1"], links=[_link("g", "ev:1")]),
            bear=_turn("Bear", Stance.BUY, 0.7),
        )
        metrics, decision = _call(round_turns=turns, conflicts=[])
        assert decision.stop_reason == StopReason.CONSENSUS_REACHED

    def test_continue_new_evidence_outranks_material(self):
        # new evidence + blocking conflict + fundable -> rule 6 continue.
        conflicts = [_conflict()]
        turns = _bull_bear_round(
            bull=_turn("Bull", Stance.BUY, 0.7, cited=["ev:1"], links=[_link("g", "ev:1")]),
            bear=_turn("Bear", Stance.SELL, 0.5),
        )
        metrics, decision = _call(round_turns=turns, conflicts=conflicts)
        assert decision.stop_reason == StopReason.CONTINUE_FOR_NEW_EVIDENCE
        assert decision.route == DebateRoute.CONTINUE
        assert decision.next_speaker == "Bull"


# ---------------------------------------------------------------------------
# Scenario D & low-value round
# ---------------------------------------------------------------------------


class TestScenarioD:
    def test_no_new_evidence_rounds_to_no_new_evidence(self):
        metrics, decision = _call(conflicts=[])
        assert metrics.new_valid_evidence_count == 0
        assert decision.stop_reason == StopReason.NO_NEW_EVIDENCE

    def test_no_new_evidence_with_patience_1_from_prior_streak(self):
        metrics, decision = _call(prior_no_new=0, conflicts=[])
        assert decision.stop_reason == StopReason.NO_NEW_EVIDENCE

    def test_low_value_non_consensus_reaches_diminishing_returns(self):
        # New evidence absent (rule 4 suppressed by patience=2), no interpretive
        # conflict, no consensus -> rule 8 diminishing returns.
        cfg = _cfg(no_new_evidence_patience=2)
        conflicts = [_conflict(kind=ConflictKind.FACTUAL)]
        metrics, decision = _call(
            cfg=cfg,
            conflicts=conflicts,
            bull_stance=Stance.BUY,
            bear_stance=Stance.SELL,
            bull_confidence=0.9,
            bear_confidence=0.1,
        )
        assert decision.stop_reason == StopReason.DIMINISHING_RETURNS

    def test_first_zero_round_under_patience_2_not_terminated_by_rule4(self):
        cfg = _cfg(no_new_evidence_patience=2)
        metrics, decision = _call(cfg=cfg, conflicts=[_conflict(kind=ConflictKind.FACTUAL)])
        # rule 4 must NOT fire (streak 1 < patience 2); falls through.
        assert decision.trace[3].activated is False
        assert decision.stop_reason != StopReason.NO_NEW_EVIDENCE


# ---------------------------------------------------------------------------
# Scenario E: consensus
# ---------------------------------------------------------------------------


class TestScenarioE:
    def test_close_stances_no_conflict_consensus(self):
        turns = _bull_bear_round(
            bull=_turn("Bull", Stance.BUY, 0.7, cited=["ev:1"], links=[_link("g", "ev:1")]),
        )
        metrics, decision = _call(
            round_turns=turns,
            bull_stance=Stance.BUY, bear_stance=Stance.BUY,
            bull_confidence=0.7, bear_confidence=0.75, conflicts=[],
        )
        assert decision.stop_reason == StopReason.CONSENSUS_REACHED

    def test_open_conflict_prevents_consensus(self):
        metrics, decision = _call(
            bull_stance=Stance.BUY, bear_stance=Stance.BUY,
            bull_confidence=0.7, bear_confidence=0.75,
            conflicts=[_conflict()],
        )
        assert decision.stop_reason != StopReason.CONSENSUS_REACHED

    def test_large_confidence_gap_prevents_consensus(self):
        turns = _bull_bear_round(
            bull=_turn("Bull", Stance.BUY, 0.9, cited=["ev:1"], links=[_link("g", "ev:1")]),
        )
        metrics, decision = _call(
            round_turns=turns,
            bull_stance=Stance.BUY, bear_stance=Stance.BUY,
            bull_confidence=0.9, bear_confidence=0.1, conflicts=[],
        )
        assert decision.stop_reason != StopReason.CONSENSUS_REACHED

    def test_rating_distance_beyond_threshold_prevents_consensus(self):
        turns = _bull_bear_round(
            bull=_turn("Bull", Stance.BUY, 0.7, cited=["ev:1"], links=[_link("g", "ev:1")]),
        )
        metrics, decision = _call(
            round_turns=turns,
            bull_stance=Stance.BUY, bear_stance=Stance.SELL,
            bull_confidence=0.7, bear_confidence=0.7, conflicts=[],
        )
        assert decision.stop_reason != StopReason.CONSENSUS_REACHED


# ---------------------------------------------------------------------------
# Scenario F: budget / manager-reserve boundary
# ---------------------------------------------------------------------------


class TestScenarioF:
    def test_budget_exhausted_route(self):
        cfg = _cfg(max_tokens=1000, reserved_summary_tokens=100, next_round_estimate_tokens=200)
        usage = {"calls": 2, "tokens": 800, "seconds": 10.0, "estimated": True}
        metrics, decision = _call(cfg=cfg, usage=usage)
        assert decision.route == DebateRoute.SUMMARIZE
        assert decision.stop_reason == StopReason.BUDGET_EXHAUSTED

    def test_manager_reserve_boundary_triggers_before_another_call(self):
        # enough calls for the next round, but not enough tokens left to
        # guarantee the summary reserve -> budget_exhausted.
        cfg = _cfg(max_tokens=500, reserved_summary_tokens=100, next_round_estimate_tokens=200)
        usage = {"calls": 2, "tokens": 250, "seconds": 10.0, "estimated": True}
        metrics, decision = _call(cfg=cfg, usage=usage)
        assert decision.stop_reason == StopReason.BUDGET_EXHAUSTED

    def test_reserve_guarantee_not_yet_exhausted_continues_when_possible(self):
        cfg = _cfg(max_tokens=1000, reserved_summary_tokens=100, next_round_estimate_tokens=200)
        usage = {"calls": 2, "tokens": 250, "seconds": 10.0, "estimated": True}
        conflicts = [_conflict()]
        turns = _bull_bear_round(
            bull=_turn("Bull", Stance.BUY, 0.7, cited=["ev:1"], links=[_link("g", "ev:1")]),
            bear=_turn("Bear", Stance.SELL, 0.5),
        )
        metrics, decision = _call(cfg=cfg, usage=usage, round_turns=turns, conflicts=conflicts)
        assert decision.stop_reason == StopReason.CONTINUE_FOR_NEW_EVIDENCE

    def test_usage_estimated_flag_serialized(self):
        cfg = _cfg(max_tokens=1000, reserved_summary_tokens=100, next_round_estimate_tokens=200)
        usage = {"calls": 2, "tokens": 800, "seconds": 10.0, "estimated": True}
        metrics, decision = _call(cfg=cfg, usage=usage)
        assert metrics.estimated is True
        assert metrics.calls == 2


# ---------------------------------------------------------------------------
# Rule 7 material change and rule 8
# ---------------------------------------------------------------------------


def _prior(stance, confidence, *, evidence=(), reasons=()):
    return _SideReference(stance=stance, confidence=confidence, evidence_ids=list(evidence), reasons=list(reasons))


class TestMaterialChangeRules:
    def test_interpretive_open_plus_material_plus_budget_continues(self):
        cfg = _cfg(no_new_evidence_patience=2)
        prior_bull = _prior(Stance.HOLD, 0.5)
        # current Bull stance moved Buy (material).
        metrics, decision = _call(
            cfg=cfg,
            round_index=2,
            conflicts=[_conflict()],
            bull_stance=Stance.BUY,
            bull_confidence=0.7,
            prior_bull=prior_bull,
            bull_evidence=["ev:1"],
        )
        assert decision.stop_reason == StopReason.CONTINUE_FOR_MATERIAL_CHANGE
        assert decision.route == DebateRoute.CONTINUE
        assert decision.next_speaker == "Bull"

    def test_no_material_change_no_continue(self):
        cfg = _cfg(no_new_evidence_patience=2)
        prior_bull = _prior(Stance.HOLD, 0.5, evidence=["ev:1"])
        # current Bull unchanged (Hold/0.5, same evidence) -> not material.
        metrics, decision = _call(
            cfg=cfg,
            round_index=2,
            conflicts=[_conflict()],
            bull_stance=Stance.HOLD,
            bull_confidence=0.5,
            prior_bull=prior_bull,
            bull_evidence=["ev:1"],
            bull_reasons=[],
        )
        assert decision.stop_reason == StopReason.DIMINISHING_RETURNS

    def test_bear_material_change_counts_even_if_bull_static(self):
        cfg = _cfg(no_new_evidence_patience=2)
        prior_bear = _prior(Stance.HOLD, 0.5)
        metrics, decision = _call(
            cfg=cfg,
            round_index=2,
            conflicts=[_conflict()],
            bear_stance=Stance.SELL,
            bear_confidence=0.7,
            prior_bear=prior_bear,
            bear_evidence=["ev:2"],
        )
        assert decision.stop_reason == StopReason.CONTINUE_FOR_MATERIAL_CHANGE

    def test_same_speaker_prior_required(self):
        cfg = _cfg(no_new_evidence_patience=2)
        # prior_bull is None (round 1), so even a directional first round has no
        # material change -> no continue under rule 7.
        metrics, decision = _call(
            cfg=cfg,
            conflicts=[_conflict()],
            bull_stance=Stance.BUY,
            bull_confidence=0.9,
        )
        assert decision.stop_reason != StopReason.CONTINUE_FOR_MATERIAL_CHANGE

    def test_cross_speaker_change_is_not_material(self):
        # Bull moved but only the Bear's prior exists; Bull has no own prior, so
        # no material change. Rule 7 must not fire.
        cfg = _cfg(no_new_evidence_patience=2)
        prior_bear = _prior(Stance.HOLD, 0.5)
        metrics, decision = _call(
            cfg=cfg,
            round_index=2,
            conflicts=[_conflict()],
            bull_stance=Stance.BUY,
            bull_confidence=0.9,
            prior_bear=prior_bear,  # Bear prior only; Bull has none
        )
        assert decision.stop_reason != StopReason.CONTINUE_FOR_MATERIAL_CHANGE

    def test_rephrasing_same_stance_same_reasons_is_not_material(self):
        cfg = _cfg(no_new_evidence_patience=2)
        prior_bull = _prior(Stance.BUY, 0.7, evidence=["ev:1"], reasons=["r1"])
        metrics, decision = _call(
            cfg=cfg,
            round_index=2,
            conflicts=[_conflict()],
            bull_stance=Stance.BUY,
            bull_confidence=0.7,
            prior_bull=prior_bull,
            bull_evidence=["ev:1"],
            bull_reasons=["r1"],
        )
        assert decision.stop_reason == StopReason.DIMINISHING_RETURNS


class TestActionOnlyDisagreement:
    def test_action_only_does_not_fabricate_blocking_conflict(self):
        # Bull and Bear recommend different actions with no *tracked* conflict.
        # Even with new evidence present, that divergence is not an interpretive
        # or factual blocking conflict, so the debate must NOT keep going via
        # any continue rule.
        turns = _bull_bear_round(
            bull=_turn("Bull", Stance.BUY, 0.7, cited=["ev:1"], links=[_link("g", "ev:1")]),
        )
        metrics, decision = _call(
            round_turns=turns,
            bull_stance=Stance.BUY, bear_stance=Stance.SELL,
            bull_confidence=0.7, bear_confidence=0.7, conflicts=[],
        )
        assert decision.route == DebateRoute.SUMMARIZE
        # No continue rule fired.
        assert decision.trace[-1].rule == "diminishing_returns"

    def test_minor_factual_conflict_does_not_block(self):
        # Only a MINOR conflict -> not blocking -> consensus path.
        turns = _bull_bear_round(
            bull=_turn("Bull", Stance.BUY, 0.7, cited=["ev:1"], links=[_link("g", "ev:1")]),
        )
        metrics, decision = _call(
            round_turns=turns,
            bull_stance=Stance.BUY, bear_stance=Stance.BUY,
            bull_confidence=0.7, bear_confidence=0.7,
            conflicts=[_conflict(kind=ConflictKind.FACTUAL, severity=ConflictSeverity.MINOR)],
        )
        assert decision.stop_reason == StopReason.CONSENSUS_REACHED


# ---------------------------------------------------------------------------
# Complete-pair timing + malformed order (via the node)
# ---------------------------------------------------------------------------


class TestCompletePairTiming:
    def _state(self, turns):
        return {
            "investment_debate_state": {"turns": turns, "count": len(turns)},
            "trade_date": TARGET,
            "data_quality_verdict": "normal",
            "data_quality_group_statuses": [],
            "data_quality_evidence_records": [_rec("ev:1")],
        }

    def test_evaluates_only_after_complete_bull_bear(self):
        node = create_debate_evaluator_node(config=_cfg(max_debate_rounds=100))
        turns = [
            _turn("Bull").to_dict(),
            _turn("Bear").to_dict(),
        ]
        out = node(self._state(turns))
        # A complete pair is evaluated; metrics appended.
        assert out["investment_debate_state"]["round_metrics"]
        assert out["debate_termination_decision"]["round_index"] == 1

    def test_empty_turns_fails_closed_to_summary(self):
        node = create_debate_evaluator_node(config=_cfg())
        out = node(self._state([]))
        assert out["debate_termination_decision"]["route"] == "summarize"
        assert out["debate_termination_decision"]["stop_reason"] == "malformed_debate_state"

    def test_odd_turns_fails_closed(self):
        node = create_debate_evaluator_node(config=_cfg())
        turns = [_turn("Bull").to_dict()]
        out = node(self._state(turns))
        assert out["debate_termination_decision"]["stop_reason"] == "malformed_debate_state"

    def test_bear_then_bull_out_of_order_fails_closed(self):
        node = create_debate_evaluator_node(config=_cfg())
        turns = [_turn("Bear").to_dict(), _turn("Bull").to_dict()]
        out = node(self._state(turns))
        assert out["debate_termination_decision"]["stop_reason"] == "malformed_debate_state"

    def test_bull_bull_sequence_fails_closed(self):
        node = create_debate_evaluator_node(config=_cfg())
        turns = [_turn("Bull").to_dict(), _turn("Bull").to_dict()]
        out = node(self._state(turns))
        assert out["debate_termination_decision"]["stop_reason"] == "malformed_debate_state"


# ---------------------------------------------------------------------------
# JSON trace serialization
# ---------------------------------------------------------------------------


class TestTraceJSON:
    def _sample_decision(self):
        turns = _bull_bear_round(
            bull=_turn("Bull", Stance.BUY, 0.7, cited=["ev:1"], links=[_link("g", "ev:1")]),
            bear=_turn("Bear", Stance.SELL, 0.5),
        )
        _, decision = _call(round_turns=turns, conflicts=[_conflict()])
        return decision

    def test_decision_serializes_to_json(self):
        decision = self._sample_decision()
        payload = json.dumps(decision.to_dict())
        assert json.loads(payload)

    def test_trace_entries_all_json_safe(self):
        decision = self._sample_decision()
        for entry in decision.trace:
            assert json.dumps(entry.to_dict())
            assert isinstance(entry.activated, bool)
            assert isinstance(entry.thresholds, dict)
            assert isinstance(entry.actual, dict)
            assert isinstance(entry.evidence_ids, list)

    def test_trace_covers_all_rules_in_order(self):
        decision = self._sample_decision()
        rules = [e.rule for e in decision.trace]
        assert rules[:3] == ["gate_blocked", "budget", "max_rounds"]
        assert rules[3] in ("no_new_evidence", "consensus", "continue_new_evidence", "continue_material", "diminishing_returns")

    def test_metrics_json_safe(self):
        turns = _bull_bear_round(
            bull=_turn("Bull", Stance.BUY, 0.7, cited=["ev:1"], links=[_link("g", "ev:1")]),
        )
        metrics, _ = _call(round_turns=turns, conflicts=[])
        assert json.dumps(metrics.to_dict())


# ---------------------------------------------------------------------------
# Debate Evaluator routing after the node
# ---------------------------------------------------------------------------


class TestEvaluatorRouter:
    """``should_continue_after_debate_evaluator`` maps the decision to a node."""

    def _logic(self):
        from tradingagents.graph.conditional_logic import ConditionalLogic

        return ConditionalLogic()

    def test_continue_bull_routes_to_bull(self):
        state = {"debate_termination_decision": {"route": "continue", "next_speaker": "Bull"}}
        assert self._logic().should_continue_after_debate_evaluator(state) == "Bull Researcher"

    def test_continue_bear_routes_to_bear(self):
        state = {"debate_termination_decision": {"route": "continue", "next_speaker": "Bear"}}
        assert self._logic().should_continue_after_debate_evaluator(state) == "Bear Researcher"

    def test_summarize_routes_to_manager(self):
        state = {"debate_termination_decision": {"route": "summarize", "next_speaker": ""}}
        assert self._logic().should_continue_after_debate_evaluator(state) == "Research Manager"

    def test_stop_routes_to_manager(self):
        state = {"debate_termination_decision": {"route": "stop", "next_speaker": ""}}
        assert self._logic().should_continue_after_debate_evaluator(state) == "Research Manager"

    @pytest.mark.parametrize("decision", [None, {}, {"route": "continue", "next_speaker": "X"}, {"route": "continue"}, {"route": "jump"}])
    def test_missing_or_unknown_fails_closed_to_manager(self, decision):
        logic = self._logic()
        if decision is None:
            assert logic.should_continue_after_debate_evaluator({}) == "Research Manager"
        else:
            assert logic.should_continue_after_debate_evaluator({"debate_termination_decision": decision}) == "Research Manager"

    def test_empty_decision_fails_closed(self):
        assert self._logic().should_continue_after_debate_evaluator({"debate_termination_decision": {}}) == "Research Manager"
