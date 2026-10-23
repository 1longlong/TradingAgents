from typing import Annotated

from langgraph.graph import MessagesState
from typing_extensions import NotRequired, TypedDict


# Researcher team state
class InvestDebateState(TypedDict):
    bull_history: Annotated[
        str, "Bullish Conversation history"
    ]  # Bullish Conversation history
    bear_history: Annotated[
        str, "Bearish Conversation history"
    ]  # Bullish Conversation history
    history: Annotated[str, "Conversation history"]  # Conversation history
    current_response: Annotated[str, "Latest response"]  # Last response
    judge_decision: Annotated[str, "Final judge decision"]  # Last response
    count: Annotated[int, "Length of the current conversation"]  # Conversation length

    # Phase 3B dynamic debate-termination bookkeeping. All plain JSON-safe
    # structures so the debate evaluator state survives LangGraph checkpointing.
    turns: NotRequired[
        Annotated[list, "Serialized DebateTurn dicts (readable + metadata) in speaker order"]
    ]
    conflicts: NotRequired[
        Annotated[list, "Serialized ConflictRecord dicts tracked across the debate"]
    ]
    stances: NotRequired[
        Annotated[dict, "Serialized StanceSnapshot dicts keyed by speaker (Bull/Bear)"]
    ]
    previously_cited_evidence_ids: NotRequired[
        Annotated[list, "Evidence IDs cited before the current round, in citation order"]
    ]
    round_metrics: NotRequired[
        Annotated[list, "Serialized RoundMetrics dicts, one per completed round"]
    ]
    metadata_parse_failed_count: NotRequired[Annotated[int, "Count of failed metadata parses"]]
    no_new_evidence_streak: NotRequired[Annotated[int, "Consecutive rounds with zero new evidence"]]
    budget: NotRequired[
        Annotated[dict, "Serialized BudgetState dict (limits + usage + estimates)"]
    ]


# Risk management team state
class RiskDebateState(TypedDict):
    aggressive_history: Annotated[
        str, "Aggressive Agent's Conversation history"
    ]  # Conversation history
    conservative_history: Annotated[
        str, "Conservative Agent's Conversation history"
    ]  # Conversation history
    neutral_history: Annotated[
        str, "Neutral Agent's Conversation history"
    ]  # Conversation history
    history: Annotated[str, "Conversation history"]  # Conversation history
    latest_speaker: Annotated[str, "Analyst that spoke last"]
    current_aggressive_response: Annotated[
        str, "Latest response by the aggressive analyst"
    ]  # Last response
    current_conservative_response: Annotated[
        str, "Latest response by the conservative analyst"
    ]  # Last response
    current_neutral_response: Annotated[
        str, "Latest response by the neutral analyst"
    ]  # Last response
    judge_decision: Annotated[str, "Judge's decision"]
    count: Annotated[int, "Length of the current conversation"]  # Conversation length


class AgentState(MessagesState):
    company_of_interest: Annotated[str, "Company that we are interested in trading"]
    asset_type: Annotated[str, "Asset type under analysis such as stock or crypto"]
    instrument_context: Annotated[str, "Deterministic ticker identity resolved at run start"]
    trade_date: Annotated[str, "What date we are trading at"]

    sender: Annotated[str, "Agent that sent this message"]

    # research step
    market_report: Annotated[str, "Report from the Market Analyst"]
    sentiment_report: Annotated[str, "Report from the Sentiment Analyst"]
    news_report: Annotated[
        str, "Report from the News Researcher of current world affairs"
    ]
    fundamentals_report: Annotated[str, "Report from the Fundamentals Researcher"]

    # deterministic Data Quality Gate (Phase 3A). Plain JSON-safe primitives so
    # the gate result is checkpoint-serializable; see graph/data_quality_gate.py.
    data_quality_verdict: Annotated[str, "Gate verdict: normal/degraded/blocked"]
    data_quality_evidence_records: Annotated[
        list, "Serialized EvidenceRecord dicts for the verified market snapshot"
    ]
    data_quality_validation_results: Annotated[
        dict, "Serialized validation results keyed by evidence_id"
    ]
    data_quality_group_statuses: Annotated[
        list, "Serialized EvidenceGroupQuality dicts, one per evaluated category"
    ]
    data_quality_gate_decision: Annotated[
        dict, "Serialized GateDecision (verdict, limitations, reason codes)"
    ]
    data_quality_context: Annotated[
        str, "Human-readable gate constraint/context string for downstream prompts"
    ]
    data_quality_error: Annotated[
        str | None, "Gate error marker (None on a clean run; a message when fail-closed)"
    ]
    # Stage 2 STRUCTURED optional-category evidence contract (input-only). This
    # is the ONLY channel by which trustworthy structured optional-category
    # evidence (fundamentals, news, sentiment) enters the gate: a mapping of
    # category -> serialized EvidenceGroupQuality dict. Never parsed from analyst
    # prose; an absent value yields a deterministic unavailable/insufficient
    # result that degrades under the policy (see graph/data_quality_gate.py).
    data_quality_optional_evidence: NotRequired[
        Annotated[dict, "Optional-category EvidenceGroupQuality dicts by category"]
    ]

    # researcher team discussion step
    investment_debate_state: Annotated[
        InvestDebateState, "Current state of the debate on if to invest or not"
    ]
    # Phase 3B: deterministic run-level LLM usage {calls, tokens, seconds,
    # estimated}, updated by every Bull/Bear researcher call and read by the
    # Debate Evaluator to enforce the budget/reserve rules. Plain JSON-safe.
    debate_usage: NotRequired[
        Annotated[dict, "Run-level usage {calls, tokens, seconds, estimated}"]
    ]
    investment_plan: Annotated[str, "Plan generated by the Analyst"]
    # Phase 3B: the deterministic Debate Evaluator's serialized RoutingDecision
    # plus the associated RoundMetrics, written after each complete Bull+Bear
    # round. Plain JSON-safe (list sentinel).
    debate_termination_decision: NotRequired[
        Annotated[dict, "Serialized RoutingDecision dict (route, stop_reason, trace)"]
    ]

    trader_investment_plan: Annotated[str, "Plan generated by the Trader"]

    # risk management team discussion step
    risk_debate_state: Annotated[
        RiskDebateState, "Current state of the debate on evaluating risk"
    ]
    final_trade_decision: Annotated[str, "Final decision made by the Risk Analysts"]
    past_context: Annotated[str, "Memory log context injected at run start (same-ticker decisions + cross-ticker lessons)"]
    portfolio_context: Annotated[str, "Caller-supplied holdings and cash, rendered at run start; empty when not provided"]
