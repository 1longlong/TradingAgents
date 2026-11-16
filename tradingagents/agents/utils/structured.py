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
import re
import time
from collections.abc import Callable
from typing import Any, TypeVar

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
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
    return bound


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
        safe_text, _info = sanitize_analyst_text(free_text_block, agent_name=agent_name)
        return safe_text, None

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
    from langgraph.prebuilt.tool_node import InjectedState

    from langchain_core.messages import ToolMessage

    by_name: dict[str, Any] = {}
    # name -> {tool_arg: state_key | None}; every entry is stripped from the
    # model's args, matching ToolNode's ``all_injected_keys``.
    injected: dict[str, dict[str, str | None]] = {}
    # name -> required injected args (ToolNode raises when these are missing).
    injected_required: dict[str, set[str]] = {}
    try:
        from langgraph.prebuilt.tool_node import _get_all_injected_args
    except Exception:  # noqa: BLE001 - private helper moved; use the schema scan
        _get_all_injected_args = None

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
        results = []
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
    from langchain_core.messages import AIMessage

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
    """
    retry_history = list(history)
    if retry_history:
        last = retry_history[-1]
        if getattr(last, "type", None) == "ai" and getattr(last, "tool_calls", None):
            retry_history.pop()
    messages = _single_pass_messages(retry_history)
    response = ((prompt | llm).invoke(messages) if prompt is not None
                else llm.invoke(messages))
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

    Every fallback lands on the untouched RC1 behaviour, so this can only change
    the report's shape. It removes the code-built blank ending, but it neither
    guarantees non-empty text (a model that emits ``""`` still yields ``""``,
    as in RC1) nor is every failure converted into a success -- read the
    remaining risks below:

    * ``structured_llm is None`` (S2 off / provider unsupported) -> plain loop,
      prose returned exactly as before S2.
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
        result = (prompt | llm.bind_tools(tools)).invoke(messages)
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
        result = (prompt | bound).invoke(history)
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
                if not schema_call.get("id"):
                    # ToolMessage/parser bookkeeping expects an id on every tool
                    # call the model emits; without one the message cannot be
                    # serialised back into the history.
                    raise ValueError("schema tool call carried no call id")
                report = schema.model_validate(schema_call.get("args") or {})
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
        error=ValueError("no schema call within %d rounds (budget exhausted "
                         "or every tool failed)" % SINGLE_PASS_MAX_ROUNDS),
    )
    logger.info("%s: single-pass loop ended without a schema call (%s)",
                agent_name, exhausted)
    prose = _single_pass_free_text(llm, history, agent_name, prompt=prompt)
    # The data-tool rounds ride along with the results this runner executed, and
    # the free-text answer closes the sequence, so shared state has no dangling
    # tool call for the graph to replay.
    return prose, None, _terminal_messages(emitted, history, prose, drop_last=False)
