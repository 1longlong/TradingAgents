"""Workstream 3 — native structured analyst output (S2).

The three tool-loop analysts used to emit free-form markdown. S2 makes their
*terminal generation* produce typed fields, then renders them back to markdown.

These tests pin the properties that make that safe to ship:

1. **It can never block a run.** Any structured failure keeps the prose the loop
   already produced. A shape change is not allowed to become an outage.
2. **An empty report is not "structured".** If the loop produced nothing, no
   schema call is made and nothing is invented.
3. **The rendered report preserves the decision-relevant content** the
   downstream researchers consume: evidence, the analyst-specific block, risks,
   and the interpretation.
4. **The no-data path stays honest** — `AnalystStance.UNKNOWN` exists, so an
   analyst that could not fetch data is not forced into a verdict.
"""

from __future__ import annotations

import unittest
from unittest import mock

from tradingagents.agents import schemas as S
from tradingagents.agents.utils.structured import finalize_analyst_report

EVIDENCE = [S.EvidenceItem(claim="price above 50d", evidence="close=178.42 vs 171.9", source="snapshot")]


class _FakeStructured:
    """Stands in for llm.with_structured_output(schema)."""

    def __init__(self, result=None, exc=None):
        self.result = result
        self.exc = exc
        self.calls = 0

    def invoke(self, messages, config=None):
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.result


def _market(**over):
    base = dict(
        stance=S.AnalystStance.BULLISH,
        key_evidence=EVIDENCE,
        key_levels=[S.PriceLevel(label="Resistance", price="179.88", why="session high")],
        risks=["ATR rising"],
        interpretation="Trend intact above both averages.",
    )
    base.update(over)
    return S.MarketAnalystReport(**base)


class FallbackTest(unittest.TestCase):
    """Structured finalisation must never abort or blank a report."""

    def test_failure_keeps_free_text(self):
        fake = _FakeStructured(exc=RuntimeError("provider 503"))
        out, obj = finalize_analyst_report(
            llm=object(), structured_llm=fake, messages=[], render=S.render_market_analyst_report,
            agent_name="Market Analyst", free_text_block="## Free text report",
        )
        self.assertEqual(out, "## Free text report")
        self.assertIsNone(obj, "a failed structuring attempt must not expose a typed object")
        self.assertEqual(fake.calls, 1)

    def test_none_result_keeps_free_text(self):
        fake = _FakeStructured(result=None)
        out, obj = finalize_analyst_report(
            llm=object(), structured_llm=fake, messages=[], render=S.render_market_analyst_report,
            agent_name="Market Analyst", free_text_block="prose",
        )
        self.assertEqual(out, "prose")
        self.assertIsNone(obj)

    def test_unsupported_provider_keeps_free_text_without_calling(self):
        out, obj = finalize_analyst_report(
            llm=object(), structured_llm=None, messages=[], render=S.render_market_analyst_report,
            agent_name="Market Analyst", free_text_block="prose",
        )
        self.assertEqual(out, "prose")
        self.assertIsNone(obj)

    def test_empty_block_makes_no_structured_call(self):
        # The loop ended without a report (e.g. it kept calling tools until the
        # step limit). There is nothing to structure, and inventing one would be
        # fabrication.
        fake = _FakeStructured(result=_market())
        out, obj = finalize_analyst_report(
            llm=object(), structured_llm=fake, messages=[], render=S.render_market_analyst_report,
            agent_name="Market Analyst", free_text_block="",
        )
        self.assertEqual(out, "")
        self.assertIsNone(obj)
        self.assertEqual(fake.calls, 0)

    def test_whitespace_only_block_makes_no_call(self):
        fake = _FakeStructured(result=_market())
        out, obj = finalize_analyst_report(
            llm=object(), structured_llm=fake, messages=[], render=S.render_market_analyst_report,
            agent_name="Market Analyst", free_text_block="   \n ",
        )
        self.assertEqual(out, "   \n ")
        self.assertIsNone(obj)
        self.assertEqual(fake.calls, 0)

    def test_empty_render_falls_back(self):
        fake = _FakeStructured(result=_market())
        out, obj = finalize_analyst_report(
            llm=object(), structured_llm=fake, messages=[], render=lambda _r: "   ",
            agent_name="Market Analyst", free_text_block="prose",
        )
        self.assertEqual(out, "prose")
        self.assertIsNone(obj)

    def test_success_returns_rendered_markdown(self):
        fake = _FakeStructured(result=_market())
        out, obj = finalize_analyst_report(
            llm=object(), structured_llm=fake, messages=[], render=S.render_market_analyst_report,
            agent_name="Market Analyst", free_text_block="prose",
        )
        self.assertIn("**Stance:** Bullish", out)
        self.assertNotEqual(out, "prose")
        # The typed object is returned only on the success branch, so downstream
        # stages can distinguishes real fields from a prose fallback.
        self.assertIsNotNone(obj)
        self.assertIsInstance(obj, S.MarketAnalystReport)


class RenderPreservesContentTest(unittest.TestCase):
    """Each analyst's rendered report must keep what downstream agents read."""

    def test_market_report_has_all_blocks(self):
        out = S.render_market_analyst_report(_market())
        for needle in ("**Stance:**", "**Key evidence:**", "**Key levels:**", "**Risks:**",
                       "178.42", "Resistance: 179.88", "ATR rising", "Trend intact"):
            self.assertIn(needle, out)

    def test_fundamentals_report_has_figures(self):
        r = S.FundamentalsAnalystReport(
            stance=S.AnalystStance.MILDY_BULLISH if hasattr(S.AnalystStance, "MILDY_BULLISH")
            else S.AnalystStance.MILDLY_BULLISH,
            key_evidence=EVIDENCE,
            key_figures=[S.FundamentalFact(metric="Revenue", value="46.7B (Q2 FY2026)", read="demand strong")],
            risks=["customer concentration"],
            interpretation="Margins stay wide.",
        )
        out = S.render_fundamentals_analyst_report(r)
        for needle in ("**Key figures:**", "Revenue: 46.7B (Q2 FY2026)", "customer concentration", "Margins stay wide."):
            self.assertIn(needle, out)
        self.assertNotIn("**Key levels:**", out)

    def test_news_report_has_catalysts(self):
        r = S.NewsAnalystReport(
            stance=S.AnalystStance.MIXED,
            key_evidence=EVIDENCE,
            catalysts=[S.Catalyst(date="2026-09-22", event="hyperscaler deal", relevance="demand visibility")],
            risks=["export licence review"],
            interpretation="Positive flow, policy risk.",
        )
        out = S.render_news_analyst_report(r)
        for needle in ("**Catalysts:**", "2026-09-22 — hyperscaler deal", "export licence review"):
            self.assertIn(needle, out)
        # News must not carry a price-level block: that field belonged to the
        # generic schema and invited the model to relabel a headline number.
        self.assertNotIn("**Key levels:**", out)

    def test_unknown_stance_renders_without_a_verdict(self):
        r = S.NewsAnalystReport(stance=S.AnalystStance.UNKNOWN, interpretation="No news retrieved.")
        out = S.render_news_analyst_report(r)
        self.assertIn("**Stance:** Unknown", out)


class NewsMissingnessTest(unittest.TestCase):
    """A dead company-news feed must never render as a directional stance.

    Observed in the shipped-config run: every seed prompt for 2026-09-23 said
    "use Unknown if the data you needed could not be retrieved", and the
    20261106 campaign obeyed it 10/10 — but the first 20261107 run returned
    ``stance=Mixed`` plus "trim exposure into strength" while its own evidence
    said no NVDA news could be verified. Macro data arriving made the
    instruction ambiguous, so the decision is now made in Python.
    """

    def _report(self, stance):
        return S.NewsAnalystReport(
            stance=stance,
            key_evidence=EVIDENCE,
            risks=["no company news retrieved"],
            interpretation="Macro-only: rates up, VIX low.",
        )

    def test_unavailable_source_forces_unknown_even_when_model_says_mixed(self):
        r = self._report(S.AnalystStance.MIXED).model_copy(
            update={"news_source_status": S.NewsSourceStatus.UNAVAILABLE}
        )
        out = S.render_news_analyst_report(r)
        self.assertIn("**Stance:** Unknown", out)
        self.assertNotIn("**Stance:** Mixed", out)
        self.assertIn("News source unavailable for this window", out)
        # The model's reasoning is kept, not deleted -- only the verdict is fixed.
        self.assertIn("Macro-only: rates up, VIX low.", out)

    def test_available_source_keeps_model_stance(self):
        r = self._report(S.AnalystStance.MIXED).model_copy(
            update={"news_source_status": S.NewsSourceStatus.AVAILABLE}
        )
        out = S.render_news_analyst_report(r)
        self.assertIn("**Stance:** Mixed", out)
        self.assertNotIn("News source unavailable", out)

    @staticmethod
    def _tool(name, content):
        # Build the attributes *after* construction: ``MagicMock(name="x")``
        # sets the mock's repr, not ``.name``, so it would silently fail to
        # match the classifier's ``getattr(m, "name")`` check.
        m = mock.MagicMock(type="tool")
        m.name = name
        m.content = content
        return m

    def test_classifier_flags_data_unavailable(self):
        msg = self._tool(
            "get_news", "DATA_UNAVAILABLE: no configured vendor could serve get_news right now"
        )
        self.assertIs(S.classify_news_source_availability([msg]), S.NewsSourceStatus.UNAVAILABLE)

    def test_classifier_flags_coverage_gap(self):
        # A live-only vendor answering an old window is "no company news", not
        # "this company had no news".
        msg = self._tool(
            "get_news",
            "<Yahoo Finance news unavailable for 2026-09-16..2026-09-23: it only serves newer items>",
        )
        self.assertIs(S.classify_news_source_availability([msg]), S.NewsSourceStatus.UNAVAILABLE)

    def test_classifier_accepts_real_articles(self):
        msg = self._tool(
            "get_news",
            "### NVDA announces X\n- Publisher: Reuters\n- Link: https://example.com/a",
        )
        self.assertIs(S.classify_news_source_availability([msg]), S.NewsSourceStatus.AVAILABLE)

    def test_classifier_ignores_non_news_tools(self):
        msg = self._tool("get_macro_indicators_batch", "CPI 334.1")
        self.assertIs(S.classify_news_source_availability([msg]), S.NewsSourceStatus.UNAVAILABLE)

    def test_classifier_never_called_means_unavailable(self):
        self.assertIs(S.classify_news_source_availability([]), S.NewsSourceStatus.UNAVAILABLE)

    def test_classifier_any_real_news_wins_over_a_failed_call(self):
        failed = self._tool("get_news", "DATA_UNAVAILABLE: vendor down")
        real = self._tool("get_news", "### A real headline\n- Publisher: Reuters")
        self.assertIs(
            S.classify_news_source_availability([failed, real]), S.NewsSourceStatus.AVAILABLE
        )

    def test_every_stance_member_is_renderable(self):
        for stance in S.AnalystStance:
            r = S.MarketAnalystReport(stance=stance, interpretation="x")
            self.assertIn(stance.value, S.render_market_analyst_report(r))


class SchemaInvariantsTest(unittest.TestCase):
    def test_no_analyst_schema_requires_a_score_or_verdict(self):
        # Every field beyond stance must be optional, so a data-starved analyst
        # can still emit a valid structured report instead of failing validation
        # and losing the whole report to the fallback.
        for schema in (S.MarketAnalystReport, S.FundamentalsAnalystReport, S.NewsAnalystReport):
            for name, field in schema.model_fields.items():
                if name == "stance":
                    continue
                self.assertFalse(
                    field.is_required(),
                    f"{schema.__name__}.{name} is required; a data gap would invalidate the report",
                )

    def test_analyst_specific_blocks_are_disjoint(self):
        self.assertIn("key_levels", S.MarketAnalystReport.model_fields)
        self.assertNotIn("key_levels", S.FundamentalsAnalystReport.model_fields)
        self.assertNotIn("key_levels", S.NewsAnalystReport.model_fields)
        self.assertIn("key_figures", S.FundamentalsAnalystReport.model_fields)
        self.assertIn("catalysts", S.NewsAnalystReport.model_fields)

    def test_all_schemas_serialisable(self):
        for schema in (S.MarketAnalystReport, S.FundamentalsAnalystReport, S.NewsAnalystReport):
            js = schema.model_json_schema()
            self.assertEqual(js["type"], "object")


class WiringTest(unittest.TestCase):
    """The three analysts must actually call the finaliser."""

    def test_all_three_analysts_finalise(self):
        from tradingagents.agents.analysts import (
            fundamentals_analyst,
            market_analyst,
            news_analyst,
        )

        for mod, schema_name in (
            (market_analyst, "MarketAnalystReport"),
            (fundamentals_analyst, "FundamentalsAnalystReport"),
            (news_analyst, "NewsAnalystReport"),
        ):
            src = open(mod.__file__).read()
            self.assertIn("finalize_analyst_report", src, mod.__name__)
            self.assertIn(schema_name, src, mod.__name__)
            self.assertIn("bind_structured", src, mod.__name__)

    def test_trailing_prose_is_dropped_not_replayed(self):
        # The loop's last message is the finished prose report. Replaying it to
        # a schema-bound call makes the model answer "I already wrote it" or
        # refuse ("I can't produce the report from the data"), and re-sending it
        # also charges for the discarded prose a second time (measured at 2.7x
        # the free-text cost). It is therefore dropped, and the tool history the
        # loop accumulated is what grounds the structured fields.
        from langchain_core.messages import AIMessage, HumanMessage

        fake = _FakeStructured(result=_market())
        captured = {}

        def spy(messages, config=None):
            captured["messages"] = messages
            return _market()

        fake.invoke = spy
        finalize_analyst_report(
            llm=object(), structured_llm=fake,
            messages=[HumanMessage(content="TOOL RESULT: close=178.42"),
                      AIMessage(content="FINAL PROSE ANALYSIS")],
            render=S.render_market_analyst_report, agent_name="X", free_text_block="FINAL PROSE ANALYSIS",
        )
        sent = captured["messages"]
        self.assertEqual(type(sent[-1]).__name__, "HumanMessage")
        self.assertEqual([type(m).__name__ for m in sent], ["HumanMessage", "HumanMessage"])
        # The tool evidence survives...
        self.assertIn("close=178.42", sent[0].content)
        # ...and the discarded prose is gone.
        self.assertNotIn("FINAL PROSE ANALYSIS", "".join(m.content for m in sent))

    def test_free_text_guidance_stripped_from_structured_call(self):
        # Measured live: with the analyst prompt's trailing "Write a very
        # detailed and nuanced report ..." the schema call succeeded 1/3; without
        # it, 3/3. The analytical instructions before it must survive.
        from langchain_core.messages import HumanMessage, SystemMessage

        fake = _FakeStructured(result=_market())
        captured = {}
        fake.invoke = lambda messages, config=None: captured.setdefault("m", messages) or _market()
        system = (
            "Prefer these indicators: rsi, macd, atr.\n\n"
            "Write a very detailed and nuanced report of the trends you observe. "
            "Provide specific, actionable insights."
        )
        finalize_analyst_report(
            llm=object(), structured_llm=fake,
            messages=[SystemMessage(content=system), HumanMessage(content="data")],
            render=S.render_market_analyst_report, agent_name="X", free_text_block="prose",
        )
        sent_system = captured["m"][0].content
        self.assertNotIn("Write a very detailed", sent_system)
        self.assertIn("Prefer these indicators", sent_system)

    def test_tool_call_instruction_neutralised_for_structured_call(self):
        # Schema-only structured output binds exactly one tool. A prompt that
        # still says "call get_verified_market_snapshot" makes the model emit an
        # unknown tool call, the parser raises and the report falls back.
        # Measured live: 2 failures out of 3 before this was handled.
        from langchain_core.messages import HumanMessage, SystemMessage

        fake = _FakeStructured(result=_market())
        captured = {}
        fake.invoke = lambda messages, config=None: captured.setdefault("m", messages) or _market()
        system = (
            "Before writing the final report, call get_verified_market_snapshot for "
            "this ticker and the current date, and treat it as the source of truth "
            "for any exact OHLCV claim."
        )
        finalize_analyst_report(
            llm=object(), structured_llm=fake,
            messages=[SystemMessage(content=system), HumanMessage(content="data")],
            render=S.render_market_analyst_report, agent_name="X", free_text_block="prose",
        )
        sent_system = captured["m"][0].content
        self.assertNotIn("call get_verified_market_snapshot for this ticker", sent_system)
        self.assertIn("already retrieved", sent_system)
        # The analytical constraint itself is retained, not deleted.
        self.assertIn("source of truth", sent_system)

    def test_fundamentals_layout_stripped_but_tool_and_language_kept(self):
        # FIX-1: the "Please write a comprehensive report ..." marker opens the
        # *middle* of the fundamentals prompt; truncating at it silently dropped
        # the tool-usage sentence and the language instruction from the
        # structured call. Only the prose-layout sentence may be removed.
        from langchain_core.messages import HumanMessage, SystemMessage

        from tradingagents.agents.utils.agent_utils import get_language_instruction
        from tradingagents.dataflows import config as df_config

        report = S.FundamentalsAnalystReport(stance=S.AnalystStance.UNKNOWN, interpretation="x")
        fake = _FakeStructured(result=report)
        captured = {}
        fake.invoke = lambda messages, config=None: captured.setdefault("m", messages) or report
        # Same construction as fundamentals_analyst.py:44-49.
        try:
            df_config.set_config({"output_language": "German"})
            language_instruction = get_language_instruction()
            self.assertTrue(language_instruction, "language instruction must be non-empty for this test")
            system = (
                "You are a researcher tasked with analyzing fundamental information over the past week about a company. Please write a comprehensive report of the company's fundamental information such as financial documents, company profile, basic company financials, and company financial history to gain a full view of the company's fundamental information to inform traders. Make sure to include as much detail as possible. Provide specific, actionable insights with supporting evidence to help traders make informed decisions."
                + " Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."
                + " Use the available tools: `get_fundamentals` for comprehensive company analysis, `get_balance_sheet`, `get_cashflow`, and `get_income_statement` for specific financial statements."
                + language_instruction
            )
        finally:
            df_config.set_config({"output_language": "English"})
        finalize_analyst_report(
            llm=object(), structured_llm=fake,
            messages=[SystemMessage(content=system), HumanMessage(content="data")],
            render=S.render_fundamentals_analyst_report, agent_name="X", free_text_block="prose",
        )
        sent_system = captured["m"][0].content
        self.assertNotIn("Please write a comprehensive report", sent_system)
        self.assertNotIn("append a Markdown table", sent_system)
        self.assertIn("Use the available tools: `get_fundamentals`", sent_system)
        self.assertIn("`get_balance_sheet`", sent_system)
        self.assertIn(language_instruction.strip(), sent_system)


def _cond(**over):
    base = dict(
        condition="weekly close below the 50-day SMA",
        observable_signal="close vs close_50_sma in get_indicators",
        threshold="171.90",
        evidence_basis="close=178.42 vs 50d SMA 171.90",
        invalidates="the trend-intact stance",
    )
    base.update(over)
    return S.InvalidationCondition(**base)


def _scenario(name, weight, **over):
    base = dict(
        name=S.ScenarioType(name),
        weight=weight,
        supporting_evidence="hyperscaler capex guidance up",
        trigger_conditions="close above 179.88 resistance",
        invalidation_conditions="close back below the 50d SMA",
    )
    base.update(over)
    return S.Scenario(**base)


def _market_with(**over):
    kwargs = dict(stance=S.AnalystStance.MILDLY_BULLISH, key_evidence=EVIDENCE, interpretation="Trend intact")
    kwargs.update(over)
    return S.MarketAnalystReport(**kwargs)


class InvalidationConditionTest(unittest.TestCase):
    """A2 — invalidation conditions must render, and must not be invented."""

    def test_market_renders_grounded_condition(self):
        out = S.render_market_analyst_report(_market_with(invalidation=[_cond()]))
        self.assertIn("**Invalidation conditions:**", out)
        self.assertIn("weekly close below the 50-day SMA", out)
        self.assertIn("threshold: 171.90", out)
        self.assertIn("invalidates: the trend-intact stance", out)
        # Rendered before the closing interpretation, so it is not lost in prose.
        self.assertLess(out.index("Invalidation conditions"), out.index("Trend intact"))

    def test_fundamentals_renders_grounded_condition(self):
        r = S.FundamentalsAnalystReport(
            stance=S.AnalystStance.BEARISH,
            invalidation=[_cond(condition="gross margin falls below 40%", threshold="40%")],
            interpretation="Margins compressing.",
        )
        out = S.render_fundamentals_analyst_report(r)
        self.assertIn("gross margin falls below 40%", out)
        self.assertIn("threshold: 40%", out)

    def test_no_threshold_is_stated_not_invented(self):
        out = S.render_market_analyst_report(
            _market_with(invalidation=[_cond(threshold=None, evidence_basis="close above the 50d SMA")])
        )
        self.assertIn("threshold: no fixed threshold", out)
        # The threshold slot itself must not have been given a fabricated number.
        slot = out.split("threshold: ")[1].split(";")[0]
        self.assertNotRegex(slot, r"\d")

    def test_empty_list_states_unavailable_rather_than_silence(self):
        out = S.render_market_analyst_report(_market_with(invalidation=[]))
        self.assertIn("No invalidation condition could be grounded", out)

    def test_news_render_is_unchanged_by_the_new_blocks(self):
        r = S.NewsAnalystReport(stance=S.AnalystStance.MIXED, interpretation="x")
        out = S.render_news_analyst_report(r)
        self.assertNotIn("Invalidation conditions", out)
        self.assertNotIn("Scenarios", out)


class ScenarioWeightTest(unittest.TestCase):
    """A3 — weights must be honest: no equal split, no rescale, no fabrication."""

    def _render(self, scenario_set):
        return S.render_market_analyst_report(_market_with(scenario_set=scenario_set))

    def test_estimated_weights_render_and_sum(self):
        st = S.ScenarioSet(
            status=S.ScenarioStatus.ESTIMATED,
            scenarios=[_scenario("Bull", 45.0), _scenario("Base", 40.0), _scenario("Bear", 15.0)],
        )
        out = self._render(st)
        self.assertIn("**Scenarios (Bull / Base / Bear):**", out)
        self.assertIn("Bull (weight: 45%)", out)
        self.assertIn("_Weights sum to 100%._", out)
        self.assertIn("invalidated by: close back below the 50d SMA", out)

    def test_not_estimable_is_a_value_not_an_equal_split(self):
        st = S.ScenarioSet(
            status=S.ScenarioStatus.NOT_ESTIMABLE,
            scenarios=[_scenario("Bull", None), _scenario("Base", None), _scenario("Bear", None)],
        )
        out = self._render(st)
        self.assertIn("_Weights not estimable from the retrieved data._", out)
        self.assertNotIn("33%", out)
        for scenario in ("Bull", "Base", "Bear"):
            self.assertIn(f"{scenario} (weight: not estimated)", out)

    def test_not_estimable_suppresses_numeric_weights_the_model_forgot_to_clear(self):
        # Audit D-2: a model that sets status=NOT_ESTIMABLE but leaves the
        # default 33.3/33.3/33.3 in the fields must NOT render an even split.
        # The status is authoritative; the numbers are dropped at the renderer.
        st = S.ScenarioSet(
            status=S.ScenarioStatus.NOT_ESTIMABLE,
            scenarios=[
                _scenario("Bull", 33.3),
                _scenario("Base", 33.3),
                _scenario("Bear", 33.3),
            ],
        )
        out = self._render(st)
        self.assertNotIn("33%", out)
        self.assertIn("_Weights not estimable from the retrieved data._", out)
        for scenario in ("Bull", "Base", "Bear"):
            self.assertIn(f"{scenario} (weight: not estimated)", out)

    def test_not_estimable_suppresses_a_two_way_even_split(self):
        st = S.ScenarioSet(
            status=S.ScenarioStatus.NOT_ESTIMABLE,
            scenarios=[_scenario("Bull", 50.0), _scenario("Bear", 50.0)],
        )
        out = self._render(st)
        self.assertNotIn("50%", out)
        self.assertIn("(weight: not estimated)", out)

    def test_weights_that_do_not_sum_to_100_are_not_rescaled(self):
        st = S.ScenarioSet(
            status=S.ScenarioStatus.ESTIMATED,
            scenarios=[_scenario("Bull", 60.0), _scenario("Base", 60.0)],
        )
        out = self._render(st)
        self.assertIn("Bull (weight: 60%)", out)
        self.assertIn("_Weights sum to 120%", out)
        self.assertIn("not normalised", out)

    def test_out_of_range_weight_is_dropped_not_coerced(self):
        st = S.ScenarioSet(
            status=S.ScenarioStatus.ESTIMATED,
            scenarios=[_scenario("Bull", 45.0), _scenario("Base", -5.0), _scenario("Bear", 1e9)],
        )
        out = self._render(st)
        self.assertIn("Bull (weight: 45%)", out)
        self.assertIn("Base (weight: not estimated)", out)
        self.assertIn("Bear (weight: not estimated)", out)
        self.assertIn("not normalised", out)

    def test_missing_weight_among_present_ones_is_reported(self):
        st = S.ScenarioSet(
            status=S.ScenarioStatus.ESTIMATED,
            scenarios=[_scenario("Bull", 55.0), _scenario("Base", 45.0), _scenario("Bear", None)],
        )
        out = self._render(st)
        self.assertIn("1 branch without a weight", out)

    def test_empty_scenario_set_renders_nothing(self):
        out = self._render(S.ScenarioSet())
        self.assertNotIn("**Scenarios", out)

    def test_fundamentals_scenarios_render(self):
        r = S.FundamentalsAnalystReport(
            stance=S.AnalystStance.NEUTRAL,
            scenario_set=S.ScenarioSet(
                status=S.ScenarioStatus.ESTIMATED,
                scenarios=[_scenario("Base", 100.0)],
            ),
        )
        out = S.render_fundamentals_analyst_report(r)
        self.assertIn("Base (weight: 100%)", out)

    def test_weights_never_trigger_the_prose_fallback(self):
        # A bad weight must degrade the field, not the whole report.
        st = S.ScenarioSet(
            status=S.ScenarioStatus.ESTIMATED,
            scenarios=[_scenario("Bull", float("nan"))],
        )
        fake = _FakeStructured(result=_market_with(scenario_set=st))
        out, _obj = finalize_analyst_report(
            llm=object(), structured_llm=fake, messages=[],
            render=S.render_market_analyst_report, agent_name="Market Analyst",
            free_text_block="PROSE FALLBACK",
        )
        self.assertNotIn("PROSE FALLBACK", out)
        self.assertIn("not estimable", out)


class ScenarioSchemaTest(unittest.TestCase):
    """A3/A5 — schema level: optional, backwards compatible, serialisable."""

    def test_old_payload_without_new_fields_still_validates(self):
        r = S.MarketAnalystReport(stance=S.AnalystStance.BULLISH)
        self.assertEqual(r.invalidation, [])
        self.assertIsNone(r.scenario_set)

    def test_news_schema_has_no_invalidation_or_scenarios(self):
        # Those blocks belong to market and fundamentals; news already carries
        # catalysts and must not be given a price-level style block again.
        self.assertNotIn("invalidation", S.NewsAnalystReport.model_fields)
        self.assertNotIn("scenario_set", S.NewsAnalystReport.model_fields)

    def test_new_fields_are_present_on_both_reports(self):
        for schema in (S.MarketAnalystReport, S.FundamentalsAnalystReport):
            self.assertIn("invalidation", schema.model_fields)
            self.assertIn("scenario_set", schema.model_fields)

    def test_schema_is_serialisable(self):
        js = S.MarketAnalystReport.model_json_schema()
        self.assertIn("invalidation", js["properties"])
        self.assertIn("scenario_set", js["properties"])

    def test_weight_description_distinguishes_probability_from_confidence(self):
        desc = S.Scenario.model_fields["weight"].description.lower()
        self.assertIn("not how confident", desc)


class DownstreamConsumptionTest(unittest.TestCase):
    """A2.6 — the rendered blocks must reach the downstream readers verbatim."""

    def _report(self):
        return S.render_market_analyst_report(
            _market_with(
                invalidation=[_cond()],
                scenario_set=S.ScenarioSet(
                    status=S.ScenarioStatus.ESTIMATED,
                    scenarios=[_scenario("Bull", 45.0), _scenario("Base", 40.0), _scenario("Bear", 15.0)],
                ),
            )
        )

    def test_bull_researcher_prompt_carries_invalidation_and_scenarios(self):
        from tradingagents.agents.researchers.bull_researcher import create_bull_researcher

        report = self._report()
        seen = {}

        class _LLM:
            def invoke(self, prompt):
                seen["prompt"] = prompt
                return mock.Mock(content="bull")

        state = {
            "market_report": report,
            "sentiment_report": "",
            "news_report": "",
            "fundamentals_report": "",
            "investment_debate_state": {"history": "", "bull_history": "", "bear_history": "",
                                        "current_response": "", "count": 0},
        }
        with mock.patch(
            "tradingagents.agents.researchers.bull_researcher.get_instrument_context_from_state",
            return_value="",
        ):
            create_bull_researcher(_LLM())(state)
        self.assertIn("**Invalidation conditions:**", seen["prompt"])
        self.assertIn("Bull (weight: 45%)", seen["prompt"])
        self.assertIn("weekly close below the 50-day SMA", seen["prompt"])

    def test_trader_prompt_carries_market_invalidation(self):
        # The Trader embeds state["market_report"] verbatim (trader.py:44), so a
        # rendered block reaches it without any consumer change. Assert on that
        # contract rather than driving the whole node.
        import inspect

        from tradingagents.agents.trader import trader as trader_module

        report = self._report()
        source = inspect.getsource(trader_module.create_trader)
        self.assertIn('report_section = f"Technical Market Report:\\n{market_report}\\n\\n"', source)
        self.assertIn("**Invalidation conditions:**", report)
        self.assertIn("Bull (weight: 45%)", report)


class PromptInstructionTest(unittest.TestCase):
    """The new analysis instructions must survive the structured-call cleanup."""

    def test_new_instructions_are_not_stripped_as_layout(self):
        from langchain_core.messages import SystemMessage

        from tradingagents.agents.utils.structured import _without_free_text_guidance

        text = (
            "Write a very detailed and nuanced report of the trends you observe."
            " Make sure to append a Markdown table at the end of the report."
            " Also state what would falsify your view: each invalidation condition"
            " must quote a threshold only from tool output."
            " Where the evidence supports it, lay out Bull, Base and Bear branches."
        )
        out = _without_free_text_guidance([SystemMessage(content=text)])[0].content
        self.assertNotIn("append a Markdown table", out)
        self.assertIn("state what would falsify your view", out)
        self.assertIn("Bull, Base and Bear branches", out)


if __name__ == "__main__":
    unittest.main()
