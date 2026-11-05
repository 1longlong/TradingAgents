"""WebUI announcement endpoint contracts.

Covers REQ-WEB-012. Offline tests mock the upstream announcement fetch; no
network call is made. The blocking acknowledgement itself is a frontend
behaviour and is covered by ``announcements.test.tsx``; this suite verifies the
server forwards ``require_attention`` and never fails the request.
"""

from __future__ import annotations

import json

import pytest

from test.offline.web_fixture_app import (
    SECRET,
    build_fixture_tree,
    make_iteration3_client,
    require_iteration3_modules,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def client(tmp_path, monkeypatch):
    require_iteration3_modules()
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    return make_iteration3_client(build_fixture_tree(tmp_path))


def _mock(monkeypatch, result=None, error=None, counter=None):
    import tradingagents_web.api.announcements as module

    def fake(*args, **kwargs):
        if counter is not None:
            counter.append(1)
        if error is not None:
            raise error
        return result

    monkeypatch.setattr(module, "fetch_announcements", fake)


def test_announcements_are_returned(client, monkeypatch):
    _mock(
        monkeypatch,
        result={"announcements": ["Scheduled maintenance"], "require_attention": False},
    )
    response = client.get("/api/announcements")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["announcements"] == ["Scheduled maintenance"]
    assert payload["require_attention"] is False


def test_failure_uses_safe_fallback(client, monkeypatch):
    _mock(monkeypatch, error=RuntimeError("upstream unavailable"))
    response = client.get("/api/announcements")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["announcements"]
    assert payload["require_attention"] is False
    text = json.dumps(payload).lower()
    assert "http" in text or "tauric" in text or "github" in text


def test_malformed_upstream_payload_uses_safe_fallback(client, monkeypatch):
    _mock(monkeypatch, result={"announcements": "not-a-list"})
    response = client.get("/api/announcements")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert isinstance(payload["announcements"], list)
    assert payload["require_attention"] is False


def test_require_attention_blocks_acknowledgement(client, monkeypatch):
    _mock(
        monkeypatch,
        result={"announcements": ["Read this"], "require_attention": True},
    )
    response = client.get("/api/announcements")
    assert response.status_code == 200, response.text
    payload = response.json()
    # The server keeps the flag; the UI must block until acknowledgement.
    assert payload["require_attention"] is True
    assert payload["announcements"] == ["Read this"]


def test_announcements_are_cached(client, monkeypatch):
    counter: list[int] = []
    _mock(
        monkeypatch,
        result={"announcements": ["cached"], "require_attention": False},
        counter=counter,
    )
    assert client.get("/api/announcements").status_code == 200
    assert client.get("/api/announcements").status_code == 200
    assert len(counter) == 1


def test_announcement_response_contains_no_secret_or_server_path(client, monkeypatch):
    _mock(
        monkeypatch,
        result={"announcements": ["hello"], "require_attention": False},
    )
    response = client.get("/api/announcements")
    assert SECRET not in response.text
    assert "results_dir" not in response.text
    assert "/Users/" not in response.text


def test_announcement_text_remains_untrusted_data(client, monkeypatch):
    _mock(
        monkeypatch,
        result={
            "announcements": ["<script>alert(1)</script>"],
            "require_attention": False,
        },
    )
    response = client.get("/api/announcements")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    assert isinstance(response.json()["announcements"], list)
