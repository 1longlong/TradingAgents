"""Core observability infrastructure for TradingAgents (Phase 1).

This module is deliberately **observability only**. It records logical LangChain
LLM invocations and tool executions without changing any trading/business
semantics, prompts, agent instructions, model configuration, available tools,
routing, debate/risk behavior, agent outputs/schemas, memory/external-data
behavior, or intentional LLM-call behavior.

It does **not** implement (explicitly out of scope):
- token/tool-result compression
- Evidence Packet / Claim Ledger
- duplicate-call blocking or caching
- batch tools
- adaptive routing

Phase 2 extensions implemented here (still observability-only):
- ToolNode round instrumentation (``attrib_tool_round``)
- persistent telemetry output (``write_telemetry_artifact``)
- agent-node scope wiring (``attrib_agent_node``)
- direct Sentiment prefetch tracking (``record_prefetch_call``)
- structured-output attempt tracking (``record_structured_attempt``)
- run lifecycle (``run_telemetry`` / ``begin`` / ``finalize``) with one collector
  and one artifact per analysis run

Key concerns addressed here:

* **Stable agent IDs** are defined once and shared (no scattered string maps).
* **Agent execution scope** uses a ``ContextVar`` so it is safe under nested /
  concurrent execution, restores prior scope correctly, survives exceptions,
  and cannot leak across agents.
* **RunMetricsCollector** owns a unique ``telemetry_run_id`` per analysis run,
  thread-safe mutation, a collector-global monotonic sequence, and per-agent
  local sequences. Runs are fully independent (no cross-run leak).
* **ObservabilityCallbackHandler** records every logical LLM invocation and tool
  execution, deduplicated by LangChain's ``run_id``. Provider-reported usage is
  authoritative; missing usage is UNKNOWN/PARTIAL, never zero. Raw prompt and
  tool-result contents are never stored.

The module imports only stdlib and langchain_core (already a dependency).
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import os
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, ToolMessage

logger = logging.getLogger(__name__)

__all__ = [
    # Stable agent IDs
    "AGENT_MARKET_ANALYST",
    "AGENT_SENTIMENT_ANALYST",
    "AGENT_NEWS_ANALYST",
    "AGENT_FUNDAMENTALS_ANALYST",
    "AGENT_BULL_RESEARCHER",
    "AGENT_BEAR_RESEARCHER",
    "AGENT_RESEARCH_MANAGER",
    "AGENT_TRADER",
    "AGENT_AGGRESSIVE_ANALYST",
    "AGENT_CONSERVATIVE_ANALYST",
    "AGENT_NEUTRAL_ANALYST",
    "AGENT_PORTFOLIO_MANAGER",
    "AGENT_UNATTRIBUTED",
    "ALL_AGENT_IDS",
    # Scope
    "get_current_agent_id",
    "agent_scoped",
    # Determinism helpers
    "utf8_byte_size",
    "canonical_serialize",
    "sha256_fingerprint",
    "fingerprint_tool_arguments",
    # Phase 2 event records
    "ToolRoundEvent",
    "PrefetchSourceEvent",
    "StructuredOutputEvent",
    "NodeContextEvent",
    # Node / scope wiring helpers
    "NODE_TO_AGENT",
    "agent_id_for_node",
    "ANALYST_KEY_TO_AGENT",
    "analyst_agent_id_for_key",
    "size_agent_state_context",
    "AGENT_STATE_CONTEXT_WHITELIST",
    "count_tool_calls_in_state",
    "attrib_agent_node",
    "attrib_tool_round",
    "record_prefetch_call",
    "record_structured_attempt",
    # Collector
    "RunMetricsCollector",
    "LLMCallEvent",
    "ToolExecutionEvent",
    # Callback handler
    "ObservabilityCallbackHandler",
    "scan_tool_calls",
    "extract_tool_message_bytes",
    # Run lifecycle + persistence
    "TELEMETRY_SCHEMA_VERSION",
    "run_telemetry",
    "begin_observability_run",
    "finalize_observability_run",
    "write_telemetry_artifact",
    "resolve_observability_collector",
    "bind_run_scope",
    "unbind_run_scope",
]


# ---------------------------------------------------------------------------
# Stable machine-readable agent IDs — single source of truth.
# ---------------------------------------------------------------------------
AGENT_MARKET_ANALYST = "market_analyst"
AGENT_SENTIMENT_ANALYST = "sentiment_analyst"
AGENT_NEWS_ANALYST = "news_analyst"
AGENT_FUNDAMENTALS_ANALYST = "fundamentals_analyst"
AGENT_BULL_RESEARCHER = "bull_researcher"
AGENT_BEAR_RESEARCHER = "bear_researcher"
AGENT_RESEARCH_MANAGER = "research_manager"
AGENT_TRADER = "trader"
AGENT_AGGRESSIVE_ANALYST = "aggressive_analyst"
AGENT_CONSERVATIVE_ANALYST = "conservative_analyst"
AGENT_NEUTRAL_ANALYST = "neutral_analyst"
AGENT_PORTFOLIO_MANAGER = "portfolio_manager"
AGENT_UNATTRIBUTED = "unattributed"

ALL_AGENT_IDS = frozenset({
    AGENT_MARKET_ANALYST,
    AGENT_SENTIMENT_ANALYST,
    AGENT_NEWS_ANALYST,
    AGENT_FUNDAMENTALS_ANALYST,
    AGENT_BULL_RESEARCHER,
    AGENT_BEAR_RESEARCHER,
    AGENT_RESEARCH_MANAGER,
    AGENT_TRADER,
    AGENT_AGGRESSIVE_ANALYST,
    AGENT_CONSERVATIVE_ANALYST,
    AGENT_NEUTRAL_ANALYST,
    AGENT_PORTFOLIO_MANAGER,
    AGENT_UNATTRIBUTED,
})


# ---------------------------------------------------------------------------
# Node-name → stable agent-id mapping (single source of truth for wiring).
# ---------------------------------------------------------------------------
# The graph adds every business-agent node by this display name (see
# ``tradingagents.graph.setup``). Mapping the display name to the stable agent
# id keeps agent attribution correct without inferring identity from generated
# text and without editing each agent factory.
NODE_TO_AGENT: dict[str, str] = {
    "Market Analyst": AGENT_MARKET_ANALYST,
    "Sentiment Analyst": AGENT_SENTIMENT_ANALYST,
    "News Analyst": AGENT_NEWS_ANALYST,
    "Fundamentals Analyst": AGENT_FUNDAMENTALS_ANALYST,
    "Bull Researcher": AGENT_BULL_RESEARCHER,
    "Bear Researcher": AGENT_BEAR_RESEARCHER,
    "Research Manager": AGENT_RESEARCH_MANAGER,
    "Trader": AGENT_TRADER,
    "Aggressive Analyst": AGENT_AGGRESSIVE_ANALYST,
    "Conservative Analyst": AGENT_CONSERVATIVE_ANALYST,
    "Neutral Analyst": AGENT_NEUTRAL_ANALYST,
    "Portfolio Manager": AGENT_PORTFOLIO_MANAGER,
}


def agent_id_for_node(node_name: str) -> str | None:
    """Return the stable agent id for a graph node name, or ``None``."""
    return NODE_TO_AGENT.get(node_name)


# Analyst wire-key (config/CLI selection) -> stable agent id.
ANALYST_KEY_TO_AGENT: dict[str, str] = {
    "market": AGENT_MARKET_ANALYST,
    "social": AGENT_SENTIMENT_ANALYST,
    "news": AGENT_NEWS_ANALYST,
    "fundamentals": AGENT_FUNDAMENTALS_ANALYST,
}


def analyst_agent_id_for_key(key: str) -> str:
    """Return the stable observability agent id for an analyst wire key."""
    return ANALYST_KEY_TO_AGENT.get(key, key)


# ---------------------------------------------------------------------------
# AgentState context whitelist (sizes only — never contents).
# ---------------------------------------------------------------------------
# ``size_agent_state_context`` measures the UTF-8 byte size of exactly these
# fields at node entry. Nested debate dictionaries are split into history and
# current/latest-response groups so each is measured separately.
AGENT_STATE_CONTEXT_WHITELIST = frozenset({
    "market_report",
    "sentiment_report",
    "news_report",
    "fundamentals_report",
    "investment_plan",
    "trader_investment_plan",
    "past_context",
    "portfolio_context",
})

# Investing debate nested keys -> sizing groups.
_INVEST_DEBATE_HISTORY_KEYS = ("history", "bull_history", "bear_history")
_INVEST_DEBATE_CURRENT_KEYS = ("current_response",)
# Risk debate nested keys -> sizing groups.
_RISK_DEBATE_HISTORY_KEYS = ("history", "aggressive_history", "conservative_history", "neutral_history")
_RISK_DEBATE_CURRENT_KEYS = ("current_aggressive_response", "current_conservative_response", "current_neutral_response")


def size_agent_state_context(state: Any) -> dict[str, int]:
    """Return ``{field: utf8_bytes}`` for the whitelisted AgentState fields.

    Only sizes are computed; contents are never stored. Unknown fields are
    ignored. Arrays of messages may appear (``List[List[BaseMessage]]`` or the
    current ``Annotated[List[BaseMessage]]`` shape); because ``messages`` is not
    in the whitelist it is never sized here.
    """
    context: dict[str, int] = {}
    if not isinstance(state, dict):
        return context
    for field in AGENT_STATE_CONTEXT_WHITELIST:
        value = state.get(field)
        if value is None:
            continue
        context[field] = utf8_byte_size(value)

    invest = state.get("investment_debate_state")
    if isinstance(invest, dict):
        invest_history = _sum_field_bytes(invest, _INVEST_DEBATE_HISTORY_KEYS)
        invest_current = _sum_field_bytes(invest, _INVEST_DEBATE_CURRENT_KEYS)
        if invest_history is not None:
            context["investment_debate_history"] = invest_history
        if invest_current is not None:
            context["investment_debate_current"] = invest_current

    risk = state.get("risk_debate_state")
    if isinstance(risk, dict):
        risk_history = _sum_field_bytes(risk, _RISK_DEBATE_HISTORY_KEYS)
        risk_current = _sum_field_bytes(risk, _RISK_DEBATE_CURRENT_KEYS)
        if risk_history is not None:
            context["risk_debate_history"] = risk_history
        if risk_current is not None:
            context["risk_debate_current"] = risk_current

    return context


def _sum_field_bytes(mapping: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    """Sum the UTF-8 byte size of the listed keys, or ``None`` when all absent."""
    total = 0
    found = False
    for key in keys:
        value = mapping.get(key)
        if value is None:
            continue
        total += utf8_byte_size(value)
        found = True
    return total if found else None


# ---------------------------------------------------------------------------
# Agent execution scope (ContextVar based).
# ---------------------------------------------------------------------------
# The current agent id, or None when no agent scope is active. ContextVar is
# copied per async task / context, so concurrent execution cannot leak and the
# previous scope is restored automatically on context exit.
_current_agent_var: ContextVar[str | None] = ContextVar(
    "tradingagents_current_agent", default=None
)


def get_current_agent_id() -> str | None:
    """Return the current agent id, or ``None`` when no scope is active."""
    return _current_agent_var.get()


@contextmanager
def agent_scoped(agent_id: str | None):
    """Run a block with ``agent_id`` as the current agent scope.

    Restores the previous scope on exit even if the block raises. Supports
    nesting: the outer scope is preserved and restored afterwards. When
    ``agent_id`` is ``None`` the scope is unchanged (a no-op guard) — callers
    that lack an attribution should use ``AGENT_UNATTRIBUTED`` explicitly.
    """
    if agent_id is None:
        yield
        return
    token = _current_agent_var.set(agent_id)
    try:
        yield
    finally:
        _current_agent_var.reset(token)


# ---------------------------------------------------------------------------
# Deterministic, canonical serialization helpers.
# ---------------------------------------------------------------------------
def utf8_byte_size(value: Any) -> int:
    """Return the UTF-8 byte size of ``value`` (str, bytes, or serializable).

    Unserializable objects fall back to their repr so the helper never raises
    inside telemetry paths. Never stores the value.
    """
    try:
        text = value if isinstance(value, str) else value.decode("utf-8")
    except (AttributeError, UnicodeDecodeError):
        text = repr(value)
    return len(text.encode("utf-8"))


def canonical_serialize(value: Any) -> str:
    """Produce a deterministic, canonical JSON string for ``value``.

    Sorts dict keys and normalizes separators so semantically-equal objects with
    different key insertion order serialize identically. Uses ``json.dumps``
    with ``sort_keys=True`` and no whitespace.
    """
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=_json_default,
    )


def _json_default(obj: Any) -> Any:
    """Best-effort fallback for objects JSON cannot serialize natively."""
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if hasattr(obj, "dict") and callable(obj.dict):
        return obj.dict()
    if hasattr(obj, "model_dump") and callable(obj.model_dump):
        return obj.model_dump()
    return repr(obj)


def sha256_fingerprint(value: Any) -> str:
    """Return a hex SHA-256 fingerprint of the canonical form of ``value``."""
    digest = hashlib.sha256()
    digest.update(canonical_serialize(value).encode("utf-8"))
    return digest.hexdigest()


def normalize_tool_arguments(arguments: Any) -> dict[str, Any]:
    """Return a normalized (dict) form of tool arguments for fingerprinting.

    Accepts the permissive shapes LangChain hands to ``on_tool_start`` (a
    ``dict`` of arguments, or a JSON string). Never uses ``hash()``.
    """
    if arguments is None:
        return {}
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except (ValueError, TypeError):
            return {"_raw": arguments}
        if isinstance(parsed, dict):
            return parsed
        return {"_value": parsed}
    if hasattr(arguments, "dict") and callable(arguments.dict):
        return arguments.dict()
    if hasattr(arguments, "model_dump") and callable(arguments.model_dump):
        return arguments.model_dump()
    return {"_value": arguments}


def fingerprint_tool_arguments(
    agent_id: str, tool_name: str, arguments: Any
) -> str:
    """Return a deterministic SHA-256 fingerprint of a tool invocation.

    ``SHA-256(agent_id + tool_name + canonical normalized arguments)``. Dict key
    order is irrelevant because the arguments are canonicalized (sorted). Uses a
    stable separator to avoid agent/tool name collisions.
    """
    normalized = normalize_tool_arguments(arguments)
    canonical = canonical_serialize(normalized)
    payload = f"{agent_id}\n{tool_name}\n{canonical}"
    return sha256_fingerprint(payload)


def scan_tool_calls(message: Any) -> list[dict[str, Any]]:
    """Return the ``tool_calls`` on an AIMessage as a list of dicts, or ``[]``."""
    calls = getattr(message, "tool_calls", None)
    if not calls:
        return []
    result = []
    for call in calls:
        if isinstance(call, dict):
            result.append(call)
        else:
            result.append(
                {
                    "name": getattr(call, "name", ""),
                    "args": getattr(call, "args", {}),
                    "id": getattr(call, "id", ""),
                }
            )
    return result


def _collect_message_counts(
    messages: list[Any],
) -> tuple[int, int]:
    """Return ``(prompt_message_count, tool_message_count)`` from a message batch.

    ``messages`` is the ``list[list[BaseMessage]]`` shape passed to
    ``on_chat_model_start``. Only counts are computed; contents are never kept.
    """
    prompt_count = 0
    tool_count = 0
    for batch in messages:
        batch_items = batch if isinstance(batch, (list, tuple)) else [batch]
        for message in batch_items:
            if isinstance(message, ToolMessage):
                tool_count += 1
            else:
                prompt_count += 1
    return prompt_count, tool_count


def _message_content_bytes(message: Any) -> int:
    """UTF-8 byte size of a message's *content* (never the object repr).

    Uses ``.content`` when the object exposes it (BaseMessage); otherwise falls
    back to ``utf8_byte_size`` on the object.
    """
    if isinstance(message, (str, bytes)):
        return utf8_byte_size(message)
    content = getattr(message, "content", None)
    if content is not None:
        return utf8_byte_size(content)
    return utf8_byte_size(message)


def _prompt_message_bytes(messages: list[Any]) -> int:
    """Return total UTF-8 bytes of non-Tool (prompt) messages' content only."""
    total = 0
    for batch in messages:
        batch_items = batch if isinstance(batch, (list, tuple)) else [batch]
        for message in batch_items:
            if not isinstance(message, ToolMessage):
                total += _message_content_bytes(message)
    return total


def extract_tool_message_bytes(messages: list[Any]) -> int:
    """Return total UTF-8 bytes of ToolMessage contents without storing them."""
    total = 0
    for batch in messages:
        batch_items = batch if isinstance(batch, (list, tuple)) else [batch]
        for message in batch_items:
            if isinstance(message, ToolMessage):
                total += _message_content_bytes(message)
    return total


# ---------------------------------------------------------------------------
# Event records and the run-scoped collector.
# ---------------------------------------------------------------------------
@dataclass
class LLMCallEvent:
    """One logical LangChain LLM invocation.

    Never contains full prompt or message contents — only counts and byte sizes.
    """
    telemetry_run_id: str
    callback_run_id: str
    agent_id: str
    global_sequence: int
    agent_sequence: int
    # reported-input counting uses ``*_sum`` fields on the collector.
    model: str | None = None
    provider: str | None = None
    parent_run_id: str | None = None
    started_at: float | None = None
    ended_at: float | None = None
    duration_s: float | None = None
    prompt_message_count: int = 0
    prompt_utf8_bytes: int = 0
    tool_message_count: int = 0
    tool_message_utf8_bytes: int = 0
    reported_input_tokens: int | None = None
    reported_output_tokens: int | None = None
    reported_reasoning_tokens: int | None = None
    reported_cached_input_tokens: int | None = None
    usage_source: str | None = None
    usage_complete: bool = False
    success: bool = True
    error_class: str | None = None


@dataclass
class ToolExecutionEvent:
    """One executed tool invocation. Never stores the raw tool result."""
    telemetry_run_id: str
    agent_id: str
    tool_name: str
    global_sequence: int
    agent_sequence: int
    callback_run_id: str | None = None
    parent_run_id: str | None = None
    started_at: float | None = None
    ended_at: float | None = None
    duration_s: float | None = None
    success: bool = True
    error_type: str | None = None
    arguments_fingerprint: str | None = None
    result_utf8_bytes: int | None = None
    result_sha256: str | None = None
    duplicate_count: int = 0


@dataclass
class ToolRoundEvent:
    """One ToolNode execution batch (a round), not an individual tool call.

    ``number_of_tool_calls`` is the count of tools actually executed in this
    batch. It is recorded by observing the ToolNode batch directly — it is never
    inferred from the ``tool_calls`` counter.
    """
    telemetry_run_id: str
    agent_id: str
    sequence: int
    number_of_tool_calls: int = 0
    started_at: float | None = None
    ended_at: float | None = None
    duration_ms: float | None = None
    status: str = "ok"
    error_type: str | None = None


@dataclass
class PrefetchSourceEvent:
    """One sentiment-analyst direct-prefetch call (never a LangChain tool)."""
    telemetry_run_id: str
    agent_id: str
    source: str
    started_at: float | None = None
    ended_at: float | None = None
    duration_ms: float | None = None
    result_utf8_bytes: int = 0
    success: bool = True
    error_type: str | None = None


@dataclass
class StructuredOutputEvent:
    """One structured-output attempt outcome.

    ``kind`` is one of ``"success"``, ``"failure"`` or ``"unsupported"``;
    ``used_fallback`` is true when the plain ``llm.invoke`` free-text path was
    taken (either because structured output failed or was unsupported).
    """
    telemetry_run_id: str
    agent_id: str
    agent_name: str
    kind: str
    used_fallback: bool = False
    started_at: float | None = None
    ended_at: float | None = None
    duration_ms: float | None = None
    error_type: str | None = None


@dataclass
class NodeContextEvent:
    """One business-agent node execution (context sized at entry)."""
    telemetry_run_id: str
    agent_id: str
    node: str
    started_at: float | None = None
    ended_at: float | None = None
    wall_time_ms: float | None = None
    status: str = "ok"
    error_type: str | None = None
    context_bytes: dict[str, int] = field(default_factory=dict)


# Sentinel for "no token info reported" so we never confuse it with a real 0.
_MISSING = object()

# The immutable schema version written into every telemetry artifact.
TELEMETRY_SCHEMA_VERSION = 1


class RunMetricsCollector:
    """Collect telemetry for a single analysis run (or test).

    Attributes and named interfaces:
    - ``telemetry_run_id``: unique per collector instance (per analysis run).
    - ``new_run()`` / ``new_run_id()``: factory for independent runs.
    - thread-safe mutation via an internal lock.
    - ``global_sequence``: collector-global monotonic counter of recorded
      events (LLM + tool), assigned at record time.
    - per-agent local sequence counters for LLM and tool events.
    - ``finalize()``: idempotently marks the run closed; recording after
      finalize is a no-op (defensive, does not raise).
    - ``snapshot()`` / ``serialize_metrics()``: deterministic serialization.

    Runs are independent: no shared mutable module state, so sequential or
    concurrent collectors never leak metrics into each other.
    """

    def __init__(self, telemetry_run_id: str | None = None) -> None:
        self.telemetry_run_id = telemetry_run_id or new_run_id()
        self._lock = threading.Lock()
        self._closed = False
        self._next_global_sequence = 0
        # agent_id -> {kind: next_seq}
        self._agent_sequences: dict[str, dict[str, int]] = {}
        self.llm_calls: list[LLMCallEvent] = []
        self.tool_calls: list[ToolExecutionEvent] = []
        self.tool_rounds: list[ToolRoundEvent] = []
        self.prefetch_events: list[PrefetchSourceEvent] = []
        self.structured_events: list[StructuredOutputEvent] = []
        self.node_events: list[NodeContextEvent] = []
        # Duplicate tool executions observed (incremented, never blocked).
        self.duplicate_tool_call_count = 0
        # Token/success aggregates (provider-reported is authoritative).
        self.llm_success_count = 0
        self.llm_error_count = 0
        self.llm_calls_with_provider_usage = 0
        self.llm_calls_without_provider_usage = 0
        self.reported_input_tokens_sum = 0
        self.reported_output_tokens_sum = 0
        self.reported_reasoning_tokens_sum = 0
        self.reported_cached_input_tokens_sum = 0
        self.usage_complete = False

        # Run metadata + lifecycle (Phase 2). ``_run_started`` is idempotently
        # set by ``begin_run`` and guards against double begin / double write.
        self.schema_version = TELEMETRY_SCHEMA_VERSION
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.run_status: str | None = None
        self.failure_type: str | None = None
        self.ticker: str | None = None
        self.trade_date: str | None = None
        self.asset_type: str | None = None
        self.selected_analysts: list[str] = []
        self.llm_provider: str | None = None
        self.quick_think_model: str | None = None
        self.deep_think_model: str | None = None
        self.max_debate_rounds: int | None = None
        self.max_risk_rounds: int | None = None
        self.results_dir: str | None = None
        self._run_started = False
        self._run_finished = False
        self._telemetry_written = False
        self._telemetry_path: str | None = None

    # -- lifecycle ---------------------------------------------------------
    def finalize(self) -> None:
        """Close the run for recording (idempotent)."""
        with self._lock:
            self._closed = True

    def is_finalized(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def llm_calls_count(self) -> int:
        with self._lock:
            return len(self.llm_calls)

    @property
    def tool_calls_count(self) -> int:
        with self._lock:
            return len(self.tool_calls)

    @property
    def tool_rounds_count(self) -> int:
        with self._lock:
            return len(self.tool_rounds)

    # -- run lifecycle -----------------------------------------------------
    def begin_run(self, **metadata: Any) -> None:
        """Idempotently mark the run started and record run metadata.

        The first call wins; later calls with different metadata are ignored so
        a double-begin (e.g. from the CLI and the graph both wrapping a call)
        cannot reset or overwrite the run.
        """
        with self._lock:
            if self._run_started:
                return
            self._run_started = True
            self.started_at = time.monotonic()
            self.run_status = "running"
            for field, value in metadata.items():
                if value is None:
                    continue
                setattr(self, field, value)

    def finish_run(self, status: str, failure_type: str | None = None) -> None:
        """Idempotently mark the run finished with ``status``.

        ``status`` is one of ``"completed"``, ``"failed"`` or ``"interrupted"``.
        ``failure_type`` is a sanitized class name. The first call wins.
        """
        with self._lock:
            if self._run_finished:
                return
            self._run_finished = True
            self.run_status = status
            self.finished_at = time.monotonic()
            if failure_type is not None:
                self.failure_type = failure_type

    def is_run_started(self) -> bool:
        with self._lock:
            return self._run_started

    def is_run_finished(self) -> bool:
        with self._lock:
            return self._run_finished

    def mark_telemetry_written(self) -> None:
        with self._lock:
            self._telemetry_written = True

    def has_telemetry_been_written(self) -> bool:
        with self._lock:
            return self._telemetry_written

    @property
    def telemetry_path(self) -> str | None:
        """Return the telemetry artifact path, when known.

        Returns the persisted path after ``write_telemetry_artifact`` succeeds,
        otherwise the path the run's artifact *would* be written to (derived from
        the run's results dir / ticker / trade date). ``None`` when the artifact
        is not applicable (e.g. no results directory).
        """
        with self._lock:
            if self._telemetry_path is not None:
                return self._telemetry_path
        computed = _compute_telemetry_path(self)
        return str(computed) if computed is not None else None

    # -- sequencing --------------------------------------------------------
    def _next_agent_sequence(self, agent_id: str, kind: str) -> int:
        per_agent = self._agent_sequences.setdefault(agent_id, {})
        current = per_agent.get(kind, 0)
        per_agent[kind] = current + 1
        return current

    # -- LLM events --------------------------------------------------------
    def record_llm_call(self, event: LLMCallEvent) -> int:
        """Record a logical LLM call. Returns the global sequence assigned."""
        with self._lock:
            if self._closed:
                return -1
            sequence = self._next_global_sequence
            self._next_global_sequence += 1
            event.global_sequence = sequence
            event.agent_sequence = self._next_agent_sequence(event.agent_id, "llm")
            self.llm_calls.append(event)
            if event.success:
                self.llm_success_count += 1
            else:
                self.llm_error_count += 1
            has_usage = event.usage_source is not None
            if has_usage:
                self.llm_calls_with_provider_usage += 1
                self.reported_input_tokens_sum += event.reported_input_tokens or 0
                self.reported_output_tokens_sum += event.reported_output_tokens or 0
                if event.reported_reasoning_tokens is not None:
                    self.reported_reasoning_tokens_sum += event.reported_reasoning_tokens
                if event.reported_cached_input_tokens is not None:
                    self.reported_cached_input_tokens_sum += event.reported_cached_input_tokens
            else:
                self.llm_calls_without_provider_usage += 1
            # Completeness updates only when the newest event asserts it (we
            # never down-grade a previously-complete run on a later partial).
            if has_usage and event.usage_complete and not self.usage_complete:
                self.usage_complete = True
            elif not has_usage:
                self.usage_complete = False
            return sequence

    def record_tool_execution(self, event: ToolExecutionEvent) -> int:
        """Record a tool execution. Returns the global sequence assigned."""
        with self._lock:
            if self._closed:
                return -1
            sequence = self._next_global_sequence
            self._next_global_sequence += 1
            event.global_sequence = sequence
            event.agent_sequence = self._next_agent_sequence(event.agent_id, "tool")
            self.tool_calls.append(event)
            if event.duplicate_count:
                self.duplicate_tool_call_count += 1
            return sequence

    # -- tool rounds -------------------------------------------------------
    def record_tool_round(self, event: ToolRoundEvent) -> int:
        """Record one ToolNode batch. Returns the per-agent round sequence."""
        with self._lock:
            if self._closed:
                return -1
            event.sequence = self._next_agent_sequence(event.agent_id, "round")
            self.tool_rounds.append(event)
            return event.sequence

    # -- prefetch ----------------------------------------------------------
    def record_prefetch(self, event: PrefetchSourceEvent) -> int:
        """Record one sentiment-analyst direct-prefetch call."""
        with self._lock:
            if self._closed:
                return -1
            self.prefetch_events.append(event)
            return len(self.prefetch_events)

    # -- structured output -------------------------------------------------
    def record_structured(self, event: StructuredOutputEvent) -> int:
        """Record one structured-output attempt outcome."""
        with self._lock:
            if self._closed:
                return -1
            self.structured_events.append(event)
            return len(self.structured_events)

    # -- node context ------------------------------------------------------
    def record_node(self, event: NodeContextEvent) -> int:
        """Record one business-agent node execution."""
        with self._lock:
            if self._closed:
                return -1
            self.node_events.append(event)
            return len(self.node_events)

    # -- snapshot / serialization ------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        """Return a deep summary of recorded metrics (deterministic)."""
        with self._lock:
            return {
                "telemetry_run_id": self.telemetry_run_id,
                "closed": self._closed,
                "llm_calls": len(self.llm_calls),
                "tool_calls": len(self.tool_calls),
                "duplicate_tool_call_count": self.duplicate_tool_call_count,
                "llm_success_count": self.llm_success_count,
                "llm_error_count": self.llm_error_count,
                "llm_calls_with_provider_usage": self.llm_calls_with_provider_usage,
                "llm_calls_without_provider_usage": self.llm_calls_without_provider_usage,
                "reported_input_tokens_sum": self.reported_input_tokens_sum,
                "reported_output_tokens_sum": self.reported_output_tokens_sum,
                "reported_reasoning_tokens_sum": self.reported_reasoning_tokens_sum,
                "reported_cached_input_tokens_sum": self.reported_cached_input_tokens_sum,
                "usage_complete": self.usage_complete,
            }

    def serialize_metrics(self) -> str:
        """Return a deterministic JSON string of the run snapshot."""
        return canonical_serialize(self.snapshot())

    def build_telemetry(self) -> dict[str, Any]:
        """Return the complete, deterministic telemetry payload for this run.

        Produces the immutable per-run artifact (schema, run metadata, usage
        coverage, audit quality, run totals, per-agent aggregates, and the
        event sections). Only counts, sizes, ids and sanitized names flow in —
        never raw prompts, messages, tool results, social/news feeds, state or
        memory contents.
        """
        with self._lock:
            return _build_telemetry_dict(self)


# A boring global monotonic counter for run-id generation so distinct collectors
# get distinct ids even in the same process (never shared data, just ids).
_run_id_counter = 0
_run_id_lock = threading.Lock()


def new_run_id() -> str:
    """Return a fresh, unique telemetry run id."""
    global _run_id_counter
    with _run_id_lock:
        _run_id_counter += 1
        return f"run-{uuid.uuid4().hex}-{_run_id_counter}"


# ---------------------------------------------------------------------------
# Per-run context so callbacks can bind a collector + run id + agent.
# ---------------------------------------------------------------------------
@dataclass
class _RunBinding:
    collector: RunMetricsCollector
    run_id: str


_run_var: ContextVar[_RunBinding | None] = ContextVar(
    "tradingagents_current_run", default=None
)


def _current_binding() -> _RunBinding | None:
    return _run_var.get()


def get_current_collector() -> RunMetricsCollector | None:
    bind = _run_var.get()
    return bind.collector if bind is not None else None


def bind_run_scope(collector: RunMetricsCollector | None):
    """Bind ``collector`` to the current context; return a token to unbind.

    Use with :func:`unbind_run_scope` when a run's lifecycle spans a block that
    cannot conveniently be wrapped in a ``with run_scoped(...)`` context manager
    (e.g. the CLI's streaming try/except/else/finally). The token must be passed
    to :func:`unbind_run_scope` exactly once, typically in a ``finally``.
    """
    if collector is None:
        return None
    return _run_var.set(_RunBinding(collector=collector, run_id=collector.telemetry_run_id))


def unbind_run_scope(token) -> None:
    """Reset a :func:`bind_run_scope` token (idempotent, never raises)."""
    if token is not None:
        try:
            _run_var.reset(token)
        except (ValueError, RuntimeError):  # noqa: BLE001 — already reset / wrong context.
            pass


@contextmanager
def run_scoped(collector: RunMetricsCollector | None):
    """Bind a collector (+ its run id) for the duration of a scope."""
    if collector is None:
        yield
        return
    token = bind_run_scope(collector)
    try:
        yield
    finally:
        unbind_run_scope(token)


@contextmanager
def observe_run(collector: RunMetricsCollector | None = None, agent_id: str | None = None):
    """Convenience: bind the collector *and* an agent scope together.

    ``agent_id`` may be ``None`` to leave agent attribution to the surrounding
    scope (or the caller's own ``agent_scoped`` block).
    """
    with run_scoped(collector):
        if agent_id is None:
            yield
            return
        with agent_scoped(agent_id):
            yield


# ---------------------------------------------------------------------------
# Callback handler.
# ---------------------------------------------------------------------------
class ObservabilityCallbackHandler(BaseCallbackHandler):
    """Record LLM and tool lifecycle events via LangChain callbacks.

    Every logical LLM invocation is recorded once, keyed by the callback
    ``run_id``. If both ``on_llm_start`` and ``on_chat_model_start`` fire for the
    same logical call (they may, depending on the model class / langchain
    version), a single event is produced. The ``run_id`` → ``agent_id`` mapping is
    frozen at start time so ``on_llm_end``/``on_llm_error`` are attributed
    correctly even if the ContextVar scope changed in between. Unknown/missing
    starts are safe (attributed to ``unattributed`` when no scope is active).

    Only counts and byte sizes flow into events; never raw prompts, tool
    arguments, or tool results. Provider-reported usage is copied from the
    message ``usage_metadata`` / ``response_metadata`` / ``llm_output``.
    """

    # Telemetry must never break or alter an LLM/tool call: callback errors are
    # logged, not raised, so the application exception (if any) is preserved.
    raise_error = False

    def __init__(self, collector: RunMetricsCollector | None = None) -> None:
        super().__init__()
        self._collector = collector
        self._lock = threading.Lock()
        # run_id(str) -> dict of start-time metadata.
        self._llm_starts: dict[str, dict[str, Any]] = {}
        self._tool_starts: dict[str, dict[str, Any]] = {}
        # run_id(str) -> tuple(agent_id, ...) frozen at start for attribution.
        self._llm_attribution: dict[str, str] = {}
        self._tool_attribution: dict[str, str] = {}

    def _resolve_collector(self) -> RunMetricsCollector | None:
        """Return the collector for this callback.

        An explicitly-bound collector wins; otherwise the per-run binding (set by
        ``run_scoped`` / ``observe_run``) is used. This lets the same handler
        instance serve many runs without cross-run leakage: each run's binding is
        read at event time from the ContextVar.
        """
        if self._collector is not None:
            return self._collector
        bind = _current_binding()
        return bind.collector if bind is not None else None

    @property
    def collector(self) -> RunMetricsCollector | None:
        """The collector this handler writes to (explicit, else run-bound)."""
        return self._resolve_collector()

    # -- LLM ---------------------------------------------------------------
    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        self._handle_llm_start(run_id, parent_run_id, serialized, prompts=None)

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        self._handle_llm_start(run_id, parent_run_id, serialized, messages=messages)

    def _handle_llm_start(self, run_id, parent_run_id, serialized, prompts=None, messages=None):
        if run_id is None:
            return
        rid = self._run_id_str(run_id)
        with self._lock:
            # Duplicate start for the same logical run_id: keep the first. This
            # handles cases where on_llm_start and on_chat_model_start both fire
            # for one call, and duplicate callback delivery.
            if rid in self._llm_starts:
                return

            agent_id = get_current_agent_id() or AGENT_UNATTRIBUTED
            self._llm_attribution[rid] = agent_id
            prompt_count = 0
            prompt_bytes = 0
            tool_count = 0
            tool_bytes = 0
            if prompts is not None:
                prompt_count = len(prompts)
                for p in prompts:
                    prompt_bytes += utf8_byte_size(p)
            else:
                prompt_count, tool_count = _collect_message_counts(messages)
                prompt_bytes = _prompt_message_bytes(messages)
                tool_bytes = extract_tool_message_bytes(messages)
            self._llm_starts[rid] = {
                "agent_id": agent_id,
                "parent_run_id": self._run_id_str(parent_run_id) if parent_run_id else None,
                "started_at": time.monotonic(),
                "model": _model_from_serialized(serialized),
                "provider": _provider_from_serialized(serialized),
                "prompt_message_count": prompt_count,
                "prompt_utf8_bytes": prompt_bytes,
                "tool_message_count": tool_count,
                "tool_message_utf8_bytes": tool_bytes,
            }

    def on_llm_end(self, response: Any, *, run_id: Any = None, **kwargs: Any) -> None:
        if run_id is None:
            return
        rid = self._run_id_str(run_id)
        with self._lock:
            start = self._llm_starts.get(rid)
            # Duplicate end delivery for an already-emitted run must not
            # double-count: drop it once the event was emitted.
            if start is None or start.get("emitted"):
                return
            start["emitted"] = True
            start_data = start
            self._llm_starts.pop(rid, None)
            self._llm_attribution.pop(rid, None)
        self._emit_llm(rid, start_data, response=response, success=True, error=None)

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        if run_id is None:
            return
        rid = self._run_id_str(run_id)
        with self._lock:
            start = self._llm_starts.get(rid)
            if start is None or start.get("emitted"):
                return
            start["emitted"] = True
            start_data = start
            self._llm_starts.pop(rid, None)
            self._llm_attribution.pop(rid, None)
        self._emit_llm(rid, start_data, response=None, success=False, error=error)

    def _emit_llm(self, rid, start_data, response, success, error):
        collector = self._resolve_collector()
        ended_at = time.monotonic()
        started_at = start_data.get("started_at")
        duration = (ended_at - started_at) if started_at is not None else None

        usage = _extract_usage(response) if response is not None else None

        event = LLMCallEvent(
            telemetry_run_id=collector.telemetry_run_id if collector else "",
            callback_run_id=rid,
            agent_id=start_data.get("agent_id", AGENT_UNATTRIBUTED),
            global_sequence=0,
            agent_sequence=0,
            model=start_data.get("model"),
            provider=start_data.get("provider"),
            parent_run_id=start_data.get("parent_run_id"),
            started_at=started_at,
            ended_at=ended_at,
            duration_s=duration,
            prompt_message_count=start_data.get("prompt_message_count", 0),
            prompt_utf8_bytes=start_data.get("prompt_utf8_bytes", 0),
            tool_message_count=start_data.get("tool_message_count", 0),
            tool_message_utf8_bytes=start_data.get("tool_message_utf8_bytes", 0),
            reported_input_tokens=usage["input"] if usage else None,
            reported_output_tokens=usage["output"] if usage else None,
            reported_reasoning_tokens=usage["reasoning"] if usage else None,
            reported_cached_input_tokens=usage["cached_input"] if usage else None,
            usage_source=usage["source"] if usage else None,
            usage_complete=usage["complete"] if usage else False,
            success=success,
            error_class=_sanitized_error_class(error),
        )
        if collector is not None:
            collector.record_llm_call(event)

    # -- Tools -------------------------------------------------------------
    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        if run_id is None:
            return
        rid = self._run_id_str(run_id)

        with self._lock:
            if rid in self._tool_starts:
                return
            agent_id = get_current_agent_id() or AGENT_UNATTRIBUTED
            self._tool_attribution[rid] = agent_id
            tool_name = _tool_name_from_serialized(serialized)
            arguments = inputs if inputs is not None else _parse_input_str(input_str)
            self._tool_starts[rid] = {
                "agent_id": agent_id,
                "parent_run_id": self._run_id_str(parent_run_id) if parent_run_id else None,
                "started_at": time.monotonic(),
                "tool_name": tool_name,
                "input_str": input_str,
                "inputs": arguments,
                "emitted": False,
            }

    def on_tool_end(self, output: Any, *, run_id: Any = None, **kwargs: Any) -> None:
        if run_id is None:
            return
        rid = self._run_id_str(run_id)
        with self._lock:
            start = self._tool_starts.get(rid)
            if start is None or start.get("emitted"):
                return
            start["emitted"] = True
            start_data = start
            self._tool_starts.pop(rid, None)
            agent_id = self._tool_attribution.pop(rid, AGENT_UNATTRIBUTED)
        self._emit_tool(rid, start_data, agent_id, output=output, success=True, error=None)

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        if run_id is None:
            return
        rid = self._run_id_str(run_id)
        with self._lock:
            start = self._tool_starts.get(rid)
            if start is None or start.get("emitted"):
                return
            start["emitted"] = True
            start_data = start
            self._tool_starts.pop(rid, None)
            agent_id = self._tool_attribution.pop(rid, AGENT_UNATTRIBUTED)
        self._emit_tool(rid, start_data, agent_id, output=None, success=False, error=error)

    def _emit_tool(self, rid, start_data, agent_id, output, success, error):
        collector = self._resolve_collector()
        ended_at = time.monotonic()
        started_at = start_data.get("started_at")
        duration = (ended_at - started_at) if started_at is not None else None
        tool_name = start_data.get("tool_name", "")
        arguments = start_data.get("inputs", {})
        fingerprint = fingerprint_tool_arguments(agent_id, tool_name, arguments)

        duplicate = self._count_duplicate(agent_id, tool_name, fingerprint)

        event = ToolExecutionEvent(
            telemetry_run_id=collector.telemetry_run_id if collector else "",
            agent_id=agent_id,
            tool_name=tool_name,
            global_sequence=0,
            agent_sequence=0,
            callback_run_id=rid,
            parent_run_id=start_data.get("parent_run_id"),
            started_at=started_at,
            ended_at=ended_at,
            duration_s=duration,
            success=success,
            error_type=_sanitized_error_class(error),
            arguments_fingerprint=fingerprint,
            result_utf8_bytes=utf8_byte_size(output) if success and output is not None else None,
            result_sha256=sha256_fingerprint(output) if success and output is not None else None,
            duplicate_count=duplicate,
        )
        if collector is not None:
            collector.record_tool_execution(event)

    def _count_duplicate(self, agent_id, tool_name, fingerprint) -> int:
        """Return 1 when this fingerprint has been seen for this run, else 0."""
        # Track per-run to keep collectors independent. A duplicate is a repeat
        # of (agent_id, tool_name, canonical args) already observed in this run.
        seen = getattr(self, "_seen_tool_fingerprints", None)
        if seen is None:
            seen = set()
            self._seen_tool_fingerprints = seen
        key = (agent_id, tool_name, fingerprint)
        is_dup = key in seen
        seen.add(key)
        return 1 if is_dup else 0

    @staticmethod
    def _run_id_str(run_id: Any) -> str:
        return str(run_id)


# ---------------------------------------------------------------------------
# Extraction helpers (private).
# ---------------------------------------------------------------------------
def _model_from_serialized(serialized: Any) -> str | None:
    if isinstance(serialized, dict):
        model = serialized.get("model") or serialized.get("model_name")
        if model:
            return str(model)
        # serialized may be the LLM id like {"lc","...","id":["...","ChatOpenAI"]}
        return None
    return getattr(serialized, "model_name", None) or getattr(serialized, "model", None)


def _provider_from_serialized(serialized: Any) -> str | None:
    return None


def _tool_name_from_serialized(serialized: Any) -> str:
    if isinstance(serialized, dict):
        return str(serialized.get("name") or serialized.get("_name") or "")
    return getattr(serialized, "name", "") or getattr(serialized, "name", "")


def _parse_input_str(input_str: str) -> dict[str, Any]:
    if not input_str:
        return {}
    try:
        parsed = json.loads(input_str)
        if isinstance(parsed, dict):
            return parsed
        return {"_value": parsed}
    except (ValueError, TypeError):
        return {"_raw": input_str}


def _sanitized_error_class(error: BaseException | None) -> str | None:
    """Return a sanitized (identifier-safe) error class name, never a repr."""
    if error is None:
        return None
    name = type(error).__name__
    return "".join(ch for ch in name if ch.isalnum() or ch == "_") or "Exception"


def _extract_usage(response: Any) -> dict[str, Any] | None:
    """Extract provider-reported usage from an ``on_llm_end`` response.

    Returns ``None`` when no provider usage was reported at all. When usage is
    present, greedily reads the canonical ``usage_metadata`` first (with the
    raw ``llm_output`` / ``response_metadata`` as fallback for providers that
    only populate those). Never invents zeros.
    """
    generation = _first_generation(response)
    if generation is None:
        return None

    message = getattr(generation, "message", None)
    # A single source dict for extraction.
    if isinstance(message, AIMessage):
        usage = _extract_usage_metadata(getattr(message, "usage_metadata", None))
        if usage is not None:
            return usage
        usage = _extract_usage_metadata(getattr(message, "response_metadata", None))
        if usage is not None:
            return usage

    llm_output = getattr(response, "llm_output", None)
    if llm_output:
        usage = _extract_usage_metadata(llm_output)
        if usage is not None:
            return usage

    return None


def _first_generation(response: Any) -> Any | None:
    generations = getattr(response, "generations", None)
    if not generations:
        return None
    first_batch = generations[0]
    if not first_batch:
        return None
    return first_batch[0]


def _extract_usage_metadata(raw: Any) -> dict[str, Any] | None:
    """Normalize a usage blob to our canonical fields, or ``None`` if absent.

    Handles both the canonical ``usage_metadata`` shape and the raw OpenAI-style
    ``token_usage`` / ``usage`` nested objects that some providers put in
    ``response_metadata`` or ``llm_output``.
    """
    if not isinstance(raw, dict):
        if hasattr(raw, "model_dump") and callable(raw.model_dump):
            raw = raw.model_dump()
        else:
            return None
    if not raw:
        return None

    # Unwrap common nested usage detail objects so the numbered-token lookup
    # below sees the prompt/completion/total fields regardless of nesting.
    nested = None
    for key in ("token_usage", "usage", "usage_metadata"):
        value = raw.get(key)
        if isinstance(value, dict):
            merged = dict(value)
            # Copy details blocks from the outer object if the inner lacks them.
            for detail_key in ("input_token_details", "output_token_details"):
                merged.setdefault(detail_key, raw.get(detail_key))
            merged.setdefault("total_tokens", raw.get("total_tokens"))
            nested = merged
            break
    if nested is not None:
        raw = nested

    input_tokens = _first_int(raw.get("input_tokens"), raw.get("prompt_tokens"))
    output_tokens = _first_int(raw.get("output_tokens"), raw.get("completion_tokens"))
    if input_tokens is _MISSING and output_tokens is _MISSING:
        # total_tokens only still gives partial (non-zero) info.
        total = raw.get("total_tokens")
        if total is None:
            return None
        # Without a split we cannot reliably derive input/output; treat as
        # unknown-but-present usage (partial). We record no numbers.
        return {
            "input": None,
            "output": None,
            "reasoning": None,
            "cached_input": None,
            "source": "provider",
            "complete": False,
        }

    # Cached-input is informational, from input_token_details.cache_read +
    # cache_creation; it is a detail of input_tokens, never added to totals.
    cached = None
    in_details = raw.get("input_token_details") or raw.get("input_tokens_details")
    if isinstance(in_details, dict):
        cached = _sum_ints([
            in_details.get("cache_read"),
            in_details.get("cache_creation"),
        ])

    # Reasoning is informational, a subset of output_tokens.
    reasoning = None
    out_details = raw.get("output_token_details") or raw.get("output_tokens_details")
    if isinstance(out_details, dict):
        reasoning = out_details.get("reasoning")
        if not isinstance(reasoning, int) or reasoning < 0:
            reasoning = None

    complete = (input_tokens is not _MISSING) and (output_tokens is not _MISSING)
    return {
        "input": None if input_tokens is _MISSING else input_tokens,
        "output": None if output_tokens is _MISSING else output_tokens,
        "reasoning": reasoning,
        "cached_input": cached,
        "source": "provider",
        "complete": complete,
    }


def _first_int(*values: Any) -> Any:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
    return _MISSING


def _sum_ints(values: list[Any]) -> int | None:
    total = 0
    found = False
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            total += value
            found = True
    return total if found else None


# ---------------------------------------------------------------------------
# Telemetry aggregate / payload building (module-level, lock held by caller).
# ---------------------------------------------------------------------------
def _new_agent_aggregate() -> dict[str, Any]:
    return {
        "llm_calls": 0,
        "llm_success_count": 0,
        "llm_error_count": 0,
        "calls_with_provider_usage": 0,
        "calls_without_provider_usage": 0,
        "reported_input_tokens_sum": 0,
        "reported_output_tokens_sum": 0,
        "reported_reasoning_tokens_sum": 0,
        "reported_cached_input_tokens_sum": 0,
        "prompt_utf8_bytes_sum": 0,
        "tool_message_utf8_bytes_sum": 0,
        "usage_complete": False,
        "tool_calls": 0,
        "tool_success_count": 0,
        "tool_error_count": 0,
        "tool_rounds": 0,
        "tool_result_utf8_bytes_sum": 0,
        "duplicate_tool_call_count": 0,
        "prefetched_data_calls": 0,
        "prefetched_data_utf8_bytes": 0,
        "structured_attempts": 0,
        "structured_successes": 0,
        "structured_failures": 0,
        "structured_fallbacks": 0,
        "structured_unsupported": 0,
        "node_invocations": 0,
        "node_wall_time_ms": 0.0,
    }


def _build_telemetry_dict(collector: RunMetricsCollector) -> dict[str, Any]:
    """Assemble the deterministic per-run telemetry dict under the lock."""
    agents: dict[str, dict[str, Any]] = {}

    def agg(agent_id: str) -> dict[str, Any]:
        return agents.setdefault(agent_id, _new_agent_aggregate())

    # LLM events.
    for ev in collector.llm_calls:
        a = agg(ev.agent_id)
        a["llm_calls"] += 1
        if ev.success:
            a["llm_success_count"] += 1
        else:
            a["llm_error_count"] += 1
        if ev.usage_source is not None:
            a["calls_with_provider_usage"] += 1
            a["reported_input_tokens_sum"] += ev.reported_input_tokens or 0
            a["reported_output_tokens_sum"] += ev.reported_output_tokens or 0
            if ev.reported_reasoning_tokens is not None:
                a["reported_reasoning_tokens_sum"] += ev.reported_reasoning_tokens
            if ev.reported_cached_input_tokens is not None:
                a["reported_cached_input_tokens_sum"] += ev.reported_cached_input_tokens
            if ev.usage_complete and not a["usage_complete"]:
                a["usage_complete"] = True
        else:
            a["calls_without_provider_usage"] += 1
        a["prompt_utf8_bytes_sum"] += ev.prompt_utf8_bytes
        a["tool_message_utf8_bytes_sum"] += ev.tool_message_utf8_bytes

    # Tool executions.
    for ev in collector.tool_calls:
        a = agg(ev.agent_id)
        a["tool_calls"] += 1
        if ev.success:
            a["tool_success_count"] += 1
        else:
            a["tool_error_count"] += 1
        if ev.result_utf8_bytes is not None:
            a["tool_result_utf8_bytes_sum"] += ev.result_utf8_bytes
        if ev.duplicate_count:
            a["duplicate_tool_call_count"] += 1

    # Tool rounds.
    for ev in collector.tool_rounds:
        a = agg(ev.agent_id)
        a["tool_rounds"] += 1

    # Prefetch.
    for ev in collector.prefetch_events:
        a = agg(ev.agent_id)
        a["prefetched_data_calls"] += 1
        a["prefetched_data_utf8_bytes"] += ev.result_utf8_bytes or 0

    # Structured output.
    for ev in collector.structured_events:
        a = agg(ev.agent_id)
        a["structured_attempts"] += 1
        if ev.kind == "success":
            a["structured_successes"] += 1
        elif ev.kind == "failure":
            a["structured_failures"] += 1
        elif ev.kind == "unsupported":
            a["structured_unsupported"] += 1
        if ev.used_fallback:
            a["structured_fallbacks"] += 1

    # Node context.
    for ev in collector.node_events:
        a = agg(ev.agent_id)
        a["node_invocations"] += 1
        a["node_wall_time_ms"] += (ev.wall_time_ms or 0.0)

    # Run totals = sum over all agents (unattributed is an explicit pseudo-agent).
    run_totals = {
        "llm_calls": sum(a["llm_calls"] for a in agents.values()),
        "llm_success_count": sum(a["llm_success_count"] for a in agents.values()),
        "llm_error_count": sum(a["llm_error_count"] for a in agents.values()),
        "calls_with_provider_usage": sum(a["calls_with_provider_usage"] for a in agents.values()),
        "calls_without_provider_usage": sum(a["calls_without_provider_usage"] for a in agents.values()),
        "reported_input_tokens_sum": sum(a["reported_input_tokens_sum"] for a in agents.values()),
        "reported_output_tokens_sum": sum(a["reported_output_tokens_sum"] for a in agents.values()),
        "reported_reasoning_tokens_sum": sum(a["reported_reasoning_tokens_sum"] for a in agents.values()),
        "reported_cached_input_tokens_sum": sum(a["reported_cached_input_tokens_sum"] for a in agents.values()),
        "tool_calls": sum(a["tool_calls"] for a in agents.values()),
        "tool_success_count": sum(a["tool_success_count"] for a in agents.values()),
        "tool_error_count": sum(a["tool_error_count"] for a in agents.values()),
        "tool_rounds": sum(a["tool_rounds"] for a in agents.values()),
        "tool_result_utf8_bytes_sum": sum(a["tool_result_utf8_bytes_sum"] for a in agents.values()),
        "duplicate_tool_call_count": sum(a["duplicate_tool_call_count"] for a in agents.values()),
        "prefetched_data_calls": sum(a["prefetched_data_calls"] for a in agents.values()),
        "prefetched_data_utf8_bytes": sum(a["prefetched_data_utf8_bytes"] for a in agents.values()),
        "structured_attempts": sum(a["structured_attempts"] for a in agents.values()),
        "structured_successes": sum(a["structured_successes"] for a in agents.values()),
        "structured_failures": sum(a["structured_failures"] for a in agents.values()),
        "structured_fallbacks": sum(a["structured_fallbacks"] for a in agents.values()),
        "structured_unsupported": sum(a["structured_unsupported"] for a in agents.values()),
        "node_invocations": sum(a["node_invocations"] for a in agents.values()),
        "node_wall_time_ms": round(sum(a["node_wall_time_ms"] for a in agents.values()), 3),
    }

    # Usage coverage (run-level).
    total_llm = run_totals["llm_calls"]
    with_usage = run_totals["calls_with_provider_usage"]
    without_usage = run_totals["calls_without_provider_usage"]
    usage_complete = bool(without_usage == 0 and total_llm > 0 and with_usage == total_llm)
    usage_coverage = {
        "llm_calls": total_llm,
        "calls_with_provider_usage": with_usage,
        "calls_without_provider_usage": without_usage,
        "complete": usage_complete,
    }

    unattributed_llm = agents.get(AGENT_UNATTRIBUTED, {}).get("llm_calls", 0)
    unattributed_tool = agents.get(AGENT_UNATTRIBUTED, {}).get("tool_calls", 0)
    # Read the private flags directly: the caller (build_telemetry) holds the
    # lock, so we must not re-acquire it here.
    run_finished = collector._run_finished
    audit_quality = {
        "usage_complete": usage_complete,
        "attribution_complete": bool(unattributed_llm == 0 and unattributed_tool == 0),
        # ``telemetry_complete`` means: this record corresponds to a run that
        # reached a TERMINAL state (completed/interrupted/failed) and was
        # finalized for persistence. It does NOT mean full provider token
        # coverage (see ``usage_complete``) nor that every event was attributed
        # (see ``attribution_complete``). Because the artifact is produced only
        # during finalize, this is always True within a persisted artifact.
        # ``_telemetry_written`` is the internal write-guard and is set *after*
        # serialization, so it cannot be part of the artifact's own self-report
        # (doing so would make it perpetually False).
        "telemetry_complete": bool(run_finished),
    }

    # Event sections (counts / sizes / ids / names only — never contents).
    event_lists = {
        "llm_call_events": [
            {
                "telemetry_run_id": ev.telemetry_run_id,
                "callback_run_id": ev.callback_run_id,
                "agent_id": ev.agent_id,
                "global_sequence": ev.global_sequence,
                "agent_sequence": ev.agent_sequence,
                "model": ev.model,
                "provider": ev.provider,
                "success": ev.success,
                "error_class": ev.error_class,
                "started_at": ev.started_at,
                "ended_at": ev.ended_at,
                "duration_s": ev.duration_s,
                "prompt_message_count": ev.prompt_message_count,
                "prompt_utf8_bytes": ev.prompt_utf8_bytes,
                "tool_message_count": ev.tool_message_count,
                "tool_message_utf8_bytes": ev.tool_message_utf8_bytes,
                "reported_input_tokens": ev.reported_input_tokens,
                "reported_output_tokens": ev.reported_output_tokens,
                "reported_reasoning_tokens": ev.reported_reasoning_tokens,
                "reported_cached_input_tokens": ev.reported_cached_input_tokens,
                "usage_source": ev.usage_source,
                "usage_complete": ev.usage_complete,
            }
            for ev in collector.llm_calls
        ],
        "tool_call_events": [
            {
                "telemetry_run_id": ev.telemetry_run_id,
                "agent_id": ev.agent_id,
                "tool_name": ev.tool_name,
                "global_sequence": ev.global_sequence,
                "agent_sequence": ev.agent_sequence,
                "callback_run_id": ev.callback_run_id,
                "success": ev.success,
                "error_type": ev.error_type,
                "started_at": ev.started_at,
                "ended_at": ev.ended_at,
                "duration_s": ev.duration_s,
                "arguments_fingerprint": ev.arguments_fingerprint,
                "result_utf8_bytes": ev.result_utf8_bytes,
                "result_sha256": ev.result_sha256,
                "duplicate_count": ev.duplicate_count,
            }
            for ev in collector.tool_calls
        ],
        "tool_round_events": [
            {
                "telemetry_run_id": ev.telemetry_run_id,
                "agent_id": ev.agent_id,
                "sequence": ev.sequence,
                "number_of_tool_calls": ev.number_of_tool_calls,
                "started_at": ev.started_at,
                "ended_at": ev.ended_at,
                "duration_ms": ev.duration_ms,
                "status": ev.status,
                "error_type": ev.error_type,
            }
            for ev in collector.tool_rounds
        ],
        "prefetch_events": [
            {
                "telemetry_run_id": ev.telemetry_run_id,
                "agent_id": ev.agent_id,
                "source": ev.source,
                "started_at": ev.started_at,
                "ended_at": ev.ended_at,
                "duration_ms": ev.duration_ms,
                "result_utf8_bytes": ev.result_utf8_bytes,
                "success": ev.success,
                "error_type": ev.error_type,
            }
            for ev in collector.prefetch_events
        ],
        "structured_events": [
            {
                "telemetry_run_id": ev.telemetry_run_id,
                "agent_id": ev.agent_id,
                "agent_name": ev.agent_name,
                "kind": ev.kind,
                "used_fallback": ev.used_fallback,
                "started_at": ev.started_at,
                "ended_at": ev.ended_at,
                "duration_ms": ev.duration_ms,
                "error_type": ev.error_type,
            }
            for ev in collector.structured_events
        ],
        "node_context_events": [
            {
                "telemetry_run_id": ev.telemetry_run_id,
                "agent_id": ev.agent_id,
                "node": ev.node,
                "started_at": ev.started_at,
                "ended_at": ev.ended_at,
                "wall_time_ms": ev.wall_time_ms,
                "status": ev.status,
                "error_type": ev.error_type,
                "context_bytes": dict(ev.context_bytes),
            }
            for ev in collector.node_events
        ],
    }

    return {
        "schema_version": collector.schema_version,
        "run": {
            "telemetry_run_id": collector.telemetry_run_id,
            "started_at": collector.started_at,
            "finished_at": collector.finished_at,
            "duration_ms": _duration_ms(collector.started_at, collector.finished_at),
            "run_status": collector.run_status,
            "failure_type": collector.failure_type,
            "ticker": collector.ticker,
            "trade_date": collector.trade_date,
            "asset_type": collector.asset_type,
            "selected_analysts": list(collector.selected_analysts),
            "llm_provider": collector.llm_provider,
            "quick_think_model": collector.quick_think_model,
            "deep_think_model": collector.deep_think_model,
            "max_debate_rounds": collector.max_debate_rounds,
            "max_risk_rounds": collector.max_risk_rounds,
        },
        "usage_coverage": usage_coverage,
        "audit_quality": audit_quality,
        "run_totals": run_totals,
        "unattributed_llm_events": unattributed_llm,
        "unattributed_tool_events": unattributed_tool,
        "agents": agents,
        **event_lists,
    }


def _duration_ms(started_at: float | None, finished_at: float | None) -> float | None:
    if started_at is None or finished_at is None:
        return None
    return round((finished_at - started_at) * 1000.0, 3)


# ---------------------------------------------------------------------------
# Run lifecycle (one collector, one begin, one finalize, one JSON artifact).
# ---------------------------------------------------------------------------
def resolve_observability_collector(handlers: list | None) -> RunMetricsCollector | None:
    """Return the collector bound to the first observability callback handler.

    Callbacks can be delivered through two distinct paths — the LLM constructor
    (``llm_kwargs["callbacks"]``) and the LangGraph execution config — but both
    arrive via the same handler instance, so they must share one collector. This
    finds the single collector so a run is never double-begun or double-written
    through two logical collectors.
    """
    if not handlers:
        return None
    for handler in handlers:
        collector = getattr(handler, "collector", None)
        if isinstance(collector, RunMetricsCollector):
            return collector
    return None


def begin_observability_run(
    handlers: list | None,
    *,
    results_dir: str | None = None,
    **metadata: Any,
) -> RunMetricsCollector:
    """Create or resolve the single run collector and mark it started.

    Always returns a usable collector (a fresh one when no observability handler
    supplies one), and always idempotently ``begin_run``s it so a double-begin
    from the CLI and graph paths cannot reset a run.
    """
    collector = resolve_observability_collector(handlers)
    if collector is None:
        collector = RunMetricsCollector()
    if results_dir is not None:
        collector.results_dir = str(results_dir)
    collector.begin_run(**metadata)
    return collector


def finalize_observability_run(
    collector: RunMetricsCollector | None,
    *,
    status: str = "completed",
    failure_type: str | None = None,
    write: bool = True,
) -> None:
    """Idempotently finish a run and write its single telemetry artifact.

    Never raises: a persistence or instrumentation failure must not fail an
    otherwise-valid analysis. The application exception (if any) is preserved by
    the caller, which re-raises it AFTER this attempts its best-effort write.
    """
    if collector is None:
        return
    try:
        collector.finish_run(status, failure_type=failure_type)
    except Exception:  # noqa: BLE001
        logger.warning("Could not finish observability run", exc_info=True)
    if write:
        try:
            already = collector.has_telemetry_been_written()
            if not already:
                write_telemetry_artifact(collector)
        except Exception:  # noqa: BLE001
            logger.warning("Could not write telemetry artifact", exc_info=True)


@contextmanager
def run_telemetry(
    handlers: list | None = None,
    *,
    results_dir: str | None = None,
    write: bool = True,
    **metadata: Any,
):
    """Wrap an analysis run: begin, bind, finalize, write, and contain failures.

    Yields the single ``RunMetricsCollector``. On success the run is marked
    ``completed`` and written once. On failure the run is marked ``failed`` with
    a sanitized failure type, telemetry is still written (partial metrics
    preserved), and the ORIGINAL application exception is re-raised. The
    observability path never swallows or replaces the application failure.
    """
    collector = begin_observability_run(handlers, results_dir=results_dir, **metadata)
    with run_scoped(collector):
        try:
            yield collector
        except BaseException as exc:  # noqa: BLE001 — we re-raise it below.
            collector.finish_run("failed", failure_type=_sanitized_error_class(exc))
            try:
                if write and not collector.has_telemetry_been_written():
                    write_telemetry_artifact(collector)
            except Exception:  # noqa: BLE001
                logger.warning("Could not write telemetry artifact", exc_info=True)
            raise
        else:
            finalize_observability_run(collector, status="completed", write=write)


# ---------------------------------------------------------------------------
# Telemetry JSON persistence (best-effort, never raises).
# ---------------------------------------------------------------------------
def _compute_telemetry_path(
    collector: RunMetricsCollector,
    *,
    results_dir: str | None = None,
    ticker: str | None = None,
    trade_date: str | None = None,
) -> Path:
    """Return the path a run's telemetry artifact is written to (no I/O).

    Mirrors :func:`write_telemetry_artifact` path construction so consumers can
    report the expected/last telemetry location without writing anything.
    """
    import importlib

    try:
        safe_mod = importlib.import_module("tradingagents.dataflows.utils")
    except Exception:  # noqa: BLE001
        safe_mod = None

    base = Path(results_dir or collector.results_dir or os.getcwd())
    run_ticker = ticker or collector.ticker
    run_date = trade_date or collector.trade_date

    safe_ticker = "unknown"
    if safe_mod is not None and run_ticker:
        try:
            safe_ticker = safe_mod.safe_ticker_component(run_ticker)
        except Exception:  # noqa: BLE001
            safe_ticker = "unknown"
    date_comp = str(run_date).replace("/", "-") if run_date else "unknown"
    return base / safe_ticker / date_comp / "telemetry" / f"{collector.telemetry_run_id}.json"


def write_telemetry_artifact(
    collector: RunMetricsCollector,
    *,
    results_dir: str | None = None,
    ticker: str | None = None,
    trade_date: str | None = None,
) -> Path | None:
    """Write exactly one immutable JSON telemetry artifact for the run.

    Path: ``<results_dir>/<safe_ticker>/<trade_date>/telemetry/<run_id>.json``.

    Uses a temporary file plus ``os.replace`` for an atomic write. Unique path
    via ``telemetry_run_id`` so earlier runs are never overwritten. Deterministic
    JSON via ``canonical_serialize``. Returns the written path, or ``None`` when
    it could not be written (logged — never raised).
    """
    if collector is None:
        return None

    try:
        path = _compute_telemetry_path(
            collector, results_dir=results_dir, ticker=ticker, trade_date=trade_date
        )
        telemetry_dir = path.parent
        telemetry_dir.mkdir(parents=True, exist_ok=True)

        payload = canonical_serialize(collector.build_telemetry())

        temp_path = path.with_suffix(f".{os.getpid()}.tmp")
        if os.environ.get("TRADINGAGENTS_TELEMETRY_SKIP_ATOMIC") != "1":
            temp_path = path.with_suffix(f".{os.getpid()}.tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(temp_path, path)

        with collector._lock:
            collector._telemetry_path = str(path)
        collector.mark_telemetry_written()
        return path
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not persist telemetry artifact: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Phase 2 instrumentation helpers (agent node wiring, tool rounds, prefetch,
# structured output). These never alter business semantics: they wrap existing
# callables, set an agent scope, and record observability events.
# ---------------------------------------------------------------------------
def count_tool_calls_in_state(state: Any) -> int:
    """Return how many tool calls a ToolNode batch would execute.

    A ToolNode round is triggered by an AI message carrying ``tool_calls``.
    Returns ``0`` when the state has no such message (no round). This counts
    individual tool executions in a batch — it is not inferred from the
    ``tool_calls`` counter elsewhere.
    """
    if not isinstance(state, dict):
        return 0
    messages = state.get("messages")
    if not messages:
        return 0
    # messages may be a list of BaseMessage (current shape).
    last = messages[-1] if isinstance(messages, (list, tuple)) else None
    if last is None:
        return 0
    tool_calls = getattr(last, "tool_calls", None)
    if not tool_calls:
        return 0
    return len(tool_calls)


def _callable_node_name(callable_: Callable, explicit_name: str | None = None,
                        _seen: frozenset | None = None) -> str:
    """Return a stable, human-meaningful name for a callable node without mutating it.

    Telemetry must not assume every business node is a plain function with a
    ``__name__`` attribute. TradingAgents nodes include real ``functools.partial``
    instances (e.g. the Trader), Runnables (ToolNode), and ordinary functions, so
    we resolve a name through a safe, explicitly-ordered fallback chain:

    1. ``explicit_name`` — the graph/business node name already known by
       ``setup.py`` (e.g. ``"Trader"``, ``"Market Analyst"``). Most useful/stable.
    2. ``callable_.__name__`` when it exists and is a string.
    3. ``functools.partial.func`` recursively (a partial calls its ``func``).
    4. the callable's class name as the final fallback.

    ``_seen`` guards against pathological recursive partials. The wrapped
    business callable is never mutated.
    """
    if explicit_name is not None:
        return explicit_name

    seen = _seen or frozenset()
    if id(callable_) in seen:
        # Deeply-recursive wrapper; avoid an infinite loop.
        name = getattr(callable_, "__name__", None)
        if name is None:
            name = type(callable_).__name__
        return name

    name = getattr(callable_, "__name__", None)
    if isinstance(name, str) and name:
        return name

    # ``functools.partial`` has no ``__name__``; unwrap its ``.func``.
    if isinstance(callable_, functools.partial):
        return _callable_node_name(callable_.func, None, seen | {id(callable_)})

    return type(callable_).__name__


def attrib_agent_node(agent_id: str, node: Callable, node_name: str | None = None):
    """Return a LangGraph node that sets ``agent_id`` scope and records node stats.

    The node executes inside ``agent_scoped(agent_id)`` so LLM/tool callbacks are
    attributed correctly. On entry the whitelisted AgentState field sizes are
    measured; on exit the wall time is recorded. Exceptions are re-raised
    unchanged after a failure event is recorded. The previous scope is restored
    and no raw state/tool contents are ever stored.

    ``node_name`` is the explicit, stable graph/business node name (e.g.
    ``"Trader"``) already known by ``setup.py``. It is used verbatim for the
    recorded node event regardless of how ``node`` is implemented (plain
    function, ``functools.partial``, Runnable, ...). When omitted, a safe
    ``_callable_node_name`` fallback resolves a name without mutating ``node``.
    """
    resolved_name = _callable_node_name(node, node_name)

    def wrapped(*args, **kwargs):
        # LangGraph passes the state as the first positional argument.
        state = args[0] if args else (kwargs.get("state") if "state" in kwargs else None)
        context_bytes = size_agent_state_context(state) if isinstance(state, dict) else {}
        started_at = time.monotonic()
        status = "ok"
        error_type = None
        with agent_scoped(agent_id):
            try:
                result = node(*args, **kwargs)
            except BaseException as exc:  # noqa: BLE001 — re-raised unchanged
                status = "error"
                error_type = _sanitized_error_class(exc)
                ended_at = time.monotonic()
                _record_node_event(agent_id, resolved_name, started_at, ended_at,
                                   status, error_type, context_bytes)
                raise
        ended_at = time.monotonic()
        _record_node_event(agent_id, resolved_name, started_at, ended_at,
                           status, error_type, context_bytes)
        return result

    # Preserve the underlying node's identity where useful for introspection.
    wrapped.__name__ = resolved_name
    wrapped.__wrapped__ = node
    return wrapped


def attrib_tool_round(agent_id: str, tool_node: Callable | None = None):
    """Wrap a ToolNode to scope it and record each batch.

    Usable directly (``attrib_tool_round(aid, node)``) or as a decorator
    (``@attrib_tool_round(aid)``). One ToolNode invocation === one round.
    ``number_of_tool_calls`` is the count of tool calls in the batch (observed
    directly). ToolNode behavior is preserved exactly; failures are re-raised.
    """
    def wrap(node: Callable):
        # A real ``langgraph.prebuilt.ToolNode`` is a LangChain ``Runnable``
        # (a ``RunnableCallable`` subclass) and, crucially, is NOT directly
        # callable (it has no ``__call__``). LangGraph invokes it through its
        # ``.invoke(state, config)`` method. A plain function/callable node is
        # invoked directly. Detect which dialect to use so behavior, config and
        # callback propagation are preserved exactly for either shape.
        use_invoke = not callable(node) and hasattr(node, "invoke")

        def wrapped(*args, **kwargs):
            state = args[0] if args else (kwargs.get("state") if "state" in kwargs else None)
            number = count_tool_calls_in_state(state)
            started_at = time.monotonic()
            status = "ok"
            error_type = None
            with agent_scoped(agent_id):
                try:
                    if use_invoke:
                        result = node.invoke(*args, **kwargs)
                    else:
                        result = node(*args, **kwargs)
                except BaseException as exc:  # noqa: BLE001 — re-raised unchanged
                    status = "error"
                    error_type = _sanitized_error_class(exc)
                    ended_at = time.monotonic()
                    _record_tool_round(agent_id, number, started_at, ended_at, status, error_type)
                    raise
            ended_at = time.monotonic()
            _record_tool_round(agent_id, number, started_at, ended_at, status, error_type)
            return result

        wrapped.__name__ = getattr(node, "__name__", node.__class__.__name__)

        # Do NOT set ``__wrapped__`` to the ToolNode ``node`` here. LangGraph
        # coerces runnables with ``inspect.signature(func, follow_wrapped=True)``
        # (see ``RunnableCallable`` / ``coerce_to_runnable``). Setting
        # ``__wrapped__`` to a real ``langgraph.prebuilt.ToolNode`` *instance*
        # makes that signature inspection follow ``__wrapped__`` into the
        # ToolNode and raise ``TypeError: descriptor '__call__' for 'type'
        # objects doesn't apply to a 'ToolNode' object`` during
        # ``StateGraph.add_node`` — before any graph/LLM execution. The
        # ``__name__`` (a string) above is safe; a ``__wrapped__`` reference to
        # an object is not. ToolNode behavior, config/callback propagation and
        # errors are all preserved because ``wrapped`` still delegates to
        # ``node`` (via ``.invoke`` for a Runnable, or ``node(...)`` for a plain
        # callable) unchanged.
        return wrapped

    if tool_node is not None:
        return wrap(tool_node)
    return wrap


def _record_node_event(agent_id, node_name, started_at, ended_at, status, error_type, context_bytes):
    collector = get_current_collector()
    if collector is None:
        return
    try:
        event = NodeContextEvent(
            telemetry_run_id=collector.telemetry_run_id,
            agent_id=agent_id,
            node=node_name,
            started_at=started_at,
            ended_at=ended_at,
            wall_time_ms=round((ended_at - started_at) * 1000.0, 3),
            status=status,
            error_type=error_type,
            context_bytes=context_bytes,
        )
        collector.record_node(event)
    except Exception:  # noqa: BLE001 — never break node execution
        logger.debug("Could not record node event", exc_info=True)


def _record_tool_round(agent_id, number_of_tool_calls, started_at, ended_at, status, error_type):
    collector = get_current_collector()
    if collector is None:
        return
    try:
        event = ToolRoundEvent(
            telemetry_run_id=collector.telemetry_run_id,
            agent_id=agent_id,
            sequence=0,
            number_of_tool_calls=number_of_tool_calls,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=round((ended_at - started_at) * 1000.0, 3),
            status=status,
            error_type=error_type,
        )
        collector.record_tool_round(event)
    except Exception:  # noqa: BLE001
        logger.debug("Could not record tool round", exc_info=True)


def record_prefetch_call(source: str, fn: Callable, *args, **kwargs):
    """Call ``fn(*args, **kwargs)`` while timing it and recording the size.

    Returns ``fn``'s result unchanged. Records a ``PrefetchSourceEvent`` (source,
    timing, byte size, success) — never the raw fetched content. Instrumented
    sources are separate from LangChain tool calls.
    """
    collector = get_current_collector()
    started_at = time.monotonic()
    try:
        result = fn(*args, **kwargs)
    except BaseException as exc:  # noqa: BLE001 — re-raised unchanged
        if collector is not None:
            try:
                collector.record_prefetch(PrefetchSourceEvent(
                    telemetry_run_id=collector.telemetry_run_id,
                    agent_id=get_current_agent_id() or AGENT_UNATTRIBUTED,
                    source=source,
                    started_at=started_at,
                    ended_at=time.monotonic(),
                    duration_ms=round((time.monotonic() - started_at) * 1000.0, 3),
                    result_utf8_bytes=0,
                    success=False,
                    error_type=_sanitized_error_class(exc),
                ))
            except Exception:  # noqa: BLE001
                logger.debug("Could not record prefetch event", exc_info=True)
        raise
    if collector is not None:
        try:
            collector.record_prefetch(PrefetchSourceEvent(
                telemetry_run_id=collector.telemetry_run_id,
                agent_id=get_current_agent_id() or AGENT_UNATTRIBUTED,
                source=source,
                started_at=started_at,
                ended_at=time.monotonic(),
                duration_ms=round((time.monotonic() - started_at) * 1000.0, 3),
                result_utf8_bytes=utf8_byte_size(result),
                success=True,
                error_type=None,
            ))
        except Exception:  # noqa: BLE001
            logger.debug("Could not record prefetch event", exc_info=True)
    return result


def record_structured_attempt(
    agent_name: str,
    *,
    kind: str,
    used_fallback: bool = False,
    error: BaseException | None = None,
    started_at: float | None = None,
    ended_at: float | None = None,
) -> None:
    """Record a structured-output attempt outcome through the current collector.

    ``kind`` is ``"success"``, ``"failure"`` or ``"unsupported"``. Pure
    observability: never alters structured/fallback behavior.
    """
    collector = get_current_collector()
    if collector is None:
        return
    started_at = started_at if started_at is not None else time.monotonic()
    ended_at = ended_at if ended_at is not None else time.monotonic()
    try:
        collector.record_structured(StructuredOutputEvent(
            telemetry_run_id=collector.telemetry_run_id,
            agent_id=get_current_agent_id() or AGENT_UNATTRIBUTED,
            agent_name=agent_name,
            kind=kind,
            used_fallback=used_fallback,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=round((ended_at - started_at) * 1000.0, 3),
            error_type=_sanitized_error_class(error),
        ))
    except Exception:  # noqa: BLE001
        logger.debug("Could not record structured event", exc_info=True)
