"""Iteration-2 configuration projection contracts.

Covers REQ-WEB-001 (backend portion) and REQ-WEB-013. These tests fail as
EXPECTED-UNIMPLEMENTED until the run control plane exists.
"""

from __future__ import annotations

import json

import pytest

from test.offline.web_fixture_app import (
    SECRET,
    build_fixture_tree,
    make_run_client,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    return make_run_client(build_fixture_tree(tmp_path))


def test_config_exposes_defaults_and_providers_without_server_paths(client):
    response = client.get("/api/config")
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["providers"]
    assert payload["defaults"]["llm_provider"]
    assert payload["defaults"]["quick_think_llm"]
    assert payload["defaults"]["deep_think_llm"]
    text = json.dumps(payload)
    for forbidden in ("results_dir", "data_cache_dir", "memory_log_path", "project_dir"):
        assert forbidden not in payload
        assert forbidden not in text


def test_key_status_is_reported_without_returning_the_value(client):
    response = client.get("/api/config")
    assert response.status_code == 200, response.text
    assert SECRET not in response.text
    status = response.json()["key_status"]
    assert status["openai"] == "configured"


def test_missing_key_is_not_configured_but_does_not_break_config(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = make_run_client(build_fixture_tree(tmp_path))
    response = client.get("/api/config")
    assert response.status_code == 200, response.text
    assert response.json()["key_status"]["openai"] == "not_configured"
    assert SECRET not in response.text


def test_environment_locked_values_are_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_OUTPUT_LANGUAGE", "Chinese")
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    client = make_run_client(build_fixture_tree(tmp_path))
    response = client.get("/api/config")
    assert response.status_code == 200, response.text
    assert response.json()["env_locks"]["output_language"] is True


def test_models_endpoint_returns_options_for_provider_and_mode(client):
    response = client.get(
        "/api/config/models", params={"provider": "openai", "mode": "quick"}
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["models"]
    assert any(item.get("value") == "custom" for item in payload["models"])


def test_unknown_provider_or_mode_is_rejected(client):
    bad_provider = client.get(
        "/api/config/models", params={"provider": "not-a-provider", "mode": "quick"}
    )
    assert bad_provider.status_code in {400, 404, 422}
    bad_mode = client.get(
        "/api/config/models", params={"provider": "openai", "mode": "not-a-mode"}
    )
    assert bad_mode.status_code in {400, 404, 422}
