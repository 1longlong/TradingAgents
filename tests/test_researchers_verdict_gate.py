"""Phase 3A offline tests: Bull/Bear researchers gate on the exact verdict value.

Authoritative requirement (#4): the degraded restriction must be based on the
exact ``data_quality_verdict`` value, not substring matching inside the
human-readable gate context. A context string that happens to contain the word
"degraded" (e.g. inside a reason or limitation) must not enable the restricted
language when the verdict is actually blocked, and the restriction must apply
when the verdict is degraded even if the context text does not literally say
"degraded".

No network, no paid LLM: the researcher node is driven with a fake LLM that
captures the prompt it was handed.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tradingagents.agents.researchers.bear_researcher import create_bear_researcher
from tradingagents.agents.researchers.bull_researcher import create_bull_researcher

RESTRICTION_MARKER = "Data quality is degraded: low-evidence claims cannot be decisive"


def _base_state(**overrides):
    state = {
        "company_of_interest": "COF",
        "trade_date": "2026-05-13",
        "asset_type": "stock",
        "data_quality_verdict": "blocked",
        "market_report": "market body",
        "sentiment_report": "sentiment body",
        "news_report": "news body",
        "fundamentals_report": "fundamentals body",
        "investment_debate_state": {
            "history": "h",
            "count": 1,
            "bear_history": "",
            "bull_history": "",
            "current_response": "",
        },
    }
    state.update(overrides)
    return state


def _captured_prompt(llm):
    return llm.invoke.call_args.args[0] if llm.invoke.call_args.args else llm.invoke.call_args.kwargs["prompt"]


@pytest.mark.parametrize("factory", [create_bull_researcher, create_bear_researcher])
class TestDegradedRestrictionOnExactVerdict:
    def test_verdict_blocked_does_not_inject_restriction(self, factory):
        # The context text mentions "degraded" (inside a reason/limitation), but
        # the authoritative verdict is blocked. The researcher must NOT enable
        # the degraded restriction based on that substring.
        llm = MagicMock()
        llm.invoke = MagicMock(return_value=MagicMock(content="argument"))
        node = factory(llm)
        node(
            _base_state(
                data_quality_verdict="blocked",
                data_quality_context=(
                    "[Data Quality Gate] Verdict: blocked. "
                    "Degraded data may not be decisive."
                ),
            )
        )
        prompt = _captured_prompt(llm)
        assert RESTRICTION_MARKER not in prompt, prompt

    def test_verdict_degraded_injects_restriction(self, factory):
        # Verdict is degraded even though the context string never says the
        # word "degraded": the restriction must still be enabled via the exact
        # verdict value.
        llm = MagicMock()
        llm.invoke = MagicMock(return_value=MagicMock(content="argument"))
        node = factory(llm)
        node(
            _base_state(
                data_quality_verdict="degraded",
                data_quality_context="[Data Quality Gate] Verdict: degraded.",
            )
        )
        prompt = _captured_prompt(llm)
        assert RESTRICTION_MARKER in prompt, prompt

    def test_verdict_normal_does_not_inject_restriction(self, factory):
        llm = MagicMock()
        llm.invoke = MagicMock(return_value=MagicMock(content="argument"))
        node = factory(llm)
        node(
            _base_state(
                data_quality_verdict="normal",
                data_quality_context="[Data Quality Gate] Verdict: normal.",
            )
        )
        prompt = _captured_prompt(llm)
        assert RESTRICTION_MARKER not in prompt, prompt
