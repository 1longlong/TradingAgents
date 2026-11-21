"""REQ-WEB-001/003/013, FR-DDT-004, ADR-001/007: real-run policy adapter contracts."""

from __future__ import annotations

import uuid
from copy import deepcopy
from dataclasses import asdict

import pytest

from test.offline.web_fixture_app import (
    FakeGraphRunner,
    build_fixture_tree,
    make_run_client,
    wait_terminal,
)
from tradingagents.debate.config import (
    DEFAULT_DEBATE_TERMINATION_CONFIG,
    resolve_debate_termination_config,
)
from tradingagents.default_config import _ENV_OVERRIDES, DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph as CoreGraph
from tradingagents_web.runtime.analysis_graph import WebAnalysisGraph
from tradingagents_web.runtime.debate_policy import PUBLIC_DEBATE_FIELDS

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in _ENV_OVERRIDES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("tradingagents_web.api.config.load_last_run", lambda: {})


def body(**overrides):
    return {
        "client_request_id": uuid.uuid4().hex,
        "ticker": "NVDA",
        "trade_date": "2026-11-01",
        "analysts": ["market"],
        **overrides,
    }


@pytest.mark.parametrize("enabled", [True, False])
def test_custom_policy_reaches_runner_snapshot_and_saved_history(tmp_path, enabled):
    runner = FakeGraphRunner()
    client = make_run_client(build_fixture_tree(tmp_path), runner_factory=runner)
    policy = {
        "enabled": enabled,
        "max_debate_rounds": 4,
        "no_new_evidence_patience": 2,
        "stance_distance_threshold": 0.5,
        "confidence_delta_threshold": 0.1,
        "max_calls": 20,
        "max_tokens": 50000,
        "max_time": 900,
        "reserved_summary_tokens": 5000,
        "reserved_summary_seconds": 100,
        "next_round_estimate_tokens": 3000,
        "next_round_estimate_seconds": 45,
    }
    before = deepcopy(DEFAULT_CONFIG)
    response = client.post(
        "/api/runs",
        json=body(research_depth=3, debate_termination=policy, max_risk_discuss_rounds=2),
    )
    assert response.status_code == 201, response.text
    snapshot = wait_terminal(client, response.json()["run_id"])
    config = runner.received_request["config"]
    assert config["max_debate_rounds"] == snapshot["research_depth"] == 4
    assert config["max_risk_discuss_rounds"] == snapshot["max_risk_discuss_rounds"] == 2
    assert snapshot["debate_termination"] == policy
    assert asdict(resolve_debate_termination_config(config)) == config["debate_termination"]
    assert before == DEFAULT_CONFIG
    detail = client.get(f"/api/history/{snapshot['artifact_id']}").json()
    assert detail["metadata"]["debate_termination"] == policy
    assert detail["metadata"]["max_risk_discuss_rounds"] == 2
    assert "evidence_manifest_field" not in str(detail["metadata"])
    assert "trace_field" not in str(snapshot)


def test_defaults_partial_overrides_and_legacy_round_mapping(tmp_path):
    runner = FakeGraphRunner()
    client = make_run_client(build_fixture_tree(tmp_path), runner_factory=runner)
    defaults = client.get("/api/config").json()["defaults"]
    assert set(defaults["debate_termination"]) == set(PUBLIC_DEBATE_FIELDS)
    assert defaults["debate_termination"]["enabled"] is True
    for request, cap, risk, patience in [
        (body(), 1, 1, 1),
        (body(research_depth=3), 3, 3, 1),
        (body(research_depth=5, debate_termination={"no_new_evidence_patience": 2}), 5, 5, 2),
        (body(debate_termination={"max_debate_rounds": 2}, max_risk_discuss_rounds=4), 2, 4, 1),
    ]:
        response = client.post("/api/runs", json=request)
        assert response.status_code == 201, response.text
        snapshot = wait_terminal(client, response.json()["run_id"])
        assert snapshot["research_depth"] == cap
        assert snapshot["max_risk_discuss_rounds"] == risk
        assert snapshot["debate_termination"]["no_new_evidence_patience"] == patience


def test_environment_locks_override_nested_and_legacy_caps(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_MAX_DEBATE_ROUNDS", "4")
    monkeypatch.setenv("TRADINGAGENTS_MAX_RISK_ROUNDS", "2")
    runner = FakeGraphRunner()
    client = make_run_client(build_fixture_tree(tmp_path), runner_factory=runner)
    projected = client.get("/api/config").json()
    assert projected["defaults"]["debate_termination"]["max_debate_rounds"] == 4
    assert projected["defaults"]["max_risk_discuss_rounds"] == 2
    assert projected["env_locks"]["max_debate_rounds"] is True
    assert projected["env_locks"]["max_risk_discuss_rounds"] is True
    response = client.post(
        "/api/runs",
        json=body(
            research_depth=5,
            debate_termination={"enabled": False, "max_debate_rounds": 3},
            max_risk_discuss_rounds=5,
        ),
    )
    assert response.status_code == 201, response.text
    snapshot = wait_terminal(client, response.json()["run_id"])
    assert snapshot["research_depth"] == 4
    assert snapshot["debate_termination"]["max_debate_rounds"] == 4
    assert snapshot["debate_termination"]["enabled"] is False
    assert snapshot["max_risk_discuss_rounds"] == 2


@pytest.mark.parametrize(
    "overrides",
    [
        {"enabled": "false"},
        {"enabled": 1},
        {"max_calls": True},
        {"max_calls": 0},
        {"max_debate_rounds": 0},
        {"no_new_evidence_patience": 0},
        {"stance_distance_threshold": 4.1},
        {"confidence_delta_threshold": 1.1},
        {"max_tokens": -1},
        {"max_time": 0},
        {"max_time": "Infinity"},
        {"reserved_summary_tokens": -1},
        {"reserved_summary_seconds": -1},
        {"next_round_estimate_tokens": -1},
        {"next_round_estimate_seconds": -1},
        {"max_tokens": 4000},
        {"max_time": 90},
        {"max_calls": None},
        {"trace_field": "arbitrary_state"},
        {"evidence_manifest_field": "arbitrary_state"},
        {"unknown": 1},
    ],
)
def test_invalid_policy_is_rejected_before_worker_start(tmp_path, overrides):
    runner = FakeGraphRunner()
    client = make_run_client(build_fixture_tree(tmp_path), runner_factory=runner)
    response = client.post("/api/runs", json=body(debate_termination=overrides))
    assert response.status_code == 422, response.text
    assert not runner.started.is_set()
    assert client.get("/api/runs/active").json() == {"run_id": None}


@pytest.mark.parametrize("risk", [True, 0, -1, 1.5, "3"])
def test_risk_rounds_require_a_positive_integer(tmp_path, risk):
    runner = FakeGraphRunner()
    client = make_run_client(build_fixture_tree(tmp_path), runner_factory=runner)
    assert client.post("/api/runs", json=body(max_risk_discuss_rounds=risk)).status_code == 422
    assert not runner.started.is_set()


def graph_for_signature(**overrides):
    graph = object.__new__(WebAnalysisGraph)
    graph.selected_analysts = ["market"]
    graph.config = {
        "max_debate_rounds": 3,
        "max_risk_discuss_rounds": 2,
        "debate_termination": overrides,
    }
    return graph


def test_default_checkpoint_identity_remains_compatible_with_core():
    graph = graph_for_signature()
    assert graph._run_signature("stock") == CoreGraph._run_signature(graph, "stock")


@pytest.mark.parametrize(
    "changes",
    [
        {"enabled": False},
        {"no_new_evidence_patience": 2},
        {"stance_distance_threshold": 0.5},
        {"confidence_delta_threshold": 0.1},
        {"max_calls": 30},
        {"max_tokens": 50000},
        {"max_time": 900},
        {"reserved_summary_tokens": 5000},
        {"reserved_summary_seconds": 100},
        {"next_round_estimate_tokens": 3000},
        {"next_round_estimate_seconds": 45},
    ],
)
def test_custom_checkpoint_policies_cannot_resume_each_other_or_defaults(changes):
    default = graph_for_signature()._run_signature("stock")
    graph = graph_for_signature(**changes)
    changed = graph._run_signature("stock")
    assert changed != default
    assert changed == graph_for_signature(**changes)._run_signature("stock")
    # ADR-012 now includes the effective debate policy in the core execution
    # digest. Preserve that identity and the existing Web-specific suffix.
    core = CoreGraph._run_signature(graph, "stock")
    assert core != CoreGraph._run_signature(graph_for_signature(), "stock")
    assert changed.startswith(core + "|web_debate_policy=")
    suffix = changed.removeprefix(core + "|web_debate_policy=")
    assert len(suffix) == 64 and all(char in "0123456789abcdef" for char in suffix)
    assert all(
        str(value) not in suffix
        for value in changes.values()
        if isinstance(value, str)
    )


def test_history_does_not_invent_missing_or_invalid_policy():
    from tradingagents_web.artifacts.index import _presentation_metadata

    assert "debate_termination" not in _presentation_metadata({})
    assert "debate_termination" not in _presentation_metadata(
        {"debate_termination": {"enabled": True}}
    )
    policy = asdict(DEFAULT_DEBATE_TERMINATION_CONFIG)
    assert "debate_termination" not in _presentation_metadata({"debate_termination": policy})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_policy_values_are_rejected_by_request_schema(value):
    from pydantic import ValidationError

    from tradingagents_web.models.requests import DebatePolicyRequest

    with pytest.raises(ValidationError):
        DebatePolicyRequest.model_validate({"max_time": value})


def test_server_defaults_are_projected_without_mutation_or_internal_selectors(
    tmp_path, monkeypatch
):
    from importlib import import_module

    config_module = import_module("tradingagents_web.api.config")
    configured = deepcopy(config_module.DEFAULT_CONFIG)
    configured["debate_termination"] = {
        "enabled": False,
        "max_debate_rounds": 4,
        "no_new_evidence_patience": 2,
    }
    configured["max_risk_discuss_rounds"] = 3
    before = deepcopy(configured)
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG", configured)
    runner = FakeGraphRunner()
    client = make_run_client(build_fixture_tree(tmp_path), runner_factory=runner)
    defaults = client.get("/api/config").json()["defaults"]
    assert defaults["research_depth"] == 4
    assert defaults["max_risk_discuss_rounds"] == 3
    assert defaults["debate_termination"]["no_new_evidence_patience"] == 2
    response = client.post("/api/runs", json=body())
    assert response.status_code == 201, response.text
    snapshot = wait_terminal(client, response.json()["run_id"])
    assert snapshot["research_depth"] == 4
    assert snapshot["max_risk_discuss_rounds"] == 3
    assert configured == before


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_http_nonfinite_numbers_do_not_start_worker_or_break_error_serialization(tmp_path, value):
    import json

    runner = FakeGraphRunner()
    client = make_run_client(build_fixture_tree(tmp_path), runner_factory=runner)
    response = client.post(
        "/api/runs",
        content=json.dumps(body(debate_termination={"max_time": value})),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["category"] == "validation"
    assert not runner.started.is_set()


def test_rejected_nested_fields_do_not_echo_values(tmp_path):
    client = make_run_client(build_fixture_tree(tmp_path), runner_factory=FakeGraphRunner())
    value = "never-echo-client-credential"
    response = client.post("/api/runs", json=body(debate_termination={"api_key": value}))
    assert response.status_code == 422
    assert value not in response.text
