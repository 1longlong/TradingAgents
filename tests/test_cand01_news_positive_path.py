"""CAND-01 PF-01 — the news analyst must classify its news source from the
tool results it actually executed.

The defect (PF-01, ``20261114_cand01_final_preflight_live_0/PREFLIGHT_AUDIT.md``):
``create_news_analyst`` classified the company-news feed **before** the
single-pass tool loop ran, from the messages the node received. In the graph
the analyst node is entered *before* any ``get_news`` call, so the classifier
always saw an empty tool history and forced ``Stance: Unknown`` plus
"News Source Unavailable" onto reports built from real articles. RC1 did not
have the bug because its ``ToolNode`` round-trips put the ``ToolMessage`` into
``state["messages"]`` before the finalising visit.

Every test here drives the real objects:

* the real ``get_news`` / ``get_global_news`` tools from
  ``tradingagents.agents.utils.news_data_tools`` (their vendor boundary is
  patched, so the payloads are the real vendor renderers' output shapes);
* the real ``create_news_analyst`` node, through a **compiled** LangGraph
  (analyst -> conditional -> ``ToolNode`` -> analyst) using the production
  ``ConditionalLogic.should_continue_news`` rails, so the tool messages travel
  the same path the live pipeline uses.

Only the LLM and the network are fakes: no provider usage.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from unittest.mock import patch

import tradingagents.dataflows.finnhub_news as fhnews
from tradingagents.agents.analysts.news_analyst import (
    NEWS_UNAVAILABLE_PREFIX,
    create_news_analyst,
)

# The provenance-structured banner is named separately from the legacy alias so
# this file can also be run against earlier commits to prove the tests are not
# vacuous; those commits only export the prefix.
NEWS_UNAVAILABLE_BANNER = getattr(
    __import__("tradingagents.agents.analysts.news_analyst",
               fromlist=["NEWS_UNAVAILABLE_BANNER"]),
    "NEWS_UNAVAILABLE_BANNER", NEWS_UNAVAILABLE_PREFIX)

# The authoritative live-feed status line. Older commits have no such concept,
# so fall back to a value none of their reports can start with; the tests that
# rely on it are expected to fail there, which is what proves them non-vacuous.
NEWS_SOURCE_AVAILABLE_NOTE = getattr(
    __import__("tradingagents.agents.analysts.news_analyst",
               fromlist=["_news_available_note"]),
    "_news_available_note",
    lambda status: "<no-live-status-line>")(
        __import__("tradingagents.agents.schemas",
                   fromlist=["NewsSourceStatus"]).NewsSourceStatus.AVAILABLE)
from tradingagents.agents.schemas import (
    AnalystStance,
    NewsSourceStatus,
    classify_news_source_availability,
)
from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.agents.utils.news_data_tools import get_global_news, get_news
from tradingagents.graph.conditional_logic import ConditionalLogic

TRADE_DATE = "2026-09-23"
WINDOW = ("2026-09-16", "2026-09-23")

STORIES = [
    ("2026-09-21", "Nvidia unveils next-gen AI chip roadmap", "Reuters", "Reuters"),
    ("2026-09-20", "Nvidia shares close at record high", "Bloomberg", "Bloomberg"),
]


def _epoch(date_str):
    return int(
        datetime.strptime(date_str, "%Y-%m-%d")
        .replace(tzinfo=timezone.utc)
        .timestamp()
    )


def finnhub_articles(stories):
    """A real Finnhub ``company-news`` payload (list-of-records shape).

    Finnhub returns ``headline``/``summary``/``source``/``datetime``/``url``/
    ``related`` per record, with ``datetime`` as a UNIX epoch. The window is
    expressed as a date range by the caller, so the fixture only has to be a
    faithful vendor payload.
    """
    return [
        {
            "category": "company",
            "datetime": _epoch(day),
            "headline": title,
            "id": 1000 + i,
            "image": "",
            "related": ticker,
            "source": publisher,
            "summary": f"{title} — full report.",
            "url": f"https://news.example.invalid/{i}",
        }
        for i, (day, title, publisher, _src) in enumerate(stories)
        for ticker in (f"story-{i}",)
    ]


def finnhub_news_text(ticker, stories, start=WINDOW[0], end=WINDOW[1]):
    """The exact string ``get_news_finnhub`` renders for ``stories``.

    Rendering through the real vendor function (with only ``_request`` patched)
    keeps the fixture honest: if the vendor output shape changes, this fixture
    changes with it instead of drifting into a made-up format. The project is
    Finnhub-only for company news, so this replaces the retired yfinance
    fixture CAND-01 was originally written against.
    """
    import json

    payload = json.dumps(finnhub_articles(stories))

    # Both the credential and the transport are patched: the fixture renders
    # through the real vendor function, but the test never needs a key and never
    # touches the network.
    with patch.object(fhnews, "get_api_key", lambda: "test-key"), \
            patch.object(fhnews, "_request", lambda url: (200, payload, "")):
        return fhnews.get_news_finnhub(ticker, start, end)


ALPHA_VANTAGE_FEED = (
    '{"items":"","sentiment_score_definition":"x>=0.35: Bullish",'
    '"relevance_score_definition":"0<x<=1","feed":['
    '{"title":"JPMorgan lifts 2026 net interest income guidance",'
    '"url":"https://example.invalid/jpm-1","time_published":"20260922T141500",'
    '"authors":["Jane Doe"],"summary":"The bank raised its full-year NII outlook.",'
    '"source":"Reuters","overall_sentiment_label":"Somewhat-Bullish",'
    '"ticker_sentiment":[{"ticker":"JPM","relevance_score":"0.9",'
    '"ticker_sentiment_label":"Bullish"}]},'
    '{"title":"JPMorgan to expand private-credit book",'
    '"url":"https://example.invalid/jpm-2","time_published":"20260918T100000",'
    '"authors":["John Roe"],"summary":"Management outlined growth in private credit.",'
    '"source":"Bloomberg","overall_sentiment_label":"Neutral",'
    '"ticker_sentiment":[{"ticker":"JPM","relevance_score":"0.8",'
    '"ticker_sentiment_label":"Neutral"}]}]}'
)
GLOBAL_NEWS = (
    "## Global Market News, from 2026-09-18 to 2026-09-23:\n\n"
    "### Fed officials signal slower easing (source: Reuters)\n"
    "Policymakers flagged a slower path as inflation cools.\n"
)
EMPTY_WINDOW = (
    "No news found for XOM between 2026-09-16 and 2026-09-23"
)
TIMEOUT_TEXT = (
    "DATA_UNAVAILABLE: no configured vendor could serve get_news right now "
    "(get_news transient failure: timed out after 30s). This says nothing about "
    "the instrument; report the data as unavailable and do not estimate or "
    "fabricate values."
)
AUTH_TEXT = (
    "NEWS_STATUS=AUTH_MISSING: Alpha Vantage could not answer for JPM "
    "(2026-09-16..2026-09-23) — no credential is configured for this vendor. "
    "This says nothing about the instrument; report the news as unavailable "
    "rather than as neutral."
)

BULLISH_ARGS = {
    "stance": "Bullish",
    "key_evidence": [
        {
            "claim": "Nvidia unveiled its next-gen AI chip roadmap.",
            "evidence": "Nvidia unveils next-gen AI chip roadmap (Reuters, 2026-09-21)",
            "source": "get_news: Reuters",
        }
    ],
    "catalysts": [
        {"date": "2026-09-21", "event": "AI chip roadmap unveiled",
         "relevance": "supports data-centre demand"},
    ],
    "risks": ["Execution slip on the roadmap."],
    "interpretation": "News flow supports the current bid.",
}
BEARISH_ARGS = {
    "stance": "Bearish",
    "key_evidence": [
        {"claim": "The roadmap slipped a quarter.",
         "evidence": "Roadmap delayed (Reuters, 2026-09-21)", "source": "get_news"},
    ],
    "catalysts": [{"date": "2026-09-21", "event": "Roadmap delayed",
                   "relevance": "negative"}],
    "risks": ["Share loss."],
    "interpretation": "News flow is negative.",
}


def _news_call(call_id="tc-news", ticker="NVDA", start=WINDOW[0], end=WINDOW[1]):
    return {"name": "get_news", "type": "tool_call", "id": call_id,
            "args": {"ticker": ticker, "start_date": start, "end_date": end}}


def _global_call(call_id="tc-global"):
    return {"name": "get_global_news", "type": "tool_call", "id": call_id,
            "args": {"curr_date": TRADE_DATE, "look_back_days": 5, "limit": 10}}


def _schema_call(args=None, call_id="schema-1"):
    return {"name": "NewsAnalystReport", "type": "tool_call", "id": call_id,
            "args": dict(args or BULLISH_ARGS)}


class ScriptedLLM(BaseChatModel):
    """Replays one scripted ``AIMessage`` per call, in order.

    The last scripted message repeats, so a runaway loop is still bounded by
    ``SINGLE_PASS_MAX_ROUNDS`` and the graph's recursion limit rather than
    hanging the test.
    """

    script: list = []
    cursor: int = 0
    seen_binds: list = []

    @property
    def _llm_type(self):
        return "scripted-news"

    def bind_tools(self, tools, **kwargs):
        model = self
        names = [getattr(t, "name", None) for t in tools]

        def _gen(messages, config=None):
            model.seen_binds.append(names)
            step = model.script[min(model.cursor, len(model.script) - 1)]
            model.cursor += 1
            return step(messages) if callable(step) else step

        return RunnableLambda(_gen)

    def with_structured_output(self, schema, **kwargs):
        # Only exists so the factory can build the two-call path; no test here
        # relies on it succeeding.
        return RunnableLambda(lambda _m, config=None: None)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(
            message=AIMessage(content="prose fallback"))])


class _RecordingVendor:
    """Patches ``route_to_vendor`` for ``get_news`` and counts executions."""

    def __init__(self, test, news_text=EMPTY_WINDOW, global_text=GLOBAL_NEWS,
                 raise_news=None):
        self.test = test
        self.news_text = news_text
        self.global_text = global_text
        self.raise_news = raise_news
        self.news_calls = []
        self.global_calls = []

    def __call__(self, method, *args, **kwargs):
        if method == "get_news":
            self.news_calls.append(args)
            if self.raise_news is not None:
                raise self.raise_news
            return self.news_text
        if method == "get_global_news":
            self.global_calls.append(args)
            return self.global_text
        raise AssertionError(f"unexpected vendor method {method!r}")

    def __enter__(self):
        self._patch = patch(
            "tradingagents.agents.utils.news_data_tools.route_to_vendor", self)
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()
        return False


class NewsGraphHarness:
    """The production analyst wiring, compiled and run for real.

    ``news node -> should_continue_news -> ToolNode -> news node -> Msg Clear``
    is the same shape ``graph/setup.py`` builds, and the conditional edges are
    the production ``ConditionalLogic`` methods, so a write-back bug shows up as
    a re-entered analyst (or a recursion error) exactly as it would live.
    """

    def __init__(self, test, llm, single_pass):
        self.test = test
        self.llm = llm
        self.single_pass = single_pass
        self.news_node_visits = 0

    def _wrap(self, node):
        def _inner(state):
            self.news_node_visits += 1
            return node(state)
        return _inner

    def build(self):
        node = self._wrap(create_news_analyst(
            self.llm, batch_macro=False, structured=True,
            single_pass=self.single_pass))
        logic = ConditionalLogic()
        g = StateGraph(AgentState)
        g.add_node("News Analyst", node)
        g.add_node("tools_news", ToolNode(
            [get_news, get_global_news], messages_key="messages"))
        g.add_node("Msg Clear News",
                   lambda s: {"messages": [HumanMessage(content="Proceed.")]})
        g.add_edge(START, "News Analyst")
        g.add_conditional_edges("News Analyst", logic.should_continue_news,
                                ["tools_news", "Msg Clear News"])
        g.add_edge("tools_news", "News Analyst")
        g.add_edge("Msg Clear News", END)
        return g.compile()

    def run(self):
        graph = self.build()
        out = graph.invoke(
            {
                "messages": [HumanMessage(content="Analyse NVDA news")],
                "trade_date": TRADE_DATE,
                "company_of_interest": "NVDA",
                "asset_type": "stock",
            },
            config={"recursion_limit": 25},
        )
        return out


def _make_llm(script):
    llm = ScriptedLLM(script=list(script), cursor=0, seen_binds=[])
    return llm


def _calls_of(message):
    """Tool calls declared by an assistant turn (ToolMessages have none)."""
    if not isinstance(message, AIMessage):
        return []
    return list(message.tool_calls or [])


def _tool_messages(out):
    return [m for m in out["messages"] if isinstance(m, ToolMessage)]


def _assert_single_pass_finalised(test, out, expected_text_marker=None):
    """Exactly one terminal answer, every tool call matched, no replay."""
    messages = out["messages"]
    pending = set()
    for m in messages:
        for call in _calls_of(m):
            pending.add(call["id"])
        if isinstance(m, ToolMessage):
            test.assertIn(m.tool_call_id, pending,
                          f"ToolMessage {m.tool_call_id} has no matching call")
            pending.discard(m.tool_call_id)
    test.assertEqual(pending, set(), f"dangling tool calls: {pending}")
    schema_calls = [
        c for m in messages for c in _calls_of(m)
        if c.get("name") == "NewsAnalystReport"
    ]
    test.assertEqual(schema_calls, [],
                     "the schema call must not be replayed in shared state")
    if expected_text_marker is not None:
        test.assertIn(expected_text_marker, out["news_report"])


# --------------------------------------------------------------------------
# Positive path (P1-P3)
# --------------------------------------------------------------------------
class RealCompanyNewsTest(unittest.TestCase):
    """P1: one real company article inside the tool loop."""

    def setUp(self):
        self.llm = _make_llm([
            AIMessage(content="", tool_calls=[_news_call()]),
            AIMessage(content="", tool_calls=[_schema_call()]),
        ])
        self.vendor = _RecordingVendor(
            self, news_text=finnhub_news_text("NVDA", STORIES))
        with self.vendor:
            self.out = NewsGraphHarness(self, self.llm, single_pass=True).run()

    def test_status_is_available(self):
        tool_msgs = _tool_messages(self.out)
        self.assertEqual(len(tool_msgs), 1)
        self.assertEqual(tool_msgs[0].name, "get_news")
        self.assertIn("### Nvidia unveils", tool_msgs[0].content)
        self.assertIs(
            classify_news_source_availability(self.out["messages"]),
            NewsSourceStatus.AVAILABLE)

    def test_model_stance_is_preserved(self):
        report = self.out["news_report"]
        self.assertIn("**Stance:** Bullish", report)
        self.assertNotIn("Unknown", report)

    def test_no_false_unavailability_text(self):
        report = self.out["news_report"]
        self.assertNotIn("DATA_UNAVAILABLE", report)
        self.assertNotIn("News source unavailable", report)
        self.assertNotIn("no company-specific news was retrieved", report)
        self.assertFalse(report.startswith(NEWS_UNAVAILABLE_PREFIX))

    def test_report_carries_the_real_evidence(self):
        report = self.out["news_report"]
        self.assertIn("Nvidia unveils next-gen AI chip roadmap", report)
        self.assertIn("AI chip roadmap unveiled", report)

    def test_the_tool_ran_once(self):
        self.assertEqual(len(self.vendor.news_calls), 1,
                         f"get_news executed {len(self.vendor.news_calls)}x")
        self.assertEqual(self.llm.cursor, 2, "exactly two model calls expected")

    def test_graph_history_is_legal(self):
        _assert_single_pass_finalised(self, self.out,
                                      "Nvidia unveils next-gen AI chip roadmap")


class MultipleRealArticlesTest(unittest.TestCase):
    """P2: several real articles, titles/dates/sources preserved."""

    def test_status_is_available_and_evidence_survives(self):
        llm = _make_llm([
            AIMessage(content="", tool_calls=[_news_call()]),
            AIMessage(content="", tool_calls=[_schema_call()]),
        ])
        vendor = _RecordingVendor(
            self, news_text=finnhub_news_text("NVDA", STORIES))
        with vendor:
            out = NewsGraphHarness(self, llm, single_pass=True).run()
        tool_msg = _tool_messages(out)[0]
        for _day, title, publisher, _src in STORIES:
            self.assertIn(f"### {title} (source: {publisher})", tool_msg.content)
        self.assertIn("2026-09-16 to 2026-09-23", tool_msg.content)
        self.assertNotIn("News source unavailable", out["news_report"])


class VendorShapeCompatibilityTest(unittest.TestCase):
    """P3: the real Alpha Vantage and Finnhub response shapes both classify."""

    def _run_with(self, text, args):
        llm = _make_llm([
            AIMessage(content="", tool_calls=[_news_call()]),
            AIMessage(content="", tool_calls=[_schema_call(args)]),
        ])
        vendor = _RecordingVendor(self, news_text=text)
        with vendor:
            return NewsGraphHarness(self, llm, single_pass=True).run()

    def test_alpha_vantage_feed_is_available(self):
        out = self._run_with(ALPHA_VANTAGE_FEED, BULLISH_ARGS)
        self.assertIs(
            classify_news_source_availability(out["messages"]),
            NewsSourceStatus.AVAILABLE)
        self.assertIn(
            '"feed":[{"title":"JPMorgan lifts 2026 net interest income guidance"',
            _tool_messages(out)[0].content)
        self.assertNotIn("News source unavailable", out["news_report"])

    def test_finnhub_markdown_is_available(self):
        out = self._run_with(finnhub_news_text("NVDA", STORIES), BULLISH_ARGS)
        self.assertIs(
            classify_news_source_availability(out["messages"]),
            NewsSourceStatus.AVAILABLE)
        self.assertNotIn("News source unavailable", out["news_report"])

    def test_a_bearish_reading_of_the_same_articles_is_not_overridden(self):
        out = self._run_with(finnhub_news_text("NVDA", STORIES), BEARISH_ARGS)
        self.assertIn("**Stance:** Bearish", out["news_report"])


# --------------------------------------------------------------------------
# Negative path (N1-N5)
# --------------------------------------------------------------------------
class NewsFailurePathTest(unittest.TestCase):
    """N1-N5: absent or broken news keeps the authoritative Unknown."""

    def _run(self, text, *, raise_news=None, with_global=False, args=None):
        script = [AIMessage(content="", tool_calls=[_news_call()])]
        if with_global:
            script.append(AIMessage(content="", tool_calls=[_global_call()]))
        script.append(AIMessage(content="", tool_calls=[_schema_call(args)]))
        llm = _make_llm(script)
        vendor = _RecordingVendor(self, news_text=text,
                                  raise_news=raise_news)
        with vendor:
            out = NewsGraphHarness(self, llm, single_pass=True).run()
        return out, vendor

    def _assert_unknown(self, out):
        report = out["news_report"]
        self.assertTrue(report.startswith(NEWS_UNAVAILABLE_PREFIX), report[:200])
        self.assertIn("**Stance:** Unknown", report)
        self.assertNotIn("**Stance:** Bullish", report)
        self.assertIs(
            classify_news_source_availability(out["messages"]),
            NewsSourceStatus.UNAVAILABLE)

    def test_n1_timeout_is_unknown(self):
        out, _ = self._run(TIMEOUT_TEXT)
        self._assert_unknown(out)

    def test_n1_b_raised_vendor_timeout_is_unknown(self):
        out, _ = self._run("", raise_news=TimeoutError("timed out after 30s"))
        self._assert_unknown(out)

    def test_n2_auth_missing_keeps_the_taxonomy_token(self):
        out, _ = self._run(AUTH_TEXT)
        self._assert_unknown(out)
        message = _tool_messages(out)[0].content
        self.assertTrue(message.startswith("NEWS_STATUS=AUTH_MISSING"), message)

    def test_n3_empty_article_list_is_not_available(self):
        empty = finnhub_news_text("NVDA", [])  # "No news found for NVDA ..."
        out, _ = self._run(empty)
        self._assert_unknown(out)

    def test_n4_placeholder_is_not_available(self):
        for placeholder in ("", "   ", "No news found", "N/A"):
            with self.subTest(placeholder=placeholder):
                out, _ = self._run(placeholder)
                self._assert_unknown(out)

    def test_n5_global_news_cannot_stand_in_for_company_news(self):
        out, vendor = self._run(EMPTY_WINDOW, with_global=True)
        self.assertEqual(len(vendor.global_calls), 1)
        self.assertIn("Fed officials signal slower easing",
                      _tool_messages(out)[1].content)
        # Global news arrived, company news did not: still Unknown.
        self._assert_unknown(out)

    def test_n6_broken_tool_status_still_closes_the_graph(self):
        # A throwing tool becomes a status="error" ToolMessage, and the model
        # still finalises: the graph must not re-run the call.
        out, _ = self._run("", raise_news=RuntimeError("boom"))
        self._assert_unknown(out)
        self.assertEqual(_tool_messages(out)[0].status, "error")


# --------------------------------------------------------------------------
# Graph integrity (G1-G6)
# --------------------------------------------------------------------------
class GraphHistoryIntegrityTest(unittest.TestCase):
    def _run(self, script, text=None, ticker="NVDA"):
        llm = _make_llm(script)
        vendor = _RecordingVendor(
            self, news_text=text or finnhub_news_text(ticker, STORIES))
        with vendor:
            out = NewsGraphHarness(self, llm, single_pass=True).run()
        return out, vendor, llm

    def test_g1_real_toolmessage_reaches_the_final_analysis(self):
        out, _v, llm = self._run([
            AIMessage(content="", tool_calls=[_news_call()]),
            AIMessage(content="", tool_calls=[_schema_call()]),
        ])
        # The classification the report was built from can only come from the
        # executed ToolMessage; assert it is present with its real content.
        titles = [m.content for m in _tool_messages(out)
                  if "Nvidia unveils" in m.content]
        self.assertEqual(len(titles), 1)
        self.assertIn("**Stance:** Bullish", out["news_report"])

    def test_g2_every_tool_call_has_result_and_g3_no_rerun(self):
        out, vendor, llm = self._run([
            AIMessage(content="", tool_calls=[_news_call("a")]),
            AIMessage(content="", tool_calls=[_global_call("b")]),
            AIMessage(content="", tool_calls=[_news_call("c")]),
            AIMessage(content="", tool_calls=[_schema_call()]),
        ])
        self.assertEqual(len(vendor.news_calls), 2)
        self.assertEqual(len(vendor.global_calls), 1)
        _assert_single_pass_finalised(self, out)

    def test_g3_b_mixed_turn_runs_the_data_call_once(self):
        mixed = AIMessage(content="", tool_calls=[
            _news_call("mixed"),
            _schema_call(call_id="mixed-schema"),
        ])
        out, vendor, llm = self._run([
            mixed,
            AIMessage(content="", tool_calls=[_schema_call()]),
        ])
        self.assertEqual(len(vendor.news_calls), 1)
        _assert_single_pass_finalised(self, out)
        self.assertIn("**Stance:** Bullish", out["news_report"])

    def test_g4_one_node_visit_and_one_structured_answer(self):
        harness = NewsGraphHarness(self, _make_llm([
            AIMessage(content="", tool_calls=[_news_call("a")]),
            AIMessage(content="", tool_calls=[_news_call("b")]),
            AIMessage(content="", tool_calls=[_schema_call()]),
        ]), single_pass=True)
        vendor = _RecordingVendor(
            self, news_text=finnhub_news_text("NVDA", STORIES))
        with vendor:
            out = harness.run()
        # Data tools run inside the node, so the graph's ToolNode is never
        # entered: one visit, one report.
        self.assertEqual(harness.news_node_visits, 1)
        self.assertEqual(len(vendor.news_calls), 2)
        self.assertIn("**Stance:** Bullish", out["news_report"])

    def test_g6_unknown_path_stays_closed(self):
        harness = NewsGraphHarness(self, _make_llm([
            AIMessage(content="", tool_calls=[_news_call()]),
            AIMessage(content="", tool_calls=[_schema_call()]),
        ]), single_pass=True)
        with _RecordingVendor(self, news_text=EMPTY_WINDOW):
            out = harness.run()
        self.assertEqual(harness.news_node_visits, 1)
        self.assertTrue(out["news_report"].startswith(NEWS_UNAVAILABLE_PREFIX))


class ProseFallbackTest(unittest.TestCase):
    """A prose ending (no schema call) must still carry the right status."""

    def test_prose_with_real_news_states_available(self):
        llm = _make_llm([
            AIMessage(content="", tool_calls=[_news_call()]),
            AIMessage(content="NVDA news is constructive."),
        ])
        with _RecordingVendor(self, news_text=finnhub_news_text("NVDA", STORIES)):
            out = NewsGraphHarness(self, llm, single_pass=True).run()
        # The model's text is preserved byte-identically; the system states the
        # tool-derived availability in front of it, never reading the text.
        self.assertEqual(out["news_report"],
                         NEWS_SOURCE_AVAILABLE_NOTE + "NVDA news is constructive.")

    def test_prose_with_dead_news_gets_the_header(self):
        llm = _make_llm([
            AIMessage(content="", tool_calls=[_news_call()]),
            AIMessage(content="NVDA looks mixed."),
        ])
        with _RecordingVendor(self, news_text=EMPTY_WINDOW):
            out = NewsGraphHarness(self, llm, single_pass=True).run()
        self.assertTrue(out["news_report"].startswith(NEWS_UNAVAILABLE_PREFIX))

    def test_budget_exhaustion_over_dead_news_gets_the_header(self):
        # Always ask for another tool round: SINGLE_PASS_MAX_ROUNDS runs out.
        llm = _make_llm([
            AIMessage(content="", tool_calls=[_news_call("loop")]),
        ])
        with _RecordingVendor(self, news_text=EMPTY_WINDOW):
            out = NewsGraphHarness(self, llm, single_pass=True).run()
        self.assertTrue(out["news_report"].startswith(NEWS_UNAVAILABLE_PREFIX))

    def test_budget_exhaustion_over_real_news_keeps_available(self):
        llm = _make_llm([
            AIMessage(content="", tool_calls=[_news_call("loop")]),
        ])
        with _RecordingVendor(self, news_text=finnhub_news_text("NVDA", STORIES)):
            out = NewsGraphHarness(self, llm, single_pass=True).run()
        self.assertFalse(out["news_report"].startswith(NEWS_UNAVAILABLE_PREFIX))


class Rc1ParityTest(unittest.TestCase):
    """G5: RC1's two-call node classifies the same inputs the same way.

    Driven directly, one visit per legacy step (the two-call node returns its
    own message and lets the graph's ``ToolNode`` interleave the result).
    """

    def _run_two_call(self, text):
        llm = _make_llm([AIMessage(content="", tool_calls=[_news_call()])])
        node = create_news_analyst(llm, batch_macro=False, structured=True,
                                   single_pass=False)
        messages = [HumanMessage(content="Analyse NVDA news")]
        state = {"messages": messages, "trade_date": TRADE_DATE,
                 "company_of_interest": "NVDA", "asset_type": "stock"}
        with _RecordingVendor(self, news_text=text) as vendor:
            first = node(state)
            tool_msg = ToolMessage(
                content=vendor.news_text, name="get_news",
                tool_call_id=first["messages"][0].tool_calls[0]["id"])
            second = node(dict(state, messages=[
                *messages, *first["messages"], tool_msg]))
        return first["news_report"], second["news_report"]

    def test_rc1_prose_ending_is_empty_exactly_as_before(self):
        # RC1's two-call ending relies on the model writing prose; a scripted
        # model that ends on a tool call yields "". Unchanged from RC1.
        first, _second = self._run_two_call(EMPTY_WINDOW)
        self.assertEqual(first, "")

    def test_rc1_sees_real_news_as_available(self):
        # The classification is what TC-01's own two-call regression pins; with
        # the ToolMessage in state, RC1 reads the feed as available (no forced
        # header) -- the behaviour single-pass must now match.
        _first, second = self._run_two_call(finnhub_news_text("NVDA", STORIES))
        self.assertFalse(second.startswith(NEWS_UNAVAILABLE_PREFIX), second[:200])

    def test_rc1_forced_header_only_on_dead_feeds(self):
        from tradingagents.agents.schemas import classify_news_source_availability

        dead = [ToolMessage(content=EMPTY_WINDOW, name="get_news",
                            tool_call_id="x")]
        live = [ToolMessage(content=finnhub_news_text("NVDA", STORIES),
                            name="get_news", tool_call_id="x")]
        self.assertIs(classify_news_source_availability(dead),
                      NewsSourceStatus.UNAVAILABLE)
        self.assertIs(classify_news_source_availability(live),
                      NewsSourceStatus.AVAILABLE)


class ProvenanceStatusTest(unittest.TestCase):
    """Availability is decided by provenance (the get_news ToolMessages), not text.

    Final audit H1: an earlier attempt to strip model-written banners matched on
    words and therefore deleted real sentences, a quoted banner and a code-block
    banner from live reports. The guard no longer rewrites model content at all.
    Status comes from ``classify_news_source_availability`` over the real tool
    history; the only text the system owns is its own banner component, which is
    identified by exact text and emitted only when the feed is dead.
    """

    # Every one of these is legitimate model prose and must survive verbatim on
    # a live feed -- including the historical quotation and its blockquote and
    # code-block forms (user requirements 1, 2).
    PRESERVED = (
        ("false-declaration-at-head",
         "News source unavailable. That said, the roadmap is live."),
        ("false-declaration-colon",
         "News source unavailable: management guided higher."),
        ("false-declaration-semicolon",
         "News source unavailable; but the flow is bullish."),
        ("sentence-with-claim",
         "News source unavailable for the previous quarter, but this quarter's"
         " roadmap is live and bullish."),
        ("historical-quotation",
         "Yesterday the log read:\n\n> **News source unavailable.**\n\n"
         "Today the articles are live and bullish."),
        ("quotation-in-blockquote",
         "> **News source unavailable for this window.**"),
        ("quotation-nested-blockquote",
         "> > **News source unavailable for this window.**"),
        ("quotation-in-code-block",
         "Example:\n```\n> **News source unavailable.**\n```"),
        ("article-headline",
         "### News source unavailable for Boeing suppliers (source: Reuters)"),
        ("mid-sentence-mention",
         "The desk log shows a news source unavailable banner last week."),
        ("real-model-stance",
         "**Stance:** Mixed\n\nTwo-sided tape."),
        ("real-unknown-stance",
         "**Stance:** Unknown\n\nNo directional read."),
        ("plain-prose", "Bullish body with real evidence."),
    )

    def _prose_run(self, text, prose):
        llm = _make_llm([
            AIMessage(content="", tool_calls=[_news_call()]),
            AIMessage(content=prose),
        ])
        with _RecordingVendor(self, news_text=text):
            return NewsGraphHarness(self, llm, single_pass=True).run()["news_report"]

    def test_real_news_never_injects_the_banner(self):
        live = finnhub_news_text("NVDA", STORIES)
        for why, prose in self.PRESERVED:
            with self.subTest(why=why):
                report = self._prose_run(live, prose)
                self.assertFalse(
                    report.startswith(NEWS_UNAVAILABLE_BANNER), report[:120])

    def test_real_news_preserves_model_text_verbatim(self):
        # Requirement 2: no deletion merely for sharing the banner's wording.
        live = finnhub_news_text("NVDA", STORIES)
        for why, prose in self.PRESERVED:
            with self.subTest(why=why):
                self.assertIn(prose, self._prose_run(live, prose))

    def test_live_feed_states_availability_without_reading_the_text(self):
        # Requirement 3/decision: the system states the tool-derived status on
        # the prose-fallback path; it does not judge the model's words. Every
        # report below -- asserting, mentioning, agreeing -- gets the same
        # status line and its text is preserved verbatim.
        live = finnhub_news_text("NVDA", STORIES)
        for why, prose in self.PRESERVED:
            with self.subTest(why=why):
                report = self._prose_run(live, prose)
                self.assertTrue(
                    report.startswith(NEWS_SOURCE_AVAILABLE_NOTE), report[:120])
                self.assertIn(prose, report)
                self.assertFalse(report.startswith(NEWS_UNAVAILABLE_BANNER))

    def test_agreeing_report_gets_the_same_status_line(self):
        # No text matching: an ordinary agreeing report and a contradictory one
        # are treated identically, because the status is the tool's, not the
        # model's.
        live = finnhub_news_text("NVDA", STORIES)
        agreeing = self._prose_run(live, "NVDA news is constructive.")
        contradictory = self._prose_run(
            live, "News source unavailable. The tape is bullish.")
        self.assertEqual(agreeing, NEWS_SOURCE_AVAILABLE_NOTE
                         + "NVDA news is constructive.")
        self.assertEqual(contradictory, NEWS_SOURCE_AVAILABLE_NOTE
                         + "News source unavailable. The tape is bullish.")

    def test_dead_feed_exposes_unknown_via_the_system_banner(self):
        # Requirement 4. The count is of the system banner component, never of
        # the bare phrase: a model may quote that phrase as evidence, and that
        # quote must stay (requirement 2).
        for why, prose in self.PRESERVED:
            with self.subTest(why=why):
                report = self._prose_run(EMPTY_WINDOW, prose)
                self.assertTrue(report.startswith(NEWS_UNAVAILABLE_BANNER),
                                report[:120])
                self.assertEqual(
                    report.count(NEWS_UNAVAILABLE_BANNER), 1, report)
                self.assertIn("**Stance:** Unknown", report)

    def test_dead_feed_keeps_quoted_evidence_intact(self):
        # Requirement 2 applies on a dead feed too: the model's quote is kept.
        prose = "Example:\n```\n> **News source unavailable.**\n```"
        report = self._prose_run(EMPTY_WINDOW, prose)
        self.assertTrue(report.startswith(NEWS_UNAVAILABLE_BANNER))
        self.assertIn(prose, report)

    def test_valid_bullish_and_bearish_stances_survive_real_news(self):
        # Requirement 5, end to end through the graph with a schema answer.
        live = finnhub_news_text("NVDA", STORIES)
        for stance in ("Bullish", "Bearish"):
            with self.subTest(stance=stance):
                llm = _make_llm([
                    AIMessage(content="", tool_calls=[_news_call()]),
                    AIMessage(content="", tool_calls=[_schema_call(
                        dict(BULLISH_ARGS, stance=stance))]),
                ])
                with _RecordingVendor(self, news_text=live):
                    report = NewsGraphHarness(
                        self, llm, single_pass=True).run()["news_report"]
                self.assertIn(f"**Stance:** {stance}", report)
                self.assertFalse(report.startswith(NEWS_UNAVAILABLE_BANNER))

    def test_node_never_reads_the_report_text_for_status(self):
        # Decision: never match text. The guard and the status line must be
        # pure functions of the classifier verdict, identical for every body.
        from tradingagents.agents.analysts.news_analyst import (
            _guard_news_unavailable, _news_available_note,
        )

        asserting = (
            "News source unavailable. The tape is bullish.",
            "> **News source unavailable.**",
            "News source unavailable for this window.",
            "**News source unavailable for this window.** The stance is Unknown.",
            "- News source unavailable",
            "Yesterday:\n\n> **News source unavailable.**\n\nToday live.",
            "Example:\n```\n> **News source unavailable.**\n```",
        )
        mentioning = (
            "The desk log shows a news source unavailable banner last week.",
            "### News source unavailable for Boeing suppliers (source: Reuters)",
            "News source unavailable last week, but now live.",
            "Global macro news source unavailable; company news is live.",
            "News is constructive.",
        )
        for text in asserting + mentioning:
            with self.subTest(text=text[:40]):
                self.assertEqual(
                    _guard_news_unavailable(text, NewsSourceStatus.AVAILABLE),
                    text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\n"))
                self.assertTrue(_news_available_note(
                    NewsSourceStatus.AVAILABLE).startswith(
                        NEWS_SOURCE_AVAILABLE_NOTE))
                self.assertEqual(
                    _news_available_note(NewsSourceStatus.UNAVAILABLE), "")

    def test_guard_is_idempotent_and_uses_only_its_own_banner(self):
        # Requirement 5: provenance, not text matching -- and no double banner.
        from tradingagents.agents.analysts.news_analyst import (
            _guard_news_unavailable,
        )

        once = _guard_news_unavailable("body", NewsSourceStatus.UNAVAILABLE)
        self.assertEqual(once, _guard_news_unavailable(
            once, NewsSourceStatus.UNAVAILABLE))
        self.assertEqual(once.count(NEWS_UNAVAILABLE_BANNER), 1)
        cleared = _guard_news_unavailable(once, NewsSourceStatus.AVAILABLE)
        self.assertEqual(cleared, "body")
        self.assertEqual(_guard_news_unavailable(
            cleared, NewsSourceStatus.UNAVAILABLE), once)
        # A report the application never wrote is never altered on AVAILABLE.
        for _, prose in self.PRESERVED:
            self.assertEqual(
                _guard_news_unavailable(prose, NewsSourceStatus.AVAILABLE), prose)


class StanceInvariantsTest(unittest.TestCase):
    """UNKNOWN semantics must survive the fix (no Unknown -> Neutral)."""

    def test_model_unknown_stance_with_real_news_is_not_rewritten(self):
        args = {"stance": "Unknown", "interpretation": "No directional read."}
        llm = _make_llm([
            AIMessage(content="", tool_calls=[_news_call()]),
            AIMessage(content="", tool_calls=[_schema_call(args)]),
        ])
        with _RecordingVendor(self, news_text=finnhub_news_text("NVDA", STORIES)):
            out = NewsGraphHarness(self, llm, single_pass=True).run()
        self.assertIn("**Stance:** Unknown", out["news_report"])
        self.assertNotIn("**Stance:** Neutral", out["news_report"])
        self.assertFalse(out["news_report"].startswith(NEWS_UNAVAILABLE_PREFIX))

    def test_forced_unknown_never_becomes_neutral(self):
        llm = _make_llm([
            AIMessage(content="", tool_calls=[_news_call()]),
            AIMessage(content="", tool_calls=[_schema_call(
                {"stance": "Neutral", "interpretation": "two-sided"})]),
        ])
        with _RecordingVendor(self, news_text=EMPTY_WINDOW):
            out = NewsGraphHarness(self, llm, single_pass=True).run()
        self.assertIn("**Stance:** Unknown", out["news_report"])
        self.assertNotIn("**Stance:** Neutral", out["news_report"])


class ClassifierUnitFenceTest(unittest.TestCase):
    """The classifier itself is unchanged; only the history it sees is."""

    def test_no_messages_is_unavailable(self):
        self.assertIs(classify_news_source_availability([]),
                      NewsSourceStatus.UNAVAILABLE)

    def test_global_news_alone_is_unavailable(self):
        msg = ToolMessage(content=GLOBAL_NEWS, name="get_global_news",
                          tool_call_id="g")
        self.assertIs(classify_news_source_availability([msg]),
                      NewsSourceStatus.UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
