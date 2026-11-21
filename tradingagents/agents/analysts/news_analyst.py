from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.schemas import (
    NewsAnalystReport,
    NewsSourceStatus,
    classify_news_source_availability,
    render_news_analyst_report,
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
from tradingagents.agents.utils.structured import (
    _schema_tool_name,
    bind_structured,
    finalize_analyst_report,
    finalize_single_pass,
    run_data_tools,
)
from tradingagents.debate.usage_capture import instrument_analyst_invoke

NEWS_UNAVAILABLE_PREFIX = (
    "> **News source unavailable for this window.** The stance is"
    " **Unknown**, not Neutral: no company-specific news was"
    " retrieved, so the market's news flow cannot be read. Any"
    " macro observation below is context, not a news-driven"
    " view.\n\n**Stance:** Unknown\n\n"
)

# The availability verdict is decided by :func:`classify_news_source_availability`
# from the real ``get_news`` ToolMessages and nowhere else. The guard never reads
# the report's prose to decide availability, and it never deletes a line because
# of the words in it: a model may legitimately quote the banner as evidence, put
# it in a blockquote or a code block, or write a sentence that opens with the
# same words (final audit H1). Only *provenance* is authoritative.
#
# The banner below is the application's own component: it is emitted only when
# the classifier says the company-news feed is dead, and it is identified by this
# exact text -- never by matching a heuristic against user/model content.
NEWS_UNAVAILABLE_BANNER = (
    "> **News source unavailable for this window.** The stance is"
    " **Unknown**, not Neutral: no company-specific news was"
    " retrieved, so the market's news flow cannot be read. Any"
    " macro observation below is context, not a news-driven"
    " view.\n\n**Stance:** Unknown\n\n"
)

# Kept for callers that imported the old name; same authoritative text.
NEWS_UNAVAILABLE_PREFIX = NEWS_UNAVAILABLE_BANNER


def _strip_application_banner(report: str) -> str:
    """Remove *this module's* banner, by exact text, from the head of ``report``.

    This is provenance, not content matching: the string removed is the literal
    component :data:`NEWS_UNAVAILABLE_BANNER` that this module inserted, and it
    is only ever inserted at the head of the report. Removing it makes guarding
    idempotent (guarding twice must not stack two banners, and re-guarding a
    cleared report must restore exactly one).

    No other text is examined. A model's own prose -- including a quoted banner,
    a banner in a code block, or a sentence that opens with the phrase -- is
    never touched here.
    """
    body = report.replace("\r\n", "\n").replace("\r", "\n").lstrip("\n")
    banner = NEWS_UNAVAILABLE_BANNER
    if body.startswith(banner):
        return body[len(banner):].lstrip("\n")
    return body


def _news_available_note(news_status: NewsSourceStatus) -> str:
    """An authoritative status line for a prose-fallback report on a live feed.

    This replaces the earlier "validation note", which tried to detect a
    contradiction by matching the words the model wrote. Two independent audits
    showed every such matcher fails in one direction or the other: a loose
    trigger fired on ordinary evidence mentions, a strict one missed realistic
    dead-feed assertions. The note therefore no longer inspects the report at
    all (user decision: never match text).

    Instead, on the prose-fallback path the system states the tool-derived
    availability, exactly as the renderer does on the schema path, so a
    downstream reader has the authoritative verdict no matter what the model
    wrote. It is emitted only when the classifier says the company feed was
    ``AVAILABLE``; on ``UNAVAILABLE`` the full banner in
    :func:`_guard_news_unavailable` already carries the verdict. Nothing in the
    model's text is read, rewritten, or removed.
    """
    if news_status is not NewsSourceStatus.AVAILABLE:
        return ""
    return (
        "> **Company news source: available.** The ``get_news`` tool returned"
        " company-specific articles for this window, so the analysis below is"
        " news-backed. This line is set by the system from the tool result and"
        " does not restate or override the analyst's text.\n\n"
    )


def _guard_news_unavailable(report: str, news_status: NewsSourceStatus) -> str:
    """Make ``report``'s availability status agree with ``news_status``.

    ``news_status`` is derived by the node from the real ``get_news`` results,
    never from ``report``. Two outcomes:

    * ``UNAVAILABLE`` -- the application banner is prepended (a system-controlled
      status component, identified by :data:`NEWS_UNAVAILABLE_BANNER`).
    * ``AVAILABLE`` -- the banner is *not* prepended and nothing model-authored is
      touched: the report is returned byte-identical apart from line-ending
      normalisation. The authoritative status is added by the caller through
      :func:`_news_available_note`, which never reads the text.

    Guarding is idempotent in both directions because the only text removed is
    this module's own banner, by exact match.
    """
    body = _strip_application_banner(report)
    if news_status is NewsSourceStatus.UNAVAILABLE:
        return NEWS_UNAVAILABLE_BANNER + body
    return body


def create_news_analyst(llm, batch_macro: bool = True, structured: bool = True,
                        single_pass: bool = False):
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
    ``single_pass``
        CAND-01 experiment switch; see ``create_market_analyst``. Ignored when
        ``structured`` is False.
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

        # Decided in Python from the tool results, not by the model: a dead
        # company-news feed must not become a directional stance. It must be
        # decided from the *finished* tool history: in single-pass mode the
        # data tools run *inside* ``finalize_single_pass``, so classifying the
        # messages the node received would judge a feed that had not been asked
        # yet (PF-01: real articles forced to Unknown).
        def make_render(messages, executed=()):
            news_status = classify_news_source_availability(
                [*messages, *executed])

            def _render(report):
                return render_news_analyst_report(
                    report.model_copy(update={"news_source_status": news_status})
                )

            return news_status, _render

        if single_pass:
            # ``accept`` runs after the loop, over the schema instance plus the
            # full tool history the loop built (the caller's messages and every
            # ToolMessage this runner executed), which is what the forced
            # stance must be derived from. It cannot close over the loop's
            # return value: the loop binds that after ``accept`` runs.
            executed: list = []
            outcome: dict = {}

            def _accept(report):
                news_status, render = make_render(state["messages"], executed)
                outcome["rendered"] = render(report)
                return outcome["rendered"]

            report, _, emitted = finalize_single_pass(
                llm=llm,
                structured_llm=structured_llm,
                prompt=prompt,
                messages=state["messages"],
                tools=tools,
                schema=NewsAnalystReport,
                render=None,
                agent_name="News Analyst",
                run_tools=run_data_tools(tools, state=state),
                state=state,
                accept=_accept,
                executed=executed,
            )
            result_rendered = outcome.get("rendered")
            news_status, _ = make_render(state["messages"], executed)
            if result_rendered is not None and report == result_rendered:
                # The success branch: the renderer already applied the forced
                # status, which is only ever UNAVAILABLE with the full header,
                # so no additional status line is needed.
                return {"messages": emitted, "news_report": report}
            # A prose fallback never passes through the renderer, so the status
            # banner (dead feed) or the authoritative status line (live feed)
            # is applied here from the same tool-derived verdict. Neither reads
            # the model's text.
            guarded = _guard_news_unavailable(report, news_status)
            return {
                "messages": emitted,
                "news_report": _news_available_note(news_status) + guarded,
            }

        # Non-single-pass (RC1) path. The loop's own call is one outbound
        # request; the terminal finalisation inside ``finalize_analyst_report``
        # is another, settled by the schema-bound binding. Both are counted.
        result = instrument_analyst_invoke(chain, state["messages"], speaker="News Analyst")

        report = ""
        if len(result.tool_calls) == 0:
            governed = bool(
                (state.get("run_config") or {}).get("news_tool_governance", {}).get("enabled")
            )
            schema_tool = _schema_tool_name(NewsAnalystReport)
            if governed or any(tc.get("name") == schema_tool for tc in (result.tool_calls or [])):
                from tradingagents.agents.utils.tool_governance import analyst_report

                report = analyst_report(result)
            else:
                news_status, render = make_render(state["messages"])

                report, _ = finalize_analyst_report(
                    llm=llm,
                    structured_llm=structured_llm,
                    messages=prompt.format_prompt(messages=state["messages"]).to_messages() + [result],
                    render=render,
                    agent_name="News Analyst",
                    free_text_block=result.content,
                )
                report = _guard_news_unavailable(report, news_status)
                report = _news_available_note(news_status) + report

        return {
            "messages": [result],
            "news_report": report,
        }

    return news_analyst_node
