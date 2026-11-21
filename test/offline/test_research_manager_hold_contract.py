"""Phase 3A offline tests: the Research Manager's deterministic Hold contract.

Authoritative requirement (#3): on a blocked run the Research Manager output
must be a non-directional Hold even if the LLM returns Buy, Sell, Overweight,
or Underweight, on *both* the structured and free-text paths. The enforcement
must not rely on prompt obedience alone, and the stored ``investment_plan`` must
not expose a conflicting directional recommendation.

No network, no paid LLM: the manager node is driven with a fake LLM that
deliberately returns directional output.

Traceability: FR-DQG-006 (authoritative blocked verdict at the output boundary);
supports INV-1 (fail closed).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tradingagents.agents.managers.research_manager import (
    _enforce_non_directional_hold,
    create_research_manager,
)
from tradingagents.agents.schemas import PortfolioRating, ResearchPlan


def _base_state(**overrides):
    state = {
        "company_of_interest": "COF",
        "trade_date": "2026-05-13",
        "asset_type": "stock",
        "data_quality_verdict": "blocked",
        "investor_state": {},
        "risk_debate_state": {"history": "", "count": 0, "latest_speaker": ""},
        "investment_debate_state": {
            "history": "debate history",
            "count": 3,
            "bear_history": "bear",
            "bull_history": "bull",
            "current_response": "Bull Analyst: argument",
        },
    }
    state.update(overrides)
    return state


@pytest.mark.parametrize(
    "directional",
    ["Buy", "Sell", "Overweight", "Underweight"],
)
def test_blocked_structured_path_always_holds(directional):
    llm = MagicMock()
    # Structured output path: the model returns a directional ResearchPlan whose
    # rationale invents an absent-Bear argument.
    plan = ResearchPlan(
        recommendation=PortfolioRating(directional),
        rationale="The bear overplayed its hand (should NOT be trusted).",
        strategic_actions="Add to position (should be neutralised).",
    )
    structured_llm = MagicMock()
    structured_llm.invoke = MagicMock(return_value=plan)
    llm.with_structured_output = MagicMock(return_value=structured_llm)

    # Positively-partial blocked run: only Bull executed (structured), Bear
    # refused pre-call. The trusted prose must use the safe partial template and
    # must NOT carry the invented absent-Bear attribution.
    state = _base_state(data_quality_verdict="blocked")
    state["data_quality_gate_decision"] = {"decision": "blocked"}
    state["debate_termination_decision"] = {
        "route": "summarize",
        "stop_reason": "budget_exhausted",
        "refused_speaker": "Bear",
        "trace": [],
    }
    state["investment_debate_state"] = {
        "history": "Bull Analyst: case",
        "count": 1,
        "bull_history": "Bull Analyst: case",
        "bear_history": "",
        "current_response": "Bull Analyst: case",
        "turns": [{"speaker": "Bull", "content": "case"}],
    }

    manager = create_research_manager(llm)
    out = manager(state)

    plan_text = out["investment_plan"]
    assert "**Recommendation**: Hold" in plan_text, plan_text
    # No conflicting directional recommendation is exposed.
    for word in ("Buy", "Sell", "Overweight", "Underweight"):
        assert f"**Recommendation**: {word}" not in plan_text, plan_text
    # Safer trusted template: the invented absent-Bear rationale is NOT preserved.
    assert "bear overplayed" not in plan_text.lower()
    assert "no response from: bear" in plan_text.lower()


@pytest.mark.parametrize(
    "directional",
    ["Buy", "Sell", "Overweight", "Underweight"],
)
def test_blocked_freetext_path_always_holds(directional):
    llm = MagicMock()
    # Provider does not support structured output -> free-text fallback.
    llm.with_structured_output = MagicMock(return_value=None)
    llm.invoke = MagicMock(
        return_value=MagicMock(
            content=(
                f"**Recommendation**: {directional}\n\n"
                "**Rationale**: the data was too thin but I'll side with "
                "momentum anyway.\n\n"
                "**Strategic Actions**: buy more."
            )
        )
    )

    manager = create_research_manager(llm)
    out = manager(_base_state())

    plan_text = out["investment_plan"]
    assert "**Recommendation**: Hold" in plan_text, plan_text
    for word in ("Buy", "Sell", "Overweight", "Underweight"):
        assert f"**Recommendation**: {word}" not in plan_text, plan_text


def test_blocked_freetext_without_recommendation_header_gets_forced_hold():
    # A free-text response that deviates from the header entirely must still
    # yield a stored Hold recommendation, never exposed as directional.
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=None)
    llm.invoke = MagicMock(
        return_value=MagicMock(content="I think this is a clear Buy opportunity.")
    )
    manager = create_research_manager(llm)
    out = manager(_base_state())
    plan_text = out["investment_plan"]
    assert "**Recommendation**: Hold" in plan_text, plan_text


def test_non_blocked_run_is_not_forced_to_hold():
    # A normal run must not be coerced: the manager keeps the LLM's call.
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=None)
    llm.invoke = MagicMock(
        return_value=MagicMock(content="**Recommendation**: Buy\n\n**Rationale**: strong.")
    )
    manager = create_research_manager(llm)
    # A trusted normal gate carries a matching decision object; a bare
    # ``data_quality_verdict`` without one fails closed to blocked.
    out = manager(
        _base_state(
            data_quality_verdict="normal",
            data_quality_gate_decision={"decision": "normal"},
        )
    )
    assert "**Recommendation**: Buy" in out["investment_plan"]


def test_enforce_dirties_metadata_notes_but_pins_hold():
    # Direct unit check of the enforcement helper on a rendered ResearchPlan.
    rendered = ResearchPlan(
        recommendation=PortfolioRating.UNDERWEIGHT,
        rationale="Weak fundamentals.",
        strategic_actions="Trim.",
    )
    # Render manually (mirrors the structured render used by the node).
    from tradingagents.agents.schemas import render_research_plan

    plan_text = render_research_plan(rendered)
    coerced = _enforce_non_directional_hold(plan_text)
    assert "**Recommendation**: Hold" in coerced
    assert "**Recommendation**: Underweight" not in coerced
    assert "Weak fundamentals." in coerced


def test_partial_hallucinated_opponent_not_in_trusted_plan():
    # NFR-AUD-001 / INV-6: when Bear did NOT execute (structured Bull-only
    # state), a model that falsely attributes a claim to the absent Bear must
    # not leak that attribution into the authoritative investment_plan. A
    # truthful footer over contradictory trusted prose is a FAIL.
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=None)
    llm.invoke = MagicMock(
        return_value=MagicMock(
            content=(
                "**Recommendation**: Buy\n\n"
                "**Rationale**: The bear overplayed its hand and conceded, so "
                "the bull thesis clearly wins.\n\n"
                "**Strategic Actions**: Buy aggressively."
            )
        )
    )
    state = _base_state(
        data_quality_verdict="normal",
        data_quality_gate_decision={"decision": "normal"},
    )
    state["investment_debate_state"] = {
        "history": "Bull Analyst: bullish case",
        "count": 1,
        "bull_history": "Bull Analyst: bullish case",
        "bear_history": "",
        "current_response": "Bull Analyst: bullish case",
        "turns": [{"speaker": "Bull", "content": "bullish case"}],
    }
    manager = create_research_manager(llm)
    out = manager(state)
    plan = out["investment_plan"]
    low = plan.lower()
    assert "bear overplayed" not in low
    assert "conceded" not in low
    assert "bear" not in low or "no response from: bear" in low
    # Rating policy preserved (not coerced to Hold just because partial).
    assert "**Recommendation**: Buy" in plan


def test_partial_forwards_are_quarantined_separately(tmp_path):
    # The raw partial narrative may exist only in the quarantined audit file,
    # never in the trusted plan.
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=None)
    llm.invoke = MagicMock(
        return_value=MagicMock(
            content="**Recommendation**: Buy\n\n**Rationale**: the bear conceded.\n\n**Strategic Actions**: buy."
        )
    )
    audit = tmp_path / "partial_audit.jsonl"
    state = _base_state(
        data_quality_verdict="normal",
        data_quality_gate_decision={"decision": "normal"},
    )
    state["debate_partial_audit_path"] = str(audit)
    state["investment_debate_state"] = {
        "history": "Bull Analyst: bullish case",
        "count": 1,
        "bull_history": "Bull Analyst: bullish case",
        "bear_history": "",
        "current_response": "Bull Analyst: bullish case",
        "turns": [{"speaker": "Bull", "content": "bullish case"}],
    }
    manager = create_research_manager(llm)
    out = manager(state)
    assert "the bear conceded" not in out["investment_plan"].lower()
    raw = audit.read_text(encoding="utf-8")
    assert "the bear conceded" in raw
    assert "non_authoritative" in raw


def _legacy_unknown_state(**overrides):
    """A non-blocked state with legacy prose-only histories (UNKNOWN evidence)."""
    state = _base_state(
        data_quality_verdict="normal",
        data_quality_gate_decision={"decision": "normal"},
    )
    state["investment_debate_state"] = {
        "history": "Bull Analyst: bull prose\nBear Analyst: bear prose",
        "count": 2,
        "bull_history": "Bull Analyst: bull prose",
        "bear_history": "Bear Analyst: bear prose",
        "current_response": "Bear Analyst: bear prose",
        # No structured turns -> legacy/unknown (prose does not prove execution).
    }
    state.update(overrides)
    return state


def test_adversarial_unknown_legacy_not_trusted_in_plan(tmp_path):
    # Partial OR UNKNOWN -> deterministic trusted template. A legacy/unknown
    # state whose model invents absent-opponent attribution must NOT leak into
    # the trusted plan; the raw narrative exists only in quarantined audit.
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=None)
    llm.invoke = MagicMock(
        return_value=MagicMock(
            content=(
                "**Recommendation**: Buy\n\n"
                "**Rationale**: The bear overplayed its hand and conceded, and "
                "the bull rebutted it decisively.\n\n"
                "**Strategic Actions**: Buy aggressively."
            )
        )
    )
    state = _legacy_unknown_state()
    state["debate_partial_audit_path"] = str(tmp_path / "q.jsonl")
    manager = create_research_manager(llm)
    out = manager(state)
    plan = out["investment_plan"].lower()
    assert "overplayed" not in plan
    assert "rebutted" not in plan
    assert "**rationale**:" in plan
    assert "unverified" in plan
    # Rating policy preserved (unknown/legacy is not coerced to Hold).
    assert "**recommendation**: buy" in plan


def test_default_results_dir_quarantine_no_override(tmp_path):
    # No explicit debate_partial_audit_path; the DEFAULT path must be derived
    # from results_dir + identity so the raw audit is persisted (not dropped).
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=None)
    llm.invoke = MagicMock(
        return_value=MagicMock(
            content="**Recommendation**: Buy\n\n**Rationale**: the bear conceded.\n\n**Strategic Actions**: buy."
        )
    )
    state = _legacy_unknown_state()
    state["results_dir"] = str(tmp_path)
    state["company_of_interest"] = "COF"
    state["trade_date"] = "2026-05-13"
    # Ensure no explicit override.
    state.pop("debate_partial_audit_path", None)
    manager = create_research_manager(llm)
    out = manager(state)
    assert "the bear conceded" not in out["investment_plan"].lower()
    # The default quarantine file exists under results_dir/<ticker>/<date>/audit.
    files = list(tmp_path.rglob("partial_debate_audit.jsonl"))
    assert len(files) == 1, list(tmp_path.rglob("*"))
    raw = files[0].read_text(encoding="utf-8")
    assert "the bear conceded" in raw
    assert "non_authoritative" in raw
    assert "2026-05-13/COF" in raw
