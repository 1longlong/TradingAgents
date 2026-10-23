# TradingAgents/graph/setup.py

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from tradingagents.agents import (
    create_aggressive_debator,
    create_bear_researcher,
    create_bull_researcher,
    create_conservative_debator,
    create_fundamentals_analyst,
    create_market_analyst,
    create_msg_delete,
    create_neutral_debator,
    create_news_analyst,
    create_portfolio_manager,
    create_research_manager,
    create_sentiment_analyst,
    create_trader,
)
from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.debate.config import (
    DEFAULT_DEBATE_TERMINATION_CONFIG,
    DebateTerminationConfig,
)
from tradingagents.debate.evaluator_node import create_debate_evaluator_node

from .analyst_execution import build_analyst_execution_plan
from .conditional_logic import ConditionalLogic
from .data_quality_gate import create_data_quality_gate_node

# Every target a shared conditional router can return. Each edge driven by the
# router maps all of them, so a fall-through return (e.g. under prompt/i18n/
# refactor drift in the speaker labels) can never hit a missing path_map entry
# and crash LangGraph mid-run (#1088).
DEBATE_PATH_MAP = {
    "Bull Researcher": "Bull Researcher",
    "Bear Researcher": "Bear Researcher",
    "Research Manager": "Research Manager",
}
# The Debate Evaluator routes back to a speaker (continue) or to the Research
# Manager (summarize/stop). Complete map so a fall-through return can never hit
# a missing entry (#1088).
DEBATE_EVALUATOR_PATH_MAP = {
    "Bull Researcher": "Bull Researcher",
    "Bear Researcher": "Bear Researcher",
    "Research Manager": "Research Manager",
}
RISK_ANALYSIS_PATH_MAP = {
    "Aggressive Analyst": "Aggressive Analyst",
    "Conservative Analyst": "Conservative Analyst",
    "Neutral Analyst": "Neutral Analyst",
    "Portfolio Manager": "Portfolio Manager",
}
# The Data Quality Gate routes to exactly two targets: Bull Researcher (the
# gate deemed the market data normal or degraded, so the debate may proceed with
# restrictions) or Research Manager (the gate blocked the debate, forcing an
# evidence-insufficient restricted conclusion). Complete map so a fall-through
# can never hit a missing entry (#1088).
GATE_PATH_MAP = {
    "Bull Researcher": "Bull Researcher",
    "Research Manager": "Research Manager",
}


class GraphSetup:
    """Handles the setup and configuration of the agent graph."""

    def __init__(
        self,
        quick_thinking_llm: Any,
        deep_thinking_llm: Any,
        tool_nodes: dict[str, ToolNode],
        conditional_logic: ConditionalLogic,
        data_quality_gate_factory: Any = None,
        debate_termination_config: DebateTerminationConfig | None = None,
        debate_evaluator_factory: Any = None,
    ):
        """Initialize with required components.

        ``data_quality_gate_factory`` is an optional node factory (defaults to
        :func:`create_data_quality_gate_node`) so tests can inject a fixed
        snapshot / deterministic clock without touching a network. It must be
        callable with no arguments and return a LangGraph node.

        ``debate_termination_config`` is the validated Phase 3B configuration
        group; when ``None`` the built-in defaults are used and the evaluator
        resolves the config from the state on first run. ``debate_evaluator_factory``
        is an optional node factory so tests can inject a deterministic evaluator
        node; it defaults to :func:`create_debate_evaluator_node`.
        """
        self.quick_thinking_llm = quick_thinking_llm
        self.deep_thinking_llm = deep_thinking_llm
        self.tool_nodes = tool_nodes
        self.conditional_logic = conditional_logic
        self.debate_termination_config = (
            debate_termination_config or DEFAULT_DEBATE_TERMINATION_CONFIG
        )
        self.data_quality_gate_node = (
            data_quality_gate_factory()
            if data_quality_gate_factory is not None
            else create_data_quality_gate_node()
        )
        self.debate_evaluator_node = (
            debate_evaluator_factory()
            if debate_evaluator_factory is not None
            else create_debate_evaluator_node(config=self.debate_termination_config)
        )

    def setup_graph(
        self, selected_analysts=("market", "social", "news", "fundamentals")
    ):
        """Set up and compile the agent workflow graph.

        Args:
            selected_analysts (list): List of analyst types to include. Options are:
                - "market": Market analyst
                - "social": Social media analyst
                - "news": News analyst
                - "fundamentals": Fundamentals analyst
        """
        plan = build_analyst_execution_plan(selected_analysts)

        analyst_factories = {
            "market": lambda: create_market_analyst(self.quick_thinking_llm),
            "social": lambda: create_sentiment_analyst(self.quick_thinking_llm),
            "news": lambda: create_news_analyst(self.quick_thinking_llm),
            "fundamentals": lambda: create_fundamentals_analyst(self.quick_thinking_llm),
        }

        # Create researcher and manager nodes
        bull_researcher_node = create_bull_researcher(self.quick_thinking_llm)
        bear_researcher_node = create_bear_researcher(self.quick_thinking_llm)
        research_manager_node = create_research_manager(self.deep_thinking_llm)
        trader_node = create_trader(self.quick_thinking_llm)

        # Create risk analysis nodes
        aggressive_analyst = create_aggressive_debator(self.quick_thinking_llm)
        neutral_analyst = create_neutral_debator(self.quick_thinking_llm)
        conservative_analyst = create_conservative_debator(self.quick_thinking_llm)
        portfolio_manager_node = create_portfolio_manager(self.deep_thinking_llm)

        # Create workflow
        workflow = StateGraph(AgentState)

        # Add analyst nodes to the graph
        for spec in plan.specs:
            workflow.add_node(spec.agent_node, analyst_factories[spec.key]())
            workflow.add_node(spec.clear_node, create_msg_delete())
            workflow.add_node(spec.tool_node, self.tool_nodes[spec.key])

        # Add other nodes
        workflow.add_node("Data Quality Gate", self.data_quality_gate_node)
        workflow.add_node("Bull Researcher", bull_researcher_node)
        workflow.add_node("Bear Researcher", bear_researcher_node)
        workflow.add_node("Debate Evaluator", self.debate_evaluator_node)
        workflow.add_node("Research Manager", research_manager_node)
        workflow.add_node("Trader", trader_node)
        workflow.add_node("Aggressive Analyst", aggressive_analyst)
        workflow.add_node("Neutral Analyst", neutral_analyst)
        workflow.add_node("Conservative Analyst", conservative_analyst)
        workflow.add_node("Portfolio Manager", portfolio_manager_node)

        # Define edges
        # Start with the first analyst
        workflow.add_edge(START, plan.specs[0].agent_node)

        # Connect analysts in sequence
        for i, spec in enumerate(plan.specs):
            current_analyst = spec.agent_node
            current_tools = spec.tool_node
            current_clear = spec.clear_node

            # Add conditional edges for current analyst
            workflow.add_conditional_edges(
                current_analyst,
                getattr(self.conditional_logic, f"should_continue_{spec.key}"),
                [current_tools, current_clear],
            )
            workflow.add_edge(current_tools, current_analyst)

            # Connect to next analyst or to the Data Quality Gate if this is the
            # last analyst. The gate then conditionally routes to Bull Researcher
            # (normal/degraded) or straight to Research Manager (blocked).
            if i < len(plan.specs) - 1:
                workflow.add_edge(current_clear, plan.specs[i + 1].agent_node)
            else:
                workflow.add_edge(current_clear, "Data Quality Gate")

        # After the gate, route to the Bull Researcher (normal/degraded) or the
        # Research Manager (blocked). Fails closed in the router (#1088).
        workflow.add_conditional_edges(
            "Data Quality Gate",
            self.conditional_logic.should_continue_after_data_gate,
            GATE_PATH_MAP,
        )

        # The debate runs Bull -> Bear -> Debate Evaluator, and the evaluator is
        # the single authoritative dynamic router (Phase 3B): it either returns
        # to a speaker (continue) or routes to the Research Manager
        # (summarize/stop). The old per-turn fixed-count router is retained as a
        # helper for the disabled baseline mode but is not a graph edge, so the
        # evaluator owns every routing decision (#1088).
        workflow.add_edge("Bull Researcher", "Bear Researcher")
        workflow.add_edge("Bear Researcher", "Debate Evaluator")
        workflow.add_conditional_edges(
            "Debate Evaluator",
            self.conditional_logic.should_continue_after_debate_evaluator,
            DEBATE_EVALUATOR_PATH_MAP,
        )
        workflow.add_edge("Research Manager", "Trader")
        workflow.add_edge("Trader", "Aggressive Analyst")
        # All three risk edges share the complete RISK_ANALYSIS_PATH_MAP (#1088).
        for risk_node in ("Aggressive Analyst", "Conservative Analyst", "Neutral Analyst"):
            workflow.add_conditional_edges(
                risk_node,
                self.conditional_logic.should_continue_risk_analysis,
                RISK_ANALYSIS_PATH_MAP,
            )

        workflow.add_edge("Portfolio Manager", END)

        return workflow
