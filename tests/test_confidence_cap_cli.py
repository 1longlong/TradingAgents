"""ADR-011 Stage 4: the CLI entry point must sanitize a legacy checkpoint BEFORE
any streamed model invocation.

The CLI streams ``graph.graph.stream(...)`` directly (it does not call
``TradingAgentsGraph._run_graph``), so the same fail-closed resume sanitizer must
be wired into the CLI path itself. These tests drive the REAL ``run_analysis``
with a graph double that delegates the confidence sanitizer to the REAL
``TradingAgentsGraph._sanitize_confidence_on_resume`` over a REAL SQLite
checkpointer, and record whether a stream/LLM call happened:

- a legacy over-confident checkpoint is sanitized BEFORE the stream starts;
- a sanitizer failure prevents ANY stream/LLM call (fail closed).

No network, no paid LLM.

Traceability: FR-DQG-006, NFR-AUD-001, INV-1/INV-6.
"""

from __future__ import annotations

import pytest

SYMBOL = "COF"
TARGET = "2026-05-13"


class _NullLive:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeBuffer:
    def __init__(self):
        self.messages = []
        self.tool_calls = []
        self.report_sections = {}
        self.agent_status = {}
        self.selected_analysts = []
        self._processed_message_ids = set()

    def init_for_analysis(self, selected_analysts):
        self.selected_analysts = [a.lower() for a in selected_analysts]

    def add_message(self, kind, content):
        self.messages.append((0.0, kind, content))

    def add_tool_call(self, name, args):
        self.tool_calls.append((0.0, name, args))

    def update_report_section(self, *a):
        pass

    def update_agent_status(self, agent, status):
        self.agent_status[agent] = status


def _degraded_legacy_state():
    from tradingagents.graph.propagation import Propagator

    state = Propagator().create_initial_state(SYMBOL, TARGET, asset_type="stock")
    state.update(
        {
            "data_quality_verdict": "degraded",
            "data_quality_gate_decision": {
                "decision": "degraded",
                "decided_at": "2026-05-13T12:00:00Z",
            },
            "data_quality_context": "[Data Quality Gate] Verdict: degraded.",
            "data_quality_error": None,
            "market_report": "Market view; confidence: 0.95 in the trend.",
        }
    )
    return state


class _CheckpointedCLIGraph:
    """A CLI graph double that uses the REAL resume sanitizer + a SQLite saver."""

    def __init__(self, tmp_path, *, fail_sanitize=False):

        self.events = []
        self.fail_sanitize = fail_sanitize
        self.config = {
            "results_dir": str(tmp_path),
            "data_cache_dir": str(tmp_path / "cache"),
            "checkpoint_enabled": True,
        }
        self.ticker = SYMBOL
        self._resuming = True
        self.selected_analysts = ("market",)
        self.log_states_dict = {}
        self.debug = False
        self.graph = self
        self.propagator = self
        # The CLI reads the prior checkpoint through this method; the real method
        # reads from the checkpointer that ``self.graph`` resolves to.
        self._real_graph = self._make_real_graph(tmp_path)

    def _make_real_graph(self, tmp_path):
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        real = object.__new__(TradingAgentsGraph)
        real.config = self.config
        real.debug = False
        real._resuming = True
        real.graph = self.graph  # same double -> shares update_state/get_state
        return real

    # --- graph interface the CLI uses ---------------------------------------
    def get_graph_args(self, callbacks=None):
        return {"config": {"configurable": {"thread_id": f"{TARGET}/{SYMBOL}"}}}

    def begin_checkpoint(self, *a, **k):
        return f"{TARGET}/{SYMBOL}"

    def end_checkpoint(self):
        pass

    def create_run_state(self, ticker, trade_date, asset_type="stock", portfolio=None,
                         run_id=None, usage_ledger_path=None):
        return _degraded_legacy_state()

    def checkpoint_input(self, state):
        return None  # resume

    def clear_checkpoint_on_success(self, *a, **k):
        pass

    def process_signal(self, text):
        from tradingagents.graph.signal_processing import SignalProcessor
        return SignalProcessor.process_signal(None, text)

    def record_decision(self, *a, **k):
        pass

    def _read_checkpoint_state(self, args):
        snapshot = self.graph.get_state(args.get("config"))
        values = getattr(snapshot, "values", None)
        return dict(values) if isinstance(values, dict) else None

    def _sanitize_confidence_on_resume(self, args, prior_state):
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        if self.fail_sanitize:
            self.events.append(("sanitize", "fail"))
            raise RuntimeError("injected sanitizer failure")
        # Delegate to the REAL production sanitizer (same code the API runs).
        bound = self._real_graph
        bound.graph = self.graph
        bound._resuming = True
        bound.config = self.config
        TradingAgentsGraph._sanitize_confidence_on_resume(bound, args, prior_state)
        values = self.graph.get_state(args.get("config")).values
        self.events.append(("sanitize", values.get("market_report")))

    # Minimal LangGraph surface the CLI touches when resuming.
    def get_state(self, config):
        from types import SimpleNamespace

        if not hasattr(self, "_state_val"):
            raise AssertionError("no checkpoint seeded")
        return SimpleNamespace(values=dict(self._state_val))

    def update_state(self, config, delta):
        if not hasattr(self, "_state_val"):
            self._state_val = {}
        self._state_val.update(delta)

    def seed(self, state):
        self._state_val = dict(state)

    def stream(self, graph_input, **kwargs):
        self.events.append(("stream",))
        yield {"messages": [], "final_trade_decision": "Rating: Buy\n\nBuy COF."}


def _run(tmp_path, monkeypatch, fake):
    import cli.main as m
    from cli.models import AnalystType

    monkeypatch.setattr(m, "TradingAgentsGraph", lambda *a, **k: fake)
    monkeypatch.setattr(m, "message_buffer", _FakeBuffer())
    monkeypatch.setattr(m, "create_layout", lambda: None)
    monkeypatch.setattr(m, "update_display", lambda *a, **k: None)
    monkeypatch.setattr(m, "Live", _NullLive)
    monkeypatch.setattr(m, "get_user_selections", lambda: {
        "ticker": SYMBOL, "analysis_date": TARGET,
        "analysts": [AnalystType.MARKET], "asset_type": "stock",
    })
    monkeypatch.setattr(m, "_build_run_config", lambda selections, checkpoint: {
        "data_cache_dir": str(tmp_path / "cache"),
        "results_dir": str(tmp_path / "results"),
        "checkpoint_enabled": True,
    })
    monkeypatch.setattr(m.typer, "prompt", lambda *a, **k: "N")
    m.run_analysis()


@pytest.mark.unit
def test_cli_legacy_checkpoint_sanitized_before_stream(tmp_path, monkeypatch):
    fake = _CheckpointedCLIGraph(tmp_path)
    fake.seed(_degraded_legacy_state())

    _run(tmp_path, monkeypatch, fake)

    # The sanitizer ran BEFORE the stream and produced an effective report (no raw
    # 0.95) in the checkpoint before any model/stream call.
    kinds = [e[0] for e in fake.events]
    assert "sanitize" in kinds and "stream" in kinds
    assert kinds.index("sanitize") < kinds.index("stream")
    sanitized_report = next(e[1] for e in fake.events if e[0] == "sanitize")
    assert "0.95" not in sanitized_report
    assert "0.6" in sanitized_report
    # Financial text is not resurrected (the only confidence token is capped).
    values = fake.graph.get_state({"configurable": {"thread_id": f"{TARGET}/{SYMBOL}"}}).values
    assert "confidence" not in str(values["market_report"]).replace(
        "confidence: 0.6", ""
    ) or "0.95" not in values["market_report"]


@pytest.mark.unit
def test_cli_sanitizer_failure_prevents_stream(tmp_path, monkeypatch):
    fake = _CheckpointedCLIGraph(tmp_path, fail_sanitize=True)
    fake.seed(_degraded_legacy_state())

    with pytest.raises(RuntimeError, match="injected sanitizer failure"):
        _run(tmp_path, monkeypatch, fake)

    # Fail closed: no stream (hence no model call) ever happened.
    assert ("sanitize", "fail") in fake.events
    assert not any(e[0] == "stream" for e in fake.events)
