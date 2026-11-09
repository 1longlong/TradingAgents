# TradingAgents/graph/conditional_logic.py

from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.agents.utils.tool_governance import round_limit_reached
from tradingagents.graph.market_governance import parse_market_tool_governance


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

    def should_continue_market_governed(self, state: AgentState):
        """Market tool governance (opt-in): where the analyst goes next.

        * an unusable answer (refusal, explicit truncation, blank body) or a
          pending call nobody may run -> **raise**: this is a dead end, not a
          reason to spend another generation. No report is stored, the analyst
          is not marked finished, and no second request is made;
        * tool calls, while the allowance is not yet spent ->
          ``market_tool_prepare``, which registers the round. Once the allowance
          is spent a tool-call turn cannot start a new batch: it goes to
          ``market_wrap_up`` (which pairs its calls and writes the report from
          the evidence already collected), so the run never re-enters the
          normal tool loop;
        * a plain-text answer -> ``market_finish``: the analyst wrote the
          report itself, so the single wrap-up is not needed (and must not
          overwrite it);
        * nothing at all -> ``market_wrap_up``, the only place a report is
          written for it.

        It never goes to ``tools_market``.
        """
        from tradingagents.graph.market_tool_governance import (
            MarketGovernanceError,
            analyst_report,
            pending_calls,
            reject_unusable_response,
            scope_of,
        )

        last_message = state["messages"][-1]
        if getattr(last_message, "tool_calls", None):
            scope = scope_of(state.get("tool_governance") or {})
            limits = parse_market_tool_governance(
                state.get("run_config") or {}
            ).limits()
            spent = bool(scope.get("finished") or scope.get("closed")) or (
                round_limit_reached(scope, limits)
            )
            pending = pending_calls(state) if spent else []
            if pending:
                # A call with no reply and no allowance left to run it: routing
                # on would hand the wrap-up a dangling tool call.
                raise MarketGovernanceError(
                    "the market analyst's allowance is spent and these calls "
                    f"cannot run: {', '.join(pending)}; no report was written"
                )
            if spent:
                return "market_wrap_up"
            return "market_tool_prepare"
        if analyst_report(last_message):
            return "market_finish"
        # Not a usable report. A refusal, an explicit truncation or a blank
        # answer is final: fail here rather than send it to the wrap-up as if
        # it were a request for one more generation.
        reject_unusable_response(last_message, "market analyst")
        return "market_wrap_up"

    def should_execute_market_prepared(self, state: AgentState):
        """Market tool governance: run the registered round, wrap up, or go back.

        The prepare node has already saved the round in the graph state. That
        saved plan decides what happens to *this* batch, and it must be honoured
        even when the round it charged was the last one allowed: reaching the
        cap forbids a **new** batch, it does not revoke calls the plan already
        approved.

        * the plan still has a call to execute/reuse/replay ->
          ``market_tool_execute``;
        * every call was answered inside prepare (all blocked) and the
          allowance is spent -> ``market_wrap_up``: no new batch may run;
        * every call was answered but rounds remain -> ``Market Analyst``,
          which decides the next step (another batch or its own report).

        Once the allowance is spent, ``should_continue_market_governed`` never
        sends the analyst back here, so the loop cannot resume.
        """
        from tradingagents.graph.market_tool_governance import (
            prepared_work,
            scope_of,
        )

        if prepared_work(state):
            return "market_tool_execute"
        scope = scope_of(state.get("tool_governance") or {})
        limits = parse_market_tool_governance(
            state.get("run_config") or {}
        ).limits()
        if scope.get("closed") or round_limit_reached(scope, limits):
            return "market_wrap_up"
        return "Market Analyst"

    def should_continue_market_after_execute(self, state: AgentState):
        """Market tool governance: where the run goes once a batch has run.

        The batch the analyst asked for has **fully** executed and every call
        is paired before this is asked. Only then:

        * allowance still left -> ``Market Analyst``: it is its turn to decide
          (another batch or its own report);
        * allowance spent -> ``market_wrap_up``: no new batch may start, so the
          run goes straight to the single wrap-up. The analyst is **not** asked
          again just to be told it may not use tools.

        ``prepared_work`` guards the invariant: if the saved plan still has
        work, routing on would drop approved calls, so that is refused rather
        than silently wrapped up.
        """
        from tradingagents.graph.market_tool_governance import (
            MarketGovernanceError,
            prepared_work,
            scope_of,
        )

        if prepared_work(state):
            raise MarketGovernanceError(
                "the market tool batch is not fully executed; routing on would "
                "drop approved calls"
            )
        scope = scope_of(state.get("tool_governance") or {})
        limits = parse_market_tool_governance(
            state.get("run_config") or {}
        ).limits()
        if scope.get("closed") or round_limit_reached(scope, limits):
            return "market_wrap_up"
        return "Market Analyst"

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
