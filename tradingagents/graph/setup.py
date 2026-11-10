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
    create_sentiment_prefetch_node,
    create_trader,
)
from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.dataflows.config import get_config

from .analyst_execution import build_analyst_execution_plan
from .conditional_logic import ConditionalLogic
from .fundamentals_governance import parse_fundamentals_tool_governance
from .fundamentals_tool_governance import create_fundamentals_governance_nodes
from .market_governance import parse_market_tool_governance
from .market_tool_governance import create_market_governance_nodes
from .news_governance import parse_news_tool_governance
from .news_tool_governance import create_news_governance_nodes
from .sentiment_prefetch import PREFETCH_NODE, parse_sentiment_prefetch

# Every target a shared conditional router can return. Each edge driven by the
# router maps all of them, so a fall-through return (e.g. under prompt/i18n/
# refactor drift in the speaker labels) can never hit a missing path_map entry
# and crash LangGraph mid-run (#1088).
DEBATE_PATH_MAP = {
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


class GraphSetup:
    """Handles the setup and configuration of the agent graph."""

    def __init__(
        self,
        quick_thinking_llm: Any,
        deep_thinking_llm: Any,
        tool_nodes: dict[str, ToolNode],
        conditional_logic: ConditionalLogic,
        config: dict[str, Any] | None = None,
    ):
        """Initialize with required components."""
        self.quick_thinking_llm = quick_thinking_llm
        self.deep_thinking_llm = deep_thinking_llm
        self.tool_nodes = tool_nodes
        self.conditional_logic = conditional_logic
        # The run config decides whether market tool governance is on. ``None``
        # falls back to the configuration the run installed (``get_config``).
        self.config = config

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

        # Analyst tool governance is opt-in per analyst (default off), each with
        # its own config section. With one on, that analyst routes through its
        # own prepare/execute/wrap-up nodes; nothing else in the graph changes,
        # and the other analysts stay on today's path.
        run_config = get_config() if self.config is None else self.config
        governed = {
            "market": parse_market_tool_governance(run_config).enabled
            and any(spec.key == "market" for spec in plan.specs),
            "fundamentals": parse_fundamentals_tool_governance(run_config).enabled
            and any(spec.key == "fundamentals" for spec in plan.specs),
            "news": parse_news_tool_governance(run_config).enabled
            and any(spec.key == "news" for spec in plan.specs),
        }
        governance_nodes: dict[str, dict[str, Any]] = {}
        if governed["market"]:
            governance_nodes["market"] = create_market_governance_nodes(
                llm=self.quick_thinking_llm, tool_node=self.tool_nodes["market"]
            )
        if governed["fundamentals"]:
            governance_nodes["fundamentals"] = create_fundamentals_governance_nodes(
                llm=self.quick_thinking_llm, tool_node=self.tool_nodes["fundamentals"]
            )
        if governed["news"]:
            governance_nodes["news"] = create_news_governance_nodes(
                llm=self.quick_thinking_llm, tool_node=self.tool_nodes["news"]
            )

        # The sentiment prefetch split (opt-in, default off) adds one node in
        # front of the sentiment analyst: it saves the three source blocks, and
        # the analyst then consumes them instead of fetching. With it off the
        # analyst is its original single node.
        prefetch_split = (
            parse_sentiment_prefetch(run_config).enabled
            and any(spec.key == "social" for spec in plan.specs)
        )

        analyst_factories = {
            "market": lambda: create_market_analyst(self.quick_thinking_llm),
            "social": lambda: create_sentiment_analyst(
                self.quick_thinking_llm, prefetch_split=prefetch_split
            ),
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
            if spec.key == "social" and prefetch_split:
                workflow.add_node(PREFETCH_NODE, create_sentiment_prefetch_node())
            if spec.key in governance_nodes:
                prefix = spec.key
                workflow.add_node(f"{prefix}_tool_prepare", governance_nodes[spec.key]["prepare"])
                workflow.add_node(f"{prefix}_tool_execute", governance_nodes[spec.key]["execute"])
                workflow.add_node(f"{prefix}_finish", governance_nodes[spec.key]["finish"])
                workflow.add_node(f"{prefix}_wrap_up", governance_nodes[spec.key]["wrap_up"])

        # Add other nodes
        workflow.add_node("Bull Researcher", bull_researcher_node)
        workflow.add_node("Bear Researcher", bear_researcher_node)
        workflow.add_node("Research Manager", research_manager_node)
        workflow.add_node("Trader", trader_node)
        workflow.add_node("Aggressive Analyst", aggressive_analyst)
        workflow.add_node("Neutral Analyst", neutral_analyst)
        workflow.add_node("Conservative Analyst", conservative_analyst)
        workflow.add_node("Portfolio Manager", portfolio_manager_node)

        def entry_node(spec) -> str:
            # The sentiment analyst is always entered through its prefetch node
            # when the split is on -- first in the plan or behind another
            # analyst -- because that node is what saves its sources.
            if spec.key == "social" and prefetch_split:
                return PREFETCH_NODE
            return spec.agent_node

        # Define edges
        # Start with the first analyst
        workflow.add_edge(START, entry_node(plan.specs[0]))

        # Connect analysts in sequence
        for i, spec in enumerate(plan.specs):
            current_analyst = spec.agent_node
            current_tools = spec.tool_node
            current_clear = spec.clear_node

            if spec.key in governed and governed[spec.key]:
                # A governed analyst. The analyst either asked for tools
                # (prepare registers the round) or stopped (wrap-up). The
                # prepare node then either lets it run or, once the allowance is
                # spent, sends it to the single wrap-up. The path never
                # re-enters the analyst's plain tool node.
                prefix = spec.key
                workflow.add_conditional_edges(
                    current_analyst,
                    getattr(
                        self.conditional_logic, f"should_continue_{prefix}_governed"
                    ),
                    [
                        f"{prefix}_tool_prepare",
                        f"{prefix}_wrap_up",
                        f"{prefix}_finish",
                    ],
                )
                workflow.add_conditional_edges(
                    f"{prefix}_tool_prepare",
                    getattr(
                        self.conditional_logic, f"should_execute_{prefix}_prepared"
                    ),
                    [f"{prefix}_tool_execute", f"{prefix}_wrap_up", current_analyst],
                )
                # After execute the batch is complete and paired; only now is
                # the next step decided. A spent allowance wraps up directly
                # instead of asking the analyst again.
                workflow.add_conditional_edges(
                    f"{prefix}_tool_execute",
                    getattr(
                        self.conditional_logic,
                        f"should_continue_{prefix}_after_execute",
                    ),
                    [current_analyst, f"{prefix}_wrap_up"],
                )
                workflow.add_edge(f"{prefix}_finish", current_clear)
                workflow.add_edge(f"{prefix}_wrap_up", current_clear)
            else:
                # Add conditional edges for current analyst
                workflow.add_conditional_edges(
                    current_analyst,
                    getattr(self.conditional_logic, f"should_continue_{spec.key}"),
                    [current_tools, current_clear],
                )
                workflow.add_edge(current_tools, current_analyst)

            # Connect to next analyst or to Bull Researcher if this is the last analyst
            if i < len(plan.specs) - 1:
                workflow.add_edge(current_clear, entry_node(plan.specs[i + 1]))
            else:
                workflow.add_edge(current_clear, "Bull Researcher")

        if prefetch_split:
            # Prefetch has no branch and no tools: success flows straight into
            # the generation node, and a failure propagates out (nothing saved).
            workflow.add_edge(PREFETCH_NODE, "Sentiment Analyst")

        # Both research-debate edges share the complete DEBATE_PATH_MAP (#1088).
        for debate_node in ("Bull Researcher", "Bear Researcher"):
            workflow.add_conditional_edges(
                debate_node,
                self.conditional_logic.should_continue_debate,
                DEBATE_PATH_MAP,
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
