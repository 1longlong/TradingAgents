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

# ADR-012-error-handling-merge-integration.md: contract typing/security, NFR-BC-001, INV-1.
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, cast

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import StructuredTool

from tradingagents.agents.schemas import (
    SentimentBand,
    SentimentDataStatus,
    SentimentReport,
    classify_sentiment_sources,
    render_sentiment_report,
)
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
from tradingagents.dataflows.errors import (
    NoMarketDataError,
    VendorRateLimitError,
    VendorTimeoutError,
    VendorUnavailableError,
)
from tradingagents.dataflows.reddit import fetch_reddit_posts
from tradingagents.dataflows.stocktwits import fetch_stocktwits_messages
from tradingagents.observability import record_prefetch_call

logger = logging.getLogger(__name__)


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
    news_function = cast(StructuredTool, get_news).func
    assert news_function is not None  # The registered get_news tool is synchronous.
    return {
        "news": news_function(ticker, start_date, end_date, trade_date=end_date),
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


def _render_without_measurement(report: SentimentReport) -> str:
    """Render a report whose sources returned nothing usable.

    The model must still describe what each source said, but it must not be
    allowed to emit a sentiment reading: any band and score it supplied are
    discarded and replaced with an explicit Unknown / not-scored header. This
    is the enforcement point, not merely a prompt instruction, because the
    placeholder header reaches six downstream agents first.
    """
    forced = report.model_copy(
        update={
            "overall_band": SentimentBand.UNKNOWN,
            "overall_score": None,
            "data_status": SentimentDataStatus.UNAVAILABLE,
        }
    )
    rendered = render_sentiment_report(forced)
    return (
        rendered
        + "\n\n> No usable sentiment source for this window. The band is"
        " **Unknown**, not Neutral: absence of data is not evidence of a"
        " balanced market."
    )


#: Conditions the legacy single-node path may degrade to a sentinel. A typed
#: throttle/timeout/unavailability/absence is "could not answer", not "no news";
#: an untyped ``RuntimeError`` is the historical prefetch-failure shape the
#: legacy contract documents. Fatal/auth/rejected/unknown-internal errors are
#: NOT in this set and propagate to the caller (Release-first policy).
_RECOVERABLE_PREFETCH_ERRORS = (
    VendorRateLimitError,
    VendorTimeoutError,
    VendorUnavailableError,
    NoMarketDataError,
    RuntimeError,
)


def _prefetch_or_degrade(label: str, fetch) -> str:
    """Run a prefetch, degrading only the documented recoverable failures."""
    try:
        return fetch()
    except _RECOVERABLE_PREFETCH_ERRORS as exc:
        logger.warning("Sentiment %s prefetch failed (%s); degrading", label, exc)
        return (
            f"DATA_UNAVAILABLE: the {label} prefetch raised "
            f"{type(exc).__name__}. Treat this source as unavailable; do not "
            "infer that the instrument is quiet in any direction."
        )


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
            # Personal single-node path: fetch all three, degrading an untyped
            # failure to a visible sentinel so a prefetch cannot abort the node.
            news_block = _prefetch_or_degrade(
                "news",
                lambda: record_prefetch_call(
                    "news", cast(Callable[..., Any], getattr(get_news, "func", get_news)), ticker, start_date, end_date,
                    trade_date=end_date,
                ),
            )
            stocktwits_block = record_prefetch_call(
                "stocktwits", fetch_stocktwits_messages,
                ticker, limit=30, start_date=start_date, end_date=end_date,
            )
            reddit_block = record_prefetch_call(
                "reddit", fetch_reddit_posts,
                ticker, start_date=start_date, end_date=end_date,
            )
            blocks = {
                "news": news_block,
                "stocktwits": stocktwits_block,
                "reddit": reddit_block,
            }

        news_block = blocks["news"]
        stocktwits_block = blocks["stocktwits"]
        reddit_block = blocks["reddit"]

        system_message = _build_system_message(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            news_block=news_block,
            stocktwits_block=stocktwits_block,
            reddit_block=reddit_block,
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

        # Availability is decided here, from the strings actually handed to the
        # model, so an outage cannot be read as a neutral reading. Without this
        # every run whose three sources were placeholders still produced
        # "Neutral (Score: 5.0/10)" — a measurement nobody made.
        data_status = classify_sentiment_sources(
            news_block, stocktwits_block, reddit_block
        )

        def render(report: SentimentReport) -> str:
            # The header's data status must be the one Python just computed from
            # the actual source strings, not the model's own field: that field
            # defaults to AVAILABLE, so rendering it verbatim let a degraded or
            # empty news prefetch still print "Data status: AVAILABLE". Stamp the
            # computed verdict onto a copy so the deterministic classification is
            # the single source of truth on both the structured and prose paths.
            same_status = getattr(report, "data_status", None) is data_status
            if not same_status:
                report = report.model_copy(update={"data_status": data_status})
            if data_status in (
                SentimentDataStatus.AVAILABLE,
                SentimentDataStatus.PARTIAL,
            ):
                return render_sentiment_report(report)
            return _render_without_measurement(report)

        report_text = invoke_structured_or_freetext(
            structured_llm,
            llm,
            formatted_messages,
            render,
            "Sentiment Analyst",
            schema=SentimentReport,
        )
        if data_status is SentimentDataStatus.UNAVAILABLE and not report_text.startswith(
            "**Overall Sentiment:** **Unknown**"
        ):
            # Free-text fallback (provider without structured output, or a
            # structured miss) bypasses ``_render_without_measurement``, so the
            # model's own header is still in the text. Prepend the authoritative
            # one rather than trusting prose about a measurement never taken.
            report_text = (
                "**Overall Sentiment:** **Unknown** (Score: not scored (no data))\n"
                "**Confidence:** Low\n"
                f"**Data status:** {SentimentDataStatus.UNAVAILABLE.value}"
                "\n\n> No usable sentiment source for this window. The band is"
                " **Unknown**, not Neutral: absence of data is not evidence of a"
                " balanced market.\n\n" + report_text
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

6. **Be honest about data limits, and never score an absence.** If StockTwits returned only a handful of messages, or one or more sources returned an "<unavailable>" / "coverage starts" placeholder, the sentiment read is less robust — flag this explicitly in the `confidence` field and the narrative. If the sources are silent on a given subreddit, say so. **A placeholder is not a neutral reading.** A source that did not reach the requested window tells you nothing about what people thought on those dates; "no data" and "balanced opinion" are different findings and must never be reported as the same thing.

7. **Identify catalysts and risks** that emerge across sources — news of upcoming earnings, product launches, competitive threats, macro headlines, etc.

8. **Past sentiment is not predictive.** Frame your conclusions as signal for the trader to weigh alongside fundamentals and technicals, not as a price call.

## Output fields

Fill the following fields:

- **overall_band**: Exactly one of Bullish / Mildly Bullish / Neutral / Mixed / Mildly Bearish / Bearish / **Unknown**. Use Mixed when sources point in clearly different directions. Use Neutral only when the sources you *did* receive contain real messages that genuinely balance out — silence from a source is not neutral evidence. Use **Unknown** when no source returned usable data for the window: nothing was measured, so there is no direction to report.
- **overall_score**: A number from 0 (maximally bearish) to 10 (maximally bullish); 5 is neutral. Keep it consistent with overall_band. **Set it to null when overall_band is Unknown** — a score implies a measurement that did not happen.
- **data_status**: AVAILABLE when all three sources returned usable data, PARTIAL when some did, UNAVAILABLE when none did, ERROR when a source failed outright rather than merely not covering the window.
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
