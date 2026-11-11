from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.schemas import (
    FundamentalsAnalystReport,
    render_fundamentals_analyst_report,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    finalize_analyst_report,
)

from tradingagents.agents.utils.agent_utils import (
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_income_statement,
    get_instrument_context_from_state,
    get_language_instruction,
)


def create_fundamentals_analyst(llm, structured: bool = True):
    """Create the fundamentals analyst node.

    ``structured`` is the ablation switch for native structured output. When
    False the analyst never binds a schema and emits free text, so an ablation
    arm can run the pre-S2 path with every other variable held constant.
    """
    structured_llm = (
        bind_structured(llm, FundamentalsAnalystReport, "Fundamentals Analyst")
        if structured else None
    )
    def fundamentals_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = get_instrument_context_from_state(state)

        tools = [
            get_fundamentals,
            get_balance_sheet,
            get_cashflow,
            get_income_statement,
        ]

        system_message = (
            "You are a researcher tasked with analyzing fundamental information over the past week about a company. Please write a comprehensive report of the company's fundamental information such as financial documents, company profile, basic company financials, and company financial history to gain a full view of the company's fundamental information to inform traders. Make sure to include as much detail as possible. Provide specific, actionable insights with supporting evidence to help traders make informed decisions."
            + " Also state what would falsify your view: each invalidation condition should name the reported metric or guidance development that would prove the stance wrong, the signal a reader would watch, and the figure in your report it rests on. A threshold may only be quoted from tool output; if the reports give no number, leave it null rather than inventing one."
            + " Where the evidence supports it, lay out Bull, Base and Bear branches for the trade-date horizon, each with its trigger, what would rule it out, and a probability weight in percent. Weights estimate how likely each branch is, not your confidence in the report. Only assign weights when the evidence supports them and they sum to 100; otherwise set the status to not_estimable and leave the weights null. Never split the weight evenly by default."
            + " Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."
            + " Use the available tools: `get_fundamentals` for comprehensive company analysis, `get_balance_sheet`, `get_cashflow`, and `get_income_statement` for specific financial statements."
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " Report what your tools support; another agent decides the trade."
                    " You have access to the following tools: {tool_names}."
                    " Today's date is {current_date}; treat it as 'now' for all analysis and tool-call date ranges. {instrument_context}\n"
                    "{system_message}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)

        result = chain.invoke(state["messages"])

        report = ""
        report_obj = None

        if len(result.tool_calls) == 0:
            report, report_obj = finalize_analyst_report(
                llm=llm,
                structured_llm=structured_llm,
                messages=prompt.format_prompt(messages=state["messages"]).to_messages() + [result],
                render=render_fundamentals_analyst_report,
                agent_name="Fundamentals Analyst",
                free_text_block=result.content,
            )

        return {
            "messages": [result],
            "fundamentals_report": report,
            # Typed side-channel; see market_analyst_node for the contract.
            "fundamentals_report_obj": report_obj,
        }

    return fundamentals_analyst_node
