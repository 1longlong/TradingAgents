"""Phase 3A offline tests: the Research Manager's deterministic Hold contract.

Authoritative requirement (#3): on a blocked run the Research Manager output
must be a non-directional Hold even if the LLM returns Buy, Sell, Overweight,
or Underweight, on *both* the structured and free-text paths. The enforcement
must not rely on prompt obedience alone, and the stored ``investment_plan`` must
not expose a conflicting directional recommendation.

No network, no paid LLM: the manager node is driven with a fake LLM that
deliberately returns directional output.
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
    # Structured output path: the model returns a directional ResearchPlan.
    plan = ResearchPlan(
        recommendation=PortfolioRating(directional),
        rationale="Strong directional case (should be preserved).",
        strategic_actions="Add to position (should be neutralised).",
    )
    structured_llm = MagicMock()
    structured_llm.invoke = MagicMock(return_value=plan)
    llm.with_structured_output = MagicMock(return_value=structured_llm)

    manager = create_research_manager(llm)
    out = manager(_base_state())

    plan_text = out["investment_plan"]
    assert "**Recommendation**: Hold" in plan_text, plan_text
    # No conflicting directional recommendation is exposed.
    for word in ("Buy", "Sell", "Overweight", "Underweight"):
        assert f"**Recommendation**: {word}" not in plan_text, plan_text
    # The evidence-insufficient rationale is preserved.
    assert "Strong directional case" in plan_text


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
    out = manager(_base_state(data_quality_verdict="normal"))
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
