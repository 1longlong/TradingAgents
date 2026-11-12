"""Trader: turns the Research Manager's investment plan into a concrete transaction proposal."""

from __future__ import annotations

import functools

from langchain_core.messages import AIMessage

from tradingagents.agents.schemas import TraderProposal, render_trader_proposal
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
    get_portfolio_context_from_state,
)
from tradingagents.agents.utils.output_guard import (
    enforce_blocked_conclusion,
    enforce_trusted_boundary,
    is_blocked_run,
)
from tradingagents.agents.utils.structured import (
    NO_EXTERNAL_TOOLS,
    bind_structured,
    invoke_structured_or_freetext,
)


def create_trader(llm):
    structured_llm = bind_structured(llm, TraderProposal, "Trader")

    def trader_node(state, name):
        company_name = state["company_of_interest"]
        instrument_context = get_instrument_context_from_state(state)
        investment_plan = state["investment_plan"]
        # The research plan digests the debate but loses exact price structure;
        # give the Trader the technical market report so entry/stop levels are
        # grounded in real ATR / support-resistance / current price (#1167). The
        # report is empty when the user did not select the market analyst, so
        # only offer it (and the grounding instruction) when it has content.
        market_report = (state["market_report"] or "").strip()
        portfolio_context = get_portfolio_context_from_state(state)
        # A blocked gate is authoritative: the Trader may not translate an
        # evidence-insufficient conclusion into a directional transaction.
        blocked = is_blocked_run(state)

        if market_report:
            grounding = (
                "Ground concrete price levels (entry, stop-loss, position sizing) in the technical "
                "market report's price structure -- current price, support/resistance, ATR, and "
                "volatility -- and use the research plan for direction and strategy. "
            )
            report_section = f"Technical Market Report:\n{market_report}\n\n"
        else:
            grounding = ""
            report_section = ""

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a trading agent analyzing market data to make investment decisions. "
                    "Based on your analysis, provide a specific recommendation to buy, sell, or hold. "
                    + grounding
                    # Entry/stop are numeric price fields. Asking for concrete
                    # levels invites a percentage ("15%"), which is not a price
                    # and fails the structured parse (#1288).
                    + "State entry price and stop-loss as absolute price levels in the "
                    "instrument's quote currency (for example 189.5), never a percentage "
                    "or a range; convert a percentage distance to the price level it "
                    "implies, or omit the field if you cannot state a number. "
                    + NO_EXTERNAL_TOOLS
                    + get_language_instruction()
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Here is the research team's investment plan for {company_name}. "
                    f"{instrument_context}\n\n"
                    f"{report_section}"
                    f"{portfolio_context}\n\n"
                    f"Proposed Investment Plan:\n{investment_plan}\n\n"
                    "Make an informed, strategic trading decision.\n\n"
                    "## Output\n\n"
                    "Write these sections, in this order, starting with the action "
                    "on its own line:\n\n"
                    "- **Action**: exactly one of Buy / Hold / Sell. A research "
                    "recommendation of Overweight is a Buy and Underweight is a Sell, "
                    "sized by how strong the case is; conflict alone is not a Hold.\n"
                    "- **Reasoning**: why, against the plan and the price structure\n"
                    "- **Entry Price**, **Stop Loss**, **Position Sizing**: when you can state them"
                ),
            },
        ]

        if blocked:
            # Ground the restriction in the prompt too, but never rely on
            # prompt obedience: the stored plan is pinned below.
            messages[-1]["content"] += (
                "\n\nIMPORTANT — THE DATA QUALITY GATE BLOCKED THIS RUN. The "
                "research conclusion is evidence-insufficient. You may only "
                "propose Hold; do not propose Buy or Sell, and do not give an "
                "aggressive action plan."
            )

        from tradingagents.debate.confidence_policy import (
            cap_agent_text,
            cap_typed_confidence,
            update_audit,
        )

        # ADR-011: cap the TYPED numeric confidence at full raw precision BEFORE the
        # lossy 2-decimal render, so a raw 0.954321 / 0.6000001 is genuinely capped
        # and its exact raw is recorded (not masked by rounded rendered text).
        typed_audit: list[dict] = []

        def _cap_typed(result):
            return cap_typed_confidence(
                result, state, source="Trader", boundary="trader_typed",
                sink=typed_audit,
            )

        trader_plan = invoke_structured_or_freetext(
            structured_llm,
            llm,
            messages,
            render_trader_proposal,
            "Trader",
            sanitize_result=_cap_typed,
        )

        # Authoritative contract: a blocked run's stored transaction proposal
        # is pinned to Hold on both the structured and free-text paths.
        if blocked:
            trader_plan = enforce_blocked_conclusion(trader_plan, field="action")
        # ADR-010: never restate a REJECTED exact fact in the trusted trader plan.
        trader_plan = enforce_trusted_boundary(trader_plan, state)

        # ADR-011: cap explicit confidence-labelled numerics on a degraded run.
        trader_plan, _text_entries = cap_agent_text(
            trader_plan, state, source="Trader", boundary="trader_plan",
        )
        _cap_entries = list(typed_audit) + list(_text_entries)

        result = {
            "messages": [AIMessage(content=trader_plan)],
            "trader_investment_plan": trader_plan,
            "sender": name,
        }
        if _cap_entries:
            result["confidence_cap_audit"] = update_audit(state, _cap_entries)
        return result

    return functools.partial(trader_node, name="Trader")
