# TradingAgents/graph/conditional_logic.py

from tradingagents.agents.utils.agent_states import AgentState


class ConditionalLogic:
    """Handles conditional logic for determining graph flow."""

    def __init__(self, max_debate_rounds=1, max_risk_discuss_rounds=1):
        """Initialize with configuration parameters."""
        self.max_debate_rounds = max_debate_rounds
        self.max_risk_discuss_rounds = max_risk_discuss_rounds

    def should_continue_market(self, state: AgentState):
        """Determine if market analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_market"
        return "Msg Clear Market"

    def should_continue_social(self, state: AgentState):
        """Determine if sentiment-analyst tool round should continue.

        Method name keeps the legacy ``social`` suffix to match the
        ``AnalystType.SOCIAL = "social"`` wire value (saved-config
        back-compat); the returned ``clear_node`` label uses the v0.2.5
        rename so it matches the node registered by the execution plan.
        """
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_social"
        return "Msg Clear Sentiment"

    def should_continue_news(self, state: AgentState):
        """Determine if news analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_news"
        return "Msg Clear News"

    def should_continue_fundamentals(self, state: AgentState):
        """Determine if fundamentals analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_fundamentals"
        return "Msg Clear Fundamentals"

    def should_continue_debate(self, state: AgentState) -> str:
        """Determine if debate should continue."""

        if (
            state["investment_debate_state"]["count"] >= 2 * self.max_debate_rounds
        ):  # 3 rounds of back-and-forth between 2 agents
            return "Research Manager"
        if state["investment_debate_state"]["current_response"].startswith("Bull"):
            return "Bear Researcher"
        return "Bull Researcher"

    def should_continue_after_debate_evaluator(self, state: AgentState) -> str:
        """Route after the Debate Evaluator node (Phase 3B).

        The Debate Evaluator writes a serialized :class:`RoutingDecision` to
        ``debate_termination_decision``. A ``continue`` route sends the debate
        back to the next speaker (Bull Researcher by default); a ``summarize``
        or ``stop`` route sends it to the Research Manager. Missing or
        malformed evaluator state fails closed to the Research Manager so a
        broken evaluator can never loop the debate unboundedly (#1088).
        """
        decision = state.get("debate_termination_decision")
        if not isinstance(decision, dict) or not decision:
            return "Research Manager"
        route = decision.get("route")
        if route == "continue":
            speaker = decision.get("next_speaker")
            if speaker == "Bull":
                return "Bull Researcher"
            if speaker == "Bear":
                return "Bear Researcher"
            # A drift/unknown speaker fails closed rather than looping.
            return "Research Manager"
        return "Research Manager"

    def should_continue_after_data_gate(self, state: AgentState) -> str:
        """Route after the Data Quality Gate.

        Returns either ``"Bull Researcher"`` — the gate verdict is ``normal`` or
        ``degraded``, so the standard debate may proceed (with restrictions) —
        or ``"Research Manager"`` — the verdict is ``blocked``, or the gate
        state is missing/malformed, in which case the run fails closed and skips
        the normal Bull/Bear debate straight to an evidence-insufficient
        restricted conclusion.

        Failing closed is authoritative: any gate-state anomaly (absent fields,
        an empty or unparseable decision object, a verdict/decision that is not
        one of the three known values, or a verdict that disagrees with the
        decision object) routes blocked to the Research Manager rather than
        silently continuing as an unrestricted debate. Only a decision object
        whose ``decision`` field and the state's ``data_quality_verdict`` are
        both the same ``normal`` or ``degraded`` value may route to the Bull
        Researcher.
        """
        decision = state.get("data_quality_gate_decision")
        verdict = state.get("data_quality_verdict")

        # The decision object must be a non-empty dict carrying a known decision.
        if not isinstance(decision, dict) or not decision:
            return "Research Manager"
        decision_value = decision.get("decision")
        if decision_value not in ("normal", "degraded", "blocked"):
            return "Research Manager"
        # The state verdict must be a known (non-empty) string matching the
        # decision object; a mismatch means the gate state is inconsistent.
        if not isinstance(verdict, str):
            return "Research Manager"
        verdict = verdict.strip()
        if verdict not in ("normal", "degraded", "blocked"):
            return "Research Manager"
        if verdict != decision_value:
            return "Research Manager"
        if verdict == "blocked":
            return "Research Manager"
        return "Bull Researcher"

    def should_continue_risk_analysis(self, state: AgentState) -> str:
        """Determine if risk analysis should continue."""
        if (
            state["risk_debate_state"]["count"] >= 3 * self.max_risk_discuss_rounds
        ):  # 3 rounds of back-and-forth between 3 agents
            return "Portfolio Manager"
        if state["risk_debate_state"]["latest_speaker"].startswith("Aggressive"):
            return "Conservative Analyst"
        if state["risk_debate_state"]["latest_speaker"].startswith("Conservative"):
            return "Neutral Analyst"
        return "Aggressive Analyst"
