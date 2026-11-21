"""ADR-011 amendment (2026-11-12): confidence suffix token/sentence boundaries.

Approved plan + test cases (human WANG Yiwen, 2026-11-12; implementation approval
ONLY, NOT final human acceptance). These pin the DEFECT-1 repair: the suffix
confidence grammar must respect structural numeric/sentence boundaries so an
ordinary price/date is byte-for-byte unchanged, while a GENUINE confidence
(including a soft-wrapped one) is still capped/quarantined per the 0.60 contract.

Confirmed live defect (reproduced offline):
    in : "Re-entry requires a close above $204.38. Confidence is set at the
          plan's 0.55."
    bad: "... $204.unknown (invalid confidence quarantined) Confidence ..."
    fix: "$204.38." stays byte-for-byte; the true 0.55 is within cap.

Key rules pinned here:
- a numeric literal never absorbs a trailing sentence period;
- a sentence terminator (``. ! ? ;``) is a boundary, not a connector;
- soft vertical whitespace (LF or CRLF) still binds a genuine suffix;
- a date/sign/path/currency-glued numeric is NOT a confidence candidate
  (``$204.38`` / ``2026-11-05`` / ``2026/11/05`` fragments never match);
- a bare ``204.38 confidence`` (no currency, no ``%``) stays INVALID/quarantined
  (not blanket-exempted as a "price").

No network, no paid LLM.

Traceability: NFR-AUD-001, NFR-BC-001, NFR-DET-001, INV-6.
"""

from __future__ import annotations

import pytest

from tradingagents.debate.confidence_policy import (
    QUARANTINE_MARKER,
    REASON_CAPPED,
    REASON_INVALID,
    cap_agent_text,
    rewrite_confidence_text,
)

DEGRADED = "degraded"


def _rewrite(text: str) -> tuple[str, list]:
    return rewrite_confidence_text(text, DEGRADED)


class TestExactLiveReproduction:
    def test_price_preserved_true_confidence_within_cap(self):
        # The exact live REVIEW input: price byte-identical, no audit entry (the
        # genuine 0.55 is within cap and is not suffix-labelled on the price).
        text = (
            "Re-entry requires a close above $204.38. Confidence is set at the "
            "plan's 0.55."
        )
        out, audit = _rewrite(text)
        assert out == text
        assert "$204.38." in out
        assert "204.unknown" not in out
        assert audit == []

    def test_price_corruption_negative_pin(self):
        # The old bug's corruption marker must never reappear for this input.
        out, _ = _rewrite("Re-entry requires a close above $204.38. Confidence is set at the plan's 0.55.")
        assert "invalid confidence quarantined" not in out


class TestSentenceNewlineBoundary:
    @pytest.mark.parametrize(
        "text",
        [
            "$204.38. Confidence: 0.95",
            "$204.38.\nConfidence: 0.95",
            "$204.38.\r\nConfidence: 0.95",
        ],
    )
    def test_price_intact_only_labelled_capped(self, text):
        out, audit = _rewrite(text)
        assert "$204.38." in out
        assert "204.unknown" not in out
        assert "0.95" not in out
        assert "0.6" in out
        assert any(a["reason"] == REASON_CAPPED for a in audit)

    def test_terminator_is_not_a_connector(self):
        # 0.95 followed by a terminator then the label: 0.95 is NOT that suffix.
        out, audit = _rewrite("The result was 0.95.\nconfidence is high")
        assert out == "The result was 0.95.\nconfidence is high"
        assert audit == []


class TestCurrencyAndDateFiguresUnchanged:
    @pytest.mark.parametrize(
        "text",
        [
            "$204.38",
            "$1,234.56",
            "€1.234,56",
            "As of 2026-11-05 confidence: 0.55",
            "As of 2026/11/05 confidence: 0.55",
            "close 200.13 on 2026-05-04 confidence: 0.55",
        ],
    )
    def test_currency_and_date_not_matched(self, text):
        out, audit = _rewrite(text)
        # The price/date portion is byte-identical and never quarantined.
        assert "unknown (invalid confidence quarantined)" not in out
        # A genuine labelled value that IS within cap stays unchanged too.
        if "0.55" in text:
            assert out == text
            assert audit == []

    def test_slash_date_fragment_not_corrupted(self):
        out, _ = _rewrite("As of 2026/11/05 we hold; confidence: 0.95")
        assert "2026/11/05" in out
        assert "unknown" not in out
        # The genuine labelled 0.95 is still capped.
        assert "0.95" not in out and "0.6" in out


class TestBareNumericInvalidNotExempted:
    def test_bare_decimal_gt1_confidence_still_quarantined(self):
        # Contract preserved: bare 204.38 (no currency, no %) -> invalid labelled.
        out, audit = _rewrite("204.38 confidence")
        assert QUARANTINE_MARKER in out
        assert any(a["reason"] == REASON_INVALID and a.get("quarantined") for a in audit)

    def test_currency_glued_price_is_ordinary(self):
        out, audit = _rewrite("$204.38 confidence")
        assert out == "$204.38 confidence"
        assert audit == []

    def test_medium_large_bare_still_quarantined(self):
        out, _ = _rewrite("300.5 confidence")
        assert QUARANTINE_MARKER in out


class TestSoftWrapGenuineCap:
    @pytest.mark.parametrize(
        "text",
        [
            "0.95\nconfidence",
            "0.95\n confidence",
            "0.95\r\nconfidence",
            "0.95\r\n confidence",
        ],
    )
    def test_soft_wrap_binds_and_caps(self, text):
        out, audit = _rewrite(text)
        assert "0.95" not in out
        assert "0.6" in out
        assert any(a["reason"] == REASON_CAPPED for a in audit)

    def test_double_newline_not_a_soft_wrap(self):
        out, _ = _rewrite("0.95\n\nconfidence")
        assert out == "0.95\n\nconfidence"


class TestPreservedForms:
    @pytest.mark.parametrize(
        "text,expect",
        [
            ("Confidence: 95%", "Confidence: 60%"),
            ("confidence of 0.95", "confidence of 0.6"),
            ("95% confidence", "60% confidence"),
            ("0.95 confidence", "0.6 confidence"),
            ("**Confidence:** 0.95", "**Confidence:** 0.6"),
            ('"confidence": 0.95', '"confidence": 0.6'),
            ("Confidence: ０.９５", "Confidence: 0.6"),
            ("Confidence: ９５％", "Confidence: 60%"),
            ("confidence of 9.5e-1", "confidence of 0.6"),
            ("Confidence: +0.95", "Confidence: 0.6"),
        ],
    )
    def test_genuine_forms_capped(self, text, expect):
        out, _ = _rewrite(text)
        assert out == expect

    @pytest.mark.parametrize(
        "text",
        [
            "Confidence: 0.55 and 60% confidence",
            "confidence is 0.60",
            "-0.95 confidence",  # negative out of [0,1] -> quarantined, not capped
        ],
    )
    def test_within_cap_or_invalid_unchanged_or_quarantine(self, text):
        out, audit = _rewrite(text)
        if "confidence is 0.60" in text:
            assert out == text and audit == []
        elif "-0.95" in text:
            assert QUARANTINE_MARKER in out
        else:
            assert "0.55" in out and "60%" in out and audit == []


class TestInvalidQuarantinePreserved:
    @pytest.mark.parametrize(
        "text",
        [
            "Confidence: 95",
            "Confidence: 9e-1x",
            "Confidence: 0.9foo",
            "Confidence: NaN",
            "confidence: true",
            "confidence: null",
        ],
    )
    def test_malformed_labelled_still_quarantined(self, text):
        out, audit = _rewrite(text)
        assert QUARANTINE_MARKER in out
        assert any(a["reason"] == REASON_INVALID and a.get("quarantined") for a in audit)


class TestIdempotenceAndVerdicts:
    def test_double_apply_identical(self):
        text = "close above $204.38. Confidence: 0.95 and 95% confidence"
        once, _ = _rewrite(text)
        twice, audit2 = _rewrite(once)
        assert once == twice
        assert audit2 == []

    @pytest.mark.parametrize("verdict", ["normal", "blocked"])
    def test_non_degraded_unchanged(self, verdict):
        text = "close above $204.38; confidence: 0.95"
        out, audit = rewrite_confidence_text(text, verdict)
        assert out == text
        assert audit == []


class TestZeroCollateralCorpus:
    @pytest.mark.parametrize(
        "text",
        [
            "Open 196.07, High 196.25, Low 181.46, Close 181.60 on 2026-11-05.",
            "200-SMA 204.38 and 50-SMA 220.59; volume 306.1 million.",
            "Margin 0.31, return 12%, position 200 shares, entry 189.5.",
            "Receivables +55% QoQ vs revenue +17.9%; DSO ~39 to ~59 days.",
            "Filed 2026-11-05; observation 2026/11/05; 9.5e-1 beta.",
        ],
    )
    def test_ordinary_figures_byte_identical(self, text):
        out, audit = _rewrite(text)
        assert out == text
        assert audit == []


class TestRealBoundaryPropagation:
    def test_trader_plan_and_report_preserve_price_cap_genuine(self, tmp_path):
        from pathlib import Path

        from tradingagents.reporting import write_report_tree

        plan = (
            "Re-entry requires a close above $204.38. Confidence is set at the "
            "plan's 0.55. On a degraded run the conviction ceiling is 0.60; the "
            "raw long-term view is 0.95 confidence."
        )
        state = {
            "data_quality_verdict": "degraded",
            "data_quality_gate_decision": {
                "decision": "degraded",
                "decided_at": "2026-05-13T12:00:00Z",
            },
            "company_of_interest": "NVDA",
            "trade_date": "2026-11-05",
            "trader_investment_plan": plan,
            "market_report": "",
            "sentiment_report": "",
            "news_report": "",
            "fundamentals_report": "",
            "investment_plan": "",
            "final_trade_decision": "",
            "investment_debate_state": {
                "history": "", "bull_history": "", "bear_history": "",
                "current_response": "", "judge_decision": "",
            },
            "risk_debate_state": {
                "history": "", "aggressive_history": "",
                "conservative_history": "", "neutral_history": "",
                "current_aggressive_response": "",
                "current_conservative_response": "",
                "current_neutral_response": "", "judge_decision": "",
            },
        }
        # Agent-boundary cap (the Trader node's own rewrite).
        capped, _ = cap_agent_text(
            plan, state, source="Trader", boundary="agent:Trader:trader_plan",
        )
        # Price byte-identical, only the genuine 0.95 confidence capped.
        assert "$204.38." in capped
        assert "204.unknown" not in capped
        assert "0.95" not in capped
        assert "0.55" in capped

        # Report boundary independently recomputes the same effective value.
        final = dict(state)
        final["trader_investment_plan"] = plan
        write_report_tree(final, "NVDA", tmp_path / "run")
        trader_md = (Path(tmp_path) / "run" / "3_trading" / "trader.md").read_text(
            encoding="utf-8"
        )
        complete = (Path(tmp_path) / "run" / "complete_report.md").read_text(
            encoding="utf-8"
        )
        for body in (trader_md, complete):
            assert "$204.38." in body
            assert "204.unknown" not in body
        # Report and agent boundary agree on the capped value.
        assert "0.95" not in trader_md


class TestRealTraderNodePropagation:
    def _mock_llm(self, content):
        from langchain_core.messages import AIMessage
        from langchain_core.runnables import RunnableLambda

        class _Mock:
            def __init__(self, content):
                self.content = content
                self.with_structured_output = lambda *a, **k: None
                self.bind_tools = lambda tools: RunnableLambda(
                    lambda m: AIMessage(content=self.content, tool_calls=[])
                )

            def invoke(self, prompt):
                return AIMessage(content=self.content)

        return _Mock(content)

    def test_trader_node_preserves_price_caps_genuine(self):
        from tradingagents.agents.trader.trader import create_trader

        # The model output reproduces the live price-corruption input shape plus a
        # genuine over-cap labelled confidence.
        model_text = (
            "**Action**: Hold\n\n**Reasoning**: Re-entry requires a close above "
            "$204.38. Confidence is set at the plan's 0.55. Long-term conviction is "
            "0.95 confidence.\n\n**Entry Price**: not applicable\n"
        )
        state = {
            "data_quality_verdict": "degraded",
            "data_quality_gate_decision": {
                "decision": "degraded", "decided_at": "2026-11-05T12:00:00Z",
            },
            "company_of_interest": "NVDA",
            "trade_date": "2026-11-05",
            "investment_plan": "Hold until confirmed.",
            "market_report": "",
            "portfolio_context": "",
        }
        node = create_trader(self._mock_llm(model_text))
        result = node(state)
        plan = result["trader_investment_plan"]
        # Price byte-identical (not corrupted); genuine 0.95 confidence capped.
        assert "$204.38." in plan
        assert "204.unknown" not in plan
        assert "0.95 confidence" not in plan
        assert "0.6 confidence" in plan
        assert "0.55" in plan


class TestRealMemoryBoundary:
    def _mock_graph(self, config):
        # Bypass the heavy __init__; only record_decision/_is_blocked_state are used.
        import types

        from tradingagents.agents.utils.memory import TradingMemoryLog
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
        graph.config = config
        graph.memory_log = TradingMemoryLog(config)
        graph._is_blocked_state = types.MethodType(
            lambda self, s: False, graph
        )
        return graph

    def test_record_decision_preserves_price_caps_genuine(self, tmp_path):
        graph = self._mock_graph({"memory_log_path": str(tmp_path / "mem.md"), "results_dir": str(tmp_path)})
        final_state = {
            "data_quality_verdict": "degraded",
            "data_quality_gate_decision": {
                "decision": "degraded", "decided_at": "2026-11-05T12:00:00Z",
            },
            "company_of_interest": "NVDA",
            "trade_date": "2026-11-05",
            "final_trade_decision": (
                "**Action**: Hold\n\nReasoning: wait for a close above $204.38; "
                "conviction 0.95 confidence, plan confidence 0.55."
            ),
        }
        graph.record_decision("NVDA", "2026-11-05", final_state)
        entries = graph.memory_log.load_entries()
        body = "\n".join(str(e) for e in entries)
        assert "$204.38" in body
        assert "204.unknown" not in body
        assert "0.95 confidence" not in body
