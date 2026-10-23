"""Research Manager: turns the bull/bear debate into a structured investment plan for the trader."""

from __future__ import annotations

import re

from tradingagents.agents.schemas import ResearchPlan, render_research_plan
from tradingagents.agents.utils.agent_utils import (
    get_data_quality_context_from_state,
    get_instrument_context_from_state,
    get_language_instruction,
)
from tradingagents.agents.utils.structured import (
    NO_EXTERNAL_TOOLS,
    bind_structured,
    invoke_structured_or_freetext,
)
from tradingagents.debate.conflicts import build_conflict_summary

# Matches the recommendation field on its own line, capturing the value the LLM
# chose (markdown ``**Recommendation**: X`` or a bare ``Recommendation: X``).
_RECOMMENDATION_LINE_RE = re.compile(
    r"^\s*(?:\*\*Recommendation\*\*|Recommendation)\s*[:\-]\s*(.+?)\s*$"
)


def _enforce_non_directional_hold(plan_text: str) -> str:
    """Deterministically coerce a Research Manager plan to a non-directional Hold.

    Authoritative for a blocked run: the standard bull/bear debate was skipped
    because critical market data is missing or conflicting, so the intended
    outcome is an evidence-insufficient conclusion. Prompt obedience alone is
    not relied upon — whatever the LLM returned (structured or free-text), the
    stored recommendation is rewritten to ``Hold`` so a conflicting Buy / Sell /
    Overweight / Underweight is never exposed.

    The rationale is preserved unchanged so the useful evidence-insufficient
    reasoning and the recovery conditions the model already wrote stay intact,
    but the recommendation itself is pinned and a short note explains why.
    """
    lines = plan_text.splitlines()
    recommendation_found = False
    for index, line in enumerate(lines):
        match = _RECOMMENDATION_LINE_RE.match(line)
        if not match:
            continue
        recommendation_found = True
        # Preserve the marker text but pin the value to Hold.
        marker = line[: match.start(1)] if match.start(1) else line
        lines[index] = f"{marker}Hold"
        break

    result = "\n".join(lines).strip()
    if not recommendation_found:
        # A free-text response that deviated from the Recommendation header
        # entirely: prepend an authoritative non-directional Hold so the stored
        # plan is never read as a conflicting directional call.
        result = (
            "**Recommendation**: Hold\n\n"
            "Note: this run was blocked by the Data Quality Gate; only an "
            "evidence-insufficient conclusion is permitted.\n\n"
            + result
        )
    else:
        result = (
            result
            + "\n\n"
            + "Note: the Data Quality Gate blocked this run; the conclusion is "
            "evidence-insufficient, not a directional call."
        )
    return result


def _conflict_summary_block(investment_debate_state: dict) -> str:
    """A safe, structured conflict summary block for the Research Manager prompt.

    Consumes only the tracked conflicts (already validated and derived by the
    Debate Evaluator from structured metadata). It prefers the persisted
    ``conflict_summary`` (which also carries the resolve/escalate resolution
    notes) and recomputes ``open_blocking_count`` authoritatively from the
    conflicts it actually carries, so a stale count or an empty summary never
    misreports a blocking disagreement. It never embeds free-form analyst prose
    or chain-of-thought, and it returns an empty string when there are no
    tracked conflicts — so a bare action-only divergence (which is not a
    blocking conflict) is not presented as a fabricated disagreement. Safe even
    for a legacy state with no conflict fields.
    """
    conflicts_raw = investment_debate_state.get("conflicts") or []
    if not conflicts_raw:
        return ""
    try:
        # The persisted summary carries the resolution notes; recompute the
        # blocking count from the conflicts actually present (authoritative).
        summary = build_conflict_summary(
            conflict_summary = investment_debate_state.get("conflict_summary"),
            conflicts=conflicts_raw,
        )
    except Exception:  # noqa: BLE001 — never let a bad conflict block the manager
        return ""
    return summary.to_prompt_block()


def create_research_manager(llm):
    structured_llm = bind_structured(llm, ResearchPlan, "Research Manager")

    def research_manager_node(state) -> dict:
        instrument_context = get_instrument_context_from_state(state)
        history = state["investment_debate_state"].get("history", "")
        data_quality_context = get_data_quality_context_from_state(state)
        data_quality_verdict = state.get("data_quality_verdict", "blocked")

        investment_debate_state = state["investment_debate_state"]
        conflict_block = _conflict_summary_block(investment_debate_state)
        conflict_section = (
            f"\n\n{conflict_block}" if conflict_block else ""
        )

        prompt = f"""As the Research Manager and debate facilitator, your role is to critically evaluate this round of debate and deliver a clear, actionable investment plan for the trader.

{instrument_context}

{data_quality_context}

---

**Rating Scale** (use exactly one):
- **Buy**: Strong conviction in the bull thesis; recommend taking or growing the position
- **Overweight**: Constructive view; recommend gradually increasing exposure
- **Hold**: Balanced view; recommend maintaining the current position
- **Underweight**: Cautious view; recommend trimming exposure
- **Sell**: Strong conviction in the bear thesis; recommend exiting or avoiding the position

The debate always contains conflicting arguments; deciding which side is stronger is the job, so conflict alone is not a reason to Hold. Commit to the side with the stronger case, sized by how decisively it wins. Choose Hold only when the evidence is still balanced after that weighing, or too thin to support a call; do not manufacture a direction to appear decisive. Weigh the bull and bear cases on their merits, independent of which side spoke first or last.
{conflict_section}

---

**Debate History:**
{history}

## Output

Write these sections, in this order, starting with the recommendation on its own line:

- **Recommendation**: exactly one of Buy / Overweight / Hold / Underweight / Sell
- **Rationale**: which arguments decided it
- **Strategic Actions**: concrete steps for the trader, sized against a standard allocation

{NO_EXTERNAL_TOOLS}""" + get_language_instruction()

        if data_quality_verdict == "blocked":
            prompt += (
                "\n\nIMPORTANT — DEBATE WAS BLOCKED BY THE DATA QUALITY GATE. "
                "You did not receive a normal bull/bear debate; the standard "
                "debate was skipped because critical market data is missing or "
                "conflicting. This is an evidence-insufficient conclusion only. "
                "State explicitly: (1) the missing/conflicting critical data and "
                "the validation that completed, (2) the limited observations "
                "available, and (3) the conditions under which the block would "
                "clear on a later run. You MUST NOT produce a strong directional "
                "Buy or Sell — a Hold (or a clearly-hedged, evidence-insufficient "
                "call) is the correct outcome. Do not manufacture conviction "
                "you do not have. State the conclusion as insufficient evidence "
                "rather than inventing a direction."
            )
        elif data_quality_verdict == "degraded":
            prompt += (
                "\n\nIMPORTANT — DATA QUALITY IS DEGRADED. Confidence is capped "
                "by the limitations above: low-evidence claims cannot be "
                "decisive. Cite only the evidence IDs listed in the gate context. "
                "If the core view is supported only by Low evidence, choose Hold "
                "or explicitly state the evidence is insufficient rather than "
                "manufacturing direction. Do not overstate certainty."
            )

        investment_plan = invoke_structured_or_freetext(
            structured_llm,
            llm,
            prompt,
            render_research_plan,
            "Research Manager",
        )

        # Authoritative contract: a blocked run must produce a non-directional
        # Hold even if the model returned a directional call, on both the
        # structured and free-text paths. Do not rely on prompt obedience.
        if data_quality_verdict == "blocked":
            investment_plan = _enforce_non_directional_hold(investment_plan)

        new_investment_debate_state = {
            "judge_decision": investment_plan,
            "history": investment_debate_state.get("history", ""),
            "bear_history": investment_debate_state.get("bear_history", ""),
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": investment_plan,
            "count": investment_debate_state["count"],
        }
        # Preserve the Phase 3B bookkeeping so the debate termination trace
        # survives the manager's conclusion for checkpointing and reports. These
        # fields are optional; a legacy state simply carries nothing extra.
        for phase3b_field in (
            "turns",
            "conflicts",
            "conflict_summary",
            "stances",
            "previously_cited_evidence_ids",
            "round_metrics",
            "metadata_parse_failed_count",
            "no_new_evidence_streak",
            "budget",
        ):
            if phase3b_field in investment_debate_state:
                new_investment_debate_state[phase3b_field] = investment_debate_state[phase3b_field]

        return {
            "investment_debate_state": new_investment_debate_state,
            "investment_plan": investment_plan,
            "debate_termination_decision": state.get("debate_termination_decision"),
        }

    return research_manager_node
