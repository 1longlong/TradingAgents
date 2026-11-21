"""Sentiment analyst — multi-source sentiment analysis for a target ticker.

Previously named ``social_media_analyst``. Renamed and redesigned because
the old version had a prompt that demanded social-media analysis but the
only tool available was Yahoo Finance news — which led LLMs to fabricate
Reddit/X/StockTwits content under prompt pressure (verified live).

The redesigned agent pre-fetches three complementary data sources before
the LLM is invoked and injects them into the prompt as structured blocks:

  1. News headlines     — Yahoo Finance (institutional framing)
  2. StockTwits messages — retail-trader posts indexed by cashtag, with
                           user-labeled Bullish/Bearish sentiment tags
  3. Reddit posts        — r/wallstreetbets, r/stocks, r/investing

Each source is trimmed to the analysis window. These text feeds serve recent
items and are not archived as of a past date, so sentiment inputs for a
historical run are not guaranteed to be point-in-time.

The agent does not use tool-calling; the data is in the prompt from
turn 0. Output uses the structured-output pattern (json_schema for
OpenAI/xAI, response_schema for Gemini, tool-use for Anthropic), falling
back to free-text generation for providers that lack native support, so
the sentiment header (band + score + confidence) is deterministic across
runs and providers instead of free-form per-model prose.

The optional prefetch split (``config["sentiment_prefetch"]``, see
:mod:`tradingagents.graph.sentiment_prefetch`) puts the three fetches in their
own graph node, so a checkpoint taken between fetching and generating lets a
failed model call resume without fetching the sources again.

See: https://github.com/TauricResearch/TradingAgents/issues/557
See: https://github.com/TauricResearch/TradingAgents/issues/796
"""

from datetime import datetime, timedelta

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.schemas import SentimentReport, render_sentiment_report
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
    get_news,
)
from tradingagents.agents.utils.structured import (
    NO_EXTERNAL_TOOLS,
    bind_structured,
    invoke_structured_or_freetext,
)
from tradingagents.dataflows.reddit import fetch_reddit_posts
from tradingagents.dataflows.stocktwits import fetch_stocktwits_messages


def _prefetch_module():
    """The prefetch module, imported lazily.

    ``tradingagents.graph`` imports the agents package (graph setup), and this
    agent is imported *by* that package, so a module-level import of the graph
    package here would be circular.
    """
    from tradingagents.graph import sentiment_prefetch

    return sentiment_prefetch


def _seven_days_back(trade_date: str) -> str:
    return (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")


def _analysis_window(state):
    """The ticker, trade date and 7-day start date this analyst analyses."""
    ticker = state["company_of_interest"]
    end_date = state["trade_date"]
    return ticker, end_date, _seven_days_back(end_date)


def _fetch_sources(
    ticker: str, start_date: str, end_date: str, fetch_parameters
) -> dict[str, str]:
    """Fetch the three sentiment sources exactly once, for one window.

    ``fetch_parameters`` (from the snapshot this call runs under) carries the
    limits the fetches use, so the saved identity names the news article count
    and the vendor chain the request will actually receive. The news tool's
    vendor reads ``news_article_limit`` from ``get_config()`` at call time;
    inside :func:`fetch_snapshot` that read returns the snapshot's value.

    StockTwits and Reddit degrade on any transport or parse failure and return
    a placeholder string; news does NOT — a rejected credential, a refused
    request or an internal error still propagates through route_to_vendor, so
    no source is treated as "no data" when it was never observed.
    """
    prefetch = _prefetch_module()
    if prefetch.news_article_limit_now() != fetch_parameters.news_article_limit:
        raise prefetch.SentimentInputError(
            "the news article limit changed between snapshot and fetch "
            f"({fetch_parameters.news_article_limit!r} -> "
            f"{prefetch.news_article_limit_now()!r}); "
            "refusing to label the fetched text with a stale limit"
        )
    return {
        "news": get_news.func(ticker, start_date, end_date, trade_date=end_date),
        # Pass the analysis window so a historical run trims social posts to it
        # instead of leaking today's chatter into a backtest (#1220).
        "stocktwits": fetch_stocktwits_messages(
            ticker,
            limit=fetch_parameters.stocktwits_limit,
            start_date=start_date,
            end_date=end_date,
        ),
        "reddit": fetch_reddit_posts(ticker, start_date=start_date, end_date=end_date),
    }


def create_sentiment_prefetch_node():
    """Create the ``Sentiment Prefetch`` graph node (prefetch-split path).

    Makes the same three calls as the single-node path and returns them, with
    their identity, under ``sentiment_inputs``. Nothing else in the state is
    written, so the checkpoint after this node is what lets a failed model call
    resume without fetching again. A fetch error propagates unchanged: nothing
    is saved, and a resume fetches again.
    """

    def sentiment_prefetch_node(state):
        prefetch = _prefetch_module()
        ticker, end_date, start_date = _analysis_window(state)
        # One context-local snapshot of the run's config is used for the
        # request parameters, the vendor chain the fetch routes through and
        # the identity the result is saved under. Nothing global is written,
        # so a concurrent set_config cannot change this request and is not
        # overwritten when the block exits (normally, on an error or on
        # cancellation). The blocks are fetched and saved inside the block so
        # the label is read from the same snapshot that served the request.
        with prefetch.fetch_snapshot(_run_config(state)) as snapshot:
            blocks = _fetch_sources(
                ticker, start_date, end_date, snapshot.parameters
            )
            # Refuse if the context's snapshot is no longer the one that
            # fetched: the label is never corrected from a later read.
            prefetch.refuse_changed_fetch_parameters(
                snapshot, prefetch.current_fetch_parameters()
            )
            update = {
                prefetch.STATE_KEY: prefetch.save_inputs(
                    state,
                    ticker=ticker,
                    start_date=start_date,
                    end_date=end_date,
                    snapshot=snapshot,
                    news_block=blocks["news"],
                    stocktwits_block=blocks["stocktwits"],
                    reddit_block=blocks["reddit"],
                )
            }
        return update

    return sentiment_prefetch_node


def _run_config(state):
    """The config this run was started with (``run_config``), else the live one."""
    config = state.get("run_config")
    if isinstance(config, dict) and config:
        return config
    from tradingagents.dataflows.config import get_config

    return get_config()


def create_sentiment_analyst(llm, prefetch_split: bool = False):
    """Create a sentiment analyst node for the trading graph.

    Pre-fetches news + StockTwits + Reddit data, injects them into the
    prompt as structured blocks, and produces a deterministic sentiment
    report via structured output (with a free-text fallback for providers
    that do not support it).

    ``prefetch_split`` selects the two-node path (default off, which is the
    original one-node path): ``True`` makes this node consume only the three
    blocks already saved under ``sentiment_inputs`` by
    :func:`create_sentiment_prefetch_node`, never fetching sources itself.
    """
    structured_llm = bind_structured(llm, SentimentReport, "Sentiment Analyst")

    def sentiment_analyst_node(state):
        ticker, end_date, start_date = _analysis_window(state)
        instrument_context = get_instrument_context_from_state(state)

        if prefetch_split:
            # Saved blocks only. A missing/partial/mismatched input raises
            # before the model is called; it never re-fetches, and an
            # "<... unavailable ...>" placeholder is used exactly as saved.
            # The expected values are read inside the same context-local
            # snapshot of the run config the prefetch used, so this run's
            # config -- not the global one -- decides whether the saved input
            # still matches. No fetch happens here.
            prefetch = _prefetch_module()
            with prefetch.fetch_snapshot(_run_config(state)) as snapshot:
                blocks = prefetch.load_inputs(
                    state,
                    ticker=ticker,
                    start_date=start_date,
                    end_date=end_date,
                    snapshot=snapshot,
                )
        else:
            # Pre-fetch is not persisted on this path: a re-run of this node
            # fetches all three again. One context-local snapshot serves both
            # the fetch and the label, like the prefetch node.
            prefetch = _prefetch_module()
            with prefetch.fetch_snapshot(_run_config(state)) as snapshot:
                blocks = _fetch_sources(
                    ticker, start_date, end_date, snapshot.parameters
                )

        system_message = _build_system_message(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            news_block=blocks["news"],
            stocktwits_block=blocks["stocktwits"],
            reddit_block=blocks["reddit"],
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Report what your tools support; another agent decides the trade."
                    # No tool-calling here: the data is pre-fetched into the
                    # prompt, so tool-range wording would only invite a
                    # hallucinated tool call (#1130).
                    " Today's date is {current_date}; treat it as 'now' for all analysis. {instrument_context}"
                    " " + NO_EXTERNAL_TOOLS +
                    "\n{system_message}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(current_date=end_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        # Format the template into a concrete message list so the structured
        # and free-text paths receive the same input. No bind_tools — the
        # data is already in the prompt.
        formatted_messages = prompt.format_messages(messages=state["messages"])

        report_text = invoke_structured_or_freetext(
            structured_llm,
            llm,
            formatted_messages,
            render_sentiment_report,
            "Sentiment Analyst",
            schema=SentimentReport,
        )

        return {
            "messages": [AIMessage(content=report_text)],
            "sentiment_report": report_text,
        }

    return sentiment_analyst_node


def _build_system_message(
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    news_block: str,
    stocktwits_block: str,
    reddit_block: str,
) -> str:
    """Assemble the sentiment-analyst system message with structured data blocks."""
    return f"""You are a financial market sentiment analyst. Your task is to produce a comprehensive sentiment report for {ticker} covering the period from {start_date} to {end_date}, drawing on three complementary data sources that have already been collected for you.

## Data sources (pre-fetched, in this prompt)

### News headlines — Yahoo Finance, past 7 days
Institutional framing. Fact-driven, slower-moving signal.

<start_of_news>
{news_block}
<end_of_news>

### StockTwits messages — retail-trader social platform indexed by cashtag
Fast-moving signal. Each message carries a user-labeled sentiment tag (Bullish / Bearish / no-label) plus the message body.

<start_of_stocktwits>
{stocktwits_block}
<end_of_stocktwits>

### Reddit posts — r/wallstreetbets, r/stocks, r/investing (past 7 days)
Community discussion, without vote or comment counts. Subreddit character matters (r/wallstreetbets is often contrarian/exuberant; r/stocks more measured; r/investing longer-term).

<start_of_reddit>
{reddit_block}
<end_of_reddit>

## How to analyze this data (best practices)

1. **Read the StockTwits Bullish/Bearish ratio as a leading retail-sentiment signal.** A 70/30 bullish/bearish split is moderately bullish; ≥90/10 may indicate over-extension and contrarian risk; 50/50 is uncertainty. Sample size matters — base rates on the actual message count, not percentages alone.

2. **Look for cross-source divergences.** If news framing is bearish but StockTwits is overwhelmingly bullish, that mismatch is itself a signal — it can mean retail is leaning into a thesis the news flow hasn't caught up to (or vice versa, that retail is chasing while institutions are cautious).

3. **Read Reddit posts for substance.** The feed carries no vote or comment counts, so judge a post by its body excerpt, not its title alone, and do not infer engagement.

4. **Distinguish opinion from event.** A news headline ("Nvidia announces $500M Corning deal") is an event; a StockTwits post ("buying NVDA, this is going to moon") is opinion. Both are inputs but should be weighted differently in your conclusions.

5. **Identify recurring narrative themes.** What topic keeps coming up across sources? That's the dominant narrative driving current sentiment.

6. **Be honest about data limits.** If StockTwits returned only a handful of messages, or one or more sources returned an "<unavailable>" placeholder, the sentiment read is less robust — flag this explicitly in the `confidence` field and the narrative. If the sources are silent on a given subreddit, say so.

7. **Identify catalysts and risks** that emerge across sources — news of upcoming earnings, product launches, competitive threats, macro headlines, etc.

8. **Past sentiment is not predictive.** Frame your conclusions as signal for the trader to weigh alongside fundamentals and technicals, not as a price call.

## Output fields

Fill the following fields:

- **overall_band**: Exactly one of Bullish / Mildly Bullish / Neutral / Mixed / Mildly Bearish / Bearish. Use Mixed when sources point in clearly different directions; Neutral only when all sources are genuinely silent.
- **overall_score**: A number from 0 (maximally bearish) to 10 (maximally bullish); 5 is neutral. Keep it consistent with overall_band.
- **confidence**: low / medium / high, based on data quality and sample size.
- **narrative**: Full source-by-source breakdown, divergences, dominant narrative themes, catalysts and risks, and a markdown summary table of key sentiment signals (direction, source, supporting evidence).

{get_language_instruction()}"""


# ---------------------------------------------------------------------------
# Backwards-compatibility shim
# ---------------------------------------------------------------------------
def create_social_media_analyst(llm):
    """Deprecated alias for :func:`create_sentiment_analyst`.

    Kept so existing code that imports ``create_social_media_analyst``
    continues to work.

    .. deprecated::
        Import :func:`create_sentiment_analyst` directly instead.
    """
    import warnings
    warnings.warn(
        "create_social_media_analyst is deprecated and will be removed in a "
        "future version. Use create_sentiment_analyst instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return create_sentiment_analyst(llm)
