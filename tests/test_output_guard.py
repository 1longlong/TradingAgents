"""Offline regressions for the centralized data-quality output guard.

Reproduces the 2026-11-06 review finding: on a *blocked* Data Quality Gate run
the Research Manager correctly rewrites its recommendation to Hold, yet the
Trader -> risk debate -> Portfolio Manager path could still carry a model Buy
into ``final_trade_decision`` and the signal processor would report Buy.

The gate verdict is authoritative. No Buy / Sell / Overweight / Underweight may
remain as an executable recommendation or rating on a blocked run, on either the
structured or the free-text rendering path, while the evidence-insufficient
explanation and recovery conditions the model wrote are preserved.

All fixtures are deterministic: fixed snapshots, fake LLMs, no network.

Traceability: FR-DQG-006 (authoritative blocked verdict at the output boundary);
supports INV-1 (fail closed) and the multiline containment recorded in ADR-005.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langgraph.prebuilt import ToolNode

import tradingagents.dataflows.market_data_validator as validator
from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager
from tradingagents.agents.managers.research_manager import create_research_manager
from tradingagents.agents.schemas import (
    PortfolioDecision,
    PortfolioRating,
    ResearchPlan,
    TraderAction,
    TraderProposal,
    render_pm_decision,
    render_research_plan,
    render_trader_proposal,
)
from tradingagents.agents.trader.trader import create_trader
from tradingagents.agents.utils.output_guard import (
    DIRECTIONAL_RATINGS,
    effective_gate_verdict,
    enforce_blocked_conclusion,
    is_blocked_run,
)
from tradingagents.agents.utils.rating import RATING_REVIEW, extract_rating
from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.data_quality_gate import (
    GATE_CONTEXT_KEY,
    GATE_DECISION_KEY,
    GATE_VERDICT_KEY,
    create_data_quality_gate_node,
)
from tradingagents.graph.propagation import Propagator
from tradingagents.graph.setup import GraphSetup
from tradingagents.graph.signal_processing import SignalProcessor
from tradingagents.reporting import write_report_tree

SYMBOL = "COF"
TARGET = "2026-05-13"
FETCHED = "2026-05-13T12:00:00Z"

DIRECTIONAL = ("Buy", "Sell", "Overweight", "Underweight")


# ---------------------------------------------------------------------------
# Deterministic fixtures (mirror the gate graph tests, no external services)
# ---------------------------------------------------------------------------


def _fixed_dataframe() -> pd.DataFrame:
    dates = pd.bdate_range("2026-04-01", "2026-05-20")
    closes = [100 + i for i in range(len(dates))]
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": [c - 0.5 for c in closes],
            "High": [c + 1.0 for c in closes],
            "Low": [c - 1.0 for c in closes],
            "Close": closes,
            "Volume": [1_000_000 + i for i in range(len(dates))],
        }
    )


def _fake_llm(content: str = "Buy"):
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=None)
    llm.invoke = MagicMock(return_value=MagicMock(content=content))
    bt = RunnableLambda(lambda m: AIMessage(content=content, tool_calls=[]))
    llm.bind_tools = MagicMock(return_value=bt)
    return llm


def _real_blocked_gate_node():
    """A real gate node whose snapshot fetch fails, producing a blocked verdict."""

    def boom(*args, **kwargs):
        raise RuntimeError("Synthetic missing critical market data")

    return create_data_quality_gate_node(
        snapshot_builder=boom, now_provider=lambda: FETCHED
    )


def _build_graph(quick, deep, gate_factory=None):
    tool_nodes = {key: ToolNode([]) for key in ("market", "social", "news", "fundamentals")}
    setup = GraphSetup(
        quick,
        deep,
        tool_nodes,
        ConditionalLogic(),
        data_quality_gate_factory=gate_factory,
    )
    return setup.setup_graph(("market",)).compile()


def _initial_state():
    return Propagator().create_initial_state(SYMBOL, TARGET, asset_type="stock")


def _stream_state(graph, state):
    """Run the graph node-by-node, merging updates, and return (state, nodes)."""
    nodes: list[str] = []
    for delta in graph.stream(state, stream_mode="updates"):
        nodes.extend(delta)
        for update in delta.values():
            if isinstance(update, dict):
                state.update(update)
    return state, nodes


# ---------------------------------------------------------------------------
# effective_gate_verdict: fail-closed reading of the gate state
# ---------------------------------------------------------------------------


class TestEffectiveGateVerdict:
    def test_matching_normal_and_degraded_are_effective(self):
        for verdict in ("normal", "degraded"):
            state = {
                GATE_VERDICT_KEY: verdict,
                GATE_DECISION_KEY: {"decision": verdict},
            }
            assert effective_gate_verdict(state) == verdict
            assert is_blocked_run(state) is False

    def test_blocked_is_blocked(self):
        state = {GATE_VERDICT_KEY: "blocked", GATE_DECISION_KEY: {"decision": "blocked"}}
        assert effective_gate_verdict(state) == "blocked"
        assert is_blocked_run(state) is True

    @pytest.mark.parametrize(
        "state",
        [
            {},  # no gate state at all
            {GATE_VERDICT_KEY: "normal"},  # verdict without a decision object
            {GATE_VERDICT_KEY: "normal", GATE_DECISION_KEY: "not-a-dict"},
            {GATE_VERDICT_KEY: "normal", GATE_DECISION_KEY: {}},
            {GATE_VERDICT_KEY: "normal", GATE_DECISION_KEY: {"decision": None}},
            {GATE_VERDICT_KEY: "normal", GATE_DECISION_KEY: {"decision": "unknown"}},
            {GATE_VERDICT_KEY: "normal!", GATE_DECISION_KEY: {"decision": "normal!"}},
            {GATE_VERDICT_KEY: "normal", GATE_DECISION_KEY: {"decision": "blocked"}},
            {GATE_VERDICT_KEY: "blocked", GATE_DECISION_KEY: {"decision": "normal"}},
            {GATE_VERDICT_KEY: 12345, GATE_DECISION_KEY: {"decision": 12345}},
        ],
    )
    def test_missing_malformed_or_inconsistent_state_fails_closed(self, state):
        assert effective_gate_verdict(state) == "blocked"
        assert is_blocked_run(state) is True

    def test_non_mapping_state_fails_closed(self):
        assert effective_gate_verdict(None) == "blocked"
        assert effective_gate_verdict("normal") == "blocked"


# ---------------------------------------------------------------------------
# enforce_blocked_conclusion: structured and free-text rendering paths
# ---------------------------------------------------------------------------


class TestEnforceBlockedConclusion:
    def test_structured_research_plan_is_pinned_to_hold(self):
        for directional in DIRECTIONAL:
            rendered = render_research_plan(
                ResearchPlan(
                    recommendation=PortfolioRating(directional),
                    rationale="Directional case that must be preserved.",
                    strategic_actions="Act on it.",
                )
            )
            guarded = enforce_blocked_conclusion(rendered, field="recommendation")
            assert "**Recommendation**: Hold" in guarded
            for word in DIRECTIONAL:
                assert f"**Recommendation**: {word}" not in guarded
            assert "Directional case that must be preserved." in guarded

    def test_structured_pm_decision_is_pinned_to_hold(self):
        for directional in DIRECTIONAL:
            rendered = render_pm_decision(
                PortfolioDecision(
                    rating=PortfolioRating(directional),
                    executive_summary="Thesis the model wrote.",
                    investment_thesis="Evidence the model cited.",
                )
            )
            guarded = enforce_blocked_conclusion(rendered, field="rating")
            assert "**Rating**: Hold" in guarded
            for word in DIRECTIONAL:
                assert f"**Rating**: {word}" not in guarded
            assert "Thesis the model wrote." in guarded
            assert "Evidence the model cited." in guarded
            assert extract_rating(guarded) == "Hold"

    def test_structured_trader_proposal_is_pinned_to_hold(self):
        for directional in ("Buy", "Sell"):
            rendered = render_trader_proposal(
                TraderProposal(
                    action=TraderAction(directional),
                    reasoning="Reasoning the model wrote.",
                    entry_price=123.5,
                    stop_loss=110.0,
                )
            )
            guarded = enforce_blocked_conclusion(rendered, field="action")
            assert "**Action**: Hold" in guarded
            assert "FINAL TRANSACTION PROPOSAL: **HOLD**" in guarded
            assert f"FINAL TRANSACTION PROPOSAL: **{directional.upper()}**" not in guarded
            assert "Reasoning the model wrote." in guarded

    @pytest.mark.parametrize("field", ["recommendation", "rating", "action"])
    def test_freetext_path_with_header_is_pinned(self, field):
        label = {
            "recommendation": "Recommendation",
            "rating": "Rating",
            "action": "Action",
        }[field]
        text = (
            f"**{label}**: Sell\n\n"
            "Rationale: momentum looked weak.\n\n"
            "Recovery: re-run once the missing market data is restored."
        )
        guarded = enforce_blocked_conclusion(text, field=field)
        assert f"**{label}**: Hold" in guarded
        assert f"**{label}**: Sell" not in guarded
        # Explanation and recovery conditions survive untouched.
        assert "momentum looked weak." in guarded
        assert "Recovery: re-run once the missing market data is restored." in guarded

    @pytest.mark.parametrize("field", ["recommendation", "rating", "action"])
    def test_freetext_without_header_gets_authoritative_hold(self, field):
        guarded = enforce_blocked_conclusion(
            "I think this is a clear Buy opportunity.", field=field
        )
        label = {
            "recommendation": "Recommendation",
            "rating": "Rating",
            "action": "Action",
        }[field]
        assert f"**{label}**: Hold" in guarded
        assert "blocked by the Data Quality Gate" in guarded

    def test_prose_is_not_corrupted_by_broad_word_replacement(self):
        # Narrative mentions of both sides are legitimate explanation; only the
        # decision field is pinned so the reasoning stays readable.
        text = (
            "**Rating**: Overweight\n\n"
            "The bull case argued Buy on the backlog, while the bear case "
            "argued Sell on margin compression. Neither was conclusive."
        )
        guarded = enforce_blocked_conclusion(text, field="rating")
        assert "**Rating**: Hold" in guarded
        assert "argued Buy on the backlog" in guarded
        assert "argued Sell on margin compression" in guarded

    def test_idempotent(self):
        text = "**Rating**: Buy\n\nRationale."
        once = enforce_blocked_conclusion(text, field="rating")
        twice = enforce_blocked_conclusion(once, field="rating")
        assert once == twice

    def test_empty_text_still_yields_hold(self):
        guarded = enforce_blocked_conclusion("", field="rating")
        assert "**Rating**: Hold" in guarded

    def test_compatibility_marker_pinned_without_primary_header(self):
        # Regression: the no-header branch previously returned before the
        # FINAL TRANSACTION PROPOSAL marker was pinned, leaving an executable BUY.
        guarded = enforce_blocked_conclusion(
            "FINAL TRANSACTION PROPOSAL: **BUY**", field="action"
        )
        assert "**Action**: Hold" in guarded
        assert "FINAL TRANSACTION PROPOSAL: **HOLD**" in guarded
        assert "BUY" not in guarded.upper()

    def test_compatibility_marker_markup_tolerated(self):
        for text in (
            "- FINAL TRANSACTION PROPOSAL: BUY",
            "FINAL TRANSACTION PROPOSAL — **Buy**",
            "## FINAL TRANSACTION PROPOSAL: _SELL_",
            "Final Transaction Proposal: **Sell**.",
        ):
            guarded = enforce_blocked_conclusion(text, field="action")
            assert "**HOLD**" in guarded, guarded
            assert "BUY" not in guarded.upper()
            assert "SELL" not in guarded.upper()

    def test_repeated_decision_headers_all_pinned(self):
        # Regression: only the first header was pinned, leaving a later Sell.
        guarded = enforce_blocked_conclusion("Action: Buy\nAction: Sell", field="action")
        assert "**Action**: Hold" in guarded
        assert "Action: Sell" not in guarded
        assert "Action: Buy" not in guarded

    def test_repeated_rating_headers_all_pinned(self):
        guarded = enforce_blocked_conclusion(
            "**Rating**: Buy\n\nIntermediate prose.\n\n**Rating**: Sell", field="rating"
        )
        assert "**Rating**: Hold" in guarded
        assert "**Rating**: Buy" not in guarded
        assert "**Rating**: Sell" not in guarded
        assert "Intermediate prose." in guarded

    def test_bullet_and_heading_markup_tolerated(self):
        for header in ("- Action: Buy", "## Action: Sell", "1. **Action**: Buy"):
            guarded = enforce_blocked_conclusion(header, field="action")
            assert "Action" in guarded and "Hold" in guarded
            assert "Buy" not in guarded and "Sell" not in guarded

    def test_markup_tolerance_does_not_touch_prose(self):
        # Ordinary rationale lines that merely *mention* a rating word are not
        # decision headers and must survive unchanged.
        text = (
            "**Rating**: Buy\n\n"
            "- The Buy case rested on a backlog that the bear could not refute.\n"
            "## The bear argued Sell, but it was weaker."
        )
        guarded = enforce_blocked_conclusion(text, field="rating")
        assert "**Rating**: Hold" in guarded
        assert "The Buy case rested on a backlog" in guarded
        assert "## The bear argued Sell, but it was weaker." in guarded

    def test_blocked_trader_sizing_is_neutralised_but_rationale_kept(self):
        rendered = render_trader_proposal(
            TraderProposal(
                action=TraderAction.BUY,
                reasoning="Entry above support at 189.5 looked constructive.",
                entry_price=189.5,
                stop_loss=178.0,
                position_sizing="6% of portfolio",
            )
        )
        guarded = enforce_blocked_conclusion(rendered, field="action")
        assert "**Action**: Hold" in guarded
        # The executable sizing fields no longer carry a fill instruction...
        assert "**Entry Price**: not applicable (blocked run: no executable position)" in guarded
        assert "**Stop Loss**: not applicable (blocked run: no executable position)" in guarded
        assert "**Position Sizing**: not applicable (blocked run: no executable position)" in guarded
        assert "6% of portfolio" not in guarded
        # ...while the quoted reasoning keeps the historical rationale text.
        assert "Entry above support at 189.5 looked constructive." in guarded
        assert "not applicable (blocked run: no executable position)" in guarded

    def test_repeated_and_markup_enforcement_is_idempotent(self):
        for field, text in (
            ("action", "Action: Buy\n- FINAL TRANSACTION PROPOSAL: **SELL**\nAction: Sell"),
            ("rating", "**Rating**: Buy\n## Rating: Sell"),
            ("recommendation", "Recommendation: Buy\nRecommendation: Overweight"),
        ):
            once = enforce_blocked_conclusion(text, field=field)
            twice = enforce_blocked_conclusion(once, field=field)
            assert once == twice


# ---------------------------------------------------------------------------
# Review findings 1 & 3: alternative decision headers and separator preservation
# ---------------------------------------------------------------------------


class TestAlternativeDecisionHeaders:
    """The guard must pin the same header grammar the rating extractor reads.

    ``extract_rating`` NFKC-normalizes (so a fullwidth colon becomes ``:``) and
    searches within a line, so ``Rating：Buy`` and ``Final rating: Buy`` were
    recognized as a later Buy after the guard prepended a Hold. The guard now
    rewrites those headers themselves; the final signal boundary is also
    gate-aware as a structural backstop.
    """

    @pytest.mark.parametrize(
        "text",
        [
            "Rating：Buy",  # fullwidth colon
            "Rating： Sell",  # fullwidth colon + space
            "Final rating: Buy",  # prefixed label
            "The rating: Overweight",  # descriptor prefix
            "Rating — Buy",  # unicode dash separator
            "**Final rating**: Sell",  # prefixed + markdown
            "Ｒａｔｉｎｇ：Ｂｕｙ",  # fullwidth label AND value
            "My final overall investment rating: Buy",  # arbitrary prefix
            "My final overall investment rating: Sell.",  # arbitrary prefix + punctuation
        ],
    )
    def test_alternative_rating_headers_resolve_to_hold(self, text):
        guarded = enforce_blocked_conclusion(text, field="rating")
        assert extract_rating(guarded) == "Hold", guarded
        assert SignalProcessor().process_signal(guarded) == "Hold"

    def test_fullwidth_label_and_value_is_canonicalised(self):
        guarded = enforce_blocked_conclusion("Ｒａｔｉｎｇ：Ｂｕｙ", field="rating")
        assert "**Rating**: Hold" in guarded
        assert extract_rating(guarded) == "Hold"

    def test_arbitrary_prefix_is_neutralised_not_prepend_only(self):
        # The prior defect: prepending Hold left the original "My ... rating:
        # Buy" line intact and the parser read it. The whole decision line is now
        # canonicalised.
        guarded = enforce_blocked_conclusion(
            "My final overall investment rating: Buy", field="rating"
        )
        assert extract_rating(guarded) == "Hold"
        assert "My final overall investment rating: Buy" not in guarded

    def test_repeated_trailing_alternative_header_is_pinned(self):
        text = "**Rating**: Buy\n\nSome rationale.\n\nFinal rating: Sell"
        guarded = enforce_blocked_conclusion(text, field="rating")
        assert extract_rating(guarded) == "Hold"
        assert "Some rationale." in guarded

    def test_multiple_alternative_headers_all_neutralised(self):
        text = (
            "Rating: Buy\n\n"
            "The bear argued Sell on margin compression.\n\n"
            "My final overall investment rating: Sell"
        )
        guarded = enforce_blocked_conclusion(text, field="rating")
        assert extract_rating(guarded) == "Hold"
        assert SignalProcessor().process_signal(guarded) == "Hold"
        # Rationale prose is preserved as non-executable explanation.
        assert "The bear argued Sell on margin compression." in guarded

    def test_alternative_recommendation_header_is_pinned(self):
        guarded = enforce_blocked_conclusion("Recommendation：Sell", field="recommendation")
        assert "Recommendation" in guarded
        assert "Sell" not in guarded

    def test_normal_and_degraded_text_is_not_guarded(self):
        # The guard is only applied on blocked runs; calling it here mirrors the
        # caller, which gates on is_blocked_run. Unblocked behavior is unchanged.
        for state in (
            {GATE_VERDICT_KEY: "normal", GATE_DECISION_KEY: {"decision": "normal"}},
            {GATE_VERDICT_KEY: "degraded", GATE_DECISION_KEY: {"decision": "degraded"}},
        ):
            assert is_blocked_run(state) is False


class TestSeparatorPreservation:
    """Review finding 3: pinning must not concatenate Hold with the tail prose."""

    @pytest.mark.parametrize("field", ["recommendation", "rating", "action"])
    def test_natural_language_tail_keeps_a_separator(self, field):
        label = {
            "recommendation": "Recommendation",
            "rating": "Rating",
            "action": "Action",
        }[field]
        text = f"{label}: Buy because the outlook is good."
        guarded = enforce_blocked_conclusion(text, field=field)
        first_line = guarded.splitlines()[0]
        # The rating field is rendered in the canonical blocked form; the other
        # fields keep the model's original header shape. In every case the
        # natural-language tail is preserved with a real separator.
        assert "Hold because the outlook is good." in first_line
        assert "Holdbecause" not in guarded
        assert "because the outlook is good." in guarded

    def test_markdown_value_with_tail_keeps_a_separator(self):
        guarded = enforce_blocked_conclusion(
            "**Rating**: **Buy** because the outlook is good.", field="rating"
        )
        assert "**Rating**: Hold because the outlook is good." in guarded
        assert "Holdbecause" not in guarded

    @pytest.mark.parametrize(
        "text",
        [
            "Rating: Buy because the outlook is good.",
            "Rating：Buy because the outlook is good.",
            "Final rating: Sell since margins are weak.",
            "**Rating**: Overweight. Momentum was strong.",
        ],
    )
    def test_guarded_output_is_parseable_and_idempotent(self, text):
        once = enforce_blocked_conclusion(text, field="rating")
        assert extract_rating(once) == "Hold"
        twice = enforce_blocked_conclusion(once, field="rating")
        assert once == twice



# ---------------------------------------------------------------------------
# Executable directional instructions surviving a blocked gate (2026-11-06
# maintenance): fullwidth/NFKC variants, long decision-label descriptors,
# repeated/trailing headers, and executable proposal markers with explanation
# tails. The guard must canonicalise the decision to Hold and the Trader's
# executable sizing to not-applicable, while preserving ordinary rationale,
# quoted alternatives and recovery conditions.
# ---------------------------------------------------------------------------

_FULLWIDTH_ACTION_BLOCK = (
    "**Action**: Hold\n\n"
    "Ａｃｔｉｏｎ：Ｂｕｙ\n"
    "Entry Price：100\n"
    "Stop Loss：95\n"
    "Position Sizing：20%\n"
    "FINAL TRANSACTION PROPOSAL: BUY because momentum improved"
)


class TestExecutableInstructionSurvival:
    def test_fullwidth_block_has_no_executable_direction_or_sizing(self):
        guarded = enforce_blocked_conclusion(_FULLWIDTH_ACTION_BLOCK, field="action")
        # No directional action survives, in any width.
        for word in ("Ｂｕｙ", "Buy"):
            assert f"**Action**: {word}" not in guarded
        assert "Action: Buy" not in guarded
        # Every sizing field is the canonical not-applicable line, so no active
        # value survives. No raw fullwidth sizing labels remain either, and the
        # only recognized sizing values are the not-applicable placeholders.
        assert "**Entry Price**: not applicable (blocked run: no executable position)" in guarded
        assert "**Stop Loss**: not applicable (blocked run: no executable position)" in guarded
        assert "**Position Sizing**: not applicable (blocked run: no executable position)" in guarded
        for original in ("Entry Price：100", "Stop Loss：95", "Position Sizing：20%"):
            assert original not in guarded
        # No active numeric entry/stop price survives anywhere in the stored plan.
        for active in ("189.5", "100", "95", "20%"):
            assert active not in guarded
        # The compatibility marker carries Hold, not a directional value.
        assert "FINAL TRANSACTION PROPOSAL: **HOLD**" in guarded
        assert "PROPOSAL: BUY" not in guarded and "PROPOSAL: **BUY**" not in guarded
        # A readable explanation tail is preserved and output stays idempotent.
        assert "because momentum improved" in guarded
        assert enforce_blocked_conclusion(guarded, field="action") == guarded

    @pytest.mark.parametrize(
        "text",
        [
            "Ａｃｔｉｏｎ：Ｂｕｙ",
            "Ｒａｔｉｎｇ：Ｂｕｙ",
            "Ｒｅｃｏｍｍｅｎｄａｔｉｏｎ：Ｓｅｌｌ",
            "My final carefully reviewed overall detailed investment committee "
            "consensus recommendation rating: Buy",
        ],
    )
    @pytest.mark.parametrize("field", ["recommendation", "rating", "action"])
    def test_nfkc_and_long_descriptor_variants_resolve_to_hold(self, text, field):
        guarded = enforce_blocked_conclusion(text, field=field)
        assert extract_rating(guarded) == "Hold", guarded
        assert SignalProcessor().process_signal(guarded) == "Hold"

    @pytest.mark.parametrize("field", ["recommendation", "rating", "action"])
    @pytest.mark.parametrize(
        "separator",
        ["：", ":", "—", " - "],
    )
    def test_repeated_trailing_labels_all_pinned(self, field, separator):
        label = {"recommendation": "Recommendation", "rating": "Rating", "action": "Action"}[field]
        text = (
            f"**{label}**: Hold\n\n"
            "Some rationale survives.\n\n"
            f"{label}{separator}Buy\n"
            f"{label}{separator}Sell"
        )
        guarded = enforce_blocked_conclusion(text, field=field)
        assert "Some rationale survives." in guarded
        for word in ("Buy", "Sell"):
            assert f"{label}{separator}{word}" not in guarded, guarded
        assert enforce_blocked_conclusion(guarded, field=field) == guarded

    @pytest.mark.parametrize(
        "text",
        [
            "FINAL TRANSACTION PROPOSAL: BUY because momentum improved",
            "FINAL TRANSACTION PROPOSAL：ＳＥＬＬ because the trend broke",
            "- FINAL TRANSACTION PROPOSAL: **BUY** since the backlog grew",
            "ＦＩＮＡＬ ＴＲＡＮＳＡＣＴＩＯＮ ＰＲＯＰＯＳＡＬ：ＢＵＹ momentum improved",
        ],
    )
    def test_proposal_marker_with_explanation_tail_is_pinned(self, text):
        guarded = enforce_blocked_conclusion(text, field="action")
        assert "FINAL TRANSACTION PROPOSAL: **HOLD**" in guarded, guarded
        assert "BUY" not in guarded.upper()
        assert "SELL" not in guarded.upper()
        # The explanation after the value survives as non-executable prose.
        assert ("momentum improved" in guarded) or ("trend broke" in guarded) or (
            "backlog grew" in guarded
        )
        assert enforce_blocked_conclusion(guarded, field="action") == guarded

    def test_markdown_wrapped_decision_is_canonicalised(self):
        for text in ("## Action: **Buy**", "1. _Action_: Sell", "**Action**: __Buy__"):
            guarded = enforce_blocked_conclusion(text, field="action")
            assert "**Action**: Hold" in guarded, guarded
            assert "Buy" not in guarded.replace("**Action**: Hold", "")

    def test_rationale_and_recovery_are_not_rewritten(self):
        text = (
            "Action: Buy\n"
            "Reasoning: I rejected the earlier Action: Buy because evidence is missing.\n"
            "Recovery: obtain data before changing the action."
        )
        guarded = enforce_blocked_conclusion(text, field="action")
        assert "**Action**: Hold" in guarded
        # The rationale's nested mention and the recovery condition survive.
        assert "I rejected the earlier Action: Buy because evidence is missing." in guarded
        assert "Recovery: obtain data before changing the action." in guarded

    def test_blockquote_alternatives_are_not_rewritten(self):
        text = (
            "Action: Buy\n\n"
            "> Action: Sell was an alternative, not a decision."
        )
        guarded = enforce_blocked_conclusion(text, field="action")
        assert "**Action**: Hold" in guarded
        assert "> Action: Sell was an alternative, not a decision." in guarded

    def test_long_non_header_line_is_fast(self):
        # Regression for catastrophic backtracking: a long ordinary rationale
        # line that repeatedly contains the label words must not be treated as a
        # header and must return promptly.
        import time

        line = "The analyst said the Rating: Buy case was weak. " * 500
        start = time.perf_counter()
        guarded = enforce_blocked_conclusion(line, field="rating")
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0
        # The nested mention is not a decision header; a Hold is prepended but
        # the prose is preserved verbatim (no broad word replacement).
        assert "The analyst said the Rating: Buy case was weak." in guarded

    @pytest.mark.parametrize(
        "text",
        [
            "Rating: Buy\n> Rating: Sell was an alternative, not a decision.",
            "Rating: Buy\nReasoning: We rejected the earlier rating: Sell because it lacks evidence.",
        ],
    )
    def test_quoted_or_narrative_alternative_does_not_override_hold(self, text):
        # Parser/guard agreement: the quoted/narrative alternative survives as
        # explanation but the executable Hold remains authoritative for the
        # plain textual signal, not only for the structured gate state.
        guarded = enforce_blocked_conclusion(text, field="rating")
        assert "**Rating**: Hold" in guarded
        assert SignalProcessor().process_signal(guarded) == "Hold"
        assert extract_rating(guarded) == "Hold"
        # The alternative survives as non-executable explanation.
        assert ("was an alternative, not a decision." in guarded) or (
            "because it lacks evidence." in guarded
        )
        assert enforce_blocked_conclusion(guarded, field="rating") == guarded

    @pytest.mark.parametrize(
        "text",
        [
            "Rating: Buy\n> Rating: Sell was an alternative, not a decision.",
            "Rating: Buy\nReasoning: We rejected the earlier rating: Sell because it lacks evidence.",
        ],
    )
    def test_quoted_or_narrative_alternative_kept_in_memory_and_report(self, text, tmp_path):
        # The stored report decision and the memory DECISION body must agree with
        # the authoritative Hold even though a quoted/narrative alternative
        # survives in the prose.
        from tradingagents.agents.utils.memory import TradingMemoryLog

        guarded = enforce_blocked_conclusion(text, field="rating")
        log = TradingMemoryLog({"memory_log_path": str(tmp_path / "mem.md")})
        log.store_decision(SYMBOL, TARGET, guarded, blocked=True)
        entry = log.load_entries()[0]
        assert entry["rating"] == "Hold"
        assert extract_rating(entry["decision"]) == "Hold"
        decision_md = log.load_entries()[0]["decision"]
        assert f"**Rating**: {entry['rating']}" in decision_md

    def test_research_manager_freetext_fullwidth_recommendation_is_hold(self):
        llm = MagicMock()
        llm.with_structured_output = MagicMock(return_value=None)
        llm.invoke = MagicMock(
            return_value=MagicMock(
                content=(
                    "Ｒｅｃｏｍｍｅｎｄａｔｉｏｎ：Ｂｕｙ\n\n"
                    "**Rationale**: the data was too thin but momentum looked strong.\n\n"
                    "**Strategic Actions**: add aggressively."
                )
            )
        )
        out = create_research_manager(llm)(_manager_state())
        plan = out["investment_plan"]
        assert "**Recommendation**: Hold" in plan, plan
        for word in DIRECTIONAL:
            assert f"**Recommendation**: {word}" not in plan
        # Rationale survives; a fullwidth directional header does not.
        assert "momentum looked strong." in plan
        assert "Ｂｕｙ" not in plan


# ---------------------------------------------------------------------------
# Multiline executable instructions surviving a blocked gate (2026-11-10).
# The header grammar requires a value on the SAME line after a separator, so
# block-style instructions (``**Action**:`` newline ``Buy``) or inline executable
# sentences (``Buy 100 shares at $100. Exit at $120.``) survived the prepended
# Hold and contradicted it in the stored plan. The guard must contain these
# without breaking legitimate rationale/quotations.
# ---------------------------------------------------------------------------

_MULTILINE_ACTION_BLOCK = (
    "**Action**:\n"
    "Buy\n"
    "**Entry Price**: $100\n"
    "**Position Sizing**: 10%"
)

_MULTILINE_PROPOSAL_BLOCK = (
    "FINAL TRANSACTION PROPOSAL:\n"
    "BUY 100 shares at $100"
)

_MULTILINE_PLAIN_BLOCK = "Buy 100 shares at $100. Exit at $120."


class TestMultilineExecutableInstructions:
    """Regression: block/inline executable instructions on a blocked run.

    Every case must end with the plan containing an authoritative Hold and no
    executable directional/fill instruction (sizing neutralised, proposal pinned
    to HOLD), while a legitimate rationale or a quoted alternative is preserved.
    """

    @pytest.mark.parametrize(
        "text",
        [
            _MULTILINE_ACTION_BLOCK,
            _MULTILINE_ACTION_BLOCK.replace("\n", "\r\n"),  # CRLF
            "  **Action**:   \n  Buy  \n**Entry Price**:   $100\n**Position Sizing**:   10%",
            "**Action**:\n**Buy**\n**Entry Price**: **$100**\n**Position Sizing**: **10%**",
            "**Action**:\n*Buy*\n**Entry Price**: $100\n**Position Sizing**: 10%",
            "- **Action**:\n  Buy\n  **Entry Price**: $100\n  **Position Sizing**: 10%",
            "Ａｃｔｉｏｎ：\nＢｕｙ\nＥｎｔｒｙ Ｐｒｉｃｅ：＄１００\n"
            "Ｐｏｓｉｔｉｏｎ Ｓｉｚｉｎｇ：１０％",
        ],
    )
    def test_action_block_multiline_variants_are_contained(self, text):
        guarded = enforce_blocked_conclusion(text, field="action")
        assert "**Action**: Hold" in guarded, guarded
        # The dangling value line is contained, not left executable.
        assert "\nBuy\n" not in guarded
        assert "\nＢｕｙ\n" not in guarded
        # Sizing fields are neutralised; no active price/size survives as active.
        assert "**Entry Price**: not applicable" in guarded
        assert "**Position Sizing**: not applicable" in guarded
        assert "$100" not in guarded
        assert "10%" not in guarded or "10%" in "not applicable"
        # Idempotent.
        assert enforce_blocked_conclusion(guarded, field="action") == guarded

    @pytest.mark.parametrize(
        "text",
        [
            _MULTILINE_PROPOSAL_BLOCK,
            _MULTILINE_PROPOSAL_BLOCK.replace("\n", "\r\n"),
            "FINAL TRANSACTION PROPOSAL:\r\nBUY 100 shares at $100",
            "- FINAL TRANSACTION PROPOSAL:\n**BUY** 100 shares at $100",
            "Final Transaction Proposal:\nSell 50 shares at $95. Stop at $110.",
            "ＦＩＮＡＬ ＴＲＡＮＳＡＣＴＩＯＮ ＰＲＯＰＯＳＡＬ：\nＢＵＹ １００ ｓｈａｒｅｓ",
        ],
    )
    def test_multiline_proposal_block_is_pinned(self, text):
        guarded = enforce_blocked_conclusion(text, field="action")
        assert "FINAL TRANSACTION PROPOSAL: **HOLD**" in guarded, guarded
        upper = guarded.upper()
        assert "BUY 100 SHARES" not in upper
        assert "BUY 100 SHARES AT $100" not in upper
        assert "PROPOSAL:\nBUY" not in upper
        assert "PROPOSAL:\r\nBUY" not in upper
        assert "ＳＨＡＲＥＳ" not in guarded
        # Exactly one authoritative Hold decision is asserted by the canonical line.
        assert "**Action**: Hold" in guarded
        assert enforce_blocked_conclusion(guarded, field="action") == guarded

    @pytest.mark.parametrize(
        "text",
        [
            _MULTILINE_PLAIN_BLOCK,
            "Buy 100 shares at $100.\nExit at $120.\nSell 50 shares at $130.",
            "BUY 100 SHARES AT $100. EXIT AT $120.",
            "Buy 100 shares at $100 and set a stop at $90.",
        ],
    )
    def test_unsupported_plain_executable_sentences_fail_closed(self, text):
        guarded = enforce_blocked_conclusion(text, field="action")
        # Unsupported format -> authoritative Hold with fail-closed explanation;
        # no executable share/price instruction survives in the plan body.
        assert "**Action**: Hold" in guarded
        upper = guarded.upper()
        assert "BUY 100 SHARES" not in upper
        assert "SELL 50 SHARES" not in upper
        assert "EXIT AT $120" not in upper
        assert "STOP AT $90" not in upper
        assert "blocked by the Data Quality Gate" in guarded
        assert enforce_blocked_conclusion(guarded, field="action") == guarded

    def test_multiline_legitimate_rationale_preserved(self):
        # A multi-line rationale is not a decision: the Hold is pinned and the
        # reasoning survives; narrative mentions are not executable instructions.
        text = (
            "**Action**:\n"
            "Buy\n"
            "**Reasoning**:\n"
            "The bull case argued Buy on backlog growth.\n"
            "The bear case argued Sell on margin compression.\n"
            "Neither case was conclusive."
        )
        guarded = enforce_blocked_conclusion(text, field="action")
        assert "**Action**: Hold" in guarded
        assert "The bull case argued Buy on backlog growth." in guarded
        assert "The bear case argued Sell on margin compression." in guarded
        assert "Neither case was conclusive." in guarded

    def test_multiline_quoted_alternative_preserved(self):
        text = (
            "**Action**:\n"
            "Buy\n\n"
            "> FINAL TRANSACTION PROPOSAL: SELL was an alternative, not a decision.\n"
            "> Action: Sell was considered."
        )
        guarded = enforce_blocked_conclusion(text, field="action")
        assert "**Action**: Hold" in guarded
        assert "> FINAL TRANSACTION PROPOSAL: SELL was an alternative" in guarded
        assert "> Action: Sell was considered." in guarded

    def test_fullwidth_and_long_form_existing_behavior_still_holds(self):
        # Do not weaken the prior 130-guard coverage: the canonical fullwidth
        # block still resolves to Hold with neutralised sizing and pinned marker.
        guarded = enforce_blocked_conclusion(_FULLWIDTH_ACTION_BLOCK, field="action")
        assert "**Action**: Hold" in guarded
        assert "**Entry Price**: not applicable" in guarded
        assert "FINAL TRANSACTION PROPOSAL: **HOLD**" in guarded
        assert extract_rating(guarded) == "Hold"
        assert enforce_blocked_conclusion(guarded, field="action") == guarded

    def test_multiline_proposal_repeated_label_all_pinned(self):
        text = (
            "**Action**: Hold\n\n"
            "FINAL TRANSACTION PROPOSAL:\nBUY 100 shares at $100\n"
            "FINAL TRANSACTION PROPOSAL:\nSELL 50 shares at $95"
        )
        guarded = enforce_blocked_conclusion(text, field="action")
        upper = guarded.upper()
        assert "BUY 100 SHARES" not in upper
        assert "SELL 50 SHARES" not in upper
        assert guarded.upper().count("FINAL TRANSACTION PROPOSAL: **HOLD**") == 2
        assert enforce_blocked_conclusion(guarded, field="action") == guarded


class TestMultilineBlankLineAndQuotedRationale:
    """Boundary variants (2026-11-10): blank physical lines and quoted rationale.

    A blank physical line between a label and its value (``**Action**:`` blank
    ``Buy``) must not defeat containment, a direction-plus-explanation value line
    (``Buy because valuation is attractive``) must be contained, split sizing
    (``**Entry Price**:`` blank ``$100``) must be neutralised, and a *quoted*
    historical/negated rationale (``We rejected "Buy 100 shares at $100" ...``)
    must be preserved verbatim, not deleted by an unanchored regex.
    """

    @pytest.mark.parametrize(
        "text",
        [
            "**Action**:\n\nBuy\n**Entry Price**: $100\n**Position Sizing**: 10%",
            "**Action**:\n\n\nBuy\n**Entry Price**: $100\n**Position Sizing**: 10%",
            "**Action**:\n \nBuy\n**Entry Price**: $100\n**Position Sizing**: 10%",
            "**Action**:\r\n\r\nBuy\r\n**Entry Price**: $100\r\n**Position Sizing**: 10%",
        ],
    )
    def test_blank_line_before_direction_value_is_contained(self, text):
        guarded = enforce_blocked_conclusion(text, field="action")
        assert "**Action**: Hold" in guarded, guarded
        # No surviving bare Buy value line (blank-line separated) contradicts Hold.
        assert "\nBuy\n" not in guarded and "\r\nBuy\r\n" not in guarded
        assert not any(
            line.strip().lower() == "buy" for line in guarded.splitlines()
        ), guarded
        assert "$100" not in guarded
        assert "**Entry Price**: not applicable" in guarded
        assert enforce_blocked_conclusion(guarded, field="action") == guarded

    def test_direction_plus_explanation_value_is_contained(self):
        text = "**Action**:\nBuy because valuation is attractive.\n**Entry Price**: $100"
        guarded = enforce_blocked_conclusion(text, field="action")
        assert "**Action**: Hold" in guarded
        # The executable direction line does not survive as a live value.
        assert "\nBuy because valuation is attractive.\n" not in guarded
        assert "$100" not in guarded
        assert enforce_blocked_conclusion(guarded, field="action") == guarded

    @pytest.mark.parametrize(
        "text",
        [
            "**Action**: Hold\n**Entry Price**:\n\n$100\n**Position Sizing**:\n\n10%",
            "**Action**: Hold\n**Entry Price**:\n$100\n**Position Sizing**:\n10%",
            "**Action**: Hold\n**Entry Price**:\r\n\r\n$100\r\n**Position Sizing**:\r\n10%",
        ],
    )
    def test_split_sizing_with_blank_line_is_neutralised(self, text):
        guarded = enforce_blocked_conclusion(text, field="action")
        assert "**Entry Price**: not applicable" in guarded, guarded
        assert "**Position Sizing**: not applicable" in guarded, guarded
        assert "$100" not in guarded
        assert "10%" not in guarded
        # No dangling active value line remains after a neutralised sizing label.
        assert not any(line.strip() in ("$100", "10%") for line in guarded.splitlines())
        assert enforce_blocked_conclusion(guarded, field="action") == guarded

    def test_blank_line_before_proposal_value_is_contained(self):
        for text in (
            "FINAL TRANSACTION PROPOSAL:\n\nBUY 100 shares at $100",
            "FINAL TRANSACTION PROPOSAL:\r\n\r\nBUY 100 shares at $100",
        ):
            guarded = enforce_blocked_conclusion(text, field="action")
            assert "FINAL TRANSACTION PROPOSAL: **HOLD**" in guarded, guarded
            assert "BUY 100 SHARES" not in guarded.upper()
            assert "PROPOSAL:\n\nBUY" not in guarded.upper()
            assert enforce_blocked_conclusion(guarded, field="action") == guarded

    @pytest.mark.parametrize(
        "text",
        [
            '**Action**: Buy\nRationale: We rejected "Buy 100 shares at $100" because evidence is missing.',
            "**Action**: Buy\nWe considered a Buy 100 shares at $100 plan but the evidence was missing.",
            '**Action**: Buy\nQuoted alternative: "Sell 50 shares at $95" was evaluated and rejected.',
            "**Action**: Buy\nEarlier proposal: Buy 100 shares at $100. It was not executed.",
        ],
    )
    def test_quoted_or_narrative_historical_rationale_is_preserved(self, text):
        guarded = enforce_blocked_conclusion(text, field="action")
        assert "**Action**: Hold" in guarded
        # The quoted/narrative historical discussion survives verbatim; the
        # unanchored containment must not delete a non-executable quotation.
        body = guarded
        for marker in (
            'We rejected "Buy 100 shares at $100"',
            "We considered a Buy 100 shares at $100 plan",
            '"Sell 50 shares at $95" was evaluated and rejected',
            "Earlier proposal: Buy 100 shares at $100. It was not executed.",
        ):
            if marker in text:
                assert marker in body, (marker, guarded)

    def test_long_repeated_direction_token_lines_are_linear(self):
        import time

        line = "Buy 100 shares at $100. " * 400
        start = time.perf_counter()
        guarded = enforce_blocked_conclusion(line, field="action")
        elapsed = time.perf_counter() - start
        assert elapsed < 1.5
        assert "**Action**: Hold" in guarded
        assert "BUY 100 SHARES" not in guarded.upper()

    @pytest.mark.parametrize(
        "text",
        [
            "Action:\n- Buy",
            "Action:\n1. Buy",
            "**Action**:\n* Buy",
            "Action:\n- **Sell**",
            "Action:\n2. Underweight",
            "Ｒａｔｉｎｇ：\n- Ｂｕｙ",
        ],
    )
    def test_bulleted_or_numbered_direction_value_is_contained(self, text):
        field = "rating" if "Ｒａｔｉｎｇ" in text else "action"
        guarded = enforce_blocked_conclusion(text, field=field)
        label = {"action": "Action", "rating": "Rating"}[field]
        assert f"**{label}**: Hold" in guarded, guarded
        # No surviving bulleted/numbered bare-direction value line contradicts Hold.
        for word in ("Buy", "Sell", "Underweight", "Ｂｕｙ"):
            assert not any(
                line.strip().lstrip("-*+ ").strip().strip("*_").lower()
                == word.lower()
                for line in guarded.splitlines()
            ), guarded
        assert enforce_blocked_conclusion(guarded, field=field) == guarded

    @pytest.mark.parametrize(
        "text",
        [
            "Action: Buy\nBuy 100 shares at $100 because the earlier forecast improved;",
            "Action: Buy\nBuy 100 shares at $100; analyst says \"good value\".",
            "Action: Buy\nBuy 100 shares at $100 because we considered it earlier.",
            "Action: Buy\nSell 50 shares at $95 since the previous target was hit.",
        ],
    )
    def test_live_command_with_rationale_keyword_or_quote_is_still_contained(self, text):
        # A line that LEADS with a trade verb is a live command: a later
        # "earlier"/"considered" keyword or an incidental quotation must NOT grant
        # blanket immunity and leave it executable.
        guarded = enforce_blocked_conclusion(text, field="action")
        assert "**Action**: Hold" in guarded
        upper = guarded.upper()
        assert "BUY 100 SHARES AT $100" not in upper
        assert "SELL 50 SHARES AT $95" not in upper
        assert enforce_blocked_conclusion(guarded, field="action") == guarded

    @pytest.mark.parametrize(
        "text,expected_tail",
        [
            ("**Action**:\nBuy because valuation is attractive.", "because valuation is attractive."),
            ("**Action**:\nBuy since the backlog grew.", "since the backlog grew."),
            ("**Action**:\n- Sell as margins compressed.", "as margins compressed."),
        ],
    )
    def test_multiline_direction_explanation_is_preserved_as_rationale(
        self, text, expected_tail
    ):
        guarded = enforce_blocked_conclusion(text, field="action")
        assert "**Action**: Hold" in guarded
        assert expected_tail in guarded, guarded
        assert "\nBuy" not in guarded and "\nSell" not in guarded
        assert enforce_blocked_conclusion(guarded, field="action") == guarded

    @pytest.mark.parametrize(
        "text,expected_tail,forbidden",
        [
            (
                "Action: Buy 100 shares at $100 because valuation is attractive",
                "because valuation is attractive",
                "100 shares",
            ),
            (
                "Action: Buy 100 shares at $100",
                None,
                "100 shares",
            ),
            (
                "**Action**: Buy 100 shares at $100 because valuation is attractive.",
                "because valuation is attractive.",
                "100 shares",
            ),
            (
                "Action: Buy 100 shares at $100; analyst says \"good value\".",
                None,
                "100 shares",
            ),
        ],
    )
    def test_same_line_decision_executable_tail_is_stripped(
        self, text, expected_tail, forbidden
    ):
        guarded = enforce_blocked_conclusion(text, field="action")
        first = guarded.splitlines()[0]
        assert first.startswith("**Action**: Hold"), guarded
        # No executable position/price remains in the decision field line.
        assert forbidden not in first, first
        assert "$100" not in first, first
        if expected_tail is not None:
            # A clearly separated rationale clause survives.
            assert expected_tail in first, first
        assert enforce_blocked_conclusion(guarded, field="action") == guarded

    @pytest.mark.parametrize(
        "text",
        [
            "Action:\n**Strong Buy**",
            "Action:\nStrong Buy",
            "**Action**:\nStrong Sell now",
            "Action:\n**Very Strong Buy**",  # four words -> not value-like; still prose-safe
            "**Action**: Strong Buy",
            "**Action**: Strong",
        ],
    )
    def test_unsupported_value_in_decision_position_fails_closed(self, text):
        guarded = enforce_blocked_conclusion(text, field="action")
        assert "**Action**: Hold" in guarded, guarded
        # No residual direction variant survives as a live decision value.
        for word in ("Strong", "Buy", "Sell"):
            assert f"**Action**: Hold {word}" not in guarded
            assert not any(
                line.strip().lower().endswith(word.lower())
                and line.strip().lower() != "**action**: hold"
                and "hold" not in line.strip().lower()
                for line in guarded.splitlines()
            ), guarded
        assert enforce_blocked_conclusion(guarded, field="action") == guarded

    def test_trader_node_unsupported_strong_buy_cannot_escape_blocked(self):
        llm = MagicMock()
        llm.with_structured_output = MagicMock(return_value=None)
        llm.invoke = MagicMock(return_value=MagicMock(content="Action:\n**Strong Buy**"))
        node = create_trader(llm)
        out = node(_manager_state(investment_plan="**Recommendation**: Hold"))
        plan = out["trader_investment_plan"]
        assert "**Action**: Hold" in plan
        assert "Strong Buy" not in plan

    def test_trader_node_same_line_executable_tail_stripped(self):
        llm = MagicMock()
        llm.with_structured_output = MagicMock(return_value=None)
        llm.invoke = MagicMock(
            return_value=MagicMock(
                content="Action: Buy 100 shares at $100 because valuation is attractive"
            )
        )
        node = create_trader(llm)
        out = node(_manager_state(investment_plan="**Recommendation**: Hold"))
        plan = out["trader_investment_plan"]
        first = plan.splitlines()[0]
        assert first.startswith("**Action**: Hold")
        assert "100 shares" not in first and "$100" not in first
        assert "because valuation is attractive" in first

    def test_trader_node_bulleted_direction_value_cannot_escape_blocked(self):
        llm = MagicMock()
        llm.with_structured_output = MagicMock(return_value=None)
        llm.invoke = MagicMock(return_value=MagicMock(content="Action:\n- Buy"))
        node = create_trader(llm)
        out = node(_manager_state(investment_plan="**Recommendation**: Hold"))
        plan = out["trader_investment_plan"]
        assert "**Action**: Hold" in plan
        assert not any(line.strip().lstrip("-*+ ").strip() == "Buy" for line in plan.splitlines())

    def test_trader_node_live_command_with_quote_cannot_escape_blocked(self):
        llm = MagicMock()
        llm.with_structured_output = MagicMock(return_value=None)
        llm.invoke = MagicMock(
            return_value=MagicMock(
                content='Action: Buy\nBuy 100 shares at $100 because the earlier forecast improved;'
            )
        )
        node = create_trader(llm)
        out = node(_manager_state(investment_plan="**Recommendation**: Hold"))
        plan = out["trader_investment_plan"]
        assert "**Action**: Hold" in plan
        assert "BUY 100 SHARES" not in plan.upper()


class TestMultilineTraderNodeAndGraph:
    def test_trader_freetext_multiline_block_cannot_escape_blocked(self):
        llm = MagicMock()
        llm.with_structured_output = MagicMock(return_value=None)
        llm.invoke = MagicMock(return_value=MagicMock(content=_MULTILINE_ACTION_BLOCK))
        node = create_trader(llm)
        out = node(_manager_state(investment_plan="**Recommendation**: Hold"))
        plan = out["trader_investment_plan"]
        assert "**Action**: Hold" in plan
        assert "\nBuy\n" not in plan
        assert "**Entry Price**: not applicable" in plan
        assert "**Position Sizing**: not applicable" in plan
        assert "$100" not in plan
        assert extract_rating(plan) == "Hold"

    def test_trader_freetext_plain_sentence_cannot_escape_blocked(self):
        llm = MagicMock()
        llm.with_structured_output = MagicMock(return_value=None)
        llm.invoke = MagicMock(return_value=MagicMock(content=_MULTILINE_PLAIN_BLOCK))
        node = create_trader(llm)
        out = node(_manager_state(investment_plan="**Recommendation**: Hold"))
        plan = out["trader_investment_plan"]
        assert "**Action**: Hold" in plan
        assert "BUY 100 SHARES" not in plan.upper()
        assert "EXIT AT $120" not in plan.upper()

    def test_blocked_graph_multiline_plan_carries_no_executable_instruction(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(
            validator,
            "load_ohlcv",
            MagicMock(side_effect=ValueError("Synthetic missing critical market data")),
        )
        blocked_text = (
            _MULTILINE_ACTION_BLOCK
            + "\n"
            + _MULTILINE_PROPOSAL_BLOCK
        )
        quick = _fake_llm(blocked_text)
        deep = _fake_llm(blocked_text)
        graph = _build_graph(quick, deep, gate_factory=lambda: create_data_quality_gate_node(
            now_provider=lambda: FETCHED
        ))
        final, _ = _stream_state(graph, _initial_state())

        assert final["data_quality_verdict"] == "blocked"
        trader_plan = final["trader_investment_plan"]
        assert "**Action**: Hold" in trader_plan
        assert "\nBuy\n" not in trader_plan
        assert "BUY 100 SHARES" not in trader_plan.upper()
        assert "**Entry Price**: not applicable" in trader_plan
        assert "PROPOSAL:\nBUY" not in trader_plan.upper()
        assert SignalProcessor().process_signal(final["final_trade_decision"], final) == "Hold"

        # Saved report and memory agree with the restricted Hold conclusion.
        write_report_tree(final, SYMBOL, tmp_path / "reports")
        trader_md = (
            Path(tmp_path) / "reports" / "3_trading" / "trader.md"
        ).read_text(encoding="utf-8")
        assert "BUY 100 SHARES" not in trader_md.upper()
        decision_md = (
            Path(tmp_path) / "reports" / "5_portfolio" / "decision.md"
        ).read_text(encoding="utf-8")
        assert extract_rating(decision_md) == "Hold"

        from tradingagents.agents.utils.memory import TradingMemoryLog

        log = TradingMemoryLog({"memory_log_path": str(tmp_path / "mem.md")})
        log.store_decision(
            SYMBOL, TARGET, final["final_trade_decision"], blocked=is_blocked_run(final)
        )
        entries = log.load_entries()
        assert entries[0]["rating"] == "Hold"
        assert extract_rating(entries[0]["decision"]) == "Hold"


# ---------------------------------------------------------------------------
# Downstream nodes: blocked cannot be undone by Trader / Portfolio Manager
# ---------------------------------------------------------------------------


def _manager_state(**overrides):
    state = {
        "company_of_interest": SYMBOL,
        "trade_date": TARGET,
        "asset_type": "stock",
        "instrument_context": "",
        "portfolio_context": "",
        "data_quality_verdict": "blocked",
        "data_quality_gate_decision": {"decision": "blocked"},
        "data_quality_context": "[Data Quality Gate] Verdict: blocked.",
        "market_report": "",
        "sentiment_report": "",
        "news_report": "",
        "fundamentals_report": "",
        "investment_plan": "**Recommendation**: Hold",
        "trader_investment_plan": "**Action**: Hold",
        "risk_debate_state": {
            "history": "",
            "count": 0,
            "aggressive_history": "",
            "conservative_history": "",
            "neutral_history": "",
            "latest_speaker": "",
            "current_aggressive_response": "",
            "current_conservative_response": "",
            "current_neutral_response": "",
        },
        "investment_debate_state": {"history": "", "count": 0, "bear_history": "", "bull_history": "",
                                    "current_response": ""},
    }
    state.update(overrides)
    return state


def _structured_llm_returning(model):
    llm = MagicMock()
    structured = MagicMock()
    structured.invoke = MagicMock(return_value=model)
    llm.with_structured_output = MagicMock(return_value=structured)
    llm.invoke = MagicMock(return_value=MagicMock(content="free text fallback"))
    return llm


class TestTraderBlockedContract:
    @pytest.mark.parametrize("directional", ["Buy", "Sell"])
    def test_trader_structured_buy_cannot_escape_blocked(self, directional):
        llm = _structured_llm_returning(
            TraderProposal(action=TraderAction(directional), reasoning="Momentum was strong.")
        )
        node = create_trader(llm)
        out = node(_manager_state(investment_plan="**Recommendation**: Hold"))
        plan = out["trader_investment_plan"]
        assert "**Action**: Hold" in plan
        assert f"FINAL TRANSACTION PROPOSAL: **{directional.upper()}**" not in plan
        assert "Momentum was strong." in plan

    def test_trader_freetext_buy_cannot_escape_blocked(self):
        llm = MagicMock()
        llm.with_structured_output = MagicMock(return_value=None)
        llm.invoke = MagicMock(
            return_value=MagicMock(content="**Action**: Buy\n\n**Reasoning**: chart looked strong.")
        )
        node = create_trader(llm)
        out = node(_manager_state(investment_plan="**Recommendation**: Hold"))
        assert "**Action**: Hold" in out["trader_investment_plan"]
        assert "chart looked strong." in out["trader_investment_plan"]

    def test_trader_freetext_fullwidth_instructions_cannot_escape_blocked(self):
        # The exact 2026-11-06 operator reproduction: a stored plan that reads
        # Hold but still carries fullwidth executable instructions and an
        # explained proposal marker.
        llm = MagicMock()
        llm.with_structured_output = MagicMock(return_value=None)
        llm.invoke = MagicMock(return_value=MagicMock(content=_FULLWIDTH_ACTION_BLOCK))
        node = create_trader(llm)
        out = node(_manager_state(investment_plan="**Recommendation**: Hold"))
        plan = out["trader_investment_plan"]
        assert "**Action**: Hold" in plan
        for word in ("Ｂｕｙ", "Buy", "Sell"):
            assert f"**Action**: {word}" not in plan
        assert "**Entry Price**: not applicable" in plan
        assert "**Stop Loss**: not applicable" in plan
        assert "**Position Sizing**: not applicable" in plan
        assert "FINAL TRANSACTION PROPOSAL: **HOLD**" in plan
        assert "PROPOSAL: BUY" not in plan
        assert "because momentum improved" in plan
        assert extract_rating(plan) == "Hold"

    def test_trader_normal_run_is_not_coerced(self):
        llm = MagicMock()
        llm.with_structured_output = MagicMock(return_value=None)
        llm.invoke = MagicMock(return_value=MagicMock(content="**Action**: Buy\n\n**Reasoning**: x"))
        node = create_trader(llm)
        out = node(
            _manager_state(
                data_quality_verdict="normal",
                data_quality_gate_decision={"decision": "normal"},
                investment_plan="**Recommendation**: Buy",
            )
        )
        assert "**Action**: Buy" in out["trader_investment_plan"]

    def test_trader_prompt_carries_blocked_directive(self):
        llm = MagicMock()
        llm.with_structured_output = MagicMock(return_value=None)
        llm.invoke = MagicMock(return_value=MagicMock(content="**Action**: Hold"))
        node = create_trader(llm)
        node(_manager_state(investment_plan="**Recommendation**: Hold"))
        prompt = llm.invoke.call_args.args[0]
        rendered = json.dumps(prompt) if not isinstance(prompt, str) else prompt
        assert "DATA QUALITY GATE BLOCKED" in rendered


class TestPortfolioManagerBlockedContract:
    @pytest.mark.parametrize("directional", DIRECTIONAL)
    def test_pm_structured_directional_cannot_escape_blocked(self, directional):
        llm = _structured_llm_returning(
            PortfolioDecision(
                rating=PortfolioRating(directional),
                executive_summary="Action plan the model wrote.",
                investment_thesis="Evidence the model cited.",
            )
        )
        node = create_portfolio_manager(llm)
        out = node(
            _manager_state(
                investment_plan="**Recommendation**: Hold",
                trader_investment_plan="**Action**: Hold",
                risk_debate_state={"history": "", "count": 0, "aggressive_history": "",
                                   "conservative_history": "", "neutral_history": "",
                                   "latest_speaker": "", "current_aggressive_response": "",
                                   "current_conservative_response": "",
                                   "current_neutral_response": ""},
            )
        )
        decision = out["final_trade_decision"]
        assert "**Rating**: Hold" in decision
        assert extract_rating(decision) == "Hold"
        for word in DIRECTIONAL:
            assert f"**Rating**: {word}" not in decision
        assert "Action plan the model wrote." in decision

    def test_pm_freetext_directional_cannot_escape_blocked(self):
        llm = MagicMock()
        llm.with_structured_output = MagicMock(return_value=None)
        llm.invoke = MagicMock(
            return_value=MagicMock(
                content="**Rating**: Buy\n\n**Executive Summary**: Enter now.\n\n"
                "**Investment Thesis**: the risk debate favored upside."
            )
        )
        node = create_portfolio_manager(llm)
        out = node(
            _manager_state(
                investment_plan="**Recommendation**: Hold",
                trader_investment_plan="**Action**: Hold",
                risk_debate_state={"history": "", "count": 0, "aggressive_history": "",
                                   "conservative_history": "", "neutral_history": "",
                                   "latest_speaker": "", "current_aggressive_response": "",
                                   "current_conservative_response": "",
                                   "current_neutral_response": ""},
            )
        )
        assert "**Rating**: Hold" in out["final_trade_decision"]
        assert SignalProcessor().process_signal(out["final_trade_decision"]) == "Hold"
        assert "the risk debate favored upside." in out["final_trade_decision"]

    def test_pm_missing_gate_state_fails_closed(self):
        llm = MagicMock()
        llm.with_structured_output = MagicMock(return_value=None)
        llm.invoke = MagicMock(return_value=MagicMock(content="**Rating**: Buy\n\nx"))
        node = create_portfolio_manager(llm)
        state = _manager_state(
            data_quality_verdict=None,
            data_quality_gate_decision=None,
            investment_plan="**Recommendation**: Hold",
            trader_investment_plan="**Action**: Hold",
            risk_debate_state={"history": "", "count": 0, "aggressive_history": "",
                               "conservative_history": "", "neutral_history": "",
                               "latest_speaker": "", "current_aggressive_response": "",
                               "current_conservative_response": "",
                               "current_neutral_response": ""},
        )
        out = node(state)
        assert "**Rating**: Hold" in out["final_trade_decision"]

    def test_pm_normal_run_is_not_coerced(self):
        llm = MagicMock()
        llm.with_structured_output = MagicMock(return_value=None)
        llm.invoke = MagicMock(return_value=MagicMock(content="**Rating**: Buy\n\nx"))
        node = create_portfolio_manager(llm)
        out = node(
            _manager_state(
                data_quality_verdict="normal",
                data_quality_gate_decision={"decision": "normal"},
                investment_plan="**Recommendation**: Buy",
                trader_investment_plan="**Action**: Buy",
                risk_debate_state={"history": "", "count": 0, "aggressive_history": "",
                                   "conservative_history": "", "neutral_history": "",
                                   "latest_speaker": "", "current_aggressive_response": "",
                                   "current_conservative_response": "",
                                   "current_neutral_response": ""},
            )
        )
        assert "**Rating**: Buy" in out["final_trade_decision"]


# ---------------------------------------------------------------------------
# Complete graph: real blocked gate + adversarial directional fakes
# ---------------------------------------------------------------------------


def _adversarial_structured_llm(default: str = "Buy"):
    """An LLM whose structured path returns a directional model per schema.

    ``with_structured_output`` is called with the target schema; the returned
    object renders every agent's output as a maximal directional call so only a
    deterministic guard can stop it leaking from a blocked run.
    """

    def _structured_for(schema, *args, **kwargs):
        structured = MagicMock()
        if schema is ResearchPlan:
            model_obj = ResearchPlan(
                recommendation=PortfolioRating(default),
                rationale="Adversarial rationale.",
                strategic_actions="Act aggressively.",
            )
        elif schema is TraderProposal:
            model_obj = TraderProposal(
                action=TraderAction(default), reasoning="Adversarial reasoning."
            )
        elif schema is PortfolioDecision:
            model_obj = PortfolioDecision(
                rating=PortfolioRating(default),
                executive_summary="Adversarial plan.",
                investment_thesis="Adversarial thesis.",
            )
        else:  # pragma: no cover - unexpected schema in this test
            structured.invoke = MagicMock(return_value=None)
            return structured
        structured.invoke = MagicMock(return_value=model_obj)
        return structured

    llm = MagicMock()
    llm.with_structured_output = MagicMock(side_effect=_structured_for)
    llm.invoke = MagicMock(return_value=MagicMock(content=default))
    llm.bind_tools = MagicMock(
        return_value=RunnableLambda(lambda m: AIMessage(content=default, tool_calls=[]))
    )
    return llm


class TestCompleteGraphEnforcement:
    def test_blocked_run_cannot_end_directional_structured(self, monkeypatch):
        # Structured path: every LLM returns a directional ResearchPlan /
        # TraderProposal / PortfolioDecision, so only the guard can stop it.
        monkeypatch.setattr(
            validator,
            "load_ohlcv",
            MagicMock(side_effect=ValueError("Synthetic missing critical market data")),
        )
        quick = _adversarial_structured_llm("Buy")
        deep = _adversarial_structured_llm("Sell")

        graph = _build_graph(quick, deep, gate_factory=lambda: create_data_quality_gate_node(
            now_provider=lambda: FETCHED
        ))
        final, nodes = _stream_state(graph, _initial_state())

        assert final["data_quality_verdict"] == "blocked"
        assert "Bull Researcher" not in nodes and "Bear Researcher" not in nodes
        assert "**Recommendation**: Hold" in final["investment_plan"]
        assert "**Action**: Hold" in final["trader_investment_plan"]
        assert "**Rating**: Hold" in final["final_trade_decision"]
        assert SignalProcessor().process_signal(final["final_trade_decision"]) == "Hold"
        assert final["risk_debate_state"]["judge_decision"] == final["final_trade_decision"]

    def test_blocked_run_cannot_end_directional_freetext(self, monkeypatch):
        # Free-text path: this is the exact review reproduction. The fake LLM
        # returns "Buy" everywhere; the real gate blocks on a failing snapshot.
        monkeypatch.setattr(
            validator,
            "load_ohlcv",
            MagicMock(side_effect=ValueError("Synthetic missing critical market data")),
        )
        quick = _fake_llm("Buy")
        deep = _fake_llm("Buy")
        graph = _build_graph(quick, deep, gate_factory=lambda: create_data_quality_gate_node(
            now_provider=lambda: FETCHED
        ))
        final, nodes = _stream_state(graph, _initial_state())

        assert final["data_quality_verdict"] == "blocked"
        assert "Bull Researcher" not in nodes and "Bear Researcher" not in nodes
        assert "**Recommendation**: Hold" in final["investment_plan"]
        assert "**Action**: Hold" in final["trader_investment_plan"]
        assert "**Rating**: Hold" in final["final_trade_decision"]
        signal = SignalProcessor().process_signal(final["final_trade_decision"])
        assert signal == "Hold"

    def test_blocked_report_and_signal_reflect_restricted_conclusion(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            validator,
            "load_ohlcv",
            MagicMock(side_effect=ValueError("Synthetic missing critical market data")),
        )
        quick = _fake_llm("Buy")
        deep = _fake_llm("Buy")
        graph = _build_graph(quick, deep, gate_factory=lambda: create_data_quality_gate_node(
            now_provider=lambda: FETCHED
        ))
        final, _ = _stream_state(graph, _initial_state())
        report_path = write_report_tree(final, SYMBOL, tmp_path / "reports")

        complete = Path(report_path).read_text(encoding="utf-8")
        # The final decision and portfolio section carry the restricted call,
        # never an actionable directional rating on a blocked run.
        assert "**Rating**: Hold" in complete
        assert "**Rating**: Buy" not in complete
        assert Path(tmp_path / "reports" / "3_trading" / "trader.md").read_text(
            encoding="utf-8"
        ).count("**Action**: Hold") == 1
        decision_md = Path(tmp_path / "reports" / "5_portfolio" / "decision.md").read_text(
            encoding="utf-8"
        )
        assert extract_rating(decision_md) == "Hold"
        # Trace: the gate verdict is still visible in the report.
        assert "blocked" in complete.lower()

    @pytest.mark.parametrize(
        "escape",
        [
            "Rating：Buy",  # fullwidth colon (review finding 1)
            "Final rating: Buy",  # prefixed label (review finding 1)
            "Rating: Buy because the outlook is good.",  # separator (review finding 3)
            "Ｒａｔｉｎｇ：Ｂｕｙ",  # fullwidth label AND value (operator recheck)
            "My final overall investment rating: Buy",  # arbitrary prefix (operator recheck)
        ],
    )
    def test_blocked_graph_summary_with_alternative_headers_ends_hold(self, monkeypatch, escape):
        # The exact review reproductions: the fake LLM returns an alternative
        # decision-header format on a real blocked gate. The stored decision and
        # the final signal must both be Hold.
        monkeypatch.setattr(
            validator,
            "load_ohlcv",
            MagicMock(side_effect=ValueError("Synthetic missing critical market data")),
        )
        quick = _fake_llm(escape)
        deep = _fake_llm(escape)
        graph = _build_graph(quick, deep, gate_factory=lambda: create_data_quality_gate_node(
            now_provider=lambda: FETCHED
        ))
        final, nodes = _stream_state(graph, _initial_state())

        assert final["data_quality_verdict"] == "blocked"
        assert "Bull Researcher" not in nodes and "Bear Researcher" not in nodes
        assert SignalProcessor().process_signal(
            final["final_trade_decision"], final
        ) == "Hold"
        assert SignalProcessor().process_signal(final["final_trade_decision"]) == "Hold"
        # The stored decision text itself no longer reads as a directional call.
        assert extract_rating(final["final_trade_decision"]) == "Hold"
        assert "Holdbecause" not in final["final_trade_decision"]

    @pytest.mark.parametrize(
        "escape",
        [
            "Ｒａｔｉｎｇ：Ｂｕｙ",
            "My final overall investment rating: Buy",
            "Rating: Buy because the outlook is good.",
        ],
    )
    def test_blocked_graph_report_and_memory_agree_with_signal(
        self, monkeypatch, tmp_path, escape
    ):
        # Operator recheck: the structured signal was protected, but the saved
        # report decision and the memory DECISION body could still parse as Buy,
        # contradicting the Hold tag. Verify report text, memory tag, and memory
        # body all agree with the structured Hold signal.
        from tradingagents.agents.utils.memory import TradingMemoryLog

        monkeypatch.setattr(
            validator,
            "load_ohlcv",
            MagicMock(side_effect=ValueError("Synthetic missing critical market data")),
        )
        quick = _fake_llm(escape)
        deep = _fake_llm(escape)
        graph = _build_graph(quick, deep, gate_factory=lambda: create_data_quality_gate_node(
            now_provider=lambda: FETCHED
        ))
        final, _ = _stream_state(graph, _initial_state())

        # Report decision text parses to Hold.
        write_report_tree(final, SYMBOL, tmp_path / "reports")
        decision_md = (
            Path(tmp_path) / "reports" / "5_portfolio" / "decision.md"
        ).read_text(encoding="utf-8")
        assert extract_rating(decision_md) == "Hold"

        # Memory tag and DECISION body agree.
        log = TradingMemoryLog({"memory_log_path": str(tmp_path / "mem.md")})
        log.store_decision(
            SYMBOL,
            TARGET,
            final["final_trade_decision"],
            blocked=is_blocked_run(final),
        )
        entries = log.load_entries()
        assert entries[0]["rating"] == "Hold"
        assert extract_rating(entries[0]["decision"]) == "Hold"

    def test_blocked_graph_stored_plans_carry_no_executable_instruction(
        self, monkeypatch, tmp_path
    ):
        # 2026-11-06 operator reproduction, end-to-end: the real failing gate
        # blocks the run and a fake model whose free text embeds fullwidth
        # executable instructions plus an explained proposal marker must not
        # leave any of them in the STORED intermediate Trader / Research plans or
        # the saved report -- not merely in the final signal.
        monkeypatch.setattr(
            validator,
            "load_ohlcv",
            MagicMock(side_effect=ValueError("Synthetic missing critical market data")),
        )
        quick = _fake_llm(_FULLWIDTH_ACTION_BLOCK)
        deep = _fake_llm(_FULLWIDTH_ACTION_BLOCK)
        graph = _build_graph(quick, deep, gate_factory=lambda: create_data_quality_gate_node(
            now_provider=lambda: FETCHED
        ))
        final, nodes = _stream_state(graph, _initial_state())

        assert final["data_quality_verdict"] == "blocked"
        assert "Bull Researcher" not in nodes and "Bear Researcher" not in nodes

        # Stored intermediate plans carry no executable direction or sizing.
        trader_plan = final["trader_investment_plan"]
        assert "**Action**: Hold" in trader_plan
        assert "**Entry Price**: not applicable" in trader_plan
        assert "**Stop Loss**: not applicable" in trader_plan
        assert "**Position Sizing**: not applicable" in trader_plan
        assert "20%" not in trader_plan
        assert "FINAL TRANSACTION PROPOSAL: **HOLD**" in trader_plan
        assert "PROPOSAL: BUY" not in trader_plan
        assert "Ｂｕｙ" not in trader_plan

        assert "**Recommendation**: Hold" in final["investment_plan"]
        assert final["risk_debate_state"]["judge_decision"] == final["final_trade_decision"]
        assert SignalProcessor().process_signal(final["final_trade_decision"], final) == "Hold"

        # The saved report is consistent with the stored Hold decision.
        write_report_tree(final, SYMBOL, tmp_path / "reports")
        trader_md = (
            Path(tmp_path) / "reports" / "3_trading" / "trader.md"
        ).read_text(encoding="utf-8")
        assert "not applicable (blocked run: no executable position)" in trader_md
        assert "FINAL TRANSACTION PROPOSAL: **BUY**" not in trader_md
        decision_md = (
            Path(tmp_path) / "reports" / "5_portfolio" / "decision.md"
        ).read_text(encoding="utf-8")
        assert extract_rating(decision_md) == "Hold"

    def test_blocked_graph_signal_boundary_uses_structured_state(self):
        # Even if a decision text carried a directional header the guard did not
        # recognize, the structured gate state at the signal boundary forces Hold.
        sp = SignalProcessor()
        blocked_state = {
            GATE_VERDICT_KEY: "blocked",
            GATE_DECISION_KEY: {"decision": "blocked"},
        }
        assert sp.process_signal("Rating: Buy", blocked_state) == "Hold"
        normal_state = {
            GATE_VERDICT_KEY: "normal",
            GATE_DECISION_KEY: {"decision": "normal"},
        }
        assert sp.process_signal("Rating: Buy", normal_state) == "Buy"


class TestMemorySignalConsistency:
    def test_blocked_memory_tag_is_hold(self, tmp_path):
        from tradingagents.agents.utils.memory import TradingMemoryLog

        log = TradingMemoryLog({"memory_log_path": str(tmp_path / "mem.md")})
        log.store_decision(
            "COF", TARGET, "Rating: Buy\n\nA model buy.", blocked=True
        )
        entries = log.load_entries()
        assert entries and entries[0]["rating"] == "Hold"

    def test_blocked_graph_state_flags_memory_as_blocked(self):
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        assert TradingAgentsGraph._is_blocked_state(
            {GATE_VERDICT_KEY: "blocked", GATE_DECISION_KEY: {"decision": "blocked"}}
        )
        assert not TradingAgentsGraph._is_blocked_state(
            {GATE_VERDICT_KEY: "normal", GATE_DECISION_KEY: {"decision": "normal"}}
        )
        # A legacy minimal state without gate fields keeps its text-based parse.
        assert not TradingAgentsGraph._is_blocked_state(
            {"final_trade_decision": "Rating: Buy"}
        )

    def test_graph_process_signal_uses_curr_state_gate_verdict(self):
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        g = object.__new__(TradingAgentsGraph)
        g.signal_processor = SignalProcessor()
        g.curr_state = {
            GATE_VERDICT_KEY: "blocked",
            GATE_DECISION_KEY: {"decision": "blocked"},
        }
        assert g.process_signal("Rating: Buy") == "Hold"
        g.curr_state = {
            GATE_VERDICT_KEY: "normal",
            GATE_DECISION_KEY: {"decision": "normal"},
        }
        assert g.process_signal("Rating: Buy") == "Buy"




# ---------------------------------------------------------------------------
# Degraded and normal runs keep supported behavior
# ---------------------------------------------------------------------------


def _stub_gate_node(verdict: str):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        return {
            GATE_VERDICT_KEY: verdict,
            GATE_DECISION_KEY: {"decision": verdict, "decided_at": FETCHED},
            GATE_CONTEXT_KEY: f"[Data Quality Gate] Verdict: {verdict}.",
            "data_quality_error": None,
            "data_quality_evidence_records": [],
            "data_quality_validation_results": {},
            "data_quality_group_statuses": [],
        }

    return node


class TestUnblockedRunsPreserveBehavior:
    @pytest.mark.parametrize("verdict", ["normal", "degraded"])
    def test_directional_output_is_preserved(self, verdict):
        # The same Buy-everywhere *structured* model must keep its call on an
        # unblocked run; only a blocked run is restricted.
        quick = _adversarial_structured_llm("Buy")
        deep = _adversarial_structured_llm("Buy")
        graph = _build_graph(quick, deep, gate_factory=lambda: _stub_gate_node(verdict))
        final, nodes = _stream_state(graph, _initial_state())
        assert final["data_quality_verdict"] == verdict
        assert "Bull Researcher" in nodes
        assert "**Rating**: Buy" in final["final_trade_decision"]
        assert SignalProcessor().process_signal(final["final_trade_decision"]) == "Buy"

    def test_degraded_is_not_silently_rewritten_to_hold(self):
        # Degraded runs cap confidence but are not forced to Hold.
        text = "**Rating**: Overweight\n\nReduced conviction given low-quality evidence."
        assert enforce_blocked_conclusion is not None  # helper exists
        # The downgrade helper must not be applied unless the run is blocked.
        assert not is_blocked_run(
            {GATE_VERDICT_KEY: "degraded", GATE_DECISION_KEY: {"decision": "degraded"}}
        )
        assert extract_rating(text) == "Overweight"

    @pytest.mark.parametrize("verdict", ["normal", "degraded"])
    def test_guard_forms_do_not_block_unblocked_runs(self, verdict):
        # The new multiline / unsupported-value / executable-tail handling runs
        # only when the caller sees a blocked gate state. A normal/degraded run is
        # never blocked, so a directional call keeps its original meaning and the
        # guard is never invoked on it.
        state = {GATE_VERDICT_KEY: verdict, GATE_DECISION_KEY: {"decision": verdict}}
        assert is_blocked_run(state) is False
        # The decision text is not coerced because the run is not blocked; the
        # raw directional call still reads as a direction.
        assert extract_rating("Action: Buy 100 shares at $100") == "Buy"


class TestLegacyCheckpointCompatibility:
    def test_supported_legacy_normal_checkpoint_is_not_blocked(self):
        legacy_state = {
            "data_quality_verdict": "normal",
            "data_quality_gate_decision": {"decision": "normal"},
            "data_quality_group_statuses": [{"category": "market", "quality_status": "High"}],
        }
        assert effective_gate_verdict(legacy_state) == "normal"

    def test_legacy_normal_freetext_decision_survives(self):
        llm = MagicMock()
        llm.with_structured_output = MagicMock(return_value=None)
        llm.invoke = MagicMock(return_value=MagicMock(content="**Rating**: Buy\n\nx"))
        node = create_portfolio_manager(llm)
        out = node(
            _manager_state(
                data_quality_verdict="normal",
                data_quality_gate_decision={"decision": "normal"},
                investment_plan="**Recommendation**: Buy",
                trader_investment_plan="**Action**: Buy",
                risk_debate_state={"history": "", "count": 0, "aggressive_history": "",
                                   "conservative_history": "", "neutral_history": "",
                                   "latest_speaker": "", "current_aggressive_response": "",
                                   "current_conservative_response": "",
                                   "current_neutral_response": ""},
            )
        )
        assert "**Rating**: Buy" in out["final_trade_decision"]


class TestWhyNotConfidenceCeiling:
    def test_no_numeric_confidence_cap_is_invented(self):
        # Finding 4 (degraded confidence cap) is out of this milestone's scope and
        # no schema/policy defines a numeric ceiling, so the guard must not
        # invent one: a degraded run is never treated as blocked by the guard.
        assert "confidence_ceiling" not in enforce_blocked_conclusion.__doc__.lower()
        state = {GATE_VERDICT_KEY: "degraded", GATE_DECISION_KEY: {"decision": "degraded"}}
        assert not is_blocked_run(state)


def test_directional_rating_vocabulary_is_complete():
    assert set(DIRECTIONAL_RATINGS) == set(DIRECTIONAL)
    assert RATING_REVIEW not in DIRECTIONAL_RATINGS
    # The research manager contract must never expose a directional call either.
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=None)
    llm.invoke = MagicMock(return_value=MagicMock(content="**Recommendation**: Buy\n\nx"))
    out = create_research_manager(llm)(_manager_state())
    for word in DIRECTIONAL:
        assert f"**Recommendation**: {word}" not in out["investment_plan"]
