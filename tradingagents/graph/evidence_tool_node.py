"""Durable capture at the tool-node boundary (ADR-008).

The run-scoped evidence collector lives in a ``ContextVar`` and therefore survives
LangChain's context-copying tool executor (worker threads), but a ``ContextVar`` is
**not** durable across LangGraph checkpointing: a checkpoint stores graph *state*,
not process-local context. If a checkpoint is taken right after a tool node and
the process restarts before the gate runs, the in-memory collector is gone. The
analyst loop (analyst -> tools -> analyst) means flushing only in a later clear
node is also insufficient: evidence must be written into state at the tool node
boundary itself.

:class:`EvidenceCapturingToolNode` wraps a LangGraph ``ToolNode`` (a
``RunnableCallable``) as a **plain state-node function** with the exact signature
LangGraph injects into — ``(state, config, runtime)`` — and delegates to the inner
node via ``inner.invoke(state, config, runtime=runtime)``. After the tool runs, it
merges the collector's captured evidence into the returned state delta, so the
checkpoint LangGraph takes immediately after the tool node carries the captured
evidence. A resumed run re-seeds the collector from that state (see
:func:`tradingagents.evidence.ingest.use_collector` ``prior_state``).

We do NOT override private ``ToolNode`` methods or bypass ``ToolNode``; the inner
node executes exactly as LangGraph would run it, with the real injected runtime.
The merge never changes tool messages or prose; with no active collector or no
captured data it returns the inner output unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import ToolNode

from tradingagents.evidence.ingest import (
    INGEST_ATTEMPTS_STATE_KEY,
    INGEST_METADATA_STATE_KEY,
    INGEST_RECORDS_STATE_KEY,
    ORIGIN_STATE_KEY,
    get_active_collector,
    merge_into_state,
)

# The ingest state keys this boundary write touches (all JSON-safe).
INGEST_STATE_KEYS = (
    INGEST_RECORDS_STATE_KEY,
    ORIGIN_STATE_KEY,
    INGEST_ATTEMPTS_STATE_KEY,
    INGEST_METADATA_STATE_KEY,
)


def capture_into_state(
    state: Mapping[str, Any] | None,
    *,
    pruned_record_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Merge the active collector's captured evidence into a state delta.

    Returns the JSON-safe ingest state keys (records, attempt envelopes, run
    metadata) that make capture survive a checkpoint, or ``{}`` when no collector
    is active (bare tests / no run) or nothing was captured. Safe to spread into a
    node's returned state update; never raises (a capture failure must never break
    a node).
    """
    try:
        collector = get_active_collector()
    except Exception:  # noqa: BLE001 — capture must never break a node
        return {}
    if collector is None:
        return {}
    delta = collector.state_delta(pruned_record_ids=pruned_record_ids)
    if not _has_ingest(delta):
        return {}
    return merge_into_state(delta, state)


def _has_ingest(delta: Mapping[str, Any]) -> bool:
    return bool(
        delta.get(INGEST_RECORDS_STATE_KEY)
        or delta.get(INGEST_ATTEMPTS_STATE_KEY)
        or delta.get(ORIGIN_STATE_KEY)
    )


class EvidenceCapturingToolNode:
    """Wrap a ``ToolNode`` as a graph state-node function with durable capture.

    The instance is callable with LangGraph's injected ``(state, config, runtime)``
    signature; it invokes the wrapped ``ToolNode`` with the real runtime and then
    merges captured evidence into the returned state update so the tool-boundary
    checkpoint retains it.
    """

    def __init__(self, tool_node: ToolNode, *, name: str = "tools") -> None:
        self._tool_node = tool_node
        self._name = name

    def __call__(self, state: Mapping[str, Any], config: RunnableConfig, runtime: Any):
        output = self._tool_node.invoke(state, config, runtime=runtime)
        captured = capture_into_state(state if isinstance(state, Mapping) else None)
        if not captured:
            return output
        if isinstance(output, Mapping):
            combined = dict(output)
            combined.update(captured)
            return combined
        # A non-dict output (bare message list) cannot carry state keys; the
        # captured evidence is still merged at the gate via the live collector.
        return output

    @property
    def name(self) -> str:
        return self._name

    def __getattr__(self, item: str) -> Any:
        # Delegate tool metadata to the wrapped node so anything that inspects
        # the node keeps working; guard against recursion before init.
        if item.startswith("_") or item in ("_tool_node", "_name"):
            raise AttributeError(item)
        return getattr(self._tool_node, item)


class EvidenceCapturingAnalystNode:
    """Wrap an analyst node so captures made *inside* the analyst are persisted.

    Some analysts (e.g. the Sentiment Analyst) prefetch vendor data directly in
    the analyst node rather than through a ``ToolNode``; a checkpoint taken right
    after that analyst would otherwise lose the captures until a later clear node.
    This wrapper calls the inner analyst ``(state)`` and merges any captured
    evidence into the analyst's returned state delta, so the post-analyst
    checkpoint retains it. A no-op when nothing was captured.
    """

    def __init__(self, analyst_node: Any, *, name: str) -> None:
        self._analyst_node = analyst_node
        self._name = name

    def __call__(self, state: Mapping[str, Any], config: RunnableConfig, runtime: Any):
        output = self._analyst_node(state)
        captured = capture_into_state(state if isinstance(state, Mapping) else None)
        if captured and isinstance(output, Mapping):
            combined = dict(output)
            combined.update(captured)
            return combined
        return output

    @property
    def name(self) -> str:
        return self._name

    def __getattr__(self, item: str) -> Any:
        if item.startswith("_") or item in ("_analyst_node", "_name"):
            raise AttributeError(item)
        return getattr(self._analyst_node, item)
