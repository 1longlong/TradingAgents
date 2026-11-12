# TradingAgents/graph/propagation.py

from typing import Any

from tradingagents.agents.utils.agent_states import (
    InvestDebateState,
    RiskDebateState,
)


class Propagator:
    """Handles state initialization and propagation through the graph."""

    def __init__(self, max_recur_limit=100):
        """Initialize with configuration parameters."""
        self.max_recur_limit = max_recur_limit

    def create_initial_state(
        self,
        company_name: str,
        trade_date: str,
        asset_type: str = "stock",
        past_context: str = "",
        instrument_context: str = "",
        portfolio_context: str = "",
        results_dir: str = "",
        run_id: str | None = None,
        usage_ledger_path: str | None = None,
    ) -> dict[str, Any]:
        """Create the initial state for the agent graph.

        ``instrument_context`` is the deterministic ticker-identity string
        resolved once at run start (see
        ``TradingAgentsGraph.resolve_instrument_context``). When empty, agents
        fall back to ticker-only context via
        ``get_instrument_context_from_state``. ``results_dir`` (when set) lets
        the debate nodes derive default durable audit paths for aborted
        invocations and partial-debate quarantine.

        ``run_id``/``usage_ledger_path`` (ADR-009) carry the real execution
        identity and durable usage-ledger path for the run so the usage capture
        can scope spend to exactly this execution.
        """
        state: dict[str, Any] = {
            "messages": [("human", company_name)],
            "company_of_interest": company_name,
            "asset_type": asset_type,
            "instrument_context": instrument_context,
            "trade_date": str(trade_date),
            "results_dir": results_dir,
            "past_context": past_context,
            "portfolio_context": portfolio_context,
            "investment_debate_state": InvestDebateState(
                {
                    "bull_history": "",
                    "bear_history": "",
                    "history": "",
                    "current_response": "",
                    "judge_decision": "",
                    "count": 0,
                }
            ),
            "risk_debate_state": RiskDebateState(
                {
                    "aggressive_history": "",
                    "conservative_history": "",
                    "neutral_history": "",
                    "history": "",
                    "latest_speaker": "",
                    "current_aggressive_response": "",
                    "current_conservative_response": "",
                    "current_neutral_response": "",
                    "judge_decision": "",
                    "count": 0,
                }
            ),
            "market_report": "",
            "fundamentals_report": "",
            "sentiment_report": "",
            "news_report": "",
            # Data Quality Gate (Phase 3A). Default to a fail-closed blank so a
            # checkpoint/caller that predates the gate still routes blocked rather
            # than silently continuing as normal; see graph/data_quality_gate.py.
            "data_quality_verdict": "blocked",
            "data_quality_evidence_records": [],
            "data_quality_validation_results": {},
            "data_quality_group_statuses": [],
            "data_quality_gate_decision": {},
            "data_quality_context": "",
            "data_quality_error": "gate not run",
            "data_quality_source_attempts": [],
        }
        if run_id:
            state["run_id"] = run_id
        if usage_ledger_path:
            state["usage_ledger_path"] = usage_ledger_path
        return state

    def get_graph_args(self, callbacks: list | None = None) -> dict[str, Any]:
        """Get arguments for the graph invocation.

        Args:
            callbacks: Optional list of callback handlers for tool execution tracking.
                       Note: LLM callbacks are handled separately via LLM constructor.
        """
        config = {"recursion_limit": self.max_recur_limit}
        if callbacks:
            config["callbacks"] = callbacks
        return {
            "stream_mode": "values",
            "config": config,
        }
