"""Portfolio Manager: synthesises the risk-analyst debate into the final decision.

Uses LangChain's ``with_structured_output`` so the LLM produces a typed
``PortfolioDecision`` directly, in a single call.  The result is rendered
back to markdown for storage in ``final_trade_decision`` so memory log,
CLI display, and saved reports continue to consume the same shape they do
today.  When a provider does not expose structured output, the agent falls
back gracefully to free-text generation.
"""

from __future__ import annotations

from tradingagents.agents.schemas import PortfolioDecision, render_pm_decision
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
    get_portfolio_context_from_state,
)
from tradingagents.agents.utils.output_guard import (
    enforce_blocked_conclusion,
    is_blocked_run,
)
from tradingagents.agents.utils.structured import (
    NO_EXTERNAL_TOOLS,
    bind_structured,
    invoke_structured_or_freetext,
)


def create_portfolio_manager(llm):
    structured_llm = bind_structured(llm, PortfolioDecision, "Portfolio Manager")

    def portfolio_manager_node(state) -> dict:
        instrument_context = get_instrument_context_from_state(state)
        portfolio_context = get_portfolio_context_from_state(state)

        history = state["risk_debate_state"]["history"]
        risk_debate_state = state["risk_debate_state"]
        research_plan = state["investment_plan"]
        trader_plan = state["trader_investment_plan"]
        # The final decision must honour the gate: a blocked run may not be
        # upgraded by the risk debate into a directional rating.
        blocked = is_blocked_run(state)

        past_context = state.get("past_context", "")
        lessons_line = (
            f"- Lessons from prior decisions and outcomes:\n{past_context}\n"
            if past_context
            else ""
        )

        prompt = f"""As the Portfolio Manager, synthesize the risk analysts' debate and deliver the final trading decision.

{instrument_context}

{portfolio_context}

---

**Rating Scale** (use exactly one):
- **Buy**: Strong conviction to enter or add to position
- **Overweight**: Favorable outlook, gradually increase exposure
- **Hold**: Maintain current position, no action needed
- **Underweight**: Reduce exposure, take partial profits
- **Sell**: Exit position or avoid entry

**Context:**
- Research Manager's investment plan: **{research_plan}**
- Trader's transaction proposal: **{trader_plan}**
{lessons_line}
**Risk Analysts Debate History:**
{history}

---

Ground every conclusion in specific evidence from the analysts. The risk debate always contains conflicting stances; deciding which is stronger is the job, so conflict alone is not a reason to Hold. Commit to the stronger case, sized by how decisively it wins. Choose Hold only when the evidence is still balanced after that weighing, or too thin to support a call; do not force a direction to appear decisive. Weigh the analysts on their merits, independent of speaking order.

## Output

Write these sections, in this order, starting with the rating on its own line:

- **Rating**: exactly one of Buy / Overweight / Hold / Underweight / Sell
- **Executive Summary**: the call and how to act on it
- **Investment Thesis**: the evidence that decided it, and what would change it

{NO_EXTERNAL_TOOLS}{get_language_instruction()}"""

        if blocked:
            prompt += (
                "\n\nIMPORTANT — THE DATA QUALITY GATE BLOCKED THIS RUN. The "
                "Research Manager's conclusion is evidence-insufficient and the "
                "Trader was restricted to Hold. You MUST NOT issue a directional "
                "Buy / Overweight / Underweight / Sell rating; the only permitted "
                "rating is Hold. Explain the missing critical data and the "
                "recovery conditions rather than manufacturing a direction."
            )

        # ADR-011: cap the TYPED numeric confidence at full raw precision BEFORE the
        # lossy 2-decimal render, so a raw 0.954321 / 0.6000001 is genuinely capped
        # and its exact raw is recorded (not masked by rounded rendered text).
        from tradingagents.debate.confidence_policy import cap_typed_confidence

        typed_audit: list[dict] = []

        def _cap_typed(result):
            return cap_typed_confidence(
                result, state,
                source="Portfolio Manager", boundary="final_trade_decision_typed",
                sink=typed_audit,
            )

        final_trade_decision = invoke_structured_or_freetext(
            structured_llm,
            llm,
            prompt,
            render_pm_decision,
            "Portfolio Manager",
            sanitize_result=_cap_typed,
        )

        # Authoritative contract: the final rating on a blocked run is pinned to
        # Hold on both the structured and free-text paths so no upstream model
        # can undo the Research Manager's restricted conclusion.
        if blocked:
            final_trade_decision = enforce_blocked_conclusion(
                final_trade_decision, field="rating"
            )
        # ADR-010: the final trusted decision must not restate a REJECTED exact
        # fact (valid ID, wrong date/value/unit) even if a downstream model echoed
        # it. Narrow, line-scoped redaction only; never a global Hold.
        from tradingagents.agents.utils.output_guard import (
            enforce_trusted_boundary,
        )

        final_trade_decision = enforce_trusted_boundary(final_trade_decision, state)

        # ADR-011: cap explicit confidence-labelled numerics on a degraded run so
        # the final decision never carries a raw over-cap confidence.
        from tradingagents.debate.confidence_policy import cap_agent_text, update_audit

        final_trade_decision, _text_entries = cap_agent_text(
            final_trade_decision, state,
            source="Portfolio Manager", boundary="final_trade_decision",
        )
        _cap_entries = list(typed_audit) + list(_text_entries)

        new_risk_debate_state = {
            "judge_decision": final_trade_decision,
            "history": risk_debate_state["history"],
            "aggressive_history": risk_debate_state["aggressive_history"],
            "conservative_history": risk_debate_state["conservative_history"],
            "neutral_history": risk_debate_state["neutral_history"],
            "latest_speaker": "Judge",
            "current_aggressive_response": risk_debate_state["current_aggressive_response"],
            "current_conservative_response": risk_debate_state["current_conservative_response"],
            "current_neutral_response": risk_debate_state["current_neutral_response"],
            "count": risk_debate_state["count"],
        }

        result = {
            "risk_debate_state": new_risk_debate_state,
            "final_trade_decision": final_trade_decision,
        }
        if _cap_entries:
            result["confidence_cap_audit"] = update_audit(state, _cap_entries)
        return result

    return portfolio_manager_node
