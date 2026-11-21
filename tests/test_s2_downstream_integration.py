"""Workstream B — S2 typed fields are consumed programmatically downstream.

Before this workstream the market/fundamentals analysts parsed an S2 report,
rendered it to markdown, and dropped the object: every downstream agent read the
fields only as prose it had to re-interpret. These tests pin the new contract:

1. The analyst stores the parsed object under a dedicated state key
   (``market_report_obj`` / ``fundamentals_report_obj``) and ``None`` when the
   prose fallback was used.
2. Bull, Bear and the three risk analysts read *role-specific* fields from that
   object and put them in their prompt.
3. The routers return a ``{source: block}`` mapping. Consumers *substitute* the
   routed block for that source's full report, so the prompt carries only the
   fields rather than the whole prose report plus the fields (token-negative).
   A source without typed fields falls back to the full report exactly as before.
4. The routing never invents data: a NOT_ESTIMABLE scenario set produces no
   numbers, a missing field stays missing, and a stop-loss is never presented as
   thesis invalidation.
5. The prose-only / old-S2 path is unchanged: no typed object means the prompt is
   byte-identical to what it was before this workstream.
"""

from __future__ import annotations

import unittest

from tradingagents.agents import schemas as S
from tradingagents.agents.researchers.bear_researcher import create_bear_researcher
from tradingagents.agents.researchers.bull_researcher import create_bull_researcher
from tradingagents.agents.risk_mgmt.aggressive_debator import create_aggressive_debator
from tradingagents.agents.risk_mgmt.conservative_debator import create_conservative_debator
from tradingagents.agents.risk_mgmt.neutral_debator import create_neutral_debator
from tradingagents.agents.utils.s2_context import (
    bear_context_block,
    bull_context_block,
    has_s2_fields,
    risk_context_block,
    routed_report,
)


def _invalidation(text="Weekly close below the 50-day average", basis="price history"):
    return S.InvalidationCondition(
        condition=text,
        observable_signal="close < 171.90",
        threshold=None,
        evidence_basis=basis,
        invalidates="the bullish trend thesis",
    )


def _scenario(name, weight=None, evidence="", triggers="", invalidation=""):
    return S.Scenario(
        name=name,
        weight=weight,
        supporting_evidence=evidence or f"{name.value} evidence",
        trigger_conditions=triggers or f"{name.value} trigger",
        invalidation_conditions=invalidation or f"{name.value} invalidation",
    )


def _estimated_market():
    return S.MarketAnalystReport(
        stance=S.AnalystStance.MILDLY_BULLISH,
        invalidation=[_invalidation()],
        scenario_set=S.ScenarioSet(
            status=S.ScenarioStatus.ESTIMATED,
            scenarios=[
                _scenario(S.ScenarioType.BULL, 50),
                _scenario(S.ScenarioType.BASE, 30),
                _scenario(S.ScenarioType.BEAR, 20),
            ],
        ),
    )


def _not_estimable_market():
    return S.MarketAnalystReport(
        stance=S.AnalystStance.NEUTRAL,
        invalidation=[_invalidation()],
        scenario_set=S.ScenarioSet(
            status=S.ScenarioStatus.NOT_ESTIMABLE,
            scenarios=[
                _scenario(S.ScenarioType.BULL),
                _scenario(S.ScenarioType.BEAR),
            ],
        ),
    )


def _fundamentals_with_levels():
    report = S.FundamentalsAnalystReport(
        stance=S.AnalystStance.BULLISH,
        key_figures=[S.FundamentalFact(metric="Revenue", value="46.7B (Q2)", read="grew 12%")],
        invalidation=[_invalidation("Gross margin falls below 70%", "income statement")],
        scenario_set=S.ScenarioSet(
            status=S.ScenarioStatus.ESTIMATED,
            scenarios=[
                _scenario(S.ScenarioType.BULL, 40, evidence="AI capex stays strong"),
                _scenario(S.ScenarioType.BEAR, 25, triggers="hyperscaler capex cuts"),
            ],
        ),
    )
    return report


class _FakeToolResult:
    """Minimal AIMessage stand-in for an analyst that stopped calling tools."""

    tool_calls: list = []

    def __init__(self, content="Final analysis."):
        self.content = content


class _SpeakingLLM:
    def __init__(self, content="my argument"):
        self.content = content
        self.prompts: list[str] = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return _FakeToolResult(self.content)


class _ReportObjStateMixin:
    """State with the four report strings and the two optional typed keys."""

    @staticmethod
    def state(*, market_obj=None, fundamentals_obj=None, include_obj_keys=True):
        state = {
            "investment_debate_state": {
                "history": "",
                "bull_history": "",
                "bear_history": "",
                "current_response": "",
                "count": 0,
            },
            "risk_debate_state": {
                "history": "",
                "aggressive_history": "",
                "conservative_history": "",
                "neutral_history": "",
                "current_aggressive_response": "",
                "current_conservative_response": "",
                "current_neutral_response": "",
                "count": 0,
            },
            "market_report": "MARKET PROSE",
            "sentiment_report": "SENTIMENT PROSE",
            "news_report": "NEWS PROSE",
            "fundamentals_report": "FUNDAMENTALS PROSE",
            "trader_investment_plan": "TRADER PLAN",
            "company_of_interest": "NVDA",
            "asset_type": "stock",
        }
        if include_obj_keys:
            state["market_report_obj"] = market_obj
            state["fundamentals_report_obj"] = fundamentals_obj
        return state


# --------------------------------------------------------------------------- #
# 1. router unit behaviour
# --------------------------------------------------------------------------- #
def _joined(routed: dict[str, str]) -> str:
    """All routed blocks as one string, for text-presence assertions."""
    return "\n\n".join(routed.values())


class RouterUnitTest(unittest.TestCase):
    def test_routers_return_a_source_mapping(self):
        for router in (bull_context_block, bear_context_block, risk_context_block):
            with self.subTest(router=router.__name__):
                routed = router(_estimated_market(), _fundamentals_with_levels())
                self.assertIsInstance(routed, dict)
                self.assertEqual(set(routed), {"market", "fundamentals"})

    def test_only_sources_with_typed_fields_are_in_the_mapping(self):
        for router in (bull_context_block, bear_context_block, risk_context_block):
            with self.subTest(router=router.__name__):
                self.assertEqual(set(router(_estimated_market(), None)), {"market"})
                self.assertEqual(
                    set(router(None, _fundamentals_with_levels())), {"fundamentals"}
                )

    def test_each_block_has_only_its_own_source_heading(self):
        routed = bull_context_block(_estimated_market(), _fundamentals_with_levels())
        self.assertIn("#### From the market report", routed["market"])
        self.assertNotIn("#### From the fundamentals report", routed["market"])
        self.assertIn("#### From the fundamentals report", routed["fundamentals"])
        self.assertNotIn("#### From the market report", routed["fundamentals"])

    def test_no_object_means_no_block(self):
        self.assertEqual(bull_context_block(None, None), {})
        self.assertEqual(bear_context_block(None, None), {})
        self.assertEqual(risk_context_block(None, None), {})
        self.assertFalse(has_s2_fields(None))

    def test_report_without_s2_data_means_no_block(self):
        empty = S.MarketAnalystReport(stance=S.AnalystStance.NEUTRAL)
        self.assertFalse(has_s2_fields(empty))
        self.assertEqual(bull_context_block(empty, None), {})

    def test_not_estimable_never_prints_a_number(self):
        block = _joined(bull_context_block(_not_estimable_market(), None))
        self.assertNotIn("%", block)
        self.assertNotIn("33.3", block)
        self.assertIn("not estimable", block.lower())
        self.assertIn("Do not assume an equal split", block)

    def test_estimated_weights_are_shown_verbatim(self):
        block = _joined(bull_context_block(_estimated_market(), None))
        self.assertIn("Bull 50%", block)
        self.assertIn("Base 30%", block)
        self.assertIn("Bear 20%", block)

    def test_out_of_range_weight_drops_the_whole_set(self):
        # 150 is impossible; the renderer drops it, so the router must too and
        # must not silently rescale the remaining 20%.
        report = S.MarketAnalystReport(
            stance=S.AnalystStance.NEUTRAL,
            scenario_set=S.ScenarioSet(
                status=S.ScenarioStatus.ESTIMATED,
                scenarios=[
                    _scenario(S.ScenarioType.BULL, 150),
                    _scenario(S.ScenarioType.BEAR, 20),
                ],
            ),
        )
        block = _joined(bull_context_block(report, None))
        self.assertNotIn("150", block)
        self.assertIn("not estimable", block.lower())

    def test_invalidation_is_never_presented_as_a_stop_loss(self):
        block = _joined(bull_context_block(_estimated_market(), None))
        self.assertIn("Invalidation conditions", block)
        self.assertIn("not stop-losses", block)

    def test_stated_threshold_is_quoted_and_missing_one_is_not_invented(self):
        block = _joined(bull_context_block(_estimated_market(), None))
        # threshold is None on the fixture: the block must say so explicitly
        self.assertIn("no numeric threshold stated", block)

    def test_bull_and_bear_receive_different_scenarios(self):
        bull = _joined(bull_context_block(_estimated_market(), None))
        bear = _joined(bear_context_block(_estimated_market(), None))
        self.assertIn("Bull scenario", bull)
        self.assertNotIn("Bear scenario", bull)
        self.assertIn("Bear scenario", bear)
        self.assertNotIn("Bull scenario", bear)

    def test_risk_block_carries_levels_triggers_and_downside(self):
        block = _joined(risk_context_block(None, _fundamentals_with_levels()))
        self.assertIn("Bear (downside) scenario", block)
        self.assertIn("Scenario risk triggers", block)
        self.assertIn("hyperscaler capex cuts", block)

    def test_routed_report_returns_full_text_when_block_is_falsy(self):
        for full, block in (
            ("MARKET PROSE", None),
            ("MARKET PROSE", ""),
            ("", None),
            ("(No market report in this run: it is not available, not an empty finding.)", ""),
        ):
            with self.subTest(full=full, block=block):
                self.assertIs(routed_report(full, block, "market"), full)

    def test_routed_report_substitutes_the_block_when_present(self):
        full = "MARKET PROSE " * 1000
        block = "\n\n#### From the market report\nBull scenario: x\n\n"
        out = routed_report(full, block, "market")
        self.assertEqual(out, block.strip())
        self.assertNotIn("MARKET PROSE", out)


# --------------------------------------------------------------------------- #
# 2. consumers actually read the typed fields
# --------------------------------------------------------------------------- #
class SharedContextTest(unittest.TestCase):
    """Audit W1: substitution must not drop key evidence.

    ``routed_report`` REPLACES the full report with the routed block, so every
    item that lived in the full report (stance, key evidence, risks, figures,
    interpretation) has to be carried by the block itself or it is lost.
    """

    SHARED_MARKET_EVIDENCE = S.EvidenceItem(
        claim="RSI is overbought",
        evidence="78.4 on 2026-11-06",
        source="get_indicators: rsi",
    )
    SHARED_MARKET_RESEARCH = S.EvidenceItem(
        claim="Price above the 50-day average",
        evidence="close 182.10 vs close_50_sma 171.90",
        source="get_indicators: close_50_sma",
    )
    MARKET_INTERPRETATION = "Trend intact while momentum cools; a close below the average voids it."
    MARKET_RISK = "Momentum divergence on declining volume"
    LEVEL_RESISTANCE = S.PriceLevel(label="Resistance", price="186.40", why="prior swing high")
    LEVEL_SUPPORT = S.PriceLevel(label="Support", price="171.90", why="50-day SMA")

    def _market(self):
        return S.MarketAnalystReport(
            stance=S.AnalystStance.MILDLY_BULLISH,
            key_evidence=[self.SHARED_MARKET_EVIDENCE, self.SHARED_MARKET_RESEARCH],
            key_levels=[self.LEVEL_RESISTANCE, self.LEVEL_SUPPORT],
            risks=[self.MARKET_RISK],
            invalidation=[_invalidation()],
            scenario_set=S.ScenarioSet(
                status=S.ScenarioStatus.ESTIMATED,
                scenarios=[
                    _scenario(S.ScenarioType.BULL, 50),
                    _scenario(S.ScenarioType.BASE, 30),
                    _scenario(S.ScenarioType.BEAR, 20),
                ],
            ),
            interpretation=self.MARKET_INTERPRETATION,
        )

    ROUTERS = (bull_context_block, bear_context_block, risk_context_block)
    CONSUMERS = (
        create_bull_researcher,
        create_bear_researcher,
        create_aggressive_debator,
        create_conservative_debator,
        create_neutral_debator,
    )

    def test_substitution_preserves_evidence_risks_interpretation_and_stance(self):
        market_obj = self._market()
        for factory in self.CONSUMERS:
            with self.subTest(consumer=factory.__name__):
                llm = _SpeakingLLM()
                factory(llm)(_ReportObjStateMixin.state(market_obj=market_obj))
                prompt = llm.prompts[0]
                # The full report was substituted away...
                self.assertNotIn("MARKET PROSE", prompt)
                # ...so the essential context must be in the block, verbatim.
                self.assertIn("**Stance:** Mildly Bullish", prompt)
                self.assertIn("**Key evidence:**", prompt)
                self.assertIn("RSI is overbought — 78.4 on 2026-11-06 (get_indicators: rsi)", prompt)
                self.assertIn(
                    "Price above the 50-day average — close 182.10 vs close_50_sma 171.90 "
                    "(get_indicators: close_50_sma)",
                    prompt,
                )
                self.assertIn("**Risks:**", prompt)
                self.assertIn(self.MARKET_RISK, prompt)
                self.assertIn(self.MARKET_INTERPRETATION, prompt)

    def test_fundamentals_key_figures_survive_routing(self):
        fund_obj = _fundamentals_with_levels()
        for factory in self.CONSUMERS:
            with self.subTest(consumer=factory.__name__):
                llm = _SpeakingLLM()
                factory(llm)(_ReportObjStateMixin.state(fundamentals_obj=fund_obj))
                prompt = llm.prompts[0]
                self.assertNotIn("FUNDAMENTALS PROSE", prompt)
                self.assertIn("**Key figures:**", prompt)
                self.assertIn("Revenue: 46.7B (Q2) — grew 12%", prompt)

    def test_bull_and_bear_blocks_include_key_levels(self):
        market_obj = self._market()
        for router in (bull_context_block, bear_context_block):
            with self.subTest(router=router.__name__):
                block = router(market_obj, None)["market"]
                self.assertIn("Key levels (price structure, not thesis invalidation):", block)
                self.assertIn("Resistance: 186.40 (prior swing high)", block)
                self.assertIn("Support: 171.90 (50-day SMA)", block)

    def test_each_block_carries_key_levels_exactly_once(self):
        market_obj = self._market()
        for router in self.ROUTERS:
            with self.subTest(router=router.__name__):
                block = router(market_obj, None)["market"]
                self.assertEqual(block.count("Key levels (price structure"), 1)
                self.assertEqual(block.count("Resistance: 186.40"), 1)

    def test_risks_are_omitted_when_the_analyst_stated_none(self):
        report = S.MarketAnalystReport(
            stance=S.AnalystStance.NEUTRAL,
            invalidation=[_invalidation()],
        )
        block = _joined(bull_context_block(report, None))
        self.assertNotIn("**Risks:**", block)

    def test_inconsistent_weights_are_not_presented_as_an_estimate(self):
        # 60 + 60 + 30 = 150. The set is complete and every weight is in range,
        # so before the fix it printed as "analyst estimate".
        report = S.MarketAnalystReport(
            stance=S.AnalystStance.NEUTRAL,
            invalidation=[_invalidation()],
            scenario_set=S.ScenarioSet(
                status=S.ScenarioStatus.ESTIMATED,
                scenarios=[
                    _scenario(S.ScenarioType.BULL, 60),
                    _scenario(S.ScenarioType.BASE, 60),
                    _scenario(S.ScenarioType.BEAR, 30),
                ],
            ),
        )
        block = _joined(bull_context_block(report, None))
        self.assertNotIn("analyst estimate", block)
        self.assertNotIn("Bull 60%", block)
        self.assertNotIn("Base 60%", block)
        self.assertNotIn("Bear 30%", block)
        self.assertIn("do not sum to 100%", block)
        self.assertIn("Do not read them as probabilities", block)
        self.assertIn("do not rescale them", block)

    def test_weights_summing_to_100_still_print_normally(self):
        report = S.MarketAnalystReport(
            stance=S.AnalystStance.NEUTRAL,
            invalidation=[_invalidation()],
            scenario_set=S.ScenarioSet(
                status=S.ScenarioStatus.ESTIMATED,
                scenarios=[
                    _scenario(S.ScenarioType.BULL, 50),
                    _scenario(S.ScenarioType.BASE, 30),
                    _scenario(S.ScenarioType.BEAR, 20),
                ],
            ),
        )
        block = _joined(bull_context_block(report, None))
        self.assertIn("Scenario weights (analyst estimate): Bull 50%, Base 30%, Bear 20%.", block)
        self.assertNotIn("do not sum to 100%", block)

    def test_weights_within_tolerance_still_print(self):
        report = S.MarketAnalystReport(
            stance=S.AnalystStance.NEUTRAL,
            invalidation=[_invalidation()],
            scenario_set=S.ScenarioSet(
                status=S.ScenarioStatus.ESTIMATED,
                scenarios=[
                    _scenario(S.ScenarioType.BULL, 50.5),
                    _scenario(S.ScenarioType.BASE, 30),
                    _scenario(S.ScenarioType.BEAR, 20),
                ],
            ),
        )
        block = _joined(bull_context_block(report, None))
        self.assertIn("analyst estimate", block)
        self.assertIn("Bull 50.5%", block)


# --------------------------------------------------------------------------- #
# 2. consumers actually read the typed fields
# --------------------------------------------------------------------------- #
class ConsumerWiringTest(_ReportObjStateMixin, unittest.TestCase):
    def test_bull_reads_bull_scenario_and_invalidation(self):
        llm = _SpeakingLLM()
        create_bull_researcher(llm)(
            self.state(market_obj=_estimated_market())
        )
        prompt = llm.prompts[0]
        self.assertIn("From the market report", prompt)
        self.assertIn("Bull scenario", prompt)
        self.assertIn("Weekly close below the 50-day average", prompt)
        self.assertIn("Bull 50%", prompt)

    def test_bear_reads_bear_scenario_and_invalidation(self):
        llm = _SpeakingLLM()
        create_bear_researcher(llm)(
            self.state(market_obj=_estimated_market())
        )
        prompt = llm.prompts[0]
        self.assertIn("From the market report", prompt)
        self.assertIn("Bear scenario", prompt)
        self.assertIn("Weekly close below the 50-day average", prompt)

    def test_risk_analysts_read_invalidation_and_downside(self):
        for factory in (
            create_aggressive_debator,
            create_conservative_debator,
            create_neutral_debator,
        ):
            with self.subTest(factory=factory.__name__):
                llm = _SpeakingLLM()
                factory(llm)(
                    self.state(fundamentals_obj=_fundamentals_with_levels())
                )
                prompt = llm.prompts[0]
                self.assertIn("From the fundamentals report", prompt)
                self.assertIn("Gross margin falls below 70%", prompt)
                self.assertIn("Bear (downside) scenario", prompt)

    def test_bull_and_bear_do_not_receive_the_same_block(self):
        bull_llm, bear_llm = _SpeakingLLM(), _SpeakingLLM()
        create_bull_researcher(bull_llm)(self.state(market_obj=_estimated_market()))
        create_bear_researcher(bear_llm)(self.state(market_obj=_estimated_market()))
        self.assertNotEqual(bull_llm.prompts[0], bear_llm.prompts[0])


class SubstitutionTest(_ReportObjStateMixin, unittest.TestCase):
    """Routed fields REPLACE the full report; they are not appended to it.

    Appending was the defect: new S2 cost more input tokens than old S2 and the
    consumer still read the prose routing was meant to replace.
    """

    CONSUMERS = (
        ("bull", create_bull_researcher, bull_context_block),
        ("bear", create_bear_researcher, bear_context_block),
        ("aggressive", create_aggressive_debator, risk_context_block),
        ("conservative", create_conservative_debator, risk_context_block),
        ("neutral", create_neutral_debator, risk_context_block),
    )

    def test_typed_market_fields_replace_the_market_report(self):
        market_obj = _estimated_market()
        for name, factory, router in self.CONSUMERS:
            with self.subTest(consumer=name):
                llm = _SpeakingLLM()
                factory(llm)(self.state(market_obj=market_obj))
                prompt = llm.prompts[0]
                block = router(market_obj, None)["market"]
                self.assertNotIn("MARKET PROSE", prompt)
                self.assertIn(block, prompt)
                # The other source has no typed fields: unchanged full report.
                self.assertIn("FUNDAMENTALS PROSE", prompt)

    def test_typed_fundamentals_fields_replace_the_fundamentals_report(self):
        fund_obj = _fundamentals_with_levels()
        for name, factory, router in self.CONSUMERS:
            with self.subTest(consumer=name):
                llm = _SpeakingLLM()
                factory(llm)(self.state(fundamentals_obj=fund_obj))
                prompt = llm.prompts[0]
                block = router(None, fund_obj)["fundamentals"]
                self.assertNotIn("FUNDAMENTALS PROSE", prompt)
                self.assertIn(block, prompt)
                self.assertIn("MARKET PROSE", prompt)

    def test_both_sources_typed_replace_both_reports(self):
        market_obj, fund_obj = _estimated_market(), _fundamentals_with_levels()
        for name, factory, router in self.CONSUMERS:
            with self.subTest(consumer=name):
                llm = _SpeakingLLM()
                factory(llm)(self.state(market_obj=market_obj, fundamentals_obj=fund_obj))
                prompt = llm.prompts[0]
                routed = router(market_obj, fund_obj)
                self.assertNotIn("MARKET PROSE", prompt)
                self.assertNotIn("FUNDAMENTALS PROSE", prompt)
                self.assertIn(routed["market"], prompt)
                self.assertIn(routed["fundamentals"], prompt)
                self.assertIn("SENTIMENT PROSE", prompt)
                self.assertIn("NEWS PROSE", prompt)

    def test_prompt_is_shorter_than_the_append_baseline(self):
        # Token-negative: the routed prompt must be strictly shorter than the
        # old "full report + block appended after it" baseline.
        market_obj = _estimated_market()
        routed_llm = _SpeakingLLM()
        create_bull_researcher(routed_llm)(self.state(market_obj=market_obj))

        baseline = self.state()
        baseline["market_report_obj"] = None
        baseline_llm = _SpeakingLLM()
        create_bull_researcher(baseline_llm)(baseline)
        appended = baseline_llm.prompts[0] + "\n\n" + bull_context_block(
            market_obj, None
        )["market"]

        self.assertLess(len(routed_llm.prompts[0]), len(appended))

    def test_absent_full_report_still_gets_typed_fields(self):
        # report_or_absent runs FIRST; a typed block still replaces its placeholder.
        market_obj = _estimated_market()
        for name, factory, router in self.CONSUMERS:
            with self.subTest(consumer=name):
                state = self.state(market_obj=market_obj)
                state["market_report"] = ""
                llm = _SpeakingLLM()
                factory(llm)(state)
                prompt = llm.prompts[0]
                self.assertNotIn("(No market report in this run", prompt)
                self.assertIn(router(market_obj, None)["market"], prompt)


class FallbackTest(_ReportObjStateMixin, unittest.TestCase):
    """No typed fields for a source -> that source's full report, as before."""

    CONSUMERS = (
        ("bull", create_bull_researcher),
        ("bear", create_bear_researcher),
        ("aggressive", create_aggressive_debator),
        ("conservative", create_conservative_debator),
        ("neutral", create_neutral_debator),
    )

    def test_full_reports_survive_when_no_typed_fields_exist(self):
        for name, factory in self.CONSUMERS:
            with self.subTest(consumer=name):
                llm = _SpeakingLLM()
                factory(llm)(self.state())
                prompt = llm.prompts[0]
                self.assertIn("MARKET PROSE", prompt)
                self.assertIn("FUNDAMENTALS PROSE", prompt)
                self.assertNotIn("#### From the", prompt)
                self.assertNotIn("Typed S2 fields", prompt)

    def test_report_without_s2_data_falls_back_to_full_report(self):
        empty = S.MarketAnalystReport(stance=S.AnalystStance.NEUTRAL)
        self.assertFalse(has_s2_fields(empty))
        for name, factory in self.CONSUMERS:
            with self.subTest(consumer=name):
                llm = _SpeakingLLM()
                factory(llm)(self.state(market_obj=empty))
                prompt = llm.prompts[0]
                self.assertIn("MARKET PROSE", prompt)
                self.assertIn("FUNDAMENTALS PROSE", prompt)
                self.assertNotIn("#### From the", prompt)


# --------------------------------------------------------------------------- #
# 3. backward compatibility — prose-only / old-S2 path is untouched
# --------------------------------------------------------------------------- #
class BackwardCompatibilityTest(_ReportObjStateMixin, unittest.TestCase):
    def test_old_state_without_obj_keys_does_not_raise(self):
        for factory in (
            create_bull_researcher,
            create_bear_researcher,
            create_aggressive_debator,
            create_conservative_debator,
            create_neutral_debator,
        ):
            with self.subTest(factory=factory.__name__):
                llm = _SpeakingLLM()
                factory(llm)(self.state(include_obj_keys=False))
                self.assertNotIn("#### From the", llm.prompts[0])

    def test_none_object_adds_nothing_to_the_prompt(self):
        # The prompt with an explicit None must be byte-identical to the prompt
        # from a state that never had the key at all.
        with_key = _SpeakingLLM()
        create_bull_researcher(with_key)(self.state(market_obj=None))
        without_key = _SpeakingLLM()
        create_bull_researcher(without_key)(self.state(include_obj_keys=False))
        self.assertEqual(with_key.prompts[0], without_key.prompts[0])

    def test_prompt_keeps_its_existing_report_sections(self):
        # Strengthened for routing: the typed source is replaced by its block,
        # every other source keeps its full report.
        llm = _SpeakingLLM()
        create_bull_researcher(llm)(self.state(market_obj=_estimated_market()))
        prompt = llm.prompts[0]
        self.assertNotIn("MARKET PROSE", prompt)
        self.assertIn("#### From the market report", prompt)
        self.assertIn("FUNDAMENTALS PROSE", prompt)
        self.assertIn("SENTIMENT PROSE", prompt)
        self.assertIn("NEWS PROSE", prompt)


if __name__ == "__main__":
    unittest.main()
