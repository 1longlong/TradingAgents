import threading
from typing import Any

from tradingagents.observability import (
    ObservabilityCallbackHandler,
    RunMetricsCollector,
)


class StatsCallbackHandler(ObservabilityCallbackHandler):
    """Callback handler that tracks LLM calls, tool calls, and token usage.

    Subclasses :class:`ObservabilityCallbackHandler` so the same handler instance
    both records full events into a :class:`RunMetricsCollector` and exposes the
    coarse counters the CLI summary (and any existing consumers) relies on:

    ``llm_calls``, ``tool_calls``, ``tokens_in``, ``tokens_out``, ``get_stats()``.

    Every logical LLM/tool invocation is counted exactly once by ``run_id`` even
    when both ``on_llm_start`` and ``on_chat_model_start`` fire for a single call
    (the observability handler deduplicates the underlying events; the counters
    here deduplicate on the same ``run_id``).
    """

    def __init__(self, collector: RunMetricsCollector | None = None) -> None:
        # Always back the handler with a collector so events are recorded even
        # when the caller does not supply one (the CLI does not).
        if collector is None:
            collector = RunMetricsCollector()
        super().__init__(collector=collector)
        self._lock = threading.Lock()
        self.llm_calls = 0
        self.tool_calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self._seen_llm_starts: set[str] = set()
        self._seen_tool_starts: set[str] = set()

    @property
    def collector(self) -> RunMetricsCollector:
        """The underlying observability collector for this handler."""
        return self._collector

    def on_llm_start(self, serialized, prompts, *, run_id=None, **kwargs) -> None:
        """Record the observability event and bump the coarse LLM call counter."""
        super().on_llm_start(serialized, prompts, run_id=run_id, **kwargs)
        if run_id is not None and str(run_id) not in self._seen_llm_starts:
            self._seen_llm_starts.add(str(run_id))
            with self._lock:
                self.llm_calls += 1

    def on_chat_model_start(
        self, serialized, messages, *, run_id=None, **kwargs
    ) -> None:
        """Record the observability event and bump the coarse LLM call counter."""
        super().on_chat_model_start(serialized, messages, run_id=run_id, **kwargs)
        if run_id is not None and str(run_id) not in self._seen_llm_starts:
            self._seen_llm_starts.add(str(run_id))
            with self._lock:
                self.llm_calls += 1

    def on_llm_end(self, response, *, run_id=None, **kwargs) -> None:
        """Record the observability event and refresh token summary."""
        super().on_llm_end(response, run_id=run_id, **kwargs)
        with self._lock:
            self.tokens_in = self._collector.reported_input_tokens_sum
            self.tokens_out = self._collector.reported_output_tokens_sum

    def on_tool_start(
        self, serialized, input_str, *, run_id=None, inputs=None, **kwargs
    ) -> None:
        """Record the observability event and bump the coarse tool counter."""
        super().on_tool_start(
            serialized, input_str, run_id=run_id, inputs=inputs, **kwargs
        )
        if run_id is not None and str(run_id) not in self._seen_tool_starts:
            self._seen_tool_starts.add(str(run_id))
            with self._lock:
                self.tool_calls += 1

    def get_stats(self) -> dict[str, Any]:
        """Return current statistics (back-compat shape + observability summary).

        The keys ``llm_calls``, ``tool_calls``, ``tokens_in``, ``tokens_out`` are
        unchanged for existing consumers. Additional keys expose the compact
        per-agent observability summary, usage/attribution coverage, structured
        fallback, duplicate-tool and telemetry-path info so the CLI footer and
        post-run summary can render the Phase 2 observability metadata.
        """
        with self._lock:
            summary = self._observability_summary()
        return {
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            **summary,
        }

    def _observability_summary(self) -> dict[str, Any]:
        """Build the lightweight observability summary from the collector.

        Reads only the collector's stored aggregates and event lists (counts,
        sizes, ids — never raw content). This is independent of the full
        ``build_telemetry`` payload and is cheap enough for footer refreshes.
        """
        collector = self._collector
        if collector is None:
            return {}

        # Per-agent aggregates (counts only).
        agents: dict[str, dict[str, Any]] = {}
        unattributed = "unattributed"

        def agg(agent_id: str) -> dict[str, Any]:
            return agents.setdefault(agent_id, {
                "llm_calls": 0,
                "tool_calls": 0,
                "tool_rounds": 0,
                "prefetch_calls": 0,
                "structured_attempts": 0,
                "structured_fallbacks": 0,
                "structured_unsupported": 0,
                "node_invocations": 0,
            })

        for ev in collector.llm_calls:
            agg(ev.agent_id)["llm_calls"] += 1
        for ev in collector.tool_calls:
            agg(ev.agent_id)["tool_calls"] += 1
        for ev in collector.tool_rounds:
            agg(ev.agent_id)["tool_rounds"] += 1
        for ev in collector.prefetch_events:
            agg(ev.agent_id)["prefetch_calls"] += 1
        for ev in collector.structured_events:
            a = agg(ev.agent_id)
            a["structured_attempts"] += 1
            if ev.used_fallback:
                a["structured_fallbacks"] += 1
            if ev.kind == "unsupported":
                a["structured_unsupported"] += 1
        for ev in collector.node_events:
            agg(ev.agent_id)["node_invocations"] += 1

        unattributed_llm = agents.get(unattributed, {}).get("llm_calls", 0)
        unattributed_tool = agents.get(unattributed, {}).get("tool_calls", 0)

        with_usage = collector.llm_calls_with_provider_usage
        without_usage = collector.llm_calls_without_provider_usage
        total_llm = collector.llm_calls_count

        try:
            telemetry_path = collector.telemetry_path
        except Exception:  # noqa: BLE001
            telemetry_path = None

        return {
            "tool_rounds": collector.tool_rounds_count,
            "duplicate_tool_calls": collector.duplicate_tool_call_count,
            "structured_attempts": len(collector.structured_events),
            "structured_failures": _count_kind(collector.structured_events, "failure"),
            "structured_fallbacks": _count_fallback(collector.structured_events),
            "structured_unsupported": _count_kind(collector.structured_events, "unsupported"),
            "usage_complete": bool(without_usage == 0 and total_llm > 0 and with_usage == total_llm),
            "calls_with_provider_usage": with_usage,
            "calls_without_provider_usage": without_usage,
            "unattributed_llm": unattributed_llm,
            "unattributed_tool": unattributed_tool,
            "agents": agents,
            "telemetry_path": telemetry_path,
        }


def _count_kind(events, kind: str) -> int:
    """Count structured events matching ``kind``."""
    return sum(1 for e in events if getattr(e, "kind", None) == kind)


def _count_fallback(events) -> int:
    """Count structured events that triggered a fallback."""
    return sum(1 for e in events if getattr(e, "used_fallback", False))
