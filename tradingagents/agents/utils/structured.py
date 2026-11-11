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
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from tradingagents.observability import record_structured_attempt

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


def bind_structured(llm: Any, schema: type[T], agent_name: str) -> Any | None:
    """Return ``llm.with_structured_output(schema)`` or ``None`` if unsupported.

    Logs a warning when the binding fails so the user understands the agent
    will use free-text generation for every call instead of one-shot fallback.
    """
    try:
        llm_with_schema = llm.with_structured_output(schema)
    except (NotImplementedError, AttributeError) as exc:
        logger.warning(
            "%s: provider does not support with_structured_output (%s); "
            "falling back to free-text generation",
            agent_name, exc,
        )
        record_structured_attempt(agent_name, kind="unsupported", error=exc)
        return None
    record_structured_attempt(agent_name, kind="success")
    return llm_with_schema


def invoke_structured_or_freetext(
    structured_llm: Any | None,
    plain_llm: Any,
    prompt: Any,
    render: Callable[[T], str],
    agent_name: str,
    structured_prompt: Any | None = None,
) -> str:
    """Run the structured call and render to markdown; fall back to free-text on any failure.

    ``prompt`` is whatever the underlying LLM accepts (a string for chat
    invocations, a list of message dicts for chat models that take that
    shape). The same value is forwarded to the free-text path so the
    fallback sees the same input the structured call did.

    ``structured_prompt`` overrides only what the *structured* call receives
    (see :func:`split_free_text_guidance`); the free-text fallback always keeps
    the original ``prompt``, which carries the output format a provider without
    structured output needs. Passing ``None`` keeps the historical behaviour of
    sending ``prompt`` to both.
    """
    started_at = time.monotonic()
    if structured_llm is not None:
        try:
            result = structured_llm.invoke(
                prompt if structured_prompt is None else structured_prompt
            )
            if result is None:
                # A thinking model can answer in plain text instead of calling
                # the tool, leaving the parser with nothing to return. Treat it
                # as a structured miss and fall back, with a clear reason.
                raise ValueError("structured output returned no parsed result")
            record_structured_attempt(
                agent_name, kind="success", started_at=started_at, ended_at=time.monotonic()
            )
            return render(result)
        except Exception as exc:
            logger.warning(
                "%s: structured-output invocation failed (%s); retrying once as free text",
                agent_name, exc,
            )
            record_structured_attempt(
                agent_name, kind="failure", used_fallback=True, error=exc,
                started_at=started_at, ended_at=time.monotonic(),
            )

    # ``structured_llm`` is None only when the provider reported it does not
    # support structured output (see ``bind_structured``). Record that the
    # resulting free-text fallback was used at the invocation/runtime scope so
    # the unsupported status is observable in real run telemetry (the
    # construction-time event in bind_structured fires outside a run scope).
    if structured_llm is None:
        record_structured_attempt(
            agent_name, kind="unsupported", used_fallback=True,
            started_at=started_at, ended_at=time.monotonic(),
        )

    response = plain_llm.invoke(prompt)
    return response.content


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


def finalize_analyst_report(
    llm: Any,
    structured_llm: Any | None,
    messages: list[Any],
    render: Callable[[T], str],
    agent_name: str,
    free_text_block: str,
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

    Note on cost: the schema travels as a tool definition on this one call, so
    it adds its token size to that call's input. It is not re-sent on every
    tool turn, which is what makes the trade viable (see the campaign's
    structured_output/level2_results.md for the measurement).

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
        return free_text_block, None

    structured_messages = _prepare_structured_messages(messages)

    started_at = time.monotonic()
    try:
        result = structured_llm.invoke(structured_messages)
        if result is None:
            raise ValueError("structured output returned no parsed result")
        rendered = render(result)
        if not rendered or not rendered.strip():
            raise ValueError("structured render produced an empty report")
        record_structured_attempt(
            agent_name, kind="success", started_at=started_at, ended_at=time.monotonic()
        )
        return rendered, result
    except Exception as exc:  # noqa: BLE001 - a shape change must never abort a run
        logger.warning(
            "%s: structured finalisation failed (%s); keeping the free-text report",
            agent_name, exc,
        )
        record_structured_attempt(
            agent_name, kind="failure", used_fallback=True, error=exc,
            started_at=started_at, ended_at=time.monotonic(),
        )
        return free_text_block, None
