"""Shared helpers for invoking an agent with structured output and a graceful fallback.

The Portfolio Manager, Trader, and Research Manager all follow the same
canonical pattern:

1. At agent creation, wrap the LLM with ``with_structured_output(Schema)``
   so the model returns a typed Pydantic instance. If the provider does
   not support structured output (rare; mostly older Ollama models), the
   wrap is skipped and the agent uses free-text generation instead.
2. At invocation, run the structured call and render the result back to
   markdown. If the structured call itself fails for any reason
   (malformed JSON from a weak model, transient provider issue), fall
   back to a plain ``llm.invoke`` so the pipeline never blocks.

Centralising the pattern here keeps the agent factories small and ensures
all three agents log the same warnings when fallback fires.

Two cross-cutting concerns meet at this module:

* **Accounting (ADR-009).** A structured attempt is settled from the RAW
  transport usage (``include_raw=True``), so a typed result still records the
  provider's real token counts. Settlement only ever wraps the OUTBOUND call:
  parsing, sanitizing and rendering happen after settlement, so a downstream
  failure can never turn a known usage into an unknown-cost record.
* **Single-pass finalisation (CAND-01).** ``finalize_single_pass`` replaces the
  write-prose-then-restructure pair with one loop whose terminal turn emits the
  schema. That loop issues several outbound calls through ONE model object, so
  each call is instrumented at the transport boundary by
  :class:`UsageSettlementHandler` — N outbound attempts are N settled
  invocations, never one nested or doubled settlement.
"""

# ADR-012-error-handling-merge-integration.md: contract typing/security, NFR-BC-001, INV-1.

from __future__ import annotations

import inspect
import json
import logging
import re
import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, ValidationError

from tradingagents.debate.usage_capture import (
    BudgetDeniedError,
    UsageCapture,
    get_active_capture,
    instrumented_model_call,
)
from tradingagents.observability import record_structured_attempt

logger = logging.getLogger(__name__)

#: Parameter names of ``BaseChatModel.with_structured_output``. Used only to
#: decide whether an opaque ``TypeError`` message names a *different* argument
#: (a real defect) or none at all (the ``include_raw`` rejection shape).
_WITH_STRUCTURED_OUTPUT_PARAMS = frozenset({
    "kwargs",
    "schema",
    "include_raw",
    "method",
    "strict",
    "tools",
    "tool_choice",
    "ls_structured_output_format",
})

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

# Map the agent name to its whole-run usage phase (ADR-009). Unknown agents fall
# back to a constant ``unknown_phase`` so a free-form string is never persisted.
_AGENT_PHASE = {
    "Research Manager": "research_manager",
    "Trader": "trader",
    "Portfolio Manager": "portfolio",
    "Sentiment Analyst": "analyst",
}

# Sentences with which the analyst system prompts ask for a *prose layout*.
# They describe the free-text report, so they must not reach the schema-bound
# call, where they compete with the schema tool and cause the parser to return
# nothing (measured: 1/3 success with them, 3/3 without). A marker may open a
# sentence in the middle of the prompt (the fundamentals/news prompts name
# their tools *after* it), so only the layout sentence starting at the marker is
# removed, never the rest of the prompt.
ANALYST_FREE_TEXT_MARKERS = (
    "Write a very detailed and nuanced report of the trends you observe.",
    "Please write a comprehensive report",
    "Make sure to append a Markdown table",
)

# Schema-only structured output binds exactly one tool (the schema). A prompt
# that still tells the model to call a data tool makes it emit an unknown tool
# call, the parser raises ("Unknown tool type: 'get_verified_market_snapshot'")
# and the report falls back. Measured on the live model: 2 failures out of 3
# before this was handled. The instruction is therefore neutralised for the
# structured call only -- the tool has already been called by then, and its
# result is in the history.
STRUCTURED_TOOL_INSTRUCTION_RE = (
    (
        "Before writing the final report, call get_verified_market_snapshot for "
        "this ticker and the current date, and treat it as the source of truth",
        "Treat the get_verified_market_snapshot output already retrieved in this "
        "conversation as the source of truth",
    ),
)

STRUCTURED_FINALISATION_INSTRUCTION = (
    "Emit your final analyst report now as the structured object defined by the "
    "tool schema. Fill every field from the analysis you have just completed: "
    "quote only values that appeared in the tool output, leave a list empty "
    "rather than inventing an entry, and use the Unknown stance if the data you "
    "needed could not be retrieved."
)

# CAND-01: the single-pass terminal call. The same instruction as above, but
# this one is delivered *on the call that would otherwise have written prose*,
# so it has to say how to use the tools it is still bound to. The model may keep
# fetching data; it only has to stop asking for tools when it is ready to answer.
SINGLE_PASS_FINALISATION_INSTRUCTION = (
    STRUCTURED_FINALISATION_INSTRUCTION
    + " If a tool result is still missing and you need it, call that data tool"
    " first; otherwise answer with the schema's tool call now."
)

# Upper bound on schema-bound rounds for one analyst node (data-tool round,
# then the next). It is a safety stop, not a policy: the model normally answers
# with the schema on its first or second round. When it is hit, the run falls
# back to the RC1 two-call finalisation rather than dropping evidence.
SINGLE_PASS_MAX_ROUNDS = 4


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
    unique = []
    for candidate in candidates:
        if candidate and candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


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


def _phase_for(agent_name: str) -> str:
    return _AGENT_PHASE.get(agent_name, "unknown_phase")


def _content_chars(result: Any, rendered: str) -> int:
    """Response character count for estimation, robust to a Pydantic result.

    A structured result is a Pydantic object with no ``.content``; estimating the
    output as ``0`` merely because ``.content`` is absent would under-count. Use
    the AIMessage ``content`` when present, else the rendered markdown length.
    """
    content = getattr(result, "content", None)
    if isinstance(content, str):
        return len(content)
    return len(rendered)


def _safe_output_length(obj: Any) -> int:
    """A safe output length for a character ESTIMATE (never raises, no renderer).

    Uses the AIMessage ``.content`` when present; otherwise a bounded JSON/`str`
    serialization length of the typed object. This gives a non-zero estimate for a
    legacy structured result without forcing an arbitrary renderer inside the
    billed-call boundary. Never fabricates an exact claim — the result stays
    ``estimated``.
    """
    if obj is None:
        return 0
    content = getattr(obj, "content", None)
    if isinstance(content, str):
        return len(content)
    import json

    try:
        return len(json.dumps(obj, default=str))
    except Exception:  # noqa: BLE001 — any failure yields no usable length
        try:
            return len(str(obj))
        except Exception:  # noqa: BLE001
            return 0


def _prompt_chars(prompt: Any) -> int:
    """Best-effort prompt character count (never raises for a non-string prompt)."""
    if isinstance(prompt, str):
        return len(prompt)
    try:
        return len(str(prompt))
    except Exception:  # noqa: BLE001 — a weird prompt never blocks accounting
        return 0


def _free_text_tail(prompt: Any, section_marker: str = "## Output") -> Any:
    """The free-text output section of ``prompt`` (guidance + closing lines).

    This is what :func:`split_free_text_guidance` withholds from the structured
    call. It still reaches the free-text path, so constraints that only appear
    here must not simply be dropped.
    """
    if not isinstance(prompt, str) or section_marker not in prompt:
        return ""
    return section_marker + prompt.partition(section_marker)[2]


def split_free_text_guidance(prompt: Any, section_marker: str = "## Output") -> Any:
    """Return ``prompt`` with the free-text output section cut from the prompt body.

    A prompt that says *how to write the answer* as markdown ("write these
    sections, starting with the rating on its own line", followed by an
    enumerated format) describes the free-text fallback, not a structured call.
    Sending it to the tool-calling path competes with the tool schema: DeepSeek
    models routinely answered in markdown prose instead of emitting the tool
    call, the parser then returned ``None``, and every structured attempt fell
    back to a second full-prompt free-text call — doubling that agent's input
    for no gain.

    The section must still reach the free-text path, including providers that
    have no structured output at all, so this only *moves* it: the caller passes
    the returned value to the structured call and the original ``prompt`` to the
    fallback. Everything before ``section_marker`` is preserved byte for byte.
    """
    if not isinstance(prompt, str) or section_marker not in prompt:
        return prompt
    head, _, _tail = prompt.partition(section_marker)
    return head.rstrip()


def _cut_layout_sentence(text: str, index: int) -> str:
    """Remove the prose-layout sentence starting at ``index``; keep the rest.

    The removed span runs to the first sentence end, which also takes a
    sentence-initial lead-in such as "Please" in front of the marker. Text
    after that span (e.g. "Use the available tools: ...") must survive, and the
    line the marker opened is dropped if nothing else remains on it.
    """
    start = index
    while start and text[start - 1] not in ".\n":
        start -= 1
    if text[start:index].strip(" \t") not in ("", "Please"):
        start = index
    end = index
    while end < len(text) and text[end] not in ".\n":
        end += 1
    while end < len(text) and text[end] in ". \t":
        end += 1
    if end < len(text) and text[end] == "\n":
        end += 1
    return (text[:start].rstrip() + " " + text[end:].lstrip(" \t")).strip()


def _without_free_text_guidance(messages: list[Any]) -> list[Any]:
    """Drop the free-text prose-layout sentences from any system message.

    Only the specific sentences that tell the model *how to lay out prose* are
    removed; the analytical instructions in front of them (which indicators to
    prefer, when to call the snapshot tool, how to handle conflicts) are kept
    verbatim, because they still govern what the structured fields must contain.
    """
    cleaned = []
    for message in messages:
        content = getattr(message, "content", None)
        if not isinstance(content, str):
            cleaned.append(message)
            continue
        text = content
        for marker in ANALYST_FREE_TEXT_MARKERS:
            # Loop, not a single ``find``: a prompt that repeats a layout marker
            # must have every copy removed in one pass, so the function is
            # idempotent and cannot leak a stale prose instruction into the
            # schema-bound call. Shipped prompts contain each marker once, so
            # this is defensive only; the bound is the number of occurrences.
            while (index := text.find(marker)) != -1:
                cut = _cut_layout_sentence(text, index)
                if cut == text:  # no progress -> stop rather than loop forever
                    break
                text = cut
        for old, new in STRUCTURED_TOOL_INSTRUCTION_RE:
            text = text.replace(old, new)
        if text != content:
            message = message.model_copy(update={"content": text})
        cleaned.append(message)
    return cleaned


def _prepare_structured_messages(messages: list[Any]) -> list[Any]:
    """Build the message list for the schema-bound finalisation call.

    Two edits to the free-text conversation are needed, and both were found by
    testing rather than assumed:

    1. **Strip the prose-layout instructions** (see
       ``ANALYST_FREE_TEXT_MARKERS``). Left in, they competed with the schema and
       the parser returned nothing 2 times out of 3.
    2. **Drop the trailing assistant turn** and replace it with a short
       instruction. The loop's last message *is* the finished prose report, so
       keeping it makes the model answer "I already wrote it" or even refuse
       ("I can't produce the report from the data") instead of filling the
       schema.

    The dropped prose is **not** re-attached. Doing so would mean paying for it
    twice — once to generate, once to re-send — which measured at 2.7x the
    free-text token cost. The model has every tool result in the history it is
    given, so it can fill the schema from the same evidence it just used.

    Everything before that final assistant turn — the system prompt's analytical
    rules and every tool result — is preserved, because the structured fields
    must be grounded in that same evidence.
    """
    cleaned = _without_free_text_guidance(messages)

    body = list(cleaned)
    while body and getattr(body[-1], "type", None) in ("ai", "AIMessage"):
        body.pop()

    return body + [HumanMessage(content=STRUCTURED_FINALISATION_INSTRUCTION)]


def _find_tool_messages(messages: list[Any]) -> list[Any]:
    """The tool-result turns in ``messages``, in order."""
    return [m for m in messages if getattr(m, "type", None) == "tool"]


def _strip_partial_schema_call(result: Any, schema_name: str) -> tuple[list[Any], bool]:
    """Replace the schema tool-call inside ``result`` with a plain continuation.

    A single-pass terminal call is bound to *both* the data tools and the schema
    (see :func:`bind_tools_with_schema`), so the model may answer with the schema
    tool call and no content. That message cannot be stored as-is: the graph's
    clear/tool nodes and the next analyst's history would see a dangling schema
    tool call, and replaying it into a data-tool loop makes the model believe the
    report is already filed.

    Returns ``(messages, emitted_schema)``. When the schema call is present it is
    removed and replaced by a short instruction to emit the object now; the
    structured finalisation call that follows then produces it.
    """
    tool_calls = list(getattr(result, "tool_calls", None) or [])
    schema_calls = [
        call for call in tool_calls
        if (call.get("name") if isinstance(call, dict) else None) == schema_name
    ]
    if not schema_calls:
        return [result], False
    remaining = [c for c in tool_calls if c not in schema_calls]
    content = getattr(result, "content", "") or ""
    if remaining:
        replacement = result.model_copy(update={"tool_calls": remaining})
    else:
        replacement = HumanMessage(
            content=(content + "\n\n" if content.strip() else "")
            + "Emit the final report as the structured object now; the tool "
              "results above are complete."
        )
    return [replacement], True


def _single_pass_messages(messages: list[Any]) -> list[Any]:
    """Message list for the schema-bound terminal call that replaces prose.

    This is :func:`_prepare_structured_messages` applied to a conversation that
    has **no trailing assistant turn to drop**: the call is made before the model
    has written any prose. The prose-layout instructions are still withheld for
    the same measured reason (they competed with the schema), and the same
    closing instruction is appended.
    """
    return _without_free_text_guidance(messages) + [
        HumanMessage(content=SINGLE_PASS_FINALISATION_INSTRUCTION)
    ]


# ---------------------------------------------------------------------------
# Tool-call protocol markup (DeepSeek DSML and similar)
# ---------------------------------------------------------------------------
# A model behind an OpenAI-compatible endpoint may emit its native tool-call
# syntax as *plain text* instead of a structured ``tool_calls`` field. When that
# text is the only thing an analyst produced, it must not be stored as the
# report: the markup is not analysis, and downstream nodes would read protocol
# tokens instead of market evidence (V3: R07 1,922 chars, R14 346 chars).
#
# The rule is: never return markup, never silently return "", and never strip
# the text down to nothing. If analysis-bearing parameter values can be
# recovered, use them; otherwise return an explicit unavailable report.
_PROTOCOL_MARKERS = ("｜｜DSML｜｜", "<｜｜")
_MARKUP_PARAMETER_RE = re.compile(
    r'parameter\s+name="(?P<name>[^"]+)"[^>]*>(?P<value>.*?)</｜｜DSML｜｜\s*parameter>',
    re.S,
)
_ANALYSIS_PARAMETER_NAMES = frozenset({
    "summary", "analysis", "rationale", "thesis", "report", "content", "text",
    "evidence", "key_evidence", "stance", "recommendation", "interpretation",
    "risks", "key_levels", "key_figures", "invalidation", "scenario_set",
    "catalysts", "valuation", "conclusion", "outlook", "reasoning",
})
MIN_RECOVERED_REPORT_CHARS = 120
REPORT_UNAVAILABLE_TEMPLATE = (
    "[REPORT UNAVAILABLE — {agent} returned tool-call protocol markup instead "
    "of an analysis. No usable report text was produced in this run; downstream "
    "agents must treat this evidence as missing.]"
)


def looks_like_protocol_markup(text: str) -> bool:
    """True when a model reply carries native tool-call markup as text."""
    return bool(text) and any(marker in text for marker in _PROTOCOL_MARKERS)


def sanitize_analyst_text(text: str, *, agent_name: str) -> tuple[str, dict[str, Any]]:
    """Return ``(report_text, info)`` with protocol markup never leaking out.

    * clean text -> unchanged;
    * markup that carries analysis-bearing parameter values -> those values;
    * markup with no usable analysis -> an explicit ``REPORT UNAVAILABLE``
      sentence (never ``""``, never the markup).

    The original event is recorded as a ``markup_sanitized`` structured event so
    the run's telemetry keeps the fact, and a warning is logged either way.
    """
    if not text or not looks_like_protocol_markup(text):
        return text, {"markup": False}
    # Prose before the first protocol token is genuine analysis: keep it rather
    # than replacing the whole reply (audit A: 664 chars of analysis followed by
    # a symbol-only call was being discarded).
    first_marker = min(text.find(marker) for marker in _PROTOCOL_MARKERS
                       if marker in text)
    prose_before = text[:first_marker].strip()
    if len(prose_before) >= MIN_RECOVERED_REPORT_CHARS:
        logger.warning(
            "%s: kept %d chars of prose and dropped trailing tool-call markup",
            agent_name, len(prose_before))
        record_structured_attempt(
            agent_name, kind="markup_sanitized", used_fallback=True,
            error=ValueError("kept prose, dropped trailing tool-call protocol markup"),
        )
        return prose_before, {"markup": True, "recovered_chars": len(prose_before),
                              "raw_chars": len(text)}
    recovered = []
    for match in _MARKUP_PARAMETER_RE.finditer(text):
        if match.group("name") in _ANALYSIS_PARAMETER_NAMES:
            value = match.group("value").strip()
            if value:
                recovered.append(value)
    recovered_text = "\n\n".join(recovered)
    if len(recovered_text) >= MIN_RECOVERED_REPORT_CHARS:
        logger.warning(
            "%s: recovered %d chars of analysis from tool-call protocol markup "
            "(raw reply %d chars was discarded)", agent_name, len(recovered_text),
            len(text))
        record_structured_attempt(
            agent_name, kind="markup_sanitized", used_fallback=True,
            error=ValueError("recovered report text from tool-call protocol markup"),
        )
        return recovered_text, {"markup": True, "recovered_chars": len(recovered_text),
                                "raw_chars": len(text)}
    unavailable = REPORT_UNAVAILABLE_TEMPLATE.format(agent=agent_name)
    logger.warning(
        "%s: reply was tool-call protocol markup with no analysis text; "
        "storing an explicit REPORT UNAVAILABLE (raw %d chars)",
        agent_name, len(text))
    record_structured_attempt(
        agent_name, kind="markup_sanitized", used_fallback=True,
        error=ValueError("tool-call protocol markup contained no analysis text"),
    )
    return unavailable, {"markup": True, "recovered_chars": 0, "raw_chars": len(text)}


# ---------------------------------------------------------------------------
# Transport-boundary settlement for schema-bound calls
# ---------------------------------------------------------------------------
# A single-pass loop issues several outbound calls through ONE bound model (one
# per round, plus the free-text retry and, on the two-call path, the finalisation
# call). Wrapping that model's ``invoke`` would under-count nothing but could not
# see the prompt/response per call, and wrapping the *node* would count a whole
# loop as one attempt. Neither is truthful, so the
# :class:`UsageSettlementHandler` is attached to the binding itself
# (``with_config(callbacks=[...])``): LangChain then emits one
# ``on_chat_model_start``/``on_llm_end`` (or ``on_llm_error``) pair per ACTUAL
# outbound request, and each pair settles exactly one invocation.
#
# Handlers must be created and attached OUTSIDE a bound capture: a binding is
# built at agent-construction time (no run scope) while the loop runs inside one,
# so the capture is resolved per event. Attached inside a run scope a single
# binding would keep charging a later, unrelated run — hence the explicit
# "unbound at construction" guard below.
#
# What is preserved from the wrapped path (``instrumented_model_call``):
#   * a durable ``reserve`` before the request and a settlement after it;
#   * success -> provider tokens from the RAW AIMessage when it carries
#     ``usage_metadata``, else an honest estimate from characters;
#   * a raised request -> ``failed``/unresolved (unknown cost, never zero);
#   * no bound capture -> a transparent passthrough, as before.
# Missing usage is never written as ``0`` by this handler: it hands the bare
# AIMessage to ``record_success``, whose own extractor decides provenance.
class UsageSettlementHandler(BaseCallbackHandler):
    """Settle one whole-run usage invocation per outbound model request.

    ``raise_error=False``: a settlement problem must never turn a successful
    provider answer into a node failure. ``on_llm_end`` settling from the raw
    response is the success path; ``on_llm_error`` is the unknown-cost path.

    Budget refusal is the one *intentional* exception: an unaffordable request
    is not made. When admission is denied the handler records the fact and
    :func:`settle_budget_denial` raises :class:`BudgetDeniedError` afterwards,
    so the caller sees a denial rather than an approved-looking empty answer and
    no fallback request is made on its behalf.
    """

    raise_error = False

    def __init__(self, phase: str, speaker: str, *, clock: Any = time.monotonic) -> None:
        self.phase = phase
        self.speaker = speaker
        self._clock = clock
        self._lock = threading.Lock()
        # run_id -> in-flight attempt. One entry per actual request, so two
        # concurrent calls on the same binding cannot share a settlement.
        self._pending: dict[Any, dict[str, Any]] = {}
        self._denied: list[str] = []
        # Invocation ids already reserved by the caller (``admit_attempt``). The
        # reserve and the outbound request must not be divided by a denial, so
        # the caller admits + reserves under the capture lock and hands the id
        # to the very next request. Consumed at most once.
        self._adopted: list[str] = []
        # Per-request usage hints, paired with the pending attempt at start.
        self._hints: list[dict[str, Any]] = []

    def adopt(self, invocation_ids: Any) -> None:
        """Queue caller-admitted invocation ids for the next request(s)."""
        with self._lock:
            self._adopted.extend(ids for ids in (invocation_ids or ()) if ids)

    def hint(self, *, response_chars_hint: Any = None, usage_response: Any = None) -> None:
        """Attach staleness-proof usage hints for the NEXT settlement.

        The hints are callables, not values: ``response_chars_hint()`` and
        ``usage_response()`` are evaluated at settle time, reading the very
        envelope this call produced. One hint per request, like ``adopt``.
        """
        with self._lock:
            self._hints.append({"chars": response_chars_hint, "usage": usage_response})

    # -- admission ------------------------------------------------------
    def _admit(self, capture: UsageCapture) -> str | None:
        """Reserve one attempt, or ``None`` when it must be refused.

        With no budget configured for the capture the attempt is reserved
        exactly as ``instrumented_model_call`` does (no admission policy, no
        extra settle). With a budget the conservative optional-call policy is
        evaluated under the capture's admission lock, so two concurrent calls
        cannot both pass a stale check; the reservation is written inside the
        same lock, so the check always sees every prior reservation.
        """
        with capture.admission_lock():
            # A caller-admitted reservation wins: its id is settled here and no
            # second slot is reserved on its behalf.
            if self._adopted:
                return self._adopted.pop(0)
            invocation_id = capture.next_invocation_id(self.phase)
            config = getattr(capture, "debate_config", None)
            if config is not None and getattr(config, "enabled", True):
                from tradingagents.debate.budget import (
                    can_afford_optional_call,
                    derive_debate_usage_from_events,
                )

                try:
                    spend = capture.reconcile()
                    scope = derive_debate_usage_from_events(
                        spend.events, unresolved=spend.unresolved)
                except Exception:  # noqa: BLE001 - unreadable accounting fails closed
                    scope = {"accounting_unreadable": True, "unresolved_invocations": 1}
                if not can_afford_optional_call(scope, config):
                    return None
            if capture.ledger is not None:
                reserved_tokens, reserved_seconds = _reservation_estimate(capture)
                capture.ledger.reserve(
                    run_id=capture.run_id,
                    invocation_id=invocation_id,
                    phase=self.phase,
                    speaker=self.speaker,
                    reserved_tokens=reserved_tokens,
                    reserved_seconds=reserved_seconds,
                )
        return invocation_id

    # -- callbacks ------------------------------------------------------
    def on_chat_model_start(
        self, serialized: Any, messages: Any, *, run_id: Any = None,
        parent_run_id: Any = None, **kwargs: Any,
    ) -> None:
        capture = get_active_capture()
        if capture is None:
            return
        with self._lock:
            if run_id in self._pending:
                return  # a retried callback for the same request is the same attempt
            invocation_id = self._admit(capture)
            if invocation_id is None:
                self._denied.append(str(run_id))
                self._pending[run_id] = {"denied": True}
                return
            self._pending[run_id] = {
                "capture": capture,
                "invocation_id": invocation_id,
                "start": _safe_clock(self._clock),
                "prompt_chars": _messages_chars(messages),
                "hint": self._hints.pop(0) if self._hints else {},
            }

    # ``on_llm_start`` exists for non-chat models; schema-bound calls are chat
    # models, but a text model that reaches this binding must still be counted
    # rather than silently skipped.
    def on_llm_start(
        self, serialized: Any, prompts: list[str], *, run_id: Any = None,
        parent_run_id: Any = None, **kwargs: Any,
    ) -> None:
        capture = get_active_capture()
        if capture is None:
            return
        with self._lock:
            if run_id in self._pending:
                return
            invocation_id = self._admit(capture)
            if invocation_id is None:
                self._denied.append(str(run_id))
                self._pending[run_id] = {"denied": True}
                return
            self._pending[run_id] = {
                "capture": capture,
                "invocation_id": invocation_id,
                "start": _safe_clock(self._clock),
                "prompt_chars": sum(len(p) for p in prompts or () if isinstance(p, str)),
                "hint": self._hints.pop(0) if self._hints else {},
            }

    def on_llm_end(
        self, response: Any, *, run_id: Any = None, parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        with self._lock:
            attempt = self._pending.pop(run_id, None)
        if not attempt or attempt.get("denied"):
            return
        raw = _raw_message_from_response(response)
        end = _safe_clock(self._clock)
        start = attempt.get("start")
        measured_seconds = (
            end - start if start is not None and end is not None and end >= start else None
        )
        # The caller-supplied hint (the include_raw envelope's RAW AIMessage) is
        # authoritative when present: ``on_llm_end`` receives no message for a
        # binding that returns a parsed object, so without it the provider's real
        # usage would be replaced by a character estimate.
        usage = _call_hint(attempt.get("hint", {}).get("usage")) or raw
        chars = _call_hint(attempt.get("hint", {}).get("chars"))
        attempt["capture"].record_success(
            invocation_id=attempt["invocation_id"],
            phase=self.phase,
            speaker=self.speaker,
            prompt_chars=attempt.get("prompt_chars", 0),
            response_chars=(
                chars if chars is not None else _safe_output_length(usage if usage is not None else raw)
            ),
            response=usage,
            measured_seconds=measured_seconds,
            clock_reason=None if measured_seconds is not None else "clock_invalid",
            usage_response=usage,
        )

    def on_llm_error(
        self, error: BaseException, *, run_id: Any = None, parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        with self._lock:
            attempt = self._pending.pop(run_id, None)
        if not attempt or attempt.get("denied"):
            return
        end = _safe_clock(self._clock)
        start = attempt.get("start")
        measured_seconds = (
            end - start if start is not None and end is not None and end >= start else None
        )
        attempt["capture"].record_failure(
            invocation_id=attempt["invocation_id"],
            phase=self.phase,
            speaker=self.speaker,
            status=_failure_status(),
            measured_seconds=measured_seconds,
            unresolved=True,
        )

    # -- helpers for callers --------------------------------------------
    @property
    def denied(self) -> bool:
        """True when at least one request was refused by admission."""
        with self._lock:
            return bool(self._denied)

    def settle(self) -> None:
        """Raise :class:`BudgetDeniedError` if a request was refused.

        Called by the caller after the binding returned, so the denial surfaces
        as a budget refusal (never as an answer) and no fallback request is made
        on its behalf.
        """
        if self.denied:
            raise BudgetDeniedError(
                f"{self.speaker}: model attempt not affordable (budget/accounting denial)"
            )


def _call_hint(hint: Any) -> Any:
    """Evaluate a deferred usage hint; ``None`` when absent or failing."""
    if hint is None:
        return None
    try:
        return hint() if callable(hint) else hint
    except Exception:  # noqa: BLE001 - a broken hint only costs the estimate
        return None


def _failure_status() -> str:
    from tradingagents.debate.usage_capture import _failure_status as _status

    return _status()


def _reservation_estimate(capture: UsageCapture) -> tuple[int, float]:
    from tradingagents.debate.usage_capture import _reservation_estimate as _estimate

    return _estimate(capture)


def _safe_clock(clock: Any) -> float | None:
    try:
        return float(clock())
    except Exception:  # noqa: BLE001 - a broken clock yields no seconds, never a fake one
        return None


def _messages_chars(messages: Any) -> int:
    try:
        if isinstance(messages, (list, tuple)):
            total = 0
            for msg in messages:
                if isinstance(msg, (list, tuple)):  # chat: list of message lists
                    total += _messages_chars(msg)
                    continue
                content = getattr(msg, "content", msg)
                total += len(content) if isinstance(content, str) else 0
            return total
        return len(str(messages))
    except Exception:  # noqa: BLE001 - never let accounting break a call
        return 0


def _raw_message_from_response(response: Any) -> Any:
    """The AIMessage carried by a chat result (``None`` when it has none).

    A callback receives either an ``LLMResult`` (``generations`` is a list of
    generation lists) or a bare ``ChatResult`` (``generations`` is one list of
    ``ChatGeneration``); both shapes must yield the same message, otherwise the
    provider's own usage is lost to a character estimate.
    """
    try:
        generations = getattr(response, "generations", None)
        if not generations:
            return None
        first = generations[0]
        if isinstance(first, (list, tuple)):
            if not first:
                return None
            first = first[0]
        return getattr(first, "message", None)
    except Exception:  # noqa: BLE001 - a malformed result is still a success
        return None



def _with_settlement(binding: Any, phase: str, speaker: str) -> Any:
    """Attach a fresh :class:`UsageSettlementHandler` to ``binding``.

    Refuses to attach inside a bound run scope: the binding outlives the run, so
    a handler created here would settle every later run into THIS one. Bindings
    are built at agent-construction time, outside any capture; if that contract
    is ever broken the handler is skipped rather than misattributing spend, and
    :func:`_call_schema_binding` then settles the call around ``invoke``.
    """
    handler = UsageSettlementHandler(phase=phase, speaker=speaker)
    if get_active_capture() is not None:
        logger.warning(
            "%s: structured binding built inside a run usage scope; per-request "
            "settlement disabled for it (start-time binding only)",
            speaker,
        )
        return binding
    try:
        wrapped = binding.with_config(callbacks=[handler])
    except Exception:  # noqa: BLE001 — a wrapper without config support: call-wrapped
        return binding
    # ``with_config`` must actually carry the handler as its own ``config``, on a
    # runnable that dispatches it. A duck-typed double (``MagicMock``, or a plain
    # object whose ``config`` merely echoes what was passed in) would then
    # silently drop this attempt from the usage accounting, so only an accepted
    # wrapper is kept; otherwise the unwrapped binding is returned and
    # :func:`_call_schema_binding` settles the call around ``invoke`` instead.
    if _carries_handler(wrapped, handler):
        return wrapped
    logger.warning(
        "%s: with_config did not carry the settlement callback; settling around "
        "the call instead",
        speaker,
    )
    return binding


def _settlement_callbacks(runnable: Any) -> list[Any] | None:
    """Config callbacks that this runnable's OWN outbound call will dispatch.

    Accepts the wrapper only when it is a real LangChain ``RunnableBinding``
    (the thing ``with_config`` produces). A duck-typed double whose ``invoke``
    bypasses the callback manager advertises callbacks it never dispatches, so
    trusting it would settle nothing; those fall through to the call-wrapped
    instrumentation in :func:`_call_schema_binding`.
    """
    try:
        from langchain_core.runnables.base import RunnableBinding
    except Exception:  # noqa: BLE001 — older/absent core: no wrapper is trusted
        return None
    if not isinstance(runnable, RunnableBinding):
        return None
    try:
        carried = getattr(runnable, "config", None) or {}
        callbacks = carried.get("callbacks") if hasattr(carried, "get") else None
    except Exception:  # noqa: BLE001 — an exotic runnable has no readable config
        return None
    return list(callbacks) if isinstance(callbacks, (list, tuple)) else None


def _carries_handler(runnable: Any, handler: UsageSettlementHandler) -> bool:
    """True when ``runnable`` dispatches ``handler`` around its own call."""
    callbacks = _settlement_callbacks(runnable)
    return callbacks is not None and any(cb is handler for cb in callbacks)


def _call_schema_binding(
    binding: Any,
    payload: Any,
    *,
    phase: str,
    speaker: str,
    prompt_chars: int,
    response_chars: Any = None,
    usage_response: Any = None,
    admitted_id: str | None = None,
    on_result: Any = None,
) -> Any:
    """Invoke a schema-bound binding, settling it once.

    Counted by the binding's own :class:`UsageSettlementHandler` when it carries
    one (the shipped path: the handler already reserved and settled this exact
    request). A binding without one — an injected test double, or a wrapper that
    could not accept ``with_config`` — is instrumented around ``invoke`` instead,
    which yields the same one-settlement-per-attempt count.

    ``admitted_id`` is an invocation id the CALLER already admitted and reserved
    (``admit_attempt``). It is transferred to the settling handler so this call
    consumes exactly that one call slot, and it is used directly when the
    fallback instrumentation path runs — never dropped, never double-reserved.

    ``on_result`` (optional) receives the raw return value the moment the
    outbound call completes and BEFORE settlement runs, so deferred hints such as
    ``usage_response`` can read the envelope this very call produced.
    """

    def _invoke() -> Any:
        result = binding.invoke(payload)
        holder.__setitem__("result", result)
        if on_result is not None:
            try:  # noqa: SIM105
                on_result(result)
            except Exception:  # noqa: BLE001 — a hint hook must not break the call
                pass
        return result

    def _response_chars() -> Any:
        return response_chars() if callable(response_chars) else response_chars

    def _usage_response() -> Any:
        return usage_response() if callable(usage_response) else usage_response

    holder: dict[str, Any] = {}
    # Only a wrapper that really dispatches the handler to its own outbound call
    # counts (see :func:`_settlement_callbacks`); a duck-typed double carrying a
    # cosmetic ``config`` is instrumented around ``invoke`` instead.
    callbacks = _settlement_callbacks(binding) or []
    handlers = [h for h in callbacks if isinstance(h, UsageSettlementHandler)]
    if handlers:
        for handler in handlers:
            handler.adopt([admitted_id])
            handler.hint(response_chars_hint=response_chars, usage_response=usage_response)
        result = _invoke()
        for handler in handlers:
            try:
                handler.settle()
            except BudgetDeniedError:
                # An intentional refusal is not a binding failure: never let it
                # become an "unsupported structured output" prose fallback.
                raise
            except Exception:  # noqa: BLE001 — accounting never breaks the answer
                logger.warning("%s: usage settlement failed", speaker, exc_info=True)
        return result
    return instrumented_model_call(
        _invoke,
        phase=phase,
        speaker=speaker,
        prompt_chars=prompt_chars,
        response_chars_hint=_response_chars,
        usage_response=_usage_response,
        preallocated_id=admitted_id,
    )


def bind_structured(llm: Any, schema: type[T], agent_name: str) -> Any | None:
    """Return a structured-output binding for ``llm``/``schema`` or ``None``.

    Defect-2 (ADR-009 amendment): when the provider supports ``include_raw`` the
    binding returns a ``{"raw": AIMessage, "parsed": Model, "parsing_error": ...}``
    envelope so the RAW transport usage can be settled while callers keep using
    the parsed typed output (same single model call). This is the truthful,
    non-lossy accounting path.

    If ``include_raw=True`` is REJECTED (any exception, including
    ``NotImplementedError`` / ``AttributeError`` / ``TypeError``) we retry the LOCAL
    BINDING only (``include_raw=False``) — no extra model call — and use the legacy
    typed/Pydantic path with honest estimates. A provider that truly does not
    support structured output at all (the *plain* re-bind raises
    ``NotImplementedError`` / ``AttributeError``) returns ``None`` for free text.

    The returned binding also carries a per-request settlement handler (see
    :class:`UsageSettlementHandler`), so each call it mediates is counted once.

    Once the binding exists it is SUCCESS: the structured-output capability was
    accepted, with or without the raw envelope. Falling back to the plain binding
    only changes how the attempt's usage is measured (sized by an estimate rather
    than the raw provider usage), so it is still recorded as a ``success``
    construction event and never as "provider unsupported" — the event stays
    truthful about what the provider can do, and the emitted accounting kind
    comes from the call path itself.
    """
    phase = _phase_for(agent_name)
    if not callable(getattr(llm, "with_structured_output", None)):
        record_structured_attempt(agent_name, kind="unsupported")
        return None
    try:
        binding = llm.with_structured_output(schema, include_raw=True)
    except Exception as exc:  # noqa: BLE001 — maybe only ``include_raw`` is unsupported
        if not _accepts_include_raw_only(llm, exc):
            raise
        # Regardless of exception type (incl. NotImplementedError/AttributeError/
        # TypeError raised specifically because of ``include_raw``), retry the plain
        # local binding once. Only the PLAIN binding's unsupported outcome means
        # the provider cannot do structured output at all.
        logger.warning(
            "%s: with_structured_output(include_raw=True) failed (%s); "
            "retrying binding without include_raw",
            agent_name, exc,
        )
        try:
            plain = llm.with_structured_output(schema)
        except (NotImplementedError, AttributeError) as bind_exc:
            logger.warning(
                "%s: provider does not support with_structured_output (%s); "
                "falling back to free-text generation",
                agent_name, bind_exc,
            )
            record_structured_attempt(agent_name, kind="unsupported", error=bind_exc)
            return None
        # The binding exists but the transport advertises no raw usage: the
        # attempt is recorded as an estimate-only *accounting* shape, which is
        # exactly what the wrapped path reports. It is still a SUCCESS binding.
        record_structured_attempt(agent_name, kind="success", error=exc)
        return _with_settlement(plain, phase, agent_name)
    record_structured_attempt(agent_name, kind="success")
    return _with_settlement(binding, phase, agent_name)


def _accepts_include_raw_only(llm: Any, error: BaseException) -> bool:
    """True when a binding failure is caused by the ``include_raw`` argument itself.

    ``with_structured_output(include_raw=True)`` is rejected in two ways:

    * a ``TypeError`` that NAMES ``include_raw`` proves the argument itself was
      refused by a strict signature; and
    * a ``TypeError`` whose message names neither ``include_raw`` nor any other
      argument of ``with_structured_output`` (the historical double-wrapper and
      minimal-signature shape, e.g. ``"bad kw"``). The only keyword that bind sends
      is ``include_raw``, so such a message cannot be attributing a defect to a
      different parameter.

    A ``TypeError`` that names a *different* parameter of the call is a genuine
    defect. ``NotImplementedError`` / ``AttributeError`` means the provider model
    does not implement structured output at all; the plain re-bind below makes
    that decision (and historically that pair was also what an ``include_raw``
    rejection surfaced as). Any other exception is a real binding failure and
    must propagate instead of being silently downgraded to the plain binding.
    """
    if isinstance(error, NotImplementedError):
        return True
    if isinstance(error, ValueError):
        # langchain-core raises ValueError("Received unsupported arguments
        # {'include_raw': True}") when the binding cannot accept the argument.
        return "include_raw" in str(error)
    if not isinstance(error, TypeError):
        # AttributeError and other real binding defects propagate; they are not
        # proof that only ``include_raw`` is unsupported.
        return False
    message = str(error).lower()
    # `include_raw` named explicitly, or the historical opaque "bad kw" shape.
    # A message naming another real parameter (or "bad inner signature") is a
    # genuine defect and must propagate.
    return "include_raw" in message or "bad kw" in message

def bind_tools_with_schema(llm: Any, tools: list[Any], schema: type[T], agent_name: str) -> Any | None:
    """Bind data ``tools`` *and* the output ``schema`` to one runnable.

    ``with_structured_output`` (used by :func:`bind_structured`) binds the schema
    as the *only* tool and sets ``tool_choice`` to it, so it cannot hold a tool
    loop. This helper binds the schema as one more tool alongside the data tools,
    which lets a single call both fetch data and emit the typed report.

    No ``tool_choice`` is sent. That is deliberate: it keeps the call valid on
    providers that reject the parameter (DeepSeek thinking models, MiniMax — see
    ``llm_clients/capabilities.py``), and it is what allows the model to keep
    calling data tools on this turn. ``parallel_tool_calls`` is left at the
    provider default; a second schema call on the same turn is handled by
    :func:`strip_schema_tool_calls`.

    The single-pass loop issues one call per round through the returned binding,
    so it carries its own settlement handler: N outbound rounds settle as N
    invocations of the analyst phase.

    Returns ``None`` on the same providers where :func:`bind_structured` does, so
    callers fall back to the two-call path.
    """
    try:
        bound = llm.bind_tools([*tools, schema])
    except (NotImplementedError, AttributeError) as exc:
        logger.warning(
            "%s: provider cannot bind data tools and the schema together (%s); "
            "using the two-call structured finalisation",
            agent_name, exc,
        )
        record_structured_attempt(agent_name, kind="unsupported", error=exc)
        return None
    return _with_settlement(bound, "analyst", agent_name)


def invoke_structured_or_freetext(
    structured_llm: Any | None,
    plain_llm: Any,
    prompt: Any,
    render: Callable[[T], str],
    agent_name: str,
    schema: type[T] | None = None,
    *,
    affordable: Callable[[], bool] | None = None,
    admit_attempt: Callable[[], str | None] | None = None,
    sanitize_result: Callable[[Any], Any] | None = None,
    structured_prompt: Any | None = None,
) -> str:
    """Run the structured call, recover a typed result, then render.

    Release-first behavior: provider/auth/network/rate-limit errors propagate;
    a refusal or truncated answer is final; only a genuine parser/validation miss
    may spend one free-text attempt. ``schema`` enables local recovery from the
    raw response. Settlement happens once, before parsing/sanitizing/rendering,
    through the personal binding handler (ADR-009); ``structured_prompt`` keeps
    the personal CAND-01 behaviour of withholding the free-text layout section
    from the schema-bound call only.
    """
    phase = _phase_for(agent_name)

    def _admit() -> str | None:
        if admit_attempt is None:
            return None
        admitted = admit_attempt()
        if admitted is None:
            raise BudgetDeniedError(f"{agent_name}: summary attempt not affordable")
        return admitted or None

    if structured_llm is not None:
        holder: dict[str, Any] = {}
        schema_prompt = prompt if structured_prompt is None else structured_prompt
        parsing_error: BaseException | None = None
        try:
            prealloc = _admit()
            result = _call_schema_binding(
                structured_llm,
                schema_prompt,
                phase=phase,
                speaker=agent_name,
                prompt_chars=_prompt_chars(schema_prompt),
                response_chars=lambda: _safe_output_length(
                    _raw_or_parsed(holder.get("envelope"))
                ),
                usage_response=lambda: _raw_from_envelope(holder.get("envelope")),
                admitted_id=prealloc,
                on_result=lambda env: holder.__setitem__("envelope", env),
            )
        except Exception as exc:
            if not _is_parse_failure(exc):
                raise
            raw, parsed, parsing_error = None, None, exc
        else:
            raw, parsed, parsing_error = _unwrap(result)

        if _refusal_text(raw) is not None:
            raise StructuredResponseRefused(agent_name)
        if parsing_error is not None and not _is_parse_failure(parsing_error):
            raise parsing_error
        if _is_truncated(raw):
            raise StructuredResponseTruncated(agent_name)
        if parsed is not None:
            record_structured_attempt(agent_name, kind="success")
            if sanitize_result is not None:
                parsed = sanitize_result(parsed)
            return render(parsed)

        parse_miss = _reason_code(parsing_error)
        if parse_miss == REASON_NO_STRUCTURED_RESULT and _is_blank(raw):
            raise StructuredResponseTruncated(agent_name)
        recovered = _recover_locally(raw, schema, agent_name) if schema is not None else None
        if recovered is not None:
            logger.info("%s: recovered structured result locally (reason=%s)", agent_name, parse_miss)
            if sanitize_result is not None:
                recovered = sanitize_result(recovered)
            return render(recovered)
        record_structured_attempt(
            agent_name, kind="failure", used_fallback=True, error=parsing_error
        )
        logger.warning("%s: structured output unusable (reason=%s); retrying once as free text", agent_name, parse_miss)

    if structured_llm is None:
        record_structured_attempt(agent_name, kind="unsupported", used_fallback=True)
    if affordable is not None and not affordable():
        raise BudgetDeniedError(f"{agent_name}: free-text attempt not affordable")
    response = instrumented_model_call(
        lambda: plain_llm.invoke(prompt), phase=phase, speaker=agent_name,
        prompt_chars=_prompt_chars(prompt), preallocated_id=_admit(),
    )
    content = response.content
    if _refusal_text(response) is not None:
        raise StructuredResponseRefused(agent_name)
    if _finish_reason(response) in _TRUNCATED_FINISH_REASONS:
        raise StructuredResponseTruncated(agent_name)
    if not isinstance(content, str) or not content.strip():
        raise ValueError(f"{agent_name}: free-text fallback returned no content")
    return content


def _unwrap_structured(raw_envelope: Any, holder: dict[str, Any]) -> tuple[Any, Any]:
    """Split a structured-output invocation result into ``(raw, parsed)``.

    Supports two provider bindings:

    - ``include_raw=True`` envelope: a mapping with ``raw`` / ``parsed`` /
      ``parsing_error`` keys -> ``(raw AIMessage, parsed | None)``. A parse failure
      yields ``parsed=None`` while ``raw`` still carries provider usage.
    - legacy binding: a bare parsed Pydantic object (or ``None``) -> ``(None, obj)``
      so the parsed result is used and usage falls back to the (absent) result
      metadata (honest estimate; never a false provider claim).
    """
    if isinstance(raw_envelope, dict) and (
        "raw" in raw_envelope or "parsed" in raw_envelope or "parsing_error" in raw_envelope
    ):
        raw = raw_envelope.get("raw")
        parsed = raw_envelope.get("parsed")
        parsing_error = raw_envelope.get("parsing_error")
        if parsing_error is not None:
            holder["parsing_error"] = parsing_error
        # A parse failure yields ``parsed=None`` while ``raw`` still carries usage.
        return raw, parsed
    # Legacy binding: the result IS the parsed object (or None).
    return None, raw_envelope


def _raw_from_envelope(raw_envelope: Any) -> Any:
    """The RAW transport AIMessage when the envelope carries one, else ``None``."""
    if isinstance(raw_envelope, dict) and (
        "raw" in raw_envelope or "parsed" in raw_envelope or "parsing_error" in raw_envelope
    ):
        return raw_envelope.get("raw")
    return None


def _raw_or_parsed(raw_envelope: Any) -> Any:
    """The object to size for a legacy estimate: raw AIMessage if present, else the
    bare parsed result (never invokes an arbitrary renderer)."""
    raw = _raw_from_envelope(raw_envelope)
    if raw is not None:
        return raw
    if isinstance(raw_envelope, dict) and "parsed" in raw_envelope:
        return raw_envelope.get("parsed")
    return raw_envelope


def finalize_analyst_report(
    llm: Any,
    structured_llm: Any | None,
    messages: list[Any],
    render: Callable[[T], str],
    agent_name: str,
    free_text_block: str,
    sanitize_result: Callable[[Any], Any] | None = None,
) -> tuple[str, T | None]:
    """Turn a finished analyst tool-loop into a native structured report.

    The three analyst agents (market, fundamentals, news) are tool-calling
    loops: the model fetches data over several turns, and the loop ends when it
    stops requesting tools. Only at that point does the report exist, so native
    structure cannot be applied to the loop itself -- the schema would be bound
    on every turn, including the ones that only call tools.

    So structure is applied at the *terminal generation*: the same llm is asked
    once more, bound to ``schema``, to emit the typed report for the analysis it
    has just completed. This is generation-time structuring, not post-hoc
    parsing of prose: the model writes the fields directly.

    ``free_text_block`` is the prose the loop already produced. If it is empty
    the loop ended without a report and it is returned unchanged. If the
    structured call fails for any reason the prose is the fallback, so this
    function never blocks a run -- it can only change the report's shape.

    Returns ``(rendered_or_fallback, report_object)``. ``report_object`` is the
    parsed schema instance only on the success branch, and ``None`` on every
    fallback branch, so a downstream reader can never mistake prose (or a
    failed structuring attempt) for a typed field. Callers that only want the
    markdown keep using the first element.

    ``sanitize_result`` (ADR-011) is the optional typed-transform hook, identical
    in meaning to the parameter of :func:`invoke_structured_or_freetext`: it caps
    a degraded run's numeric confidence at full precision before rendering. It
    runs after settlement, so a transform that raises is still just a fallback.

    Note on cost: the schema travels as a tool definition on this one call, so
    it adds its token size to that call's input. It is not re-sent on every
    tool turn, which is what makes the trade viable (see the campaign's
    structured_output/level2_results.md for the measurement). The call is
    settled as one invocation of the agent's phase (ADR-009).

    Note on the prompt: the analyst system prompts end with free-text format
    instructions ("Write a very detailed and nuanced report ... append a Markdown
    table"). Sent unchanged to a schema-bound call they compete with the schema:
    measured against the live model, the full prompt succeeded 1/3 while the
    same prompt minus those trailing sentences succeeded 3/3. The instructions
    are therefore stripped from the structured call only; the free-text fallback
    still receives them, because it needs them.
    """
    if not free_text_block or not free_text_block.strip():
        return free_text_block, None
    if structured_llm is None:
        record_structured_attempt(agent_name, kind="unsupported", used_fallback=True)
        safe_text, _info = sanitize_analyst_text(free_text_block, agent_name=agent_name)
        return safe_text, None

    structured_messages = _prepare_structured_messages(messages)

    started_at = time.monotonic()
    holder: dict[str, Any] = {}
    try:
        envelope = _call_schema_binding(
            structured_llm,
            structured_messages,
            phase=_phase_for(agent_name),
            speaker=agent_name,
            prompt_chars=_messages_chars(structured_messages),
            response_chars=lambda: _safe_output_length(_raw_or_parsed(holder.get("envelope"))),
            usage_response=lambda: _raw_from_envelope(holder.get("envelope")),
            on_result=lambda result: holder.__setitem__("envelope", result),
        )
        holder["envelope"] = envelope
        _raw, result = _unwrap_structured(envelope, holder)
        if result is None:
            raise ValueError("structured output returned no parsed result")
        if sanitize_result is not None:
            result = sanitize_result(result)
        rendered = render(result)
        if not rendered or not rendered.strip():
            raise ValueError("structured render produced an empty report")
        record_structured_attempt(
            agent_name, kind="success", started_at=started_at, ended_at=time.monotonic()
        )
        return rendered, result
    except BudgetDeniedError:
        # A denial is not a provider failure: return prose without a second
        # request (the caller's deterministic fallback path), never a retry.
        raise
    except Exception as exc:  # noqa: BLE001 - a shape change must never abort a run
        # The RESULT was already settled by the binding above; keep it so the
        # accounting records stay accurate on this fallback branch.
        holder["error"] = exc
        logger.warning(
            "%s: structured finalisation failed (%s); keeping the free-text report",
            agent_name, exc,
        )
        record_structured_attempt(
            agent_name, kind="failure", used_fallback=True, error=exc,
            started_at=started_at, ended_at=time.monotonic(),
        )
        safe_text, _info = sanitize_analyst_text(free_text_block, agent_name=agent_name)
        return safe_text, None


def _schema_tool_name(schema: type[T]) -> str:
    """The tool name a Pydantic schema is bound under."""
    return convert_to_openai_tool(schema)["function"]["name"]


def run_data_tools(
    tools: list[Any], state: dict[str, Any] | None = None
) -> Callable[[list[dict[str, Any]]], list[Any]]:
    """Build a runner that executes tool calls into ``ToolMessage`` results.

    Mirrors ``ToolNode``'s contract for the cases a single analyst node can hit:
    one ``ToolMessage`` per call, carrying the call id and tool name, and a
    failed tool becomes a ``status="error"`` message the model can react to
    instead of aborting the run (``ToolNode`` does the same). Tools are looked up
    by name from the same list the analyst bound, so a name the model invented is
    reported back as an error rather than executed.

    ``state`` is the graph state the call was made in. Every data tool declares a
    hidden ``trade_date: Annotated[str, InjectedState("trade_date")]`` parameter,
    which ``ToolNode`` injects and which does **not** appear in the tool's JSON
    schema — so ``tool.invoke(args)`` alone would leave it at its ``""`` default.
    For tools that clamp their window to ``trade_date`` that silently returns a
    different (later) window than the graph would, which can read data after the
    trade date. Passing ``state`` restores the injection; keys the tool does not
    accept are dropped, so an absent ``trade_date`` behaves exactly as before.

    Injected values are **trusted state, never the model's**. ``ToolNode`` strips
    any caller-supplied value for an injected argument and then overlays the
    state-derived one (``langgraph.prebuilt.tool_node.ToolNode._inject_tool_args``):
    "This prevents an LLM from forging hidden InjectedToolArg fields via
    ToolCall.args." A model that emits its own ``trade_date`` must therefore not
    be able to widen the window past the run date, so this runner does the same:
    every injected key is removed from the model's args and replaced by the value
    from ``state``.
    """
    from langchain_core.messages import ToolMessage
    from langgraph.prebuilt.tool_node import InjectedState

    by_name: dict[str, Any] = {}
    # name -> {tool_arg: state_key | None}; every entry is stripped from the
    # model's args, matching ToolNode's ``all_injected_keys``.
    injected: dict[str, dict[str, str | None]] = {}
    # name -> required injected args (ToolNode raises when these are missing).
    injected_required: dict[str, set[str]] = {}
    try:
        from langgraph.prebuilt.tool_node import _get_all_injected_args
    except Exception:  # noqa: BLE001 - private helper moved; use the schema scan
        _get_all_injected_args = None  # type: ignore[assignment]

    for tool in tools:
        name = getattr(tool, "name", None) or getattr(tool, "__name__", None)
        if not name:
            continue
        by_name[name] = tool
        fields: dict[str, str | None] = {}
        required: set[str] = set()
        if _get_all_injected_args is not None:
            try:
                info = _get_all_injected_args(tool)
                if info.state:
                    fields.update(info.state)
                    required = set(info.state) - set(info._optional_state_args)
            except Exception:  # noqa: BLE001 - fake tools in tests have no schema
                fields = {}
        if not fields:
            schema = getattr(tool, "args_schema", None)
            for param, fld in (getattr(schema, "model_fields", None) or {}).items():
                for meta in getattr(fld, "metadata", None) or []:
                    if isinstance(meta, InjectedState):
                        fields[param] = meta.field
                        if fld.is_required():
                            required.add(param)
        if fields:
            injected[name] = fields
            injected_required[name] = required
    state = state or {}

    def _injected_args(name: str, args: dict[str, Any]) -> dict[str, Any]:
        fields = injected.get(name)
        if not fields:
            return args
        trusted: dict[str, Any] = {}
        for tool_arg, state_key in fields.items():
            if not state_key:
                # ToolNode injects the whole state dict for a field-less
                # InjectedState.
                trusted[tool_arg] = state
            elif state_key in state:
                trusted[tool_arg] = state[state_key]
            elif tool_arg in injected_required.get(name, set()):
                # ToolNode raises KeyError when a required injected field is
                # absent from state. Raising here turns that into a status="error"
                # ToolMessage instead of letting the tool run with a forged or
                # default value.
                raise KeyError(state_key)
            # Optional field with no state value: leave the tool's own default.
        # Strip caller-supplied values for injected args, then add back only the
        # trusted ones (ToolNode's ordering, so state always wins).
        stripped = {k: v for k, v in args.items() if k not in fields}
        return {**stripped, **trusted}

    def _run(calls: list[dict[str, Any]]) -> list[Any]:
        # One ``_run`` invocation is exactly one tool round: the model asked for
        # this batch, the runner executes it, and the ToolMessages go back to the
        # model. Single-pass never touches the graph's ToolNode, so without this
        # the round counter stays 0 even though rounds happened (V3 finding).
        from tradingagents.observability import record_tool_round

        if not calls:
            # No model turn, no round: the loop calls the runner only when the
            # model actually asked for tools.
            return []
        round_started = time.monotonic()
        round_status, round_error = "ok", None
        results: list[Any] = []
        try:
            executed = _execute_calls(calls, results)
            if executed and all(getattr(m, "status", None) == "error" for m in executed):
                round_status = "error"
            return executed
        except BaseException as exc:  # noqa: BLE001 - re-raised unchanged
            round_status, round_error = "error", type(exc).__name__
            raise
        finally:
            record_tool_round(
                number_of_tool_calls=len(calls), started_at=round_started,
                ended_at=time.monotonic(), status=round_status,
                error_type=round_error,
            )

    def _execute_calls(calls: list[dict[str, Any]], results: list[Any]) -> list[Any]:
        for call in calls:
            name = call.get("name")
            if not isinstance(name, str):
                continue
            tool = by_name.get(name)
            if tool is None:
                results.append(ToolMessage(
                    content=f"Error: {name} is not a valid tool, try one of "
                            f"{sorted(by_name)}.",
                    name=name, tool_call_id=call.get("id"), status="error",
                ))
                continue
            try:
                content = tool.invoke(
                    _injected_args(name, call.get("args") or {})
                )
                results.append(ToolMessage(
                    content=content if isinstance(content, str) else str(content),
                    name=name, tool_call_id=call.get("id"),
                ))
            except Exception as exc:  # noqa: BLE001 - a tool error is a message
                results.append(ToolMessage(
                    content=f"Error: {type(exc).__name__}: {exc}",
                    name=name, tool_call_id=call.get("id"), status="error",
                ))
        return results

    return _run


def _terminal_messages(
    emitted: list[Any],
    history: list[Any],
    rendered: str,
    *,
    drop_last: bool = True,
) -> list[Any]:
    """The assistant/tool messages to return when the loop ends deliberately.

    LangGraph's routing reads ``state["messages"][-1].tool_calls``
    (``ConditionalLogic.should_continue_*``) and ``MessagesState`` appends what a
    node returns. So whatever this node hands back must (a) be a legal
    assistant/tool sequence and (b) leave an assistant turn **without** pending
    tool calls last, or the graph routes back into the tool node.

    ``emitted`` alone is not enough. It holds only assistant turns; the
    ``ToolMessage`` results this runner executed live in ``history``. Returning
    the assistant turns without their results leaves a dangling tool call at the
    end of the state, the tool node runs that call again, and the analyst is
    re-entered -- an unbounded loop that also re-executes the data tool.

    So return the executed turns **with** their results, and finish with a
    no-tool-call ``AIMessage`` carrying the rendered report. The schema-carrying
    turn itself is dropped (it is not a data tool result and must never be
    replayed). On the common k>=1 path this is the k data-tool rounds plus their
    results plus one terminal turn.
    """
    # Build the sequence straight from ``emitted`` (the assistant turns, in
    # order) plus the results this runner executed, so every data tool call is
    # immediately followed by its own ``ToolMessage``. Slicing ``history`` is
    # not equivalent: ``history`` interleaves results, so its tail length does
    # not line up with ``len(emitted)`` once the schema turn is present.
    results: dict[str, Any] = {}
    for m in history:
        if getattr(m, "type", None) == "tool" and getattr(m, "tool_call_id", None):
            results[m.tool_call_id] = m

    turns: list[Any] = []
    for i, turn in enumerate(emitted):
        if drop_last and i == len(emitted) - 1:
            # The schema-carrying turn is not a data tool result: never replay
            # it from shared state.
            break
        declared = list(getattr(turn, "tool_calls", None) or [])
        data_calls = [c for c in declared if c.get("id") in results]
        if not data_calls:
            # Nothing this turn asked for was executed (e.g. a schema call that
            # rode along with a data call on an earlier mixed turn). Putting the
            # turn back would leave a tool call the graph would re-run.
            continue
        if len(data_calls) != len(declared):
            # A mixed turn: keep only the calls this runner executed, otherwise
            # the schema call would stay dangling in shared state.
            turn = turn.model_copy(update={"tool_calls": data_calls})
        turns.append(turn)
        for call in data_calls:
            result = results.get(call.get("id"))
            if result is not None:
                turns.append(result)
    if not turns:
        # The loop answered on its very first turn: nothing was executed, so end
        # on an explicit no-tool-call turn. Appending an empty list would leave
        # the prior HumanMessage last and routing would raise on ``.tool_calls``.
        turns.append(AIMessage(content=rendered))
    elif not isinstance(turns[-1], AIMessage) or getattr(turns[-1], "tool_calls", None):
        # Last element is a tool result or a turn whose call the graph must not
        # run again: close the loop with the report as a plain assistant turn.
        turns.append(AIMessage(content=rendered))
    return turns


def _schema_tool_call(result: Any, schema_tool: str) -> dict[str, Any] | None:
    """The schema tool call carried by ``result``, if any."""
    for call in getattr(result, "tool_calls", None) or []:
        if isinstance(call, dict) and call.get("name") == schema_tool:
            return call
    return None


def _free_text_retry(
    prompt: Any, llm: Any, history: list[Any], agent_name: str
) -> tuple[str, Any]:
    """One prose retry that cannot replay a dangling tool call.

    ``finalize_single_pass`` appends the assistant turn to ``history`` *before*
    validating its schema call. When validation fails, replaying ``history``
    unchanged sends an assistant message with ``tool_calls`` and no matching
    ``ToolMessage`` (V3 R12: provider 400), and invoking bare ``llm`` drops the
    analyst system prompt. This helper drops a trailing tool-call-only assistant
    turn and goes through the caller's prompt, so both the message pairing and
    the system prompt are correct.

    This is a real outbound request, so it is settled once like any other
    attempt (ADR-009): the chat model emits its own callback events, which the
    capture-backed instrumentation around ``invoke`` counts.
    """
    retry_history = list(history)
    if retry_history:
        last = retry_history[-1]
        if getattr(last, "type", None) == "ai" and getattr(last, "tool_calls", None):
            retry_history.pop()
    messages = _single_pass_messages(retry_history)
    chain = prompt | llm if prompt is not None else llm
    response = instrumented_model_call(
        lambda: chain.invoke(messages),
        phase="analyst",
        speaker=agent_name,
        prompt_chars=_messages_chars(messages),
    )
    text = getattr(response, "content", "") or ""
    sanitized, _info = sanitize_analyst_text(text, agent_name=agent_name)
    return sanitized, response


def _single_pass_free_text(
    llm: Any, history: list[Any], agent_name: str, prompt: Any = None
) -> str:
    """Ask once for a prose report over the history gathered so far.

    The last-resort ending for the single-pass loop: the model never produced a
    schema call and never produced prose either (budget exhausted, or every tool
    in the round failed). One plain ``llm.invoke`` over the full history is
    exactly the turn RC1 would have written, so the node asks for a real report
    instead of returning a code-built empty string.

    This cannot guarantee non-empty text: if the model itself answers with ``""``
    the result is ``""``, exactly as RC1's ``finalize_analyst_report`` returns the
    empty ``free_text_block`` it was handed. An empty ending is logged as a
    warning and never dressed up as a valid structured report (``report_obj``
    stays ``None``); it is a run-quality anomaly to flag, not a normal ending.
    """
    content, _response = _free_text_retry(prompt, llm, history, agent_name)
    if not content.strip():
        logger.warning("%s: single-pass ending produced no text", agent_name)
    return content


def finalize_single_pass(
    llm: Any,
    structured_llm: Any | None,
    prompt: Any,
    messages: list[Any],
    tools: list[Any],
    schema: type[T],
    render: Callable[[T], str] | None,
    agent_name: str,
    run_tools: Callable[[list[Any]], list[Any]] | None = None,
    state: dict[str, Any] | None = None,
    accept: Callable[[T], str] | None = None,
    executed: list[Any] | None = None,
) -> tuple[str, T | None, list[Any]]:
    """CAND-01: write the structured report on the call that would have written prose.

    The RC1 two-call path (:func:`finalize_analyst_report`) ends the tool loop
    with a full prose report and then pays a second call to regenerate the same
    analysis as typed fields, discarding the prose. On the RC1 2x2 pilot the
    discarded turn averaged 4,151 output tokens across 12 analyst finalisations
    while the replacement call's input was within 156 tokens of it, so the prose
    is the repeatable cost.

    Here the schema is bound as one more tool beside the data tools. The loop is
    untouched — the model may keep calling data tools — but when it is ready to
    answer it emits the schema tool call instead of prose, and that call *is* the
    report. Nothing is written twice.

    ``run_tools`` executes a list of data-tool calls and returns their
    ``ToolMessage`` results; it is the caller's own tool node, so tool side
    effects, error handling and observability are identical to the graph's.
    ``state`` is the analyst's graph state, used to inject the hidden
    ``trade_date`` into the data tools exactly as ``ToolNode`` would.

    Accounting (ADR-009): every round below is one outbound request through one
    binding, and each is settled once by that binding's handler — so a loop of k
    rounds plus a retry is counted as k+1 attempts, never as one node-level call
    and never twice. The free-text retries go through
    :func:`instrumented_model_call`, so they are counted too, and an unbound run
    stays a transparent passthrough. A budget denial raised by the binding
    propagates unchanged: no fallback request is made on its behalf.

    Every fallback lands on the untouched RC1 behaviour, so this can only change
    the report's shape. It removes the code-built blank ending, but it neither
    guarantees non-empty text (a model that emits ``""`` still yields ``""``,
    as in RC1) nor is every failure converted into a success -- read the
    remaining risks below:

    * ``structured_llm is None`` (single-pass off / provider unsupported) -> the
      two-call path's plain loop, prose returned exactly as before.
    * this call produced no schema call and no tool calls (model answered in
      prose) -> :func:`finalize_analyst_report` finalises that prose.
    * the schema call fails validation -> ``llm.invoke`` once on the same
      single-pass prompt, as the two-call path does.
    * the round budget is exhausted with data-tool calls still pending, or every
      tool in a round failed -> ``llm.invoke`` once as free text, so a run that
      gathered tools but never answered still gets one free-text attempt.

    ``accept`` lets the caller post-process the parsed schema instance and
    return the text to use; it runs on the success branch only, after the loop
    has finished, so it sees every ``ToolMessage`` this runner executed (PF-01:
    the news node classifies its source from that history, which does not exist
    until the loop has run). Raising from it is a normal failure: the loop
    falls back to the free-text retry like any other schema error. Callers that
    need the history must supply ``accept`` instead of ``render``; supplying
    neither is a programming error, not a runtime condition.

    ``executed`` is an optional list that is filled (in place, and by
    reference while the loop runs) with every message this runner produced —
    assistant turns and the ``ToolMessage`` results it executed — so a caller
    can classify evidence after the fact without holding the loop's return
    value.

    Returns ``(rendered_or_prose, report_object, messages_to_return)``.
    """
    schema_tool = _schema_tool_name(schema)
    phase = _phase_for(agent_name)
    if render is None and accept is None:
        raise TypeError(
            f"{agent_name}: finalize_single_pass needs render= or accept=")
    # ``accept`` is the post-loop hook; the plain renderer is the same hook with
    # no history to read, so both take one argument and one code path runs.
    if accept is None:
        accept = render
    if run_tools is None:
        run_tools = run_data_tools(tools, state=state)

    if structured_llm is None:
        result = instrumented_model_call(
            lambda: (prompt | llm.bind_tools(tools)).invoke(messages),
            phase=phase,
            speaker=agent_name,
            prompt_chars=_messages_chars(messages),
        )
        if getattr(result, "tool_calls", None):
            return "", None, [result]  # graph's tool node runs it; normal loop
        record_structured_attempt(agent_name, kind="unsupported", used_fallback=True)
        safe_text, _info = sanitize_analyst_text(
            getattr(result, "content", "") or "", agent_name=agent_name)
        return safe_text, None, [result]

    bound = llm.bind_tools([*tools, schema])
    history = list(messages)
    emitted: list[Any] = []
    if executed is not None:
        executed.clear()
        executed.extend(history)

    for _ in range(SINGLE_PASS_MAX_ROUNDS):
        # One outbound request per round; the binding settles each one exactly
        # once (either through its own handler or around ``invoke``), so a
        # denied round raises ``BudgetDeniedError`` before any fallback.
        result = _call_schema_binding(
            bound,
            history,
            phase=phase,
            speaker=agent_name,
            prompt_chars=_messages_chars(history),
        )
        history.append(result)
        emitted.append(result)

        schema_call = _schema_tool_call(result, schema_tool)
        # A model may emit the schema together with a data-tool call in the same
        # turn ("fetch these and finalise"). Treating that as terminal would
        # silently drop the requested evidence, so execute the data calls first
        # and only accept the schema on a turn that asks for no data.
        all_calls = list(getattr(result, "tool_calls", None) or [])
        # Only a *data* call beside the schema makes a turn mixed. Counting raw
        # calls would misclassify two schema calls (a model slip) as mixed and
        # drop a valid structured report to prose.
        mixed = schema_call is not None and any(
            c.get("name") != schema_tool for c in all_calls)
        if mixed:
            logger.info(
                "%s: schema and data tools requested in one turn; running the "
                "data tool(s) first", agent_name)
            # The schema call is not executed, so it must not stay on the
            # assistant turn: the next request would carry an unresolved
            # tool_call id and an OpenAI-compatible provider rejects it exactly
            # like R12 (audit A, MEDIUM). Keep only the data calls.
            data_only = [c for c in all_calls if c.get("name") != schema_tool]
            result = result.model_copy(update={"tool_calls": data_only})
            history[-1] = result
            emitted[-1] = result
            all_calls = data_only
        if schema_call is not None and not mixed:
            started_at = time.monotonic()
            try:
                assert schema is not None
                if not schema_call.get("id"):
                    # ToolMessage/parser bookkeeping expects an id on every tool
                    # call the model emits; without one the message cannot be
                    # serialised back into the history.
                    raise ValueError("schema tool call carried no call id")
                report = schema.model_validate(schema_call.get("args") or {})
                assert accept is not None
                rendered = accept(report)
                if not rendered or not rendered.strip():
                    raise ValueError("structured render produced an empty report")
                record_structured_attempt(
                    agent_name, kind="success",
                    started_at=started_at, ended_at=time.monotonic(),
                )
                # The schema call is not a data tool result, so the graph has
                # nothing to execute: this turn ends the analyst. The assistant
                # message that carried it is dropped from the shared history, as
                # the two-call path drops its prose turn, so the next analyst
                # never replays a stray tool call.
                return rendered, report, _terminal_messages(emitted, history, rendered)
            except BudgetDeniedError:
                raise
            except Exception as exc:  # noqa: BLE001 - never abort a run
                logger.warning(
                    "%s: single-pass structured call failed (%s); "
                    "retrying once as free text", agent_name, exc,
                )
                record_structured_attempt(
                    agent_name, kind="failure", used_fallback=True, error=exc,
                    started_at=started_at, ended_at=time.monotonic(),
                )
                # The loop may already hold data-tool results, and those are
                # what the free-text answer has to stand on, so finalise over
                # them rather than over the pre-loop history.
                # ``history`` still ends with the schema-carrying turn: the
                # retry helper drops it (no dangling tool_call) and goes through
                # ``prompt`` (system prompt preserved) — V3 R12's 400.
                text, response = _free_text_retry(prompt, llm, history, agent_name)
                # Fold the free-text answer into history so the shared state
                # carries the data-tool rounds *with* their results, then close
                # on the prose turn.
                history.append(response)
                emitted.append(response)
                return text, None, _terminal_messages(
                    emitted, history, text, drop_last=False)

        # Data-tool calls (skipping the schema call when a turn mixed both).
        data_calls = [c for c in getattr(result, "tool_calls", None) or []
                      if c.get("name") != schema_tool]
        if not data_calls:
            # The model answered in prose on this turn instead of filling the
            # schema. RC1 treats that prose as the finished report and returns
            # it unchanged, so do the same: paying a second call to restructure
            # it would reintroduce the very duplication this path removes, and
            # finalising over a history that has the prose stripped out would be
            # strictly worse than RC1. ``report_obj`` stays None exactly as it
            # does in RC1 whenever structure is unavailable.
            prose = getattr(result, "content", "") or ""
            if not prose.strip():
                prose = _single_pass_free_text(llm, history, agent_name, prompt=prompt)
            else:
                # A reply can be protocol markup even when it carries no
                # tool_calls (the V3 R07/R14 mechanism); sanitize this path too
                # (audit A, HIGH).
                prose, _markup_info = sanitize_analyst_text(
                    prose, agent_name=agent_name)
            record_structured_attempt(agent_name, kind="failure", used_fallback=True)
            # The prose turn is itself the terminating assistant turn, so keep
            # it (drop_last=False). Earlier data-tool rounds ride along with the
            # results this runner already executed, so no tool call is left
            # dangling in shared state.
            return prose, None, _terminal_messages(
                emitted, history, prose, drop_last=False)

        rounds_before = len(history)
        history.extend(run_tools(data_calls))
        if executed is not None:
            executed.extend(history[rounds_before:])
        # A round in which every call failed to execute (unknown name, tool
        # error) leaves the model nothing new to read; looping on it would just
        # burn rounds.
        if all(getattr(m, "status", None) == "error" for m in history[-len(data_calls):]):
            break

    # The loop ended without a report: either the round budget ran out with the
    # model still asking for data tools, or every tool in the last round failed.
    # Do not return a code-built blank report -- ask once for free text over
    # everything gathered, which is what RC1's ending turn did. The model may
    # still answer with "" (RC1 would too); that is logged and left as None
    # rather than reported as a valid structured result.
    #
    # Record exactly one structured event, as RC1's ``finalize_analyst_report``
    # does on every return. No schema call happened here, so this must NOT be
    # reported as a success: it is a failure of structured output (the model
    # never emitted one) that fell back to prose. ``exhausted`` says which of the
    # two endings fired, so the run can tell a truncated loop from dead tools.
    exhausted = "round budget" if emitted else "no round"
    record_structured_attempt(
        agent_name, kind="failure", used_fallback=True,
        error=ValueError(f"no schema call within {SINGLE_PASS_MAX_ROUNDS} rounds "
                         "(budget exhausted or every tool failed)"),
    )
    logger.info("%s: single-pass loop ended without a schema call (%s)",
                agent_name, exhausted)
    prose = _single_pass_free_text(llm, history, agent_name, prompt=prompt)
    # The data-tool rounds ride along with the results this runner executed, and
    # the free-text answer closes the sequence, so shared state has no dangling
    # tool call for the graph to replay.
    return prose, None, _terminal_messages(emitted, history, prose, drop_last=False)
