from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.schemas import (
    NewsAnalystReport,
    NewsSourceStatus,
    classify_news_source_availability,
    render_news_analyst_report,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    finalize_analyst_report,
)

from tradingagents.agents.utils.agent_utils import (
    get_global_news,
    get_instrument_context_from_state,
    get_language_instruction,
    get_macro_indicators,
    get_macro_indicators_batch,
    get_news,
    get_prediction_markets,
)


def create_news_analyst(llm, batch_macro: bool = True, structured: bool = True):
    """Create the news analyst node.

    Two ablation switches, both defaulting to the shipped behaviour:

    ``batch_macro``
        When False the batch tool is neither imported into the node's tool list
        nor mentioned in the prompt, so the model cannot call it. The
        single-series ``get_macro_indicators`` tool remains available, which is
        what makes the OFF arm the genuine pre-batch behaviour rather than a
        crippled one.
    ``structured``
        When False the analyst never binds the S2 schema and emits free text.
    """
    structured_llm = (
        bind_structured(llm, NewsAnalystReport, "News Analyst")
        if structured else None
    )
    def news_analyst_node(state):
        current_date = state["trade_date"]
        asset_type = state.get("asset_type", "stock")
        asset_label = "company" if asset_type == "stock" else "asset"
        instrument_context = get_instrument_context_from_state(state)

        tools = [
            get_news,
            get_global_news,
            get_macro_indicators,
            get_prediction_markets,
        ]
        if batch_macro:
            tools.append(get_macro_indicators_batch)

        # Only advertise the batch tool when it is actually bound. Naming an
        # absent tool in the prompt is what causes "unknown tool" failures.
        macro_hint = (
            " — or prefer the batch whenever you need more than one series, since "
            "get_macro_indicators_batch(indicators, curr_date, look_back_days) "
            "returns them in a single call"
            if batch_macro
            else ""
        )
        system_message = (
            f"You are a news researcher tasked with analyzing recent news and trends over the past week. Please write a comprehensive report of the current state of the world that is relevant for trading and macroeconomics. Use the available tools: get_news(ticker, start_date, end_date) for {asset_label}-specific news by ticker symbol, get_global_news(curr_date, look_back_days, limit) for broader macroeconomic news, get_macro_indicators(indicator, curr_date, look_back_days) to ground macro commentary in actual data from FRED (e.g. 'cpi', 'core_pce', 'unemployment', 'fed_funds_rate', '10y_treasury', 'yield_curve'){macro_hint}, and get_prediction_markets(topic, limit) for live market-implied probabilities of forward-looking events (e.g. 'Fed rate cut', 'recession 2026', geopolitical or sector events). Provide specific, actionable insights with supporting evidence to help traders make informed decisions."
            + """ Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."""
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

        if len(result.tool_calls) == 0:
            # Decided in Python from the tool results, not by the model: a dead
            # company-news feed must not become a directional stance.
            news_status = classify_news_source_availability(state["messages"])

            def render(report):
                return render_news_analyst_report(
                    report.model_copy(update={"news_source_status": news_status})
                )

            report, _ = finalize_analyst_report(
                llm=llm,
                structured_llm=structured_llm,
                messages=prompt.format_prompt(messages=state["messages"]).to_messages() + [result],
                render=render,
                agent_name="News Analyst",
                free_text_block=result.content,
            )
            if news_status is NewsSourceStatus.UNAVAILABLE and not report.startswith(
                "> **News source unavailable"
            ):
                # The prose fallback never passes through the renderer, so the
                # model's own stance header would survive unchallenged. Prepend
                # the authoritative one (same approach as the sentiment node).
                report = (
                    "> **News source unavailable for this window.** The stance is"
                    " **Unknown**, not Neutral: no company-specific news was"
                    " retrieved, so the market's news flow cannot be read. Any"
                    " macro observation below is context, not a news-driven"
                    " view.\n\n**Stance:** Unknown\n\n" + report
                )

        return {
            "messages": [result],
            "news_report": report,
        }

    return news_analyst_node
