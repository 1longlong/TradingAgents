"""Real graph adapter: ADR-001/007, REQ-WEB-002/005, INV-WEB-001/010."""

from __future__ import annotations

import time

from cli.stats_handler import StatsCallbackHandler
from tradingagents.agents.utils.rating import is_review
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents_web.errors import run_failure

from .projector import StreamProjector


class LiveStats(StatsCallbackHandler):
    """Publish real callback counters, including during provider waits (REQ-WEB-002)."""

    def __init__(self, emit, started):
        super().__init__()
        self.emit = emit
        self.started = started

    def publish(self):
        self.emit(
            {
                "type": "stats",
                "payload": {
                    **self.get_stats(),
                    "elapsed": round(time.perf_counter() - self.started, 3),
                },
            }
        )

    def on_chat_model_start(self, *args, **kwargs):
        super().on_chat_model_start(*args, **kwargs)
        self.publish()

    def on_llm_start(self, *args, **kwargs):
        super().on_llm_start(*args, **kwargs)
        self.publish()

    def on_llm_end(self, *args, **kwargs):
        super().on_llm_end(*args, **kwargs)
        self.publish()

    def on_tool_start(self, *args, **kwargs):
        super().on_tool_start(*args, **kwargs)
        self.publish()


class GraphRunner:
    """Real runner; only provider/data boundaries are replaced in integration tests."""

    def run(self, request, emit, cancel_event) -> None:
        config = request["config"]
        ticker, trade_date = request["ticker"], request["trade_date"]
        asset_type = request.get("asset_type", "stock")
        analysts, portfolio = request["analysts"], request.get("portfolio")
        started = time.perf_counter()
        graph = None
        outcome = None
        phase = "configuration"
        stats = LiveStats(emit, started)
        emit({"type": "run.preparing", "payload": {"phase": phase}})
        try:
            if cancel_event.is_set():
                return
            graph = TradingAgentsGraph(
                selected_analysts=analysts,
                config=config,
                debug=False,
                callbacks=[stats],
            )
            phase = "context"
            emit({"type": "run.phase", "payload": {"phase": phase}})
            init_state = graph.create_run_state(ticker, trade_date, asset_type, portfolio)
            if cancel_event.is_set():
                return
            args = graph.propagator.get_graph_args(callbacks=[stats])
            thread_id = graph.begin_checkpoint(ticker, trade_date, asset_type, portfolio)
            if thread_id is not None:
                args.setdefault("config", {}).setdefault("configurable", {})["thread_id"] = (
                    thread_id
                )
            emit(
                {
                    "type": "run.resumed" if getattr(graph, "_resuming", False) else "run.started",
                    "payload": {
                        "ticker": ticker,
                        "trade_date": trade_date,
                        "asset_type": asset_type,
                        "analysts": analysts,
                        "checkpoint_enabled": bool(config.get("checkpoint_enabled")),
                    },
                }
            )
            phase = "analysis"
            projector = StreamProjector(analysts)
            for event in projector.project(init_state):
                emit(event)
            final_state = {}
            for chunk in graph.graph.stream(graph.checkpoint_input(init_state), **args):
                if cancel_event.is_set():
                    return
                final_state.update(chunk)
                for event in projector.project(chunk):
                    emit(event)
                stats.publish()
            if cancel_event.is_set():
                return
            phase = "decision"
            graph.record_decision(ticker, trade_date, final_state)
            graph.clear_checkpoint_on_success(ticker, trade_date, asset_type, portfolio)
            signal = graph.process_signal(final_state.get("final_trade_decision", ""))
            outcome = {
                "type": "run.completed",
                "payload": {
                    "signal": signal,
                    "review": is_review(signal),
                    "wall_times": {"total": round(time.perf_counter() - started, 3)},
                    "final_state": final_state,
                },
            }
        except Exception as exc:
            outcome = {"type": "run.failed", "payload": run_failure(exc, phase)}
        finally:
            if graph is not None:
                try:
                    graph.end_checkpoint()
                except Exception as exc:
                    outcome = {"type": "run.failed", "payload": run_failure(exc, "checkpoint")}
            # Publish a terminal event only after checkpoint cleanup has finished.
            if outcome is not None:
                emit(outcome)
