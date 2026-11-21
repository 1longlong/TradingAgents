"""REQ-WEB-001/002/006/007/013; ADR-001/003: real TUI parity contracts."""

from __future__ import annotations

import json
import uuid

import pytest
import requests

from test.offline.web_fixture_app import build_fixture_tree, make_run_client
from tradingagents_web.runtime.graph_runner import LiveStats
from tradingagents_web.runtime.model_catalog import OpenRouterCatalog
from tradingagents_web.runtime.projector import StreamProjector

pytestmark = pytest.mark.unit


def test_observed_roles_repeated_turns_reports_and_exact_analyst_time(monkeypatch):
    events = []
    projector = StreamProjector(["market"])
    stats = LiveStats(events.append, 0, projector)
    clock = iter([10.0, 12.0, 15.0])
    monkeypatch.setattr("tradingagents.graph.analyst_execution.monotonic", lambda: next(clock))
    first = uuid.uuid4()
    stats.on_chain_start(
        None, {}, run_id=first, name="Market Analyst", metadata={"langgraph_node": "Market Analyst"}
    )
    stats.on_chain_end({"messages": ["tool request"]}, run_id=first)
    assert not stats.wall_times()
    assert projector.counts()["reports_completed"] == 0
    second = uuid.uuid4()
    stats.on_chain_start(
        None,
        {},
        run_id=second,
        name="Market Analyst",
        metadata={"langgraph_node": "Market Analyst"},
    )
    stats.on_chain_end({"market_report": "report"}, run_id=second)
    assert stats.wall_times() == {"Market Analyst": 5.0}
    projector.project({"market_report": "report"})
    assert projector.counts()["reports_completed"] == 1
    assert projector.counts()["reports_total"] == 4
    for _ in range(2):
        turn = uuid.uuid4()
        stats.on_chain_start(
            None,
            {},
            run_id=turn,
            name="Bull Researcher",
            metadata={"langgraph_node": "Bull Researcher"},
        )
        assert projector._statuses["Bull Researcher"] == "in_progress"
        stats.on_chain_end({}, run_id=turn)
        assert projector._statuses["Bull Researcher"] == "completed"
    assert projector.counts()["reports_completed"] == 1
    nested = uuid.uuid4()
    stats.on_chain_start(
        None, {}, run_id=nested, name="prompt", metadata={"langgraph_node": "Portfolio Manager"}
    )
    assert nested not in stats._nodes


def test_recovered_or_partial_state_does_not_invent_timing_or_absent_participation():
    projector = StreamProjector(["market"])
    stats = LiveStats(lambda event: None, 0, projector)
    projector.project(
        {"market_report": "restored", "investment_debate_state": {"bull_history": "only bull"}}
    )
    assert stats.wall_times() == {}
    assert projector._statuses["Bear Researcher"] == "pending"
    assert projector._statuses["Portfolio Manager"] == "pending"
    assert projector.counts()["reports_completed"] == 1
    projector.project(
        {
            "market_report": "restored",
            "investment_debate_state": {"bull_history": "only bull", "judge_decision": "summary"},
        }
    )
    assert projector.counts()["reports_completed"] == 2
    assert projector._statuses["Bear Researcher"] == "pending"


def response(payload, status=200):
    class Reply:
        status_code = status

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def iter_content(self, chunk_size):
            yield payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    return Reply()


def test_openrouter_discovery_shortlist_cache_refresh_and_no_other_provider_io(
    tmp_path, monkeypatch
):
    calls = []
    now = [0.0]
    models = [{"id": f"openai/model-{n}", "name": f"Model {n}", "created": n} for n in range(7)]
    models += [
        {"id": "niche/newest", "created": 200},
        {"id": "~alias", "created": 300},
        {"id": "openai/image", "created": 300, "architecture": {"output_modalities": ["image"]}},
        {"id": "openai/model-6", "created": 5},
        {"id": None},
        None,
    ]

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return response({"data": models})

    monkeypatch.setattr("tradingagents_web.runtime.model_catalog.requests.get", get)
    catalog = OpenRouterCatalog(clock=lambda: now[0])
    client = make_run_client(build_fixture_tree(tmp_path))
    client.app.state.openrouter_catalog = catalog

    def query(provider="openrouter", mode="quick", refresh=False):
        return client.get(
            "/api/config/models", params={"provider": provider, "mode": mode, "refresh": refresh}
        )

    assert query().json()["models"][0]["value"] == "openai/model-6"
    assert len(query(mode="deep").json()["models"]) == 6
    query(refresh=True)
    assert len(calls) == 1
    now[0] = 3
    query(refresh=True)
    assert len(calls) == 2
    now[0] = 304
    query()
    assert len(calls) == 3
    assert query(provider="openai").status_code == 200
    assert query(mode="invalid").status_code == 422
    assert len(calls) == 3
    assert calls[0][0] == "https://openrouter.ai/api/v1/models"
    options = calls[0][1]
    assert options["timeout"] == 10
    assert options["stream"] is True and options["allow_redirects"] is False
    prepared = requests.Request("GET", calls[0][0], auth=options["auth"]).prepare()
    assert "Authorization" not in prepared.headers


@pytest.mark.parametrize(
    "payload,status",
    [
        ({"data": []}, 200),
        ({"wrong": []}, 200),
        (["invalid"], 200),
        (b"not json secret-value", 200),
        (b"x" * 2_000_001, 200),
        ({"data": [{"id": "openai/model"}]}, 429),
        ({"data": [{"id": "openai/model"}]}, 302),
    ],
)
def test_discovery_invalid_or_failed_response_keeps_manual_ids_without_echo(
    monkeypatch, payload, status
):
    monkeypatch.setattr(
        "tradingagents_web.runtime.model_catalog.requests.get",
        lambda *args, **kwargs: response(payload, status),
    )
    result = OpenRouterCatalog().models()
    assert result["models"] == [{"value": "custom", "label": "Custom model ID"}]
    assert result["source"] == "custom"
    assert "secret-value" not in str(result)
    assert result["warning"]


def test_failed_refresh_keeps_last_good_models_and_throttles_repeated_failures(monkeypatch):
    now = [0.0]
    catalog = OpenRouterCatalog(clock=lambda: now[0])
    monkeypatch.setattr(catalog, "_fetch", lambda: [{"value": "openai/kept", "label": "Kept"}])
    catalog.models()
    calls = []

    def fail():
        calls.append(True)
        raise requests.Timeout("secret-value")

    monkeypatch.setattr(catalog, "_fetch", fail)
    now[0] = 3
    result = catalog.models(refresh=True)
    assert result["source"] == "cache"
    assert result["models"][0]["value"] == "openai/kept"
    assert "secret-value" not in str(result)
    catalog.models(refresh=True)
    assert len(calls) == 1


def test_terminal_snapshot_retains_timing_when_completion_has_no_timing_payload():
    from tradingagents_web.runtime.coordinator import RunCoordinator, RunRecord

    coordinator = RunCoordinator(None, None)
    record = RunRecord("r_times", {})
    coordinator._emit(
        record, {"type": "analyst.timing", "payload": {"wall_times": {"Market Analyst": 1.25}}}
    )
    coordinator._emit(record, {"type": "run.completed", "payload": {"signal": "Buy"}})
    assert record.to_snapshot()["wall_times"] == {"Market Analyst": 1.25}
