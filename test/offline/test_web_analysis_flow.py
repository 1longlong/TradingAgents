"""Analysis-path regressions: REQ-WEB-002/005/007/009/013, INV-WEB-001/003/009.

ADR-001/007: exercise the real Web runner and core graph with offline model/data
boundaries, and isolate Web artifacts from the legacy CLI tree.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from test.offline.web_fixture_app import (
    FakeGraphRunner,
    build_fixture_tree,
    make_run_client,
    wait_terminal,
)
from tradingagents_web.runtime.coordinator import RunCoordinator, RunRecord
from tradingagents_web.runtime.event_buffer import EventBuffer


@pytest.fixture(autouse=True)
def clean_overrides(monkeypatch):
    from tradingagents.default_config import _ENV_OVERRIDES

    monkeypatch.setattr("tradingagents_web.api.config.load_last_run", lambda: {})
    for name in _ENV_OVERRIDES:
        monkeypatch.delenv(name, raising=False)


def body(**changes):
    return {
        "client_request_id": uuid.uuid4().hex,
        "ticker": "NVDA",
        "trade_date": "2026-11-01",
        "analysts": ["market"],
        **changes,
    }


def test_server_defaults_and_other_locks_survive_omitted_model_inputs(tmp_path, monkeypatch):
    for name, value in {
        "TRADINGAGENTS_LLM_PROVIDER": "openai_compatible",
        "TRADINGAGENTS_LLM_BACKEND_URL": "http://127.0.0.1:1234/v1",
        "TRADINGAGENTS_QUICK_THINK_LLM": "offline-model",
        "TRADINGAGENTS_DEEP_THINK_LLM": "offline-model",
        "TRADINGAGENTS_OUTPUT_LANGUAGE": "Chinese",
        "TRADINGAGENTS_CHECKPOINT_ENABLED": "true",
        "TRADINGAGENTS_OPENAI_REASONING_EFFORT": "high",
        "TRADINGAGENTS_MAX_DEBATE_ROUNDS": "4",
    }.items():
        monkeypatch.setenv(name, value)
    runner = FakeGraphRunner()
    client = make_run_client(build_fixture_tree(tmp_path), runner_factory=runner)
    started = client.post(
        "/api/runs",
        json=body(
            backend_url=None,
            checkpoint=False,
            research_depth=4,
        ),
    )
    assert started.status_code == 201
    snapshot = wait_terminal(client, started.json()["run_id"])
    config = runner.received_request["config"]
    assert config["backend_url"] == "http://127.0.0.1:1234/v1"
    assert config["openai_reasoning_effort"] == "high"
    assert config["output_language"] == "Chinese"
    assert snapshot["checkpoint_enabled"] is True
    assert snapshot["llm_provider"] == "openai_compatible"
    assert snapshot["quick_think_llm"] == "offline-model"
    assert snapshot["deep_think_llm"] == "offline-model"
    assert snapshot["research_depth"] == 4
    projected = client.get("/api/config").json()
    assert projected["defaults"]["llm_provider"] == "openai_compatible"
    assert projected["backend_url_configured"] is True
    assert "1234" not in str(projected)


def test_completed_snapshot_contains_report_messages_and_counters(tmp_path):
    client = make_run_client(build_fixture_tree(tmp_path), runner_factory=FakeGraphRunner())
    response = client.post("/api/runs", json=body())
    snapshot = wait_terminal(client, response.json()["run_id"])
    assert snapshot["sections"]["market_report"] == "# Market\n\nMKT"
    assert snapshot["messages"][0]["content"] == "working"
    assert snapshot["stats"]["llm_calls"] == 1
    assert snapshot["agents"]["Market Analyst"] == "in_progress"
    assert snapshot["artifact_id"]


def test_expired_event_cursor_returns_full_snapshot():
    coordinator = RunCoordinator(None, None)
    record = RunRecord("r_test", {})
    record.buffer = EventBuffer(max_events=2)
    coordinator._records[record.run_id] = record
    for event in [
        {"type": "run.resumed", "payload": {}},
        {"type": "report.section", "payload": {"section": "market_report", "content": "report"}},
        {"type": "message", "payload": {"content": "message"}},
        {"type": "run.completed", "payload": {"signal": "Buy"}},
    ]:
        coordinator._emit(record, event)

    async def collect():
        return [event async for event in coordinator.stream(record.run_id, 0)]

    events = asyncio.run(collect())
    assert len(events) == 1
    assert events[0]["type"] == "snapshot"
    assert events[0]["payload"]["sections"] == {"market_report": "report"}
    assert events[0]["payload"]["status"] == "completed"
    assert events[0]["seq"] == record.last_seq


def test_artifact_initialization_failure_releases_slot(tmp_path, monkeypatch, caplog):
    import tradingagents_web.runtime.coordinator as module

    original = module.RunArtifactWriter

    def fail(*args, **kwargs):
        raise PermissionError("private-path-and-key")

    monkeypatch.setattr(module, "RunArtifactWriter", fail)
    client = make_run_client(build_fixture_tree(tmp_path), runner_factory=FakeGraphRunner())
    response = client.post("/api/runs", json=body())
    snapshot = wait_terminal(client, response.json()["run_id"])
    assert snapshot["status"] == "failed"
    assert snapshot["error"]["category"] == "storage"
    assert "private-path" not in str(snapshot)
    assert snapshot["error"]["correlation_id"] in caplog.text
    assert client.get("/api/runs/active").json()["run_id"] is None
    monkeypatch.setattr(module, "RunArtifactWriter", original)
    again = client.post("/api/runs", json=body())
    assert again.status_code == 201
    assert wait_terminal(client, again.json()["run_id"])["status"] == "completed"


def test_repeated_analysis_keeps_each_run_and_legacy_artifacts(tmp_path):
    tree = build_fixture_tree(tmp_path)
    legacy = {
        str(p.relative_to(tree.run_dir)): p.read_bytes()
        for p in tree.run_dir.rglob("*")
        if p.is_file()
    }
    runner = FakeGraphRunner(
        events=[
            {
                "type": "report.section",
                "payload": {"section": "final_trade_decision", "content": "**Rating**: Buy"},
            },
            {"type": "run.completed", "payload": {"signal": "Buy"}},
        ]
    )
    client = make_run_client(tree, runner_factory=runner)
    first = client.post("/api/runs", json=body()).json()
    complete = wait_terminal(client, first["run_id"])
    runner.events = [
        {
            "type": "report.section",
            "payload": {"section": "market_report", "content": "second run only"},
        },
        {"type": "run.failed", "payload": {"category": "upstream", "message": "failed"}},
    ]
    second = client.post("/api/runs", json=body()).json()
    failed = wait_terminal(client, second["run_id"])
    assert complete["artifact_id"] != failed["artifact_id"]
    detail = client.get(f"/api/history/{failed['artifact_id']}").json()
    assert detail["status"] == "failed"
    assert detail["sections"] == {"market_report": "second run only"}
    assert client.get(f"/api/history/{complete['artifact_id']}").json()["status"] == "completed"
    assert legacy == {
        str(p.relative_to(tree.run_dir)): p.read_bytes()
        for p in tree.run_dir.rglob("*")
        if p.is_file()
    }


def test_resumed_run_is_running(tmp_path):
    runner = FakeGraphRunner(events=[{"type": "run.resumed", "payload": {}}], block_after=0)
    client = make_run_client(build_fixture_tree(tmp_path), runner_factory=runner)
    response = client.post("/api/runs", json=body()).json()
    assert runner.started.wait(2)
    assert client.get(f"/api/runs/{response['run_id']}").json()["status"] == "running"
    client.post(f"/api/runs/{response['run_id']}/cancel")
    assert wait_terminal(client, response["run_id"])["status"] == "cancelled"


@pytest.mark.parametrize(
    "debate_policy",
    [None, {"enabled": False, "max_debate_rounds": 2, "no_new_evidence_patience": 2}],
)
def test_real_graph_runner_through_core_graph_to_report(tmp_path, monkeypatch, debate_policy):
    """Use real graph/state/memory/report code; replace only provider/data boundaries."""
    import pandas as pd
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    import tradingagents.dataflows.market_data_validator as validator
    import tradingagents.graph.trading_graph as graph_module
    from tradingagents.agents.utils.memory import TradingMemoryLog

    class OfflineModel(FakeListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

        def with_structured_output(self, schema, **kwargs):
            raise NotImplementedError("offline free-text model")

    def client_factory(**kwargs):
        model = OfflineModel(
            responses=["**Rating**: Buy\n\nOffline evidence for NVDA."],
            callbacks=kwargs.get("callbacks"),
        )
        return SimpleNamespace(get_llm=lambda: model)

    monkeypatch.setattr(graph_module, "create_llm_client", client_factory)
    # The merged core verifies market data independently of analyst prose.
    # Replace that I/O boundary too; keep the real gate and its restrictions.
    dates = pd.bdate_range("2025-10-01", "2026-10-30")
    closes = [100 + i / 10 for i in range(len(dates))]
    frame = pd.DataFrame(
        {
            "Date": dates,
            "Open": closes,
            "High": [price + 1 for price in closes],
            "Low": [price - 1 for price in closes],
            "Close": closes,
            "Volume": [1_000_000] * len(dates),
        }
    )
    monkeypatch.setattr(validator, "load_ohlcv", lambda *args, **kwargs: frame.copy())
    monkeypatch.setattr(
        graph_module,
        "resolve_instrument_identity",
        lambda ticker: {"name": "Offline NVIDIA", "currency": "USD"},
    )
    tree = build_fixture_tree(tmp_path)
    client = make_run_client(tree)  # No FakeGraphRunner: use actual GraphRunner.
    response = client.post(
        "/api/runs",
        json=body(
            checkpoint=True,
            **(
                {"debate_termination": debate_policy, "max_risk_discuss_rounds": 1}
                if debate_policy
                else {}
            ),
        ),
    )
    assert response.status_code == 201, response.text
    snapshot = wait_terminal(client, response.json()["run_id"], timeout=10)
    assert snapshot["status"] == "completed", snapshot
    assert snapshot["signal"] == "Buy"
    assert "Offline evidence" in snapshot["sections"]["final_trade_decision"]
    assert snapshot["stats"]["llm_calls"] > 0
    assert snapshot["stats"]["reports_completed"] == snapshot["stats"]["reports_total"] == 4
    assert snapshot["wall_times"]["Market Analyst"] >= 0
    assert snapshot["stats"]["agents_completed"] == snapshot["stats"]["agents_total"] == 9
    for role in [
        "Bull Researcher",
        "Bear Researcher",
        "Research Manager",
        "Aggressive Analyst",
        "Conservative Analyst",
        "Neutral Analyst",
        "Portfolio Manager",
    ]:
        assert snapshot["agents"][role] == "completed"
    if debate_policy:
        assert snapshot["debate_termination"]["enabled"] is False
        assert (
            snapshot["debate_termination"]["max_debate_rounds"] == snapshot["research_depth"] == 2
        )
        assert snapshot["debate_termination"]["no_new_evidence_patience"] == 2
        assert snapshot["max_risk_discuss_rounds"] == 1
    assert all(status == "completed" for status in snapshot["agents"].values())
    history = client.get(f"/api/history/{snapshot['artifact_id']}").json()
    assert history["status"] == "completed"
    download = client.get(f"/api/history/{snapshot['artifact_id']}/download?kind=complete")
    assert download.status_code == 200
    assert "Offline evidence" in download.text
    entries = TradingMemoryLog({"memory_log_path": str(tree.memory_log_path)}).load_entries()
    assert any(entry["ticker"] == "NVDA" and entry["rating"] == "Buy" for entry in entries)


def test_real_runner_failure_is_correlated_and_redacted(tmp_path, monkeypatch, caplog):
    import tradingagents.graph.trading_graph as graph_module

    secret = "test-secret-do-not-expose-12345678"
    monkeypatch.setenv("OPENAI_API_KEY", secret)

    def fail(**kwargs):
        raise ValueError(f"invalid provider {secret}")

    monkeypatch.setattr(graph_module, "create_llm_client", fail)
    client = make_run_client(build_fixture_tree(tmp_path))
    response = client.post("/api/runs", json=body())
    snapshot = wait_terminal(client, response.json()["run_id"])
    assert snapshot["status"] == "failed"
    assert snapshot["error"]["category"] == "config"
    assert snapshot["error"]["correlation_id"] in caplog.text
    assert secret not in caplog.text
    assert secret not in str(snapshot)


def test_provider_projection_includes_regions_and_keyless_local_endpoints(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_COMPATIBLE_API_KEY", raising=False)
    client = make_run_client(build_fixture_tree(tmp_path), runner_factory=FakeGraphRunner())
    config = client.get("/api/config").json()
    assert {"qwen-cn", "glm-cn", "minimax-cn"} <= {item["key"] for item in config["providers"]}
    assert config["key_status"]["openai_compatible"] == "not_required"
    models = client.get("/api/config/models?provider=azure&mode=quick")
    assert models.status_code == 200
    assert models.json()["models"] == [{"value": "custom", "label": "Custom model ID"}]


def test_real_market_tool_rate_limit_degrades_without_llm_failure(tmp_path, monkeypatch, caplog):
    """REQ-WEB-002/005, INV-WEB-003/010: preserve the release unavailable-data path."""
    import pandas as pd
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage
    from yfinance.exceptions import YFRateLimitError

    import tradingagents.dataflows.market_data_validator as validator
    import tradingagents.dataflows.retry_session as retry_module
    import tradingagents.dataflows.y_finance as yahoo_module
    import tradingagents.graph.trading_graph as graph_module

    class ToolCallingModel(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

        def with_structured_output(self, schema, **kwargs):
            raise NotImplementedError("offline tool-call model")

    model = ToolCallingModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_stock_data",
                        "args": {
                            "symbol": "NVDA",
                            "start_date": "2026-10-01",
                            "end_date": "2026-11-01",
                        },
                        "id": "call_market_data",
                        "type": "tool_call",
                    }
                ],
            ),
            *[AIMessage(content="**Rating**: Buy\nOffline analysis with unavailable market data.")
              for _ in range(30)],
        ],
    )

    def client_factory(**kwargs):
        model.callbacks = kwargs.get("callbacks")
        return SimpleNamespace(get_llm=lambda: model)

    def limited_history(**kwargs):
        raise YFRateLimitError()

    monkeypatch.setattr(graph_module, "create_llm_client", client_factory)
    monkeypatch.setattr(
        graph_module, "resolve_instrument_identity", lambda ticker: {"name": "Offline NVIDIA"}
    )
    monkeypatch.setattr(
        yahoo_module.yf, "Ticker", lambda ticker, **kwargs: SimpleNamespace(history=limited_history)
    )
    # Keep the release router/retry behavior, replacing only transport, sleeps
    # and the independent Gate's data I/O. Missing evidence must still block Buy.
    monkeypatch.setattr(yahoo_module, "yf_retry", lambda callback: callback())
    monkeypatch.setattr(retry_module.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(validator, "load_ohlcv", lambda *args, **kwargs: pd.DataFrame())
    tree = build_fixture_tree(tmp_path)
    client = make_run_client(tree)  # Actual runner, core graph, market tool and vendor router.
    response = client.post(
        "/api/runs",
        json=body(
            checkpoint=True,
            llm_provider="deepseek",
            quick_think_llm="deepseek-flash",
            deep_think_llm="deepseek-flash",
        ),
    )
    assert response.status_code == 201, response.text
    snapshot = wait_terminal(client, response.json()["run_id"])
    assert snapshot["status"] == "completed", snapshot
    assert snapshot["error"] is None
    assert snapshot["signal"] == "Hold"
    tools = [message for message in snapshot["messages"] if message["type"] == "Data"]
    assert any("DATA_UNAVAILABLE" in message["content"] for message in tools)
    assert any("get_stock_data" in message["content"] for message in tools)
    assert "failed for get_stock_data" in caplog.text
    assert "final_trade_decision" in snapshot["sections"]
    from tradingagents.agents.utils.memory import TradingMemoryLog

    entries = TradingMemoryLog({"memory_log_path": str(tree.memory_log_path)}).load_entries()
    assert any(entry["ticker"] == "NVDA" and entry["rating"] == "Hold" for entry in entries)
    # A successful completion clears the checkpoint without presenting an LLM
    # authentication failure or turning missing evidence into a Buy decision.
    import sqlite3

    databases = list((tree.data_cache_dir / "checkpoints").glob("*.db"))
    assert databases
    for path in databases:
        with sqlite3.connect(path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM writes").fetchone()[0] == 0


@pytest.mark.parametrize(
    "kind,category,retryable",
    [
        ("throttled", "market_data_unavailable", True),
        ("no_data", "market_data_unavailable", False),
        ("missing_credentials", "market_data_config", False),
        ("internal", "internal", None),
    ],
)
def test_failure_categories_do_not_expose_exception_details(kind, category, retryable, monkeypatch):
    """INV-WEB-003: typed data failures are safe, distinct from LLM authentication."""
    from tradingagents.dataflows.errors import (
        NoMarketDataError,
        VendorNotConfiguredError,
        VendorRateLimitError,
    )
    from tradingagents_web.errors import run_failure

    secret = "temporary-provider-secret-12345678"
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)
    errors = {
        "throttled": VendorRateLimitError(secret),
        "no_data": NoMarketDataError("NVDA", detail=secret),
        "missing_credentials": VendorNotConfiguredError(secret),
        "internal": RuntimeError(secret),
    }
    try:
        raise errors[kind]
    except Exception as exc:
        payload = run_failure(exc, "analysis")
    assert payload["category"] == category
    assert payload.get("retryable") is retryable
    assert secret not in str(payload)
    assert "contacting a provider" not in payload["message"]


@pytest.mark.parametrize("mode", ["complete", "stream_failure", "cancel", "resume_failure"])
def test_stream_runner_preserves_merged_core_contexts(tmp_path, monkeypatch, mode):
    """Core ADR-008/009/011 + INV-1/6/7, INV-WEB-001/010: no bypass on Web stream."""
    import threading

    from tradingagents.debate.usage_capture import get_active_capture
    from tradingagents.evidence.ingest import get_active_collector
    from tradingagents.graph.signal_processing import SignalProcessor
    from tradingagents.graph.trading_graph import TradingAgentsGraph as CoreGraph
    from tradingagents_web.runtime import graph_runner

    trace = []
    cancel = threading.Event()

    class BoundariesGraph:
        _usage_run_identity = CoreGraph._usage_run_identity
        _open_usage_ledger = CoreGraph._open_usage_ledger
        _attach_whole_run_usage = staticmethod(CoreGraph._attach_whole_run_usage)
        process_signal = CoreGraph.process_signal

        def __init__(self, **kwargs):
            self.config = kwargs["config"]
            self._resuming = mode == "resume_failure"
            self.signal_processor = SignalProcessor()
            self.propagator = SimpleNamespace(get_graph_args=lambda **kwargs: {})
            self.graph = SimpleNamespace(stream=self.stream)

        def begin_checkpoint(self, *args):
            trace.append("begin_checkpoint")
            return "checkpoint-thread"

        def _read_checkpoint_state(self, args):
            return {"run_id": "old-run", "data_quality_verdict": "degraded"}

        def _sanitize_confidence_on_resume(self, args, prior):
            trace.append("sanitize")
            raise ValueError("resume sanitizer refused unsafe state")

        def create_run_state(self, *args, **kwargs):
            assert kwargs["run_id"]
            assert kwargs["usage_ledger_path"]
            return {"messages": []}

        def checkpoint_input(self, state):
            return state

        def stream(self, state, **kwargs):
            trace.append("stream")
            assert get_active_collector() is not None
            capture = get_active_capture()
            assert capture is not None and capture.ledger is not None
            if mode == "stream_failure":
                raise RuntimeError("offline stream failure")
            if mode == "cancel":
                cancel.set()
            yield {
                "final_trade_decision": "**Rating**: Buy",
                "data_quality_verdict": "blocked",
                "data_quality_gate_decision": {"decision": "blocked"},
            }

        def record_decision(self, ticker, trade_date, state):
            assert "whole_run_usage" in state
            trace.append("decision")

        def clear_checkpoint_on_success(self, *args):
            trace.append("clear_checkpoint")

        def end_checkpoint(self):
            trace.append("end_checkpoint")

    monkeypatch.setattr(graph_runner, "TradingAgentsGraph", BoundariesGraph)
    events = []
    graph_runner.GraphRunner().run(
        {
            "config": {"results_dir": str(tmp_path), "checkpoint_enabled": True},
            "ticker": "NVDA",
            "trade_date": "2026-11-01",
            "analysts": ["market"],
        },
        events.append,
        cancel,
    )
    assert trace[-1] == "end_checkpoint"
    assert get_active_capture() is None
    assert get_active_collector() is None
    terminals = [event for event in events if event["type"] in {"run.completed", "run.failed"}]
    if mode == "complete":
        assert terminals[-1]["type"] == "run.completed"
        # A directional text header cannot override the trusted blocked state.
        assert terminals[-1]["payload"]["signal"] == "Hold"
        assert "decision" in trace and "clear_checkpoint" in trace
    else:
        assert "decision" not in trace and "clear_checkpoint" not in trace
        if mode == "cancel":
            assert terminals == []  # Coordinator owns the eventual cancelled event.
        else:
            assert terminals[-1]["type"] == "run.failed"
        if mode == "resume_failure":
            assert "sanitize" in trace and "stream" not in trace


@pytest.mark.parametrize("provider", ["deepseek", "openai"])
def test_explicit_analysis_models_override_environment_defaults_without_cross_provider_leak(
    tmp_path, monkeypatch, provider
):
    """REQ-WEB-001/013, INV-WEB-003: model defaults are editable; endpoint ownership stays scoped."""
    from copy import deepcopy

    from tradingagents.default_config import DEFAULT_CONFIG

    before = deepcopy(DEFAULT_CONFIG)
    for name, value in {
        "TRADINGAGENTS_LLM_PROVIDER": "deepseek",
        "TRADINGAGENTS_QUICK_THINK_LLM": "deepseek-flash",
        "TRADINGAGENTS_DEEP_THINK_LLM": "deepseek-flash",
        "TRADINGAGENTS_LLM_BACKEND_URL": "https://default-provider.test/v1",
        "TRADINGAGENTS_OPENAI_REASONING_EFFORT": "high",
        "TRADINGAGENTS_OUTPUT_LANGUAGE": "Chinese",
        "TRADINGAGENTS_CHECKPOINT_ENABLED": "true",
        "TRADINGAGENTS_MAX_DEBATE_ROUNDS": "4",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "temporary-defaults-test-secret")
    runner = FakeGraphRunner()
    client = make_run_client(build_fixture_tree(tmp_path), runner_factory=runner)
    projected = client.get("/api/config").json()
    for field in ("llm_provider", "quick_think_llm", "deep_think_llm"):
        assert projected["env_locks"][field] is False
        assert projected["env_defaults"][field] is True
    assert projected["defaults"]["llm_provider"] == "deepseek"
    assert projected["env_locks"]["max_debate_rounds"] is True
    assert "temporary-defaults-test-secret" not in str(projected)
    assert "default-provider.test" not in str(projected)
    started = client.post("/api/runs", json=body(
        llm_provider=provider, quick_think_llm="chosen-quick", deep_think_llm="chosen-deep",
        output_language="English", checkpoint=False, research_depth=4,
    ))
    assert started.status_code == 201
    snapshot = wait_terminal(client, started.json()["run_id"])
    effective = runner.received_request["config"]
    assert snapshot["llm_provider"] == provider
    assert snapshot["quick_think_llm"] == "chosen-quick"
    assert snapshot["deep_think_llm"] == "chosen-deep"
    assert snapshot["output_language"] == "Chinese"
    assert snapshot["checkpoint_enabled"] is True
    assert snapshot["research_depth"] == 4
    if provider == "openai":
        assert effective["backend_url"] is None
        assert effective["openai_reasoning_effort"] is None
    else:
        assert effective["backend_url"] == "https://default-provider.test/v1"
        assert effective["openai_reasoning_effort"] == "high"
    assert before == DEFAULT_CONFIG


@pytest.mark.parametrize("missing", ["quick_think_llm", "deep_think_llm"])
def test_provider_switch_rejects_inherited_model_ids(tmp_path, monkeypatch, missing):
    """REQ-WEB-005, INV-WEB-003: never carry a different provider's default models."""
    monkeypatch.setenv("TRADINGAGENTS_LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("TRADINGAGENTS_QUICK_THINK_LLM", "deepseek-flash")
    monkeypatch.setenv("TRADINGAGENTS_DEEP_THINK_LLM", "deepseek-flash")
    client = make_run_client(build_fixture_tree(tmp_path), runner_factory=FakeGraphRunner())
    data = body(llm_provider="openai", quick_think_llm="new-quick", deep_think_llm="new-deep")
    data.pop(missing)
    response = client.post("/api/runs", json=data)
    assert response.status_code == 422
    assert "Select both quick and deep models" in response.text
    assert client.get("/api/runs/active").json()["run_id"] is None


def test_provider_switch_can_use_its_explicit_endpoint_and_thinking(tmp_path, monkeypatch):
    """REQ-WEB-003/013, ADR-001-choice.md: explicit new-provider settings are not old defaults."""
    monkeypatch.setenv("TRADINGAGENTS_LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("TRADINGAGENTS_LLM_BACKEND_URL", "https://old-provider.test/v1")
    monkeypatch.setenv("TRADINGAGENTS_OPENAI_REASONING_EFFORT", "high")
    runner = FakeGraphRunner()
    client = make_run_client(build_fixture_tree(tmp_path), runner_factory=runner)
    response = client.post("/api/runs", json=body(
        llm_provider="openai", quick_think_llm="chosen-quick", deep_think_llm="chosen-deep",
        backend_url="https://new-provider.test/v1", openai_reasoning_effort="low",
    ))
    assert response.status_code == 201
    wait_terminal(client, response.json()["run_id"])
    assert runner.received_request["config"]["backend_url"] == "https://new-provider.test/v1"
    assert runner.received_request["config"]["openai_reasoning_effort"] == "low"
