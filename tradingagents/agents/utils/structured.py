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
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel

from tradingagents.debate.usage_capture import BudgetDeniedError, instrumented_model_call

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

# Map the agent name to its whole-run usage phase (ADR-009). Unknown agents fall
# back to a constant ``unknown_phase`` so a free-form string is never persisted.
_AGENT_PHASE = {
    "Research Manager": "research_manager",
    "Trader": "trader",
    "Portfolio Manager": "portfolio",
    "Sentiment Analyst": "analyst",
}


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
    """
    try:
        return llm.with_structured_output(schema, include_raw=True)
    except Exception as exc:  # noqa: BLE001 — maybe only ``include_raw`` is unsupported
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
            return llm.with_structured_output(schema)
        except (NotImplementedError, AttributeError) as bind_exc:
            logger.warning(
                "%s: provider does not support with_structured_output (%s); "
                "falling back to free-text generation",
                agent_name, bind_exc,
            )
            return None


def invoke_structured_or_freetext(
    structured_llm: Any | None,
    plain_llm: Any,
    prompt: Any,
    render: Callable[[T], str],
    agent_name: str,
    *,
    affordable: Callable[[], bool] | None = None,
    admit_attempt: Callable[[], str | None] | None = None,
    sanitize_result: Callable[[Any], Any] | None = None,
) -> str:
    """Run the structured call and render to markdown; fall back to free-text on any failure.

    ``sanitize_result`` (ADR-011) is an optional transform applied to a TYPED
    structured result BEFORE :func:`render`. It returns the (possibly transformed)
    result and may append audit entries to a caller-owned sink closed over by the
    caller. It exists so the degraded-run confidence cap can see the model's
    ORIGINAL full-precision numeric confidence and cap it before the lossy
    2-decimal rendering discards the raw value (e.g. ``0.6000001`` would otherwise
    render as ``0.60`` and never register as an over-cap event). A transform that
    raises still falls back to free text exactly as before.

    ``prompt`` is whatever the underlying LLM accepts (a string for chat
    invocations, a list of message dicts for chat models that take that
    shape). The same value is forwarded to the free-text path so the
    fallback sees the same input the structured call did.

    ADR-009: each actual model attempt (the structured call and, on failure, the
    free-text fallback) is instrumented so the whole-run total counts both real
    attempts. A structured attempt that returns a Pydantic result is charged with
    the rendered output length (never a fabricated ``0``) and preserves any
    provider telemetry the result carries. A structured attempt that RAISES is a
    counted, unresolved (unknown-cost) attempt, then the fallback runs as a second
    attempt. When no usage capture is bound this is a transparent passthrough.

    ``affordable`` (ADR-009) is an optional re-check consulted before the free-text
    FALLBACK attempt (and, when there is no structured LLM, before the single
    free-text attempt). When it returns ``False`` a :class:`BudgetDeniedError` is
    raised instead of making that attempt, so a previously-failed/unknown-cost
    attempt cannot be retried against the same reserve; the caller (e.g. the
    Research Manager) uses its deterministic fallback.

    ``admit_attempt`` (ADR-009) is an optional ATOMIC admission callable consulted
    before EVERY actual model attempt (structured AND fallback). It returns a
    pre-allocated durable invocation id (already reserved) or ``None`` when the
    attempt must be denied (fail closed). This is how the Research Manager
    atomically consumes ONE call slot per summary attempt across separate capture
    instances.
    """
    phase = _phase_for(agent_name)

    def _admit() -> str | None:
        if admit_attempt is None:
            return None
        admitted = admit_attempt()
        if admitted is None:
            raise BudgetDeniedError(
                f"{agent_name}: summary attempt not affordable (budget/accounting denial)"
            )
        # Empty string means "proceed on the memory-only path, no pre-id".
        return admitted or None

    if structured_llm is not None:
        try:
            prealloc = _admit()
            holder: dict[str, Any] = {}

            def _structured_transport_call() -> Any:
                # The BILLED boundary is ONLY the outbound transport invocation.
                # Parsing/sanitizing/rendering happen AFTER settlement so a
                # downstream failure can never turn a KNOWN raw provider usage into
                # an unknown-cost record.
                raw_envelope = structured_llm.invoke(prompt)
                holder["raw_envelope"] = raw_envelope
                return raw_envelope

            # Settle the single structured attempt from the RAW transport usage.
            # ``usage_response`` extracts provider usage from the raw envelope's
            # AIMessage when present; the estimate hint (legacy binding, no raw) is
            # a SAFE serialization length of the raw/typed object — never an
            # arbitrary renderer invoked inside the billed-call boundary.
            instrumented_model_call(
                _structured_transport_call,
                phase=phase,
                speaker=agent_name,
                prompt_chars=_prompt_chars(prompt),
                response_chars_hint=lambda: _safe_output_length(
                    _raw_or_parsed(holder.get("raw_envelope"))
                ),
                usage_response=lambda: _raw_from_envelope(holder.get("raw_envelope")),
                preallocated_id=prealloc,
            )
            # ---- Downstream (post-settlement) parse / sanitize / render ----
            # The outbound call is already settled with its real usage; a failure
            # here is a graceful fallback, NOT an unmetered/unknown second cost.
            raw_envelope = holder.get("raw_envelope")
            raw, parsed = _unwrap_structured(raw_envelope, holder)
            holder["raw"] = raw
            if parsed is not None and sanitize_result is not None:
                # Cap the TYPED confidence at full raw precision BEFORE the lossy
                # 2-decimal render (ADR-011). Only a real parsed object is capped.
                parsed = sanitize_result(parsed)
            if parsed is None:
                # A thinking/weak model answered without a parseable object (raw
                # text, or a tool call the parser dropped). The attempt above was
                # already settled with the provider's real usage (never a second
                # call); now fall back once, with a clear reason.
                raise ValueError("structured output returned no parsed result")
            rendered = render(parsed)
            return rendered
        except BudgetDeniedError:
            # A budget/accounting denial is NOT a provider failure: do not retry
            # as free text (that would spend again). Propagate so the caller uses
            # its deterministic fallback.
            raise
        except Exception as exc:
            # The structured attempt (if it reached the provider) was already
            # settled by the wrapper as a counted attempt with its real usage. A
            # post-settlement parse/sanitize/render failure falls through to the
            # free-text retry, which is a second counted attempt.
            logger.warning(
                "%s: structured-output invocation failed (%s); retrying once as free text",
                agent_name, exc,
            )

    # Guard the (fallback or single) free-text attempt with the affordability
    # re-check so an unknown-cost prior attempt is not retried against the reserve.
    if affordable is not None and not affordable():
        raise BudgetDeniedError(
            f"{agent_name}: free-text attempt not affordable (budget/accounting denial)"
        )
    # Atomically admit this (fallback) attempt too, so a structured→free-text
    # fallback consumes a SEPARATE call slot atomically.
    fallback_prealloc = _admit()
    response = instrumented_model_call(
        lambda: plain_llm.invoke(prompt),
        phase=phase,
        speaker=agent_name,
        prompt_chars=_prompt_chars(prompt),
        preallocated_id=fallback_prealloc,
    )
    return response.content


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
