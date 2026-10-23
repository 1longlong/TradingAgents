"""Phase 4A offline tests for the comparison runner: pairing, aggregation,
reproducibility, fail-closed malformed input, and scenarios D/E/F.

No network, no LLM, no wall-clock dependence. The runner replays scripted
fixtures through the pure debate evaluator for BOTH strategies with an identical
case identity and evidence snapshot; a mismatch fails closed with
:class:`PairingError`.
"""

from __future__ import annotations

import json

import pytest

from tradingagents.comparison.fixtures import (
    ALL_SCRIPTED_CASES,
    case_budget_protection,
    case_input_exhaustion,
    case_new_evidence_extension,
    case_no_new_evidence,
)
from tradingagents.comparison.report import (
    DEFAULT_OUTPUT_DIR,
    write_comparison_report,
)
from tradingagents.comparison.runner import pair_and_aggregate, replay_scripted_case
from tradingagents.comparison.schemas import (
    INPUT_EXHAUSTED_STOP_REASON,
    CaseIdentity,
    CaseResult,
    PairingError,
    StrategyKey,
)


def _same_identity_result(strategy: StrategyKey, overridable: CaseIdentity) -> CaseResult:
    return CaseResult(
        strategy=strategy,
        identity=overridable,
        llm_calls=1,
        tool_calls=0,
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        elapsed_seconds=1.0,
        debate_rounds=1,
        early_stopped=False,
        valid_cited_evidence_ids=[],
        total_eligible_evidence_ids=0,
        strong_conclusion=False,
        gate_verdict="normal",
        quality_status="High",
    )


# ---------------------------------------------------------------------------
# Pairing / fail-closed
# ---------------------------------------------------------------------------


def test_pairing_accepts_matched_fixed_and_dynamic():
    ident = CaseIdentity("AAPL", "2026-05-13", "snap", "1.0")
    results = [
        _same_identity_result(StrategyKey.FIXED, ident),
        _same_identity_result(StrategyKey.DYNAMIC, ident),
    ]
    report = pair_and_aggregate(results)
    assert report.total_cases == 1


def test_pairing_fails_closed_when_strategy_missing():
    ident = CaseIdentity("AAPL", "2026-05-13", "snap", "1.0")
    with pytest.raises(PairingError):
        pair_and_aggregate([_same_identity_result(StrategyKey.FIXED, ident)])


def test_pairing_fails_closed_on_identity_mismatch():
    ident_a = CaseIdentity("AAPL", "2026-05-13", "snap", "1.0")
    ident_b = CaseIdentity("AAPL", "2026-05-13", "snap", "2.0")  # policy changed
    with pytest.raises(PairingError):
        pair_and_aggregate([
            _same_identity_result(StrategyKey.FIXED, ident_a),
            _same_identity_result(StrategyKey.DYNAMIC, ident_b),
        ])


def test_pairing_fails_closed_on_duplicate_strategy():
    ident = CaseIdentity("AAPL", "2026-05-13", "snap", "1.0")
    with pytest.raises(PairingError):
        pair_and_aggregate([
            _same_identity_result(StrategyKey.FIXED, ident),
            _same_identity_result(StrategyKey.DYNAMIC, ident),
            _same_identity_result(StrategyKey.FIXED, ident),
        ])


def test_pairing_fails_closed_on_different_evidence_snapshot():
    ident_a = CaseIdentity("AAPL", "2026-05-13", "snap-1", "1.0")
    ident_b = CaseIdentity("AAPL", "2026-05-13", "snap-2", "1.0")
    with pytest.raises(PairingError):
        pair_and_aggregate([
            _same_identity_result(StrategyKey.FIXED, ident_a),
            _same_identity_result(StrategyKey.DYNAMIC, ident_b),
        ])


# ---------------------------------------------------------------------------
# Reproducibility & deterministic JSON serialization
# ---------------------------------------------------------------------------


def test_replay_is_reproducible():
    first = replay_scripted_case(case_no_new_evidence())
    second = replay_scripted_case(case_no_new_evidence())
    assert json.dumps(first[StrategyKey.FIXED].to_dict(), sort_keys=True) == json.dumps(
        second[StrategyKey.FIXED].to_dict(), sort_keys=True
    )
    assert json.dumps(first[StrategyKey.DYNAMIC].to_dict(), sort_keys=True) == json.dumps(
        second[StrategyKey.DYNAMIC].to_dict(), sort_keys=True
    )


def test_json_round_trip_report():
    sc = case_new_evidence_extension()
    paired = replay_scripted_case(sc)
    report = pair_and_aggregate(list(paired.values()))
    data = report.to_dict()
    assert json.loads(json.dumps(data)) == data  # fully JSON-safe


# ---------------------------------------------------------------------------
# Scenario D — no new evidence -> dynamic early-stops
# ---------------------------------------------------------------------------


def test_scenario_d_dynamic_stops_early_on_no_new_evidence():
    paired = replay_scripted_case(case_no_new_evidence())
    fixed = paired[StrategyKey.FIXED]
    dynamic = paired[StrategyKey.DYNAMIC]
    # Both share the identical identity.
    assert fixed.identity.matches(dynamic.identity)
    # Fixed always runs the full cap; dynamic stops at round 1 (no new evidence).
    assert fixed.debate_rounds == 3
    assert dynamic.debate_rounds == 1
    assert dynamic.early_stopped is True
    assert fixed.early_stopped is False
    # Dynamic consumed fewer calls than fixed.
    assert dynamic.llm_calls < fixed.llm_calls
    # Zero valid-cited coverage (the cited ID is Low -> never counts).
    assert dynamic.valid_cited_evidence_ids == []


# ---------------------------------------------------------------------------
# Scenario E — new valid evidence extension
# ---------------------------------------------------------------------------


def test_scenario_e_dynamic_does_not_stop_early_when_new_evidence_arrives():
    paired = replay_scripted_case(case_new_evidence_extension())
    fixed = paired[StrategyKey.FIXED]
    dynamic = paired[StrategyKey.DYNAMIC]
    assert fixed.identity.matches(dynamic.identity)
    # New High/Medium evidence arrives and a blocking conflict remains, so the
    # dynamic policy does NOT stop early (it extends to absorb the new evidence).
    assert dynamic.debate_rounds == 3
    assert fixed.debate_rounds == 3
    assert dynamic.early_stopped is False
    # Both cite the new valid evidence ID -> citation coverage > 0.
    assert "2026-05-13/XYZ/market/yfinance/volume/1" in dynamic.valid_cited_evidence_ids


# ---------------------------------------------------------------------------
# Scenario F — budget protection
# ---------------------------------------------------------------------------


def test_scenario_f_dynamic_stops_to_protect_summary_reserve():
    sc = case_budget_protection()
    paired = replay_scripted_case(sc)
    fixed = paired[StrategyKey.FIXED]
    dynamic = paired[StrategyKey.DYNAMIC]
    assert fixed.identity.matches(dynamic.identity)
    # Dynamic stops at round 1 (budget exhaustion), never exceeding the cap or
    # consuming the summary reserve.
    assert dynamic.debate_rounds == 1
    assert dynamic.early_stopped is True
    assert fixed.debate_rounds == 3
    # Dynamic token spend keeps the summary reserve intact: used tokens plus the
    # reserved summary reserve must fit within the hard cap.
    assert dynamic.total_tokens + sc.config.reserved_summary_tokens <= sc.config.max_tokens
    # Fixed baseline runs every round and blows past what would preserve reserve.
    assert fixed.total_tokens > sc.config.max_tokens
    # Neither exceeds the hard call cap.
    assert dynamic.llm_calls <= sc.config.max_calls
    assert fixed.llm_calls <= sc.config.max_calls


# ---------------------------------------------------------------------------
# Aggregate across all three fixtures
# ---------------------------------------------------------------------------


def test_aggregate_across_all_fixtures():
    collective = []
    for build in ALL_SCRIPTED_CASES:
        paired = replay_scripted_case(build())
        collective.append(paired[StrategyKey.FIXED])
        collective.append(paired[StrategyKey.DYNAMIC])
    report = pair_and_aggregate(collective)
    assert report.total_cases == 3
    assert report.fixed_total_llm_calls > report.dynamic_total_llm_calls
    assert report.dynamic_early_stop_count == 2  # D and F early-stop
    assert report.dynamic_early_stop_rate == pytest.approx(2 / 3)
    # Tool calls are aggregated and summed deterministically.
    assert report.fixed_total_tool_calls == 0
    assert report.dynamic_total_tool_calls == 0
    # Every scripted fixture marks usage as estimated (never presented as measured).
    assert report.fixed_estimated_cases == 3
    assert report.dynamic_estimated_cases == 3


def test_aggregate_preserves_tool_calls_and_estimated_summary():
    ident = CaseIdentity("AAPL", "2026-05-13", "snap", "1.0")
    results = [
        CaseResult(
            strategy=StrategyKey.FIXED, identity=ident, llm_calls=6, tool_calls=4,
            total_tokens=6000, elapsed_seconds=90.0, debate_rounds=3,
            early_stopped=False, estimated=False,
        ),
        CaseResult(
            strategy=StrategyKey.DYNAMIC, identity=ident, llm_calls=2, tool_calls=0,
            total_tokens=2000, elapsed_seconds=30.0, debate_rounds=1,
            early_stopped=True, stop_reason="budget_exhausted", estimated=True,
        ),
    ]
    report = pair_and_aggregate(results)
    assert report.fixed_total_tool_calls == 4
    assert report.dynamic_total_tool_calls == 0
    # Honest per-strategy estimated-case counts.
    assert report.fixed_estimated_cases == 0
    assert report.dynamic_estimated_cases == 1
    data = report.to_dict()
    assert data["sums_and_rates"]["fixed_total_tool_calls"] == 4
    assert data["sums_and_rates"]["dynamic_total_tool_calls"] == 0
    assert data["sums_and_rates"]["fixed_estimated_cases"] == 0
    assert data["sums_and_rates"]["dynamic_estimated_cases"] == 1
    # Per-case dynamic aggregate carries tool calls + estimated provenance.
    dynamic_agg = report.paired_cases[0][2]
    assert dynamic_agg.tool_calls == 0
    assert dynamic_agg.tool_usage_estimated is True


# ---------------------------------------------------------------------------
# Scenario G — input exhaustion is NOT an early stop (correction round)
# ---------------------------------------------------------------------------


def test_scenario_g_input_exhaustion_is_not_a_dynamic_early_stop():
    paired = replay_scripted_case(case_input_exhaustion())
    fixed = paired[StrategyKey.FIXED]
    dynamic = paired[StrategyKey.DYNAMIC]
    assert fixed.identity.matches(dynamic.identity)
    # The scripted input provides fewer rounds than max_debate_rounds and the
    # evaluator keeps wanting to CONTINUE (new valid evidence + blocking
    # conflict), so it exhausts the input. This must NOT be reported as a
    # dynamic-policy early stop.
    assert dynamic.debate_rounds == 2
    assert dynamic.early_stopped is False
    assert dynamic.stop_reason == INPUT_EXHAUSTED_STOP_REASON
    assert fixed.early_stopped is False
    assert fixed.stop_reason == INPUT_EXHAUSTED_STOP_REASON
    # The policy genuinely was NOT satisfied: it wanted to add more evidence.
    assert "2026-05-13/GHI/market/yfinance/volume/1" in dynamic.valid_cited_evidence_ids


# ---------------------------------------------------------------------------
# Actual dynamic stop reasons are preserved in the result + report (correction)
# ---------------------------------------------------------------------------


def test_dynamic_stop_reason_is_preserved_in_result():
    for case, expected in (
        (case_no_new_evidence, "no_new_evidence"),
        (case_budget_protection, "budget_exhausted"),
        (case_new_evidence_extension, "max_rounds_reached"),
    ):
        dynamic = replay_scripted_case(case())[StrategyKey.DYNAMIC]
        assert dynamic.stop_reason == expected
        assert dynamic.early_stopped == (expected != "max_rounds_reached")


def test_max_rounds_cap_is_not_an_early_stop():
    # Scenario E runs the full max_debate_rounds; it is capped, not early.
    dynamic = replay_scripted_case(case_new_evidence_extension())[StrategyKey.DYNAMIC]
    assert dynamic.debate_rounds == 3
    assert dynamic.stop_reason == "max_rounds_reached"
    assert dynamic.early_stopped is False


def test_aggregate_preserves_stop_reason_counts():
    collective = []
    for build in ALL_SCRIPTED_CASES:
        paired = replay_scripted_case(build())
        collective.append(paired[StrategyKey.FIXED])
        collective.append(paired[StrategyKey.DYNAMIC])
    report = pair_and_aggregate(collective)
    # Fixed: every case completed the max-rounds cap.
    assert report.fixed_stop_reasons == {"max_rounds_reached": 3}
    # Dynamic: D stops on no_new_evidence, F on budget_exhausted, E on cap.
    assert report.dynamic_stop_reasons == {
        "budget_exhausted": 1,
        "max_rounds_reached": 1,
        "no_new_evidence": 1,
    }
    data = report.to_dict()
    assert data["sums_and_rates"]["fixed_stop_reasons"] == {"max_rounds_reached": 3}
    assert data["sums_and_rates"]["dynamic_stop_reasons"] == {
        "budget_exhausted": 1,
        "max_rounds_reached": 1,
        "no_new_evidence": 1,
    }


def test_input_exhaustion_in_aggregate_is_not_counted_as_early_stop():
    fixed = replay_scripted_case(case_input_exhaustion())[StrategyKey.FIXED]
    dynamic = replay_scripted_case(case_input_exhaustion())[StrategyKey.DYNAMIC]
    report = pair_and_aggregate([fixed, dynamic])
    assert report.dynamic_early_stop_count == 0
    assert report.dynamic_early_stop_rate == 0.0
    # Both strategies exhausted the scripted input (no policy stop).
    assert report.fixed_stop_reasons == {INPUT_EXHAUSTED_STOP_REASON: 1}
    assert report.dynamic_stop_reasons == {INPUT_EXHAUSTED_STOP_REASON: 1}


def test_report_json_serializes_stop_reason(tmp_path):
    sc = case_budget_protection()
    paired = replay_scripted_case(sc)
    report = pair_and_aggregate(list(paired.values()))
    paths = write_comparison_report(report, tmp_path)
    data = json.loads((tmp_path / paths["comparison_json"]).read_text(encoding="utf-8"))
    # The actual dynamic stop reason is machine-readable, not inferred.
    assert data["paired_cases"][0]["dynamic"]["stop_reason"] == "budget_exhausted"
    assert data["paired_cases"][0]["fixed"]["stop_reason"] == "max_rounds_reached"


def test_report_markdown_renders_actual_stop_reason(tmp_path):
    sc = case_budget_protection()
    report = pair_and_aggregate(list(replay_scripted_case(sc).values()))
    paths = write_comparison_report(report, tmp_path)
    md = (tmp_path / paths["comparison_markdown"]).read_text(encoding="utf-8")
    # The per-case row preserves the actual reason, not a generic label.
    assert "| budget_exhausted |" in md
    assert "| max_rounds_reached |" in md
    # The note explains input exhaustion is never an early stop.
    assert "input_exhausted" in md


def test_report_markdown_renders_input_exhaustion(tmp_path):
    paired = replay_scripted_case(case_input_exhaustion())
    report = pair_and_aggregate(list(paired.values()))
    paths = write_comparison_report(report, tmp_path)
    md = (tmp_path / paths["comparison_markdown"]).read_text(encoding="utf-8")
    # Both rows show input_exhausted as the stop reason and 'no' for early stop.
    assert "input_exhausted" in md
    assert "| no | input_exhausted |" in md


# ---------------------------------------------------------------------------
# Aggregate/report propagation rejects an inconsistent result (fail closed)
# ---------------------------------------------------------------------------


def test_pair_and_aggregate_cannot_accept_inconsistent_fixed_result():
    # A FIXED result claiming an early stop is contradictory; construction
    # (and therefore any aggregation/report) fails closed rather than letting
    # an early-stop label or rate leak into the aggregate.
    ident = CaseIdentity("AAPL", "2026-05-13", "snap", "1.0")
    with pytest.raises(ValueError):
        CaseResult(
            strategy=StrategyKey.FIXED, identity=ident, llm_calls=6,
            tool_calls=0, total_tokens=6000, elapsed_seconds=90.0,
            debate_rounds=3, early_stopped=True, stop_reason="no_new_evidence",
        )


def test_pair_and_aggregate_cannot_accept_inconsistent_dynamic_reason():
    # A DYNAMIC result that is early_stopped but with an empty / non-genuine
    # stop reason is contradictory; it is rejected before it can be paired.
    ident = CaseIdentity("AAPL", "2026-05-13", "snap", "1.0")
    with pytest.raises(ValueError):
        CaseResult(
            strategy=StrategyKey.DYNAMIC, identity=ident, llm_calls=2,
            tool_calls=0, total_tokens=2000, elapsed_seconds=30.0,
            debate_rounds=1, early_stopped=True, stop_reason="",
        )


def test_report_cannot_render_inconsistent_result(tmp_path):
    # A FIXED early-stop result is rejected at construction, so the report
    # writer is never handed an inconsistent aggregation to render as "yes".
    ident = CaseIdentity("AAPL", "2026-05-13", "snap", "1.0")
    with pytest.raises(ValueError):
        write_comparison_report(
            pair_and_aggregate([
                CaseResult(
                    strategy=StrategyKey.FIXED, identity=ident, llm_calls=6,
                    tool_calls=0, total_tokens=6000, elapsed_seconds=90.0,
                    debate_rounds=3, early_stopped=True,
                    stop_reason="budget_exhausted",
                ),
                CaseResult(
                    strategy=StrategyKey.DYNAMIC, identity=ident, llm_calls=2,
                    tool_calls=0, total_tokens=2000, elapsed_seconds=30.0,
                    debate_rounds=1, early_stopped=True,
                    stop_reason="budget_exhausted",
                ),
            ]),
            tmp_path,
        )


def test_aggregate_propagates_valid_genuine_early_stop():
    # A valid genuine dynamic early stop propagates correctly to the
    # aggregate and report: early_stop_rate == 1.0 and the real reason kept.
    ident = CaseIdentity("AAPL", "2026-05-13", "snap", "1.0")
    results = [
        CaseResult(
            strategy=StrategyKey.FIXED, identity=ident, llm_calls=6,
            tool_calls=0, total_tokens=6000, elapsed_seconds=90.0,
            debate_rounds=3, early_stopped=False,
            stop_reason="max_rounds_reached",
        ),
        CaseResult(
            strategy=StrategyKey.DYNAMIC, identity=ident, llm_calls=2,
            tool_calls=0, total_tokens=2000, elapsed_seconds=30.0,
            debate_rounds=1, early_stopped=True,
            stop_reason="budget_exhausted",
        ),
    ]
    report = pair_and_aggregate(results)
    assert report.dynamic_early_stop_count == 1
    assert report.dynamic_early_stop_rate == 1.0
    assert report.dynamic_stop_reasons == {"budget_exhausted": 1}
    assert report.paired_cases[0][2].early_stop_rate == 1.0
    assert report.paired_cases[0][2].stop_reason == "budget_exhausted"


# ---------------------------------------------------------------------------
# Report writer (does not touch raw inputs)
# ---------------------------------------------------------------------------


def test_write_report_creates_json_and_markdown(tmp_path):
    sc = case_new_evidence_extension()
    paired = replay_scripted_case(sc)
    report = pair_and_aggregate(list(paired.values()))
    paths = write_comparison_report(report, tmp_path)
    assert (tmp_path / paths["comparison_json"]).exists()
    assert (tmp_path / paths["comparison_markdown"]).exists()
    data = json.loads((tmp_path / paths["comparison_json"]).read_text(encoding="utf-8"))
    assert data["total_cases"] == 1
    # Aggregate JSON carries tool-call totals AND per-strategy estimated-case status.
    assert "fixed_total_tool_calls" in data["sums_and_rates"]
    assert "dynamic_total_tool_calls" in data["sums_and_rates"]
    assert "fixed_estimated_cases" in data["sums_and_rates"]
    assert "dynamic_estimated_cases" in data["sums_and_rates"]
    # Per-case JSON carries the usage-provenance indicator per strategy.
    assert data["paired_cases"][0]["dynamic"]["tool_usage_estimated"] is True
    assert data["paired_cases"][0]["fixed"]["tool_usage_estimated"] is True
    md = (tmp_path / paths["comparison_markdown"]).read_text(encoding="utf-8")
    assert "# Phase 4A" in md
    assert "live-provider result" in md
    # Markdown per-case and aggregate tables surface tool calls + estimated/measured status.
    assert "Tool calls" in md
    assert "estimated" in md
    assert "Total tool calls" in md
    assert "Estimated (not measured) cases" in md


def test_report_markdown_uses_measured_when_not_estimated(tmp_path):
    ident = CaseIdentity("AAPL", "2026-05-13", "snap", "1.0")
    results = [
        CaseResult(
            strategy=StrategyKey.FIXED, identity=ident, llm_calls=6, tool_calls=4,
            total_tokens=6000, elapsed_seconds=90.0, debate_rounds=3,
            early_stopped=False, estimated=False,
        ),
        CaseResult(
            strategy=StrategyKey.DYNAMIC, identity=ident, llm_calls=2, tool_calls=0,
            total_tokens=2000, elapsed_seconds=30.0, debate_rounds=1,
            early_stopped=True, stop_reason="budget_exhausted", estimated=True,
        ),
    ]
    report = pair_and_aggregate(results)
    paths = write_comparison_report(report, tmp_path)
    md = (tmp_path / paths["comparison_markdown"]).read_text(encoding="utf-8")
    # A measured case is labelled measured; an estimated case is labelled estimated.
    assert "measured" in md
    assert "estimated" in md
    # Fixed: 6 LLM calls / 4 tool calls / 6000 tokens / 90.000s -> measured.
    assert "| 6 | 4 | 6000 | 90.000 | measured |" in md
    # Dynamic: 2 LLM calls / 0 tool calls / 2000 tokens / 30.000s -> estimated.
    assert "| 2 | 0 | 2000 | 30.000 | estimated |" in md


def test_report_aggregate_summarizes_estimated_cases_honestly(tmp_path):
    ident = CaseIdentity("AAPL", "2026-05-13", "snap", "1.0")
    results = [
        CaseResult(
            strategy=StrategyKey.FIXED, identity=ident, llm_calls=6, tool_calls=4,
            total_tokens=6000, elapsed_seconds=90.0, debate_rounds=3,
            early_stopped=False, estimated=False,
        ),
        CaseResult(
            strategy=StrategyKey.DYNAMIC, identity=ident, llm_calls=2, tool_calls=0,
            total_tokens=2000, elapsed_seconds=30.0, debate_rounds=1,
            early_stopped=True, stop_reason="budget_exhausted", estimated=True,
        ),
    ]
    report = pair_and_aggregate(results)
    paths = write_comparison_report(report, tmp_path)
    md = (tmp_path / paths["comparison_markdown"]).read_text(encoding="utf-8")
    # Fixed: 0 estimated of 1 case; Dynamic: 1 estimated of 1 case (never claimed measured).
    assert "| Estimated (not measured) cases | 0 | 1 |" in md


def test_pair_and_aggregate_zero_cases_is_safe():
    report = pair_and_aggregate([])
    assert report.total_cases == 0
    assert report.fixed_total_llm_calls == 0
    assert report.dynamic_total_llm_calls == 0
    assert report.fixed_total_tool_calls == 0
    assert report.dynamic_total_tool_calls == 0
    assert report.fixed_estimated_cases == 0
    assert report.dynamic_estimated_cases == 0
    assert report.dynamic_early_stop_rate is None
    # Serialization of an empty report stays JSON-safe and zero-fields.
    data = report.to_dict()
    assert data["total_cases"] == 0
    assert data["sums_and_rates"]["fixed_total_tool_calls"] == 0
    assert data["sums_and_rates"]["dynamic_estimated_cases"] == 0


def test_default_output_dir_is_evaluation_output():
    assert str(DEFAULT_OUTPUT_DIR) == "evaluation-output"
