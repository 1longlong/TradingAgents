"""Offline tests for structured-output handling: recovery, bounded fallback, error propagation.

Every case mocks the model. ``Counter.invoke`` stands in for one network
generation, so ``structured.invoke.call_count`` and ``plain.invoke.call_count``
are the exact number of generations issued on each path.
"""

from unittest.mock import MagicMock

import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from tradingagents.agents.schemas import (
    PortfolioDecision,
    PortfolioRating,
    ResearchPlan,
    SentimentBand,
    SentimentReport,
    TraderAction,
    TraderProposal,
    render_pm_decision,
)
from tradingagents.agents.utils.structured import (
    StructuredResponseTruncated,
    bind_structured,
    invoke_structured_or_freetext,
)


class SchemaError(Exception):
    """Stand-in for a provider error class: not a parse/validation failure."""


def _validation_error() -> ValidationError:
    """A real pydantic ValidationError, as LangChain's parser produces."""
    try:
        PortfolioDecision(rating="Strong Buy", executive_summary="s", investment_thesis="t")
    except ValidationError as exc:
        return exc
    raise AssertionError("expected a ValidationError")


def _decision_payload() -> dict:
    return {
        "rating": "Buy",
        "executive_summary": "Enter on strength.",
        "investment_thesis": "Trend and flows agree.",
    }


def _bind(invoke_side_effect=None, return_value=None):
    """A structured binding and a plain LLM whose generations are counted."""
    structured_llm = MagicMock()
    if invoke_side_effect is not None:
        structured_llm.invoke.side_effect = invoke_side_effect
    else:
        structured_llm.invoke.return_value = return_value
    plain_llm = MagicMock()
    plain_llm.invoke.return_value = MagicMock(content="FREETEXT REPORT")
    return structured_llm, plain_llm


def _call(structured_llm, plain_llm, render=render_pm_decision, schema=PortfolioDecision):
    return invoke_structured_or_freetext(
        structured_llm,
        plain_llm,
        "prompt",
        render,
        "Agent",
        schema=schema,
    )


def _raw(content="", tool_calls=None):
    return AIMessage(content=content, tool_calls=tool_calls or [])


# ---------------------------------------------------------------------------
# Success
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_success_renders_without_fallback():
    parsed = PortfolioDecision(**_decision_payload())
    structured_llm, plain_llm = _bind(
        return_value={"raw": _raw("{}"), "parsed": parsed, "parsing_error": None}
    )
    out = _call(structured_llm, plain_llm)
    assert "**Rating**: Buy" in out
    assert structured_llm.invoke.call_count == 1
    assert plain_llm.invoke.call_count == 0


@pytest.mark.unit
def test_bare_parsed_object_without_include_raw_still_renders():
    # A wrapper that ignores include_raw returns the model directly.
    parsed = PortfolioDecision(**_decision_payload())
    structured_llm, plain_llm = _bind(return_value=parsed)
    out = _call(structured_llm, plain_llm)
    assert "**Rating**: Buy" in out
    assert plain_llm.invoke.call_count == 0


# ---------------------------------------------------------------------------
# Local recovery from the raw response
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_recovery_from_tool_call_args_after_validation_error():
    # LangChain's parser failed, but the tool-call args validate as-is.
    structured_llm, plain_llm = _bind(
        return_value={
            "raw": _raw("", tool_calls=[
                {"name": "PortfolioDecision", "args": _decision_payload(), "id": "1"},
            ]),
            "parsed": None,
            "parsing_error": _validation_error(),
        }
    )
    out = _call(structured_llm, plain_llm)
    assert "**Rating**: Buy" in out
    assert structured_llm.invoke.call_count == 1
    assert plain_llm.invoke.call_count == 0


@pytest.mark.unit
def test_recovery_from_fenced_json_in_content():
    content = '```json\n{"rating": "Sell", "executive_summary": "s", "investment_thesis": "t"}\n```'
    structured_llm, plain_llm = _bind(
        return_value={"raw": _raw(content), "parsed": None, "parsing_error": None}
    )
    out = _call(structured_llm, plain_llm)
    assert "**Rating**: Sell" in out
    assert plain_llm.invoke.call_count == 0


@pytest.mark.unit
def test_prose_around_json_is_not_recovered():
    # Only whole-message JSON or a whole-message fenced block may be promoted;
    # a balanced brace sequence inside prose could be an example or a rejected
    # alternative.
    content = 'My answer: {"rating": "Hold", "executive_summary": "s", "investment_thesis": "t"} done'
    structured_llm, plain_llm = _bind(
        return_value={"raw": _raw(content), "parsed": None, "parsing_error": None}
    )
    out = _call(structured_llm, plain_llm)
    assert out == "FREETEXT REPORT"
    assert plain_llm.invoke.call_count == 1


@pytest.mark.unit
def test_recovery_never_invents_missing_fields():
    # Missing a required field: recovery must fail, not fill it in.
    structured_llm, plain_llm = _bind(
        return_value={
            "raw": _raw('{"rating": "Buy"}'),
            "parsed": None,
            "parsing_error": None,
        }
    )
    out = _call(structured_llm, plain_llm)
    assert out == "FREETEXT REPORT"
    assert plain_llm.invoke.call_count == 1


@pytest.mark.unit
def test_recovery_never_guesses_an_invalid_rating():
    structured_llm, plain_llm = _bind(
        return_value={
            "raw": _raw('{"rating": "Strong Buy", "executive_summary": "s", "investment_thesis": "t"}'),
            "parsed": None,
            "parsing_error": None,
        }
    )
    out = _call(structured_llm, plain_llm)
    assert out == "FREETEXT REPORT"
    assert plain_llm.invoke.call_count == 1


@pytest.mark.unit
def test_json_body_is_never_returned_as_markdown():
    # Valid JSON that does not validate must not be handed back verbatim.
    raw_json = '{"rating": "Buy"}'
    structured_llm, plain_llm = _bind(
        return_value={"raw": _raw(raw_json), "parsed": None, "parsing_error": None}
    )
    out = _call(structured_llm, plain_llm)
    assert out != raw_json
    assert plain_llm.invoke.call_count == 1


# ---------------------------------------------------------------------------
# Unrecoverable parse failure -> exactly one free-text call
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_unrecoverable_parse_failure_falls_back_once():
    structured_llm, plain_llm = _bind(
        return_value={"raw": _raw("**Rating**: Buy\nplain prose"), "parsed": None, "parsing_error": None}
    )
    out = _call(structured_llm, plain_llm)
    assert out == "FREETEXT REPORT"
    assert structured_llm.invoke.call_count == 1
    assert plain_llm.invoke.call_count == 1


@pytest.mark.unit
def test_output_parser_exception_is_a_parse_failure():
    structured_llm, plain_llm = _bind(
        invoke_side_effect=OutputParserException("bad json")
    )
    out = _call(structured_llm, plain_llm)
    assert out == "FREETEXT REPORT"
    assert structured_llm.invoke.call_count == 1
    assert plain_llm.invoke.call_count == 1


@pytest.mark.unit
def test_parsing_error_payload_is_treated_as_parse_failure():
    structured_llm, plain_llm = _bind(
        return_value={
            "raw": _raw("**Rating**: Sell"),
            "parsed": None,
            "parsing_error": OutputParserException("no tool call"),
        }
    )
    out = _call(structured_llm, plain_llm)
    assert out == "FREETEXT REPORT"
    assert plain_llm.invoke.call_count == 1


# ---------------------------------------------------------------------------
# Provider failures propagate: no retry, no free text
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("exc", [
    SchemaError("401 authentication failed"),
    SchemaError("400 invalid parameter"),
    SchemaError("connection reset by peer"),
    SchemaError("429 rate limit"),
    SchemaError("503 service unavailable"),
    RuntimeError("internal"),
])
def test_provider_errors_propagate_without_regeneration(exc):
    structured_llm, plain_llm = _bind(invoke_side_effect=exc)
    with pytest.raises(type(exc)) as caught:
        _call(structured_llm, plain_llm)
    assert caught.value is exc
    assert structured_llm.invoke.call_count == 1
    assert plain_llm.invoke.call_count == 0


@pytest.mark.unit
def test_unknown_value_error_is_not_a_parse_failure():
    structured_llm, plain_llm = _bind(invoke_side_effect=ValueError("config is wrong"))
    with pytest.raises(ValueError):
        _call(structured_llm, plain_llm)
    assert plain_llm.invoke.call_count == 0


@pytest.mark.unit
def test_unknown_attribute_error_is_not_a_capability_error():
    structured_llm, plain_llm = _bind(invoke_side_effect=AttributeError("client bug"))
    with pytest.raises(AttributeError):
        _call(structured_llm, plain_llm)
    assert plain_llm.invoke.call_count == 0


@pytest.mark.unit
def test_parse_failure_does_not_hide_a_provider_failure_on_retry():
    # Free-text call fails too: its error propagates, no loop.
    structured_llm, plain_llm = _bind(
        return_value={"raw": _raw("prose"), "parsed": None, "parsing_error": None}
    )
    plain_llm.invoke.side_effect = SchemaError("500 upstream")
    with pytest.raises(SchemaError):
        _call(structured_llm, plain_llm)
    assert structured_llm.invoke.call_count == 1
    assert plain_llm.invoke.call_count == 1


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_render_error_propagates_without_regeneration():
    parsed = PortfolioDecision(**_decision_payload())

    def broken_render(_):
        raise RuntimeError("renderer bug")

    structured_llm, plain_llm = _bind(
        return_value={"raw": _raw("{}"), "parsed": parsed, "parsing_error": None}
    )

    def call():
        return invoke_structured_or_freetext(
            structured_llm, plain_llm, "prompt", broken_render, "Agent",
            schema=PortfolioDecision,
        )

    with pytest.raises(RuntimeError, match="renderer bug"):
        call()
    assert structured_llm.invoke.call_count == 1
    assert plain_llm.invoke.call_count == 0


@pytest.mark.unit
def test_render_error_after_local_recovery_propagates():
    def broken_render(_):
        raise RuntimeError("renderer bug")

    structured_llm, plain_llm = _bind(
        return_value={"raw": _raw('{"rating": "Buy", "executive_summary": "s", "investment_thesis": "t"}'),
                      "parsed": None, "parsing_error": None}
    )
    with pytest.raises(RuntimeError, match="renderer bug"):
        invoke_structured_or_freetext(
            structured_llm, plain_llm, "prompt", broken_render, "Agent",
            schema=PortfolioDecision,
        )
    assert plain_llm.invoke.call_count == 0


# ---------------------------------------------------------------------------
# Explicit refusal and empty responses
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_explicit_refusal_skips_structured_call_and_uses_free_text_once():
    plain_llm = MagicMock()
    plain_llm.invoke.return_value = MagicMock(content="**Rating**: Hold\n\nwhy")
    out = _call(None, plain_llm)
    assert out.startswith("**Rating**: Hold")
    assert plain_llm.invoke.call_count == 1


@pytest.mark.unit
def test_unrecoverable_parse_does_not_bypass_refusal_to_retry_structured():
    # Refusal is bound once at creation; a parse miss must not re-bind or
    # reformat the prompt to sneak past it.
    plain_llm = MagicMock()
    plain_llm.invoke.return_value = MagicMock(content="REPORT")
    assert _call(None, plain_llm) == "REPORT"
    assert plain_llm.invoke.call_count == 1
    assert not hasattr(plain_llm, "with_structured_output") or \
        not plain_llm.with_structured_output.called


@pytest.mark.unit
def test_empty_structured_response_raises_without_regeneration():
    # A pure empty response is not a parse miss and buys no free-text call.
    structured_llm, plain_llm = _bind(
        return_value={"raw": _raw(""), "parsed": None, "parsing_error": None}
    )
    with pytest.raises(StructuredResponseTruncated):
        _call(structured_llm, plain_llm)
    assert plain_llm.invoke.call_count == 0


@pytest.mark.unit
def test_empty_free_text_response_raises():
    structured_llm, plain_llm = _bind(
        return_value={"raw": _raw("prose only"), "parsed": None, "parsing_error": None}
    )
    plain_llm.invoke.return_value = MagicMock(content="   ")
    with pytest.raises(ValueError, match="no content"):
        _call(structured_llm, plain_llm)
    assert plain_llm.invoke.call_count == 1


@pytest.mark.unit
def test_none_structured_response_without_raw_does_not_recover():
    structured_llm, plain_llm = _bind(return_value=None)
    with pytest.raises(StructuredResponseTruncated):
        _call(structured_llm, plain_llm)
    assert plain_llm.invoke.call_count == 0


# ---------------------------------------------------------------------------
# Binding
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_bind_requests_include_raw():
    llm = MagicMock()
    llm.with_structured_output.return_value = "bound"
    assert bind_structured(llm, PortfolioDecision, "PM") == "bound"
    _, kwargs = llm.with_structured_output.call_args
    assert kwargs["include_raw"] is True


@pytest.mark.unit
def test_bind_falls_back_when_include_raw_is_unsupported():
    # A legacy binder whose signature lacks include_raw (the real shape: no
    # **kwargs) gets the plain binding, exactly once.
    def binder(schema):
        return "plain-bound"

    llm = MagicMock()
    llm.with_structured_output = binder
    assert bind_structured(llm, PortfolioDecision, "PM") == "plain-bound"


@pytest.mark.unit
def test_bind_returns_none_only_on_explicit_refusal():
    llm = MagicMock()
    llm.with_structured_output.side_effect = NotImplementedError("no structured output")
    assert bind_structured(llm, PortfolioDecision, "PM") is None


@pytest.mark.unit
def test_bind_propagates_configuration_errors():
    llm = MagicMock()
    llm.with_structured_output.side_effect = ValueError("bad schema")
    with pytest.raises(ValueError):
        bind_structured(llm, PortfolioDecision, "PM")


# ---------------------------------------------------------------------------
# Four agents: success-path regression, each generation counted once
# ---------------------------------------------------------------------------


def _envelope(parsed, schema_name):
    raw = _raw("", tool_calls=[
        {"name": schema_name, "args": parsed.model_dump(), "id": "1"},
    ])
    return {"raw": raw, "parsed": parsed, "parsing_error": None}


@pytest.mark.unit
def test_trader_success_path():
    from tradingagents.agents.trader.trader import create_trader

    proposal = TraderProposal(action=TraderAction.BUY, reasoning="setup", entry_price=189.5)
    structured_llm, plain_llm = _bind(return_value=_envelope(proposal, "TraderProposal"))
    plain_llm.with_structured_output.return_value = structured_llm
    result = create_trader(plain_llm)({
        "company_of_interest": "NVDA",
        "investment_plan": "plan",
        "market_report": "",
    })
    assert "**Action**: Buy" in result["trader_investment_plan"]
    assert structured_llm.invoke.call_count == 1
    assert plain_llm.invoke.call_count == 0


@pytest.mark.unit
def test_research_manager_success_path():
    from tradingagents.agents.managers.research_manager import create_research_manager

    plan = ResearchPlan(
        recommendation=PortfolioRating.OVERWEIGHT,
        rationale="bull carried",
        strategic_actions="build slowly",
    )
    structured_llm, plain_llm = _bind(return_value=_envelope(plan, "ResearchPlan"))
    plain_llm.with_structured_output.return_value = structured_llm
    result = create_research_manager(plain_llm)({
        "company_of_interest": "NVDA",
        "investment_debate_state": {"history": "debate", "count": 1},
    })
    assert "**Recommendation**: Overweight" in result["investment_plan"]
    assert structured_llm.invoke.call_count == 1
    assert plain_llm.invoke.call_count == 0


@pytest.mark.unit
def test_portfolio_manager_success_path():
    from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager

    decision = PortfolioDecision(**_decision_payload())
    structured_llm, plain_llm = _bind(return_value=_envelope(decision, "PortfolioDecision"))
    plain_llm.with_structured_output.return_value = structured_llm
    empty = {"history": "", "aggressive_history": "", "conservative_history": "",
             "neutral_history": "", "latest_speaker": "", "current_aggressive_response": "",
             "current_conservative_response": "", "current_neutral_response": "",
             "judge_decision": "", "count": 0}
    result = create_portfolio_manager(plain_llm)({
        "company_of_interest": "NVDA",
        "investment_plan": "plan",
        "trader_investment_plan": "trade",
        "risk_debate_state": empty,
    })
    assert "**Rating**: Buy" in result["final_trade_decision"]
    assert structured_llm.invoke.call_count == 1
    assert plain_llm.invoke.call_count == 0


@pytest.mark.unit
def test_sentiment_analyst_success_path(monkeypatch):
    from tradingagents.agents.analysts import sentiment_analyst

    monkeypatch.setattr(sentiment_analyst, "fetch_stocktwits_messages", lambda *a, **k: "st")
    monkeypatch.setattr(sentiment_analyst, "fetch_reddit_posts", lambda *a, **k: "rd")
    monkeypatch.setattr(sentiment_analyst.get_news, "func", lambda *a, **k: "news", raising=False)

    report = SentimentReport(
        overall_band=SentimentBand.BULLISH,
        overall_score=7.5,
        confidence="high",
        narrative="upbeat",
    )
    structured_llm, plain_llm = _bind(return_value=_envelope(report, "SentimentReport"))
    plain_llm.with_structured_output.return_value = structured_llm
    result = sentiment_analyst.create_sentiment_analyst(plain_llm)({
        "company_of_interest": "NVDA",
        "trade_date": "2026-01-15",
        "asset_type": "stock",
        "messages": [],
    })
    assert "**Overall Sentiment:** **Bullish**" in result["sentiment_report"]
    assert structured_llm.invoke.call_count == 1
    assert plain_llm.invoke.call_count == 0


@pytest.mark.unit
def test_module_imports_without_optional_sdks():
    # The module must not depend on openai/anthropic being importable. Checked in
    # a subprocess: reloading in-process leaves other modules bound to the old
    # module object and silently breaks their imports.
    import subprocess
    import sys

    code = (
        "import sys\n"
        "for name in list(sys.modules):\n"
        "    if name.split('.')[0] in {'openai', 'anthropic'}:\n"
        "        del sys.modules[name]\n"
        "import tradingagents.agents.utils.structured as s\n"
        "assert callable(s.invoke_structured_or_freetext)\n"
        "assert 'openai' not in sys.modules\n"
        "assert 'anthropic' not in sys.modules\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
