"""Run one analysis through the existing LangGraph pipeline."""

from __future__ import annotations

import time

from cli.stats_handler import StatsCallbackHandler
from tradingagents.agents.utils.rating import is_review
from tradingagents.graph.trading_graph import TradingAgentsGraph

from .projector import StreamProjector


class GraphRunner:
    """Real runner used by the coordinator unless a test injects a double."""

    def run(self, request, emit, cancel_event) -> None:
        config = request["config"]
        ticker = request["ticker"]
        trade_date = request["trade_date"]
        asset_type = request.get("asset_type", "stock")
        analysts = request["analysts"]
        portfolio = request.get("portfolio")

        emit(
            {
                "type": "run.preparing",
                "payload": {"ticker": ticker, "trade_date": trade_date},
            }
        )

        stats = StatsCallbackHandler()
        graph = TradingAgentsGraph(
            selected_analysts=analysts,
            config=config,
            debug=False,
            callbacks=[stats],
        )
        started = time.perf_counter()
        try:
            init_state = graph.create_run_state(ticker, trade_date, asset_type, portfolio)
            args = graph.propagator.get_graph_args(callbacks=[stats])
            thread_id = graph.begin_checkpoint(ticker, trade_date, asset_type, portfolio)
            if thread_id is not None:
                args.setdefault("config", {}).setdefault("configurable", {})[
                    "thread_id"
                ] = thread_id

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

            projector = StreamProjector()
            trace = []
            for chunk in graph.graph.stream(
                graph.checkpoint_input(init_state), **args
            ):
                if cancel_event.is_set():
                    return
                trace.append(chunk)
                for event in projector.project(chunk):
                    emit(event)

            if cancel_event.is_set():
                return

            final_state: dict = {}
            for chunk in trace:
                final_state.update(chunk)

            graph.record_decision(ticker, trade_date, final_state)
            graph.clear_checkpoint_on_success(ticker, trade_date, asset_type, portfolio)
            signal = graph.process_signal(final_state.get("final_trade_decision", ""))
            emit(
                {
                    "type": "run.completed",
                    "payload": {
                        "signal": signal,
                        "review": is_review(signal),
                        "wall_times": {"total": round(time.perf_counter() - started, 3)},
                        "final_state": final_state,
                    },
                }
            )
        except Exception:
            emit(
                {
                    "type": "run.failed",
                    "payload": {
                        "category": "upstream",
                        "message": "analysis failed; check the server log",
                    },
                }
            )
        finally:
            graph.end_checkpoint()
