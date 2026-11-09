# TradingAgents/graph/conditional_logic.py

from typing import Any

from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.agents.utils.tool_governance import round_limit_reached
from tradingagents.graph.market_governance import parse_market_tool_governance


def _analyst_node(analyst: str) -> str:
    """The graph label of a governed analyst's node."""
    return "Market Analyst" if analyst == "market" else "Fundamentals Analyst"


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

    # -- governed analysts (opt-in tool governance) -------------------------

    def _governed_analyst(
        self,
        state: AgentState,
        *,
        analyst: str,
        module: Any,
        parse_limits: Any,
        error: type[Exception],
    ):
        """Where a governed analyst goes next, read from **its own** record.

        * an unusable answer (refusal, explicit truncation, blank body) -> raise:
          this is a dead end, not a reason to spend another generation;
        * tool calls, while the allowance is not yet spent -> the analyst's
          ``<analyst>_tool_prepare``, which registers the round;
        * tool calls once the allowance is spent -> ``<analyst>_wrap_up`` (it
          pairs the calls and writes the report from the evidence already
          collected), so the run never re-enters the normal tool loop;
        * a plain-text answer -> ``<analyst>_finish``: the analyst wrote the
          report itself;
        * nothing usable at all -> raise (see the first point).

        It never goes to the analyst's plain tool node, and it never reads
        another analyst's record, messages or report.
        """
        last_message = state["messages"][-1]
        scope = module.scope_of(state.get("tool_governance") or {}, analyst=analyst)
        if getattr(last_message, "tool_calls", None):
            limits = parse_limits(state.get("run_config") or {}).limits()
            spent = bool(scope.get("finished") or scope.get("closed")) or (
                round_limit_reached(scope, limits)
            )
            pending = module.pending_calls(state, analyst=analyst) if spent else []
            if pending:
                # A call with no reply and no allowance left to run it: routing
                # on would hand the wrap-up a dangling tool call.
                raise error(
                    f"the {analyst} analyst's allowance is spent and these "
                    f"calls cannot run: {', '.join(pending)}; no report was written"
                )
            if spent:
                return f"{analyst}_wrap_up"
            return f"{analyst}_tool_prepare"
        if module.analyst_report(last_message):
            return f"{analyst}_finish"
        # Not a usable report. A refusal, an explicit truncation or a blank
        # answer is final: fail here rather than send it to the wrap-up as if
        # it were a request for one more generation.
        module.reject_unusable_response(last_message, f"{analyst} analyst", error)
        raise error(f"the {analyst} analyst did not produce a usable answer")

    def _governed_prepared(
        self,
        state: AgentState,
        *,
        analyst: str,
        module: Any,
        parse_limits: Any,
    ):
        """After prepare: run the registered round, wrap up, or go back.

        The prepare node has already saved the round in the graph state. That
        saved plan decides what happens to *this* batch, and it must be honoured
        even when the round it charged was the last one allowed: reaching the
        cap forbids a **new** batch, it does not revoke calls the plan already
        approved.
        """
        if module.prepared_work(state, analyst=analyst):
            return f"{analyst}_tool_execute"
        scope = module.scope_of(state.get("tool_governance") or {}, analyst=analyst)
        limits = parse_limits(state.get("run_config") or {}).limits()
        if scope.get("closed") or round_limit_reached(scope, limits):
            return f"{analyst}_wrap_up"
        return _analyst_node(analyst)

    def _governed_after_execute(
        self,
        state: AgentState,
        *,
        analyst: str,
        module: Any,
        parse_limits: Any,
        error: type[Exception],
    ):
        """After a batch has fully run: the analyst again, or the wrap-up.

        The batch the analyst asked for has **fully** executed and every call is
        paired before this is asked. Once the allowance is spent the run goes
        straight to the single wrap-up: the analyst is **not** asked again just
        to be told it may not use tools.
        """
        if module.prepared_work(state, analyst=analyst):
            raise error(
                f"the {analyst} tool batch is not fully executed; routing on "
                "would drop approved calls"
            )
        scope = module.scope_of(state.get("tool_governance") or {}, analyst=analyst)
        limits = parse_limits(state.get("run_config") or {}).limits()
        if scope.get("closed") or round_limit_reached(scope, limits):
            return f"{analyst}_wrap_up"
        return _analyst_node(analyst)

    def should_continue_market_governed(self, state: AgentState):
        """Market tool governance (opt-in): where the analyst goes next.

        See :meth:`_governed_analyst` for the branch rules; the market record
        (``analysts["market"]``) and the ``market_tool_governance`` section are
        the only inputs.
        """
        from tradingagents.graph import market_tool_governance

        return self._governed_analyst(
            state,
            analyst="market",
            module=market_tool_governance,
            parse_limits=parse_market_tool_governance,
            error=market_tool_governance.MarketGovernanceError,
        )

    def should_execute_market_prepared(self, state: AgentState):
        """Market tool governance: run the registered round, wrap up, or go back."""
        from tradingagents.graph import market_tool_governance

        return self._governed_prepared(
            state,
            analyst="market",
            module=market_tool_governance,
            parse_limits=parse_market_tool_governance,
        )

    def should_continue_market_after_execute(self, state: AgentState):
        """Market tool governance: where the run goes once a batch has run."""
        from tradingagents.graph import market_tool_governance

        return self._governed_after_execute(
            state,
            analyst="market",
            module=market_tool_governance,
            parse_limits=parse_market_tool_governance,
            error=market_tool_governance.MarketGovernanceError,
        )

    def should_continue_fundamentals_governed(self, state: AgentState):
        """Fundamentals tool governance (opt-in): where the analyst goes next.

        Same rules as :meth:`should_continue_market_governed`, read only from
        the fundamentals record (``analysts["fundamentals"]``) and the
        ``fundamentals_tool_governance`` section -- never the market analyst's.
        """
        from tradingagents.graph import fundamentals_tool_governance as ftg
        from tradingagents.graph.fundamentals_governance import (
            parse_fundamentals_tool_governance,
        )

        return self._governed_analyst(
            state,
            analyst="fundamentals",
            module=ftg,
            parse_limits=parse_fundamentals_tool_governance,
            error=ftg.FundamentalsGovernanceError,
        )

    def should_execute_fundamentals_prepared(self, state: AgentState):
        """Fundamentals tool governance: run the registered round, wrap up, or go back."""
        from tradingagents.graph import fundamentals_tool_governance as ftg
        from tradingagents.graph.fundamentals_governance import (
            parse_fundamentals_tool_governance,
        )

        return self._governed_prepared(
            state,
            analyst="fundamentals",
            module=ftg,
            parse_limits=parse_fundamentals_tool_governance,
        )

    def should_continue_fundamentals_after_execute(self, state: AgentState):
        """Fundamentals tool governance: where the run goes once a batch has run."""
        from tradingagents.graph import fundamentals_tool_governance as ftg
        from tradingagents.graph.fundamentals_governance import (
            parse_fundamentals_tool_governance,
        )

        return self._governed_after_execute(
            state,
            analyst="fundamentals",
            module=ftg,
            parse_limits=parse_fundamentals_tool_governance,
            error=ftg.FundamentalsGovernanceError,
        )

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
