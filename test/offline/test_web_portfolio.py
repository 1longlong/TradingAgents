"""Portfolio validation and three-state semantics.

Covers REQ-WEB-004 and the portfolio half of REQ-WEB-028.
"""

from __future__ import annotations

import json

import pytest

from test.offline.web_fixture_app import (
    FakeGraphRunner,
    build_fixture_tree,
    make_run_client,
    wait_terminal,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy-secret-1234567890")
    return make_run_client(build_fixture_tree(tmp_path), runner_factory=FakeGraphRunner)


def _validate(client, text):
    return client.post("/api/portfolio/validate", json={"json": text})


def test_paste_and_upload_use_the_same_json_contract(client):
    text = json.dumps(
        {
            "cash": 1000.0,
            "currency": "USD",
            "positions": [{"ticker": "NVDA", "quantity": 2, "average_price": 100.0}],
        }
    )
    first = _validate(client, text)
    second = _validate(client, text)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["fingerprint"] == second.json()["fingerprint"]
    assert first.json()["valid"] is True


def test_empty_book_and_populated_book_have_different_fingerprints(client):
    empty = _validate(client, json.dumps({"cash": 0, "positions": []}))
    populated = _validate(
        client,
        json.dumps(
            {
                "cash": 100,
                "positions": [{"ticker": "AAPL", "quantity": 1}],
            }
        ),
    )
    assert empty.status_code == 200, empty.text
    assert populated.status_code == 200, populated.text
    assert empty.json()["fingerprint"] != populated.json()["fingerprint"]


def test_absent_empty_and_present_are_distinct_at_run_level(client):
    absent = client.post(
        "/api/runs",
        json={
            "client_request_id": "portfolio-absent",
            "ticker": "NVDA",
            "trade_date": "2026-11-01",
            "analysts": ["market"],
        },
    )
    assert absent.status_code == 201, absent.text
    assert absent.json()["portfolio_fingerprint"] is None
    wait_terminal(client, absent.json()["run_id"])

    empty = client.post(
        "/api/runs",
        json={
            "client_request_id": "portfolio-empty",
            "ticker": "NVDA",
            "trade_date": "2026-11-01",
            "analysts": ["market"],
            "portfolio_json": json.dumps({"cash": 0, "positions": []}),
        },
    )
    assert empty.status_code == 201, empty.text
    assert empty.json()["portfolio_fingerprint"]
    wait_terminal(client, empty.json()["run_id"])

    present = client.post(
        "/api/runs",
        json={
            "client_request_id": "portfolio-present",
            "ticker": "NVDA",
            "trade_date": "2026-11-01",
            "analysts": ["market"],
            "portfolio_json": json.dumps(
                {"cash": 10, "positions": [{"ticker": "NVDA", "quantity": 1}]}
            ),
        },
    )
    assert present.status_code == 201, present.text
    assert present.json()["portfolio_fingerprint"] != empty.json()["portfolio_fingerprint"]


def test_invalid_portfolio_never_starts_a_run(client):
    response = client.post(
        "/api/runs",
        json={
            "client_request_id": "portfolio-invalid",
            "ticker": "NVDA",
            "trade_date": "2026-11-01",
            "analysts": ["market"],
            "portfolio_json": "{not json",
        },
    )
    assert response.status_code in {400, 422}, response.text
    assert client.get("/api/runs/active").json().get("run_id") is None


@pytest.mark.parametrize(
    "payload",
    [
        "{}",
        "[]",
        "null",
        '{"positions": "not-a-list"}',
        '{"positions": [{"ticker": "../etc/passwd", "quantity": 1}]}',
    ],
)
def test_malformed_portfolio_payloads_are_rejected(client, payload):
    response = _validate(client, payload)
    assert response.status_code in {400, 422}, response.text
