"""Phase 4A offline tests for the comparison schemas and metric formulas.

Covers validation, zero-denominator behavior, measured-vs-estimated separation,
false-strong-conclusion derivation (never from prose), evidence-citation
coverage from valid cited IDs, human-traceability pending semantics, and stable
JSON round-tripping. No network, no LLM, no wall-clock dependence.
"""

from __future__ import annotations

import json

import pytest

from tradingagents.comparison.metric_formulas import (
    compute_case_aggregate,
    early_stop_rate,
    evidence_citation_coverage,
    false_strong_conclusion_rate,
    ratio,
    traceability_mean,
)
from tradingagents.comparison.schemas import (
    INPUT_EXHAUSTED_STOP_REASON,
    CaseIdentity,
    CaseResult,
    StrategyKey,
    TraceabilityStatus,
    traceability_scores_for_dimensions,
)


def _identity(**over) -> CaseIdentity:
    base = {
        "ticker": "AAPL",
        "target_date": "2026-05-13",
        "evidence_snapshot_id": "snap-1",
        "policy_version": "1.0",
    }
    base.update(over)
    return CaseIdentity(**base)


def _ok_result(**over) -> CaseResult:
    base = {
        "strategy": StrategyKey.DYNAMIC,
        "identity": _identity(),
        "llm_calls": 6,
        "tool_calls": 3,
        "input_tokens": 1000,
        "output_tokens": 500,
        "total_tokens": 1500,
        "elapsed_seconds": 120.0,
        "debate_rounds": 3,
        "early_stopped": True,
        "stop_reason": "no_new_evidence",
        "valid_cited_evidence_ids": ["ev:1", "ev:2"],
        "total_eligible_evidence_ids": 4,
        "strong_conclusion": True,
        "gate_verdict": "normal",
        "quality_status": "High",
        "estimated": False,
        "traceability_status": TraceabilityStatus.PENDING,
        "traceability_scores": [],
    }
    base.update(over)
    return CaseResult(**base)


# ---------------------------------------------------------------------------
# CaseIdentity validation
# ---------------------------------------------------------------------------


def test_identity_rejects_empty_fields():
    for field in ("ticker", "target_date", "evidence_snapshot_id", "policy_version"):
        with pytest.raises(ValueError):
            _identity(**{field: ""})
        with pytest.raises(ValueError):
            _identity(**{field: "   "})


def test_identity_round_trips_json():
    ident = _identity()
    assert CaseIdentity.from_dict(json.loads(json.dumps(ident.to_dict()))) == ident


def test_identity_matches_is_exact():
    assert _identity().matches(_identity())
    assert not _identity().matches(_identity(ticker="MSFT"))
    assert not _identity().matches(_identity(target_date="2026-05-14"))
    assert not _identity().matches(_identity(evidence_snapshot_id="snap-2"))
    assert not _identity().matches(_identity(policy_version="2.0"))


# ---------------------------------------------------------------------------
# CaseResult validation
# ---------------------------------------------------------------------------


def test_result_rejects_negative_counters():
    for field in ("llm_calls", "tool_calls", "input_tokens", "output_tokens",
                  "total_tokens", "debate_rounds", "total_eligible_evidence_ids"):
        with pytest.raises(ValueError):
            _ok_result(**{field: -1})


def test_result_rejects_negative_elapsed():
    with pytest.raises(ValueError):
        _ok_result(elapsed_seconds=-0.1)


def test_result_rejects_out_of_range_traceability_score():
    with pytest.raises(ValueError):
        _ok_result(traceability_scores=[1.5])
    with pytest.raises(ValueError):
        _ok_result(traceability_scores=[-0.1])


def test_result_allows_none_traceability_scores():
    result = _ok_result(traceability_scores=[None, 0.8, None, 0.2])
    assert result.traceability_scores == [None, 0.8, None, 0.2]


def test_result_round_trips_json():
    result = _ok_result()
    assert CaseResult.from_dict(json.loads(json.dumps(result.to_dict()))) == result


def test_measured_vs_estimated_flag_is_preserved():
    estimated = _ok_result(estimated=True)
    measured = _ok_result(estimated=False)
    assert estimated.estimated is True
    assert measured.estimated is False
    out = json.loads(json.dumps(estimated.to_dict()))
    assert out["estimated"] is True


def test_total_tokens_is_authoritative():
    result = _ok_result(input_tokens=1000, output_tokens=500, total_tokens=1500)
    assert result.summary_token_total == 1500


# ---------------------------------------------------------------------------
# Ratio + zero-denominator behavior
# ---------------------------------------------------------------------------


def test_ratio_normal():
    assert ratio(3, 4) == 0.75


def test_ratio_zero_denominator_is_none():
    assert ratio(3, 0) is None
    assert ratio(0, 0) is None


def test_early_stop_rate_percentage():
    assert early_stop_rate(True) == 1.0
    assert early_stop_rate(False) == 0.0


def test_evidence_citation_coverage():
    assert evidence_citation_coverage(2, 4) == 0.5
    assert evidence_citation_coverage(0, 4) == 0.0
    assert evidence_citation_coverage(2, 0) is None


# ---------------------------------------------------------------------------
# False-strong-conclusion (machine-readable flag + gate/quality outcome)
# ---------------------------------------------------------------------------


def test_false_strong_rate_formula():
    assert false_strong_conclusion_rate(1, 4) == 0.25
    assert false_strong_conclusion_rate(0, 4) == 0.0
    assert false_strong_conclusion_rate(1, 0) is None


@pytest.mark.parametrize(
    "gate,quality,strong,expected",
    [
        # strong on safe ground -> NOT false
        ("normal", "High", True, 0),
        ("normal", "Medium", True, 0),
        # strong on degraded/blocked -> false
        ("degraded", "Medium", True, 1),
        ("blocked", "Medium", True, 1),
        # strong on Low quality -> false (no evidentiary right)
        ("normal", "Low", True, 1),
        ("normal", "Blocked", True, 1),
        # no strong flag -> never false
        ("degraded", "Medium", False, 0),
        # unknown quality alone is not a false-strong (need an explicit flag)
        ("normal", "", True, 0),
    ],
)
def test_false_strong_is_derived_from_flag_plus_outcome(gate, quality, strong, expected):
    result = _ok_result(
        strong_conclusion=strong, gate_verdict=gate, quality_status=quality
    )
    agg = compute_case_aggregate(result)
    assert agg.false_strong_conclusion_count == expected
    if strong and expected == 0:
        assert agg.false_strong_conclusion_rate == 0.0


# ---------------------------------------------------------------------------
# Traceability pending semantics
# ---------------------------------------------------------------------------


def test_traceability_mean_of_scores():
    # Two recorded (0.8, 0.2) + one None -> mean of recorded only.
    assert traceability_mean([0.8, None, 0.2]) == pytest.approx(0.5)


def test_traceability_pending_when_unscored():
    result = _ok_result(traceability_scores=[], traceability_status=TraceabilityStatus.PENDING)
    agg = result.as_aggregate()
    assert agg.traceability_mean is None
    assert agg.traceability_status == TraceabilityStatus.PENDING


def test_traceability_scored_mean():
    result = _ok_result(
        traceability_scores=[0.8, 0.6, 0.4, 0.2],
        traceability_status=TraceabilityStatus.SCORED,
    )
    agg = result.as_aggregate()
    assert agg.traceability_mean == pytest.approx(0.5)
    assert agg.traceability_status == TraceabilityStatus.SCORED


# ---------------------------------------------------------------------------
# Scored traceability requires exactly four non-null scores in
# TRACEABILITY_DIMENSIONS order (correction round)
# ---------------------------------------------------------------------------


def _scored(**over) -> CaseResult:
    base = {
        "strategy": StrategyKey.DYNAMIC,
        "identity": _identity(),
        "llm_calls": 6,
        "traceability_status": TraceabilityStatus.SCORED,
        "traceability_scores": [0.8, 0.6, 0.4, 0.2],
    }
    base.update(over)
    return CaseResult(**base)


def test_scored_traceability_requires_exactly_four_scores():
    assert _scored().traceability_status == TraceabilityStatus.SCORED


@pytest.mark.parametrize(
    "scores",
    [
        [0.8, 0.6, 0.4],  # missing one dimension
        [0.8, 0.6, 0.4, 0.2, 0.1],  # extra dimension
        [0.8, None, 0.4, 0.2],  # null dimension
        [None, None, None, None],  # all null
        [],  # no scores at all
    ],
)
def test_scored_traceability_rejects_wrong_count_or_null(scores):
    with pytest.raises(ValueError):
        _scored(traceability_scores=scores)


def test_scored_traceability_rejects_out_of_range():
    with pytest.raises(ValueError):
        _scored(traceability_scores=[0.8, 0.6, 0.4, 1.5])


def test_pending_traceability_is_allowed_with_partial_or_none_scores():
    # PENDING is unscored; a partial/None score shape is allowed and reports
    # no mean (it must never be presented as an authoritative rating).
    result = _ok_result(
        traceability_scores=[0.8, None, 0.4, 0.2],
        traceability_status=TraceabilityStatus.PENDING,
    )
    assert result.traceability_status == TraceabilityStatus.PENDING
    assert result.as_aggregate().traceability_mean is None


def test_pending_traceability_mean_is_none_even_with_scores():
    # A PENDING result carrying a full score set must still report no mean:
    # the human has not scored it, so it can never be presented as rated.
    result = _ok_result(
        traceability_scores=[0.8, 0.6, 0.4, 0.2],
        traceability_status=TraceabilityStatus.PENDING,
    )
    assert result.as_aggregate().traceability_mean is None


# ---------------------------------------------------------------------------
# Dimension-keyed scoring helper: no missing/extra/duplicate/reordered dims
# ---------------------------------------------------------------------------


def test_dimension_scores_helper_accepts_valid_map_in_order():
    scored = traceability_scores_for_dimensions(
        {
            "source_attribution": 0.9,
            "reasoning_clarity": 0.8,
            "evidence_groundedness": 0.7,
            "decision_auditability": 0.6,
        }
    )
    assert scored == [0.9, 0.8, 0.7, 0.6]
    # The returned positional list is exactly the SCORED shape required.
    assert _scored(traceability_scores=scored).traceability_status == TraceabilityStatus.SCORED


def test_dimension_scores_helper_accepts_ordered_pairs():
    pairs = [
        ("source_attribution", 0.9),
        ("reasoning_clarity", 0.8),
        ("evidence_groundedness", 0.7),
        ("decision_auditability", 0.6),
    ]
    assert traceability_scores_for_dimensions(pairs) == [0.9, 0.8, 0.7, 0.6]


def test_dimension_scores_helper_rejects_missing_dimension():
    with pytest.raises(ValueError):
        traceability_scores_for_dimensions(
            {
                "source_attribution": 0.9,
                "reasoning_clarity": 0.8,
                "evidence_groundedness": 0.7,
            }
        )


def test_dimension_scores_helper_rejects_extra_dimension():
    with pytest.raises(ValueError):
        traceability_scores_for_dimensions(
            {
                "source_attribution": 0.9,
                "reasoning_clarity": 0.8,
                "evidence_groundedness": 0.7,
                "decision_auditability": 0.6,
                "novelty": 0.5,
            }
        )


def test_dimension_scores_helper_rejects_reordered_dimensions():
    with pytest.raises(ValueError):
        traceability_scores_for_dimensions(
            {
                "reasoning_clarity": 0.8,
                "source_attribution": 0.9,
                "evidence_groundedness": 0.7,
                "decision_auditability": 0.6,
            }
        )


def test_dimension_scores_helper_rejects_duplicate_dimensions():
    with pytest.raises(ValueError):
        traceability_scores_for_dimensions(
            [
                ("source_attribution", 0.9),
                ("source_attribution", 0.8),
                ("reasoning_clarity", 0.7),
                ("evidence_groundedness", 0.6),
                ("decision_auditability", 0.5),
            ]
        )


def test_dimension_scores_helper_rejects_out_of_range():
    with pytest.raises(ValueError):
        traceability_scores_for_dimensions(
            {
                "source_attribution": 0.9,
                "reasoning_clarity": 0.8,
                "evidence_groundedness": 0.7,
                "decision_auditability": 1.2,
            }
        )


# ---------------------------------------------------------------------------
# stop_reason serialization (correction round)
# ---------------------------------------------------------------------------


def test_stop_reason_round_trips_json():
    result = _ok_result(stop_reason="budget_exhausted")
    restored = CaseResult.from_dict(json.loads(json.dumps(result.to_dict())))
    assert restored.stop_reason == "budget_exhausted"


def test_stop_reason_is_preserved_through_aggregate():
    result = _ok_result(stop_reason="no_new_evidence")
    assert result.as_aggregate().stop_reason == "no_new_evidence"


# ---------------------------------------------------------------------------
# Fail-closed strategy / early_stopped / stop_reason consistency (narrow round)
# ---------------------------------------------------------------------------


def test_fixed_strategy_cannot_be_early_stopped():
    # A FIXED (max-rounds) result is by construction never an early stop; a
    # contradictory combination is rejected so it can never reach a report.
    with pytest.raises(ValueError):
        _ok_result(strategy=StrategyKey.FIXED, early_stopped=True,
                   stop_reason="no_new_evidence")


def test_early_stopped_requires_a_stop_reason():
    # early_stopped=True with an empty stop_reason is contradictory (a genuine
    # stop must carry its actual deterministic reason).
    with pytest.raises(ValueError):
        _ok_result(early_stopped=True, stop_reason="")


@pytest.mark.parametrize(
    "reason",
    [
        INPUT_EXHAUSTED_STOP_REASON,  # input exhaustion is never an early stop
        "max_rounds_reached",  # the hard cap is never an early stop
        "continue_for_new_evidence",  # a continue route is never a stop
        "unknown_reason",  # unrecognized reason must fail closed
        "MALFORMED_STATE",  # an unknown label rejected, not guessed
    ],
)
def test_early_stopped_rejects_non_genuine_stop_reason(reason):
    with pytest.raises(ValueError):
        _ok_result(early_stopped=True, stop_reason=reason)


def test_early_stopped_accepts_genuine_dynamic_reason():
    # Every genuine dynamic early-stop reason is accepted; these are exactly
    # the reasons the runner produces for a real policy termination.
    for reason in (
        "insufficient_evidence",
        "budget_exhausted",
        "no_new_evidence",
        "consensus_reached",
        "diminishing_returns",
    ):
        result = _ok_result(early_stopped=True, stop_reason=reason)
        assert result.early_stopped is True
        assert result.stop_reason == reason


def test_fixed_not_early_stopped_is_valid_with_any_reason():
    # A FIXED result that is not early-stopped legitimately carries the
    # max-rounds cap or the input-exhaustion reason; it is never rejected.
    fixed_cap = _ok_result(strategy=StrategyKey.FIXED, early_stopped=False,
                           stop_reason="max_rounds_reached")
    assert fixed_cap.early_stopped is False
    assert fixed_cap.stop_reason == "max_rounds_reached"
    fixed_exhaust = _ok_result(strategy=StrategyKey.FIXED, early_stopped=False,
                               stop_reason=INPUT_EXHAUSTED_STOP_REASON)
    assert fixed_exhaust.early_stopped is False


def test_dynamic_not_early_stopped_accepts_input_exhaustion():
    # A DYNAMIC result that exhausts its scripted input is not early-stopped.
    result = _ok_result(early_stopped=False,
                        stop_reason=INPUT_EXHAUSTED_STOP_REASON)
    assert result.early_stopped is False
    assert result.stop_reason == INPUT_EXHAUSTED_STOP_REASON


def test_early_stopped_rejected_through_from_dict_deserialization():
    # JSON deserialization must fail closed too: a contradiction stored on disk
    # is rejected on load rather than silently propagated into a report.
    data = _ok_result().to_dict()
    data["strategy"] = StrategyKey.FIXED.value
    data["stop_reason"] = "no_new_evidence"
    with pytest.raises(ValueError):
        CaseResult.from_dict(data)


def test_early_stopped_unknown_reason_rejected_through_from_dict():
    data = _ok_result().to_dict()
    data["stop_reason"] = "not_a_real_stop"
    data["early_stopped"] = True
    with pytest.raises(ValueError):
        CaseResult.from_dict(data)


def test_early_stopped_json_round_trip_preserves_genuine_reason():
    # A valid genuine early stop survives a full JSON round trip.
    result = _ok_result(early_stopped=True, stop_reason="budget_exhausted")
    restored = CaseResult.from_dict(json.loads(json.dumps(result.to_dict())))
    assert restored.early_stopped is True
    assert restored.stop_reason == "budget_exhausted"
    assert restored.as_aggregate().early_stop_rate == 1.0
    assert restored.as_aggregate().stop_reason == "budget_exhausted"


# ---------------------------------------------------------------------------
# Aggregate derivation
# ---------------------------------------------------------------------------


def test_aggregate_derives_expected_values():
    agg = compute_case_aggregate(_ok_result())
    assert agg.llm_calls == 6
    assert agg.debate_rounds == 3
    assert agg.early_stop_rate == 1.0
    assert agg.evidence_citation_coverage == pytest.approx(0.5)
    assert agg.strong_conclusion_count == 1
    assert agg.traceability_mean is None
    # Tool calls + usage provenance are preserved through the aggregate.
    assert agg.tool_calls == 3
    assert agg.tool_usage_estimated is False


def test_aggregate_preserves_usage_provenance_estimated():
    # A per-case estimated flag must never be presented as measured.
    estimated = compute_case_aggregate(_ok_result(estimated=True))
    measured = compute_case_aggregate(_ok_result(estimated=False))
    assert estimated.tool_usage_estimated is True
    assert measured.tool_usage_estimated is False


def test_aggregate_round_trips_json():
    agg = compute_case_aggregate(_ok_result())
    restored = compute_case_aggregate(CaseResult.from_dict(json.loads(json.dumps(
        _ok_result().to_dict())))
    )
    assert restored.identity == agg.identity
    assert restored.llm_calls == agg.llm_calls


def test_aggregate_serializes_usage_provenance():
    agg = compute_case_aggregate(_ok_result(estimated=True, tool_calls=3))
    data = json.loads(json.dumps(agg.to_dict()))
    assert data["tool_calls"] == 3
    assert data["tool_usage_estimated"] is True
    # Round-trip from the serialized dict restores tool calls + provenance.
    restored = compute_case_aggregate(
        CaseResult.from_dict(
            json.loads(json.dumps(_ok_result(estimated=True, tool_calls=3).to_dict()))
        )
    )
    assert restored.tool_calls == 3
    assert restored.tool_usage_estimated is True
