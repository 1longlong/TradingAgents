"""Shared helpers for invoking an agent with structured output and a bounded fallback.

The Portfolio Manager, Trader, Research Manager, and Sentiment Analyst follow
the same canonical pattern:

1. At agent creation, wrap the LLM with ``with_structured_output(Schema,
   include_raw=True)``. ``include_raw`` hands back ``{"raw", "parsed",
   "parsing_error"}`` so a parse/validation miss arrives as data next to the
   model's own response instead of raising and losing it. If the provider has
   no structured-output method at all, ``None`` is bound and the agent uses
   free-text generation from the start.
2. At invocation, a parse or validation miss is first repaired **locally**
   from the raw response (the schema's own tool call, then a whole-message
   JSON payload), and the repaired object must pass the same schema. Only an
   explicit "no structured output" or an unrecoverable parse failure reaches
   a free-text call, and that call is made at most once.
3. Authentication/permission, configuration/parameter, network, rate-limit,
   5xx, and unknown internal errors are **propagated**. They are not parse
   failures, so neither a retry nor a free-text regeneration is attempted.
   Transient network retries remain the SDK's job (``llm_max_retries``).
4. A model refusal is final: no local recovery, no free-text regeneration.
   A truncated answer is final too: none of its partial JSON may be salvaged
   into a decision. Both raise :class:`StructuredResponseRefused` /
   :class:`StructuredResponseTruncated`.

Rendering stays outside the model/parse guard: a broken renderer is a bug in
our code, not a reason to spend another generation or to hide its error.
"""

from __future__ import annotations

import inspect
import json
import logging
import re
from collections.abc import Callable
from typing import Any, TypeVar

from langchain_core.exceptions import OutputParserException
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Schema-only structured output binds exactly one tool (the schema itself), so a
# model that reaches for a search tool emits an unknown tool call and the whole
# structured attempt is discarded for a free-text retry. Agents on this path
# state the constraint explicitly rather than relying on the binding alone
# (#1130).
NO_EXTERNAL_TOOLS = (
    "Use only the evidence provided in this prompt. Do not call external tools "
    "or search the web; if something is missing, say so explicitly."
)

# Safe, greppable reason codes. Logs carry these and the exception type only:
# parser errors embed the raw model output and a ``ValidationError`` embeds
# the offending input values, so neither is ever formatted into a message.
REASON_PARSE_ERROR = "parse_error"
REASON_VALIDATION_ERROR = "validation_error"
REASON_EMPTY_RESPONSE = "empty_response"
REASON_NO_STRUCTURED_RESULT = "no_structured_result"
REASON_REFUSED = "refused"
REASON_TRUNCATED = "truncated"

_FENCE_RE = re.compile(r"^```[A-Za-z0-9_-]*\s*\n?(.*?)\n?```\s*$", re.DOTALL)

# Finish reasons that mean the answer is incomplete, whatever it parsed to.
_TRUNCATED_FINISH_REASONS = frozenset({"length", "max_tokens", "max_output_tokens"})
# Content-block / response-metadata keys that carry refusal text.
_REFUSAL_BLOCK_TYPES = frozenset({"refusal", "output_refusal"})


class StructuredResponseError(Exception):
    """Base for structured responses that ended in a non-recoverable state."""

    reason: str = "unusable"

    def __init__(self, agent: str) -> None:
        self.agent = agent
        super().__init__(f"{agent}: structured response {self.reason}")


class StructuredResponseRefused(StructuredResponseError):
    """The model explicitly refused to answer."""

    reason = REASON_REFUSED


class StructuredResponseTruncated(StructuredResponseError):
    """The model's answer was cut off (token limit), so it is incomplete."""

    reason = REASON_TRUNCATED


def _accepts_include_raw(binder: Any) -> bool | None:
    """Whether ``with_structured_output`` declares an ``include_raw`` parameter.

    ``True``/``False`` from a readable signature; ``None`` when no signature
    can be read (unavailable or ambiguous), in which case the caller must not
    infer a missing parameter from a ``TypeError``.
    """
    try:
        params = inspect.signature(binder).parameters.values()
    except (TypeError, ValueError):
        return None
    return any(
        param.name == "include_raw"
        or (param.kind is inspect.Parameter.VAR_KEYWORD)
        for param in params
    )


def _is_unsupported_argument_error(exc: BaseException) -> bool:
    """Whether ``exc`` says the *binding call* itself rejected a keyword.

    langchain's base chat model raises ``ValueError("Received unsupported
    arguments {'include_raw': ...}")`` when the wrapper cannot accept the
    kwarg. Only that message family qualifies: an arbitrary ``TypeError`` /
    ``ValueError`` raised inside the binder is a real failure and propagates.
    """
    if not isinstance(exc, (TypeError, ValueError)):
        return False
    return "include_raw" in str(exc) and (
        "unsupported argument" in str(exc) or "unexpected keyword" in str(exc)
    )


def bind_structured(llm: Any, schema: type[T], agent_name: str) -> Any | None:
    """Return ``llm.with_structured_output(schema, include_raw=True)`` or ``None``.

    ``include_raw`` is requested so a parse/validation miss keeps the model's
    raw response for local recovery. If the binder's signature does not
    declare the parameter, or langchain rejects it as unsupported, the plain
    binding is used once (raw response unavailable). Returns ``None`` only when
    the provider explicitly has no structured-output mode; a warning is logged
    so the user knows every call will be free text.
    """
    binder = getattr(llm, "with_structured_output", None)
    if binder is None:
        logger.warning(
            "%s: model has no with_structured_output (%s); falling back to free-text generation",
            agent_name, "attribute_missing",
        )
        return None

    try:
        if _accepts_include_raw(binder) is False:
            logger.debug(
                "%s: with_structured_output declares no include_raw; "
                "binding without raw response", agent_name,
            )
            return binder(schema)
        return binder(schema, include_raw=True)
    except NotImplementedError as exc:
        logger.warning(
            "%s: provider does not support with_structured_output (%s); "
            "falling back to free-text generation",
            agent_name, type(exc).__name__,
        )
        return None
    except (TypeError, ValueError) as exc:
        included_raw_args = _accepts_include_raw(binder)
        if included_raw_args is False or not _is_unsupported_argument_error(exc):
            raise
        logger.debug(
            "%s: with_structured_output rejected include_raw (%s); "
            "binding without raw response", agent_name, type(exc).__name__,
        )
        return binder(schema)


def _unwrap(result: Any) -> tuple[Any, T | None, BaseException | None]:
    """Split an ``include_raw`` payload into ``(raw, parsed, parsing_error)``.

    A bare parsed object (no ``include_raw`` support) is passed through with a
    ``None`` raw response. No response is ever invented when it is absent.
    """
    if isinstance(result, dict) and "parsed" in result:
        return result.get("raw"), result.get("parsed"), result.get("parsing_error")
    return None, result, None


def _is_parse_failure(exc: BaseException | None) -> bool:
    """Whether ``exc`` is a parse/validation miss, never a provider failure.

    Only the real types count: pydantic's ``ValidationError`` (which includes
    the ``PydanticOutputParser`` errors langchain raises) and langchain-core's
    ``OutputParserException``, a project dependency. A ``ValueError`` from
    elsewhere, or an unrelated class that happens to share a name in another
    module, is not a parse failure.
    """
    return isinstance(exc, (ValidationError, OutputParserException))


def _reason_code(exc: BaseException | None) -> str:
    """A safe, non-leaking reason code for ``exc``."""
    if exc is None:
        return REASON_NO_STRUCTURED_RESULT
    if isinstance(exc, ValidationError):
        return REASON_VALIDATION_ERROR
    if isinstance(exc, OutputParserException):
        return REASON_PARSE_ERROR
    return REASON_NO_STRUCTURED_RESULT


def _message_content(raw: Any) -> str:
    """The text body of a raw model response, or ``""`` when there is none."""
    if raw is None:
        return ""
    content = getattr(raw, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return ""


def _refusal_text(raw: Any) -> str | None:
    """The model's refusal message, if it refused, else ``None``.

    Covers the Chat Completions field (``additional_kwargs["refusal"]``,
    set by langchain-openai), a ``refusal`` block in ``content_blocks``, and
    a ``{"type": "refusal", ...}`` item in a list ``content``.
    """
    if raw is None:
        return None
    extra = getattr(raw, "additional_kwargs", None) or {}
    for container in (extra, getattr(raw, "response_metadata", None) or {}):
        if isinstance(container, dict):
            refusal = container.get("refusal")
            if isinstance(refusal, str) and refusal.strip():
                return refusal
    blocks = getattr(raw, "content_blocks", None) or []
    content = getattr(raw, "content", None)
    for block in list(blocks) + (content if isinstance(content, list) else []):
        if isinstance(block, dict) and str(block.get("type", "")).lower() in _REFUSAL_BLOCK_TYPES:
            text = block.get("refusal") or block.get("text")
            if isinstance(text, str) and text.strip():
                return text
    return None


def _finish_reason(raw: Any) -> str | None:
    """The provider's stop reason, normalised to lower case, or ``None``."""
    if raw is None:
        return None
    extra = getattr(raw, "additional_kwargs", None) or {}
    meta = getattr(raw, "response_metadata", None) or {}
    for container in (extra, meta):
        if isinstance(container, dict):
            reason = container.get("finish_reason") or container.get("stop_reason")
            if isinstance(reason, str) and reason:
                return reason.lower()
    return None


def _is_blank(raw: Any) -> bool:
    """Whether the response carries no text and no tool calls at all."""
    if raw is None:
        return True
    return not _message_content(raw).strip() and not (getattr(raw, "tool_calls", None) or [])


def _looks_like_json(text: str) -> bool:
    """Whether ``text`` (optionally fenced) is meant to be a JSON document."""
    body = text.strip()
    if body.startswith("```"):
        # Strip the opening fence even when it was never closed: a document
        # cut off mid-block is still meant to be JSON.
        body = re.sub(r"^```[A-Za-z0-9_-]*\s*\n?", "", body, count=1).strip()
    return body.startswith("{")


def _json_body(text: str) -> str:
    """The candidate JSON document inside ``text`` (fence stripped)."""
    body = text.strip()
    if body.startswith("```"):
        body = re.sub(r"^```[A-Za-z0-9_-]*\s*\n?", "", body, count=1)
        if body.rstrip().endswith("```"):
            body = body.rstrip()[:-3]
        return body.strip()
    return body


def _is_truncated(raw: Any) -> bool:
    """Whether the model was cut off by its token limit or mid-JSON.

    An explicit ``finish_reason`` wins: a ``length``/``max_tokens`` answer is
    incomplete even if a parser salvaged something from it. Without such a
    status, only a response that *is* a JSON document is inspected, and only
    for a structurally unterminated one (``json.loads`` reports an unclosed
    structure). Brace counting is never used: braces inside string literals,
    escapes, and Markdown prose are content, not structure, and a fenced or
    brace-containing report is not evidence of truncation.
    """
    if raw is None:
        return False
    if _finish_reason(raw) in _TRUNCATED_FINISH_REASONS:
        return True
    text = _message_content(raw).strip()
    if not text or not _looks_like_json(text):
        return False
    body = _json_body(text)
    try:
        json.loads(body)
    except json.JSONDecodeError as exc:
        # Only a document that ends mid-structure was cut off. A JSON payload
        # that is merely malformed (wrong type, stray token) is a parse miss
        # and follows the normal recovery/fallback path instead.
        return "Unterminated string" in exc.msg or exc.pos >= len(body.rstrip()) - 1
    return False


def _tool_call_args(raw: Any, schema: type[T]) -> list[Any]:
    """Argument payloads from this schema's tool call only.

    Only calls named for the schema (``schema.__name__`` or its explicit
    aliases) are eligible: a call to some other tool is a different answer,
    never a substitute decision. Duplicate candidates are de-duplicated; the
    caller rejects conflicting ones instead of picking the first.
    """
    names = {schema.__name__, *getattr(schema, "structured_tool_aliases", frozenset())}
    named: list[Any] = []
    for call in getattr(raw, "tool_calls", None) or []:
        if isinstance(call, dict):
            args, name = call.get("args"), call.get("name")
        else:
            args, name = getattr(call, "args", None), getattr(call, "name", None)
        if name in names and isinstance(args, dict) and args not in named:
            named.append(args)
    return named


def _json_payloads(text: str) -> list[str]:
    """Whole-message JSON payloads in ``text``, most specific first.

    Only two forms qualify: a message wrapped in a single ```json fence, and a
    message that *is* a JSON object. Prose is never scanned for a balanced
    ``{}`` span, so an example, a counter-example, or a rejected alternative
    quoted inside an answer can never be promoted to the decision.
    """
    if not text or not text.strip():
        return []
    body = text.strip()
    candidates: list[str] = []
    fenced = _FENCE_RE.match(body)
    if fenced:
        candidates.append(fenced.group(1).strip())
    if body.startswith("{") and body.endswith("}"):
        candidates.append(body)
    seen: set[str] = set()
    return [c for c in candidates if c and not (c in seen or seen.add(c))]


def _recover_locally(raw: Any, schema: type[T], agent_name: str) -> T | None:
    """Rebuild ``schema`` from the raw response, or ``None``.

    Tries this schema's tool-call arguments, then whole-message JSON. Each
    candidate must validate against ``schema`` unchanged: no field is filled
    in and no value is guessed. Several distinct candidates that validate but
    disagree are ambiguous and are not recovered at all.
    """
    candidates: list[T] = []
    for args in _tool_call_args(raw, schema):
        try:
            candidates.append(schema.model_validate(args))
        except ValidationError:
            continue
    for payload in _json_payloads(_message_content(raw)):
        try:
            candidates.append(schema.model_validate_json(payload))
        except (ValidationError, ValueError):
            continue
    distinct = {candidate.model_dump_json() for candidate in candidates}
    if not distinct:
        return None
    if len(distinct) > 1:
        logger.warning(
            "%s: %d distinct structured candidates in one raw response; not recovering",
            agent_name, len(distinct),
        )
        return None
    return candidates[0]


def invoke_structured_or_freetext(
    structured_llm: Any | None,
    plain_llm: Any,
    prompt: Any,
    render: Callable[[T], str],
    agent_name: str,
    schema: type[T] | None = None,
) -> str:
    """Run the structured call, recover or derive a typed result, then render.

    ``schema`` enables local recovery from the raw response and is required
    for a ``bind_structured`` binding to be repaired at all; callers built
    against the older signature still get every other guarantee (at most one
    free-text call, parse-only fallback, propagated provider errors).

    Provider failures (auth/permission, bad request, network, rate limit, 5xx,
    unknown) propagate, including when they arrive in ``parsing_error``.
    Refusals and truncated answers raise without any further generation.
    Rendering is outside the guard and its errors propagate. The free-text
    call is made at most once and its own failure propagates.
    """
    if structured_llm is not None:
        try:
            result = structured_llm.invoke(prompt)
        except Exception as exc:
            if not _is_parse_failure(exc):
                raise
            raw, parsed, parsing_error = None, None, exc
        else:
            raw, parsed, parsing_error = _unwrap(result)

        if _refusal_text(raw) is not None:
            # A refusal is a final answer. Regenerating in another format
            # would route around it.
            raise StructuredResponseRefused(agent_name)

        if parsing_error is not None and not _is_parse_failure(parsing_error):
            # A non-parse error rode along in the envelope (RuntimeError,
            # a bad request, a network failure): it is not a parse miss.
            raise parsing_error

        if _is_truncated(raw):
            # The provider stopped mid-answer (token limit or a fence/JSON cut
            # open). Whatever parsed is at best a prefix, and recovering from
            # the fragment would turn it into a decision.
            raise StructuredResponseTruncated(agent_name)

        if parsed is not None:
            return render(parsed)

        parse_miss = _reason_code(parsing_error)
        if parse_miss == REASON_NO_STRUCTURED_RESULT and _is_blank(raw):
            # Empty structured answer. LangChain reports "nothing parsed" the
            # same way, so this is judged from the response body: only an
            # answer with content (or a tool call) is a parse miss worth one
            # retry.
            raise StructuredResponseTruncated(agent_name)

        recovered = _recover_locally(raw, schema, agent_name) if schema is not None else None
        if recovered is not None:
            logger.info(
                "%s: recovered structured result locally (reason=%s)",
                agent_name, parse_miss,
            )
            return render(recovered)

        logger.warning(
            "%s: structured output unusable (reason=%s); retrying once as free text",
            agent_name, parse_miss,
        )

    response = plain_llm.invoke(prompt)
    content = response.content
    if _refusal_text(response) is not None:
        raise StructuredResponseRefused(agent_name)
    if _finish_reason(response) in _TRUNCATED_FINISH_REASONS:
        # The provider stopped at its token limit: the text is a partial
        # report. Return nothing rather than half an analysis, and do not
        # spend another generation on it.
        raise StructuredResponseTruncated(agent_name)
    if not isinstance(content, str) or not content.strip():
        # An empty free-text answer cannot become a report. Fail instead of
        # letting a blank decision propagate as if it were an analysis.
        raise ValueError(f"{agent_name}: free-text fallback returned no content")
    return content
