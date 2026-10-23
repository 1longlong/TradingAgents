from tradingagents.agents.utils.agent_utils import (
    get_data_quality_context_from_state,
    get_instrument_context_from_state,
    get_language_instruction,
    opponent_argument_or_opening,
    report_or_absent,
)
from tradingagents.debate.budget import record_call_usage
from tradingagents.debate.evidence_manifest import build_citation_allowlist
from tradingagents.debate.state import append_debate_turn
from tradingagents.debate.turn import METADATA_INSTRUCTION, parse_turn_metadata


def create_bear_researcher(llm):
    def bear_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")

        current_response = opponent_argument_or_opening(
            investment_debate_state.get("current_response", ""), "bull analyst"
        )
        market_research_report = report_or_absent(state["market_report"], "market")
        sentiment_report = report_or_absent(state["sentiment_report"], "sentiment")
        news_report = report_or_absent(state["news_report"], "news")
        fundamentals_report = report_or_absent(state["fundamentals_report"], "fundamentals")
        instrument_context = get_instrument_context_from_state(state)
        data_quality_context = get_data_quality_context_from_state(state)
        data_quality_allowlist = build_citation_allowlist(
            state.get("data_quality_evidence_records"), state.get("trade_date")
        )
        data_quality_verdict = state.get("data_quality_verdict")
        asset_type = state.get("asset_type", "stock")
        target_label = "stock" if asset_type == "stock" else "asset"
        fundamentals_label = (
            "Company fundamentals report"
            if asset_type == "stock"
            else "Asset fundamentals report (may be unavailable for crypto)"
        )

        prompt = f"""You are a Bear Analyst making the case against investing in the {target_label}. Your goal is to present a well-reasoned argument emphasizing risks, challenges, and negative indicators. Leverage the provided research and data to highlight potential downsides and counter bullish arguments effectively.

Key points to focus on:

- Risks and Challenges: Highlight factors like market saturation, financial instability, or macroeconomic threats that could hinder the stock's performance.
- Competitive Weaknesses: Emphasize vulnerabilities such as weaker market positioning, declining innovation, or threats from competitors.
- Negative Indicators: Use evidence from financial data, market trends, or recent adverse news to support your position.
- Bull Counterpoints: Critically analyze the bull argument with specific data and sound reasoning, exposing weaknesses or over-optimistic assumptions.
- Engagement: Present your argument in a conversational style, directly engaging with the bull analyst's points and debating effectively rather than simply listing facts.

Resources available:

{instrument_context}
{data_quality_context}
{data_quality_allowlist}
Market research report: {market_research_report}
Social media sentiment report: {sentiment_report}
Latest world affairs news: {news_report}
{fundamentals_label}: {fundamentals_report}
Conversation history of the debate: {history}
Last bull argument: {current_response}
Use this information to deliver a compelling bear argument, refute the bull's claims, and engage in a dynamic debate that demonstrates the risks and weaknesses of investing in the {target_label}.
""" + get_language_instruction()

        if data_quality_verdict == "degraded":
            prompt += (
                "\n\nData quality is degraded: low-evidence claims cannot be "
                "decisive, cite only the evidence IDs listed above, and cap your "
                "confidence accordingly."
            )

        prompt += METADATA_INSTRUCTION

        response = llm.invoke(prompt)

        content = response.content
        turn = parse_turn_metadata(speaker="Bear", content=content)

        new_investment_debate_state = append_debate_turn(
            investment_debate_state, turn
        )

        usage = record_call_usage(
            state.get("debate_usage"),
            prompt_chars=len(prompt),
            response_chars=len(content),
        )

        return {
            "investment_debate_state": new_investment_debate_state,
            "debate_usage": usage,
        }

    return bear_node
