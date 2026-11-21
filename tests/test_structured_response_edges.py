"""Offline tests for structured-output edge cases: refusals, truncation, envelope errors, recovery scope.

Uses real ``AIMessage`` objects and langchain-core's real exception types;
only the model call is mocked. ``plain.invoke.call_count`` is the exact
number of free-text generations issued.
"""

import logging
from unittest.mock import MagicMock

import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from tradingagents.agents.schemas import PortfolioDecision
from tradingagents.agents.utils import structured
from tradingagents.agents.utils.structured import (
    StructuredResponseRefused,
    StructuredResponseTruncated,
    bind_structured,
    invoke_structured_or_freetext,
)


class _StatusError(Exception):
    """Stand-in for a provider failure type (auth/network/5xx)."""


def _payload(rating="Buy"):
    return {
        "rating": rating,
        "executive_summary": "Enter on strength.",
        "investment_thesis": "Trend and flows agree.",
    }


def _bind(return_value=None, side_effect=None):
    structured_llm = MagicMock()
    if side_effect is not None:
        structured_llm.invoke.side_effect = side_effect
    else:
        structured_llm.invoke.return_value = return_value
    plain_llm = MagicMock()
    plain_llm.invoke.return_value = AIMessage(content="FREETEXT")
    return structured_llm, plain_llm


def _invoke(structured_llm, plain_llm, schema=PortfolioDecision):
    return invoke_structured_or_freetext(
        structured_llm, plain_llm, "prompt",
        lambda d: f"**Rating**: {d.rating.value}", "Agent", schema=schema,
    )


def _envelope(raw, parsed=None, error=None):
    return {"raw": raw, "parsed": parsed, "parsing_error": error}


def _msg(content="", **kwargs):
    return AIMessage(content=content, **kwargs)


# ---------------------------------------------------------------------------
# 1. Refusal
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_refusal_in_additional_kwargs_raises_without_free_text():
    raw = _msg("I cannot help with that.", additional_kwargs={"refusal": "I cannot help with that."})
    structured_llm, plain_llm = _bind(return_value=_envelope(raw))
    with pytest.raises(StructuredResponseRefused):
        _invoke(structured_llm, plain_llm)
    assert plain_llm.invoke.call_count == 0
    assert structured_llm.invoke.call_count == 1


@pytest.mark.unit
def test_refusal_even_when_a_parsed_value_is_present():
    parsed = PortfolioDecision(**_payload())
    raw = _msg("", additional_kwargs={"refusal": "no"})
    structured_llm, plain_llm = _bind(return_value=_envelope(raw, parsed))
    with pytest.raises(StructuredResponseRefused):
        _invoke(structured_llm, plain_llm)
    assert plain_llm.invoke.call_count == 0


@pytest.mark.unit
def test_refusal_content_block_is_detected():
    raw = _msg(content=[{"type": "refusal", "refusal": "I won't answer this."}])
    structured_llm, plain_llm = _bind(return_value=_envelope(raw))
    with pytest.raises(StructuredResponseRefused):
        _invoke(structured_llm, plain_llm)
    assert plain_llm.invoke.call_count == 0


@pytest.mark.unit
def test_refusal_is_detected_from_content_blocks_property():
    raw = _msg(content=[
        {"type": "text", "text": "thinking"},
        {"type": "refusal", "refusal": "declined"},
    ])
    assert structured._refusal_text(raw) == "declined"
    structured_llm, plain_llm = _bind(return_value=_envelope(raw))
    with pytest.raises(StructuredResponseRefused):
        _invoke(structured_llm, plain_llm)
    assert plain_llm.invoke.call_count == 0


@pytest.mark.unit
def test_refusal_on_the_free_text_path_raises():
    plain_llm = MagicMock()
    plain_llm.invoke.return_value = _msg("", additional_kwargs={"refusal": "declined"})
    with pytest.raises(StructuredResponseRefused):
        _invoke(None, plain_llm)


# ---------------------------------------------------------------------------
# 1b. Truncation and empty responses
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("finish", ["length", "max_tokens"])
def test_truncated_parsed_result_is_not_rendered(finish):
    parsed = PortfolioDecision(**_payload())
    raw = _msg("{}", response_metadata={"finish_reason": finish})
    structured_llm, plain_llm = _bind(return_value=_envelope(raw, parsed))
    with pytest.raises(StructuredResponseTruncated):
        _invoke(structured_llm, plain_llm)
    assert plain_llm.invoke.call_count == 0


@pytest.mark.unit
@pytest.mark.parametrize("partial", [
    '{"rating": "Buy", "executive_summary": "s"',
    '```json\n{"rating": "Buy", "executive_summary": "s"',
    '```json\n{"rating": "Buy", "executive_summary": "s", "investment_thesis": "t"',
])
def test_partial_json_is_never_recovered_into_a_decision(partial):
    structured_llm, plain_llm = _bind(return_value=_envelope(_msg(partial)))
    with pytest.raises(StructuredResponseTruncated):
        _invoke(structured_llm, plain_llm)
    assert plain_llm.invoke.call_count == 0


@pytest.mark.unit
def test_tool_call_args_with_open_json_are_not_recovered():
    raw = _msg("", tool_calls=[
        {"name": "PortfolioDecision", "args": _payload(), "id": "1"},
    ])
    raw.response_metadata = {"finish_reason": "length"}
    structured_llm, plain_llm = _bind(return_value=_envelope(raw))
    with pytest.raises(StructuredResponseTruncated):
        _invoke(structured_llm, plain_llm)
    assert plain_llm.invoke.call_count == 0


@pytest.mark.unit
def test_pure_empty_response_is_not_treated_as_parse_failure():
    structured_llm, plain_llm = _bind(return_value=_envelope(_msg("")))
    with pytest.raises(StructuredResponseTruncated):
        _invoke(structured_llm, plain_llm)
    assert plain_llm.invoke.call_count == 0


@pytest.mark.unit
def test_empty_parsed_result_dict_counts_as_empty():
    structured_llm, plain_llm = _bind(return_value={"raw": None, "parsed": None, "parsing_error": None})
    with pytest.raises(StructuredResponseTruncated):
        _invoke(structured_llm, plain_llm)
    assert plain_llm.invoke.call_count == 0


@pytest.mark.unit
def test_non_empty_prose_without_parse_error_still_falls_back_once():
    structured_llm, plain_llm = _bind(return_value=_envelope(_msg("**Rating**: Buy\nprose")))
    assert _invoke(structured_llm, plain_llm) == "FREETEXT"
    assert plain_llm.invoke.call_count == 1


# ---------------------------------------------------------------------------
# 1c. Truncation detection must not reject well-formed answers
# ---------------------------------------------------------------------------

_BRACE_THESIS = 'Cash flow improved {revenue up 12%} and margins held; see {model: base}.'


def _decision_with_braces() -> dict:
    payload = _payload()
    payload["investment_thesis"] = _BRACE_THESIS
    return payload


@pytest.mark.unit
def test_valid_json_with_braces_in_string_is_not_truncated():
    import json

    parsed = PortfolioDecision(**_decision_with_braces())
    assert "{" in parsed.investment_thesis
    raw = _msg(json.dumps(_decision_with_braces()), response_metadata={"finish_reason": "stop"})
    structured_llm, plain_llm = _bind(return_value=_envelope(raw))
    assert "**Rating**: Buy" in _invoke(structured_llm, plain_llm)
    assert plain_llm.invoke.call_count == 0


@pytest.mark.unit
@pytest.mark.parametrize("thesis", [
    'Unbalanced { inside a string',
    'Has } closing brace only',
    'Nested {"a": {"b": "}"}} escapes and \\"quotes\\"',
    'Trailing backslash \\',
    "Lots of {braces}}} with \"quoted {json}\" text",
])
def test_valid_parsed_result_with_odd_string_content_is_rendered(thesis):
    import json

    payload = _payload()
    payload["investment_thesis"] = thesis
    parsed = PortfolioDecision(**payload)
    raw = _msg(json.dumps(payload), response_metadata={"finish_reason": "stop"})
    structured_llm, plain_llm = _bind(return_value=_envelope(raw, parsed))
    assert "**Rating**: Buy" in _invoke(structured_llm, plain_llm)
    assert plain_llm.invoke.call_count == 0


@pytest.mark.unit
def test_parsed_result_with_length_finish_reason_is_still_rejected():
    parsed = PortfolioDecision(**_decision_with_braces())
    raw = _msg("{}", response_metadata={"finish_reason": "length"})
    structured_llm, plain_llm = _bind(return_value=_envelope(raw, parsed))
    with pytest.raises(StructuredResponseTruncated):
        _invoke(structured_llm, plain_llm)
    assert plain_llm.invoke.call_count == 0


@pytest.mark.unit
@pytest.mark.parametrize("markdown", [
    "**Rating**: Buy\n\nUse the {ticker} template.\n\n```python\nprint('{ok')\n```",
    "## Report\n\n```\nunbalanced { fence body\n```\n\nNo closing brace written.",
    "**Rating**: Hold\n\n| Metric | Value |\n|---|---|\n| {\"x\": 1} | ok |",
])
def test_markdown_with_braces_is_not_truncated(markdown):
    # Prose is not JSON: brace symbols inside it are content, not structure.
    response = _msg(markdown)
    assert structured._is_truncated(response) is False


@pytest.mark.unit
def test_unterminated_json_document_is_truncated():
    assert structured._is_truncated(_msg('{"rating": "Buy", "executive_summary": "s"')) is True


@pytest.mark.unit
def test_malformed_json_that_is_not_cut_off_is_not_truncated():
    # Wrong type in a complete document is a parse miss, not truncation.
    assert structured._is_truncated(_msg('{"rating": 7, "executive_summary": "s"}')) is False


# ---------------------------------------------------------------------------
# 1d. Free-text truncation
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("finish", ["length", "max_tokens", "max_output_tokens"])
def test_direct_free_text_truncation_raises(finish):
    plain_llm = MagicMock()
    plain_llm.invoke.return_value = _msg(
        "**Rating**: Buy\n\nHalf a report", response_metadata={"finish_reason": finish},
    )
    with pytest.raises(StructuredResponseTruncated):
        _invoke(None, plain_llm)
    assert plain_llm.invoke.call_count == 1


@pytest.mark.unit
@pytest.mark.parametrize("finish", ["length", "max_tokens", "max_output_tokens"])
def test_fallback_free_text_truncation_raises(finish):
    structured_llm, plain_llm = _bind(return_value=_envelope(_msg("prose, no JSON")))
    plain_llm.invoke.return_value = _msg(
        "**Rating**: Buy\n\npartial", response_metadata={"finish_reason": finish},
    )
    with pytest.raises(StructuredResponseTruncated):
        _invoke(structured_llm, plain_llm)
    assert structured_llm.invoke.call_count == 1
    assert plain_llm.invoke.call_count == 1


@pytest.mark.unit
def test_complete_free_text_with_stop_reason_is_returned():
    plain_llm = MagicMock()
    plain_llm.invoke.return_value = _msg(
        "**Rating**: Buy\n\nfull report {with braces}", response_metadata={"finish_reason": "stop"},
    )
    assert _invoke(None, plain_llm).startswith("**Rating**: Buy")


# ---------------------------------------------------------------------------
# 2. Non-parse errors carried in parsing_error
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("exc", [
    RuntimeError("provider blew up"),
    _StatusError("400 invalid parameter"),
    _StatusError("connection reset"),
    _StatusError("401 unauthorized"),
])
def test_non_parse_parsing_error_propagates(exc):
    structured_llm, plain_llm = _bind(return_value=_envelope(_msg("something"), None, exc))
    with pytest.raises(type(exc)) as caught:
        _invoke(structured_llm, plain_llm)
    assert caught.value is exc
    assert plain_llm.invoke.call_count == 0


@pytest.mark.unit
def test_non_parse_parsing_error_propagates_even_when_parsed_is_present():
    parsed = PortfolioDecision(**_payload())
    exc = RuntimeError("weird")
    structured_llm, plain_llm = _bind(return_value=_envelope(_msg(""), parsed, exc))
    with pytest.raises(RuntimeError):
        _invoke(structured_llm, plain_llm)
    assert plain_llm.invoke.call_count == 0


@pytest.mark.unit
def test_real_output_parser_exception_allows_recovery():
    raw = _msg('{"rating": "Sell", "executive_summary": "s", "investment_thesis": "t"}')
    structured_llm, plain_llm = _bind(return_value=_envelope(raw, None, OutputParserException("bad")))
    assert "**Rating**: Sell" in _invoke(structured_llm, plain_llm)
    assert plain_llm.invoke.call_count == 0


@pytest.mark.unit
def test_real_validation_error_allows_recovery_from_tool_call():
    try:
        PortfolioDecision(**_payload("Strong Buy"))
    except ValidationError as exc:
        real_validation = exc
    raw = _msg("", tool_calls=[{"name": "PortfolioDecision", "args": _payload(), "id": "1"}])
    structured_llm, plain_llm = _bind(return_value=_envelope(raw, None, real_validation))
    assert "**Rating**: Buy" in _invoke(structured_llm, plain_llm)
    assert plain_llm.invoke.call_count == 0


# ---------------------------------------------------------------------------
# 3. Recovery scope
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_unrelated_tool_call_is_not_adopted():
    raw = _msg("", tool_calls=[
        {"name": "UnrelatedTool", "args": _payload(), "id": "1"},
    ])
    structured_llm, plain_llm = _bind(return_value=_envelope(raw))
    assert _invoke(structured_llm, plain_llm) == "FREETEXT"
    assert plain_llm.invoke.call_count == 1


@pytest.mark.unit
def test_explicit_alias_is_accepted():
    from typing import ClassVar

    class AliasedDecision(PortfolioDecision):
        structured_tool_aliases: ClassVar[frozenset[str]] = frozenset({"make_decision"})

    raw = _msg("", tool_calls=[{"name": "make_decision", "args": _payload(), "id": "1"}])
    structured_llm, plain_llm = _bind(return_value=_envelope(raw))
    out = invoke_structured_or_freetext(
        structured_llm, plain_llm, "prompt",
        lambda d: f"**Rating**: {d.rating.value}", "Agent", schema=AliasedDecision,
    )
    assert "**Rating**: Buy" in out
    assert plain_llm.invoke.call_count == 0


@pytest.mark.unit
def test_conflicting_tool_call_candidates_are_not_silently_picked():
    raw = _msg("", tool_calls=[
        {"name": "PortfolioDecision", "args": _payload("Buy"), "id": "1"},
        {"name": "PortfolioDecision", "args": _payload("Sell"), "id": "2"},
    ])
    structured_llm, plain_llm = _bind(return_value=_envelope(raw))
    assert _invoke(structured_llm, plain_llm) == "FREETEXT"
    assert plain_llm.invoke.call_count == 1


@pytest.mark.unit
def test_identical_duplicate_tool_calls_recover_once():
    args = _payload("Hold")
    raw = _msg("", tool_calls=[
        {"name": "PortfolioDecision", "args": args, "id": "1"},
        {"name": "PortfolioDecision", "args": dict(args), "id": "2"},
    ])
    structured_llm, plain_llm = _bind(return_value=_envelope(raw))
    assert "**Rating**: Hold" in _invoke(structured_llm, plain_llm)


@pytest.mark.unit
@pytest.mark.parametrize("prose", [
    'Consider {"rating": "Buy", "executive_summary": "s", "investment_thesis": "t"} but reject it.',
    'A counter-example would be {"rating": "Sell", "executive_summary": "s", "investment_thesis": "t"}.',
    'I will not choose {"rating": "Buy", "executive_summary": "s", "investment_thesis": "t"}',
])
def test_json_embedded_in_prose_is_never_promoted(prose):
    structured_llm, plain_llm = _bind(return_value=_envelope(_msg(prose)))
    assert _invoke(structured_llm, plain_llm) == "FREETEXT"
    assert plain_llm.invoke.call_count == 1


@pytest.mark.unit
def test_whole_message_json_recovers():
    raw = _msg('{"rating": "Overweight", "executive_summary": "s", "investment_thesis": "t"}')
    structured_llm, plain_llm = _bind(return_value=_envelope(raw))
    assert "**Rating**: Overweight" in _invoke(structured_llm, plain_llm)
    assert plain_llm.invoke.call_count == 0


@pytest.mark.unit
def test_recovery_never_fills_missing_fields():
    structured_llm, plain_llm = _bind(return_value=_envelope(_msg('{"rating": "Buy"}')))
    assert _invoke(structured_llm, plain_llm) == "FREETEXT"
    assert plain_llm.invoke.call_count == 1


# ---------------------------------------------------------------------------
# 4. Exception recognition and binding fallback
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_same_named_foreign_exception_is_not_a_parse_failure():
    class OutputParserException(Exception):  # noqa: N801 - deliberately shadowing
        pass

    structured_llm, plain_llm = _bind(side_effect=OutputParserException("fake"))
    with pytest.raises(OutputParserException):
        _invoke(structured_llm, plain_llm)
    assert plain_llm.invoke.call_count == 0


@pytest.mark.unit
def test_attribute_error_inside_binder_propagates():
    llm = MagicMock()
    llm.with_structured_output.side_effect = AttributeError("client bug inside binder")
    with pytest.raises(AttributeError):
        bind_structured(llm, PortfolioDecision, "PM")


@pytest.mark.unit
def test_missing_binding_method_means_unsupported():
    class Bare:
        pass

    assert bind_structured(Bare(), PortfolioDecision, "PM") is None


@pytest.mark.unit
def test_internal_type_error_is_not_retried_as_legacy_binding():
    llm = MagicMock()
    llm.with_structured_output.side_effect = TypeError("bad inner signature")
    with pytest.raises(TypeError):
        bind_structured(llm, PortfolioDecision, "PM")
    assert llm.with_structured_output.call_count == 1


@pytest.mark.unit
def test_langchain_unsupported_argument_value_error_uses_legacy_binding():
    llm = MagicMock()
    llm.with_structured_output.side_effect = [
        ValueError("Received unsupported arguments {'include_raw': True}"),
        "legacy",
    ]
    llm.with_structured_output.__signature__ = None
    assert bind_structured(llm, PortfolioDecision, "PM") == "legacy"
    assert llm.with_structured_output.call_count == 2


@pytest.mark.unit
def test_binder_with_explicit_include_raw_never_retried_on_value_error():
    def binder(schema, *, include_raw=False):
        raise ValueError("Received unsupported arguments {'include_raw': True}")

    llm = MagicMock()
    llm.with_structured_output = binder
    with pytest.raises(ValueError):
        bind_structured(llm, PortfolioDecision, "PM")


@pytest.mark.unit
def test_declared_signature_without_include_raw_binds_plainly():
    calls = []

    def binder(schema):
        calls.append(schema)
        return "plain"

    llm = MagicMock()
    llm.with_structured_output = binder
    assert bind_structured(llm, PortfolioDecision, "PM") == "plain"
    assert calls == [PortfolioDecision]


@pytest.mark.unit
def test_declared_include_raw_signature_receives_the_kwarg():
    calls = []

    def binder(schema, *, include_raw=False):
        calls.append(include_raw)
        return "raw-bound"

    llm = MagicMock()
    llm.with_structured_output = binder
    assert bind_structured(llm, PortfolioDecision, "PM") == "raw-bound"
    assert calls == [True]


# ---------------------------------------------------------------------------
# 5. Log redaction
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_failure_log_does_not_leak_raw_output(caplog):
    secret = "SENSITIVE-MODEL-OUTPUT-9f3a api_key=sk-live-AAA http://user:pw@host/x"
    error = OutputParserException(secret, llm_output=secret)
    raw = _msg(secret)
    structured_llm, plain_llm = _bind(return_value=_envelope(raw, None, error))
    with caplog.at_level(logging.DEBUG, logger="tradingagents.agents.utils.structured"):
        _invoke(structured_llm, plain_llm)
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert secret not in joined
    assert "sk-live-AAA" not in joined
    assert "SENSITIVE-MODEL-OUTPUT" not in joined
    assert "reason=parse_error" in joined


@pytest.mark.unit
def test_validation_error_log_does_not_leak_input_values(caplog):
    secret = "SENSITIVE-INPUT-VALUE-7c1"
    try:
        PortfolioDecision(rating=secret, executive_summary="s", investment_thesis="t")
    except ValidationError as exc:
        validation = exc
    structured_llm, plain_llm = _bind(return_value=_envelope(_msg("x"), None, validation))
    with caplog.at_level(logging.DEBUG, logger="tradingagents.agents.utils.structured"):
        _invoke(structured_llm, plain_llm)
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert secret not in joined
    assert "reason=validation_error" in joined


@pytest.mark.unit
def test_ambiguous_candidate_log_does_not_leak_values(caplog):
    secret = "SENSITIVE-CANDIDATE-1b2"
    raw = _msg("", tool_calls=[
        {"name": "PortfolioDecision", "args": {
            "rating": "Buy", "executive_summary": secret, "investment_thesis": "t"}, "id": "1"},
        {"name": "PortfolioDecision", "args": {
            "rating": "Sell", "executive_summary": secret, "investment_thesis": "t"}, "id": "2"},
    ])
    structured_llm, plain_llm = _bind(return_value=_envelope(raw))
    with caplog.at_level(logging.DEBUG, logger="tradingagents.agents.utils.structured"):
        _invoke(structured_llm, plain_llm)
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert secret not in joined


# ---------------------------------------------------------------------------
# Regressions kept: happy path and single bounded fallback
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_success_path_still_renders():
    parsed = PortfolioDecision(**_payload())
    structured_llm, plain_llm = _bind(return_value=_envelope(_msg("{}"), parsed))
    assert "**Rating**: Buy" in _invoke(structured_llm, plain_llm)
    assert plain_llm.invoke.call_count == 0


@pytest.mark.unit
def test_free_text_failure_propagates_without_loop():
    structured_llm, plain_llm = _bind(return_value=_envelope(_msg("prose")))
    plain_llm.invoke.side_effect = _StatusError("500")
    with pytest.raises(_StatusError):
        _invoke(structured_llm, plain_llm)
    assert plain_llm.invoke.call_count == 1
